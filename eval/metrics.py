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


@dataclass(frozen=True, slots=True)
class ReflectiveUpliftReport:
    """V0.28.3 W6 收尾: --reflect 2-pass 跑后 pass2_rate - pass1_rate uplift 报告.

    三粒度信号 (subagent C 决):
    - per_task: dict[task_id, int] 取 -1/0/+1 (run2-run1 二元差), 散点诊断哪个 task 真受益
    - per_axis: dict[CapabilityAxis, float] 中间层趋势 (axis ≥2 task 才稳, 文档化 warning)
    - overall: float total uplift, headline 写入 JSON top-level
    - reflections_written: int run1 触发反思 task 数 (透明化假阴性 — 跟 V0.28.1 触发一致)
    """

    per_task: dict[str, int]
    per_axis: dict[CapabilityAxis, float]
    overall: float
    reflections_written: int


def compute_reflective_uplift(
    metrics: list[TaskMetric], task_axis: dict[str, CapabilityAxis],
) -> ReflectiveUpliftReport:
    """V0.28.3 W6 收尾: 算 reflect 2-pass uplift (subagent C 三粒度).

    Args:
        metrics: run_corpus(reflect=True) 返的 metrics list, 每 task × provider 配 2 条
            (inject_reflections=False/True)
        task_axis: task_id → CapabilityAxis 反查 (跟 aggregate_by_capability_axis 同)

    Returns:
        ReflectiveUpliftReport — 空 metrics / 缺配对 → per_task={}/per_axis={}/overall=0.0/reflections_written=0
    """
    # group by (task_id, provider) → {False: m1, True: m2}
    by_pair: dict[tuple[str, str], dict[bool, TaskMetric]] = {}
    for m in metrics:
        key = (m.task_id, m.provider)
        by_pair.setdefault(key, {})[m.inject_reflections] = m

    per_task: dict[str, int] = {}
    per_axis_pass1: dict[CapabilityAxis, list[int]] = {}
    per_axis_pass2: dict[CapabilityAxis, list[int]] = {}
    reflections_written = 0
    for (task_id, _provider), pair in by_pair.items():
        m1 = pair.get(False)
        m2 = pair.get(True)
        if m1 is None or m2 is None:
            continue  # 缺配对 (e.g. 老 metrics 不带 inject_reflections), 跳过
        # per_task 二元差: run2 pass - run1 pass ∈ {-1, 0, +1}
        per_task[task_id] = int(m2.pass_) - int(m1.pass_)
        # per_axis 累加 task 维 pass count
        axis = task_axis.get(task_id)
        if axis is not None:
            per_axis_pass1.setdefault(axis, []).append(int(m1.pass_))
            per_axis_pass2.setdefault(axis, []).append(int(m2.pass_))
        # run1 失败且 W6-A 触发了反思 (m2 看到 inject 不空 — 但本层无法判) →
        # 简化判: m1 failure_bucket startswith "max_steps"/"(max_steps"/"LOOP_DETECTED"
        # 跟 reflect.should_reflect 对齐. V0.29.5 fix V0.28.3 bucket 命名 bug — runner.py:67
        # `marker.split(" ")[0].split(":")[0]` 处理 "(max_steps 耗尽未完成)" 返 "(max_steps"
        # (带左括号), V0.28.3 in 检查永不命中 → reflections_written 永 0. startswith 容错修.
        if not m1.pass_ and any(
            m1.failure_bucket.startswith(p)
            for p in ("max_steps", "(max_steps", "LOOP_DETECTED")
        ):
            reflections_written += 1

    per_axis: dict[CapabilityAxis, float] = {}
    for axis, p1_list in per_axis_pass1.items():
        p2_list = per_axis_pass2.get(axis, [])
        if not p1_list or len(p1_list) != len(p2_list):
            continue
        rate1 = sum(p1_list) / len(p1_list)
        rate2 = sum(p2_list) / len(p2_list)
        per_axis[axis] = rate2 - rate1

    # overall: total uplift (sum of per_task 差) / 配对总数
    overall = sum(per_task.values()) / len(per_task) if per_task else 0.0

    return ReflectiveUpliftReport(
        per_task=per_task,
        per_axis=per_axis,
        overall=overall,
        reflections_written=reflections_written,
    )


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
