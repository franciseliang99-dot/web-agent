"""V0.23.1: real-browser smoke for human_like_drag + upload_file.

V0.23.1 sanity spike 已证 mouse.down/move/up 真触发 HTML5 dragstart (chromium + 当前 Playwright).
本 file 复刻 spike 的 dragstart 验证 + 加 file input upload 闭环.

@pytest.mark.slow + skipif WEB_AGENT_RUN_SLOW != "1" 双保险, 默认跳过.
本地手动跑: WEB_AGENT_RUN_SLOW=1 uv run pytest tests/test_loop_drag_upload.py -v
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


_DRAG_HTML = (
    "<html><body>"
    "<div id=src draggable=true style='width:80px;height:40px;background:#cfc;position:absolute;left:50px;top:50px'"
    " ondragstart='event.dataTransfer.setData(\"text/plain\",\"x\");window.__dstart=(window.__dstart||0)+1'"
    " data-som-id='1'>SRC</div>"
    "<div id=dst style='width:120px;height:80px;background:#ccf;position:absolute;left:300px;top:200px'"
    " ondragover='event.preventDefault()'"
    " ondrop='window.__drop=(window.__drop||0)+1;event.preventDefault()'"
    " data-som-id='2'>DST</div>"
    "</body></html>"
)
_DRAG_URL = "data:text/html," + urllib.parse.quote(_DRAG_HTML)

_UPLOAD_HTML = (
    "<html><body>"
    "<input type=file id=u data-som-id='1' style='width:200px'>"
    "</body></html>"
)
_UPLOAD_URL = "data:text/html," + urllib.parse.quote(_UPLOAD_HTML)

_UPLOAD_BUTTON_HTML = (
    "<html><body>"
    "<button id=btn data-som-id='1' aria-controls='hidden-input'>Upload</button>"
    "<input type=file id=hidden-input style='display:none'>"
    "</body></html>"
)
_UPLOAD_BUTTON_URL = "data:text/html," + urllib.parse.quote(_UPLOAD_BUTTON_HTML)


async def test_drag_real_chromium_triggers_dragstart_and_drop():
    """V0.23.1 闭环: human_like_drag 真触发 ondragstart + ondrop (Plan 风险 #1 spike 验证)."""
    from playwright.async_api import async_playwright
    from web_agent.actuator import human_like_drag
    from web_agent.types import Mark

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(_DRAG_URL)
            await page.wait_for_load_state("domcontentloaded")
            # 用 HTML 写死的 bbox 构 Mark (避免依赖 perceiver)
            from_m = Mark(
                id=1, tag="div", role="", text="SRC",
                bbox={"x": 50, "y": 50, "w": 80, "h": 40},
            )
            to_m = Mark(
                id=2, tag="div", role="", text="DST",
                bbox={"x": 300, "y": 200, "w": 120, "h": 80},
            )
            await human_like_drag(page, from_m, to_m)
            dstart = await page.evaluate("() => window.__dstart || 0")
            drop = await page.evaluate("() => window.__drop || 0")
            assert dstart >= 1, (
                f"V0.23.1 spike 闭环: ondragstart 必须真触发 (Plan 风险 #1 假设证伪); got {dstart}"
            )
            assert drop >= 1, f"ondrop 必须真触发 (拖放完成); got {drop}"
        finally:
            await browser.close()


async def test_upload_file_input_real_chromium_set_files(tmp_path):
    """V0.23.1: input[type=file] mark → set_input_files 真投递 (input.files.length==1)."""
    from playwright.async_api import async_playwright
    from web_agent.actuator import upload_file
    from web_agent.types import Mark

    fake = tmp_path / "fake.txt"
    fake.write_text("hello v0.23.1")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(_UPLOAD_URL)
            await page.wait_for_load_state("domcontentloaded")
            mark = Mark(
                id=1, tag="input", role="", text="",
                bbox={"x": 0, "y": 0, "w": 200, "h": 30},
                input_type="file",
            )
            await upload_file(page, mark, (str(fake),))
            count = await page.evaluate(
                "() => document.getElementById('u').files.length"
            )
            name = await page.evaluate(
                "() => document.getElementById('u').files[0].name"
            )
            assert count == 1, f"input.files 应有 1 个; got {count}"
            assert name == "fake.txt", f"文件名应是 fake.txt; got {name}"
        finally:
            await browser.close()


async def test_upload_button_dom_walk_real_chromium_finds_hidden_input(tmp_path):
    """V0.23.1: button mark + hidden file input → DOM walk 找到 input + 投递文件 (端到端).

    覆盖 SoM visibility filter 跳 hidden input 时 actuator 兜底走 DOM walk 的关键路径
    (Upwork 等 SPA 的标准模式).
    """
    from playwright.async_api import async_playwright
    from web_agent.actuator import upload_file
    from web_agent.types import Mark

    fake = tmp_path / "photo.jpg"
    fake.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(_UPLOAD_BUTTON_URL)
            await page.wait_for_load_state("domcontentloaded")
            mark = Mark(
                id=1, tag="button", role="", text="Upload",
                bbox={"x": 0, "y": 0, "w": 80, "h": 30},
            )
            await upload_file(page, mark, (str(fake),))
            count = await page.evaluate(
                "() => document.getElementById('hidden-input').files.length"
            )
            name = await page.evaluate(
                "() => document.getElementById('hidden-input').files[0].name"
            )
            assert count == 1, f"DOM walk 找到 hidden input 后投递; got count={count}"
            assert name == "photo.jpg"
        finally:
            await browser.close()
