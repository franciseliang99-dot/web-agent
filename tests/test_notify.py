"""W4-3 notify.py 单测: 平台探测 + subprocess 调用形态 + 失败 swallow."""

from __future__ import annotations

import subprocess

import pytest

from web_agent import notify as notify_mod
from web_agent.notify import notify


@pytest.fixture(autouse=True)
def reset_cache():
    """每个 case 前后清缓存, 防 sys.platform monkeypatch 被首次缓存固化。"""
    notify_mod._reset_cache_for_tests()
    yield
    notify_mod._reset_cache_for_tests()


class _Spy:
    """记录 subprocess.run 调用次数 + 参数, 不真起子进程。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, args, **kwargs):
        self.calls.append((tuple(args), kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0)


def test_disabled_env_short_circuits(monkeypatch):
    """WEB_AGENT_NOTIFY_DISABLE=true → subprocess 完全不被调用 (含平台探测)。"""
    monkeypatch.setenv("WEB_AGENT_NOTIFY_DISABLE", "true")
    spy = _Spy()
    monkeypatch.setattr("web_agent.notify.subprocess.run", spy)
    notify("t", "m")
    assert spy.calls == []


def test_macos_uses_osascript(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_NOTIFY_DISABLE", raising=False)
    monkeypatch.setattr("web_agent.notify.sys.platform", "darwin")
    monkeypatch.setattr("web_agent.notify.shutil.which",
                        lambda name: "/usr/bin/osascript" if name == "osascript" else None)
    spy = _Spy()
    monkeypatch.setattr("web_agent.notify.subprocess.run", spy)

    notify("captcha", "cloudflare hit")

    assert len(spy.calls) == 1
    args, kwargs = spy.calls[0]
    assert args[0] == "/usr/bin/osascript"
    assert args[1] == "-e"
    assert "display notification" in args[2]
    assert "cloudflare hit" in args[2]
    assert "captcha" in args[2]


def test_linux_uses_notify_send(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_NOTIFY_DISABLE", raising=False)
    monkeypatch.setattr("web_agent.notify.sys.platform", "linux")
    monkeypatch.setattr("web_agent.notify.shutil.which",
                        lambda name: "/usr/bin/notify-send" if name == "notify-send" else None)
    spy = _Spy()
    monkeypatch.setattr("web_agent.notify.subprocess.run", spy)

    notify("captcha", "recaptcha hit")

    assert len(spy.calls) == 1
    args, kwargs = spy.calls[0]
    assert args == ("/usr/bin/notify-send", "captcha", "recaptcha hit")
    assert kwargs.get("timeout") == 3
    assert kwargs.get("check") is False


def test_unknown_platform_noop(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_NOTIFY_DISABLE", raising=False)
    monkeypatch.setattr("web_agent.notify.sys.platform", "win32")
    spy = _Spy()
    monkeypatch.setattr("web_agent.notify.subprocess.run", spy)

    notify("t", "m")

    assert spy.calls == []


def test_backend_binary_missing_noop(monkeypatch):
    """linux 但没装 notify-send → which 返 None → no-op。"""
    monkeypatch.delenv("WEB_AGENT_NOTIFY_DISABLE", raising=False)
    monkeypatch.setattr("web_agent.notify.sys.platform", "linux")
    monkeypatch.setattr("web_agent.notify.shutil.which", lambda name: None)
    spy = _Spy()
    monkeypatch.setattr("web_agent.notify.subprocess.run", spy)

    notify("t", "m")

    assert spy.calls == []


def test_subprocess_oserror_swallowed(monkeypatch):
    """subprocess.run 抛 OSError (e.g. 缺 dbus) → notify() 不传播。"""
    monkeypatch.delenv("WEB_AGENT_NOTIFY_DISABLE", raising=False)
    monkeypatch.setattr("web_agent.notify.sys.platform", "linux")
    monkeypatch.setattr("web_agent.notify.shutil.which", lambda name: "/usr/bin/notify-send")

    def boom(*args, **kwargs):
        raise OSError("dbus missing")

    monkeypatch.setattr("web_agent.notify.subprocess.run", boom)

    notify("t", "m")  # 不该 raise
