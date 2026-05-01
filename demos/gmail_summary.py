"""W3-B demo: Gmail 收件箱概要 (read-only, 最新 5 封邮件的发件人 + 主题)。

前置：必须先在 chrome user-data-dir 里手动登 Gmail（一次性）。

  方式 A — 本机有 GUI / SSH 转发了 X11 / VNC：
    1. 用 CHROME_MODE=headed 起 chrome (本机 GUI 时会自动选)
    2. 在该 chrome 窗口里 goto https://mail.google.com/ 手动登录
    3. cookies 持久化到 ~/.config/web-agent-chrome/Default/Cookies
    4. 关掉 headed chrome, 重启 headless: bash scripts/start_chrome.sh

  方式 B — SSH 无 GUI 机器（无 X11 转发）：
    把本地 chrome 登好 Gmail 后的 ~/.config/google-chrome/Default/Cookies 文件
    scp 到 server 的 ~/.config/web-agent-chrome/Default/Cookies, 重启 chrome 即可

用法:
  uv run python demos/gmail_summary.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from playwright.async_api import async_playwright

from web_agent.browser import connect
from web_agent.cli import run_task


async def _check_logged_in(cdp_url: str) -> tuple[bool, str]:
    """前置检测：goto Gmail 看是否跳到登录页面 / 不支持浏览器页。返回 (logged_in, url_or_reason)。"""
    async with async_playwright() as p:
        try:
            browser, ctx, page = await connect(p, cdp_url=cdp_url)
        except Exception as e:
            return False, f"connect_over_cdp failed: {e!r}"
        try:
            await page.goto("https://mail.google.com/", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            return False, f"goto failed: {e!r}"
        url = page.url
        if "accounts.google.com" in url or "/signin" in url or "mail.google.com/about" in url:
            return False, url
        try:
            text = await page.evaluate(
                "() => (document.body && document.body.innerText || '').slice(0, 800).toLowerCase()"
            )
        except Exception:
            text = ""
        if "browser" in text and ("not supported" in text or "may not be secure" in text):
            return False, "page-flag: browser not supported / may not be secure"
        return True, url


def _print_login_help() -> None:
    print(
        "\n⚠ Gmail 未登录（或被 Google 反 bot 拦）。先手动登：\n"
        "\n  方式 A — 本机 / SSH X11 / VNC (任一种 GUI 可达 chrome 窗口)：\n"
        "    1. 关掉当前 background chrome: kill $(pgrep -f 'remote-debugging-port=9222')\n"
        "    2. 跑 CHROME_MODE=headed bash scripts/start_chrome.sh (需 DISPLAY)\n"
        "    3. 在 chrome 窗口里 goto https://mail.google.com/ 手动登\n"
        "    4. 关掉 chrome, 重启回 headless: bash scripts/start_chrome.sh\n"
        "\n  方式 B — SSH headless 机器无 GUI:\n"
        "    本地 chrome 登好 Gmail 后, scp 你本地 ~/.config/google-chrome/Default/Cookies\n"
        "    到 server ~/.config/web-agent-chrome/Default/Cookies, 重启 chrome script\n"
        "\n  cookies 一次性持久化, 之后本 demo 直接用。\n"
    )


async def main() -> None:
    cdp_url = os.environ.get("WEB_AGENT_CDP_URL", "http://127.0.0.1:9222")
    logged_in, url_or_reason = await _check_logged_in(cdp_url)
    if not logged_in:
        print(f"\n[gmail_summary] 检测失败: {url_or_reason}")
        _print_login_help()
        sys.exit(2)

    print(f"\n[gmail_summary] Gmail 已登录 (url={url_or_reason})")
    goal = (
        "你已经登录 Gmail，当前在 https://mail.google.com/。"
        "在收件箱（Inbox）的 **Primary tab**（不要看 Promotions / Social / Updates 等其他 tab）"
        "中读取**最新 5 封邮件**的「发件人」（From）和「主题」（Subject），按时间从新到旧。"
        "**只读模式**：禁止点击任何邮件行 / archive / delete / mark-read 等任何写操作，"
        "只从邮件列表视图直接读取列表项的发件人和主题文本。"
        "如果列表行的发件人/主题文本被截断，仍写下能看到的部分即可，不要试图悬停或点击。"
        "拿到 5 封后立即用 done 返回 JSON 数组: "
        "'[{\"from\": \"...\", \"subject\": \"...\"}, ...]'（按时间从新到旧排列）"
    )
    result = await run_task(
        goal=goal,
        start_url="https://mail.google.com/",
        max_steps=15,
    )
    print("\n=== Gmail Inbox Summary ===")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
