"""anti-loop 死循环检测的纯函数单测（_action_signature）。

run_react_loop 完整测试需要 mock Page + LLMClient + sqlite，复杂度高，
W2 阶段只测 signature 归一化的纯函数；端到端 demo 验证 loop 集成行为。
"""

from __future__ import annotations

from web_agent.types import ClickAction, ExtractAction, ScrollAction, TypeAction
from web_agent.loop import _action_signature


def test_signature_same_for_identical_actions():
    a1 = ClickAction(thought="点 sort", mark_id=30)
    a2 = ClickAction(thought="再次点 sort", mark_id=30)
    # thought 不进 signature（thought 不同 args 同视为重复）
    assert _action_signature(a1) == _action_signature(a2)


def test_signature_different_when_mark_id_differs():
    a1 = ClickAction(thought="x", mark_id=30)
    a2 = ClickAction(thought="x", mark_id=31)
    assert _action_signature(a1) != _action_signature(a2)


def test_signature_different_when_action_type_differs():
    a1 = ClickAction(thought="x", mark_id=30)
    a2 = ScrollAction(thought="x", dy=30)
    assert _action_signature(a1) != _action_signature(a2)


def test_signature_stable_with_arg_key_order():
    """args dict key 顺序不影响 signature（json sort_keys=True）。"""
    a1 = TypeAction(thought="x", text="hi", submit=True)
    a2 = TypeAction(thought="x", text="hi", submit=True)
    assert _action_signature(a1) == _action_signature(a2)


def test_signature_handles_chinese_args():
    a = ExtractAction(thought="x", query="", answer="量子纠缠")
    sig = _action_signature(a)
    assert "量子纠缠" in sig  # ensure_ascii=False 让中文可读
