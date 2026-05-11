"""V0.30.0 G stealth 加固单测: apply_stealth_plus init script 注入验.

mock 模式 (不真 launch chromium): MockPage.add_init_script 捕获 JS 字串 + assert 含关键 token.
sannysoft real probe (真验 stealth 生效) 留 V0.30.1 + slow opt-in test.

V0.30 plan subagent D 决: 加固 3 项 (webdriver hide / WebGL randomize / permissions consistency).
不加 audio noise / timezone / chrome.runtime spoof (V0.30 scope 太 wide, 留 V0.31+).
"""

from __future__ import annotations

import logging


class _MockPage:
    """V0.30.0 测 mock: 仅捕 add_init_script 字串, 不真 launch chromium."""

    def __init__(self) -> None:
        self.init_scripts: list[str] = []
        self._raise_on_add = False

    async def add_init_script(self, script: str) -> None:
        if self._raise_on_add:
            raise RuntimeError("mock chromium dead")
        self.init_scripts.append(script)


# ---------- apply_stealth_plus 注 init script ----------


async def test_apply_stealth_plus_injects_init_script():
    """V0.30.0: apply_stealth_plus 调 page.add_init_script 注入 1 个 JS string."""
    from web_agent.browser import apply_stealth_plus

    page = _MockPage()
    await apply_stealth_plus(page)  # type: ignore[arg-type]

    assert len(page.init_scripts) == 1


async def test_apply_stealth_plus_init_script_contains_webdriver_hide():
    """V0.30.0 G #1: init script 含 navigator.webdriver hide (defineProperty get undefined)."""
    from web_agent.browser import apply_stealth_plus

    page = _MockPage()
    await apply_stealth_plus(page)  # type: ignore[arg-type]

    js = page.init_scripts[0]
    assert "navigator" in js
    assert "webdriver" in js
    assert "undefined" in js
    assert "defineProperty" in js


async def test_apply_stealth_plus_init_script_contains_webgl_randomize():
    """V0.30.0 G #2: init script 含 WebGL vendor/renderer randomize (param 37445/37446 hook)."""
    from web_agent.browser import apply_stealth_plus

    page = _MockPage()
    await apply_stealth_plus(page)  # type: ignore[arg-type]

    js = page.init_scripts[0]
    assert "WebGLRenderingContext" in js
    assert "getParameter" in js
    assert "37445" in js  # UNMASKED_VENDOR_WEBGL
    assert "37446" in js  # UNMASKED_RENDERER_WEBGL
    assert "Intel" in js or "NVIDIA" in js or "AMD" in js  # vendor 池非空


async def test_apply_stealth_plus_init_script_contains_permissions_consistency():
    """V0.30.0 G #3: init script 含 navigator.permissions.query 一致性 (notifications)."""
    from web_agent.browser import apply_stealth_plus

    page = _MockPage()
    await apply_stealth_plus(page)  # type: ignore[arg-type]

    js = page.init_scripts[0]
    assert "permissions" in js
    assert "notifications" in js
    assert "Notification.permission" in js


async def test_apply_stealth_plus_graceful_when_add_init_script_raises(caplog):
    """V0.30.0: page.add_init_script raise → logger.warning + 不阻塞主流程 (跟 apply_stealth 同模式)."""
    from web_agent.browser import apply_stealth_plus

    page = _MockPage()
    page._raise_on_add = True

    with caplog.at_level(logging.WARNING):
        await apply_stealth_plus(page)  # type: ignore[arg-type]

    assert any("apply_stealth_plus" in r.message for r in caplog.records), (
        f"应 logger.warning, caplog: {[r.message for r in caplog.records]}"
    )


# ---------- 集成: cli.run_task 复合调用 (apply_stealth + apply_stealth_plus) ----------


def test_cli_imports_apply_stealth_plus():
    """V0.30.0: cli.py import apply_stealth_plus 跟 apply_stealth 复合使用."""
    import web_agent.cli as cli_mod
    assert hasattr(cli_mod, "apply_stealth_plus")
    assert hasattr(cli_mod, "apply_stealth")
