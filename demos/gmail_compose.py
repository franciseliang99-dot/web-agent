"""W3-C demo: Gmail Compose → 填 To/Subject/Body → 试点 Send (验证 safety abort + auto_approve 路径)。

⚠ **默认行为**: safety.py 拦 "Send" 按钮 → run_task 返回字符串以 "SAFETY_BLOCK at step ..." 开头,
   含 "rule=send-or-pay" — 这就是「拦截路径正常工作」的证据。
⚠ **真发邮件**: `export WEB_AGENT_AUTO_APPROVE=send-or-pay` 会真把测试邮件发到
   `WEB_AGENT_TEST_RECIPIENT`。**强烈建议自己发给自己**,不要拿别人邮箱当测试目标。

前置:
  1. 同 demos/gmail_summary.py 顶部「方式 A / 方式 B」: 在 user-data-dir 里登 Gmail (一次性)
  2. export WEB_AGENT_TEST_RECIPIENT=youraddr@example.com (空则 fail-fast)

用法:
  bash scripts/start_chrome.sh                                            # 终端 A
  export WEB_AGENT_TEST_RECIPIENT=me@example.com                          # 终端 B
  uv run python demos/gmail_compose.py                                    # 默认 safety 拦
  WEB_AGENT_AUTO_APPROVE=send-or-pay uv run python demos/gmail_compose.py # 真发
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

from playwright.async_api import async_playwright

from web_agent.browser import connect
from web_agent.cli import run_task


async def _check_logged_in(cdp_url: str) -> tuple[bool, str]:
    """前置检测: goto Gmail 看是否跳到登录/不支持页。返回 (logged_in, url_or_reason)。"""
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
        "\n⚠ Gmail 未登录(或被反 bot 拦)。请按 demos/gmail_summary.py 顶部的方式 A/B 登一次,\n"
        "  cookies 持久化到 user-data-dir 后, 本 demo 直接复用。\n"
    )


async def main() -> None:
    cdp_url = os.environ.get("WEB_AGENT_CDP_URL", "http://127.0.0.1:9222")
    recipient = os.environ.get("WEB_AGENT_TEST_RECIPIENT", "").strip()
    if not recipient:
        print(
            "\n⚠ 必须 export WEB_AGENT_TEST_RECIPIENT=<youraddr@example.com> 才能跑 W3-C。\n"
            "  建议发给自己, 不要拿别人邮箱当测试目标。\n"
        )
        sys.exit(2)

    logged_in, url_or_reason = await _check_logged_in(cdp_url)
    if not logged_in:
        print(f"\n[gmail_compose] 检测失败: {url_or_reason}")
        _print_login_help()
        sys.exit(2)

    print(f"\n[gmail_compose] Gmail 已登录 (url={url_or_reason}); 收件人={recipient}")
    auto_approve = os.environ.get("WEB_AGENT_AUTO_APPROVE", "")
    if "send-or-pay" in auto_approve or "*" in auto_approve:
        print("⚠ WEB_AGENT_AUTO_APPROVE 含 send-or-pay/*; 这次会真发邮件。")
    else:
        print("ℹ 默认 safety abort 模式; 真发: export WEB_AGENT_AUTO_APPROVE=send-or-pay")

    timestamp = datetime.now().isoformat(timespec="seconds")
    subject = f"web-agent W3-C test {timestamp}"
    body = (
        "This is an automated test message from web-agent W3-C demo. "
        "Purpose: verify safety.py send-or-pay rule + Compose path 端到端工作。 "
        f"Timestamp: {timestamp}"
    )
    goal = (
        "你已登录 Gmail, 当前在 https://mail.google.com/。\n"
        "任务: 撰写并发送一封测试邮件。具体步骤:\n"
        "  1. 点击 Compose/撰写 按钮 (通常左上角的圆角矩形按钮)\n"
        f"  2. 在 To/收件人 字段填: {recipient}\n"
        f"  3. 在 Subject/主题 字段填: {subject}\n"
        f"  4. 在正文区填: {body}\n"
        "  5. 点击 Send/发送 按钮提交\n"
        "Send 成功后 (撰写窗口关闭 / 显示「Message sent」) 用 done 工具返回 'sent'。\n"
        "不要点 Discard/Save Draft/取消 等其他按钮; 目标就是走 Send 路径。"
    )
    result = await run_task(
        goal=goal,
        start_url="https://mail.google.com/",
        max_steps=12,
    )
    print("\n=== Gmail Compose Result ===")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
