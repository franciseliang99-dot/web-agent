"""cli.py 单测 (audit gap 填补 — V0.12.4 trace 之后的剩余测试盲区)。

覆盖 argparse 解析 + main() 打印 + run_task signature + env precedence (cli arg > env > default)。
所有 IO 边界 (playwright/browser/llm/run_react_loop) 用 monkeypatch 拦掉, 不真起 chrome / 调 LLM。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from web_agent.cli import main, run_task


# ---------- 基础 signature ----------

def test_run_task_is_coroutine_function():
    """与 demos_smoke 同档保护: 未来 run_task 改 sync 会立刻挂掉。"""
    assert asyncio.iscoroutinefunction(run_task)


# ---------- argparse 测 (用 monkeypatch run_task 收集 kwargs) ----------

class _RunTaskRecorder:
    """patch web_agent.cli.run_task 用; 捕获 kwargs, 返 fake 结果。"""

    def __init__(self, ret: str = "FAKE_RESULT") -> None:
        self.calls: list[dict] = []
        self.ret = ret

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.ret


def test_main_parses_goal_only(monkeypatch, capsys):
    rec = _RunTaskRecorder("OK")
    monkeypatch.setattr("web_agent.cli.run_task", rec)
    monkeypatch.setattr("sys.argv", ["web-agent", "do something"])

    main()

    assert len(rec.calls) == 1
    kw = rec.calls[0]
    assert kw["goal"] == "do something"
    assert kw["start_url"] is None
    assert kw["max_steps"] is None
    assert kw["max_wallclock_s"] is None
    assert kw["cdp_url"] is None
    assert kw["provider"] is None
    assert kw["model"] is None


def test_main_parses_all_flags(monkeypatch):
    rec = _RunTaskRecorder("OK")
    monkeypatch.setattr("web_agent.cli.run_task", rec)
    monkeypatch.setattr("sys.argv", [
        "web-agent", "搜索任务",
        "--url", "https://example.com",
        "--max-steps", "5",
        "--max-wallclock-s", "12.5",
        "--cdp-url", "http://x:1",
        "--provider", "openai",
        "--model", "gpt-4o",
    ])

    main()

    kw = rec.calls[0]
    assert kw["goal"] == "搜索任务"
    assert kw["start_url"] == "https://example.com"
    assert kw["max_steps"] == 5
    assert kw["max_wallclock_s"] == 12.5
    assert kw["cdp_url"] == "http://x:1"
    assert kw["provider"] == "openai"
    assert kw["model"] == "gpt-4o"


def test_main_max_steps_int_coercion_failure_exits(monkeypatch):
    """argparse type=int 失败应 SystemExit, 不进 run_task。"""
    rec = _RunTaskRecorder()
    monkeypatch.setattr("web_agent.cli.run_task", rec)
    monkeypatch.setattr("sys.argv", ["web-agent", "g", "--max-steps", "abc"])
    with pytest.raises(SystemExit):
        main()
    assert rec.calls == []  # 解析失败前 run_task 未被调


def test_main_missing_goal_exits(monkeypatch):
    """positional goal 必填; 缺则 argparse SystemExit。"""
    rec = _RunTaskRecorder()
    monkeypatch.setattr("web_agent.cli.run_task", rec)
    monkeypatch.setattr("sys.argv", ["web-agent"])
    with pytest.raises(SystemExit):
        main()
    assert rec.calls == []


def test_main_prints_result_with_header(monkeypatch, capsys):
    rec = _RunTaskRecorder("DONE_42")
    monkeypatch.setattr("web_agent.cli.run_task", rec)
    monkeypatch.setattr("sys.argv", ["web-agent", "g"])

    main()

    captured = capsys.readouterr()
    assert "=== 任务结果 ===" in captured.out
    assert "DONE_42" in captured.out


# ---------- run_task env precedence (cli arg > env > default) ----------

class _FakePlaywrightCtx:
    """async with async_playwright() as p: 用; p 是 SimpleNamespace 几乎啥都没; cli 不真用 p。"""

    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def patch_run_task_io_chain(monkeypatch):
    """拦掉 run_task 的所有 IO 边界, 让纯 env/参数路径可观测。"""

    monkeypatch.setattr("web_agent.cli.load_dotenv", lambda: None)
    monkeypatch.setattr("web_agent.cli.async_playwright", _FakePlaywrightCtx)
    # V0.16.19: stub auto-spawn 不真去 spawn Chrome
    monkeypatch.setattr("web_agent.cli.ensure_chrome_running", lambda url: None)

    fake_page = SimpleNamespace(
        set_viewport_size=AsyncMock(),
        goto=AsyncMock(),
    )
    fake_connect = AsyncMock(return_value=(SimpleNamespace(), SimpleNamespace(), fake_page))
    monkeypatch.setattr("web_agent.cli.connect", fake_connect)
    monkeypatch.setattr("web_agent.cli.apply_stealth", AsyncMock())
    # V0.27.4: secret_store kwarg 加到 run_task 透传链, monkeypatch lambda 兼容收 **kwargs
    monkeypatch.setattr("web_agent.cli.make_client",
                        lambda provider=None, model=None, **kwargs: SimpleNamespace(name="fake", model="fake"))

    captured: dict = {}

    async def fake_run_react_loop(**kwargs):
        captured.update(kwargs)
        return "OK"

    monkeypatch.setattr("web_agent.cli.run_react_loop", fake_run_react_loop)
    return captured


async def test_run_task_cli_arg_overrides_env(monkeypatch, patch_run_task_io_chain):
    monkeypatch.setenv("WEB_AGENT_MAX_STEPS", "99")
    monkeypatch.setenv("WEB_AGENT_MAX_WALLCLOCK_S", "999.0")
    monkeypatch.setenv("WEB_AGENT_CDP_URL", "http://env:1")

    result = await run_task(
        goal="g", max_steps=7, max_wallclock_s=42.5, cdp_url="http://arg:2",
    )

    assert result == "OK"
    assert patch_run_task_io_chain["max_steps"] == 7
    assert patch_run_task_io_chain["max_wallclock_s"] == 42.5


async def test_run_task_env_used_when_arg_none(monkeypatch, patch_run_task_io_chain):
    monkeypatch.setenv("WEB_AGENT_MAX_STEPS", "50")
    monkeypatch.setenv("WEB_AGENT_MAX_WALLCLOCK_S", "120.0")

    result = await run_task(goal="g")

    assert result == "OK"
    assert patch_run_task_io_chain["max_steps"] == 50
    assert patch_run_task_io_chain["max_wallclock_s"] == 120.0


async def test_run_task_default_when_no_arg_no_env(monkeypatch, patch_run_task_io_chain):
    for var in ("WEB_AGENT_MAX_STEPS", "WEB_AGENT_MAX_WALLCLOCK_S", "WEB_AGENT_CDP_URL",
                "WEB_AGENT_VIEWPORT_WIDTH", "WEB_AGENT_VIEWPORT_HEIGHT"):
        monkeypatch.delenv(var, raising=False)

    result = await run_task(goal="g")

    assert result == "OK"
    assert patch_run_task_io_chain["max_steps"] == 20
    assert patch_run_task_io_chain["max_wallclock_s"] == 300.0
