"""safety.py 纯函数单测：覆盖 click 黑名单 / type 敏感字段 / auto_approve env / 边界。"""

from __future__ import annotations

import pytest

from web_agent.types import Action, ClickAction, DoneAction, ExtractAction, ScrollAction, TypeAction
from web_agent.perceiver import Mark
from web_agent.safety import check


def _btn(text: str, **kw) -> Mark:
    return Mark(
        id=1, tag="button", role="", text=text,
        bbox={"x": 0, "y": 0, "w": 80, "h": 30},
        input_type=kw.get("input_type", ""),
        name=kw.get("name", ""),
        href=kw.get("href", ""),
    )


def _input(input_type: str = "text", name: str = "") -> Mark:
    return Mark(
        id=2, tag="input", role="", text="",
        bbox={"x": 0, "y": 0, "w": 200, "h": 30},
        input_type=input_type, name=name, href="",
    )


def _click(mark_id: int = 1) -> Action:
    return ClickAction(thought="x", mark_id=mark_id)


def _type(text: str = "hi") -> Action:
    return TypeAction(thought="x", text=text)


# --- click 按钮文本黑名单 ---

@pytest.mark.parametrize("text,should_block", [
    ("Send", True),
    ("Send Email", True),
    ("Pay Now", True),
    ("Delete", True),
    ("Confirm Payment", True),
    ("Place Order", True),
    ("Withdraw $500", True),
    ("Subscribe", False),  # 订阅 ≠ unsubscribe
    ("Unsubscribe", True),
    ("Cancel Subscription", True),
    ("Search", False),
    ("Sender Name", False),  # word boundary 防 "sender" 误撞 "send"
    ("Login", False),
    ("Submit", True),
])
def test_click_button_text_english(text, should_block, monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _btn(text), [])
    if should_block:
        assert not d.allow, f"{text!r} 应被拦"
        assert d.rule
    else:
        assert d.allow, f"{text!r} 不该被拦 (got rule={d.rule!r})"


@pytest.mark.parametrize("text,should_block", [
    ("发送", True),
    ("立即支付", True),
    ("删除", True),
    ("确认订单", True),
    ("转账", True),
    ("注销账号", True),
    ("搜索", False),
    ("登录", False),
    ("查看", False),
])
def test_click_button_text_chinese(text, should_block, monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _btn(text), [])
    assert d.allow != should_block, (
        f"{text!r}: expected blocked={should_block}, got rule={d.rule!r}"
    )


# --- click 敏感 input ---

def test_click_password_input_blocked(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _input(input_type="password"), [])
    assert not d.allow
    assert d.rule == "input-type-sensitive"


def test_click_tel_input_blocked(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _input(input_type="tel", name="otp"), [])
    assert not d.allow


def test_click_normal_text_input_allowed(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _input(input_type="text", name="search"), [])
    assert d.allow


def test_click_amount_named_input_blocked(monkeypatch):
    """input name 含 amount/cvv/card 等关键词应拦。"""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _input(input_type="text", name="amount"), [])
    assert not d.allow
    assert "name" in d.rule


# --- type 到敏感字段 ---

def test_type_into_password_blocked(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_type("secret"), _input(input_type="password"), [])
    assert not d.allow


def test_type_into_amount_input_blocked(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_type("100"), _input(input_type="text", name="amount"), [])
    assert not d.allow


def test_type_into_search_input_allowed(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_type("query"), _input(input_type="text", name="search"), [])
    assert d.allow


# --- auto_approve env ---

def test_auto_approve_single_rule(monkeypatch):
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "send-or-pay")
    d = check(_click(), _btn("Send"), [])
    assert d.allow


def test_auto_approve_csv_multiple(monkeypatch):
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "send-or-pay,zh-send-or-pay,input-type-sensitive")
    assert check(_click(), _btn("Send"), []).allow
    assert check(_click(), _btn("发送"), []).allow
    assert check(_click(), _input(input_type="password"), []).allow


def test_auto_approve_wildcard(monkeypatch):
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "*")
    assert check(_click(), _btn("Delete"), []).allow
    assert check(_click(), _btn("立即支付"), []).allow
    assert check(_click(), _input(input_type="password"), []).allow
    assert check(_type(), _input(input_type="password"), []).allow


def test_auto_approve_unset_blocks(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _btn("Send"), [])
    assert not d.allow


# --- 边界 ---

def test_scroll_extract_done_always_allowed():
    # V0.17.0: dispatch 5 dataclass (此前 Action(type=atype, args={}, thought="x") 一律 fail)
    actions: list[Action] = [
        ScrollAction(thought="x", dy=0),
        ExtractAction(thought="x", query="", answer=""),
        DoneAction(thought="x", result=""),
    ]
    for a in actions:
        assert check(a, None, []).allow


def test_click_with_no_mark_allowed():
    """mark=None 不该崩（虽然实际 loop 不会传 None for click）。"""
    d = check(_click(), None, [])
    assert d.allow


def test_empty_text_button_allowed(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _btn(""), [])
    assert d.allow


def test_case_insensitive_match(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    assert not check(_click(), _btn("SEND"), []).allow
    assert not check(_click(), _btn("send"), []).allow
    assert not check(_click(), _btn("SeNd"), []).allow
