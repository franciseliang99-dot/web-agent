"""CDP 接管已启动的本地 Chrome（--remote-debugging-port=9222）。"""

from __future__ import annotations

from playwright.async_api import Browser, BrowserContext, Page, Playwright


async def connect(
    p: Playwright,
    cdp_url: str = "http://localhost:9222",
) -> tuple[Browser, BrowserContext, Page]:
    """连接已启动的 Chrome 调试端口，返回 (browser, context, page)。

    用户必须先在终端跑 `bash scripts/start_chrome.sh` 启动带 9222 端口的 Chrome。
    """
    browser = await p.chromium.connect_over_cdp(cdp_url)
    if not browser.contexts:
        raise RuntimeError(
            f"已连接 {cdp_url} 但 contexts 为空 — Chrome 可能没开任何窗口。"
        )
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return browser, ctx, page


async def apply_stealth(page: Page) -> None:
    """注入 stealth patches，抹除 navigator.webdriver 等自动化痕迹。

    playwright-stealth 2.x 的 API 在不同 minor 版本间有调整，这里做容错：
    如果当前安装版本 API 不匹配，warn 后跳过——主流程不挂。
    """
    try:
        from playwright_stealth import Stealth  # type: ignore[import-untyped]

        stealth = Stealth()
        if hasattr(stealth, "apply_stealth_async"):
            await stealth.apply_stealth_async(page)
        elif hasattr(stealth, "apply_async"):
            await stealth.apply_async(page)
        else:
            print("[browser] playwright-stealth API 未匹配（既无 apply_stealth_async 也无 apply_async），跳过")
    except ImportError:
        print("[browser] playwright-stealth 未安装，跳过 stealth")
    except Exception as e:
        print(f"[browser] stealth 注入失败 ({e!r})，跳过")
