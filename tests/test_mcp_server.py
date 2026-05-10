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


def _patch_replay_render(monkeypatch, *, returns: dict | None = None, raises: BaseException | None = None):
    """共享 replay_render_to_file monkeypatch helper: 返 dict 或抛指定异常."""
    def _stub(task_id, out_dir=None, db_path=None):
        if raises is not None:
            raise raises
        return returns

    monkeypatch.setattr("web_agent.mcp_server.replay_render_to_file", _stub)


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


# V0.18.0: ctx 注入时 safety_approval_cb 应 wire 通到 cli_run_task

async def test_web_agent_run_passes_elicitation_callback(monkeypatch, reset_run_lock, fake_chrome_alive):
    """V0.18.0 elicitation: ctx 可用 → web_agent_run 应构造 callback 透传给 cli_run_task."""
    captured = {}

    async def fake_run_task(goal, **kw):
        captured["safety_approval_cb"] = kw.get("safety_approval_cb")
        return "OK"

    monkeypatch.setattr("web_agent.mcp_server.cli_run_task", fake_run_task)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("web_agent_run", {"goal": "test"})
        assert not result.isError

    cb = captured["safety_approval_cb"]
    assert cb is not None, "ctx 可用时应注入 callback"
    assert callable(cb), f"callback 应可调用, got {cb!r}"


# V0.27.4: 缺 API key 时 elicit retry — accept 成功 + decline reraise

