"""V0.21.3: real-browser smoke for popup auto-register listener.

不接 9222 (隔离 chromium.launch headless), 验证 ctx.on('page') 真触发 — 弹 target=_blank
后 listener handler 收到 page 事件 + ctx.pages 自动 append 新 page (Playwright 内部行为).

@pytest.mark.slow + skipif WEB_AGENT_RUN_SLOW != "1" 双保险, 默认 CI / 本地 pytest 跳过.
本地手动跑: WEB_AGENT_RUN_SLOW=1 uv run pytest tests/test_loop_multitab.py -v
"""

from __future__ import annotations

import asyncio
import os

import pytest


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("WEB_AGENT_RUN_SLOW", "") != "1",
        reason="real chromium smoke; opt-in via WEB_AGENT_RUN_SLOW=1",
    ),
]


_HTML_WITH_TARGET_BLANK = (
    "data:text/html,"
    "<html><body>"
    "<a id=lnk href='about:blank' target='_blank'>open new tab</a>"
    "</body></html>"
)


async def test_popup_listener_triggers_on_real_target_blank_click():
    """真 chromium: 点 target=_blank → ctx.on('page') handler 被调 + ctx.pages 含新 page."""
    from playwright.async_api import async_playwright

    handler_calls: list[str] = []

    async def my_handler(page):
        handler_calls.append(getattr(page, "url", "") or "")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            ctx.on("page", my_handler)
            page = await ctx.new_page()
            await page.goto(_HTML_WITH_TARGET_BLANK)
            await page.click("#lnk")
            # listener 是 async — 给 pyee ensure_future 调度的 task 一拍时间
            await asyncio.sleep(0.2)
            assert len(handler_calls) >= 1, (
                f"target=_blank click 应触发 ctx.on('page'); got {handler_calls}"
            )
            assert len(ctx.pages) == 2, (
                f"Playwright 应自动 append popup; got {[p.url for p in ctx.pages]}"
            )
        finally:
            await browser.close()


async def test_attach_popup_listener_idempotent_against_real_ctx():
    """V0.21.3: _attach_popup_listener 调 N 次, 真 ctx 上只 .on 一次 (flag 防叠装)."""
    from playwright.async_api import async_playwright
    from web_agent.browser import _attach_popup_listener

    on_calls: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            orig_on = ctx.on

            def spy_on(event, handler):
                on_calls.append(event)
                return orig_on(event, handler)

            ctx.on = spy_on  # type: ignore[assignment]
            _attach_popup_listener(ctx)
            _attach_popup_listener(ctx)
            _attach_popup_listener(ctx)
            assert on_calls == ["page"], f"幂等失败: {on_calls}"
        finally:
            await browser.close()
