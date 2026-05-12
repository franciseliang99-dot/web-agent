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
    """V0.46.1 update: ExtractAction sig drop answer (LLM noise) + normalize query.

    旧测期望 answer 中文 in sig, V0.46.1 后 sig 仅含 normalize(query). 测改为 query 中文保留.
    """
    a = ExtractAction(thought="x", query="量子纠缠 points", answer="LLM 噪音")
    sig = _action_signature(a)
    assert "量子纠缠" in sig  # V0.46.1: normalize 保 CJK 字符


def test_signature_extract_drops_answer_v046_1() -> None:
    """V0.46.1: ExtractAction sig 不含 answer (LLM 生成 noise, 每次反复试都不同 → V0.44 anti_loop miss 根因)."""
    a = ExtractAction(thought="x", query="读取 points", answer="LLM 答案 abc")
    sig = _action_signature(a)
    assert "LLM 答案 abc" not in sig
    assert "abc" not in sig