async def test_web_agent_run_elicit_missing_secret_retry_success(
    monkeypatch, reset_run_lock, fake_chrome_alive,
):
    """V0.27.4: cli_run_task 第一次抛 MissingSecretError → ctx.elicit accept → retry 成功 + secret_store 注入."""
    from unittest.mock import AsyncMock, MagicMock

    from mcp.server.elicitation import AcceptedElicitation

    from web_agent.vault import MissingSecretError

    call_count = 0
    captured: dict[str, object] = {}

    async def fake_run_task(goal, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise MissingSecretError("ANTHROPIC_API_KEY")
        captured["secret_store"] = kw.get("secret_store")
        return "OK retried"

    monkeypatch.setattr("web_agent.mcp_server.cli_run_task", fake_run_task)

    elicited = mcp_mod.SecretInput(value="sk-ant-elicited")
    accepted = AcceptedElicitation(action="accept", data=elicited)

    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    ctx.elicit = AsyncMock(return_value=accepted)

    result = await mcp_mod.web_agent_run(goal="test", url="", max_steps=5, ctx=ctx)
    assert result == "OK retried"
    assert call_count == 2, f"应 retry 一次, 实 {call_count} 次"
    store = captured.get("secret_store")
    assert store is not None, "retry 时应注入 InMemorySecretStore"
    assert store.get("ANTHROPIC_API_KEY") == "sk-ant-elicited"  # type: ignore[union-attr]
    ctx.elicit.assert_called_once()


async def test_web_agent_run_capability_hint_routes_to_provider(
    monkeypatch, reset_run_lock, fake_chrome_alive,
):
    """V0.27.5: capability_hint param → routing select_provider → cli_run_task 收 provider.

    Kimi 强项 'multi-tab' → 'openai'; 验真透传到 cli_run_task. 同时验 P1 修: provider 计算
    在 try/except 之外, retry 时 capability_hint 选出的 provider 不丢.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    captured: dict[str, object] = {}

    async def fake_run_task(goal, **kw):
        captured["provider"] = kw.get("provider")
        return "OK"

    monkeypatch.setattr("web_agent.mcp_server.cli_run_task", fake_run_task)

    # 直接 await 函数 (非真 mcp 协议层) 简化集成测
    result = await mcp_mod.web_agent_run(
        goal="test", url="", max_steps=5, capability_hint="multi-tab", ctx=None,
    )
    assert result == "OK"
    assert captured["provider"] == "openai", \
        f"capability_hint=multi-tab → routing 应选 openai, 实 {captured['provider']!r}"


async def test_web_agent_run_capability_hint_none_keeps_old_path(
    monkeypatch, reset_run_lock, fake_chrome_alive,
):
    """V0.27.5: capability_hint=None → provider=None (老路径, env 决定)."""
    captured: dict[str, object] = {}

    async def fake_run_task(goal, **kw):
        captured["provider"] = kw.get("provider")
        return "OK"

    monkeypatch.setattr("web_agent.mcp_server.cli_run_task", fake_run_task)

    result = await mcp_mod.web_agent_run(goal="test", capability_hint=None, ctx=None)
    assert result == "OK"
    assert captured["provider"] is None  # 不接 routing → cli_run_task 内部决定


async def test_web_agent_run_elicit_missing_secret_decline_reraise(
    monkeypatch, reset_run_lock, fake_chrome_alive,
):
    """V0.27.4: 用户 decline (返 empty value) → reraise MissingSecretError 让 client 看 isError."""
    from unittest.mock import AsyncMock, MagicMock

    from mcp.server.elicitation import AcceptedElicitation

    from web_agent.vault import MissingSecretError

    async def fake_run_task(goal, **kw):
        raise MissingSecretError("OPENAI_API_KEY")

    monkeypatch.setattr("web_agent.mcp_server.cli_run_task", fake_run_task)

    declined = mcp_mod.SecretInput(value="")  # 用户 accept elicitation 但留空值 = decline
    accepted_empty = AcceptedElicitation(action="accept", data=declined)

    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    ctx.elicit = AsyncMock(return_value=accepted_empty)

    with pytest.raises(MissingSecretError) as exc_info:
        await mcp_mod.web_agent_run(goal="test", ctx=ctx)
    assert exc_info.value.key == "OPENAI_API_KEY"


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

    _patch_replay_render(monkeypatch, returns={
        "task_id": "fake-task",
        "html_path": str(fake_html.resolve()),
        "step_count": 3,
        "result": "OK",
    })

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
    _patch_replay_render(monkeypatch, raises=SystemExit("replay: db 不存在: data/trace.db"))

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


# ---------- V0.16.6 Resources (4 case) ----------

async def test_list_resources_includes_two_templates(reset_run_lock):
    """V0.16.6: list_resource_templates 返 webagent://replay/{task_id} + memory/{domain}."""
    async with create_connected_server_and_client_session(mcp) as session:
        templates = await session.list_resource_templates()
        uris = {str(t.uriTemplate) for t in templates.resourceTemplates}
        assert any("webagent://replay/" in u for u in uris), uris
        assert any("webagent://memory/" in u for u in uris), uris


async def test_read_replay_resource_returns_html(monkeypatch, reset_run_lock, tmp_path):
    """V0.16.6: read webagent://replay/{task_id} 返 HTML 文本 (mime text/html)."""
    fake_html = tmp_path / "task-x.html"
    fake_html.write_text("<html><body>fake replay</body></html>", encoding="utf-8")

    _patch_replay_render(monkeypatch, returns={
        "task_id": "task-x", "html_path": str(fake_html.resolve()), "step_count": 1, "result": "OK",
    })

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.read_resource("webagent://replay/task-x")
        assert len(result.contents) == 1
        content = result.contents[0]
        assert "fake replay" in content.text
        assert content.mimeType == "text/html"


async def test_read_memory_resource_returns_json_list(monkeypatch, reset_run_lock):
    """V0.16.6: read webagent://memory/{domain} 返 JSON list (mime application/json)."""
    from web_agent.memory import MemoryEntry

    fake_entries = [
        MemoryEntry(ts=1714850400.0, domain="example.com", goal="g", result="r", success=True),
    ]
    monkeypatch.setattr("web_agent.mcp_server.recall_by_domain", lambda db, d, limit=5: fake_entries)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.read_resource("webagent://memory/example.com")
        assert len(result.contents) == 1
        content = result.contents[0]
        parsed = json.loads(content.text)
        assert len(parsed) == 1
        assert parsed[0]["goal"] == "g"
        assert parsed[0]["success"] is True


async def test_read_replay_resource_non_existent_errors(monkeypatch, reset_run_lock):
    """V0.16.6: 不存在 task_id → resource read RuntimeError (SystemExit 转译)."""
    _patch_replay_render(monkeypatch, raises=SystemExit("replay: db 不存在"))

    async with create_connected_server_and_client_session(mcp) as session:
        # FastMCP wraps resource exceptions; pytest.raises catches the propagated McpError
        from mcp.shared.exceptions import McpError
        with pytest.raises(McpError):
            await session.read_resource("webagent://replay/nonexistent")


# ---------- Case 11 (V0.16.4): progress notification 真接通 ----------

async def test_web_agent_run_progress_callback_invoked(monkeypatch, reset_run_lock, fake_chrome_alive):
    """V0.16.4: web_agent_run 透 ctx.report_progress 给 cli.run_task → progress 事件经
    MCP 协议层路由到 client.call_tool(progress_callback=fn) 注入的 fn."""
    received: list[tuple[float, float | None, str | None]] = []

    async def collect_progress(progress, total, message):
        received.append((progress, total, message))

    async def fake_run_task(goal, start_url=None, max_steps=20, progress_cb=None, **kw):
        # 模拟 loop 主循环每步调 progress_cb
        if progress_cb is not None:
            await progress_cb(0, max_steps, f"step 1/{max_steps}")
            await progress_cb(1, max_steps, f"step 2/{max_steps}")
        return f"OK: {goal}"

    monkeypatch.setattr("web_agent.mcp_server.cli_run_task", fake_run_task)

    async with create_connected_server_and_client_session(mcp) as session:
        await session.call_tool(
            "web_agent_run",
            {"goal": "x", "max_steps": 5},
            progress_callback=collect_progress,
        )

    assert len(received) == 2, f"应收到 2 个 progress 通知, 实收 {len(received)}: {received}"
    assert received[0][0] == 0 and received[0][1] == 5
    assert received[1][0] == 1
    assert "step 2/5" in received[1][2]


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
