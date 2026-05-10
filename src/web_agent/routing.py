"""V0.27.3: 数据驱动的 LLM provider routing.

按 CapabilityAxis (eval/types.py 12 项 Literal) 在多 provider 都可用时, 选 baseline 矩阵
里 pass rate 最高的 provider. 缺数据 / available∩baseline=∅ → fallback 'anthropic'
(符合 make_client 现 default).

V0.27.3 scope: 纯函数 + 内部 baseline 字面量, 不接 cli/mcp/jd/list flag (V0.27.5 真消费时连线).

V0.27 现状 (subagent 审决): baseline JSON (data/eval/*.json) **不在 wheel** (pyproject
hatch.build.targets.wheel.packages 只含 src/web_agent + eval), pip install 用户机器无文件
→ 用 _DEFAULT_BASELINE_KIMI frozen dict 字面量, 0 IO + 0 packaging 改. JSON 留 eval
产物归档, routing.py 不依赖文件系统.

V0.27 仅 Kimi-only baseline (V0.27.0 Anthropic baseline 推迟到用户拿到 key 后跑):
缺 'retry'/'backtrack'/'real-world' 3 axis (V0.26 corpus 未覆盖) + Anthropic 全空白 →
绝大多数 axis 都 fallback anthropic. V0.27.0 跑完后 _DEFAULT_BASELINE 加 anthropic 列即生效.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eval.types import CapabilityAxis

# V0.27.3: V0.26.4 真跑数据 (data/eval/baseline-V0.26.4-kimi.json), 字面量化避 wheel 缺文件.
# 9 axis 实测 (V0.26 corpus 含覆盖 task), 3 axis 暂缺 (retry/backtrack/real-world V0.26 未 cover).
# Provider 名 "openai-kimi" 是评测 SKU 标签 (区分 OpenAIClient 跑 Kimi vs GPT base_url),
# 出口 _PROVIDER_TO_CLIENT 映射回 make_client wire protocol "openai".
_DEFAULT_BASELINE_KIMI: dict[str, dict[str, float]] = {
    "openai-kimi": {
        "baseline": 0.0,
        "multi-tab": 1.0,
        "iframe": 0.0,
        "drag": 0.0,
        "upload": 0.0,
        "download": 0.0,
        "dialog": 0.0,
        "keyboard-nav": 0.0,
        "failure-recovery": 1.0,
    },
}

# V0.27.3: routing 出口名 → make_client wire protocol 映射. 评测层用 "openai-kimi"
# 区分 OpenAIClient 后端 (Kimi vs GPT 跑同一 OpenAIClient + 不同 OPENAI_BASE_URL),
# 但 make_client 只识 "anthropic"/"openai". 这层映射不污染 make_client 命名空间.
_PROVIDER_TO_CLIENT: dict[str, str] = {
    "openai-kimi": "openai",
    "anthropic": "anthropic",
    "openai": "openai",
}

# V0.27.3: fallback 跟 make_client default 一致 (web_agent/llm/__init__.py:73).
_DEFAULT_FALLBACK = "anthropic"


def available_providers_from_env() -> list[str]:
    """V0.27.3: 按 env API key 推断当前可用 provider 列表.

    返 routing 词汇表 ("anthropic"/"openai"), 不是 SKU. routing.py 内部映射 SKU → 词汇表
    再 intersect.
    """
    out: list[str] = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        out.append("anthropic")
    if os.environ.get("OPENAI_API_KEY"):
        out.append("openai")
    return out


def select_provider(
    axis: "CapabilityAxis",
    baseline_matrix: dict[str, dict[str, float]] | None = None,
    available_providers: list[str] | None = None,
) -> str:
    """按 baseline matrix 选 axis 上 pass rate 最高的可用 provider.

    Args:
        axis: CapabilityAxis Literal (eval/types.py 12 项).
        baseline_matrix: {provider_sku: {axis: pass_rate}}. 默 None → V0.26.4 Kimi-only 字面量.
        available_providers: routing 词汇表子集 ("anthropic"/"openai"). 默 None → env 推断.

    Returns:
        make_client 接受的 provider 名 ("anthropic"/"openai"), 已经过 SKU → 词汇表映射 +
        available_providers 过滤. caller 拿到后 `make_client(provider=ret, secret_store=...)`
        透传 V0.27.1 vault.

    Fallback 'anthropic' 触发条件 (任一):
        1. axis 不在 baseline_matrix 任何 provider 数据里 (e.g. 'retry'/'backtrack')
        2. baseline_matrix[provider][axis] 全 0.0 (无 provider 在该 axis 有信号)
        3. argmax 选出的 provider 映射后不在 available_providers 里 (例如 baseline 唯一非零是
           openai-kimi 但用户只装 anthropic)
        4. baseline_matrix 为空
    """
    matrix = baseline_matrix if baseline_matrix is not None else _DEFAULT_BASELINE_KIMI
    available = (
        available_providers if available_providers is not None else available_providers_from_env()
    )

    # 收集 axis 上有非零 pass rate 的 (provider_sku, score)
    candidates: list[tuple[str, float]] = []
    for provider_sku, axis_scores in matrix.items():
        score = axis_scores.get(axis, 0.0)
        if score > 0.0:
            candidates.append((provider_sku, score))

    if not candidates:
        return _DEFAULT_FALLBACK  # case 1+2+4

    # argmax (稳定: tie 取首遇)
    candidates.sort(key=lambda x: x[1], reverse=True)

    # 出口 SKU → wire protocol + available 过滤. 必须 argmax 之后过滤
    # (subagent 提的边界: 否则会选中不可用 provider).
    for provider_sku, _score in candidates:
        wire = _PROVIDER_TO_CLIENT.get(provider_sku, _DEFAULT_FALLBACK)
        if wire in available:
            return wire

    return _DEFAULT_FALLBACK  # case 3


__all__ = ["available_providers_from_env", "select_provider"]
