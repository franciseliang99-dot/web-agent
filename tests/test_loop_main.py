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
    """V0.21.1: loop 接 ctx 不接 page; 简单 list[FakePage] wrapper.

    V0.21.3: 加 .on(event, handler) 模拟 Playwright BrowserContext listener API,
    测试可主动 await self._handlers[event](new_page) 触发 popup 路径而不真 launch chromium.
    """

    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages
        self._handlers: dict[str, object] = {}

    def on(self, event: str, handler: object) -> None:
        self._handlers[event] = handler


def _ctx(pages: list[FakePage] | None = None) -> FakeContext:
    """构 FakeContext 默认 1 tab; 多 tab 测试显式传 list."""
    return FakeContext(pages or [FakePage()])


async def _fake_perceive(page):
    # V0.22.4: perceive 返三-tuple (marks, screenshot, cross_origin_hosts)
    return [_DUMMY_MARK], _FAKE_SHOT, []


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
        return [_DUMMY_MARK], _FAKE_SHOT, []

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


def test_drain_pre_step_observations_drains_all_attrs_and_clears():
    """V0.24.1: helper 遍历 download/dialog 2 deque, append 到上一步 obs, clear 防重复."""
    from collections import deque
    from unittest.mock import MagicMock
    from web_agent.loop import _drain_pre_step_observations
    from web_agent.trace import Step, Trace
    ctx = MagicMock()
    ctx._web_agent_recent_downloads = deque(["downloaded: a.pdf"], maxlen=10)
    ctx._web_agent_recent_dialogs = deque(["dialog confirm: 'ok?' (auto-dismissed)"], maxlen=10)
    trace = Trace(task_id="t", goal="x")
    trace.append(Step(step=0, ts=0.0, thought="x", action_type="click",
                       action_args={}, observation="prior obs"))
    _drain_pre_step_observations(ctx, trace)
    assert "downloaded: a.pdf" in trace.steps[-1].observation
    assert "auto-dismissed" in trace.steps[-1].observation
    assert "prior obs" in trace.steps[-1].observation  # 原 obs 保留
    # 注入幂等: deque clear
    assert len(ctx._web_agent_recent_downloads) == 0
    assert len(ctx._web_agent_recent_dialogs) == 0


def test_drain_pre_step_observations_empty_trace_skips():
    """V0.24.1: trace.steps 空 (loop 第一步) → helper 立即 return, 不抛."""
    from collections import deque
    from unittest.mock import MagicMock
    from web_agent.loop import _drain_pre_step_observations
    from web_agent.trace import Trace
    ctx = MagicMock()
    ctx._web_agent_recent_downloads = deque(["downloaded: x.pdf"], maxlen=10)
    trace = Trace(task_id="t", goal="x")  # steps 空
    _drain_pre_step_observations(ctx, trace)
    # trace 未 mutate, deque 未 clear (因为没有 step 可挂)
    assert len(trace.steps) == 0
    assert len(ctx._web_agent_recent_downloads) == 1


def test_drain_pre_step_observations_empty_deques_noop():
    """V0.24.1: 2 deque 都空 → noop, trace.steps[-1] obs 不变."""
    from collections import deque
    from unittest.mock import MagicMock
    from web_agent.loop import _drain_pre_step_observations
    from web_agent.trace import Step, Trace
    ctx = MagicMock()
    ctx._web_agent_recent_downloads = deque(maxlen=10)
    ctx._web_agent_recent_dialogs = deque(maxlen=10)
    trace = Trace(task_id="t", goal="x")
    trace.append(Step(step=0, ts=0.0, thought="x", action_type="click",
                       action_args={}, observation="unchanged"))
    _drain_pre_step_observations(ctx, trace)
    assert trace.steps[-1].observation == "unchanged"


def test_resolve_frame_main_frame_returns_none():
    """V0.22.2: frame_path="" (主 frame) → None 让 actuator 走 page 路径."""
    from unittest.mock import MagicMock
    from web_agent.loop import _resolve_frame
    page = MagicMock()
    assert _resolve_frame(page, "") is None


def test_resolve_frame_walks_child_frames_dfs():
    """V0.22.2: "0.1" → main.child_frames[0].child_frames[1]."""
    from unittest.mock import MagicMock
    from web_agent.loop import _resolve_frame
    inner = MagicMock()
    inner.is_detached = MagicMock(return_value=False)
    middle = MagicMock(child_frames=[MagicMock(), inner])
    main = MagicMock(child_frames=[middle])
    page = MagicMock(main_frame=main)
    assert _resolve_frame(page, "0.1") is inner


