"""桌面 notification (W4-3): 在 captcha 命中 / 超时 等关键事件给用户系统级提醒。

V0.9.0 W4-2 命中只 print stdout, tmux/SSH/后台日志场景看不到;
本模块走 macOS osascript / Linux notify-send 桌面通知, 让用户即使离开终端也能感知。

设计:
- lazy 探测 + 模块缓存: 避 import 阶段 hit filesystem; 进程内只探一次
- 失败 silently swallow: notify 是辅助, 不该让 loop 因 dbus 缺失/权限拒绝挂掉
- env `WEB_AGENT_NOTIFY_DISABLE=true` 完全关 (CI / headless / 不想被打扰)
- 不可达平台 (Windows / 缺 backend) → no-op, 与 DISABLE 同效
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

log = logging.getLogger(__name__)

# 模块级缓存: (kind, binary_path|None); kind ∈ {"osascript","notify-send","none"}
_BACKEND_CACHE: tuple[str, str | None] | None = None


def _disabled() -> bool:
    return os.environ.get("WEB_AGENT_NOTIFY_DISABLE", "").lower() in ("true", "1", "yes")


def _resolve_backend() -> tuple[str, str | None]:
    """首次调用探测平台 + 二进制路径, 缓存到模块级。"""
    global _BACKEND_CACHE
    if _BACKEND_CACHE is not None:
        return _BACKEND_CACHE
    if sys.platform == "darwin":
        _BACKEND_CACHE = ("osascript", shutil.which("osascript"))
    elif sys.platform.startswith("linux"):
        _BACKEND_CACHE = ("notify-send", shutil.which("notify-send"))
    else:
        _BACKEND_CACHE = ("none", None)
    return _BACKEND_CACHE


def _reset_cache_for_tests() -> None:
    """test-only hook: 清缓存让下次 _resolve_backend 重新探测。"""
    global _BACKEND_CACHE
    _BACKEND_CACHE = None


def notify(title: str, message: str) -> None:
    """fire-and-forget 桌面通知; 失败/不可用静默无感, 不影响 caller。"""
    if _disabled():
        return
    kind, path = _resolve_backend()
    if path is None:
        return
    try:
        if kind == "osascript":
            # AppleScript: display notification "msg" with title "title"
            script = f"display notification {message!r} with title {title!r}"
            subprocess.run(
                [path, "-e", script], timeout=3, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif kind == "notify-send":
            subprocess.run(
                [path, title, message], timeout=3, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except (OSError, subprocess.SubprocessError):
        log.debug("notify failed", exc_info=True)  # silently swallow, 不污染 stdout
