"""browser.py 单测 (audit gap 收尾): connect 空 contexts / 三元组返回 / apply_stealth 各 fallback。

不真起 Playwright; 用 AsyncMock + MagicMock + monkeypatch sys.modules 模拟 stealth lib。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from web_agent.browser import apply_stealth, connect


# ---------- connect ----------

async def test_connect_returns_browser_ctx_page_triple():
    fake_page = SimpleNamespace()
    fake_ctx = SimpleNamespace(pages=[fake_page])
    fake_browser = SimpleNamespace(contexts=[fake_ctx])

    fake_chromium = SimpleNamespace(connect_over_cdp=AsyncMock(return_value=fake_browser))
    p = SimpleNamespace(chromium=fake_chromium)

    browser, ctx, page = await connect(p, cdp_url="http://x:1")
    assert browser is fake_browser
    assert ctx is fake_ctx
    assert page is fake_page
    fake_chromium.connect_over_cdp.assert_called_once_with("http://x:1")


async def test_connect_empty_contexts_raises_runtime_error():
    """连上 CDP 但 chrome 没开任何窗口 → 友好报错。"""
    fake_browser = SimpleNamespace(contexts=[])
    p = SimpleNamespace(chromium=SimpleNamespace(
        connect_over_cdp=AsyncMock(return_value=fake_browser),
    ))
    with pytest.raises(RuntimeError, match="contexts 为空"):
        await connect(p, cdp_url="http://x:1")


async def test_connect_no_pages_creates_new_page():
    """ctx 存在但无 page → 调用 new_page 创建。"""
    new_page = SimpleNamespace(id="new")
    fake_ctx = SimpleNamespace(pages=[], new_page=AsyncMock(return_value=new_page))
    fake_browser = SimpleNamespace(contexts=[fake_ctx])
    p = SimpleNamespace(chromium=SimpleNamespace(
        connect_over_cdp=AsyncMock(return_value=fake_browser),
    ))
    _, _, page = await connect(p, cdp_url="http://x:1")
    assert page is new_page
    fake_ctx.new_page.assert_called_once()


# ---------- apply_stealth ----------

async def test_apply_stealth_uses_apply_stealth_async_when_available(monkeypatch):
    """playwright-stealth 2.x 主流 API: Stealth().apply_stealth_async(page)。"""
    apply_mock = AsyncMock()

    class _Stealth:
        apply_stealth_async = apply_mock  # 标记 hasattr 命中
        # 不定义 apply_async, 让分支只走第一个

    fake_module = SimpleNamespace(Stealth=lambda: _Stealth())
    monkeypatch.setitem(sys.modules, "playwright_stealth", fake_module)

    page = SimpleNamespace()
    await apply_stealth(page)
    apply_mock.assert_called_once_with(page)


async def test_apply_stealth_falls_back_to_apply_async(monkeypatch):
    """旧版 stealth 仅有 apply_async, 走 fallback 分支。"""
    apply_mock = AsyncMock()

    class _Stealth:
        # 显式没 apply_stealth_async, 只有 apply_async
        apply_async = apply_mock

    fake_module = SimpleNamespace(Stealth=lambda: _Stealth())
    monkeypatch.setitem(sys.modules, "playwright_stealth", fake_module)

    page = SimpleNamespace()
    await apply_stealth(page)
    apply_mock.assert_called_once_with(page)


async def test_apply_stealth_unmatched_api_prints_skip(monkeypatch, caplog):
    """两个 API 都没 → logger warning skip, 不抛。 (V0.16.0 print → logger 改造)"""
    import logging

    class _Stealth:
        pass  # 既无 apply_stealth_async 也无 apply_async

    fake_module = SimpleNamespace(Stealth=lambda: _Stealth())
    monkeypatch.setitem(sys.modules, "playwright_stealth", fake_module)

    page = SimpleNamespace()
    with caplog.at_level(logging.WARNING, logger="web_agent.browser"):
        await apply_stealth(page)
    assert "API 未匹配" in caplog.text


async def test_apply_stealth_import_error_swallowed(monkeypatch, caplog):
    """playwright-stealth 未装 → ImportError 吞掉, logger warning, 不抛。"""
    import logging

    monkeypatch.setitem(sys.modules, "playwright_stealth", None)  # None → ImportError on import

    page = SimpleNamespace()
    with caplog.at_level(logging.WARNING, logger="web_agent.browser"):
        await apply_stealth(page)
    assert "未安装" in caplog.text


async def test_apply_stealth_general_exception_swallowed(monkeypatch, caplog):
    """stealth 内部抛任何异常 → 吞掉, logger warning, 不阻塞主流程。"""
    import logging

    def boom():
        raise RuntimeError("stealth init bombed")

    fake_module = SimpleNamespace(Stealth=boom)
    monkeypatch.setitem(sys.modules, "playwright_stealth", fake_module)

    page = SimpleNamespace()
    with caplog.at_level(logging.WARNING, logger="web_agent.browser"):
        await apply_stealth(page)
    assert "stealth" in caplog.text.lower()
