"""组合根：装配 browser + llm + loop，对外暴露 run_task / main entry。"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from web_agent.browser import apply_stealth, connect
from web_agent.llm import make_client
from web_agent.loop import run_react_loop
from web_agent.memory import (
    DEFAULT_DB as _MEM_DB,
    extract_domain,
    is_success,
    record_task,
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
            print(f"[cli] set_viewport_size 失败 ({e!r})，沿用 Chrome 默认视口")

        if start_url:
            print(f"[cli] navigating to {start_url}")
            await page.goto(start_url, wait_until="domcontentloaded")

        client = make_client(provider=provider, model=model)
        print(f"[cli] LLM provider={client.name} model={client.model}")
        result = await run_react_loop(
            page=page,
            client=client,
            goal=goal,
            max_steps=max_steps,
            max_wallclock_s=max_wallclock_s,
            db_path=Path("data/trace.db"),
            screenshots_dir=Path("data/screenshots"),
        )

        # W5-D 长期记忆: 跨 session 持久化 task outcome by domain.
        # try/except 包: 记忆失败 (磁盘满 / 权限) 不该阻塞主路径返回。
        if os.environ.get("WEB_AGENT_MEMORY_DISABLE", "").lower() not in ("true", "1", "yes"):
            try:
                mem_db = Path(os.environ.get("WEB_AGENT_MEMORY_DB", str(_MEM_DB)))
                record_task(mem_db, extract_domain(start_url), goal, result, is_success(result))
            except Exception as e:
                print(f"[cli] memory record failed (non-fatal): {e!r}")

        return result


def main() -> None:
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
