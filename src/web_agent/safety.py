"""授权白名单：在 actuator 之前 intercept 危险 action（W3-A）。

设计原则：
- safe by default — 默认拦 send/pay/delete/submit/transfer + 敏感字段 (password/tel/amount/cvv/...)
- 用户预授权 — `WEB_AGENT_AUTO_APPROVE=rule1,rule2,...` env 放行特定规则
- 全开 — `WEB_AGENT_AUTO_APPROVE=*` (dev 用，生产慎)
- 触发即 abort — loop 强制中止，不让 LLM 继续 retry/换策略（避免重撞）

依赖方向（按 CLAUDE.md 解耦）：domain (Mark, Action) → safety.py (本文件，纯函数) ← loop.py (业务层调用)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from web_agent.llm.base import Action
from web_agent.perceiver import Mark


@dataclass
class SafetyDecision:
    allow: bool
    rule: str = ""  # 触发的规则名（用于 trace + auto_approve 反向放行）
    reason: str = ""  # 给用户看的友好阻拦理由


# (regex, rule_name) — 用 \b word boundary 避免 "sender" 误撞 "send"
_DANGER_BUTTON_PATTERNS: list[tuple[str, str]] = [
    # 英文：发送 / 付款 / 删除 / 转账 / 二次确认 / 授权 / 取消订阅
    (
        r"\b(send|submit|publish|post|pay|paypal|checkout|delete|remove|withdraw|transfer|"
        r"wire|buy|order|purchase|place[ -]order|confirm[ -]?(payment|order)|authorize|"
        r"approve|agree[ -]and[ -]continue|accept[ -]and[ -]continue)\b",
        "send-or-pay",
    ),
    # 中文：发送 / 支付 / 删除 / 转账 / 确认订单 / 立即支付 / 授权
    (
        r"(发送|发布|提交|支付|付款|删除|确认订单|下单|结算|转账|提款|授权|"
        r"同意.{0,3}继续|立即(支付|购买|提现|结算)|确认支付|确认下单)",
        "zh-send-or-pay",
    ),
    # 订阅取消 / 账号注销
    (r"\b(unsubscribe|cancel[ -]subscription|deactivate[ -]account|close[ -]account)\b", "subscription-cancel"),
    (r"(取消订阅|注销账号|关闭账号|解除订阅)", "zh-subscription-cancel"),
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


def check(action: Action, mark: Mark | None, marks: list[Mark] | None = None) -> SafetyDecision:
    """在 actuator 调用前调一次。allow=False → loop 必须 graceful abort。

    Args:
        action: LLM 返回的下一步行动
        mark: click 的目标元素 / type 的上次 click 元素；scroll/extract/done 时为 None
        marks: 当前所有 marks（保留给 form action 检测等未来扩展，本版未用）

    Returns:
        SafetyDecision.allow=True → 放行；False → loop 写 trace + abort
    """
    if action.type in ("scroll", "extract", "done"):
        return SafetyDecision(allow=True)

    if action.type == "click" and mark is not None:
        # input type=password/tel 聚焦本身可疑（LLM 可能想填密码）
        if mark.input_type and mark.input_type.lower() in _DANGER_INPUT_TYPES:
            rule = "input-type-sensitive"
            if not _auto_approved(rule):
                return SafetyDecision(
                    allow=False,
                    rule=rule,
                    reason=(
                        f"safety: click 到敏感输入框 (type={mark.input_type!r}, name={mark.name!r})。"
                        f"预授权: WEB_AGENT_AUTO_APPROVE={rule} (或 *)"
                    ),
                )

        # 按钮文本黑名单
        text = mark.text or ""
        for pattern, rule_name in _DANGER_BUTTON_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                if _auto_approved(rule_name):
                    continue
                return SafetyDecision(
                    allow=False,
                    rule=rule_name,
                    reason=(
                        f"safety:{rule_name} (click on {text!r})。"
                        f"预授权: WEB_AGENT_AUTO_APPROVE={rule_name} (或 *)"
                    ),
                )

        # input name 含敏感关键词（含 amount/cvv/card/otp/...）
        if mark.name and _DANGER_INPUT_NAME_RE.search(mark.name):
            rule = "input-name-sensitive"
            if not _auto_approved(rule):
                return SafetyDecision(
                    allow=False,
                    rule=rule,
                    reason=(
                        f"safety: click 到敏感字段 (name={mark.name!r})。"
                        f"预授权: WEB_AGENT_AUTO_APPROVE={rule} (或 *)"
                    ),
                )

    if action.type == "type" and mark is not None:
        # type 是往已 focus 的 input 里键入；mark 应该是上次 click 的元素
        if mark.input_type and mark.input_type.lower() in _DANGER_INPUT_TYPES:
            rule = "type-into-sensitive-type"
            if not _auto_approved(rule):
                return SafetyDecision(
                    allow=False,
                    rule=rule,
                    reason=(
                        f"safety: type 到敏感输入框 (type={mark.input_type!r}, name={mark.name!r})。"
                        f"预授权: WEB_AGENT_AUTO_APPROVE={rule} (或 *)"
                    ),
                )
        if mark.name and _DANGER_INPUT_NAME_RE.search(mark.name):
            rule = "type-into-sensitive-name"
            if not _auto_approved(rule):
                return SafetyDecision(
                    allow=False,
                    rule=rule,
                    reason=(
                        f"safety: type 到敏感字段 (name={mark.name!r})。"
                        f"预授权: WEB_AGENT_AUTO_APPROVE={rule} (或 *)"
                    ),
                )

    return SafetyDecision(allow=True)
