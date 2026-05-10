"""V0.27.3 routing 单测: select_provider 数据驱动 + fallback 边界.

覆盖 6 测 (subagent 审降 15 → 6 + 漏一边界 case):
1. 12 axis parametrize (含 Kimi 强项 multi-tab/failure-recovery + 7 项 0.0 fallback)
2. 缺 axis (e.g. 'retry') fallback
3. available_providers=[] fallback
4. 显式 baseline_matrix 覆盖 default
5. openai-kimi → openai 映射 (SKU → wire protocol)
6. **关键边界** (subagent 漏): available=['anthropic'] 但 baseline 唯一非零是 openai-kimi
   → fallback anthropic (argmax 之后 intersect available, 不能选不可用 provider)
"""

from __future__ import annotations

from typing import get_args

import pytest

from eval.types import CapabilityAxis
from web_agent.routing import (
    _DEFAULT_BASELINE_KIMI,
    _DEFAULT_FALLBACK,
    available_providers_from_env,
    select_provider,
)

# V0.27.3: 12 axis 全列举测 (从 Literal get_args 自动同步, 加新 axis 不必改测).
ALL_AXES: tuple[CapabilityAxis, ...] = get_args(CapabilityAxis)


@pytest.mark.parametrize("axis", ALL_AXES)
def test_select_provider_default_baseline_kimi(axis: CapabilityAxis, monkeypatch):
    """V0.27.3: 默 baseline (Kimi-only) + 双 provider 都装时, 12 axis 各自走 routing.

    Kimi 强项 (multi-tab/failure-recovery pass=1.0) → 选 'openai';
    其余 7 axis 全 0.0 → fallback 'anthropic';
    缺数据 3 axis (retry/backtrack/real-world) → fallback 'anthropic'.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    result = select_provider(axis)

    kimi_strong: set[CapabilityAxis] = {"multi-tab", "failure-recovery"}
    if axis in kimi_strong:
        assert result == "openai", f"axis {axis!r}: Kimi 强项应选 openai, 实 {result!r}"
    else:
        assert result == _DEFAULT_FALLBACK == "anthropic", (
            f"axis {axis!r}: Kimi 弱/缺数据应 fallback anthropic, 实 {result!r}"
        )


def test_select_provider_unknown_axis_fallback(monkeypatch):
    """V0.27.3 case 1: axis 不在 baseline 任何 provider 数据 → fallback."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # 'retry' V0.26 corpus 未 cover, Kimi baseline 缺数据
    result = select_provider("retry")
    assert result == "anthropic"


def test_select_provider_empty_available_providers_fallback():
    """V0.27.3 case 3: available_providers=[] → fallback anthropic 即使 baseline 有数据."""
    result = select_provider("multi-tab", available_providers=[])
    assert result == "anthropic"  # Kimi 强项但无 provider 可用 → fallback


def test_select_provider_explicit_baseline_matrix_overrides_default():
    """V0.27.3: 显式传 baseline_matrix → 覆盖 _DEFAULT_BASELINE_KIMI."""
    custom_matrix: dict[str, dict[str, float]] = {
        "anthropic": {"iframe": 0.85},
        "openai-kimi": {"iframe": 0.0},
    }
    result = select_provider(
        "iframe", baseline_matrix=custom_matrix, available_providers=["anthropic", "openai"],
    )
    assert result == "anthropic"  # 显式数据 anthropic 强 → 选 anthropic


def test_select_provider_openai_kimi_sku_mapped_to_openai_wire():
    """V0.27.3 case: SKU 'openai-kimi' 出口必须映射成 make_client 词汇表 'openai'."""
    custom_matrix: dict[str, dict[str, float]] = {
        "openai-kimi": {"multi-tab": 1.0},
    }
    result = select_provider(
        "multi-tab", baseline_matrix=custom_matrix, available_providers=["openai"],
    )
    assert result == "openai", "SKU 名 openai-kimi 不应泄漏到 make_client (该报 unknown provider)"


def test_select_provider_argmax_filtered_by_available_after_argmax():
    """V0.27.3 关键边界 (subagent 提): argmax 必须先选, 再过滤 available, 否则会
    错过 fallback 路径. baseline 唯一非零 openai-kimi, 用户只装 anthropic
    → argmax 选 openai-kimi → 映射 openai → not in [anthropic] → fallback anthropic.

    若 filter 在 argmax 前 (错实现): 候选只剩 anthropic 但 baseline anthropic=0.0
    → 错误地继续选 anthropic 但 reason 不是 fallback (无信号 vs 显式 fallback).
    本测断言 fallback 路径触发.
    """
    custom_matrix: dict[str, dict[str, float]] = {
        "openai-kimi": {"drag": 0.95},  # 只 Kimi 有 drag 数据
    }
    result = select_provider(
        "drag", baseline_matrix=custom_matrix, available_providers=["anthropic"],
    )
    assert result == _DEFAULT_FALLBACK == "anthropic"


# --- bonus: env-driven available_providers helper (1 测) ---


def test_available_providers_from_env_both_keys(monkeypatch):
    """V0.27.3: 两 key 都装 → 两 provider 都可用."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    out = available_providers_from_env()
    assert set(out) == {"anthropic", "openai"}


def test_available_providers_from_env_only_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = available_providers_from_env()
    assert out == ["anthropic"]


def test_available_providers_from_env_neither(monkeypatch):
    """V0.27.3: 两 key 都缺 → []. select_provider 后续 fallback anthropic
    (即使 anthropic 不可用, 调用 make_client 才真 raise — routing 不抢这个错)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = available_providers_from_env()
    assert out == []


# --- bonus: _DEFAULT_BASELINE_KIMI 数据完整性自检 ---


def test_default_baseline_kimi_has_only_known_axes():
    """V0.27.3: 字面量里 axis 名全在 CapabilityAxis Literal 12 项 (typo 自检)."""
    valid_axes = set(get_args(CapabilityAxis))
    for sku, axis_scores in _DEFAULT_BASELINE_KIMI.items():
        for axis in axis_scores:
            assert axis in valid_axes, (
                f"SKU {sku!r} 含未知 axis {axis!r} (应在 CapabilityAxis Literal 内)"
            )
