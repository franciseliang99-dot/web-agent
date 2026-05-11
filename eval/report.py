"""V0.26.2: eval report — JSON dump + 文本对比表 (markdown 表 LLM/PR 友好不引 rich).

输入 CorpusReport (含 metrics list) → 输出:
- JSON: data/eval/<run_id>.json (落档可重读 + replay 面板加载)
- markdown 跨 provider 对比表 (stdout / 帖 PR)
- by capability_axis 分桶表
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from eval.metrics import (
    ProviderSummary,
    ReflectiveUpliftReport,
    aggregate,
    aggregate_by_capability_axis,
    compute_reflective_uplift,
)
from eval.runner import CorpusReport, metric_to_dict
from eval.types import CapabilityAxis, EvalTask


def _git_sha() -> str:
    """V0.26.2: 读当前 git HEAD sha (短) 让 baseline 数据可关联代码版本; 失败返 'unknown'."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def dump_json(
    report: CorpusReport, tasks: list[EvalTask], output_dir: Path,
    *, web_agent_version: str = "unknown", corpus_version: str = "unknown",
    vcr_replay: bool = False,
) -> Path:
    """V0.26.2: dump CorpusReport 到 data/eval/<run_id>.json 落档 (V0.26.4 baseline 数据底座).

    schema 跟 V0.26 plan F 节示范一致 (run_id / git_sha / providers / tasks → runs[] /
    aggregate / by_capability_axis).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{report.run_id}.json"
    summaries = aggregate(report.metrics)
    task_axis = {t.task_id: t.capability_axis for t in tasks}
    by_axis = aggregate_by_capability_axis(report.metrics, task_axis)
    # V0.28.3 W6 收尾: --reflect 跑时 metrics 含 inject_reflections 配对, 加 uplift 报告
    uplift = compute_reflective_uplift(report.metrics, task_axis)
    payload: dict[str, Any] = {
        "run_id": report.run_id,
        "started_at": round(report.started_at, 2),
        "ended_at": round(report.ended_at, 2),
        "git_sha": _git_sha(),
        "web_agent_version": web_agent_version,
        "corpus_version": corpus_version,
        "vcr_replay": vcr_replay,
        "providers": sorted({m.provider for m in report.metrics}),
        "metrics": [metric_to_dict(m) for m in report.metrics],
        "aggregate": {p: _summary_to_dict(s) for p, s in summaries.items()},
        "by_capability_axis": {axis: per_provider for axis, per_provider in by_axis.items()},
        "reflective_uplift": _uplift_to_dict(uplift),
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def _uplift_to_dict(u: ReflectiveUpliftReport) -> dict[str, Any]:
    """V0.28.3: ReflectiveUpliftReport → JSON dict. 空 (per_task={}) 仍 dump 让 caller
    能区分 "没跑 reflect" (key 缺) vs "跑了但全 0 配对" (key 在 + 空 dict)."""
    return {
        "per_task": u.per_task,
        "per_axis": {axis: round(v, 3) for axis, v in u.per_axis.items()},
        "overall": round(u.overall, 3),
        "reflections_written": u.reflections_written,
    }


def _summary_to_dict(s: ProviderSummary) -> dict[str, Any]:
    """V0.26.2: ProviderSummary → JSON dict (round 2 位精度)."""
    return {
        "task_count": s.task_count,
        "pass_count": s.pass_count,
        "pass_rate": round(s.pass_rate, 3),
        "avg_steps": round(s.avg_steps, 2),
        "median_wallclock_s": round(s.median_wallclock_s, 2),
        "total_input_tokens": s.total_input_tokens,
        "total_output_tokens": s.total_output_tokens,
        "total_input_cost_usd": round(s.total_input_cost_usd, 4),
        "total_output_cost_usd": round(s.total_output_cost_usd, 4),
        "failure_buckets": s.failure_buckets,
    }


def render_provider_summary_markdown(report: CorpusReport) -> str:
    """V0.26.2: 跨 provider 聚合表 (markdown). LLM/PR/issue 友好, 终端 monospace 也对齐.

    格式:
    | provider | tasks | pass% | avg_steps | p50_wallclock_s | total_cost_usd |
    """
    summaries = aggregate(report.metrics)
    if not summaries:
        return "(no metrics)"
    rows = []
    rows.append("| provider | tasks | pass% | avg_steps | p50_wallclock_s | total_cost_usd |")
    rows.append("|----------|-------|-------|-----------|-----------------|----------------|")
    for provider, s in sorted(summaries.items()):
        total_cost = s.total_input_cost_usd + s.total_output_cost_usd
        rows.append(
            f"| {provider} | {s.task_count} | {s.pass_rate:.1%} | "
            f"{s.avg_steps:.1f} | {s.median_wallclock_s:.1f} | ${total_cost:.4f} |"
        )
    return "\n".join(rows)


def render_capability_axis_markdown(
    report: CorpusReport, tasks: list[EvalTask],
) -> str:
    """V0.26.2: 按 capability_axis 分组 pass_rate 表 (跨 provider 对比). 决定 V0.27 vault 分级.

    格式:
    | capability_axis | anthropic | openai | kimi |
    """
    task_axis: dict[str, CapabilityAxis] = {t.task_id: t.capability_axis for t in tasks}
    by_axis = aggregate_by_capability_axis(report.metrics, task_axis)
    if not by_axis:
        return "(no axis data)"
    providers = sorted({m.provider for m in report.metrics})
    if not providers:
        return "(no provider data)"
    header = "| capability_axis | " + " | ".join(providers) + " |"
    sep = "|" + "|".join(["-" * 10] * (len(providers) + 1)) + "|"
    rows = [header, sep]
    for axis in sorted(by_axis.keys()):
        per_provider = by_axis[axis]
        cells = [f"{per_provider.get(p, 0.0):.1%}" for p in providers]
        rows.append(f"| {axis} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def render_reflective_uplift_markdown(
    report: CorpusReport, tasks: list[EvalTask],
) -> str:
    """V0.28.3 W6 收尾: 渲染 reflect 2-pass uplift markdown 表 (--reflect 跑后输出).

    格式:
    | scope        | uplift   | n配对  |
    | overall      | +25.0%   | 4     |
    | iframe       | +50.0%   | 2     |
    | multi-tab    | 0.0%     | 1     |
    | (per-task)   | t1: +1, t2: 0 |
    | reflections_written | 2 / 4 配对 (50.0%) |

    空 metrics / 0 配对 → "(no reflective data — run with --reflect)".
    axis ≥2 task 才稳信号 (subagent C 提示).
    """
    task_axis: dict[str, CapabilityAxis] = {t.task_id: t.capability_axis for t in tasks}
    uplift = compute_reflective_uplift(report.metrics, task_axis)
    if not uplift.per_task:
        return "(no reflective data — run with --reflect)"
    rows = [
        "| scope | uplift | notes |",
        "|-------|--------|-------|",
        f"| **overall** | {uplift.overall:+.1%} | {len(uplift.per_task)} task 配对 |",
    ]
    for axis in sorted(uplift.per_axis.keys()):
        v = uplift.per_axis[axis]
        rows.append(f"| {axis} | {v:+.1%} | per-axis (≥2 task 才稳) |")
    # per-task 散点
    per_task_str = ", ".join(f"{tid}: {d:+d}" for tid, d in sorted(uplift.per_task.items()))
    rows.append(f"| per-task | {per_task_str} | -1/0/+1 二元差 |")
    rows.append(
        f"| reflections_written | {uplift.reflections_written} / {len(uplift.per_task)} | "
        "run1 触发反思 task 数 (max_steps + LOOP_DETECTED) |"
    )
    return "\n".join(rows)
