"""V0.47.1 单元测 protection.py: ProtectionSignal dataclass + classify 纯函数 + listener attach.

不真起 chromium / Playwright; classify 是纯函数, listener attach 用 mock ctx 验装饰行为.
真 chromium 测留 V0.47.x.1 maintainer (10 真站 cassette + ANTHROPIC_API_KEY 红线).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from web_agent.protection import (
    ProtectionSignal,
    attach_protection_listener,
    classify,
)


# --- ProtectionSignal dataclass ---


def test_protection_signal_frozen_slots() -> None:
    """V0.47.1: ProtectionSignal frozen + slots (跟 Action/Mark/Usage 同 dataclass 模式)."""
    s = ProtectionSignal()
    with pytest.raises(AttributeError):
        s.server = "x"  # type: ignore[misc]


def test_protection_signal_defaults_unknown() -> None:
    """V0.47.1: 默认 all empty → classify unknown."""
    s = ProtectionSignal()
    assert s.status == 0
    assert s.server == ""
    assert s.cookies == frozenset()
    assert classify(s) == "unknown"


# --- classify 矩阵 ---


@pytest.mark.parametrize("signal,expected", [
    # unknown
    (ProtectionSignal(), "unknown"),
    # high: status 403/503
    (ProtectionSignal(status=403, server=""), "high"),
    (ProtectionSignal(status=503, server=""), "high"),
    # high: captcha vendor 命中 (跟 captcha.py JS probe 同 vendor)
    (ProtectionSignal(status=200, captcha_vendor="cloudflare-turnstile"), "high"),
    (ProtectionSignal(status=200, captcha_vendor="recaptcha"), "high"),
    (ProtectionSignal(status=200, captcha_vendor="hcaptcha"), "high"),
    # high: challenge-passed cookie (cf_clearance / datadome / __cfduid / incap_ses 等)
    (ProtectionSignal(status=200, cookies=frozenset({"cf_clearance"})), "high"),
    (ProtectionSignal(status=200, cookies=frozenset({"datadome"})), "high"),
    (ProtectionSignal(status=200, cookies=frozenset({"__cfduid"})), "high"),
    (ProtectionSignal(status=200, cookies=frozenset({"incap_ses_123"})), "high"),
    (ProtectionSignal(status=200, cookies=frozenset({"akamai_bot"})), "high"),
    # medium: 429 频率限制
    (ProtectionSignal(status=429), "medium"),
    # medium: 高防 server 但无 challenge cookie
    (ProtectionSignal(status=200, server="cloudflare"), "medium"),
    (ProtectionSignal(status=200, server="AkamaiGHost"), "medium"),
    (ProtectionSignal(status=200, server="datadome"), "medium"),
    (ProtectionSignal(status=200, server="incapsula"), "medium"),
    # low: 默认成功 + 无防护
    (ProtectionSignal(status=200, server=""), "low"),
    (ProtectionSignal(status=200, server="nginx"), "low"),  # 普通 web server 不在高防 set
    (ProtectionSignal(status=200, server="apache"), "low"),
    (ProtectionSignal(status=301, server=""), "low"),  # 3xx redirect 不算防护
])
def test_classify_matrix(signal: ProtectionSignal, expected: str) -> None:
    """V0.47.1: classify 各等级矩阵 (跟 CLAUDE.md 模型 vs 代码边界 — 字段已能回答, 不需 LLM)."""
    assert classify(signal) == expected, (
        f"V0.47.1 classify({signal!r}) = {classify(signal)!r}, 期望 {expected!r}"
    )


def test_classify_priority_high_over_medium() -> None:
    """V0.47.1: cookie/captcha/403 任一硬信号 + server 高防 → high (不降级 medium)."""
    s = ProtectionSignal(
        status=200, server="cloudflare",
        cookies=frozenset({"cf_clearance"}),
    )
    assert classify(s) == "high"


def test_classify_cookie_substring_match() -> None:
    """V0.47.1: 高防 cookie 用 prefix match (incap_ses_xxxxx 不只 incap_ses)."""
    s = ProtectionSignal(status=200, cookies=frozenset({"incap_ses_12345_abc"}))
    assert classify(s) == "high"


# --- attach_protection_listener ---


def test_attach_protection_listener_initializes_signals_container() -> None:
    """V0.47.1: listener attach 后 ctx._web_agent_protection_signals 初始化为 list."""
    ctx = MagicMock()
    # 模拟 BrowserContext 无 protection flag 初始状态
    ctx._web_agent_protection_listener = False
    ctx._web_agent_protection_signals = None

    attach_protection_listener(ctx)

    assert ctx._web_agent_protection_signals == []
    assert ctx._web_agent_protection_listener is True
    ctx.on.assert_called_once()  # 装 1 次 listener


def test_attach_protection_listener_idempotent() -> None:
    """V0.47.1: 同 ctx 调 2 次 attach, ctx.on 仅 1 次 (跟 _attach_popup_listener 同模式)."""
    ctx = MagicMock()
    ctx._web_agent_protection_listener = False
    ctx._web_agent_protection_signals = None

    attach_protection_listener(ctx)
    attach_protection_listener(ctx)  # 第 2 次 silent

    assert ctx.on.call_count == 1, (
        f"V0.47.1: 同 ctx 2 次 attach, ctx.on 应 1 次, 实际 {ctx.on.call_count}"
    )


def test_attach_protection_listener_preserves_existing_signals() -> None:
    """V0.47.1: 第一次 attach 后 signals 已有数据, 第 2 次 attach 不应清空 (重连场景)."""
    ctx = MagicMock()
    ctx._web_agent_protection_listener = False
    ctx._web_agent_protection_signals = [ProtectionSignal(status=200)]  # 假装已有 1 条

    attach_protection_listener(ctx)

    # idempotent 早 return, signals 不被改
    assert len(ctx._web_agent_protection_signals) == 1
