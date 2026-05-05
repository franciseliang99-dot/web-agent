"""授权白名单：在 actuator 之前 intercept 危险 action（W3-A）。

设计原则：
- safe by default — 默认拦 send/pay/delete/submit/transfer + 敏感字段 (password/tel/amount/cvv/...)
- 用户预授权 — `WEB_AGENT_AUTO_APPROVE=rule1,rule2,...` env 放行特定规则
- 全开 — `WEB_AGENT_AUTO_APPROVE=*` (dev 用，生产慎)
- 触发即 abort — loop 强制中止，不让 LLM 继续 retry/换策略（避免重撞）

依赖方向（按 CLAUDE.md 解耦）：domain (web_agent.types: Mark, Action) ← safety.py (本文件，纯函数) ← loop.py (业务层调用)

V0.16.9: 改从 `web_agent.types` import Mark/Action，消除 domain 反向依赖 port (llm.base) 和 业务层 (perceiver)。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from web_agent.types import Action, Mark


@dataclass
class SafetyDecision:
    allow: bool
    rule: str = ""  # 触发的规则名（用于 trace + auto_approve 反向放行）
    reason: str = ""  # 给用户看的友好阻拦理由


# (compiled_regex, rule_name) — 用 \b word boundary 避免 "sender" 误撞 "send"
# 模块加载时 compile 一次，后续 check() 调用零 compile/cache-lookup 开销
_DANGER_BUTTON_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 英文：发送 / 付款 / 删除 / 转账 / 二次确认 / 授权 / 取消订阅
    (
        re.compile(
            r"\b(send|submit|publish|post|pay|paypal|checkout|delete|remove|withdraw|transfer|"
            r"wire|buy|order|purchase|place[ -]order|confirm[ -]?(payment|order)|authorize|"
            r"approve|agree[ -]and[ -]continue|accept[ -]and[ -]continue)\b",
            re.IGNORECASE,
        ),
        "send-or-pay",
    ),
    # 中文：发送 / 支付 / 删除 / 转账 / 确认订单 / 立即支付 / 授权
    (
        re.compile(
            r"(发送|发布|提交|支付|付款|删除|确认订单|下单|结算|转账|提款|授权|"
            r"同意.{0,3}继续|立即(支付|购买|提现|结算)|确认支付|确认下单)",
        ),
        "zh-send-or-pay",
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
    """
    if action.type in ("scroll", "extract", "done") or mark is None:
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

    return SafetyDecision(allow=True)
