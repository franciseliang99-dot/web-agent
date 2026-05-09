"""集成测试: safety_check + run_react_loop + trace 三件套联动。

不真起 chrome / 不真调 LLM。用 fake page + fake LLMClient + monkeypatch 关 actuator/perceive,
覆盖 test_safety.py 纯函数测试盖不到的「safety 触发 → loop graceful abort → trace 落库」端到端路径。

两个场景:
  1. 默认 (无 AUTO_APPROVE): click Send 按钮 → safety_block → loop return SAFETY_BLOCK 字符串
  2. AUTO_APPROVE=send-or-pay: 同样 click Send → 放行 → 第二步 done → return result
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from web_agent.types import Action, ClickAction, DoneAction
from web_agent.loop import run_react_loop
from web_agent.perceiver import Mark


_SEND_BUTTON = Mark(
    id=1, tag="button", role="button", text="Send",
    bbox={"x": 0, "y": 0, "w": 80, "h": 30},
    input_type="", name="", href="",
)
# 8-byte 占位 (loop.py write_bytes(b64decode(...)) 需要合法 base64)
_FAKE_SHOT_B64 = "aGVsbG8h"


class FakeLLMClient:
    """按调用次数依次返回预设 Action; 用尽则重复最后一个。"""

    name = "fake"
    model = "fake"

    def __init__(self, actions: list[Action]) -> None:
        self._actions = list(actions)
        self._i = 0

    async def plan(self, goal, screenshot_b64, marks, trace) -> Action:
        a = self._actions[min(self._i, len(self._actions) - 1)]
        self._i += 1
        return a


class FakePage:
    """最小 Page stub: loop.py 直接调到的方法 (wait_for_load_state / keyboard.press)。

    perceive / human_like_click / human_like_type / scroll / think 全部由 fixture monkeypatch
    成 no-op, 这里 Page 本身不需要更多接口。
    """

    class _Keyboard:
        async def press(self, key: str) -> None:
            return None

    keyboard = _Keyboard()

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        return None


async def _fake_perceive(page):
    return [_SEND_BUTTON], _FAKE_SHOT_B64


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def patch_loop_internals(monkeypatch):
    """patch 掉 loop.py 引用的所有真实 IO 副作用 (perceive 走网络/think 真 sleep/click 操作 page)。"""
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


async def test_send_click_default_blocked_writes_safety_step(
    monkeypatch, tmp_path, patch_loop_internals
):
    """场景 1: 默认无 AUTO_APPROVE; LLM 想 click Send mark → safety abort + trace 落 safety_block 步。"""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    client = FakeLLMClient([
        ClickAction(thought="点 Send 发邮件", mark_id=1),
    ])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        FakePage(), client, goal="测试 W3-C send",
        max_steps=3, db_path=db, screenshots_dir=shots,
    )

    assert result.startswith("SAFETY_BLOCK at step 0"), f"unexpected result: {result!r}"
    assert "send-or-pay" in result, f"应含规则名: {result!r}"

    steps = _read_trace_steps(db)
    assert len(steps) == 1, f"应只有 1 step, got {len(steps)}"
    step_i, action_type, action_args = steps[0]
    assert step_i == 0
    assert action_type == "safety_block"
    assert action_args["original_type"] == "click"
    assert action_args["rule"] == "send-or-pay"
    assert action_args["mark_id"] == 1


async def test_send_click_auto_approved_proceeds_to_done(
    monkeypatch, tmp_path, patch_loop_internals
):
    """场景 2: AUTO_APPROVE=send-or-pay 后, click Send 放行, 第二步 done 正常返回。"""
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "send-or-pay")

    client = FakeLLMClient([
        ClickAction(thought="点 Send", mark_id=1),
        DoneAction(thought="完成", result="sent"),
    ])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        FakePage(), client, goal="测试 W3-C send (授权)",
        max_steps=4, db_path=db, screenshots_dir=shots,
    )

    assert result == "sent", f"应返回 done.result, got {result!r}"

    steps = _read_trace_steps(db)
    types = [s[1] for s in steps]
    assert "safety_block" not in types, f"AUTO_APPROVE 后不应有 safety_block: {types}"
    assert "click" in types, f"应记录 click 步: {types}"
    assert "done" in types, f"应记录 done 步: {types}"


async def test_wildcard_auto_approve_also_allows_send(
    monkeypatch, tmp_path, patch_loop_internals
):
    """边界: AUTO_APPROVE=* 也能放行 send-or-pay (通配符路径)。"""
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "*")

    client = FakeLLMClient([
        ClickAction(thought="点 Send", mark_id=1),
        DoneAction(thought="完成", result="ok"),
    ])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        FakePage(), client, goal="测试 wildcard",
        max_steps=4, db_path=db, screenshots_dir=shots,
    )
    assert result == "ok"
    types = [s[1] for s in _read_trace_steps(db)]
    assert "safety_block" not in types


# V0.18.0 elicitation callback path —————————————————————————————————————

async def test_safety_callback_accept_proceeds(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.18.0: callback 返 True (用户 elicit accept) → 放行继续 + 落 safety_elicited_approve step。"""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    elicit_calls: list[tuple[str, str]] = []

    async def approve_cb(rule: str, reason: str) -> bool:
        elicit_calls.append((rule, reason))
        return True

    client = FakeLLMClient([
        ClickAction(thought="点 Send", mark_id=1),
        DoneAction(thought="完成", result="elicit-sent"),
    ])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        FakePage(), client, goal="测试 elicit accept",
        max_steps=4, db_path=db, screenshots_dir=shots,
        safety_approval_cb=approve_cb,
    )

    assert result == "elicit-sent", f"放行后应跑到 done, got {result!r}"
    assert len(elicit_calls) == 1, f"safety 命中 1 次应触发 1 次 elicit, got {elicit_calls!r}"
    assert elicit_calls[0][0] == "send-or-pay"

    steps = _read_trace_steps(db)
    types = [s[1] for s in steps]
    assert "safety_block" not in types, f"放行后不应 abort: {types}"
    assert "click" in types
    assert "done" in types

    # V0.18.0: elicit 放行的 click step 在 action_args 带 elicited_approval_rule 标记
    click_step = next(s for s in steps if s[1] == "click")
    assert click_step[2].get("elicited_approval_rule") == "send-or-pay", \
        f"click step action_args 应含 elicit 放行标记: {click_step[2]!r}"


