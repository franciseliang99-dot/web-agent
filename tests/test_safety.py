"""safety.py 纯函数单测：覆盖 click 黑名单 / type 敏感字段 / auto_approve env / 边界。"""

from __future__ import annotations

import pytest

from web_agent.types import (
    Action,
    ClickAction,
    DoneAction,
    ExtractAction,
    KeyboardShortcutAction,
    PasteAction,
    ScrollAction,
    TypeAction,
)
from web_agent.perceiver import Mark
from web_agent.safety import check


def _btn(text: str, **kw) -> Mark:
    return Mark(
        id=1, tag="button", role="", text=text,
        bbox={"x": 0, "y": 0, "w": 80, "h": 30},
        input_type=kw.get("input_type", ""),
        name=kw.get("name", ""),
        href=kw.get("href", ""),
    )


def _input(input_type: str = "text", name: str = "") -> Mark:
    return Mark(
        id=2, tag="input", role="", text="",
        bbox={"x": 0, "y": 0, "w": 200, "h": 30},
        input_type=input_type, name=name, href="",
    )


def _click(mark_id: int = 1) -> Action:
    return ClickAction(thought="x", mark_id=mark_id)


def _type(text: str = "hi") -> Action:
    return TypeAction(thought="x", text=text)


# --- V0.23.2 UploadAction sensitive path 黑名单 ---


@pytest.mark.parametrize("path,should_block", [
    ("~/.ssh/id_rsa", True),
    ("~/.ssh/known_hosts", True),
    ("~/.aws/credentials", True),
    ("~/.gnupg/secring.gpg", True),
    ("~/Downloads/photo.jpg", False),
    ("~/Documents/report.pdf", False),
    ("/tmp/vacation.png", False),
    ("/home/user/Desktop/data.xlsx", False),
    ("~/projects/repo/key.pem", True),
    ("~/work/aws-credentials.json", True),
    ("~/code/.env", True),
    ("~/code/.env.local", True),
    ("~/code/.env.production", True),
    ("~/notes/secret-recipe.txt", True),
    ("/etc/passwd", True),
    ("/etc/hosts", True),
    ("~/source/auth_token.json", True),
])
def test_upload_path_blacklist_block(monkeypatch, path, should_block):
    """V0.23.2: upload paths 黑名单 fnmatch glob 标准化匹配."""
    from web_agent.types import UploadAction
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    action = UploadAction(thought="x", mark_id=1, paths=(path,))
    decision = check(action, mark=None, marks=None)
    if should_block:
        assert not decision.allow, f"{path} 应被 block"
        assert decision.rule == "upload-sensitive-path"
    else:
        assert decision.allow, f"{path} 应放行 got reason={decision.reason}"


@pytest.mark.parametrize("url", [
    # V0.70.1 原 4 scheme
    "javascript:alert(document.cookie)",
    "JAVASCRIPT:void(0)",
    "vbscript:msgbox('xss')",
    "VBScript:Execute('...')",
    "data:text/html,<script>fetch('/api')</script>",
    "DATA:image/png;base64,iVBOR...",
    "file:///etc/passwd",
    "FILE:///home/user/.ssh/id_rsa",
    # V0.70.3 allowlist 新挡 N 种 scheme (V0.70.2-A 静态分析: agent flow 无合法 non-http 用例)
    "intent://scan/#Intent;scheme=zxing;end",  # Android deep link
    "tel:+15551234567",                         # OS phone app
    "mailto:victim@x.com",                      # OS mail app
    "sms:+15551234567",                         # OS SMS app
    "ws://malicious.example/ws",                # WebSocket 非 HTTP navigation
    "wss://malicious.example/ws",
    "ftp://files.example.com/",                 # Chrome 已废弃 ftp
    "magnet:?xt=urn:btih:abc",                  # BitTorrent
    "chrome://settings/",                       # Chromium 内部
    "chrome-extension://abc/page.html",
    "view-source:https://x.com/",               # 开发者工具
    "blob:https://example.com/uuid",            # SPA 内部临时 URL
    "about:config",                             # 浏览器配置
    "example.com/page",                         # 缺 scheme (LLM 常见漏 https://)
    "//cdn.example.com/lib.js",                 # protocol-relative
])
def test_goto_url_non_http_scheme_blocked(monkeypatch, url):
    """V0.70.3: allowlist 模式 — 仅 http://https:// 允许, 其余 N 种 scheme 全拒."""
    from web_agent.types import GotoUrlAction
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    action = GotoUrlAction(thought="x", url=url)
    decision = check(action, mark=None, marks=None)
    assert not decision.allow, f"{url!r} 应被 block"
    assert decision.rule == "goto-url-non-http-scheme"


