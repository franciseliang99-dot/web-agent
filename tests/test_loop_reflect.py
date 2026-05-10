"""W5-A 自反思 (page-stuck hint) 单测 + 集成测.

软提示路径: 页面 3 步无变化 → trace.steps[-1].observation 追加 [reflect] hint
LLM 下次 plan() 看到 → 自己换策略, 不直接 abort (与 V0.5.0 anti-loop 同 action 3 次硬 abort 互补)。
"""

from __future__ import annotations

import pytest

from web_agent.types import Action, DoneAction, ScrollAction
from web_agent.loop import _page_fingerprint, run_react_loop
from web_agent.perceiver import Mark


# ---------- _page_fingerprint 纯函数 ----------

def _mk(id_: int, text: str = "btn") -> Mark:
    return Mark(
        id=id_, tag="button", role="", text=text,
        bbox={"x": 0, "y": 0, "w": 80, "h": 30},
        input_type="", name="", href="",
    )


def test_fingerprint_same_url_same_marks_eq():
    a = _page_fingerprint("https://x.test/", [_mk(1), _mk(2)])
    b = _page_fingerprint("https://x.test/", [_mk(1), _mk(2)])
    assert a == b


def test_fingerprint_diff_url_neq():
    a = _page_fingerprint("https://x.test/a", [_mk(1)])
    b = _page_fingerprint("https://x.test/b", [_mk(1)])
    assert a != b


def test_fingerprint_diff_mark_text_neq():
    a = _page_fingerprint("https://x.test/", [_mk(1, "Send")])
    b = _page_fingerprint("https://x.test/", [_mk(1, "Cancel")])
    assert a != b


def test_fingerprint_diff_mark_count_neq():
    a = _page_fingerprint("https://x.test/", [_mk(1)])
    b = _page_fingerprint("https://x.test/", [_mk(1), _mk(2)])
    assert a != b


# ---------- 集成: loop × reflection ----------

class RecordingLLMClient:
    """记录每次 plan() 看到的 trace 快照, 让测试断言 LLM 实际看到的 observation。"""

    name = "fake"
    model = "fake"

    def __init__(self, actions: list[Action]) -> None:
        self._actions = list(actions)
        self._i = 0
        self.observed_traces: list[list[str]] = []

    async def plan(self, goal, screenshot_b64, marks, trace, **kwargs) -> Action:
        # V0.21.2: **kwargs 接 tabs/current_idx
        self.observed_traces.append([s.observation for s in trace.steps])
        a = self._actions[min(self._i, len(self._actions) - 1)]
        self._i += 1
        return a


class FakePage:
    url = "https://stuck.test/"

    class _Keyboard:
        async def press(self, key: str) -> None:
            return None

    keyboard = _Keyboard()

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        return None


class FakeContext:
    """V0.21.1: loop 改读 ctx; reflect 测试单 tab. V0.21.3: 加 .on() noop."""

    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages
        self._handlers: dict[str, object] = {}

    def on(self, event: str, handler: object) -> None:
        self._handlers[event] = handler


def _ctx() -> FakeContext:
    return FakeContext([FakePage()])


_STUCK_MARKS = [_mk(1, "Submit")]
_FAKE_SHOT = "aGVsbG8h"  # b'hello!' valid base64


async def _stuck_perceive(page):
    """每次返同 marks/url → fingerprint 永同 → 触发 reflect hint。"""
    # V0.22.4: perceive 返三-tuple
    return list(_STUCK_MARKS), _FAKE_SHOT, []


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def patch_loop_internals(monkeypatch):
    monkeypatch.setattr("web_agent.loop.think", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_click", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_type", _noop)
    monkeypatch.setattr("web_agent.loop.scroll", _noop)
    # captcha_detect 默认对 FakePage 正常返 None (FakePage 缺 evaluate, except Exception → None)


