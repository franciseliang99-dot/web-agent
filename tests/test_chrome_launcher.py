"""V0.16.19 chrome_launcher: 9222 健康检查 + auto-spawn 测试 (8 case)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from web_agent.chrome_launcher import (
    check_chrome_alive,
    ensure_chrome_running,
    spawn_chrome_detached,
)


# ===== check_chrome_alive =====


def test_check_chrome_alive_true_when_9222_responds(monkeypatch):
    """urlopen 正常返回 → True."""
    monkeypatch.setattr(
        "web_agent.chrome_launcher.urllib.request.urlopen",
        lambda url, timeout=2.0: MagicMock(__enter__=lambda s: s, __exit__=lambda *a: None),
    )
    assert check_chrome_alive("http://127.0.0.1:9222") is True


def test_check_chrome_alive_false_when_unreachable(monkeypatch):
    """urlopen raise URLError → False (不抛)."""
    import urllib.error

    def raise_url_error(url, timeout=2.0):
        raise urllib.error.URLError("ECONNREFUSED")

    monkeypatch.setattr("web_agent.chrome_launcher.urllib.request.urlopen", raise_url_error)
    assert check_chrome_alive("http://127.0.0.1:9222") is False


# ===== spawn_chrome_detached =====


def test_spawn_chrome_calls_popen_with_detached_args(monkeypatch, tmp_path):
    """验 Popen 用 start_new_session=True + DEVNULL stdin/stdout/stderr."""
    script = tmp_path / "scripts" / "start_chrome.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/bash\nexit 0\n")

    fake_proc = MagicMock(pid=12345)
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return fake_proc

    monkeypatch.setattr("web_agent.chrome_launcher.subprocess.Popen", fake_popen)
    monkeypatch.setattr("web_agent.chrome_launcher.check_chrome_alive", lambda url, timeout=1.0: True)

    pid = spawn_chrome_detached(script, "http://127.0.0.1:9222")

    assert pid == 12345
    assert captured["args"] == ["bash", str(script)]
    assert captured["kwargs"]["start_new_session"] is True
    import subprocess as sp

    assert captured["kwargs"]["stdin"] == sp.DEVNULL
    assert captured["kwargs"]["stdout"] == sp.DEVNULL
    assert captured["kwargs"]["stderr"] == sp.DEVNULL
    assert captured["kwargs"]["close_fds"] is True


def test_spawn_waits_for_9222_then_returns(monkeypatch, tmp_path):
    """前 2 次 alive=False, 第 3 次 True → 不抛, poll 起作用."""
    script = tmp_path / "scripts" / "start_chrome.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/bash\nexit 0\n")

    monkeypatch.setattr("web_agent.chrome_launcher.subprocess.Popen", lambda *a, **k: MagicMock(pid=999))
    monkeypatch.setattr("web_agent.chrome_launcher.time.sleep", lambda s: None)

    calls = {"n": 0}

    def fake_alive(url, timeout=1.0):
        calls["n"] += 1
        return calls["n"] >= 3

    monkeypatch.setattr("web_agent.chrome_launcher.check_chrome_alive", fake_alive)

    pid = spawn_chrome_detached(script, "http://127.0.0.1:9222", ready_timeout=10.0, poll_interval=0.01)
    assert pid == 999
    assert calls["n"] >= 3


def test_spawn_timeout_raises_with_cookbook_msg(monkeypatch, tmp_path):
    """check_chrome_alive 永 False → RuntimeError 含 'scripts/start_chrome.sh'."""
    script = tmp_path / "scripts" / "start_chrome.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/bash\nexit 0\n")

    monkeypatch.setattr("web_agent.chrome_launcher.subprocess.Popen", lambda *a, **k: MagicMock(pid=42))
    monkeypatch.setattr("web_agent.chrome_launcher.time.sleep", lambda s: None)
    # monotonic 让 deadline 立即过期
    fake_time = iter([0.0, 0.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr("web_agent.chrome_launcher.time.monotonic", lambda: next(fake_time))
    monkeypatch.setattr("web_agent.chrome_launcher.check_chrome_alive", lambda url, timeout=1.0: False)

    with pytest.raises(RuntimeError, match="start_chrome.sh"):
        spawn_chrome_detached(script, "http://127.0.0.1:9222", ready_timeout=0.001)


def test_spawn_missing_script_raises(monkeypatch, tmp_path):
    """script_path 不存在 → 直接抛, 不调 Popen."""
    fake_popen = MagicMock()
    monkeypatch.setattr("web_agent.chrome_launcher.subprocess.Popen", fake_popen)

    with pytest.raises(RuntimeError, match="script 不存在"):
        spawn_chrome_detached(tmp_path / "nonexistent.sh", "http://127.0.0.1:9222")
    fake_popen.assert_not_called()


# ===== ensure_chrome_running =====


def test_ensure_skips_spawn_when_chrome_alive(monkeypatch):
    """alive=True → Popen / spawn_chrome_detached 不被调."""
    monkeypatch.setattr("web_agent.chrome_launcher.check_chrome_alive", lambda url, timeout=2.0: True)
    fake_spawn = MagicMock()
    monkeypatch.setattr("web_agent.chrome_launcher.spawn_chrome_detached", fake_spawn)

    ensure_chrome_running("http://127.0.0.1:9222")
    fake_spawn.assert_not_called()


def test_ensure_skips_spawn_when_auto_spawn_false(monkeypatch):
    """env=false + dead → 抛 RuntimeError, spawn 未被调 (V0.16.18 行为)."""
    monkeypatch.setattr("web_agent.chrome_launcher.check_chrome_alive", lambda url, timeout=2.0: False)
    monkeypatch.setenv("WEB_AGENT_AUTO_SPAWN_CHROME", "false")
    fake_spawn = MagicMock()
    monkeypatch.setattr("web_agent.chrome_launcher.spawn_chrome_detached", fake_spawn)

    with pytest.raises(RuntimeError, match="chrome_not_running"):
        ensure_chrome_running("http://127.0.0.1:9222")
    fake_spawn.assert_not_called()


def test_ensure_spawns_when_auto_spawn_default_and_dead(monkeypatch):
    """env unset + dead → spawn 调 1 次."""
    monkeypatch.setattr("web_agent.chrome_launcher.check_chrome_alive", lambda url, timeout=2.0: False)
    monkeypatch.delenv("WEB_AGENT_AUTO_SPAWN_CHROME", raising=False)
    fake_spawn = MagicMock(return_value=12345)
    monkeypatch.setattr("web_agent.chrome_launcher.spawn_chrome_detached", fake_spawn)

    ensure_chrome_running("http://127.0.0.1:9222")
    fake_spawn.assert_called_once()


def test_ensure_uses_default_script_path(monkeypatch):
    """script_path=None → 默认指向项目 root/scripts/start_chrome.sh."""
    monkeypatch.setattr("web_agent.chrome_launcher.check_chrome_alive", lambda url, timeout=2.0: False)
    captured = {}

    def fake_spawn(script_path, cdp_url, **kw):
        captured["script_path"] = script_path
        return 999

    monkeypatch.setattr("web_agent.chrome_launcher.spawn_chrome_detached", fake_spawn)
    ensure_chrome_running("http://127.0.0.1:9222")

    assert captured["script_path"].name == "start_chrome.sh"
    assert captured["script_path"].parent.name == "scripts"