@pytest.mark.parametrize("url", [
    "https://example.com/",
    "https://supabase.com/dashboard/x/auth/url-configuration",
    "http://localhost:8080/",
    "https://api.deepseek.com/v1",
])
def test_goto_url_https_allowed(monkeypatch, url):
    """V0.70.1: http/https URL 放行."""
    from web_agent.types import GotoUrlAction
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    action = GotoUrlAction(thought="x", url=url)
    decision = check(action, mark=None, marks=None)
    assert decision.allow, f"{url!r} 应放行 got reason={decision.reason}"


def test_goto_url_auto_approve_non_http_scheme(monkeypatch):
    """V0.70.3: WEB_AGENT_AUTO_APPROVE=goto-url-non-http-scheme → 放行 (dev escape hatch)."""
    from web_agent.types import GotoUrlAction
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "goto-url-non-http-scheme")
    action = GotoUrlAction(thought="x", url="javascript:void(0)")
    decision = check(action, mark=None, marks=None)
    assert decision.allow


def test_upload_multi_paths_one_match_blocks_all(monkeypatch):
    """V0.23.2: paths 多元素其一命中 → 整 action block (短路第一命中)."""
    from web_agent.types import UploadAction
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    action = UploadAction(thought="x", mark_id=1, paths=(
        "/tmp/safe.pdf", "~/.ssh/id_rsa", "/tmp/another.txt",
    ))
    decision = check(action, mark=None, marks=None)
    assert not decision.allow
    assert decision.rule == "upload-sensitive-path"


def test_upload_empty_paths_allowed(monkeypatch):
    """V0.23.2: 空 paths edge → safety allow (actuator/loop ERROR obs 兜底)."""
    from web_agent.types import UploadAction
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    action = UploadAction(thought="x", mark_id=1, paths=())
    decision = check(action, mark=None, marks=None)
    assert decision.allow


def test_upload_auto_approve_sensitive_path(monkeypatch):
    """V0.23.2: WEB_AGENT_AUTO_APPROVE=upload-sensitive-path 显式放行."""
    from web_agent.types import UploadAction
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "upload-sensitive-path")
    action = UploadAction(thought="x", mark_id=1, paths=("~/.ssh/id_rsa",))
    decision = check(action, mark=None, marks=None)
    assert decision.allow


def test_upload_auto_approve_wildcard(monkeypatch):
    """V0.23.2: WEB_AGENT_AUTO_APPROVE=* 通配符放行."""
    from web_agent.types import UploadAction
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "*")
    action = UploadAction(thought="x", mark_id=1, paths=("/etc/passwd",))
    decision = check(action, mark=None, marks=None)
    assert decision.allow


# --- click 按钮文本黑名单 ---

@pytest.mark.parametrize("text,should_block", [
    # V0.49.1: send standalone + Send Email 释 (amount co-signal 缺失 → 不拦)
    ("Send", False),
    ("Send Email", False),
    # V0.49.1 新: send 加 amount co-signal → 仍拦 (rule="send-amount")
    ("Send $50", True),
    ("Send 100 USD", True),
    ("Send Money $99", True),
    ("Pay Now", True),
    ("Delete", True),  # V0.49.1: rule 改为 'destructive-action' (rule 名验在 v044_regression)
    ("Confirm Payment", True),
    ("Place Order", True),
    ("Withdraw $500", True),  # V0.49.1: rule 'destructive-action'
    ("Subscribe", False),  # 订阅 ≠ unsubscribe
    ("Unsubscribe", True),
    ("Cancel Subscription", True),
    ("Search", False),
    ("Sender Name", False),  # word boundary 防 "sender" 误撞 "send"
    ("Login", False),
    # V0.45.1: 真发现 #24 fix — 'Submit' generic 动词不再 over-block
    ("Submit", False),
    ("Publish", False),
    ("Post", False),
])
def test_click_button_text_english(text, should_block, monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _btn(text), [])
    if should_block:
        assert not d.allow, f"{text!r} 应被拦"
        assert d.rule
    else:
        assert d.allow, f"{text!r} 不该被拦 (got rule={d.rule!r})"


@pytest.mark.parametrize("text,should_block", [
    # V0.49.1: 发送 standalone 释 (amount co-signal 缺失)
    ("发送", False),
    # V0.49.1 新: 发送 加 amount co-signal → 仍拦 (rule="zh-send-amount")
    ("发送 ¥50", True),
    ("发送 100 元", True),
    ("立即支付", True),
    ("删除", True),  # V0.49.1: rule 'zh-destructive-action'
    ("确认订单", True),
    ("转账", True),  # V0.49.1: rule 'zh-destructive-action'
    ("注销账号", True),
    ("搜索", False),
    ("登录", False),
    ("查看", False),
])
def test_click_button_text_chinese(text, should_block, monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _btn(text), [])
    assert d.allow != should_block, (
        f"{text!r}: expected blocked={should_block}, got rule={d.rule!r}"
    )


# --- click 敏感 input ---

def test_click_password_input_blocked(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _input(input_type="password"), [])
    assert not d.allow
    assert d.rule == "input-type-sensitive"


