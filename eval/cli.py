"""V0.26.3: web-agent-eval CLI entry script.

跑 corpus + dump JSON + 渲染 markdown 报告. 双 opt-in env 防意外烧 token / 跑慢.

用法:
  WEB_AGENT_RUN_EVAL=1 web-agent-eval --corpus all --providers anthropic --output data/eval/
  WEB_AGENT_RUN_EVAL=1 WEB_AGENT_EVAL_REAL=1 web-agent-eval --providers anthropic,openai

env:
  WEB_AGENT_RUN_EVAL=1      启用 eval (默认不设 → exit 1, 防意外跑慢/烧 token)
  WEB_AGENT_EVAL_REAL=1     真调 LLM (默认不设 → 走 cassette 回放; 缺 cassette → 提示)
  ANTHROPIC_API_KEY / OPENAI_API_KEY  跑真 LLM 时需要

输出:
  data/eval/<run_id>.json    完整 metrics + aggregate (V0.26.4 replay 面板加载)
  stdout                      markdown 跨 provider 对比表 + by-axis 矩阵
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from eval.types import EvalTask

logger = logging.getLogger(__name__)


def _parse_providers(raw: str) -> list[str]:
    """V0.26.3: --providers anthropic,openai → ["anthropic", "openai"]. 空 → ["anthropic"] 默认."""
    if not raw:
        return ["anthropic"]
    return [p.strip() for p in raw.split(",") if p.strip()]


def _select_tasks_chain_real_world() -> list:  # type: ignore[type-arg]
    """V0.32.3: 虚拟 axis 'chain-real-world' — V0.32 D' 双轴交叉 (real-world axis ∩ chain_spec≠None).

    现 _select_tasks 支单 axis 选 (CapabilityAxis 12 项), 'chain-real-world' 不在 Literal 内,
    走 special case if 分支返 V0.32.0 + V0.32.2 加的 2 chain real-world task (跨 V0.29.4 chain
    framework + V0.30 D real-world axis 双轴叠加).
    """
    from eval.corpus import ALL_TASKS
    return [t for t in ALL_TASKS if t.capability_axis == "real-world" and t.chain_spec is not None]


def _select_tasks_capability_real_world() -> list:  # type: ignore[type-arg]
    """V0.35.3: 虚拟 axis 'capability-real-world' — V0.35 A 双轴交叉 (real-world axis ∩ V0.35 actuator task).

    V0.35.0+V0.35.2 加的 3 actuator 真站点轴 task (search / click-nav / scroll), 通过 tag 'v035'
    区分. 跟 V0.32.3 'chain-real-world' 同 pattern (real-world ∩ feature axis 双标).

    `--corpus capability-real-world` 让 maintainer 单跑 V0.35 actuator task 不 wading 全 corpus.
    """
    from eval.corpus import ALL_TASKS
    return [t for t in ALL_TASKS if t.capability_axis == "real-world" and "v035" in t.tags]


def _select_tasks(corpus_filter: str) -> list:  # type: ignore[type-arg]
    """V0.26.3+V0.32.3+V0.35.3: --corpus all / <axis> / 'chain-real-world' / 'capability-real-world'.

    - "all": 全 corpus (default)
    - "chain-real-world" (V0.32.3 虚拟 axis): real-world ∩ chain_spec≠None (V0.32 D' 双轴交叉)
    - "capability-real-world" (V0.35.3 虚拟 axis): real-world ∩ V0.35 actuator task (A 双轴交叉)
    - 其他: capability_axis 单选 (V0.26.0 CapabilityAxis Literal 12 项)
    """
    from eval.corpus import ALL_TASKS
    if corpus_filter == "all":
        return list(ALL_TASKS)
    if corpus_filter == "chain-real-world":
        return _select_tasks_chain_real_world()
    if corpus_filter == "capability-real-world":
        return _select_tasks_capability_real_world()
    return [t for t in ALL_TASKS if t.capability_axis == corpus_filter]


def _check_opt_in_env() -> None:
    """V0.26.3: WEB_AGENT_RUN_EVAL=1 必须设, 防意外跑慢 / 烧 token. exit 1 + 提示."""
    if os.environ.get("WEB_AGENT_RUN_EVAL", "") != "1":
        sys.stderr.write(
            "ERROR: web-agent-eval 必须设 env WEB_AGENT_RUN_EVAL=1 才能跑 (防意外烧 token).\n"
            "用法: WEB_AGENT_RUN_EVAL=1 web-agent-eval --corpus all\n"
        )
        sys.exit(1)


def _assert_live_net_consistency(tasks: list[EvalTask]) -> None:
    """V0.30.4 (subagent V0.30.3 R3 收尾): EVAL_REAL=1 + selected tasks 含 requires_real_net=True
    时, LIVE_NET 必须 = 1 (一致性: 既要烧 token 又要走真网).

    防 maintainer 设 EVAL_REAL=1 但忘 LIVE_NET=1 → record_mode='none' + 真 LLM call → vcr 拒
    → INFRA_ERROR 困惑 (V0.30.3 hidden risk #3). fail-fast exit 1 显式报错优于 silently fall back.

    顺序关键: 必须在 _filter_requires_real_net **之前** call (filter 后 LIVE_NET=0 时 real-net
    task 已被剔, assert 无意义).

    EVAL_REAL=0 (cassette 严回放) + real-net task → 不 assert (cassette 模式无需 LIVE_NET).
    """
    if os.environ.get("WEB_AGENT_EVAL_REAL", "") != "1":
        return  # cassette replay 模式不需 LIVE_NET assert
    has_real_net_task = any(t.requires_real_net for t in tasks)
    if not has_real_net_task:
        return  # 无 real-net task EVAL_REAL=1 OK (老 data:html corpus)
    if os.environ.get("WEB_AGENT_EVAL_LIVE_NET", "") != "1":
        sys.stderr.write(
            "ERROR: EVAL_REAL=1 + selected tasks 含 requires_real_net=True 必须配 EVAL_LIVE_NET=1\n"
            "  (一致性: 既要烧 token 又要走真网录 cassette).\n"
            "  解: 加 WEB_AGENT_EVAL_LIVE_NET=1 真录 cassette, 或 unset EVAL_REAL 走 cassette 严回放.\n"
        )
        sys.exit(1)


def _filter_requires_real_net(tasks: list[EvalTask]) -> list[EvalTask]:
    """V0.30.1 D real-world: requires_real_net=True task 默跳, EVAL_LIVE_NET=1 才放行.

    三级 env 模型 (subagent C 决):
    - WEB_AGENT_RUN_EVAL=1 (必): eval 启用
    - WEB_AGENT_EVAL_REAL=1 (可): 真调 LLM (默 cassette 回放)
    - WEB_AGENT_EVAL_LIVE_NET=1 (可): 真访外网 (默跳 requires_real_net=True task)

    LIVE_NET 跟 EVAL_REAL 正交 — LIVE_NET 是网络 axis (外网请求), REAL 是 LLM axis (token 烧).
    """
    if os.environ.get("WEB_AGENT_EVAL_LIVE_NET", "") == "1":
        return tasks
    skipped = [t for t in tasks if t.requires_real_net]
    if skipped:
        logger.info(
            "V0.30.1: 跳过 %d task requires_real_net=True (set WEB_AGENT_EVAL_LIVE_NET=1 启用): %s",
            len(skipped), [t.task_id for t in skipped],
        )
    return [t for t in tasks if not t.requires_real_net]


def _check_real_eval_or_cassette(cassette_dir: Path) -> bool:
    """V0.26.3: 返 True = 真调 LLM, False = cassette 回放. 缺 cassette + 未 EVAL_REAL=1 → exit 1.

    EVAL_REAL=1 用真 LLM (烧 token; 仅 maintainer baseline / 重录 cassette);
    未设 → 找 cassette_dir 下 cassette 文件回放; 都没 → exit 1 提示用户.
    """
    if os.environ.get("WEB_AGENT_EVAL_REAL", "") == "1":
        return True
    # cassette 模式: 查 cassette_dir 是否有 .yaml
    if not cassette_dir.exists() or not list(cassette_dir.glob("*.yaml")):
        sys.stderr.write(
            f"ERROR: cassette_dir={cassette_dir} 无 .yaml; 默认 cassette 模式无法跑.\n"
            "set WEB_AGENT_EVAL_REAL=1 + ANTHROPIC_API_KEY 真调 LLM 录 cassette (V0.26.4 baseline).\n"
        )
        sys.exit(1)
    return False


async def _run_async(args: argparse.Namespace) -> int:
    """V0.26.3: async main — make_client + run_corpus + dump_json + 渲染 markdown."""
    from dotenv import load_dotenv
    from playwright.async_api import async_playwright

    from eval.corpus import ALL_PREDICATES
    from eval.report import (
        dump_json,
        render_capability_axis_markdown,
        render_provider_summary_markdown,
        render_reflective_uplift_markdown,
    )
    from eval.runner import run_corpus
    from web_agent.llm import make_client

    # V0.26.4: load .env (跟 web_agent.cli 同模式) — 让 OPENAI_API_KEY/ANTHROPIC_API_KEY/
    # OPENAI_BASE_URL 等从 .env 加载. 主 cli 已 load 但 eval/cli.py 是独立 entry.
    load_dotenv()

    tasks = _select_tasks(args.corpus)
    # V0.30.4 D real-world: EVAL_REAL=1 + real-net task → LIVE_NET 必须一致 (subagent V0.30.3 R3 收)
    _assert_live_net_consistency(tasks)
    # V0.30.1 D real-world: filter requires_real_net=True 默跳 (LIVE_NET=1 才放行)
    tasks = _filter_requires_real_net(tasks)
    if not tasks:
        sys.stderr.write(f"ERROR: corpus filter {args.corpus!r} 无匹配 task\n")
        return 1
    logger.info("eval: %d task selected (corpus=%s)", len(tasks), args.corpus)

    providers = _parse_providers(args.providers)
    clients = []
    for provider_name in providers:
        try:
            clients.append(make_client(provider=provider_name))
        except RuntimeError as e:
            logger.warning("skip provider %s: %s", provider_name, e)
    if not clients:
        sys.stderr.write("ERROR: 无可用 client (检查 API key env)\n")
        return 1
    logger.info("eval: %d client (providers=%s)", len(clients), providers)

    # cassette dir 在 eval/cassettes/ 隔离 tests/cassettes
    cassette_dir = Path(__file__).parent / "cassettes"
    use_real = _check_real_eval_or_cassette(cassette_dir)
    logger.info("eval: mode=%s", "real-LLM" if use_real else "cassette-replay")

    # output dir
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "trace.db"
    shots_dir = output_dir / "screenshots"

    # V0.28.3 W6 收尾: --reflect 触发 2-pass + isolated memory.db 防 Risk #1 跨 task 污染
    eval_memory_db = output_dir / "eval_memory.db" if args.reflect else None

    async with async_playwright() as playwright:
        report = await run_corpus(
            tasks, clients, ALL_PREDICATES,
            db_path=db_path, screenshots_dir=shots_dir,
            chromium_launcher=playwright.chromium,
            reflect=args.reflect,
            memory_db_path=eval_memory_db,
        )

    # dump JSON + 渲染 markdown
    from web_agent import __version__
    from eval import __version__ as eval_version
    json_path = dump_json(
        report, tasks, output_dir,
        web_agent_version=__version__,
        corpus_version=eval_version,
        vcr_replay=not use_real,
    )
    sys.stdout.write(f"\n=== eval JSON 落档 ===\n{json_path}\n")
    sys.stdout.write("\n=== 跨 provider 对比 ===\n")
    sys.stdout.write(render_provider_summary_markdown(report) + "\n")
    sys.stdout.write("\n=== 按 capability_axis 分组 ===\n")
    sys.stdout.write(render_capability_axis_markdown(report, tasks) + "\n")
    if args.reflect:
        sys.stdout.write("\n=== W6 reflective uplift (V0.28.3 --reflect 2-pass) ===\n")
        sys.stdout.write(render_reflective_uplift_markdown(report, tasks) + "\n")
    return 0


def main() -> None:
    """V0.26.3: web-agent-eval entry. argparse + opt-in env check + async runner."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[%(name)s] %(message)s")
    parser = argparse.ArgumentParser(
        prog="web-agent-eval",
        description="V0.26 eval golden corpus runner (V0.27 vault / V0.28 无人值守 数据底座)",
    )
    parser.add_argument(
        "--corpus", default="all",
        help=(
            "task 选择: 'all' 跑全 corpus; 或 capability_axis 单选 (e.g. 'iframe' / 'multi-tab' / "
            "'real-world' V0.30 真外网 task 默 LIVE_NET=1 才放行); 或虚拟 axis "
            "'chain-real-world' (V0.32 D' 双轴交叉: real-world ∩ chain_spec) / "
            "'capability-real-world' (V0.35 A 双轴: real-world ∩ V0.35 actuator task)"
        ),
    )
    parser.add_argument(
        "--providers", default="anthropic",
        help="comma-separated provider list (e.g. 'anthropic' / 'anthropic,openai'); 默认 anthropic",
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="每 task × provider grid 跑几次取均值 (V0.26 plan B4 推荐 N=3); V0.26.3 默认 1",
    )
    parser.add_argument(
        "--output", default="data/eval/",
        help="JSON dump 目录 (V0.26.4 replay 面板加载); 默认 data/eval/",
    )
    parser.add_argument(
        "--lint-only", action="store_true",
        help="仅跑 lint_corpus_tokens 不跑真 eval (V0.26.1 token-specific 强制检查)",
    )
    parser.add_argument(
        "--reflect", action="store_true",
        help=(
            "V0.28.3 W6 收尾: 同 task 跑 2 次 (run1 baseline / run2 inject reflections) 算 "
            "reflective_uplift = pass2_rate - pass1_rate. **token cost 翻倍** (~$0.4-0.8 单 corpus), "
            "默关 opt-in. 必须配 isolated memory.db (output_dir/eval_memory.db)."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help=(
            "V0.37.0: 列将要跑的 task + 估 cost + 校 env, 但**不开 chromium 不调 LLM** "
            "(0 token 0 wallclock). 给 maintainer 真跑前 sanity check, 防意外烧 token. "
            "跟 --lint-only 不同: dry-run 经过完整 task filter + env check 链路, 只 short-circuit "
            "在 _run_async 之前."
        ),
    )
    args = parser.parse_args()

    # lint 模式: 不需 RUN_EVAL=1 (lint 0 token 0 chromium)
    if args.lint_only:
        from eval.corpus import ALL_PREDICATES, ALL_TASKS, lint_corpus_tokens
        violations = lint_corpus_tokens(ALL_TASKS, ALL_PREDICATES)
        if violations:
            sys.stderr.write("LINT FAIL:\n" + "\n".join(violations) + "\n")
            sys.exit(1)
        sys.stdout.write(f"LINT OK: {len(ALL_TASKS)} task tokens 全过 task-specific 检查\n")
        return

    # V0.37.0: --dry-run 走完整 task filter 但不调 chromium / LLM. 放在 _check_opt_in_env 之前,
    # 让 maintainer 不设 RUN_EVAL=1 就能 sanity check task list + 估 cost + 验 env vars.
    # 跟 V0.33.4 B' baseline 双跑 deferred 配合 — 真烧 token 前先 dry-run 列 task / 估 cost / 验 key.
    if args.dry_run:
        tasks = _select_tasks(args.corpus)
        if not tasks:
            sys.stderr.write(f"ERROR: --corpus {args.corpus!r} 没匹配任何 task (检查 axis 拼写)\n")
            sys.exit(1)
        providers = [p.strip() for p in args.providers.split(",") if p.strip()]
        if not providers:
            sys.stderr.write("ERROR: --providers 解析后为空\n")
            sys.exit(1)
        # cost 估算 (V0.33.4 引: Anthropic ~$0.05-0.10/task, OpenAI/Kimi 类似量级)
        per_task_cost_lo, per_task_cost_hi = 0.05, 0.10
        total_runs = len(tasks) * len(providers) * args.runs
        cost_lo = total_runs * per_task_cost_lo
        cost_hi = total_runs * per_task_cost_hi
        real_net_count = sum(1 for t in tasks if t.requires_real_net)
        sys.stdout.write(
            f"# DRY-RUN (V0.37.0)\n"
            f"corpus filter: {args.corpus}\n"
            f"providers: {', '.join(providers)}\n"
            f"runs: {args.runs}\n"
            f"task count: {len(tasks)} (含 {real_net_count} real-net task)\n"
            f"total runs: {total_runs} ({len(tasks)} task × {len(providers)} provider × {args.runs} run)\n"
            f"estimated cost: ~${cost_lo:.2f}-${cost_hi:.2f} (Anthropic ~$0.05-0.10/task, V0.33.4 估)\n"
            f"\n## task list\n",
        )
        for t in sorted(tasks, key=lambda x: x.task_id):
            real_net = " [real-net]" if t.requires_real_net else ""
            sys.stdout.write(f"  - {t.task_id} (axis={t.capability_axis}){real_net}\n")
        sys.stdout.write("\n## env vars check\n")
        env_checks = [
            ("WEB_AGENT_RUN_EVAL", "1", "必"),
            ("WEB_AGENT_EVAL_REAL", "1", "可 (默 cassette replay; 真跑必)"),
            ("WEB_AGENT_EVAL_LIVE_NET", "1", "可 (real-net task 真访外网必)"),
        ]
        for var, expected, hint in env_checks:
            cur = os.environ.get(var, "")
            mark = "✓" if cur == expected else "✗"
            sys.stdout.write(f"  [{mark}] {var}={cur or '(unset)'} (期望 {expected}, {hint})\n")
        # API key 检查 (不调 make_client 仅 env presence)
        provider_key_map = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
        for p in providers:
            key_var = provider_key_map.get(p, f"{p.upper()}_API_KEY")
            has_key = bool(os.environ.get(key_var, "").strip())
            mark = "✓" if has_key else "✗"
            sys.stdout.write(f"  [{mark}] {key_var} ({'set' if has_key else 'unset'}, provider {p})\n")
        sys.stdout.write("\nDRY-RUN OK. 真跑去掉 --dry-run 即可.\n")
        return

    _check_opt_in_env()

    # V0.26.3: --runs 留 V0.26.4 baseline 真跑时实现 (本 commit 仅 1 run scope)
    if args.runs != 1:
        logger.warning("V0.26.3 仅支持 --runs 1 (N=3 取均值留 V0.26.4 baseline 落档时实现)")

    sys.exit(asyncio.run(_run_async(args)))


if __name__ == "__main__":
    main()
