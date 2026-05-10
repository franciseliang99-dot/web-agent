"""CDP 接管已启动的本地 Chrome（--remote-debugging-port=9222）。"""

from __future__ import annotations

import asyncio
import logging
import random

from playwright.async_api import Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)


async def _popup_notice_handler(page: Page) -> None:
    """V0.21.3: ctx.on('page') 回调 — 新 top-level page (popup / window.open) 出现时拟人延迟.

    Playwright `_on_page` 已先 `_pages.append(page)` 后 emit, 所以 ctx.pages 已含新 page;
    此 handler 仅模拟"人类注意到新 tab 弹出"的反应延迟 0.3-0.8s, **不抢焦点** (不调
    bring_to_front, 不改 active_idx) — 模仿 target=_blank 时人眼看到 tab 但继续读当前 tab.

    pyee AsyncIOEventEmitter 自动 ensure_future 把 async handler 调度成独立 task,
    不阻塞主 loop. **不装 page.on('popup')** — Playwright 内部 popup 事件已通过
    ctx.on('page') 接住一次, 双装会让 sleep 跑两遍 (V0.21.3 sanity 实测).
    """
    delay = random.uniform(0.3, 0.8)
    await asyncio.sleep(delay)
    url_preview = (getattr(page, "url", "") or "")[:80]
    logger.info("popup detected (delay=%.2fs): %s", delay, url_preview)


def _attach_popup_listener(ctx: BrowserContext) -> None:
    """V0.21.3: 给 ctx 装 popup listener, 幂等 (重装等于重 emit, 防 cli/jd_extract/list_extract
    都各自 connect 时叠装).

    用 `_web_agent_popup_listener` private flag 标记已装 — Playwright BrowserContext 是
    动态属性容器, 这种 monkey-patch flag 是 Playwright 生态常见模式.
    """
    if getattr(ctx, "_web_agent_popup_listener", False):
        return
    ctx.on("page", _popup_notice_handler)
    ctx._web_agent_popup_listener = True  # type: ignore[attr-defined]


async def connect(
    p: Playwright,
    cdp_url: str = "http://127.0.0.1:9222",
) -> tuple[Browser, BrowserContext, Page]:
    """连接已启动的 Chrome 调试端口，返回 (browser, context, page)。

    用户必须先在终端跑 `bash scripts/start_chrome.sh` 启动带 9222 端口的 Chrome。

    注：默认用 127.0.0.1 而非 localhost — 部分 Linux 发行版 IPv6 优先，
    `localhost` 会 resolve 到 ::1，但 chrome `--remote-debugging-port` 只 listen IPv4。
    用户可通过 WEB_AGENT_CDP_URL env 覆盖（cli.py 读）。

    V0.21.3: 装 ctx.on('page') popup listener 抓 target=_blank / window.open() 弹的子 tab.
    listener 装在 connect (跨 cli/jd_extract/list_extract 三个 entry 一次性), 而非 loop
    (loop 不感知 popup 注册逻辑, 解耦更干净).
    """
    browser = await p.chromium.connect_over_cdp(cdp_url)
    if not browser.contexts:
        raise RuntimeError(
            f"已连接 {cdp_url} 但 contexts 为空 — Chrome 可能没开任何窗口。"
        )
    ctx = browser.contexts[0]
    _attach_popup_listener(ctx)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return browser, ctx, page


async def apply_stealth(page: Page) -> None:
    """注入 stealth patches，抹除 navigator.webdriver 等自动化痕迹。

    playwright-stealth 2.x 的 API 在不同 minor 版本间有调整，这里做容错：
    如果当前安装版本 API 不匹配，warn 后跳过——主流程不挂。
    """
    try:
        from playwright_stealth import Stealth

        stealth = Stealth()
        if hasattr(stealth, "apply_stealth_async"):
            await stealth.apply_stealth_async(page)
        elif hasattr(stealth, "apply_async"):
            await stealth.apply_async(page)
        else:
            logger.warning("playwright-stealth API 未匹配（既无 apply_stealth_async 也无 apply_async），跳过")
    except ImportError:
        logger.warning("playwright-stealth 未安装，跳过 stealth")
    except Exception as e:
        logger.warning("stealth 注入失败 (%r)，跳过", e)
