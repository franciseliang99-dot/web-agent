"""V0.28.0 W6-A reflect 单测: should_reflect + build_reflect_prompt + parse_reflection 纯函数.

10 测覆盖:
- should_reflect parametrize 7 (max_steps/LOOP_DETECTED 触发 + WALLCLOCK/SAFETY/CAPTCHA/LLM_FAILED/成功 不触发)
- TRIGGERING_FAILURE_MARKERS 常量自检
- build_reflect_prompt 含 goal/trace/result + 空 trace 边界
- parse_reflection valid JSON / markdown fence tolerate / 无效 JSON fallback / 缺字段 fallback
- Reflection frozen+slots 跟 Action/Mark/Usage 一致
"""

from __future__ import annotations

import pytest

from web_agent.reflect import (
    TRIGGERING_FAILURE_MARKERS,
    Reflection,
    build_reflect_prompt,
    parse_reflection,
    should_reflect,
)


# --- should_reflect (subagent A 决: max_steps + LOOP_DETECTED 触发, 外因 + 成功 不触发) ---


@pytest.mark.parametrize("final_result,expected", [
    ("(max_steps 耗尽未完成)", True),  # max_steps marker
    ("LOOP_DETECTED 在 step 5...", True),  # LOOP_DETECTED marker
    ("WALLCLOCK_EXCEEDED at step 3", False),  # 外因不触发
    ("SAFETY_BLOCK at step 2: ...", False),  # 外因不触发
    ("CAPTCHA detected", False),  # 外因不触发
    ("LLM_FAILED: ...", False),  # infra fault 不触发
    ("result: 抓到了答案", False),  # 成功结果不触发
])
def test_should_reflect_trigger_matrix(final_result: str, expected: bool) -> None:
    assert should_reflect(final_result) is expected


def test_triggering_markers_constant():
    """V0.28.0: 当前 2 marker, V0.28.1 wire 时不应扩 (扩反范围会 over-trigger)."""
    assert TRIGGERING_FAILURE_MARKERS == frozenset({"max_steps", "LOOP_DETECTED"})


# --- build_reflect_prompt (subagent B 决: 文本 trace + V0.28.1 加 screenshot) ---


def test_build_reflect_prompt_contains_goal_trace_result():
    trace_steps = [
        {"step": 0, "thought": "first thought", "action": {"type": "click"}, "observation": "obs1"},
        {"step": 1, "thought": "second thought", "action": {"type": "type"}, "observation": "obs2"},
    ]
    prompt = build_reflect_prompt(
        goal="去网站搜苹果价格",
        trace_steps=trace_steps,
        final_result="(max_steps 耗尽未完成)",
    )
    assert "去网站搜苹果价格" in prompt
    assert "first thought" in prompt
    assert "second thought" in prompt
    assert "(max_steps 耗尽未完成)" in prompt
    assert "JSON" in prompt
    assert "root_cause" in prompt
    assert "hint" in prompt


def test_build_reflect_prompt_empty_trace_does_not_raise():
    """V0.28.0 边界: trace 为空 (max_steps=0 极端 case) 不应 raise."""
    prompt = build_reflect_prompt(goal="g", trace_steps=[], final_result="(max_steps)")
    assert "g" in prompt
    assert "0 steps" in prompt


# --- parse_reflection (subagent C 决: structured JSON + fallback 防阻塞 V0.28.1 wire) ---


def test_parse_reflection_valid_json():
    response = '{"root_cause": "页面加载慢", "hint": "下次先 wait_for_selector"}'
    r = parse_reflection(response)
    assert isinstance(r, Reflection)
    assert r.root_cause == "页面加载慢"
    assert r.hint == "下次先 wait_for_selector"


def test_parse_reflection_markdown_fence_tolerated():
    """V0.28.0: LLM 偶尔加 ```json ... ``` markdown fence (Anthropic Sonnet 习惯), parse 应 tolerate."""
    response = '```json\n{"root_cause": "rc", "hint": "h"}\n```'
    r = parse_reflection(response)
    assert r.root_cause == "rc"
    assert r.hint == "h"


def test_parse_reflection_invalid_json_fallback():
    """V0.28.0: parse 失败 fallback (root_cause=parse_failed + hint=raw text 截 200 char)."""
    response = "this is not JSON at all"
    r = parse_reflection(response)
    assert r.root_cause == "(reflect_parse_failed)"
    assert "this is not JSON" in r.hint


def test_parse_reflection_missing_required_fields_fallback():
    """V0.28.0: JSON 但缺 root_cause / hint 字段 → fallback (V0.28.1 wire 时 LLM schema 跑偏防御)."""
    response = '{"only_one_field": "x"}'
    r = parse_reflection(response)
    assert r.root_cause == "(reflect_parse_failed)"


def test_reflection_dataclass_is_frozen():
    """V0.28.0: Reflection frozen+slots 跟 Action/Mark/Usage 一致 (V0.28.2 inject memory 时
    hashable safe + 防 caller mutate)."""
    r = Reflection(root_cause="rc", hint="h")
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        r.root_cause = "new"  # type: ignore[misc]
