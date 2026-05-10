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


_DOWNLOAD_HTML = (
    "<html><body>"
    "<a id=dl href=\"data:text/plain;base64,aGVsbG8gdjAuMjMuMg==\" download=\"v0232.txt\">Download</a>"
    "</body></html>"
)
_DOWNLOAD_URL = "data:text/html," + urllib.parse.quote(_DOWNLOAD_HTML)


async def test_drag_emits_at_least_15_drag_frames_baseline(tmp_path):
    """V0.23.3 反爬回归保护: human_like_drag 真触发 drag 帧数 ≥15.

    V0.23.1 spike 实测 mouse path 18 帧 vs CDP locator.drag_to 1 帧 — 反爬侧拟人优势.
    本测守护后续重构不退化到 CDP 路径 (若有人改 actuator 走 frame.locator.drag_to 默认,
    drag 帧数会跌到 1 失反爬优势, 本测 ≥15 立即报警).

    阈值 15 留 ~17% 抖动 buffer (实测 18); 若未来 Playwright 升级把 mouse.move 调度优化
    导致帧数减少, 本测警报可定位 root cause (V0.23.1 CHANGELOG spike 行号).
    """
    from playwright.async_api import async_playwright
    from web_agent.actuator import human_like_drag
    from web_agent.types import Mark

    counter_html = (
        "<html><body>"
        "<div id=src draggable=true style='width:80px;height:40px;background:#cfc;"
        "position:absolute;left:50px;top:50px'"
        " ondragstart=\"event.dataTransfer.setData('text/plain','x');"
        "window.__drag_count = (window.__drag_count||0) + 1\""
        " ondrag=\"window.__drag_count = (window.__drag_count||0) + 1\">SRC</div>"
        "<div id=dst style='width:120px;height:80px;background:#ccf;"
        "position:absolute;left:300px;top:200px'"
        " ondragover=\"event.preventDefault()\""
        " ondrop=\"event.preventDefault()\">DST</div>"
        "</body></html>"
    )
    counter_url = "data:text/html," + urllib.parse.quote(counter_html)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(counter_url)
            await page.wait_for_load_state("domcontentloaded")
            from_m = Mark(
                id=1, tag="div", role="", text="SRC",
                bbox={"x": 50, "y": 50, "w": 80, "h": 40},
            )
            to_m = Mark(
                id=2, tag="div", role="", text="DST",
                bbox={"x": 300, "y": 200, "w": 120, "h": 80},
            )
            await human_like_drag(page, from_m, to_m)
            drag_count = await page.evaluate("() => window.__drag_count || 0")
            # 18 是 V0.23.1 spike 实测; 15 留 17% 抖动 buffer; CDP 路径只 1 帧
            assert drag_count >= 15, (
                f"V0.23.3 反爬回归: drag 帧数应 ≥15 (V0.23.1 spike 18 帧 baseline); "
                f"got {drag_count}. 若 ≤5 怀疑 actuator 退化到 CDP 路径 (frame.locator.drag_to)"
            )
        finally:
            await browser.close()


async def test_download_listener_real_chromium_saves_file(tmp_path, monkeypatch):
    """V0.23.2 端到端: connect 装 download listener + click <a download> 真触发 → 文件落 download_dir.

    用 task_id=test_v0232 + ctx attr 注入 download_dir = tmp_path/downloads/test_v0232.
    """
    import asyncio
    from playwright.async_api import async_playwright
    from web_agent.browser import _attach_download_listeners

    download_dir = tmp_path / "downloads" / "test_v0232"
    download_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(accept_downloads=True)
            _attach_download_listeners(ctx)
            ctx._web_agent_download_dir = download_dir
            page = await ctx.new_page()
            # _attach_download_listeners 已 attach 给 initial pages, new_page 走 ctx.on('page') 路径
            # ctx.on('page') 是 sync emit 但 _ctx_page_handler_with_download 是 async create_task
            # → 等一拍让 listener 装上
            await asyncio.sleep(0.1)
            await page.goto(_DOWNLOAD_URL)
            await page.wait_for_load_state("domcontentloaded")
            await page.click("#dl")
            # 等 download listener handler save_as 异步完成
            await asyncio.sleep(1.0)
            saved = download_dir / "v0232.txt"
            assert saved.exists(), f"download 应落 {saved}; got {list(download_dir.iterdir())}"
            assert saved.read_text() == "hello v0.23.2"
            recent = getattr(ctx, "_web_agent_recent_downloads", None)
            assert recent and any("v0232.txt" in line for line in recent), (
                f"obs deque 应含 download 元信息; got {recent}"
            )
        finally:
            await browser.close()


