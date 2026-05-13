"""V0.57.0 pilot #1: Monaco hidden textarea SoM walker exempt fix.

Pilot 真测 weak — "Monaco editor 焦点 (SoM 看不到隐藏 textarea)". V0.57.0 perceiver.py walker JS
加 .monaco-editor descendant exempt (skip zero-size + opacity filter), bbox override 用 parent
.monaco-editor outer rect.

Test scope:
- fast unit: _SOM_INJECT_JS 含 V0.57 关键 keyword (monacoParents WeakMap + monaco-editor closest)
- slow chromium real (RUN_SLOW gate): data URI 加载 Monaco minimal fixture HTML, 验 mark 真出现
"""

from __future__ import annotations

import os
from urllib.parse import quote

import pytest


def test_som_inject_js_contains_monaco_exempt_keywords() -> None:
    """V0.57.0 防回归: _SOM_INJECT_JS 含 Monaco exempt 关键路径 keyword."""
    from web_agent.perceiver import _SOM_INJECT_JS
    for keyword in (
        "monacoParents",      # WeakMap 追踪
        ".monaco-editor",     # CSS selector
        "monacoParent",       # closure 变量
    ):
        assert keyword in _SOM_INJECT_JS, (
            f"V0.57.0: _SOM_INJECT_JS 应含 {keyword!r} (Monaco exempt 路径)"
        )


def test_som_inject_js_monaco_exempt_skips_zero_size_filter() -> None:
    """V0.57.0: filter 应有 `!monacoParent && (r.width <= 1 || r.height <= 1)` pattern."""
    from web_agent.perceiver import _SOM_INJECT_JS
    # zero-size 检查仅在非 Monaco 时跑
    assert "!monacoParent && (r.width <= 1 || r.height <= 1)" in _SOM_INJECT_JS, (
        "V0.57.0: zero-size filter 应对 Monaco descendant exempt"
    )
    # opacity 检查同
    assert "!monacoParent && parseFloat(style.opacity)" in _SOM_INJECT_JS, (
        "V0.57.0: opacity filter 应对 Monaco descendant exempt"
    )


# --- chromium real test (RUN_SLOW gate, ~5s) ---


_MONACO_FIXTURE_HTML = """\
<!DOCTYPE html>
<html><head><title>Monaco minimal fixture</title></head>
<body>
  <h1>Monaco minimal fixture (V0.57.0 pilot #1)</h1>
  <div class="monaco-editor" style="width:400px;height:200px;position:relative;border:1px solid #ccc;">
    <textarea class="inputarea"
              style="position:absolute;top:0;left:0;width:1px;height:1px;opacity:0;"
              aria-label="Monaco editor input"></textarea>
    <canvas style="width:400px;height:200px;"></canvas>
  </div>
  <button id="control">Control Button (non-Monaco)</button>
</body></html>
"""


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("WEB_AGENT_RUN_SLOW", "") != "1",
    reason="real chromium probe; opt-in via WEB_AGENT_RUN_SLOW=1",
)
async def test_monaco_textarea_in_marks_via_walker_exempt() -> None:
    """V0.57.0 真测: chromium 真跑 walker JS on Monaco minimal fixture.

    Assert:
    1. Monaco textarea (1×1 opacity 0) 出现 marks (V0.57 exempt 生效, 旧 filter 不出现)
    2. Monaco textarea mark bbox != (1, 1) — bbox override 用 parent .monaco-editor outer rect
    3. control button (非 Monaco) 也出现 marks (V0.5.0 既有路径不破)
    """
    from playwright.async_api import async_playwright

    from web_agent.perceiver import _SOM_INJECT_JS

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            data_url = "data:text/html;charset=utf-8," + quote(_MONACO_FIXTURE_HTML)
            await page.goto(data_url, wait_until="load", timeout=10_000)
            marks: list[dict] = await page.evaluate(_SOM_INJECT_JS, {"shadow": True})
        finally:
            await browser.close()

    # 至少 2 mark: Monaco textarea + control button
    assert len(marks) >= 2, f"V0.57.0: 应 ≥ 2 marks (Monaco + control), got {len(marks)}: {marks}"

    # Monaco textarea (tag=textarea) 出现 marks (V0.57 exempt)
    textareas = [m for m in marks if m["tag"] == "textarea"]
    assert len(textareas) >= 1, (
        f"V0.57.0: Monaco textarea 应在 marks (exempt fix), got marks={marks}"
    )
    monaco_mark = textareas[0]

    # bbox override: 不是 1×1 (用 parent .monaco-editor 400×200 rect)
    assert monaco_mark["bbox"]["w"] > 100, (
        f"V0.57.0: Monaco mark bbox.w 应 = parent rect 宽 (~400, not textarea 1), "
        f"got {monaco_mark['bbox']}"
    )
    assert monaco_mark["bbox"]["h"] > 50, (
        f"V0.57.0: Monaco mark bbox.h 应 = parent rect 高 (~200, not textarea 1), "
        f"got {monaco_mark['bbox']}"
    )

    # Control button (非 Monaco) 仍出现
    buttons = [m for m in marks if m["tag"] == "button"]
    assert len(buttons) >= 1, f"V0.57.0 regression: control button 应在 marks, got {marks}"
