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


def test_cli_imports_init_reflections_db_for_startup_invariant() -> None:
    """V0.44.1: cli.py 启动路径需含 init_reflections_db (#21 真发现 cosmetic + auditability fix).

    防回归: 未来重构若移除 cli startup hook, .tables 失去 reflections invariant 风险,
    生产 audit 时误判 dead path 重蹈 V0.41.0 #21 真发现.
    """
    import web_agent.cli as cli_mod
    assert hasattr(cli_mod, "init_reflections_db"), (
        "V0.44.1: cli.py 缺 init_reflections_db 导入 — startup hook 被移除? "
        "真发现 #21 reflections 表 dead path 风险回归"
    )


def test_cli_imports_init_trace_db_for_schema_startup_invariant() -> None:
    """V0.53.0: cli.py 启动路径需含 init_trace_db (#28 真发现 generalize — V0.42 telemetry
    schema ALTER 不再依赖 run_react_loop lazy 触发).

    防回归: 未来重构若移除 cli startup hook, trace.db V0.42 4 字段 (input_tokens / output_tokens
    / cache_creation_input_tokens / cache_read_input_tokens) 永不 ALTER, 重蹈 #28 schema
    dead-migrate (跟 V0.44.1 #21 + V0.47.2 protections 同 startup invariant 模式).
    """
    import web_agent.cli as cli_mod
    assert hasattr(cli_mod, "init_trace_db"), (
        "V0.53.0: cli.py 缺 init_trace_db 导入 — startup hook 被移除? "
        "真发现 #28 trace.db V0.42 schema dead-migrate 风险回归"
    )


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


def test_main_capability_hint_routes_to_provider(monkeypatch):
    """V0.27.5: --capability-hint 走 routing select_provider, 覆盖 --provider; 验 provider 真选对.

    Kimi 强项 axis 'multi-tab' (V0.26.4 baseline pass=1.0) → routing 选 'openai' (SKU 'openai-kimi'
    映射 wire 'openai'). 同时验 P2 修: load_dotenv 提前到 select_provider 之前 → env 可读.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    rec = _RunTaskRecorder("OK")
    monkeypatch.setattr("web_agent.cli.run_task", rec)
    monkeypatch.setattr("sys.argv", [
        "web-agent", "g",
        "--provider", "anthropic",  # 故意设, 验 capability_hint 覆盖
        "--capability-hint", "multi-tab",
    ])

    main()

    kw = rec.calls[0]
    assert kw["provider"] == "openai", \
        f"V0.27.5: capability_hint=multi-tab Kimi 强项 → 应选 'openai' 覆盖 --provider, 实 {kw['provider']!r}"


def test_main_capability_hint_fallback_anthropic_for_zero_axis(monkeypatch):
    """V0.27.5: capability_hint='iframe' (Kimi pass=0.0) → fallback anthropic."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    rec = _RunTaskRecorder("OK")
    monkeypatch.setattr("web_agent.cli.run_task", rec)
    monkeypatch.setattr("sys.argv", [
        "web-agent", "g", "--capability-hint", "iframe",
    ])

    main()

    assert rec.calls[0]["provider"] == "anthropic"


def test_main_no_capability_hint_keeps_old_provider_path(monkeypatch):
    """V0.27.5: 不带 --capability-hint → 老路径 provider=args.provider, routing 不接管."""
    rec = _RunTaskRecorder("OK")
    monkeypatch.setattr("web_agent.cli.run_task", rec)
    monkeypatch.setattr("sys.argv", [
        "web-agent", "g", "--provider", "openai",
    ])

    main()

    assert rec.calls[0]["provider"] == "openai"  # 老路径不接 routing


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


# ---------- V0.28.2 W6-B: cli inject reflections via memories_str ----------


async def test_run_task_injects_reflections_into_memories_str(monkeypatch, patch_run_task_io_chain, tmp_path):
    """V0.28.2/V0.28.3: cli 启动 build_inject_string helper 真透传 run_react_loop."""

    def fake_inject(db, domain, *, include_memories=True, include_reflections=True, **kw):
        # 模 build_inject_string 返 含 reflections 的 memories_str
        return (
            "上次在该 domain 失败教训 (newest first, 共 1 条):\n"
            "[2025-01-01T00:00:00] 页面加载慢 → 下次先 wait_for_selector('.results')"
        )

    monkeypatch.setattr("web_agent.cli.build_inject_string", fake_inject)

    await run_task(goal="g", start_url="https://example.com")

    memories = patch_run_task_io_chain["memories"]
    assert memories is not None
    assert "上次在该 domain 失败教训" in memories
    assert "页面加载慢 →" in memories
    assert "wait_for_selector" in memories


async def test_run_task_reflections_disable_env_passes_false_to_helper(monkeypatch, patch_run_task_io_chain):
    """V0.28.2/V0.28.3: WEB_AGENT_REFLECTIONS_DISABLE=true → helper 收 include_reflections=False."""
    monkeypatch.setenv("WEB_AGENT_REFLECTIONS_DISABLE", "true")

    captured: dict[str, object] = {}

    def fake_inject(db, domain, *, include_memories=True, include_reflections=True, **kw):
        captured["include_memories"] = include_memories
        captured["include_reflections"] = include_reflections
        return None

    monkeypatch.setattr("web_agent.cli.build_inject_string", fake_inject)

    await run_task(goal="g", start_url="https://example.com")

    assert captured["include_reflections"] is False
    assert captured["include_memories"] is True  # MEMORY_DISABLE 没设, 仍 True


async def test_run_task_memory_disable_env_passes_false_to_helper(monkeypatch, patch_run_task_io_chain):
    """V0.28.3: WEB_AGENT_MEMORY_DISABLE=true → helper 收 include_memories=False."""
    monkeypatch.setenv("WEB_AGENT_MEMORY_DISABLE", "true")

    captured: dict[str, object] = {}

    def fake_inject(db, domain, *, include_memories=True, include_reflections=True, **kw):
        captured["include_memories"] = include_memories
        captured["include_reflections"] = include_reflections
        return None

    monkeypatch.setattr("web_agent.cli.build_inject_string", fake_inject)

    await run_task(goal="g", start_url="https://example.com")

    assert captured["include_memories"] is False
    assert captured["include_reflections"] is True


async def test_run_task_reflections_recall_failure_is_silent(monkeypatch, patch_run_task_io_chain, caplog):
    """V0.28.3: build_inject_string raise → cli 不该 catch (helper 内部 try/except 已包).
    本测改成验 helper 返 None 时 cli logger.info 不打 inject 信息."""
    import logging

    monkeypatch.setattr("web_agent.cli.build_inject_string",
                        lambda db, domain, **kw: None)

    with caplog.at_level(logging.INFO):
        result = await run_task(goal="g", start_url="https://example.com")

    assert result == "OK"  # 不阻塞主路径
    # helper 返 None → cli 不打 "memories+reflections inject" log
    assert not any("memories+reflections inject" in r.message for r in caplog.records), \
        f"helper 返 None 时不应打 inject log, caplog: {[r.message for r in caplog.records]}"