async def test_reflect_hint_injected_when_page_stuck_3_steps(
    monkeypatch, tmp_path, patch_loop_internals
):
    """4 步全 stuck; 用不同 scroll dy 避 V0.5.0 anti-loop 提前 abort, 再 done 收尾。"""
    monkeypatch.setattr("web_agent.loop.perceive", _stuck_perceive)

    client = RecordingLLMClient([
        ScrollAction(thought="试 scroll 1", dy=100),
        ScrollAction(thought="试 scroll 2", dy=200),
        ScrollAction(thought="试 scroll 3", dy=300),
        DoneAction(thought="收尾", result="fin"),
    ])

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _ctx(), client, goal="测 reflect",
        max_steps=5, db_path=db, screenshots_dir=shots,
    )

    assert result == "fin"
    # plan 调 4 次; reflect hint 在 step_i=2 perceive 后 fire (deque 满 + 全同),
    # 此时 trace.steps[-1] = step1, mutate step1.observation, 然后 plan(2) 立即看到。
    #   call 0: trace 空                                                 — 无 reflect
    #   call 1: trace = [step0 obs]                                      — 无 reflect (deque len=1)
    #   call 2: trace = [step0 obs, step1 obs MUTATED]                   — **含 reflect** (刚 fire)
    #   call 3: trace = [step0, step1 MUTATED, step2 obs]                — 仍含 reflect (持续注入)
    assert len(client.observed_traces) == 4
    assert "[reflect]" not in "\n".join(client.observed_traces[0]), \
        f"call 0 (trace 空) 不应见 reflect: {client.observed_traces[0]}"
    assert "[reflect]" not in "\n".join(client.observed_traces[1]), \
        f"call 1 (deque len=1) 不应见 reflect: {client.observed_traces[1]}"
    assert any("[reflect]" in s for s in client.observed_traces[2]), \
        f"call 2 (deque 满刚 fire) 应有 [reflect]: {client.observed_traces[2]}"
    assert any("[reflect]" in s for s in client.observed_traces[3]), \
        f"call 3 (持续注入) 应有 [reflect]: {client.observed_traces[3]}"


async def test_reflect_not_injected_when_marks_change(
    monkeypatch, tmp_path, patch_loop_internals
):
    """每步 mark id 不同 → fingerprint 永不同 → 全程不注入 hint。"""
    counter = {"n": 0}

    async def varying_perceive(page):
        counter["n"] += 1
        # V0.22.4: perceive 返三-tuple
        return [_mk(counter["n"], f"btn-{counter['n']}")], _FAKE_SHOT, []

    monkeypatch.setattr("web_agent.loop.perceive", varying_perceive)

    client = RecordingLLMClient([
        ScrollAction(thought="x", dy=100),
        ScrollAction(thought="x", dy=200),
        ScrollAction(thought="x", dy=300),
        DoneAction(thought="x", result="fin"),
    ])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _ctx(), client, goal="测 not stuck",
        max_steps=5, db_path=db, screenshots_dir=shots,
    )

    assert result == "fin"
    for i, snap in enumerate(client.observed_traces):
        assert all("[reflect]" not in s for s in snap), \
            f"call {i} 不该有 [reflect]: {snap}"


async def test_reflect_idempotent_no_double_append(
    monkeypatch, tmp_path, patch_loop_internals
):
    """连续 5 步 stuck, 同一个 step.observation 不该被 append 多个 [reflect]。"""
    monkeypatch.setattr("web_agent.loop.perceive", _stuck_perceive)

    client = RecordingLLMClient([
        ScrollAction(thought="x", dy=100),
        ScrollAction(thought="x", dy=200),
        ScrollAction(thought="x", dy=300),
        ScrollAction(thought="x", dy=400),
        ScrollAction(thought="x", dy=500),
        DoneAction(thought="x", result="fin"),
    ])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    await run_react_loop(
        _ctx(), client, goal="测 idempotent",
        max_steps=7, db_path=db, screenshots_dir=shots,
    )

    # 最后一次 plan call 看到的 trace, 检查每个 obs 最多一个 [reflect] 标记
    final_trace = client.observed_traces[-1]
    for obs in final_trace:
        assert obs.count("[reflect]") <= 1, f"{obs!r} 含多个 [reflect]"
