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
            marks, _, _ = await perceive(page)
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


_CLICK_HTML = (
    "<html><body>"
    "<iframe srcdoc=\""
    "<html><body>"
    "<button id='target' onclick='window.parent.__iframe_click_count = (window.parent.__iframe_click_count || 0) + 1'>click me</button>"
    "</body></html>"
    "\"></iframe>"
    "</body></html>"
)
_CLICK_PARENT_URL = "data:text/html," + urllib.parse.quote(_CLICK_HTML)


async def test_actuator_iframe_click_real_triggers_button():
    """V0.22.2 端到端: perceive 拿 iframe button mark → human_like_click(frame=...) → 真触发."""
    from playwright.async_api import async_playwright
    from web_agent.actuator import human_like_click
    from web_agent.loop import _resolve_frame
    from web_agent.perceiver import perceive

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await page.goto(_CLICK_PARENT_URL)
            await page.wait_for_load_state("networkidle", timeout=5000)
            marks, _, _ = await perceive(page)
            iframe_btn = next(
                (m for m in marks if m.frame_path == "0" and "click me" in m.text),
                None,
            )
            assert iframe_btn is not None, f"iframe button 必须被抓; got {[(m.text, m.frame_path) for m in marks]}"
            target_frame = _resolve_frame(page, iframe_btn.frame_path)
            assert target_frame is not None, "frame_path='0' 必须能 resolve"
            await human_like_click(page, iframe_btn, frame=target_frame)
            # 验 click 真触发: iframe button onclick 加 window.parent.__iframe_click_count
            count = await page.evaluate("() => window.__iframe_click_count || 0")
            assert count == 1, f"iframe button 必须被点 1 次 (V0.22.2 闭环); got count={count}"
        finally:
            await browser.close()
