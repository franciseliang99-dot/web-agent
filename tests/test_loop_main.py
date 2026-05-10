"""loop.py 主体 abort 路径单测 (audit gap 收尾)。

V0.7.0 safety-loop / V0.9.0 captcha / V0.11.0 reflect 间接覆盖了 done / safety_block /
captcha_timeout 路径; 此 file 直测剩 3 条 abort 出口:
- max_steps 耗尽 → "(max_steps 耗尽未完成)" (loop.py L291)
- wallclock 超时 → "WALLCLOCK_EXCEEDED at step N" (loop.py L147-154, 不写 step 仅 end_task)
- LLM 异常 graceful capture → "LLM_FAILED at step N" + trace 落 action_type="error" (L176-190)

复用 V0.7.0 / V0.9.0 / V0.11.0 inline FakePage/FakeLLMClient/patch_loop_internals 模式。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from web_agent.types import Action, CloseTabAction, DoneAction, ScrollAction, SwitchTabAction
from web_agent.loop import run_react_loop
from web_agent.perceiver import Mark


_DUMMY_MARK = Mark(
    id=1, tag="button", role="", text="ok",
    bbox={"x": 0, "y": 0, "w": 80, "h": 30},
    input_type="", name="", href="",
)
_FAKE_SHOT = "aGVsbG8h"


class FakeLLMClient:
    name = "fake"
    model = "fake"

    def __init__(self, actions: list[Action]) -> None:
        self._actions = list(actions)
        self._i = 0

    async def plan(self, goal, screenshot_b64, marks, trace, **kwargs) -> Action:
        # V0.21.2: **kwargs 接 tabs/current_idx (loop 始终传, fake 测试不用)
        a = self._actions[min(self._i, len(self._actions) - 1)]
        self._i += 1
        return a


class FakePage:
    """V0.21.1: 加 url + bring_to_front + close 支持多 tab 派发测试."""

    class _Keyboard:
        async def press(self, key: str) -> None:
            return None

    def __init__(self, url: str = "about:blank", title: str = "") -> None:
        self.url = url
        self._title = title
        self.keyboard = FakePage._Keyboard()
        self.brought_to_front = 0
        self.closed = False

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        return None

    async def bring_to_front(self) -> None:
        self.brought_to_front += 1

    async def close(self) -> None:
        self.closed = True

    async def title(self) -> str:
        return self._title


class FakeContext:
    """V0.21.1: loop 接 ctx 不接 page; 简单 list[FakePage] wrapper."""

    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages


def _ctx(pages: list[FakePage] | None = None) -> FakeContext:
    """构 FakeContext 默认 1 tab; 多 tab 测试显式传 list."""
    return FakeContext(pages or [FakePage()])


async def _fake_perceive(page):
    return [_DUMMY_MARK], _FAKE_SHOT


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def patch_loop_internals(monkeypatch):
    monkeypatch.setattr("web_agent.loop.perceive", _fake_perceive)
    monkeypatch.setattr("web_agent.loop.think", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_click", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_type", _noop)
    monkeypatch.setattr("web_agent.loop.scroll", _noop)


def _read_trace_steps(db: Path) -> list[tuple[int, str, dict]]:
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT step, action_type, action_args FROM steps ORDER BY step"
    ).fetchall()
    conn.close()
    return [(r[0], r[1], json.loads(r[2])) for r in rows]


def _read_task_result(db: Path) -> str:
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT result FROM tasks LIMIT 1").fetchone()
    conn.close()
    return row[0] if row else ""


# ---------- 三条 abort 路径 ----------

async def test_max_steps_exhausted_returns_signal_string(
    monkeypatch, tmp_path, patch_loop_internals
):
    """LLM 永不返 done; max_steps 跑完 → "(max_steps 耗尽未完成)"; trace 落 max_steps 个 step。

    用 varied scroll dy 避 V0.5.0 anti-loop 在第 3 次同 action 时提前硬 abort。
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    client = FakeLLMClient([
        ScrollAction(thought="x", dy=100),
        ScrollAction(thought="x", dy=200),
    ])  # 2 步 + max_steps=2 → 第 2 步用尽不 done → 出 max_steps 路径

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _ctx(), client, goal="测 max_steps 耗尽",
        max_steps=2, db_path=db, screenshots_dir=shots,
    )

    assert result == "(max_steps 耗尽未完成)"
    steps = _read_trace_steps(db)
    assert len(steps) == 2
    assert all(s[1] == "scroll" for s in steps)
    assert _read_task_result(db) == "(max_steps 耗尽未完成)"


