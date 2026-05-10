"""V0.25.0 smart retry 单测: _classify_failure + transient retry budget.

V0.21 plan #5 high-leverage move 第 1 commit. SDK 内置 max_retries=4 之上再加 step 级
retry — transient (RateLimit/InternalServer/timeout) 同 step 重 perceive+plan, fatal
立即 abort 维持 V0.20.x 兼容.
"""

from __future__ import annotations

import sqlite3

import pytest

from web_agent.loop import _classify_failure, _transient_retry_max, run_react_loop
from web_agent.types import Action, DoneAction
from web_agent.perceiver import Mark


# --- _classify_failure 纯函数 ---


class _FakeAPIError(Exception):
    """模拟 anthropic.APIError / openai.APIError (不真 import SDK)."""


class _FakeRateLimitError(Exception):
    pass


_FakeRateLimitError.__name__ = "RateLimitError"


class _FakeInternalServerError(Exception):
    pass


_FakeInternalServerError.__name__ = "InternalServerError"


class _FakeAPITimeoutError(Exception):
    pass


_FakeAPITimeoutError.__name__ = "APITimeoutError"


class _FakeAPIConnectionError(Exception):
    pass


_FakeAPIConnectionError.__name__ = "APIConnectionError"


class _FakeBadRequest(Exception):
    pass


_FakeBadRequest.__name__ = "BadRequestError"


class _FakeAuthError(Exception):
    pass


_FakeAuthError.__name__ = "AuthenticationError"


@pytest.mark.parametrize("exc_cls", [
    _FakeRateLimitError, _FakeInternalServerError,
    _FakeAPITimeoutError, _FakeAPIConnectionError,
])
def test_classify_transient_returns_transient(exc_cls):
    """V0.25.0: 4 类 transient SDK exception → 'transient'."""
    assert _classify_failure(exc_cls("x")) == "transient"


@pytest.mark.parametrize("exc_cls", [_FakeBadRequest, _FakeAuthError, RuntimeError, ValueError])
def test_classify_fatal_returns_fatal(exc_cls):
    """V0.25.0: BadRequest/Auth/RuntimeError/ValueError → 'fatal' (重试无意义)."""
    assert _classify_failure(exc_cls("x")) == "fatal"


def test_classify_http_status_429_is_transient():
    """V0.25.0: 跨第三方代理包装层 (OpenRouter/LiteLLM) 用 status_code 兜底."""
    e = RuntimeError("proxy wrapped 429")
    e.status_code = 429  # type: ignore[attr-defined]
    assert _classify_failure(e) == "transient"


def test_classify_http_status_503_is_transient():
    e = RuntimeError("upstream 503")
    e.status_code = 503  # type: ignore[attr-defined]
    assert _classify_failure(e) == "transient"


def test_classify_http_status_400_is_fatal():
    """V0.25.0: 400 BadRequest 不在 transient HTTP 集合 → fatal."""
    e = RuntimeError("400 bad")
    e.status_code = 400  # type: ignore[attr-defined]
    assert _classify_failure(e) == "fatal"


# --- _transient_retry_max env ---


