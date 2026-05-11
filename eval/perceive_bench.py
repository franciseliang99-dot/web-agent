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
import re
import sys
from dataclasses import asdict, dataclass
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
    siblings_per_layer: int = 1,
) -> BenchFixture:
    """V0.34.0+: 生 synthetic HTML fixture (perceiver 真跑用).

    - iframe_count=0 + shadow_count=0 + leaf=5: 5 个 button 单 frame light DOM (基线)
    - iframe_count=3: 3 层嵌套 iframe (JS DOM API, V0.34.2)
    - shadow_count=2: 嵌套 2 层 open shadow root (V0.34.2 DOM API attachShadow)
    - leaf_per_branch: 每分支 button 数 (linear chain mark = leaf, 见 V0.34.0 design)
    - **V0.34.3 siblings_per_layer**: 每 iframe 层 sibling iframe 数 (默 1 = linear chain
      兼容 V0.34.2 baseline). siblings>1 → fan-out 树状, mark 总 = siblings^iframe × leaf,
      是 F1 iframe DFS asyncio.gather 并发主战场 (linear chain 深度依赖串行无并发空间).

    fixture_id 命名: `if{N}[-sib{K}]-sh{M}-leaf{L}` — siblings>1 时插 `-sib{K}`, 默 1 时省
    (V0.34.2 baseline fixture_id 完全兼容, baseline JSON parse 不破).

    HTML self-contained, page.goto(data URI) 加载. siblings>1 时 chain 树状, perceive iframe
    DFS 时各 sibling 当前**串行**跑 (V0.34.3 fixture 提供 fan-out 压力, V0.34.4 F1 真并发).
    """
    if (
        iframe_count < 0
        or shadow_count < 0
        or leaf_per_branch < 1
        or siblings_per_layer < 1
    ):
        raise ValueError(
            f"非法 fixture 参数: iframe_count={iframe_count} shadow_count={shadow_count} "
            f"leaf_per_branch={leaf_per_branch} siblings_per_layer={siblings_per_layer} "
            f"(需 iframe>=0 / shadow>=0 / leaf>=1 / siblings>=1)",
        )
    sib_part = f"-sib{siblings_per_layer}" if siblings_per_layer > 1 else ""
    fixture_id = f"if{iframe_count}{sib_part}-sh{shadow_count}-leaf{leaf_per_branch}"
    branch_html = _build_branch_html(shadow_count, leaf_per_branch)
    if iframe_count == 0:
        body = branch_html
    else:
        body = _build_iframe_chain_html(iframe_count, branch_html, siblings_per_layer)
    html = f"<!DOCTYPE html><html><head><title>{fixture_id}</title></head><body>{body}</body></html>"
    return BenchFixture(
        fixture_id=fixture_id,
        iframe_count=iframe_count,
        shadow_count=shadow_count,
        leaf_per_branch=leaf_per_branch,
        html=html,
    )


def _build_iframe_chain_html(remaining: int, leaf_html: str, siblings: int = 1) -> str:
    """V0.34.2+: 递归构建 N 层 iframe HTML, 每层用 JS DOM property 设 srcdoc.

    remaining=0: 返 leaf_html (基线 leaf branch).
    remaining>0: 一段 HTML 含 K=siblings 个 iframe-host div + IIFE 跑 K 次 createElement
    iframe + ifr.srcdoc = inner_html. siblings=1 时 linear chain (V0.34.2 兼容); siblings>1
    时 fan-out 树状, F1 iframe DFS 并发优化主战场.

    JS string literal escape (json.dumps + `</`→`<\\/`) 处理任意层 (V0.34.2 fix #15 #16).
    """
    if remaining == 0:
        return leaf_html
    inner_html = _build_iframe_chain_html(remaining - 1, leaf_html, siblings)
    inner_js_lit = json.dumps(inner_html).replace("</", r"<\/")
    # K host div + 1 IIFE 跑 K 次 createElement iframe (各 host append 1 iframe)
    hosts = "".join(f'<div id="iframe-host-{s}"></div>' for s in range(siblings))
    return (
        f"{hosts}"
        f"<p>iframe-depth-{remaining} sib-{siblings}</p>"
        "<script>"
        "(function(){"
        f"  const inner = {inner_js_lit};"
        f"  for (let s = 0; s < {siblings}; s++) {{"
        '    const ifr = document.createElement("iframe");'
        "    ifr.srcdoc = inner;"
        '    ifr.style.cssText = "width:600px;height:400px;border:1px solid #ccc";'
        '    document.getElementById("iframe-host-" + s).appendChild(ifr);'
        "  }"
        "})();"
        "</script>"
    )


