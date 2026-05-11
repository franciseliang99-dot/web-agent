"""V0.30.2 G stealth 真生效验 — sannysoft probe slow opt-in test.

双 env 守门 (subagent V0.30.2 plan D 决):
- WEB_AGENT_RUN_SLOW=1 (跟 V0.21+ chromium slow smoke 同模式)
- WEB_AGENT_STEALTH_PROBE=1 (V0.30.2 新, 防意外真访 sannysoft)

真访 https://bot.sannysoft.com → screenshot 存 data/stealth_probes/<UTC date>.png + size > 10KB.
不真断分数 (sannysoft 表非二元 + 探测器升级会 break test, V0.30 plan D 决), 仅 dump artifact 给
maintainer 肉眼 review V0.30.0 apply_stealth_plus 真生效.

sannysoft 不可达 → pytest.skip (subagent V0.30.1 隐藏风险 #3).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("WEB_AGENT_RUN_SLOW", "") != "1",
        reason="real chromium probe; opt-in via WEB_AGENT_RUN_SLOW=1",
    ),
    pytest.mark.skipif(
        os.environ.get("WEB_AGENT_STEALTH_PROBE", "") != "1",
        reason="sannysoft real-net probe; opt-in via WEB_AGENT_STEALTH_PROBE=1",
    ),
]


_PROBE_DIR = Path("data/stealth_probes")


async def test_stealth_probe_sannysoft_screenshot():
    """V0.30.2: 真 launch chromium → apply_stealth+plus → goto sannysoft → screenshot 存 dir.

    artifact 路径: data/stealth_probes/<UTC YYYYMMDD>.png (gitignored, 仅 maintainer review).
    sannysoft 不可达 → pytest.skip 不挂 CI / dev iteration.
    """
    from playwright.async_api import async_playwright

    from web_agent.browser import apply_stealth, apply_stealth_plus

    _PROBE_DIR.mkdir(parents=True, exist_ok=True)
    date_stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    screenshot_path = _PROBE_DIR / f"sannysoft_{date_stamp}.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await apply_stealth(page)
            await apply_stealth_plus(page)
            try:
                await page.goto("https://bot.sannysoft.com/", timeout=15000)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception as e:
                pytest.skip(f"sannysoft unreachable ({type(e).__name__}: {e})")
            await page.screenshot(path=str(screenshot_path), full_page=True)
        finally:
            await browser.close()

    # 不断分数 (sannysoft 探测器表分数非二元 + 升级会 break), 只断 size > 10KB 防空白页
    assert screenshot_path.exists(), f"screenshot 未存到 {screenshot_path}"
    size = screenshot_path.stat().st_size
    assert size > 10_000, (
        f"screenshot size {size} bytes < 10KB, 可能空白页或 sannysoft 返错; 检查 {screenshot_path}"
    )
