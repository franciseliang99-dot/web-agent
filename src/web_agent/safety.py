"""授权白名单：在 actuator 之前 intercept 危险 action（W3-A）。

设计原则：
- safe by default — 默认拦 send/pay/delete/submit/transfer + 敏感字段 (password/tel/amount/cvv/...)
- 用户预授权 — `WEB_AGENT_AUTO_APPROVE=rule1,rule2,...` env 放行特定规则
- 全开 — `WEB_AGENT_AUTO_APPROVE=*` (dev 用，生产慎)
- 触发即 abort — loop 强制中止，不让 LLM 继续 retry/换策略（避免重撞）

依赖方向（按 CLAUDE.md 解耦）：domain (web_agent.types: Mark, Action) ← safety.py (本文件，纯函数) ← loop.py (业务层调用)

V0.16.9: 改从 `web_agent.types` import Mark/Action，消除 domain 反向依赖 port (llm.base) 和 业务层 (perceiver)。
V0.23.2: 加 UploadAction sensitive path 黑名单 (~/.ssh/ /.aws/ *.pem id_rsa* .env etc).
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path

from web_agent.types import Action, Mark, UploadAction


@dataclass
class SafetyDecision:
    allow: bool
    rule: str = ""  # 触发的规则名（用于 trace + auto_approve 反向放行）
    reason: str = ""  # 给用户看的友好阻拦理由


# (compiled_regex, rule_name) — 用 \b word boundary 避免 "sender" 误撞 "send"
# 模块加载时 compile 一次，后续 check() 调用零 compile/cache-lookup 开销
#
# V0.45.1: 删 generic 动词 submit|publish|post|order 修 #24 假阳性.
# V0.49.1 双修:
#   1. **拆 destructive-action**: delete/remove/withdraw/transfer/wire (中文 删除/提款/转账) 移出
#      send-or-pay 到新 rule. rule 名跟内涵对齐 (用户看 log 不再误以为支付拦实是 destructive).
#   2. **send amount co-signal**: 删 standalone send (中文 发送) from send-or-pay, 加新 rule
#      "send-amount" 仅在 amount 词 ($/¥/N USD/N 元) nearby 时拦. 释 'Send Email' / 'Send Message'
#      / 'Send Notification' 等 generic, 仍拦 'Send $50' / 'Send 100 USD' / '发送 ¥50'.
_DANGER_BUTTON_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 英文 send-or-pay (V0.49.1 收窄: 仅明确支付动词, 不含 destructive/send)
    (
        re.compile(
            r"\b(pay|paypal|checkout|"
            r"buy|purchase|place[ -]order|confirm[ -]?(payment|order)|authorize|"
            r"approve|agree[ -]and[ -]continue|accept[ -]and[ -]continue)\b",
            re.IGNORECASE,
        ),
        "send-or-pay",
    ),
    # V0.49.1 新: 英文 destructive-action (删除 / 转账 / 提款 / 电汇)
    (
        re.compile(
            r"\b(delete|remove|withdraw|transfer|wire)\b",
            re.IGNORECASE,
        ),
        "destructive-action",
    ),
    # V0.49.1 新: 英文 send-amount (send 仅在 amount 词 nearby 时拦)
    # 0-30 char 内含 $/¥/€/£ 或 N USD/CNY/EUR/GBP/元 (覆 "Send $50" / "Send 100 USD" / "Send Money $99")
    (
        re.compile(
            r"\bsend\b.{0,30}([\$¥€£]|\d+\s*(USD|CNY|EUR|GBP|元))",
            re.IGNORECASE,
        ),
        "send-amount",
    ),
    # 中文 zh-send-or-pay (V0.49.1 收窄: 删 发送/删除/提款/转账)
    (
        re.compile(
            r"(支付|付款|确认订单|下单|结算|授权|"
            r"同意.{0,3}继续|立即(支付|购买|提现|结算)|确认支付|确认下单)",
        ),
        "zh-send-or-pay",
    ),
    # V0.49.1 新: 中文 zh-destructive-action
    (
        re.compile(r"(删除|提款|转账)"),
        "zh-destructive-action",
    ),
    # V0.49.1 新: 中文 zh-send-amount (发送 在 0-30 char amount 词 nearby 时拦)
    (
        re.compile(r"发送.{0,30}([¥$€£]|\d+\s*(元|USD|CNY|EUR))"),
        "zh-send-amount",
    ),
    # 订阅取消 / 账号注销
    (
        re.compile(r"\b(unsubscribe|cancel[ -]subscription|deactivate[ -]account|close[ -]account)\b", re.IGNORECASE),
        "subscription-cancel",
    ),
    (re.compile(r"(取消订阅|注销账号|关闭账号|解除订阅)"), "zh-subscription-cancel"),
]

# input type 黑名单（聚焦 / 输入都拦）
_DANGER_INPUT_TYPES: set[str] = {"password", "tel"}  # tel 常见于 OTP / 银行卡

# input name/id 含敏感关键词
_DANGER_INPUT_NAME_RE = re.compile(
    r"\b(amount|cvv|card[- _]?(num|number)?|cc[- _]?num|account|otp|verif|code|pin|"
    r"ssn|tax[- _]?id|iban|swift|金额|银行卡|验证码|身份证|信用卡)\b",
    re.IGNORECASE,
)

# V0.23.2: UploadAction 路径黑名单 — fnmatch glob 模式, Path expanduser+resolve 标准化后匹配.
# symlink 跟到真实路径 (Path.resolve 默认 strict=False) 防 ~/safe/key.pem → ~/.ssh/id_rsa 绕过.
# 黑名单 (而非白名单) 因合法上传目录太散 (Downloads/Documents/Desktop/Projects/repo 内...),
# 敏感路径模式稳定 + 失败模式漏拦 (用户 elicit 兜底) > 白名单误拦体验差.
_DANGEROUS_UPLOAD_PATTERNS: list[str] = [
    "*/.ssh/*",         # SSH 私钥 / authorized_keys
    "*/.ssh",
    "*/.aws/*",         # AWS 凭证
    "*/.aws",
    "*/.gnupg/*",       # GPG 密钥
    "*/.gnupg",
    "*/.docker/config.json",  # Docker registry 凭证
    "*/.netrc",         # FTP/curl 凭证
    "*/Library/Keychains/*",  # macOS keychain
    "/etc/*",           # 系统配置 (含 shadow/passwd 等)
    "*.pem",            # 任意目录 PEM 私钥
    "*.key",            # 任意目录私钥
    "*id_rsa*",         # SSH 私钥常见命名 (含 id_rsa.pub)
    "*credentials*",    # 凭证文件常见命名
    "*.env",            # 环境变量含 secret
    "*.env.*",          # .env.local / .env.production etc
    "*token*",          # token 类文件
    "*secret*",         # secret 类文件
]


def _check_upload_paths(paths: tuple[str, ...]) -> SafetyDecision | None:
    """V0.23.2: UploadAction.paths 黑名单检查. 返 None 表全 paths 都过, SafetyDecision 表 block.

    Path expanduser+resolve 标准化跟 symlink (~/safe/key.pem → ~/.ssh/id_rsa 防绕过);
    任一 path 命中 _DANGEROUS_UPLOAD_PATTERNS 立即返 _block (不继续检查后续 path).
    """
    if not paths:
        return None  # 空 paths 由 actuator/loop ERROR obs 兜底, 不归 safety 管
    for p in paths:
        try:
            normalized = str(Path(p).expanduser().resolve())
        except (OSError, RuntimeError):
            normalized = p  # resolve 失败 (无效 path / 跨设备 symlink) → 用原串匹配
        for pattern in _DANGEROUS_UPLOAD_PATTERNS:
            if fnmatch.fnmatch(normalized, pattern):
                return _block(
                    "upload-sensitive-path",
                    f"safety: upload 命中敏感路径 (path={p!r} matches {pattern!r})。"
                    f"系统/凭证文件不可上传; 如确需放行, set "
                    f"WEB_AGENT_AUTO_APPROVE=upload-sensitive-path",
                )
    return None


def _auto_approved(rule: str) -> bool:
    """检查 WEB_AGENT_AUTO_APPROVE env 是否预授权了某个规则。`*` = 全开。"""
    env = os.environ.get("WEB_AGENT_AUTO_APPROVE", "").strip()
    if not env:
        return False
    items = {x.strip() for x in env.split(",") if x.strip()}
    return "*" in items or rule in items


def _block(rule: str, reason: str) -> SafetyDecision | None:
    """统一封装"未 auto_approve 则拦截"。命中规则但已预授权 → None (调用方 continue)。"""
    if _auto_approved(rule):
        return None
    return SafetyDecision(
        allow=False,
        rule=rule,
        reason=f"{reason} 预授权: WEB_AGENT_AUTO_APPROVE={rule} (或 *)",
    )


def check(action: Action, mark: Mark | None, marks: list[Mark] | None = None) -> SafetyDecision:
    """在 actuator 调用前调一次。allow=False → loop 必须 graceful abort。

    Args:
        action: LLM 返回的下一步行动
        mark: click 的目标元素 / type 的上次 click 元素；scroll/extract/done 时为 None
        marks: 当前所有 marks（保留给 form action 检测等未来扩展，本版未用）

    Returns:
        SafetyDecision.allow=True → 放行；False → loop 写 trace + abort

    V0.23.2: 加 UploadAction arm — paths 黑名单匹配 (mark 是 file input 不敏感, paths 才敏感).
    DragAction 不 check (拖动行为本身风险低; 真敏感是 click 到 delete/send 已被 click arm 拦).
    """
    # V0.23.2: UploadAction 优先处理 — paths 是 action 自带字段, 不依赖 mark
    if isinstance(action, UploadAction):
        decision = _check_upload_paths(action.paths)
        if decision is not None:
            return decision
        return SafetyDecision(allow=True)

    if action.type in ("scroll", "extract", "done", "keyboard_shortcut", "drag") or mark is None:
        return SafetyDecision(allow=True)

    if action.type == "click":
        if mark.input_type and mark.input_type.lower() in _DANGER_INPUT_TYPES:
            d = _block("input-type-sensitive", f"safety: click 到敏感输入框 (type={mark.input_type!r}, name={mark.name!r})。")
            if d:
                return d

        for pattern, rule_name in _DANGER_BUTTON_PATTERNS:
            if pattern.search(mark.text or ""):
                d = _block(rule_name, f"safety:{rule_name} (click on {mark.text!r})。")
                if d:
                    return d
                # auto-approved 这条，继续 check 剩余 pattern (其他 rule 可能没批)

        if mark.name and _DANGER_INPUT_NAME_RE.search(mark.name):
            d = _block("input-name-sensitive", f"safety: click 到敏感字段 (name={mark.name!r})。")
            if d:
                return d

    elif action.type == "type":
        # type 是往已 focus 的 input 里键入；mark 是上次 click 的元素
        if mark.input_type and mark.input_type.lower() in _DANGER_INPUT_TYPES:
            d = _block("type-into-sensitive-type", f"safety: type 到敏感输入框 (type={mark.input_type!r}, name={mark.name!r})。")
            if d:
                return d
        if mark.name and _DANGER_INPUT_NAME_RE.search(mark.name):
            d = _block("type-into-sensitive-name", f"safety: type 到敏感字段 (name={mark.name!r})。")
            if d:
                return d

    elif action.type == "paste":
        # V0.19.0: paste 同 type 检查 — 复用敏感 input_type / name 规则; mark 是上次 click 的元素
        if mark.input_type and mark.input_type.lower() in _DANGER_INPUT_TYPES:
            d = _block("paste-into-sensitive-type", f"safety: paste 到敏感输入框 (type={mark.input_type!r}, name={mark.name!r})。")
            if d:
                return d
        if mark.name and _DANGER_INPUT_NAME_RE.search(mark.name):
            d = _block("paste-into-sensitive-name", f"safety: paste 到敏感字段 (name={mark.name!r})。")
            if d:
                return d

    return SafetyDecision(allow=True)