async def test_download_size_over_limit_is_deleted(tmp_path, monkeypatch):
    """V0.23.3: WEB_AGENT_MAX_DOWNLOAD_MB=0 → 任何 download 超限 → save 后 stat → unlink.

    覆盖 V0.23.2 _save_download_async 后置 size 检查 + 删除路径 (Playwright Download 无
    pre-check size API, 必须 save 完才知 byte 数).
    """
    import asyncio
    from playwright.async_api import async_playwright
    from web_agent.browser import _attach_download_listeners

    monkeypatch.setenv("WEB_AGENT_MAX_DOWNLOAD_MB", "0")
    download_dir = tmp_path / "downloads" / "test_v0233_size"
    download_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(accept_downloads=True)
            _attach_download_listeners(ctx)
            ctx._web_agent_download_dir = download_dir
            page = await ctx.new_page()
            await asyncio.sleep(0.1)
            await page.goto(_DOWNLOAD_URL)
            await page.wait_for_load_state("domcontentloaded")
            await page.click("#dl")
            await asyncio.sleep(1.0)
            saved = download_dir / "v0232.txt"
            # 超限被删 → 文件不应存在
            assert not saved.exists(), (
                f"V0.23.3: WEB_AGENT_MAX_DOWNLOAD_MB=0 应删超限文件; got {saved} 仍存在"
            )
        finally:
            await browser.close()


async def test_download_collision_appends_n_suffix(tmp_path):
    """V0.23.3: 同 filename 多次 download → 加 _2/_3 后缀 (V0.23.2 _resolve_download_path).

    覆盖 V0.23.2 _resolve_download_path for-loop 2..1000 同名递增逻辑 (timestamp 不可读,
    _N 后缀人眼可读).
    """
    import asyncio
    from playwright.async_api import async_playwright
    from web_agent.browser import _attach_download_listeners

    download_dir = tmp_path / "downloads" / "test_v0233_collision"
    download_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(accept_downloads=True)
            _attach_download_listeners(ctx)
            ctx._web_agent_download_dir = download_dir
            page = await ctx.new_page()
            await asyncio.sleep(0.1)
            await page.goto(_DOWNLOAD_URL)
            await page.wait_for_load_state("domcontentloaded")
            # 两次 click 同 download URL → v0232.txt + v0232_2.txt
            await page.click("#dl")
            await asyncio.sleep(0.6)
            await page.click("#dl")
            await asyncio.sleep(1.0)
            first = download_dir / "v0232.txt"
            second = download_dir / "v0232_2.txt"
            assert first.exists(), f"第 1 次 download 应落 {first.name}; got {list(download_dir.iterdir())}"
            assert second.exists(), (
                f"V0.23.3: 第 2 次 download 同 filename 应加 _2 后缀; got "
                f"{list(download_dir.iterdir())}"
            )
        finally:
            await browser.close()


# --- V0.24.0 dialog auto-handle 真 chromium ---


_DIALOG_HTML_TEMPLATE = (
    "<html><body>"
    "<button id=trigger onclick=\"{js}\">click</button>"
    "</body></html>"
)


def _dialog_url(js: str) -> str:
    return "data:text/html," + urllib.parse.quote(_DIALOG_HTML_TEMPLATE.format(js=js))