def test_resolve_frame_index_error_returns_none():
    """V0.22.2: frame_path="0.99" 越界 → None (loop 退化主 frame, 不抛)."""
    from unittest.mock import MagicMock
    from web_agent.loop import _resolve_frame
    main = MagicMock(child_frames=[])  # 无 child
    page = MagicMock(main_frame=main)
    assert _resolve_frame(page, "0") is None


def test_resolve_frame_value_error_on_non_numeric_returns_none():
    """V0.22.2: frame_path="abc" 非数字 → ValueError → None."""
    from unittest.mock import MagicMock
    from web_agent.loop import _resolve_frame
    page = MagicMock()
    assert _resolve_frame(page, "abc") is None


def test_resolve_frame_detached_returns_none():
    """V0.22.2: resolve 到 detached frame → None (loop 退化主 frame)."""
    from unittest.mock import MagicMock
    from web_agent.loop import _resolve_frame
    detached = MagicMock()
    detached.is_detached = MagicMock(return_value=True)
    main = MagicMock(child_frames=[detached])
    page = MagicMock(main_frame=main)
    assert _resolve_frame(page, "0") is None


def test_page_fingerprint_distinguishes_frame_path():
    """V0.22.0: 同 url+marks 但 frame_path 不同 → 不同 fingerprint (防 iframe navigate 看似无变化)."""
    from web_agent.loop import _page_fingerprint
    main_mark = Mark(
        id=1, tag="button", role="", text="ok",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        input_type="", name="", href="", frame_path="",
    )
    iframe_mark = Mark(
        id=1, tag="button", role="", text="ok",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        input_type="", name="", href="", frame_path="0",
    )
    fp_main = _page_fingerprint("https://x.test/", [main_mark])
    fp_iframe = _page_fingerprint("https://x.test/", [iframe_mark])
    assert fp_main != fp_iframe, "frame_path 不同必须区分 fingerprint"


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


