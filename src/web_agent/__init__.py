"""web-agent: MultiOn-style 高度拟人 AI web agent."""

import os as _os

__version__ = "0.69.1"

# V0.63.0: opt-in 真 skip Playwright `document.fonts.ready` race. screenshotter.js:218 是唯一跳
# fonts wait 通道 — undocumented test env, 锁 playwright 版本风险, 故仅在用户显式 opt-in 时 set
# (V0.60.0 双 env opt-in 模式: 一级 user-facing → 二级 setdefault 给 driver 子进程).
if _os.environ.get("WEB_AGENT_SCREENSHOT_SKIP_FONTS", "").lower() in ("1", "true", "yes", "on"):
    _os.environ.setdefault("PW_TEST_SCREENSHOT_NO_FONTS_READY", "1")