def test_click_tel_input_blocked(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _input(input_type="tel", name="otp"), [])
    assert not d.allow


def test_click_normal_text_input_allowed(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _input(input_type="text", name="search"), [])
    assert d.allow


def test_click_amount_named_input_blocked(monkeypatch):
    """input name 含 amount/cvv/card 等关键词应拦。"""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _input(input_type="text", name="amount"), [])
    assert not d.allow
    assert "name" in d.rule


# --- type 到敏感字段 ---

def test_type_into_password_blocked(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_type("secret"), _input(input_type="password"), [])
    assert not d.allow


def test_type_into_amount_input_blocked(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_type("100"), _input(input_type="text", name="amount"), [])
    assert not d.allow


def test_type_into_search_input_allowed(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_type("query"), _input(input_type="text", name="search"), [])
    assert d.allow


# --- auto_approve env ---

def test_auto_approve_single_rule(monkeypatch):
    """V0.49.1: 'Pay Now' 命中 send-or-pay rule, auto_approve env 放行."""
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "send-or-pay")
    d = check(_click(), _btn("Pay Now"), [])
    assert d.allow


def test_auto_approve_csv_multiple(monkeypatch):
    """V0.49.1: 多 rule 放行 (Pay Now / 立即支付 / password)."""
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "send-or-pay,zh-send-or-pay,input-type-sensitive")
    assert check(_click(), _btn("Pay Now"), []).allow
    assert check(_click(), _btn("立即支付"), []).allow
    assert check(_click(), _input(input_type="password"), []).allow


def test_auto_approve_wildcard(monkeypatch):
    monkeypatch.setenv("WEB_AGENT_AUTO_APPROVE", "*")
    assert check(_click(), _btn("Delete"), []).allow
    assert check(_click(), _btn("立即支付"), []).allow
    assert check(_click(), _input(input_type="password"), []).allow
    assert check(_type(), _input(input_type="password"), []).allow


def test_auto_approve_unset_blocks(monkeypatch):
    """V0.49.1: env 未设 → 命中 rule 的真支付动词仍拦 (用 Pay Now, Send standalone V0.49.1 已释)."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _btn("Pay Now"), [])
    assert not d.allow


# --- 边界 ---

def test_scroll_extract_done_always_allowed():
    # V0.17.0: dispatch 5 dataclass (此前 Action(type=atype, args={}, thought="x") 一律 fail)
    actions: list[Action] = [
        ScrollAction(thought="x", dy=0),
        ExtractAction(thought="x", query="", answer=""),
        DoneAction(thought="x", result=""),
    ]
    for a in actions:
        assert check(a, None, []).allow


def test_click_with_no_mark_allowed():
    """mark=None 不该崩（虽然实际 loop 不会传 None for click）。"""
    d = check(_click(), None, [])
    assert d.allow


def test_empty_text_button_allowed(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_click(), _btn(""), [])
    assert d.allow


def test_case_insensitive_match(monkeypatch):
    """V0.49.1: IGNORECASE flag 对真支付动词 (Pay) 大小写不敏感. Send standalone V0.49.1 已释, 改用 Pay."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    assert not check(_click(), _btn("PAY"), []).allow
    assert not check(_click(), _btn("pay"), []).allow
    assert not check(_click(), _btn("PaY"), []).allow


# --- V0.19.0: paste / keyboard_shortcut ---


def _paste(text: str = "hello") -> Action:
    return PasteAction(thought="x", text=text)


def _keyboard(key: str = "Control+End") -> Action:
    return KeyboardShortcutAction(thought="x", key=key)


def test_paste_into_password_blocked(monkeypatch):
    """V0.19.0: paste 到敏感 input_type 同 type 拦截."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_paste("secret"), _input(input_type="password"), [])
    assert not d.allow
    assert d.rule == "paste-into-sensitive-type"


def test_paste_into_amount_input_blocked(monkeypatch):
    """V0.19.0: paste 到敏感 name (amount/cvv/...) 同 type 拦截."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_paste("100"), _input(input_type="text", name="amount"), [])
    assert not d.allow
    assert d.rule == "paste-into-sensitive-name"


def test_paste_into_search_input_allowed(monkeypatch):
    """V0.19.0: 普通文本框 paste 放行."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    d = check(_paste("query"), _input(input_type="text", name="search"), [])
    assert d.allow


def test_keyboard_shortcut_always_allowed(monkeypatch):
    """V0.19.0: keyboard_shortcut 无明确 target text 映射, 一律放行 (无 useful safety signal).

    含 sensitive mark 时也不 block — Ctrl+End 在 password 输入框不构成额外风险.
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    assert check(_keyboard("Control+End"), None, []).allow
    assert check(_keyboard("Control+a"), _input(input_type="password"), []).allow
    assert check(_keyboard("Tab"), _btn("Send"), []).allow  # 即使 mark.text 命中 send-or-pay 也不拦