def test_transient_retry_max_default(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_TRANSIENT_RETRY_MAX", raising=False)
    assert _transient_retry_max() == 3


def test_transient_retry_max_env_override(monkeypatch):
    monkeypatch.setenv("WEB_AGENT_TRANSIENT_RETRY_MAX", "7")
    assert _transient_retry_max() == 7


def test_transient_retry_max_zero_disables(monkeypatch):
    monkeypatch.setenv("WEB_AGENT_TRANSIENT_RETRY_MAX", "0")
    assert _transient_retry_max() == 0


def test_transient_retry_max_invalid_falls_back_to_3(monkeypatch):
    monkeypatch.setenv("WEB_AGENT_TRANSIENT_RETRY_MAX", "not-a-number")
    assert _transient_retry_max() == 3


# --- transient retry loop 集成 ---


_DUMMY_MARK = Mark(
    id=1, tag="button", role="", text="ok",
    bbox={"x": 0, "y": 0, "w": 80, "h": 30},
)
_FAKE_SHOT = "aGVsbG8h"


async def _fake_perceive(page):
    return [_DUMMY_MARK], _FAKE_SHOT, []


async def _noop(*args, **kwargs):
    return None


class _FakePage:
    class _Keyboard:
        async def press(self, key):
            return None

    keyboard = _Keyboard()
    url = "about:blank"

    async def wait_for_load_state(self, *args, **kwargs):
        return None

    async def title(self):
        return ""


class _FakeContext:
    def __init__(self):
        self.pages = [_FakePage()]
        self._handlers = {}

    def on(self, event, handler):
        self._handlers[event] = handler


@pytest.fixture
def patch_loop_internals(monkeypatch):
    monkeypatch.setattr("web_agent.loop.perceive", _fake_perceive)
    monkeypatch.setattr("web_agent.loop.think", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_click", _noop)


def _read_steps(db):
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT step, action_type, action_args FROM steps ORDER BY step"
    ).fetchall()
    conn.close()
    import json
    return [(r[0], r[1], json.loads(r[2])) for r in rows]


async def test_transient_retry_succeeds_after_one_failure(monkeypatch, tmp_path, patch_loop_internals):
    """V0.25.0: client.plan 抛 RateLimit 1 次后返 DoneAction → result='ok', trace.action_args 不
    含 transient_retries (因为成功 step 走 dispatch 路径不写 error step)."""
    monkeypatch.delenv("WEB_AGENT_TRANSIENT_RETRY_MAX", raising=False)

    class FlakyClient:
        name = "fake"
        model = "fake"

        def __init__(self):
            self.attempts = 0

        async def plan(self, *a, **kw) -> Action:
            self.attempts += 1
            if self.attempts == 1:
                raise _FakeRateLimitError("quota exceeded")
            return DoneAction(thought="ok", result="success-after-retry")

    client = FlakyClient()
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        _FakeContext(), client, goal="测 transient retry success",
        max_steps=2, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result == "success-after-retry"
    assert client.attempts == 2  # 1 fail + 1 success
    steps = _read_steps(db)
    # 成功 step 走 done 路径, 不写 error step
    assert any(s[1] == "done" for s in steps)
    assert not any(s[1] == "error" for s in steps)


async def test_transient_retry_budget_exhausted_aborts_with_classification(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.25.0: transient 抛 N+1 次 → budget 耗尽 abort, trace.action_args 含 classification + transient_retries."""
    monkeypatch.setenv("WEB_AGENT_TRANSIENT_RETRY_MAX", "2")  # 2 retry + 1 首发 = 3 attempts

    class AlwaysFlaky:
        name = "fake"
        model = "fake"
        attempts = 0

        async def plan(self, *a, **kw):
            type(self).attempts += 1
            raise _FakeRateLimitError("forever 429")

    db = tmp_path / "trace.db"
    result = await run_react_loop(
        _FakeContext(), AlwaysFlaky(), goal="测 budget exhausted",
        max_steps=2, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result.startswith("LLM_FAILED at step 0")
    assert "RateLimitError" in result
    assert AlwaysFlaky.attempts == 3  # budget 2 retry + 1 首发
    steps = _read_steps(db)
    error_step = next(s for s in steps if s[1] == "error")
    assert error_step[2]["classification"] == "transient"
    assert error_step[2]["transient_retries"] == 2


async def test_fatal_exception_aborts_immediately_no_retry(monkeypatch, tmp_path, patch_loop_internals):
    """V0.25.0: fatal exception (BadRequest/RuntimeError) → 立即 abort, transient_retries=0."""
    monkeypatch.delenv("WEB_AGENT_TRANSIENT_RETRY_MAX", raising=False)

    class FatalClient:
        name = "fake"
        model = "fake"
        attempts = 0

        async def plan(self, *a, **kw):
            type(self).attempts += 1
            raise _FakeBadRequest("invalid model name")

    db = tmp_path / "trace.db"
    result = await run_react_loop(
        _FakeContext(), FatalClient(), goal="测 fatal abort",
        max_steps=2, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result.startswith("LLM_FAILED at step 0")
    assert FatalClient.attempts == 1  # fatal 不重试
    steps = _read_steps(db)
    error_step = next(s for s in steps if s[1] == "error")
    assert error_step[2]["classification"] == "fatal"
    assert error_step[2]["transient_retries"] == 0


# --- V0.25.2 backtracking ---


class _GoBackPage(_FakePage):
    """V0.25.2: spy page.go_back 调用 (其他 method 复用 _FakePage)."""

    def __init__(self):
        super().__init__()
        self.go_back_calls = 0

    async def go_back(self):
        self.go_back_calls += 1


class _GoBackContext:
    def __init__(self):
        self.pages = [_GoBackPage()]
        self._handlers = {}

    def on(self, event, handler):
        self._handlers[event] = handler


async def test_anti_loop_first_trigger_calls_go_back_and_resets_state(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.25.2: 连续 3 次同 ClickAction → 第 1 次 trigger backtrack: go_back called once,
    failure_hints deque 含 "已回退", recent_actions cleared, 不 abort 进入下一 step."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    from web_agent.types import ClickAction

    class RepeatClient:
        name = "fake"
        model = "fake"
        attempts = 0

        async def plan(self, *a, **kw) -> Action:
            type(self).attempts += 1
            if type(self).attempts <= 4:  # 4 次同 click 触发 anti_loop trigger
                return ClickAction(thought="重复点", mark_id=1)
            return DoneAction(thought="done after backtrack", result="ok-after-backtrack")

    ctx = _GoBackContext()
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        ctx, RepeatClient(), goal="测 anti_loop backtrack",
        max_steps=10, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    page = ctx.pages[0]
    assert page.go_back_calls == 1, f"V0.25.2 第 1 次 trigger 应调 go_back 一次; got {page.go_back_calls}"
    assert getattr(ctx, "_web_agent_anti_loop_backtracked", False) is True
    # backtrack 后 LLM 返 done → result OK (不是 LOOP_DETECTED)
    assert result == "ok-after-backtrack", f"backtrack 后应继续; got {result}"
    steps = _read_steps(db)
    assert any(s[1] == "backtrack" for s in steps), f"应写 backtrack step; got {[s[1] for s in steps]}"


async def test_anti_loop_second_trigger_after_backtrack_aborts(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.25.2: backtrack 后再次 3 次同 action 卡死 → 不再回退, 走原 LOOP_DETECTED abort."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    from web_agent.types import ClickAction

    class ForeverRepeatClient:
        name = "fake"
        model = "fake"

        async def plan(self, *a, **kw) -> Action:
            return ClickAction(thought="一直点", mark_id=1)

    ctx = _GoBackContext()
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        ctx, ForeverRepeatClient(), goal="测 anti_loop second trigger",
        max_steps=15, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    page = ctx.pages[0]
    # 第 1 次 trigger backtrack go_back, 第 2 次 trigger abort 不再 go_back
    assert page.go_back_calls == 1, f"go_back 应只调 1 次 (第 2 次 trigger 不回退); got {page.go_back_calls}"
    assert "LOOP_DETECTED" in result
    assert "V0.25.2 backtrack 后第 2 次 trigger" in result, "abort msg 应注明 backtrack 已用过"


class _FailingGoBackPage(_FakePage):
    """V0.25.2: page.go_back 抛异常模拟 (无 history / 网络断)."""

    async def go_back(self):
        raise RuntimeError("no history to go back to")


async def test_go_back_failure_falls_through_to_abort(
    monkeypatch, tmp_path, patch_loop_internals
):
    """V0.25.2: page.go_back 抛 → log warning, 不 backtrack, 直接走原 LOOP_DETECTED abort."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    from web_agent.types import ClickAction

    class RepeatClient:
        name = "fake"
        model = "fake"

        async def plan(self, *a, **kw):
            return ClickAction(thought="x", mark_id=1)

    class _FailCtx:
        def __init__(self):
            self.pages = [_FailingGoBackPage()]
            self._handlers = {}

        def on(self, event, handler):
            self._handlers[event] = handler

    ctx = _FailCtx()
    db = tmp_path / "trace.db"
    result = await run_react_loop(
        ctx, RepeatClient(), goal="测 go_back 失败",
        max_steps=10, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert "LOOP_DETECTED" in result
    # backtrack flag 未设 (go_back 失败前置 reset 不执行)
    assert getattr(ctx, "_web_agent_anti_loop_backtracked", False) is False


async def test_env_disables_retry_acts_like_v0242(monkeypatch, tmp_path, patch_loop_internals):
    """V0.25.0: WEB_AGENT_TRANSIENT_RETRY_MAX=0 → 等同 V0.24.2 行为 (transient 也立即 abort)."""
    monkeypatch.setenv("WEB_AGENT_TRANSIENT_RETRY_MAX", "0")

    class FlakyClient:
        name = "fake"
        model = "fake"
        attempts = 0

        async def plan(self, *a, **kw):
            type(self).attempts += 1
            raise _FakeRateLimitError("would normally retry")

    db = tmp_path / "trace.db"
    result = await run_react_loop(
        _FakeContext(), FlakyClient(), goal="测 retry disabled",
        max_steps=2, db_path=db, screenshots_dir=tmp_path / "shots",
    )
    assert result.startswith("LLM_FAILED at step 0")
    assert FlakyClient.attempts == 1