async def test_wallclock_exceeded_aborts_without_step_row(
    monkeypatch, tmp_path, patch_loop_internals
):
    """elapsed > max_wallclock_s → 走 L147-154 wallclock 出口; 仅 end_task, 不 trace.append/write_step。

    用 max_wallclock_s=-1.0 让 step 0 任何 (>=0) elapsed 立即触发, 免 monkeypatch time。
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    client = FakeLLMClient([
        ScrollAction(thought="x", dy=100),
    ])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        _ctx(), client, goal="测 wallclock 超时",
        max_steps=5, max_wallclock_s=-1.0,
        db_path=db, screenshots_dir=shots,
    )

    assert result.startswith("WALLCLOCK_EXCEEDED at step 0"), result
    assert "max_wallclock_s=-1" in result
    # wallclock 路径不写 step row
    assert _read_trace_steps(db) == []
    # 但 tasks 表 result 列已被 end_task 写
    assert _read_task_result(db).startswith("WALLCLOCK_EXCEEDED")


async def test_memories_injected_as_synthetic_step_minus_one(
    monkeypatch, tmp_path, patch_loop_internals
):
    """W5-D.2: memories 字符串 → run_react_loop 主循环前 prepend Step(step=-1,
    action_type='memory_recall'); LLM 第一次 plan 应看到; 不写 sqlite (不污染持久化)。
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    seen_traces: list[list[dict]] = []

    class RecordingLLMClient:
        name = "fake"
        model = "fake"

        async def plan(self, goal, screenshot_b64, marks, trace, **kwargs):
            seen_traces.append(list(trace.for_llm()))
            return DoneAction(thought="x", result="ok")

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    memories_str = "过去在该 domain 跑过 2 个任务 (newest first):\n[ts] OK foo -> bar"

    result = await run_react_loop(
        _ctx(), RecordingLLMClient(), goal="测 W5-D.2 inject",
        max_steps=2, db_path=db, screenshots_dir=shots,
        memories=memories_str,
    )

    assert result == "ok"
    # plan() 第一次看到的 trace[0] 应是 memory_recall synthetic step
    assert len(seen_traces) == 1
    first_step_in_trace = seen_traces[0][0]
    assert first_step_in_trace["action"]["type"] == "memory_recall"
    assert "过去在该 domain 跑过" in first_step_in_trace["observation"]
    # sqlite 不含 step=-1 (不污染 trace.db 实际执行事件流)
    sqlite_steps = _read_trace_steps(db)
    sqlite_step_indices = [s[0] for s in sqlite_steps]
    assert -1 not in sqlite_step_indices


async def test_llm_exception_captured_writes_error_step(
    monkeypatch, tmp_path, patch_loop_internals
):
    """client.plan 抛 RuntimeError → loop graceful capture, 写 trace error step + end_task。

    模拟 SDK 内置 max_retries 耗尽 / network / tool_call=None 等真实 LLM 失败。
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    class RaisingLLMClient:
        name = "fake"
        model = "fake"

        async def plan(self, goal, screenshot_b64, marks, trace, **kwargs):
            raise RuntimeError("503 upstream timeout")

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _ctx(), RaisingLLMClient(), goal="测 LLM 异常",
        max_steps=5, db_path=db, screenshots_dir=shots,
    )

    assert result.startswith("LLM_FAILED at step 0"), result
    assert "RuntimeError" in result
    assert "503 upstream" in result

    steps = _read_trace_steps(db)
    assert len(steps) == 1
    step_i, action_type, action_args = steps[0]
    assert step_i == 0
    assert action_type == "error"
    assert "503 upstream" in action_args["error"]
    assert _read_task_result(db).startswith("LLM_FAILED")


# ---------- V0.21.1 multi-tab 派发测试 ----------


async def test_switch_tab_brings_target_page_to_front_and_changes_active(
    monkeypatch, tmp_path, patch_loop_internals
):
    """SwitchTabAction 派发: pages[idx].bring_to_front() 调用; trace obs 含 "switched to tab [idx]"."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    pages = [FakePage(url="https://a.example/"), FakePage(url="https://b.example/")]
    client = FakeLLMClient([
        SwitchTabAction(thought="切到 b", idx=1),
        DoneAction(thought="完成", result="ok"),
    ])
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        FakeContext(pages), client, goal="测 switch_tab",
        max_steps=3, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result == "ok"
    assert pages[1].brought_to_front == 1
    assert pages[0].brought_to_front == 0
    steps = _read_trace_steps(db)
    assert steps[0][1] == "switch_tab"
    assert steps[0][2] == {"idx": 1}


