"""V0.33.0 E 性能优化系列开篇: token baseline framework — load eval JSON + compare A vs B.

V0.33 系列 5 commit (subagent 推按 ROI 重排, WebP token 不直接减是关键发现 #13):
- V0.33.0 (本): token baseline framework + CLI compare A.jsonl B.jsonl
- V0.33.1: per-step token accumulator 修 V0.26.2 silent bug #14 (last_usage × N 高估, prompt cache
  命中后第 2+ step input_tokens 大降, 末次 × N 高估真实成本)
- V0.33.2: SoM 字段 lean mode opt-in (WEB_AGENT_SOM_FIELDS=lean) — text 直减 token 比 WebP 真有效
- V0.33.3: screenshot WebP opt-in (WEB_AGENT_SCREENSHOT_FORMAT=webp) — 注 #13 Anthropic 按 image
  tile 固定计费 ~1568 tok/image, byte 减 70% 不直接减 token, V0.33.4 baseline 验完决定保留
- V0.33.4: real_world baseline 双跑 (lean vs full / webp vs png) 出表 + 系列总结

V0.33.0 scope (subagent A-D 决): 测框架 framework 先, 不动 perceiver/loop. 跟 V0.27.1 vault /
V0.28.0 reflect / V0.29.0 chain.py / V0.30.1 vcr framework 同节奏.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TaskTokenStats:
    """V0.33.0: 单 task 单 provider token stats (从 eval JSON metrics 抽)."""

    task_id: str
    provider: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    steps: int


@dataclass(frozen=True, slots=True)
class BaselineCompareReport:
    """V0.33.0: A vs B baseline 对比报告 (per-task delta + overall sum)."""

    a_label: str
    b_label: str
    per_task: dict[tuple[str, str], dict[str, float]]  # (task_id, provider) → {input_delta, output_delta, cost_delta_usd}
    overall: dict[str, float]  # total_input_delta, total_output_delta, total_cost_delta_usd, percent_input, percent_output, percent_cost


def load_baseline_json(path: Path) -> list[TaskTokenStats]:
    """V0.33.0: 从 eval JSON dump (V0.26.2 schema) 抽 TaskTokenStats list.

    eval JSON 结构: {"metrics": [{"task_id":..., "provider":..., "input_tokens":..., ...}, ...]}.
    """
    if not path.exists():
        raise FileNotFoundError(f"baseline JSON 不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    metrics = data.get("metrics", [])
    return [
        TaskTokenStats(
            task_id=m["task_id"],
            provider=m["provider"],
            input_tokens=m.get("input_tokens", 0),
            output_tokens=m.get("output_tokens", 0),
            input_cost_usd=m.get("input_cost_usd", 0.0),
            output_cost_usd=m.get("output_cost_usd", 0.0),
            steps=m.get("steps", 0),
        )
        for m in metrics
    ]


def compare_baselines(
    baseline_a: list[TaskTokenStats],
    baseline_b: list[TaskTokenStats],
    *,
    a_label: str = "A",
    b_label: str = "B",
) -> BaselineCompareReport:
    """V0.33.0: A vs B per-(task,provider) delta + overall sum + percent change.

    delta 正值 = B 比 A 多 (regression), 负值 = B 比 A 省 (优化).
    缺 pair (一边有另一边没) 跳过 (subagent: 配对算法跟 V0.28.3 reflective_uplift 一致).
    """
    by_pair_a = {(s.task_id, s.provider): s for s in baseline_a}
    by_pair_b = {(s.task_id, s.provider): s for s in baseline_b}
    common = set(by_pair_a) & set(by_pair_b)

    per_task: dict[tuple[str, str], dict[str, float]] = {}
    total_a_in = total_a_out = 0
    total_a_cost = 0.0
    total_b_in = total_b_out = 0
    total_b_cost = 0.0
    for key in common:
        a, b = by_pair_a[key], by_pair_b[key]
        per_task[key] = {
            "input_delta": float(b.input_tokens - a.input_tokens),
            "output_delta": float(b.output_tokens - a.output_tokens),
            "cost_delta_usd": (b.input_cost_usd + b.output_cost_usd) - (a.input_cost_usd + a.output_cost_usd),
        }
        total_a_in += a.input_tokens
        total_a_out += a.output_tokens
        total_a_cost += a.input_cost_usd + a.output_cost_usd
        total_b_in += b.input_tokens
        total_b_out += b.output_tokens
        total_b_cost += b.input_cost_usd + b.output_cost_usd

    def _pct(a: float, b: float) -> float:
        return ((b - a) / a * 100.0) if a > 0 else 0.0

    overall = {
        "total_input_delta": float(total_b_in - total_a_in),
        "total_output_delta": float(total_b_out - total_a_out),
        "total_cost_delta_usd": total_b_cost - total_a_cost,
        "percent_input": _pct(total_a_in, total_b_in),
        "percent_output": _pct(total_a_out, total_b_out),
        "percent_cost": _pct(total_a_cost, total_b_cost),
    }
    return BaselineCompareReport(
        a_label=a_label, b_label=b_label, per_task=per_task, overall=overall,
    )


def render_baseline_compare_markdown(report: BaselineCompareReport) -> str:
    """V0.33.0: 渲染 BaselineCompareReport 为 markdown 表 (跟 V0.28.3 reflective_uplift markdown 同模式).

    Format:
    | scope | input Δ | output Δ | cost Δ | % cost |
    | overall | -1234 | -56 | -$0.0034 | -45.6% |
    | task_a (anthropic) | -200 | -10 | -$0.0008 | ... |
    """
    if not report.per_task:
        return "(no baseline compare data — A B 配对为空)"
    rows = [
        "| scope | input Δ | output Δ | cost Δ | % cost |",
        "|-------|---------|----------|--------|--------|",
        (
            f"| **overall ({report.a_label}→{report.b_label})** | "
            f"{report.overall['total_input_delta']:+.0f} | "
            f"{report.overall['total_output_delta']:+.0f} | "
            f"${report.overall['total_cost_delta_usd']:+.4f} | "
            f"{report.overall['percent_cost']:+.1f}% |"
        ),
    ]
    for (task_id, provider), delta in sorted(report.per_task.items()):
        rows.append(
            f"| {task_id} ({provider}) | "
            f"{delta['input_delta']:+.0f} | "
            f"{delta['output_delta']:+.0f} | "
            f"${delta['cost_delta_usd']:+.4f} | "
            f"— |"
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    """V0.33.0: web-agent-token-baseline cli — load + compare 2 eval JSON dumps.

    用法:
        web-agent-token-baseline compare data/eval/run-A.json data/eval/run-B.json
        web-agent-token-baseline stats data/eval/run-A.json
    """
    parser = argparse.ArgumentParser(
        prog="web-agent-token-baseline",
        description="V0.33.0 E 性能优化框架: load eval JSON dumps + compare token cost A vs B.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp_compare = sub.add_parser("compare", help="A.json vs B.json per-task token delta + overall")
    sp_compare.add_argument("a_path", help="A baseline JSON (eval/runner dump)")
    sp_compare.add_argument("b_path", help="B baseline JSON")
    sp_compare.add_argument("--a-label", default="A", help="A 标签 (markdown header)")
    sp_compare.add_argument("--b-label", default="B", help="B 标签")

    sp_stats = sub.add_parser("stats", help="单 baseline per-task token stats")
    sp_stats.add_argument("path", help="baseline JSON path")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "compare":
            a = load_baseline_json(Path(args.a_path))
            b = load_baseline_json(Path(args.b_path))
            report = compare_baselines(a, b, a_label=args.a_label, b_label=args.b_label)
            sys.stdout.write(render_baseline_compare_markdown(report) + "\n")
            return 0
        if args.cmd == "stats":
            stats = load_baseline_json(Path(args.path))
            sys.stdout.write(f"baseline {args.path}: {len(stats)} (task, provider) pairs\n")
            for s in sorted(stats, key=lambda x: (x.task_id, x.provider)):
                cost = s.input_cost_usd + s.output_cost_usd
                sys.stdout.write(
                    f"  {s.task_id} ({s.provider}): "
                    f"in={s.input_tokens} out={s.output_tokens} cost=${cost:.4f} steps={s.steps}\n",
                )
            return 0
    except FileNotFoundError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        return 1
    return 0


__all__ = [
    "BaselineCompareReport",
    "TaskTokenStats",
    "compare_baselines",
    "load_baseline_json",
    "render_baseline_compare_markdown",
]
