"""组合根：装配 browser + llm + loop，对外暴露 run_task / main entry。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from web_agent.browser import apply_stealth, connect
from web_agent.chrome_launcher import ensure_chrome_running
from web_agent.llm import make_client

if TYPE_CHECKING:
    from web_agent.vault import SecretStore
from web_agent.loop import ProgressCallback, SafetyApprovalCallback, run_react_loop
from web_agent.memory import (
    DEFAULT_DB as _MEM_DB,
    extract_domain,
    format_memories_for_trace,
    format_reflections_for_trace,
    is_success,
    recall_by_domain,
    recall_reflections_by_domain,
    record_task,
)
from web_agent.planner_hierarchy import (
    build_subgoal_hint_text,
    merge_into_memories,
    should_decompose,
)

logger = logging.getLogger(__name__)


async def run_task(
    goal: str,
    start_url: str | None = None,
    max_steps: int | None = None,
    max_wallclock_s: float | None = None,
    cdp_url: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    progress_cb: ProgressCallback | None = None,
    safety_approval_cb: SafetyApprovalCallback | None = None,
    secret_store: "SecretStore | None" = None,
) -> str:
    load_dotenv()
    cdp_url = cdp_url or os.environ.get("WEB_AGENT_CDP_URL", "http://127.0.0.1:9222")
    if max_steps is None:
        max_steps = int(os.environ.get("WEB_AGENT_MAX_STEPS", "20"))
    if max_wallclock_s is None:
        max_wallclock_s = float(os.environ.get("WEB_AGENT_MAX_WALLCLOCK_S", "300"))

    # V0.16.19: 9222 不可达时自动 spawn Chrome (WEB_AGENT_AUTO_SPAWN_CHROME=false 关)
    await asyncio.to_thread(ensure_chrome_running, cdp_url)

    async with async_playwright() as p:
        browser, ctx, page = await connect(p, cdp_url=cdp_url)
        await apply_stealth(page)

        vw = int(os.environ.get("WEB_AGENT_VIEWPORT_WIDTH", "1280"))
        vh = int(os.environ.get("WEB_AGENT_VIEWPORT_HEIGHT", "800"))
        try:
            await page.set_viewport_size({"width": vw, "height": vh})
        except Exception as e:
            logger.warning("set_viewport_size 失败 (%r)，沿用 Chrome 默认视口", e)

        if start_url:
            logger.info("navigating to %s", start_url)
            await page.goto(start_url, wait_until="domcontentloaded")

        client = make_client(provider=provider, model=model, secret_store=secret_store)
        logger.info("LLM provider=%s model=%s", client.name, client.model)

        # W5-D.2 长期记忆 inject: 跑 ReAct 前召回该 domain 历史, 渲染成字符串注入 trace
        mem_db = Path(os.environ.get("WEB_AGENT_MEMORY_DB", str(_MEM_DB)))
        domain = extract_domain(start_url)
        memories_str: str | None = None
        if os.environ.get("WEB_AGENT_MEMORY_DISABLE", "").lower() not in ("true", "1", "yes"):
            try:
                entries = recall_by_domain(mem_db, domain, limit=5)
                memories_str = format_memories_for_trace(entries) or None
                if memories_str:
                    logger.info("recalled %d memories for domain=%r", len(entries), domain)
            except Exception as e:
                logger.warning("memory recall failed (non-fatal): %r", e)

        # V0.28.2 W6-B: cli 启动按 domain 拉 reflections 注入 (复用 W5-D.2 memories= 通道,
        # subagent A 决 — W5-C subgoal hint 已开 merge_into_memories 一段拼接先例).
        # 顺序 memories (历史结果) → reflections (失败教训) → subgoal hint (规划提示):
        # 由具体到抽象自然过渡; reflections 经验提炼不重复 memories 的"任务结果"信息.
        if os.environ.get("WEB_AGENT_REFLECTIONS_DISABLE", "").lower() not in ("true", "1", "yes"):
            try:
                refl_entries = recall_reflections_by_domain(mem_db, domain, limit=3)
                refl_str = format_reflections_for_trace(refl_entries)
                if refl_str:
                    memories_str = merge_into_memories(memories_str, refl_str)
                    logger.info("recalled %d reflections for domain=%r", len(refl_entries), domain)
            except Exception as e:
                # reflections 表不存在 (V0.28.1 W6-A 失败时才建表) → silent swallow,
                # 跟 memory recall 同模式不阻塞主路径
                logger.warning("reflections recall failed (non-fatal): %r", e)

        # W5-C 分层规划: 长任务 / 带序号任务注入 subgoal hint (纯字符串, 无 LLM 调用)
        # 复用 W5-D.2 memories= 通道, loop step=-1 synthetic step 一并 carry
        if should_decompose(goal):
            memories_str = merge_into_memories(memories_str, build_subgoal_hint_text())
            logger.info("subgoal hint injected (W5-C: 长任务 / 带序号触发)")

        # V0.28.1 W6-A: 传 domain + memory_db_path 让 loop _maybe_reflect_on_failure 在 max_steps
        # / LOOP_DETECTED 触发时按 domain 写 reflections 表 (V0.28.2 cli 启动 inject 给下次看).
        # V0.28.2: 复用上方 mem_db / domain (避免重复 env 读 + extract_domain 调用).
        result = await run_react_loop(
            ctx=ctx,
            client=client,
            goal=goal,
            max_steps=max_steps,
            max_wallclock_s=max_wallclock_s,
            db_path=Path("data/trace.db"),
            screenshots_dir=Path("data/screenshots"),
            memories=memories_str,
            progress_cb=progress_cb,
            safety_approval_cb=safety_approval_cb,
            domain=domain,
            memory_db_path=mem_db,
        )

        # W5-D 长期记忆: 跨 session 持久化 task outcome by domain.
        # try/except 包: 记忆失败 (磁盘满 / 权限) 不该阻塞主路径返回。
        if os.environ.get("WEB_AGENT_MEMORY_DISABLE", "").lower() not in ("true", "1", "yes"):
            try:
                record_task(mem_db, domain, goal, result, is_success(result))
            except Exception as e:
                logger.warning("memory record failed (non-fatal): %r", e)

        return result


def main() -> None:
    # MCP server (V0.16.0+) 硬前提: 业务模块全用 logging.info(stderr) 不污染 stdout (JSON-RPC 通道)
    # CLI 模式 stdout 仍留给用户结果 (=== 任务结果 ===), logger 走 stderr
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="[%(name)s] %(message)s",
    )
    parser = argparse.ArgumentParser(prog="web-agent", description="高度拟人 AI web agent")
    parser.add_argument("goal", help="自然语言任务描述")
    parser.add_argument("--url", default=None, help="起始 URL（可选）")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--max-wallclock-s", type=float, default=None, help="覆盖 WEB_AGENT_MAX_WALLCLOCK_S（默认 300s）")
    parser.add_argument("--cdp-url", default=None, help="覆盖 WEB_AGENT_CDP_URL（默认 http://localhost:9222）")
    parser.add_argument("--provider", default=None, help="覆盖 WEB_AGENT_LLM_PROVIDER（anthropic/openai）")
    parser.add_argument("--model", default=None, help="覆盖 WEB_AGENT_MODEL")
    parser.add_argument(
        "--capability-hint",
        default=None,
        help="V0.27.5 routing hint (eval.types.CapabilityAxis: multi-tab/iframe/drag/upload/"
             "download/dialog/keyboard-nav/failure-recovery/baseline/...). 提供时数据驱动 "
             "select_provider 选 baseline 强项 provider, 覆盖 --provider.",
    )
    args = parser.parse_args()

    # V0.27.5 隐藏 P2 修: load_dotenv 提前到 select_provider 之前 (现 run_task 内才 load,
    # 顺序错 → available_providers_from_env() 读不到 .env 的 ANTHROPIC_API_KEY/OPENAI_API_KEY).
    # load_dotenv 默 override=False, run_task 内再调一次也安全 (幂等).
    load_dotenv()
    provider = args.provider
    if args.capability_hint:
        from web_agent.routing import select_provider
        provider = select_provider(args.capability_hint)
        logger.info("V0.27.5 routing: capability_hint=%r → provider=%r", args.capability_hint, provider)

    result = asyncio.run(
        run_task(
            goal=args.goal,
            start_url=args.url,
            max_steps=args.max_steps,
            max_wallclock_s=args.max_wallclock_s,
            cdp_url=args.cdp_url,
            provider=provider,
            model=args.model,
        )
    )
    print("\n=== 任务结果 ===")
    print(result)


if __name__ == "__main__":
    main()
