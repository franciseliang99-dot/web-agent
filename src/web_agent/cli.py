"""组合根：装配 browser + planner + loop，对外暴露 run_task / main entry。"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from web_agent.browser import apply_stealth, connect
from web_agent.loop import run_react_loop
from web_agent.planner import make_client


async def run_task(
    goal: str,
    start_url: str | None = None,
    max_steps: int | None = None,
    cdp_url: str | None = None,
    model: str | None = None,
) -> str:
    load_dotenv()
    cdp_url = cdp_url or os.environ.get("WEB_AGENT_CDP_URL", "http://localhost:9222")
    model = model or os.environ.get("WEB_AGENT_MODEL", "claude-sonnet-4-6")
    if max_steps is None:
        max_steps = int(os.environ.get("WEB_AGENT_MAX_STEPS", "20"))

    async with async_playwright() as p:
        browser, ctx, page = await connect(p, cdp_url=cdp_url)
        await apply_stealth(page)

        vw = int(os.environ.get("WEB_AGENT_VIEWPORT_WIDTH", "1280"))
        vh = int(os.environ.get("WEB_AGENT_VIEWPORT_HEIGHT", "800"))
        try:
            await page.set_viewport_size({"width": vw, "height": vh})
        except Exception as e:
            print(f"[cli] set_viewport_size 失败 ({e!r})，沿用 Chrome 默认视口")

        if start_url:
            print(f"[cli] navigating to {start_url}")
            await page.goto(start_url, wait_until="domcontentloaded")

        client = make_client()
        result = await run_react_loop(
            page=page,
            client=client,
            model=model,
            goal=goal,
            max_steps=max_steps,
            db_path=Path("data/trace.db"),
            screenshots_dir=Path("data/screenshots"),
        )
        return result


def main() -> None:
    parser = argparse.ArgumentParser(prog="web-agent", description="高度拟人 AI web agent")
    parser.add_argument("goal", help="自然语言任务描述")
    parser.add_argument("--url", default=None, help="起始 URL（可选）")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--cdp-url", default=None, help="覆盖 WEB_AGENT_CDP_URL（默认 http://localhost:9222）")
    parser.add_argument("--model", default=None, help="覆盖 WEB_AGENT_MODEL")
    args = parser.parse_args()

    result = asyncio.run(
        run_task(
            goal=args.goal,
            start_url=args.url,
            max_steps=args.max_steps,
            cdp_url=args.cdp_url,
            model=args.model,
        )
    )
    print("\n=== 任务结果 ===")
    print(result)


if __name__ == "__main__":
    main()