async def test_switch_tab_out_of_range_logs_error_and_keeps_active(
    monkeypatch, tmp_path, patch_loop_internals
):
    """SwitchTabAction idx 越界 → ERROR obs, 不 bring_to_front, active_idx 不变."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    pages = [FakePage(url="https://a.example/")]
    client = FakeLLMClient([
        SwitchTabAction(thought="瞎切", idx=99),
        DoneAction(thought="完成", result="ok"),
    ])
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        FakeContext(pages), client, goal="测 switch_tab oor",
        max_steps=3, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result == "ok"
    assert pages[0].brought_to_front == 0
    conn = sqlite3.connect(db)
    obs = conn.execute(
        "SELECT observation FROM steps WHERE action_type='switch_tab'"
    ).fetchone()[0]
    conn.close()
    assert "ERROR" in obs and "越界" in obs


async def test_close_tab_refuses_last_remaining_tab(
    monkeypatch, tmp_path, patch_loop_internals
):
    """CloseTab guard (a): len(ctx.pages)==1 → ERROR obs, 不调 page.close()."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    pages = [FakePage(url="https://a.example/")]
    client = FakeLLMClient([
        CloseTabAction(thought="想关唯一 tab", idx=0),
        DoneAction(thought="完成", result="ok"),
    ])
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        FakeContext(pages), client, goal="测 close_tab last",
        max_steps=3, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result == "ok"
    assert pages[0].closed is False
    conn = sqlite3.connect(db)
    obs = conn.execute(
        "SELECT observation FROM steps WHERE action_type='close_tab'"
    ).fetchone()[0]
    conn.close()
    assert "ERROR" in obs and "最后" in obs


async def test_close_tab_refuses_active_tab_forces_switch_first(
    monkeypatch, tmp_path, patch_loop_internals
):
    """CloseTab guard (b): idx==active_idx → ERROR obs (强迫 LLM 先 switch_tab 切走再 close)."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    pages = [FakePage(url="https://a.example/"), FakePage(url="https://b.example/")]
    client = FakeLLMClient([
        CloseTabAction(thought="想关当前 active", idx=0),
        DoneAction(thought="完成", result="ok"),
    ])
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        FakeContext(pages), client, goal="测 close_tab active",
        max_steps=3, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result == "ok"
    assert pages[0].closed is False
    conn = sqlite3.connect(db)
    obs = conn.execute(
        "SELECT observation FROM steps WHERE action_type='close_tab'"
    ).fetchone()[0]
    conn.close()
    assert "ERROR" in obs and "active" in obs


async def test_close_tab_lower_idx_decrements_active_idx(
    monkeypatch, tmp_path, patch_loop_internals
):
    """先 switch 到 idx=2, 再 close idx=0 → active_idx 应 -=1 变 1; pages[0].close() 调用."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    pages = [
        FakePage(url="https://a.example/"),
        FakePage(url="https://b.example/"),
        FakePage(url="https://c.example/"),
    ]
    client = FakeLLMClient([
        SwitchTabAction(thought="切到 c", idx=2),
        CloseTabAction(thought="关 a", idx=0),
        DoneAction(thought="完成", result="ok"),
    ])
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        FakeContext(pages), client, goal="测 close_tab adjust",
        max_steps=4, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result == "ok"
    assert pages[0].closed is True
    assert pages[2].closed is False  # active 没被关
    conn = sqlite3.connect(db)
    obs = conn.execute(
        "SELECT observation FROM steps WHERE action_type='close_tab'"
    ).fetchone()[0]
    conn.close()
    assert "active_idx now=1" in obs


