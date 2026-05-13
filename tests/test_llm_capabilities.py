"""LLM vision-capability lookup 单测。

V0.66.3 TDD red 阶段：本测试文件先于实现存在，驱动 src/web_agent/llm/_capabilities.py 落地。
实现尚不存在时，本文件全红（ImportError 即可），等绿后再 simplify。

接口契约（详见任务 prompt）：
- is_vision_capable(model: str) -> bool
- assert_vision_capable(provider: str, model: str) -> None  # 不支持时 raise RuntimeError
"""

from __future__ import annotations

import pytest

from web_agent.llm._capabilities import (  # noqa: E402
    assert_vision_capable,
    is_vision_capable,
)


# ---------------------------------------------------------------------------
# is_vision_capable — vision-capable models (True)
# ---------------------------------------------------------------------------


def test_is_vision_capable_claude_sonnet_46_true():
    assert is_vision_capable("claude-sonnet-4-6") is True


def test_is_vision_capable_gpt_4o_mini_true():
    assert is_vision_capable("gpt-4o-mini") is True


def test_is_vision_capable_kimi_k26_true():
    assert is_vision_capable("kimi-k2.6") is True


def test_is_vision_capable_qwen3_vl_32b_true():
    assert is_vision_capable("qwen3-vl-32b-instruct") is True


def test_is_vision_capable_qwen2_5_vl_72b_true():
    assert is_vision_capable("qwen2.5-vl-72b-instruct") is True


def test_is_vision_capable_qwen3_vl_openrouter_prefix_true():
    # OpenRouter "<vendor>/<model>" 前缀也要识别
    assert is_vision_capable("qwen/qwen3-vl-32b-instruct") is True


# ---------------------------------------------------------------------------
# is_vision_capable — text-only models (False)
# ---------------------------------------------------------------------------


def test_is_vision_capable_deepseek_chat_false():
    assert is_vision_capable("deepseek-chat") is False


def test_is_vision_capable_deepseek_v4_flash_false():
    assert is_vision_capable("deepseek-v4-flash") is False


def test_is_vision_capable_qwen3_instruct_false():
    # 关键 boundary: qwen3-instruct 跟 qwen3-vl-* 都 startswith "qwen3-"，
    # 实现得用更细前缀（e.g. "qwen3-vl-"）区分，不能简单按 "qwen3-" 一刀切。
    assert is_vision_capable("qwen3-instruct") is False


def test_is_vision_capable_qwen_turbo_false():
    assert is_vision_capable("qwen-turbo") is False


def test_is_vision_capable_o1_mini_false():
    # o1-mini 是 text-only，跟 o1 / o3 / o4-mini 不同
    assert is_vision_capable("o1-mini") is False


# ---------------------------------------------------------------------------
# is_vision_capable — unknown model (True + warning)
# ---------------------------------------------------------------------------


def test_is_vision_capable_unknown_model_defaults_true_with_warning():
    with pytest.warns(Warning):
        result = is_vision_capable("some-future-model-2099")
    assert result is True


# ---------------------------------------------------------------------------
# assert_vision_capable — guard
# ---------------------------------------------------------------------------


def test_assert_vision_capable_deepseek_raises_runtime_error_with_hint():
    with pytest.raises(RuntimeError) as exc_info:
        assert_vision_capable("deepseek", "deepseek-chat")
    msg = str(exc_info.value)
    assert "deepseek-chat" in msg
    assert "vision" in msg.lower()


def test_assert_vision_capable_qwen3_vl_passes():
    # 不抛 = pass；显式断言返回 None 以锁契约
    assert assert_vision_capable("openrouter", "qwen3-vl-32b-instruct") is None


def test_assert_vision_capable_error_message_contains_alternative():
    with pytest.raises(RuntimeError) as exc_info:
        assert_vision_capable("deepseek", "deepseek-chat")
    msg = str(exc_info.value)
    # 错误消息得给操作员可执行的替代 model 建议
    alternatives = ("gpt-4o-mini", "claude-sonnet-4.6", "kimi-k2.6", "qwen3-vl")
    assert any(alt in msg for alt in alternatives), (
        f"error message must suggest at least one alternative model from {alternatives}, "
        f"got: {msg!r}"
    )