async def test_dispatch_drag_calls_human_like_drag_with_resolved_marks(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.23.2: DragAction 找 from/to mark + 校验同 frame + actuator 派发 + reset last_clicked."""
    from web_agent.types import DragAction
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    from_m = Mark(id=1, tag="div", role="", text="src", bbox={"x": 10, "y": 10, "w": 30, "h": 30})
    to_m = Mark(id=2, tag="div", role="", text="dst", bbox={"x": 100, "y": 100, "w": 50, "h": 50})

    async def perceive_two(page):
        return [from_m, to_m], _FAKE_SHOT, []

    monkeypatch.setattr("web_agent.loop.perceive", perceive_two)
    drag_calls: list[tuple] = []

    async def fake_drag(page, fm, tm, frame=None):
        drag_calls.append((fm.id, tm.id, frame))

    monkeypatch.setattr("web_agent.loop.human_like_drag", fake_drag)

    client = FakeLLMClient([
        DragAction(thought="拖", from_mark_id=1, to_mark_id=2),
        DoneAction(thought="完成", result="ok"),
    ])
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        _ctx(), client, goal="测 drag dispatch",
        max_steps=3, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result == "ok"
    assert drag_calls == [(1, 2, None)]
    steps = _read_trace_steps(db)
    drag_step = next(s for s in steps if s[1] == "drag")
    assert drag_step[1] == "drag"
    assert drag_step[2].get("from_mark_id") == 1
    assert drag_step[2].get("to_mark_id") == 2


async def test_dispatch_drag_cross_frame_returns_error_obs(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.23.2: drag from.frame_path != to.frame_path → ERROR obs, 不调 actuator."""
    from web_agent.types import DragAction
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    from_m = Mark(id=1, tag="div", role="", text="src", bbox={"x": 10, "y": 10, "w": 30, "h": 30}, frame_path="")
    to_m = Mark(id=2, tag="div", role="", text="dst", bbox={"x": 100, "y": 100, "w": 50, "h": 50}, frame_path="0")

    async def perceive_cross(page):
        return [from_m, to_m], _FAKE_SHOT, []

    monkeypatch.setattr("web_agent.loop.perceive", perceive_cross)
    drag_called = {"n": 0}

    async def spy_drag(*a, **kw):
        drag_called["n"] += 1

    monkeypatch.setattr("web_agent.loop.human_like_drag", spy_drag)

    client = FakeLLMClient([
        DragAction(thought="跨帧", from_mark_id=1, to_mark_id=2),
        DoneAction(thought="完成", result="ok"),
    ])
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        _ctx(), client, goal="测 drag cross frame",
        max_steps=3, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result == "ok"
    assert drag_called["n"] == 0, "跨 frame drag 不应调用 actuator"
    import sqlite3
    conn = sqlite3.connect(db)
    obs = conn.execute("SELECT observation FROM steps WHERE action_type='drag'").fetchone()[0]
    conn.close()
    assert "ERROR" in obs and "跨 frame" in obs


async def test_dispatch_upload_calls_upload_file_with_paths(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.23.2: UploadAction 找 mark + safety pass + actuator upload_file 接 paths tuple."""
    from web_agent.types import UploadAction
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    file_input = Mark(
        id=5, tag="input", role="", text="", bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        input_type="file",
    )

    async def perceive_input(page):
        return [file_input], _FAKE_SHOT, []

    monkeypatch.setattr("web_agent.loop.perceive", perceive_input)
    upload_calls: list[tuple] = []

    async def fake_upload(page, mark, paths, frame=None):
        upload_calls.append((mark.id, paths, frame))

    monkeypatch.setattr("web_agent.loop.upload_file", fake_upload)

    client = FakeLLMClient([
        UploadAction(thought="传文件", mark_id=5, paths=("/tmp/safe.pdf",)),
        DoneAction(thought="完成", result="ok"),
    ])
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        _ctx(), client, goal="测 upload dispatch",
        max_steps=3, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result == "ok"
    assert upload_calls == [(5, ("/tmp/safe.pdf",), None)]


async def test_dispatch_upload_safety_blocks_sensitive_path(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.23.2: upload paths 命中黑名单 → safety abort 不调 actuator."""
    from web_agent.types import UploadAction
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    file_input = Mark(
        id=1, tag="input", role="", text="", bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        input_type="file",
    )

    async def perceive_input(page):
        return [file_input], _FAKE_SHOT, []

    monkeypatch.setattr("web_agent.loop.perceive", perceive_input)
    upload_called = {"n": 0}

    async def spy_upload(*a, **kw):
        upload_called["n"] += 1

    monkeypatch.setattr("web_agent.loop.upload_file", spy_upload)

    client = FakeLLMClient([
        UploadAction(thought="试敏感", mark_id=1, paths=("~/.ssh/id_rsa",)),
    ])
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        _ctx(), client, goal="测 upload safety",
        max_steps=2, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert "SAFETY_BLOCK" in result
    assert "upload-sensitive-path" in result
    assert upload_called["n"] == 0, "safety abort 不应调 actuator"


async def test_plan_called_with_cross_origin_hosts_kwarg(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.22.4: loop 把 perceive 收集的 cross_origin_hosts 透传给 client.plan() kwarg."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    seen_kwargs: list[dict] = []

    async def perceive_with_hosts(page):
        return [_DUMMY_MARK], _FAKE_SHOT, ["stripe.com", "recaptcha.net"]

    monkeypatch.setattr("web_agent.loop.perceive", perceive_with_hosts)

    class RecordingLLMClient:
        name = "fake"
        model = "fake"

        async def plan(self, goal, screenshot_b64, marks, trace, **kwargs):
            seen_kwargs.append(kwargs)
            return DoneAction(thought="完成", result="ok")

    result = await run_react_loop(
        _ctx(), RecordingLLMClient(), goal="测 cross_origin_hosts kwargs",
        max_steps=2, db_path=tmp_path / "trace.db",
        screenshots_dir=tmp_path / "shots",
    )
    assert result == "ok"
    assert seen_kwargs[0]["cross_origin_hosts"] == ["stripe.com", "recaptcha.net"]


def test_gather_tab_titles_fallback_untitled_on_no_url():
    """V0.21.2: title() 失败 + 无 url → '(untitled)' 兜底, 不 raise."""
    import asyncio
    from web_agent.loop import _gather_tab_titles

    class BarePage:
        async def title(self) -> str:
            raise RuntimeError("page navigating")

    result = asyncio.run(_gather_tab_titles([BarePage()]))
    assert result == [(0, "(untitled)")]