async def test_safety_callback_decline_blocks(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.18.0: callback 返 False (用户 elicit decline) → 维持 abort + 落 safety_block step。"""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    async def decline_cb(rule: str, reason: str) -> bool:
        return False

    client = FakeLLMClient([
        ClickAction(thought="点 Send", mark_id=1),
    ])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        FakePage(), client, goal="测试 elicit decline",
        max_steps=3, db_path=db, screenshots_dir=shots,
        safety_approval_cb=decline_cb,
    )

    assert result.startswith("SAFETY_BLOCK"), f"decline 应 abort: {result!r}"
    types = [s[1] for s in _read_trace_steps(db)]
    assert "safety_block" in types
    assert "safety_elicited_approve" not in types


async def test_safety_callback_exception_treated_as_decline(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.18.0: callback raise → 兜底视作 decline (安全 default), 不让 elicit 失败崩 loop。"""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    async def buggy_cb(rule: str, reason: str) -> bool:
        raise RuntimeError("client 不支持 elicitation")

    client = FakeLLMClient([
        ClickAction(thought="点 Send", mark_id=1),
    ])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        FakePage(), client, goal="测试 elicit exception",
        max_steps=3, db_path=db, screenshots_dir=shots,
        safety_approval_cb=buggy_cb,
    )

    assert result.startswith("SAFETY_BLOCK"), f"callback 异常应等同 decline: {result!r}"
    types = [s[1] for s in _read_trace_steps(db)]
    assert "safety_block" in types
    assert "safety_elicited_approve" not in types