async def test_dialog_alert_real_chromium_auto_dismissed(tmp_path):
    """V0.24.0: alert dialog 真触发 → handler accept (safe-defaults), page 不 hang."""
    import asyncio
    from playwright.async_api import async_playwright
    from web_agent.browser import _attach_download_listeners

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            _attach_download_listeners(ctx)
            page = await ctx.new_page()
            await asyncio.sleep(0.1)
            await page.goto(_dialog_url("alert('hello-v0240')"))
            await page.wait_for_load_state("domcontentloaded")
            await page.click("#trigger")
            await asyncio.sleep(0.3)  # 等 listener accept 调度完
            recent = getattr(ctx, "_web_agent_recent_dialogs", None)
            assert recent and any("alert" in line and "hello-v0240" in line for line in recent), (
                f"alert 应被 listener 捕获 + obs append; got {recent}"
            )
            # page 不 hang: 后续 evaluate 应正常返
            assert await page.evaluate("() => 1 + 1") == 2
        finally:
            await browser.close()


async def test_dialog_confirm_safe_default_dismiss_returns_false(tmp_path, monkeypatch):
    """V0.24.0: confirm dialog (safe-defaults) → dismiss → JS 收到 false (failsafe NO 防误删)."""
    import asyncio
    from playwright.async_api import async_playwright
    from web_agent.browser import _attach_download_listeners
    monkeypatch.delenv("WEB_AGENT_DIALOG_POLICY", raising=False)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            _attach_download_listeners(ctx)
            page = await ctx.new_page()
            await asyncio.sleep(0.1)
            await page.goto(_dialog_url("window.__r = confirm('确定删除?')"))
            await page.wait_for_load_state("domcontentloaded")
            await page.click("#trigger")
            await asyncio.sleep(0.3)
            r = await page.evaluate("() => window.__r")
            assert r is False, f"safe-defaults confirm 应 dismiss → JS false; got {r}"
            recent = getattr(ctx, "_web_agent_recent_dialogs", None)
            assert recent and any("confirm" in line and "auto-dismissed" in line for line in recent)
        finally:
            await browser.close()


async def test_dialog_confirm_auto_accept_returns_true(tmp_path, monkeypatch):
    """V0.24.0: WEB_AGENT_DIALOG_POLICY=auto-accept → confirm accept → JS 收到 true."""
    import asyncio
    from playwright.async_api import async_playwright
    from web_agent.browser import _attach_download_listeners
    monkeypatch.setenv("WEB_AGENT_DIALOG_POLICY", "auto-accept")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            _attach_download_listeners(ctx)
            page = await ctx.new_page()
            await asyncio.sleep(0.1)
            await page.goto(_dialog_url("window.__r = confirm('proceed?')"))
            await page.wait_for_load_state("domcontentloaded")
            await page.click("#trigger")
            await asyncio.sleep(0.3)
            r = await page.evaluate("() => window.__r")
            assert r is True, f"auto-accept confirm → JS true; got {r}"
        finally:
            await browser.close()


async def test_dialog_prompt_safe_default_dismiss_returns_null(tmp_path, monkeypatch):
    """V0.24.0: prompt dialog (safe-defaults) → dismiss → JS 收到 null (LLM 不会响应 prompt)."""
    import asyncio
    from playwright.async_api import async_playwright
    from web_agent.browser import _attach_download_listeners
    monkeypatch.delenv("WEB_AGENT_DIALOG_POLICY", raising=False)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            _attach_download_listeners(ctx)
            page = await ctx.new_page()
            await asyncio.sleep(0.1)
            await page.goto(_dialog_url("window.__r = prompt('your name?')"))
            await page.wait_for_load_state("domcontentloaded")
            await page.click("#trigger")
            await asyncio.sleep(0.3)
            r = await page.evaluate("() => window.__r")
            assert r is None, f"safe-defaults prompt 应 dismiss → JS null; got {r}"
            recent = getattr(ctx, "_web_agent_recent_dialogs", None)
            assert recent and any("prompt" in line for line in recent)
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