def _build_branch_html(shadow_count: int, leaf_per_branch: int) -> str:
    """V0.34.0+: 单 frame 内的 light + shadow 嵌套 HTML.

    leaf button 列出 N 个 (`<button id="bN">btn-N</button>`).
    shadow_count == 0: light DOM 直接 N 个 button.
    shadow_count > 0: 顶层一段 IIFE 用 DOM API 递归 attachShadow N 层, 最里层 createElement
    N 个 button (V0.34.2 fix Bug 2: V0.34.0 走 innerHTML 注入 `<script>` 不执行 HTML spec, 浅层
    shadow 仅装 leaves 时凑巧能用, 深层永远不 attach. 改 DOM API 一段顶层 script 一次跑完
    所有层 attachShadow).
    """
    if shadow_count == 0:
        leaves = "\n".join(
            f'<button id="b{i}" type="button">btn-{i}</button>'
            for i in range(leaf_per_branch)
        )
        return f'<div class="branch">{leaves}</div>'
    # V0.34.2: shadow 用 DOM API 递归 attachShadow (而非 innerHTML 注入 script)
    # depth=0 创建 N 个 button; depth>0 创建 host span + attachShadow + 嵌套调用 depth-1
    return (
        '<div id="shadow-root-host"></div>'
        "<script>"
        "(function(){"
        "  function buildChain(d, n, parent){"
        "    if (d === 0) {"
        "      for (let i = 0; i < n; i++) {"
        '        const btn = document.createElement("button");'
        "        btn.id = `b${i}`;"
        '        btn.type = "button";'
        "        btn.textContent = `btn-${i}`;"
        "        parent.appendChild(btn);"
        "      }"
        "      return;"
        "    }"
        '    const host = document.createElement("span");'
        "    host.id = `shadow-host-${d}`;"
        "    parent.appendChild(host);"
        '    const sr = host.attachShadow({mode: "open"});'
        "    buildChain(d - 1, n, sr);"
        "  }"
        f'  const root = document.getElementById("shadow-root-host");'
        f"  buildChain({shadow_count}, {leaf_per_branch}, root);"
        "})();"
        "</script>"
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


_FIXTURE_SPEC_RE = re.compile(r"^if(\d+)(?:-sib(\d+))?-sh(\d+)-leaf(\d+)$")


def _parse_fixture_spec(spec: str) -> BenchFixture:
    """V0.34.1+: 解析 fixture spec 字符串 → BenchFixture (互逆 build_synthetic_fixture fixture_id).

    支持格式:
    - `if{N}-sh{M}-leaf{K}` — V0.34.2 兼容 linear chain (siblings_per_layer=1, 默)
    - `if{N}-sib{K}-sh{M}-leaf{L}` — V0.34.3 fan-out 树状 (siblings_per_layer=K, F1 主战场)
    非法格式 raise ValueError (CLI 走 exit 2 分支).
    """
    m = _FIXTURE_SPEC_RE.match(spec.strip())
    if not m:
        raise ValueError(
            f"非法 fixture spec: {spec!r} (期望 'if{{N}}[-sib{{K}}]-sh{{M}}-leaf{{L}}', "
            f"e.g. 'if0-sh0-leaf5' 或 'if2-sib3-sh0-leaf3' fan-out)",
        )
    iframe = int(m.group(1))
    siblings = int(m.group(2)) if m.group(2) else 1
    shadow = int(m.group(3))
    leaf = int(m.group(4))
    return build_synthetic_fixture(iframe, shadow, leaf, siblings_per_layer=siblings)


def main(argv: list[str] | None = None) -> int:
    """V0.34.0+: web-agent-perceive-bench cli — fixture / compare / stats / run subcommands.

    V0.34.0 落 framework-only (fixture/compare/stats); V0.34.1 加 run subcommand 真跑 chromium
    (lazy import adapter, framework 本身仍 0-Playwright deps). gate 推荐 WEB_AGENT_RUN_SLOW=1
    (跟 test_loop_iframe / test_stealth_probe_sannysoft 同模式).

    用法:
        web-agent-perceive-bench fixture --iframe 3 --shadow 2 --leaf 5
        web-agent-perceive-bench compare data/bench/v034-A.json data/bench/v034-B.json
        web-agent-perceive-bench stats data/bench/v034-A.json
        web-agent-perceive-bench run --fixtures "if0-sh0-leaf5,if2-sh0-leaf3" --samples 5 \\
            --out data/bench/v0.34.1-baseline.json
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

    sp_run = sub.add_parser(
        "run",
        help="V0.34.1 真跑 chromium 测 perceive() (gate WEB_AGENT_RUN_SLOW=1 推荐)",
    )
    sp_run.add_argument(
        "--fixtures",
        required=True,
        help="逗号分隔 fixture spec (e.g. 'if0-sh0-leaf5,if2-sh0-leaf3')",
    )
    sp_run.add_argument("--samples", type=int, default=5, help="每 fixture sample 数 (默 5, median)")
    sp_run.add_argument("--out", help="输出 bench JSON 路径 (默 stdout)")
    sp_run.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="chromium headless (默 True; --no-headless 调试)",
    )

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
        if args.cmd == "run":
            # V0.34.1 lazy import adapter — framework-only 模块本身 0 Playwright deps
            import asyncio

            from eval.perceive_bench_adapter import run_bench_against_chromium

            fixtures = [
                _parse_fixture_spec(s) for s in args.fixtures.split(",") if s.strip()
            ]
            if not fixtures:
                sys.stderr.write("ERROR: --fixtures 空 (期望逗号分隔 spec list)\n")
                return 2
            results = asyncio.run(
                run_bench_against_chromium(
                    fixtures, samples_per=args.samples, headless=args.headless,
                ),
            )
            payload = {"bench_results": [asdict(r) for r in results]}
            text = json.dumps(payload, indent=2)
            if args.out:
                Path(args.out).write_text(text + "\n", encoding="utf-8")
                sys.stdout.write(
                    f"bench run → {args.out} ({len(results)} fixtures × {args.samples} samples)\n",
                )
            else:
                sys.stdout.write(text + "\n")
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
