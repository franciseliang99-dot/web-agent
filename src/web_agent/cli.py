"""组合根：装配 browser + llm + loop，对外暴露 run_task / main entry。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

from web_agent.browser import apply_stealth, connect
from web_agent.llm import make_client
from web_agent.loop import run_react_loop
from web_agent.memory import (
    DEFAULT_DB as _MEM_DB,
    extract_domain,
    format_memories_for_trace,
    is_success,
    recall_by_domain,
    record_task,
)
from web_agent.planner_hierarchy import (
    build_subgoal_hint_text,
    merge_into_memories,
    should_decompose,
)


async def run_task(
    goal: str,
    start_url: str | None = None,
    max_steps: int | None = None,
    max_wallclock_s: float | None = None,
    cdp_url: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    load_dotenv()
    cdp_url = cdp_url or os.environ.get("WEB_AGENT_CDP_URL", "http://127.0.0.1:9222")
    if max_steps is None:
        max_steps = int(os.environ.get("WEB_AGENT_MAX_STEPS", "20"))
    if max_wallclock_s is None:
        max_wallclock_s = float(os.environ.get("WEB_AGENT_MAX_WALLCLOCK_S", "300"))

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

        client = make_client(provider=provider, model=model)
        logger.info("LLM provider=%s model=%s", client.name, client.model)

        # W5-D.2 长期记忆 inject: 跑 ReAct 前召回该 domain 历史, 渲染成字符串注入 trace
        memories_str: str | None = None
        if os.environ.get("WEB_AGENT_MEMORY_DISABLE", "").lower() not in ("true", "1", "yes"):
            try:
                mem_db = Path(os.environ.get("WEB_AGENT_MEMORY_DB", str(_MEM_DB)))
                domain = extract_domain(start_url)
                entries = recall_by_domain(mem_db, domain, limit=5)
                memories_str = format_memories_for_trace(entries) or None
                if memories_str:
                    logger.info("recalled %d memories for domain=%r", len(entries), domain)
            except Exception as e:
                logger.warning("memory recall failed (non-fatal): %r", e)

        # W5-C 分层规划: 长任务 / 带序号任务注入 subgoal hint (纯字符串, 无 LLM 调用)
        # 复用 W5-D.2 memories= 通道, loop step=-1 synthetic step 一并 carry
        if should_decompose(goal):
            memories_str = merge_into_memories(memories_str, build_subgoal_hint_text())
            logger.info("subgoal hint injected (W5-C: 长任务 / 带序号触发)")

        result = await run_react_loop(
            page=page,
            client=client,
            goal=goal,
            max_steps=max_steps,
            max_wallclock_s=max_wallclock_s,
            db_path=Path("data/trace.db"),
            screenshots_dir=Path("data/screenshots"),
            memories=memories_str,
        )

        # W5-D 长期记忆: 跨 session 持久化 task outcome by domain.
        # try/except 包: 记忆失败 (磁盘满 / 权限) 不该阻塞主路径返回。
        if os.environ.get("WEB_AGENT_MEMORY_DISABLE", "").lower() not in ("true", "1", "yes"):
            try:
                mem_db = Path(os.environ.get("WEB_AGENT_MEMORY_DB", str(_MEM_DB)))
                record_task(mem_db, extract_domain(start_url), goal, result, is_success(result))
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
    args = parser.parse_args()

    result = asyncio.run(
        run_task(
            goal=args.goal,
            start_url=args.url,
            max_steps=args.max_steps,
            max_wallclock_s=args.max_wallclock_s,
            cdp_url=args.cdp_url,
            provider=args.provider,
            model=args.model,
        )
    )
    print("\n=== 任务结果 ===")
    print(result)


if __name__ == "__main__":
    main()
