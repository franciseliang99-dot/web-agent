"""W4-2 captcha 单测 + loop 集成测.

不真起 chrome / 不真调 LLM。覆盖:
- detect: 4 vendor 命中 + none + 异常吞掉
- wait_for_resolution: 清除返回 True / 超时返回 False
- loop 集成: pause-resume / 超时 / DISABLE env 跳过
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from web_agent.captcha import CaptchaInfo, detect, wait_for_resolution
from web_agent.llm.base import Action
from web_agent.loop import run_react_loop
from web_agent.perceiver import Mark


# ---------- 单测: detect ----------

class _ScriptedEvalPage:
    """page.evaluate 按调用次数依次返回预设值。"""

    def __init__(self, returns: list) -> None:
        self._returns = list(returns)
        self._i = 0
        self.calls = 0

    async def evaluate(self, js: str):
        self.calls += 1
        idx = min(self._i, len(self._returns) - 1)
        self._i += 1
        return self._returns[idx]


@pytest.mark.parametrize("vendor,sample", [
    ("cloudflare-turnstile",
     {"hit": True, "vendor": "cloudflare-turnstile", "url": "https://challenges.cloudflare.com/cdn-cgi/x"}),
    ("recaptcha",
     {"hit": True, "vendor": "recaptcha", "url": "https://www.google.com/recaptcha/api2/x"}),
    ("hcaptcha",
     {"hit": True, "vendor": "hcaptcha", "url": "https://hcaptcha.com/captcha/x"}),
    ("google-verify",
     {"hit": True, "vendor": "google-verify", "url": "https://example.com/login"}),
])
async def test_detect_each_vendor(vendor, sample):
    info = await detect(_ScriptedEvalPage([sample]))
    assert info is not None
    assert info.vendor == vendor
    assert info.url == sample["url"]


async def test_detect_no_captcha_returns_none():
    info = await detect(_ScriptedEvalPage([{"hit": False}]))
    assert info is None


async def test_detect_eval_exception_returns_none():
    """page.evaluate 抛异常 (如 page navigating) → detect 不该崩 loop。"""
    class _BoomPage:
        async def evaluate(self, js):
            raise RuntimeError("page is navigating")
    info = await detect(_BoomPage())
    assert info is None


async def test_detect_missing_evaluate_returns_none():
    """没有 evaluate 方法 (e.g. V0.7.0 FakePage) → AttributeError 被吞 → None。"""
    class _NoEvalPage:
        pass
    info = await detect(_NoEvalPage())
    assert info is None


# ---------- 单测: wait_for_resolution ----------

async def test_wait_for_resolution_clears_returns_true():
    page = _ScriptedEvalPage([
        {"hit": True, "vendor": "hcaptcha", "url": "x"},
        {"hit": False},
    ])
    ok = await wait_for_resolution(page, timeout_s=2.0, poll_s=0.01)
    assert ok is True
    assert page.calls == 2


async def test_wait_for_resolution_timeout_returns_false():
    page = _ScriptedEvalPage([{"hit": True, "vendor": "recaptcha", "url": "y"}])
    ok = await wait_for_resolution(page, timeout_s=0.05, poll_s=0.02)
    assert ok is False
    assert page.calls >= 1


# ---------- 集成: loop × captcha ----------

class FakeLLMClient:
    """V0.7.0 inline 复用模式; N=2 仍按 YAGNI 不抽 conftest helper。"""

    name = "fake"
    model = "fake"

    def __init__(self, actions: list[Action]) -> None:
        self._actions = list(actions)
        self._i = 0

    async def plan(self, goal, screenshot_b64, marks, trace) -> Action:
        a = self._actions[min(self._i, len(self._actions) - 1)]
        self._i += 1
        return a


class FakePage:
    """最小 Page stub: loop.py 直接调到 wait_for_load_state / keyboard.press,
    captcha_detect/wait 由 monkeypatch 接管, 不会到 evaluate。"""

    class _Keyboard:
        async def press(self, key: str) -> None:
            return None

    keyboard = _Keyboard()

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        return None


_DUMMY_MARK = Mark(
    id=1, tag="button", role="", text="ok",
    bbox={"x": 0, "y": 0, "w": 80, "h": 30},
    input_type="", name="", href="",
)
_FAKE_SHOT_B64 = "aGVsbG8h"


async def _fake_perceive(page):
    return [_DUMMY_MARK], _FAKE_SHOT_B64


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def patch_loop_internals(monkeypatch):
    monkeypatch.setattr("web_agent.loop.perceive", _fake_perceive)
    monkeypatch.setattr("web_agent.loop.think", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_click", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_type", _noop)
    monkeypatch.setattr("web_agent.loop.scroll", _noop)


def _read_steps(db: Path) -> list[tuple[int, str, dict]]:
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT step, action_type, action_args FROM steps ORDER BY step"
    ).fetchall()
    conn.close()
    return [(r[0], r[1], json.loads(r[2])) for r in rows]


async def test_loop_pause_then_resume_after_captcha_cleared(
    monkeypatch, tmp_path, patch_loop_internals
):
    """场景: 第 1 步 captcha 命中 + wait 返回 True (用户解了) → 继续执行 LLM done step。"""
    monkeypatch.delenv("WEB_AGENT_CAPTCHA_DISABLE", raising=False)

    detect_calls = {"n": 0}

    async def fake_detect(page):
        detect_calls["n"] += 1
        if detect_calls["n"] == 1:
            return CaptchaInfo("cloudflare-turnstile", "https://x.test/")
        return None

    async def fake_wait(page, timeout_s, poll_s):
        return True

    monkeypatch.setattr("web_agent.loop.captcha_detect", fake_detect)
    monkeypatch.setattr("web_agent.loop.captcha_wait", fake_wait)

    client = FakeLLMClient([Action(type="done", args={"result": "ok"}, thought="完成")])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        FakePage(), client, goal="测试 captcha pause-resume",
        max_steps=3, db_path=db, screenshots_dir=shots,
    )

    assert result == "ok"
    types = [s[1] for s in _read_steps(db)]
    assert "captcha_timeout" not in types
    assert "done" in types


async def test_loop_captcha_timeout_writes_step_and_aborts(
    monkeypatch, tmp_path, patch_loop_internals
):
    """场景: detect 始终命中 + wait 返回 False (用户没解) → SAFETY 风格 graceful abort。"""
    monkeypatch.delenv("WEB_AGENT_CAPTCHA_DISABLE", raising=False)

    async def fake_detect(page):
        return CaptchaInfo("recaptcha", "https://y.test/")

    async def fake_wait(page, timeout_s, poll_s):
        return False

    monkeypatch.setattr("web_agent.loop.captcha_detect", fake_detect)
    monkeypatch.setattr("web_agent.loop.captcha_wait", fake_wait)

    client = FakeLLMClient([Action(type="done", args={"result": "won't reach"}, thought="x")])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        FakePage(), client, goal="测试 captcha timeout",
        max_steps=3, db_path=db, screenshots_dir=shots,
    )

    assert result.startswith("CAPTCHA_TIMEOUT at step 0"), result
    assert "recaptcha" in result

    steps = _read_steps(db)
    assert len(steps) == 1
    step_i, action_type, action_args = steps[0]
    assert step_i == 0
    assert action_type == "captcha_timeout"
    assert action_args["vendor"] == "recaptcha"
    assert action_args["url"] == "https://y.test/"


async def test_loop_disable_env_skips_captcha_check(
    monkeypatch, tmp_path, patch_loop_internals
):
    """场景: WEB_AGENT_CAPTCHA_DISABLE=true → captcha_detect 不该被调用; 即使页面有 captcha 也直接跳过。"""
    monkeypatch.setenv("WEB_AGENT_CAPTCHA_DISABLE", "true")

    detect_called = {"n": 0}

    async def fake_detect(page):
        detect_called["n"] += 1
        return CaptchaInfo("cloudflare-turnstile", "x")  # 即使返回命中, 也不该被调到

    monkeypatch.setattr("web_agent.loop.captcha_detect", fake_detect)

    client = FakeLLMClient([Action(type="done", args={"result": "skipped"}, thought="x")])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        FakePage(), client, goal="测试 disable",
        max_steps=2, db_path=db, screenshots_dir=shots,
    )

    assert result == "skipped"
    assert detect_called["n"] == 0
