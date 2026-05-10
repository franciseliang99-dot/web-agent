"""V0.22.1: real-browser smoke for perceive() iframe DFS.

不接 9222 (隔离 chromium.launch headless), 验证 srcdoc 同源 iframe 真注入 SoM 后 marks
全局 id 连续 + frame_path 正确编码.

@pytest.mark.slow + skipif WEB_AGENT_RUN_SLOW != "1" 双保险, 默认 CI / 本地 pytest 跳过.
本地手动跑: WEB_AGENT_RUN_SLOW=1 uv run pytest tests/test_loop_iframe.py -v
"""

from __future__ import annotations

import os
import urllib.parse

import pytest


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("WEB_AGENT_RUN_SLOW", "") != "1",
        reason="real chromium smoke; opt-in via WEB_AGENT_RUN_SLOW=1",
    ),
]


_SRCDOC_HTML = (
    "<html><body>"
    "<button id='main-btn'>main button</button>"
    "<iframe srcdoc='<html><body><button>inner button</button></body></html>'></iframe>"
    "</body></html>"
)
_PARENT_URL = "data:text/html," + urllib.parse.quote(_SRCDOC_HTML)


async def test_perceive_real_srcdoc_iframe_marks_have_frame_path():
    """真 chromium srcdoc iframe → perceive 应得主 button + iframe button (frame_path='0').

    id 全局连续 (主 frame 1 + iframe 2 或更多, 取决于 SoM 抓多少); 全 unique 无冲突.
    """
    from playwright.async_api import async_playwright
    from web_agent.perceiver import perceive

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await page.goto(_PARENT_URL)
            # iframe srcdoc attach 后 wait load
            await page.wait_for_load_state("networkidle", timeout=5000)
            marks, _ = await perceive(page)
            main_marks = [m for m in marks if m.frame_path == ""]
            iframe_marks = [m for m in marks if m.frame_path == "0"]
            assert any("main button" in m.text for m in main_marks), (
                f"主 frame button 必须被抓; got main={[m.text for m in main_marks]}"
            )
            assert any("inner button" in m.text for m in iframe_marks), (
                f"iframe 内 button 必须被抓 (V0.22.1 闭环); got iframe={[m.text for m in iframe_marks]}"
            )
            ids = [m.id for m in marks]
            assert ids == sorted(ids), f"id 应升序连续; got {ids}"
            assert len(set(ids)) == len(ids), f"id 必须全局 unique; got {ids}"
        finally:
            await browser.close()
