"""V0.45.1 真发现 #24 follow-up regression test — V0.44.0 audit 真实 false-pos + 真支付 fixture.

V0.44.0 trace.db audit catch SAFETY_BLOCK 8/8 任务全是 safety:send-or-pay predicate 假阳性
('Publish'/'Submit'/'Submit order' 误判). V0.45.1 删 generic 动词 submit|publish|post|order
standalone, 本测保证:

1. **False-positive releases** (V0.44 audit 8/8 真实 case 应 allow=True):
   - 'Publish' × 6 (demo button)
   - 'Submit order' × 1 (httpbin pizza form)
   - 'Submit' × 1 (DDG search)
   + 防回归扩展 'Post' / 'Publish Article' / 'Order History' / 'Sort Order'
2. **True-positive still blocks** (真支付 fixture 应 allow=False):
   - 英文: Pay Now / Confirm Payment / Place Order / Withdraw $500 / Checkout
   - 中文: 立即支付 / 下单 / 确认订单 / 转账

未覆盖 (V0.45 保守不动, V0.46+ scope):
- `send` standalone — V0.44 audit 无 false-pos evidence, 'Send Email' 仍拦
- `delete|remove` rule name 错位 — 'send-or-pay' 不含 destructive
"""

from __future__ import annotations

import pytest

from web_agent.safety import check
from web_agent.types import ClickAction, Mark


def _btn(text: str) -> Mark:
    """Helper: button mark with given text."""
    return Mark(
        id=1, tag="button", role="", text=text,
        bbox={"x": 0, "y": 0, "w": 100, "h": 30},
        input_type="", name="", href="",
    )


def _click() -> ClickAction:
    return ClickAction(thought="test click", mark_id=1)


# --- V0.44 audit 真实 false-pos releases ---

@pytest.mark.parametrize("text", [
    "Publish",          # × 6 in V0.44 audit (demo 'Type here' input + 'Publish' button)
    "Submit order",     # × 1 in V0.44 audit (httpbin pizza form)
    "Submit",           # × 1 in V0.44 audit (DDG search)
    "Post",             # 防回归: forum/blog post 按钮
    "Publish Article",  # 防回归: dev.to / Medium 等 publish 按钮
    "Order History",    # 防回归: 'order' standalone 删后 'Order History' 不再误拦
    "Sort Order",       # 防回归: UI sort 控件
])
def test_v044_false_positive_releases_allow_true(text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """V0.45.1: V0.44.0 audit 8/8 真实 false-pos case + 防回归扩展全 allow=True."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    decision = check(_click(), _btn(text), [])
    assert decision.allow, (
        f"V0.45.1 真发现 #24 fix 回归: {text!r} 应 allow=True (V0.44 audit 真实 false-pos) "
        f"但被规则 {decision.rule!r} 拦下"
    )


# --- True-positive still blocks (V0.45 保守保留真支付) ---

@pytest.mark.parametrize("text,expected_rule", [
    # V0.49.1: send-or-pay rule 收窄到明确支付动词
    ("Pay Now", "send-or-pay"),
    ("Confirm Payment", "send-or-pay"),
    ("Place Order", "send-or-pay"),
    ("Checkout", "send-or-pay"),
    ("Buy Now", "send-or-pay"),
    ("Authorize Payment", "send-or-pay"),
    ("Approve Transfer", "send-or-pay"),  # approve 优先命中 send-or-pay (transfer 也在 destructive 但顺序后)
    # V0.49.1 新 destructive-action rule
    ("Withdraw $500", "destructive-action"),
    ("Delete Account", "destructive-action"),
    ("Wire Transfer", "destructive-action"),
    # V0.49.1 新 send-amount rule
    ("Send $50", "send-amount"),
    ("Send 100 USD", "send-amount"),
])
def test_v045_true_positive_english_still_blocks(
    text: str, expected_rule: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V0.45.1 + V0.49.1: 真支付/destructive/send-amount 动词仍 allow=False (false-neg 防回归)."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    decision = check(_click(), _btn(text), [])
    assert not decision.allow, f"V0.49.1: {text!r} 应 allow=False 但放行 (false-neg 回归)"
    assert decision.rule == expected_rule, (
        f"{text!r} 应触发 {expected_rule!r} 规则 (got {decision.rule!r})"
    )


@pytest.mark.parametrize("text,expected_rule", [
    # V0.49.1: zh-send-or-pay rule 收窄
    ("立即支付", "zh-send-or-pay"),
    ("下单", "zh-send-or-pay"),
    ("确认订单", "zh-send-or-pay"),
    ("立即购买", "zh-send-or-pay"),
    ("确认支付", "zh-send-or-pay"),
    # V0.49.1 新 zh-destructive-action
    ("转账", "zh-destructive-action"),
    ("删除文件", "zh-destructive-action"),
    ("提款", "zh-destructive-action"),
    # V0.49.1 新 zh-send-amount
    ("发送 ¥50", "zh-send-amount"),
])
def test_v045_true_positive_chinese_still_blocks(
    text: str, expected_rule: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V0.45.1 + V0.49.1: 中文真支付/destructive/send-amount 动词仍 allow=False (false-neg 防回归)."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    decision = check(_click(), _btn(text), [])
    assert not decision.allow, f"V0.49.1: {text!r} 应 allow=False 但放行"
    assert decision.rule == expected_rule, (
        f"{text!r} 应触发 {expected_rule!r} 规则 (got {decision.rule!r})"
    )


# --- 中文 generic 动词释放 (V0.45.1 删 发布|提交) ---

@pytest.mark.parametrize("text", [
    "发布",   # V0.45.1: dev.to 中文 publish
    "提交",   # V0.45.1: 表单 submit 中文
    "发布文章",  # V0.45.1: 防回归扩展
])
def test_v045_chinese_generic_verbs_release(text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """V0.45.1: 中文 generic 动词 发布|提交 释放 (跟英文 submit/publish 对偶)."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    decision = check(_click(), _btn(text), [])
    assert decision.allow, (
        f"V0.45.1 真发现 #24 fix 中文 mirror: {text!r} 应 allow=True 但被规则 "
        f"{decision.rule!r} 拦下"
    )
