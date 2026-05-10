"""V0.26.2: LLM provider 价格表 (per million token, USD).

硬编 — 价格变化频率低 (Anthropic Sonnet 4.6 stable since 2026-Q1, OpenAI gpt-5.5 同档).
更新时改本表 + bump V0.26.x patch (eval baseline 数据需带 pricing 版本号防漂移).

数据来源 (2026-05 query): anthropic.com/pricing, openai.com/pricing, platform.moonshot.cn/pricing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """V0.26.2: 单 model 输入/输出 token 价 (USD per million tokens).

    cache 价 (anthropic prompt caching read 0.1× input) V0.26.2 不算 — eval cassette 复跑
    时不计 cache 折扣防 baseline 假低估; V0.26.3 cassette 模式可 mock cache hit ratio.
    """

    model: str
    input_usd_per_million: float
    output_usd_per_million: float


# V0.26.2: model name → pricing 反查 (V0.26.3 web-agent-eval CLI 启动时 lint 验所有 model 在表里).
PRICING: dict[str, ModelPricing] = {
    # Anthropic
    "claude-sonnet-4-6": ModelPricing(
        model="claude-sonnet-4-6", input_usd_per_million=3.0, output_usd_per_million=15.0,
    ),
    "claude-opus-4-7": ModelPricing(
        model="claude-opus-4-7", input_usd_per_million=15.0, output_usd_per_million=75.0,
    ),
    "claude-haiku-4-5-20251001": ModelPricing(
        model="claude-haiku-4-5-20251001",
        input_usd_per_million=0.8, output_usd_per_million=4.0,
    ),
    # OpenAI (gpt-5.5 价格占位, 2026-05 query 时调真值)
    "gpt-5.5": ModelPricing(
        model="gpt-5.5", input_usd_per_million=3.0, output_usd_per_million=15.0,
    ),
    "gpt-4o": ModelPricing(
        model="gpt-4o", input_usd_per_million=2.5, output_usd_per_million=10.0,
    ),
    # Kimi (Moonshot)
    "kimi-k2.6": ModelPricing(
        model="kimi-k2.6", input_usd_per_million=0.6, output_usd_per_million=2.5,
    ),
    "moonshot-v1-128k": ModelPricing(
        model="moonshot-v1-128k", input_usd_per_million=8.0, output_usd_per_million=24.0,
    ),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> tuple[float, float]:
    """V0.26.2: 算 (input_cost_usd, output_cost_usd). 未知 model → (0, 0) + 后续报告标 unknown.

    返 tuple 让 caller 分别累加 / 报告分开列 input vs output cost (高 output 任务诊断信号).
    """
    p = PRICING.get(model)
    if p is None:
        return 0.0, 0.0
    return (
        input_tokens * p.input_usd_per_million / 1_000_000,
        output_tokens * p.output_usd_per_million / 1_000_000,
    )
