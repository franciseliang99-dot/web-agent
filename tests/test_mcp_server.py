"""V0.16.1 MCP server 测试: 用 mcp.shared.memory.create_connected_server_and_client_session
建 in-memory client+server 跑真协议层, monkeypatch web_agent.cli.run_task / urllib 等外部依赖。

10 case 覆盖:
1. list_tools 返 3 个 tool 名 ✓
2. web_agent_run forwards args verbatim
3. web_agent_run with bad CDP url → chrome_not_running error
4. web_agent_run concurrent serialized via _RUN_LOCK
5. web_agent_get_replay returns dict with html_path
6. web_agent_get_replay non-existent task_id → error
7. web_agent_query_memory empty domain → []
8. web_agent_query_memory normalize URL form
9. web_agent_query_memory with seeded entries → list[dict]
10. main() basicConfig stderr (smoke) — 不真 mcp.run() 仅验 logging 配置
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time

import pytest

from mcp.shared.memory import create_connected_server_and_client_session

import web_agent.mcp_server as mcp_mod
from web_agent.mcp_server import mcp


@pytest.fixture
def reset_run_lock():
    """每 test 重置 _RUN_LOCK 防 case 间状态泄漏."""
    old_lock = mcp_mod._RUN_LOCK
    mcp_mod._RUN_LOCK = asyncio.Lock()
    yield
    mcp_mod._RUN_LOCK = old_lock


@pytest.fixture
def fake_chrome_alive(monkeypatch):
    """让 _check_chrome_alive 永真, 测试不依赖真 9222."""
    monkeypatch.setattr(
        "web_agent.mcp_server._check_chrome_alive",
        lambda cdp_url, timeout=2.0: None,
    )


@pytest.fixture
def fake_chrome_dead(monkeypatch):
    """让 _check_chrome_alive 永抛 RuntimeError chrome_not_running."""
    def _boom(cdp_url, timeout=2.0):
        raise RuntimeError(f"chrome_not_running: {cdp_url} 无响应")

    monkeypatch.setattr("web_agent.mcp_server._check_chrome_alive", _boom)


# ---------- Case 1: list_tools ----------

async def test_list_tools_returns_three(reset_run_lock):
    async with create_connected_server_and_client_session(mcp) as session:
        resp = await session.list_tools()
        names = {t.name for t in resp.tools}
        assert names == {"web_agent_run", "web_agent_get_replay", "web_agent_query_memory"}


# ---------- Case 2: web_agent_run forwards args ----------

async def test_web_agent_run_forwards_args(monkeypatch, reset_run_lock, fake_chrome_alive):
    captured = {}

    async def fake_run_task(goal, start_url=None, max_steps=20, **kw):
        captured.update({"goal": goal, "start_url": start_url, "max_steps": max_steps})
        return f"OK: {goal}"

    monkeypatch.setattr("web_agent.mcp_server.cli_run_task", fake_run_task)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "web_agent_run",
            {"goal": "搜苹果价格", "url": "https://example.com", "max_steps": 5},
        )
        assert not result.isError
        assert captured == {"goal": "搜苹果价格", "start_url": "https://example.com", "max_steps": 5}


# ---------- Case 3: chrome_not_running ----------

async def test_web_agent_run_chrome_not_running(reset_run_lock, fake_chrome_dead):
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("web_agent_run", {"goal": "x"})
        assert result.isError
        text = " ".join(c.text for c in result.content if hasattr(c, "text"))
        assert "chrome_not_running" in text


# ---------- Case 4: concurrent serialized ----------

async def test_web_agent_run_serialized_via_lock(monkeypatch, reset_run_lock, fake_chrome_alive):
    order = []

    async def fake_run_task(goal, start_url=None, max_steps=20, **kw):
        order.append(("start", goal, time.monotonic()))
        await asyncio.sleep(0.1)  # 模拟跑任务
        order.append(("end", goal, time.monotonic()))
        return f"done {goal}"

    monkeypatch.setattr("web_agent.mcp_server.cli_run_task", fake_run_task)

    async with create_connected_server_and_client_session(mcp) as session:
        # 并发 call 2 个 web_agent_run
        await asyncio.gather(
            session.call_tool("web_agent_run", {"goal": "A"}),
            session.call_tool("web_agent_run", {"goal": "B"}),
        )

    # 锁串行化: 第一个 end 必须在第二个 start 之前 (无重叠)
    starts = [t for ev, _, t in order if ev == "start"]
    ends = [t for ev, _, t in order if ev == "end"]
    assert len(starts) == 2 and len(ends) == 2
    # 排序后第 1 个 end 应早于第 2 个 start
    assert sorted(ends)[0] < sorted(starts)[1], f"task overlapped: {order!r}"


# ---------- Case 5: get_replay returns dict ----------

async def test_get_replay_returns_dict(monkeypatch, reset_run_lock, tmp_path):
    fake_html = tmp_path / "fake-task.html"
    fake_html.write_text("<html>fake</html>")

    def fake_render(task_id, out_dir=None, db_path=None):
        return {
            "task_id": "fake-task",
            "html_path": str(fake_html.resolve()),
            "step_count": 3,
            "result": "OK",
        }

    monkeypatch.setattr("web_agent.mcp_server.replay_render_to_file", fake_render)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("web_agent_get_replay", {"task_id": "fake-task"})
        assert not result.isError
        # FastMCP 自动 dict→JSON content 序列化, 解回 dict 比较
        text = " ".join(c.text for c in result.content if hasattr(c, "text"))
        parsed = json.loads(text)
        assert parsed["task_id"] == "fake-task"
        assert parsed["step_count"] == 3
        assert "fake-task.html" in parsed["html_path"]


# ---------- Case 6: get_replay non-existent → error ----------

async def test_get_replay_non_existent_errors(monkeypatch, reset_run_lock):
    def boom(task_id, out_dir=None, db_path=None):
        raise SystemExit("replay: db 不存在: data/trace.db")

    monkeypatch.setattr("web_agent.mcp_server.replay_render_to_file", boom)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("web_agent_get_replay", {"task_id": "nonexistent"})
        assert result.isError


# ---------- Case 7: query_memory empty → [] ----------

async def test_query_memory_empty_domain_returns_empty(reset_run_lock):
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("web_agent_query_memory", {"domain": ""})
        assert not result.isError
        # FastMCP list-return → structuredContent={'result': [...]}
        assert result.structuredContent == {"result": []}


# ---------- Case 8: query_memory URL form normalize ----------

async def test_query_memory_normalizes_url_to_domain(monkeypatch, reset_run_lock):
    captured = {}

    def fake_recall(db, domain, limit=5):
        captured["domain"] = domain
        return []

    monkeypatch.setattr("web_agent.mcp_server.recall_by_domain", fake_recall)

    async with create_connected_server_and_client_session(mcp) as session:
        await session.call_tool(
            "web_agent_query_memory",
            {"domain": "https://github.com/x/y", "limit": 3},
        )
    # extract_domain("https://github.com/x/y") → "github.com"
    assert captured["domain"] == "github.com"


# ---------- Case 9: query_memory with seeded entries ----------

async def test_query_memory_returns_serialized_entries(monkeypatch, reset_run_lock):
    from web_agent.memory import MemoryEntry

    fake_entries = [
        MemoryEntry(ts=1714850400.0, domain="github.com", goal="g1", result="r1", success=True),
        MemoryEntry(ts=1714846800.0, domain="github.com", goal="g2", result="r2", success=False),
    ]
    monkeypatch.setattr("web_agent.mcp_server.recall_by_domain", lambda db, d, limit=5: fake_entries)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "web_agent_query_memory",
            {"domain": "github.com", "limit": 2},
        )
        parsed = result.structuredContent["result"]
        assert len(parsed) == 2
        assert parsed[0]["goal"] == "g1"
        assert parsed[0]["success"] is True
        assert parsed[1]["success"] is False


# ---------- Case 10: main() basicConfig stderr smoke ----------

def test_main_configures_logging_stderr(monkeypatch):
    """main() 必须在 mcp.run() 前 logging.basicConfig stream=stderr 防 stdout 污染."""
    monkeypatch.setattr(mcp_mod.mcp, "run", lambda: None)
    # monkeypatch 自动 teardown restore root.handlers, 防本 test 污染后续 test logging
    monkeypatch.setattr(logging.getLogger(), "handlers", [])

    mcp_mod.main()

    root_handlers = logging.getLogger().handlers
    stream_handlers = [h for h in root_handlers if isinstance(h, logging.StreamHandler)]
    assert any(h.stream is sys.stderr for h in stream_handlers), \
        f"main() 应配 stderr handler, got {[h.stream for h in stream_handlers]}"
