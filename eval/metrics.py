"""V0.26.2: metrics aggregate + ProviderSummary + by-capability_axis 分组.

TaskMetric 在 runner.py (V0.26.0 已定义); metrics.py 加聚合层 + 跨 provider 对比 helper.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from eval.runner import TaskMetric
from eval.types import CapabilityAxis


@dataclass(frozen=True, slots=True)
class ProviderSummary:
    """V0.26.2: 单 provider 跨全 corpus 聚合 (一次 baseline run 输出 N=provider 数 个 summary)."""

    provider: str
    task_count: int
    pass_count: int
    pass_rate: float
    avg_steps: float
    median_wallclock_s: float
    total_input_tokens: int
    total_output_tokens: int
    total_input_cost_usd: float
    total_output_cost_usd: float
    failure_buckets: dict[str, int]  # bucket name → 命中数


def aggregate(metrics: list[TaskMetric]) -> dict[str, ProviderSummary]:
    """V0.26.2: 跨 task 聚合到 per-provider summary (pass_rate / cost / median_wallclock / buckets).

    medianWallclock 用 statistics.median (奇数取中, 偶数取均值); 0 metric 边界返空 dict.
    """
    if not metrics:
        return {}
    by_provider: dict[str, list[TaskMetric]] = {}
    for m in metrics:
        by_provider.setdefault(m.provider, []).append(m)

    out: dict[str, ProviderSummary] = {}
    for provider, ms in by_provider.items():
        pass_count = sum(1 for m in ms if m.pass_)
        wallclock_list = [m.wallclock_s for m in ms]
        bucket_counts: dict[str, int] = {}
        for m in ms:
            bucket_counts[m.failure_bucket] = bucket_counts.get(m.failure_bucket, 0) + 1
        out[provider] = ProviderSummary(
            provider=provider,
            task_count=len(ms),
            pass_count=pass_count,
            pass_rate=pass_count / len(ms),
            avg_steps=sum(m.steps for m in ms) / len(ms),
            median_wallclock_s=statistics.median(wallclock_list),
            total_input_tokens=sum(m.input_tokens for m in ms),
            total_output_tokens=sum(m.output_tokens for m in ms),
            total_input_cost_usd=sum(m.input_cost_usd for m in ms),
            total_output_cost_usd=sum(m.output_cost_usd for m in ms),
            failure_buckets=bucket_counts,
        )
    return out


def aggregate_by_capability_axis(
    metrics: list[TaskMetric], task_axis: dict[str, CapabilityAxis],
) -> dict[CapabilityAxis, dict[str, float]]:
    """V0.26.2: 按 capability_axis 分组 → {axis: {provider: pass_rate}}.

    task_axis: task_id → CapabilityAxis 反查 (caller 从 ALL_TASKS 构造). 让 eval 报告
    显示 e.g. iframe 类 anthropic 1.0 / openai 0.5 / kimi 0.0 — 决定 V0.27 vault 按
    provider 分级权限的关键数据.
    """
    if not metrics:
        return {}
    # axis → provider → (pass_count, total_count)
    counters: dict[CapabilityAxis, dict[str, list[int]]] = {}
    for m in metrics:
        axis = task_axis.get(m.task_id)
        if axis is None:
            continue
        prov_dict = counters.setdefault(axis, {})
        bucket = prov_dict.setdefault(m.provider, [0, 0])
        bucket[1] += 1  # total
        if m.pass_:
            bucket[0] += 1  # pass

    out: dict[CapabilityAxis, dict[str, float]] = {}
    for axis, prov_map in counters.items():
        out[axis] = {
            provider: pc / tc if tc > 0 else 0.0
            for provider, (pc, tc) in prov_map.items()
        }
    return out
