"""V0.34.0 F sub-route 优化系列开篇: perceive() 子流程 bench harness framework.

V0.33 E 性能优化系列教训: 没 baseline 任何"性能优化"都是猜 (V0.33.2 lean ~16k tok 估 / V0.33.3
WebP ~70% 磁盘估都未真量化). V0.34 F sub-route 优化系列首要就是先建 bench framework, 之后 F1
(iframe DFS 并发) / F2 (SoM JS 三 walker 合并) / F3 (mark dedup) 等才能真验收.

跟 V0.33.0 token_baseline.py 同节奏 + 同构 dataclass:
- BenchFixture: synthetic HTML × N iframe × M shadow generator (纯字符串, 不接 chromium)
- BenchResult: 单次 perceive 测得 metric (perceive_ms / mark_count / memory_kb)
- BenchCompareReport: A vs B per-fixture delta + overall avg/max
- main(argv): cli `web-agent-perceive-bench` (compare / stats subcommand)

V0.34.0 scope: framework only, **不接真 chromium / Playwright**. 真跑 fixture 是 V0.34.x 后续
commit (跟 V0.33.4 deferred maintainer baseline how-to 同模式 — slow test gate WEB_AGENT_RUN_SLOW=1).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BenchFixture:
    """V0.34.0: synthetic HTML fixture (描述 + HTML body), 给 perceive() 真跑用.

    fixture_id 唯一 (含 iframe/shadow/leaf 三参数), html 是 nested-iframe + nested-shadow + N leaf
    button 的 self-contained HTML 字符串, 任何 file:// 或 page.set_content 都能加载.
    """

    fixture_id: str
    iframe_count: int  # 嵌套 iframe 深度 (0 = 单 frame), 跟 V0.22 iframe DFS 路径压力相关
    shadow_count: int  # 每 element 嵌套 shadow root 层数 (0 = light DOM only), 跟 W5-B Shadow 穿透相关
    leaf_per_branch: int  # 每 frame/shadow 内 button 数 (mark 总数 = N × M × leaf, 控制 dedup 压力)
    html: str


@dataclass(frozen=True, slots=True)
class BenchResult:
    """V0.34.0: 单次 perceive(fixture) 实测 metric.

    perceive_ms 是 perceive() wallclock (P50 应给, V0.34.x 真跑接 statistics.median 多 sample).
    memory_kb 是 perceive 前后 Python heap 增量估 (tracemalloc), 检 mark dedup 算法内存爆破.
    sample_count >=1, 多 sample 取 median 防 GC noise.
    """

    fixture_id: str
    perceive_ms: float
    mark_count: int
    memory_kb: float
    shadow_walks: int  # SoM JS 内 shadow root walker 进入次数 (诊 F5 TreeWalker 优化效果)
    iframe_walks: int  # _walk_child_frames 递归次数 (诊 F1 并发优化效果)
    sample_count: int


@dataclass(frozen=True, slots=True)
class BenchCompareReport:
    """V0.34.0: A vs B bench 对比 (per-fixture delta + overall avg).

    delta 正值 = B 比 A 慢 / 多 mark / 多内存 (regression). 负值 = B 比 A 快 / 省 (优化).
    """

    a_label: str
    b_label: str
    per_fixture: dict[str, dict[str, float]]  # fixture_id → {ms_delta, mark_delta, mem_delta_kb, percent_ms}
    overall: dict[str, float]  # avg_ms_delta, avg_mark_delta, avg_mem_delta_kb, avg_percent_ms


def build_synthetic_fixture(
    iframe_count: int = 0,
    shadow_count: int = 0,
    leaf_per_branch: int = 5,
) -> BenchFixture:
    """V0.34.0: 生 synthetic HTML fixture (perceiver 真跑用).

    - iframe_count=0 + shadow_count=0 + leaf=5 → 5 个 button 单 frame light DOM (基线 fixture)
    - iframe_count=3 → 3 层嵌套 iframe (`<iframe srcdoc="..."><iframe srcdoc="..."></iframe>`)
    - shadow_count=2 → 每 host element 内 shadow root 嵌套 2 层 (open mode, perceiver 能穿透)
    - leaf_per_branch 控制每分支 button 数, mark 总数 = (iframe+1) × (shadow+1) × leaf

    HTML 字符串 self-contained (无外部 CSS/JS 依赖), `page.set_content(html)` 直接加载即可.
    """
    if iframe_count < 0 or shadow_count < 0 or leaf_per_branch < 1:
        raise ValueError(
            f"非法 fixture 参数: iframe_count={iframe_count} shadow_count={shadow_count} "
            f"leaf_per_branch={leaf_per_branch} (需 iframe>=0 / shadow>=0 / leaf>=1)",
        )
    fixture_id = f"if{iframe_count}-sh{shadow_count}-leaf{leaf_per_branch}"
    body = _build_branch_html(shadow_count, leaf_per_branch)
    # iframe_count 层 srcdoc 嵌套 (从内向外)
    for depth in range(iframe_count):
        inner = body.replace('"', "&quot;")
        body = (
            f'<iframe srcdoc="<html><body>{inner}</body></html>" '
            f'style="width:600px;height:400px;border:1px solid #ccc"></iframe>'
            f'<p>iframe-depth-{depth + 1}</p>'
        )
    html = f"<!DOCTYPE html><html><head><title>{fixture_id}</title></head><body>{body}</body></html>"
    return BenchFixture(
        fixture_id=fixture_id,
        iframe_count=iframe_count,
        shadow_count=shadow_count,
        leaf_per_branch=leaf_per_branch,
        html=html,
    )


def _build_branch_html(shadow_count: int, leaf_per_branch: int) -> str:
    """V0.34.0 helper: 单 frame 内的 light + shadow 嵌套 HTML.

    leaf button 列出 N 个 (`<button id="bN">btn-N</button>`).
    shadow_count > 0 时, 每 button 外裹一个 host span + inline `<script>` attachShadow + 内嵌 leaf.
    """
    leaves = "\n".join(
        f'<button id="b{i}" type="button">btn-{i}</button>'
        for i in range(leaf_per_branch)
    )
    if shadow_count == 0:
        return f'<div class="branch">{leaves}</div>'
    # shadow nested: host span + script attach shadow + 嵌套同结构 (递归)
    inner = _build_branch_html(shadow_count - 1, leaf_per_branch)
    inner_safe = inner.replace("`", r"\`")
    return (
        f'<span id="shadow-host-{shadow_count}"></span>'
        f'<script>(function(){{'
        f'const host=document.getElementById("shadow-host-{shadow_count}");'
        f'const sr=host.attachShadow({{mode:"open"}});'
        f'sr.innerHTML=`{inner_safe}`;'
        f'}})();</script>'
    )


def load_bench_json(path: Path) -> list[BenchResult]:
    """V0.34.0: 从 bench JSON dump 加载 BenchResult list (跟 V0.33.0 load_baseline_json 同 pattern).

    JSON schema: {"bench_results": [{"fixture_id":..., "perceive_ms":..., ...}, ...]}.
    """
    if not path.exists():
        raise FileNotFoundError(f"bench JSON 不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("bench_results", [])
    return [
        BenchResult(
            fixture_id=r["fixture_id"],
            perceive_ms=float(r.get("perceive_ms", 0.0)),
            mark_count=int(r.get("mark_count", 0)),
            memory_kb=float(r.get("memory_kb", 0.0)),
            shadow_walks=int(r.get("shadow_walks", 0)),
            iframe_walks=int(r.get("iframe_walks", 0)),
            sample_count=int(r.get("sample_count", 1)),
        )
        for r in items
    ]


def compare_benches(
    bench_a: list[BenchResult],
    bench_b: list[BenchResult],
    *,
    a_label: str = "A",
    b_label: str = "B",
) -> BenchCompareReport:
    """V0.34.0: A vs B per-fixture delta + overall avg (跟 V0.33.0 compare_baselines 同 pattern).

    delta = B - A (正值 = B 比 A 慢/多, 负值 = B 比 A 快/省).
    缺 pair (一边有另一边没) 跳过.
    """
    by_id_a = {r.fixture_id: r for r in bench_a}
    by_id_b = {r.fixture_id: r for r in bench_b}
    common = set(by_id_a) & set(by_id_b)

    per_fixture: dict[str, dict[str, float]] = {}
    sum_ms_delta = sum_mark_delta = sum_mem_delta = sum_pct = 0.0
    for fid in common:
        a, b = by_id_a[fid], by_id_b[fid]
        ms_delta = b.perceive_ms - a.perceive_ms
        per_fixture[fid] = {
            "ms_delta": ms_delta,
            "mark_delta": float(b.mark_count - a.mark_count),
            "mem_delta_kb": b.memory_kb - a.memory_kb,
            "percent_ms": (ms_delta / a.perceive_ms * 100.0) if a.perceive_ms > 0 else 0.0,
        }
        sum_ms_delta += ms_delta
        sum_mark_delta += b.mark_count - a.mark_count
        sum_mem_delta += b.memory_kb - a.memory_kb
        sum_pct += per_fixture[fid]["percent_ms"]

    n = len(common)
    overall = {
        "avg_ms_delta": sum_ms_delta / n if n else 0.0,
        "avg_mark_delta": sum_mark_delta / n if n else 0.0,
        "avg_mem_delta_kb": sum_mem_delta / n if n else 0.0,
        "avg_percent_ms": sum_pct / n if n else 0.0,
    }
    return BenchCompareReport(
        a_label=a_label, b_label=b_label, per_fixture=per_fixture, overall=overall,
    )


def render_bench_compare_markdown(report: BenchCompareReport) -> str:
    """V0.34.0: 渲染 BenchCompareReport 为 markdown (跟 V0.33.0 render_baseline_compare_markdown 同模式)."""
    if not report.per_fixture:
        return "(no bench compare data — A B fixture 配对为空)"
    rows = [
        "| scope | ms Δ | mark Δ | mem Δ (KB) | % ms |",
        "|-------|------|--------|------------|------|",
        (
            f"| **overall avg ({report.a_label}→{report.b_label})** | "
            f"{report.overall['avg_ms_delta']:+.2f} | "
            f"{report.overall['avg_mark_delta']:+.1f} | "
            f"{report.overall['avg_mem_delta_kb']:+.1f} | "
            f"{report.overall['avg_percent_ms']:+.1f}% |"
        ),
    ]
    for fid, delta in sorted(report.per_fixture.items()):
        rows.append(
            f"| {fid} | "
            f"{delta['ms_delta']:+.2f} | "
            f"{delta['mark_delta']:+.0f} | "
            f"{delta['mem_delta_kb']:+.1f} | "
            f"{delta['percent_ms']:+.1f}% |"
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    """V0.34.0: web-agent-perceive-bench cli — fixture / compare / stats subcommands.

    V0.34.0 framework only — `run` subcommand (真跑 chromium) 留给 V0.34.x 后续 commit (gate
    WEB_AGENT_RUN_SLOW=1). 当前 cli 仅 fixture (生 HTML 给 maintainer 真跑) + compare / stats.

    用法:
        web-agent-perceive-bench fixture --iframe 3 --shadow 2 --leaf 5
        web-agent-perceive-bench compare data/bench/v034-A.json data/bench/v034-B.json
        web-agent-perceive-bench stats data/bench/v034-A.json
    """
    parser = argparse.ArgumentParser(
        prog="web-agent-perceive-bench",
        description="V0.34.0 F sub-route 优化框架: perceive() 子流程 bench fixture + compare A vs B.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp_fix = sub.add_parser("fixture", help="生 synthetic HTML fixture (给 maintainer 真跑 perceive)")
    sp_fix.add_argument("--iframe", type=int, default=0, help="嵌套 iframe 深度 (默 0)")
    sp_fix.add_argument("--shadow", type=int, default=0, help="嵌套 shadow root 层数 (默 0)")
    sp_fix.add_argument("--leaf", type=int, default=5, help="每分支 button 数 (默 5)")
    sp_fix.add_argument("--out", help="输出 HTML 路径 (默 stdout)")

    sp_cmp = sub.add_parser("compare", help="A.json vs B.json per-fixture ms/mark/mem delta + overall avg")
    sp_cmp.add_argument("a_path", help="A bench JSON")
    sp_cmp.add_argument("b_path", help="B bench JSON")
    sp_cmp.add_argument("--a-label", default="A", help="A 标签 (markdown header)")
    sp_cmp.add_argument("--b-label", default="B", help="B 标签")

    sp_stats = sub.add_parser("stats", help="单 bench per-fixture 时间/mark/内存 stats")
    sp_stats.add_argument("path", help="bench JSON path")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "fixture":
            f = build_synthetic_fixture(args.iframe, args.shadow, args.leaf)
            if args.out:
                Path(args.out).write_text(f.html, encoding="utf-8")
                sys.stdout.write(f"fixture {f.fixture_id} → {args.out} ({len(f.html)} bytes)\n")
            else:
                sys.stdout.write(f.html + "\n")
            return 0
        if args.cmd == "compare":
            a = load_bench_json(Path(args.a_path))
            b = load_bench_json(Path(args.b_path))
            report = compare_benches(a, b, a_label=args.a_label, b_label=args.b_label)
            sys.stdout.write(render_bench_compare_markdown(report) + "\n")
            return 0
        if args.cmd == "stats":
            results = load_bench_json(Path(args.path))
            sys.stdout.write(f"bench {args.path}: {len(results)} fixture results\n")
            for r in sorted(results, key=lambda x: x.fixture_id):
                sys.stdout.write(
                    f"  {r.fixture_id}: ms={r.perceive_ms:.2f} marks={r.mark_count} "
                    f"mem={r.memory_kb:.1f}KB shadow_walks={r.shadow_walks} "
                    f"iframe_walks={r.iframe_walks} (n={r.sample_count})\n",
                )
            return 0
    except FileNotFoundError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        return 1
    except ValueError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        return 2
    return 0


__all__ = [
    "BenchCompareReport",
    "BenchFixture",
    "BenchResult",
    "build_synthetic_fixture",
    "compare_benches",
    "load_bench_json",
    "main",
    "render_bench_compare_markdown",
]