async def test_initial_active_idx_kwarg_picks_jd_extract_path(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.21.1: jd_extract / list_extract 半自动模式传 initial_active_idx 指向特定 URL match tab.

    传 initial_active_idx=1 + 2 tab → 第 1 步 perceive 应走 pages[1] (LLM 第一步看到的就是
    jd_page 不是 ctx.pages[0]).
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    pages = [FakePage(url="https://a.example/"), FakePage(url="https://b.example/")]
    seen_urls: list[str] = []

    async def recording_perceive(page):
        seen_urls.append(page.url)
        return [_DUMMY_MARK], _FAKE_SHOT

    monkeypatch.setattr("web_agent.loop.perceive", recording_perceive)
    client = FakeLLMClient([DoneAction(thought="完成", result="ok")])

    result = await run_react_loop(
        FakeContext(pages), client, goal="测 initial_active_idx",
        max_steps=2, db_path=tmp_path / "trace.db",
        screenshots_dir=tmp_path / "shots",
        initial_active_idx=1,
    )
    assert result == "ok"
    assert seen_urls == ["https://b.example/"]


def test_page_fingerprint_includes_active_idx():
    """V0.21.1: _page_fingerprint 加 active_idx 防 switch-back 看似无变化触发误判."""
    from web_agent.loop import _page_fingerprint
    fp_tab0 = _page_fingerprint("https://x.example/", [_DUMMY_MARK], active_idx=0)
    fp_tab1 = _page_fingerprint("https://x.example/", [_DUMMY_MARK], active_idx=1)
    assert fp_tab0 != fp_tab1, "不同 active_idx 必须生成不同 fingerprint (防 switch-back loop_detected)"
    # 默认 active_idx=0 向后兼容 (单 tab callers 不传)
    fp_default = _page_fingerprint("https://x.example/", [_DUMMY_MARK])
    assert fp_default == fp_tab0


# ---------- V0.21.2 loop 集成: plan() 收到 tabs/current_idx ----------


async def test_plan_called_with_tabs_and_current_idx(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.21.2: loop 每 step 算 tabs + current_idx 传给 client.plan().

    验证 RecordingLLMClient 收到的 kwargs 含 tabs=[(idx, title)] + current_idx=active_idx;
    切 tab 后 current_idx 应跟随 active_idx 变.
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    pages = [
        FakePage(url="https://a.example/", title="Tab A"),
        FakePage(url="https://b.example/", title="Tab B"),
    ]
    seen_kwargs: list[dict] = []

    class RecordingLLMClient:
        name = "fake"
        model = "fake"

        def __init__(self, actions: list[Action]) -> None:
            self._actions = list(actions)
            self._i = 0

        async def plan(self, goal, screenshot_b64, marks, trace, **kwargs):
            seen_kwargs.append(kwargs)
            a = self._actions[min(self._i, len(self._actions) - 1)]
            self._i += 1
            return a

    client = RecordingLLMClient([
        SwitchTabAction(thought="切 b", idx=1),
        DoneAction(thought="完成", result="ok"),
    ])
    result = await run_react_loop(
        FakeContext(pages), client, goal="测 tabs kwargs",
        max_steps=3, db_path=tmp_path / "trace.db",
        screenshots_dir=tmp_path / "shots",
    )
    assert result == "ok"
    # 第 0 步: active_idx=0
    assert seen_kwargs[0]["current_idx"] == 0
    assert seen_kwargs[0]["tabs"] == [(0, "Tab A"), (1, "Tab B")]
    # 第 1 步: SwitchTab(1) 已派发 → active_idx=1
    assert seen_kwargs[1]["current_idx"] == 1
    assert seen_kwargs[1]["tabs"] == [(0, "Tab A"), (1, "Tab B")]


def test_gather_tab_titles_fallback_url_on_empty_title():
    """V0.21.2: title() 返空 → fallback URL path[-60:]."""
    import asyncio
    from web_agent.loop import _gather_tab_titles
    pages = [
        FakePage(url="https://example.com/very/long/path/segment", title=""),
    ]
    result = asyncio.run(_gather_tab_titles(pages))
    assert len(result) == 1
    assert result[0][0] == 0
    assert "example.com" in result[0][1] or "/very/long/path/segment" in result[0][1]


def test_gather_tab_titles_fallback_untitled_on_no_url():
    """V0.21.2: title() 失败 + 无 url → '(untitled)' 兜底, 不 raise."""
    import asyncio
    from web_agent.loop import _gather_tab_titles

    class BarePage:
        async def title(self) -> str:
            raise RuntimeError("page navigating")

    result = asyncio.run(_gather_tab_titles([BarePage()]))
    assert result == [(0, "(untitled)")]
