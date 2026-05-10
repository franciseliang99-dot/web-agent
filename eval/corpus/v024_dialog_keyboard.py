"""V0.26.1 corpus: V0.24 dialog + 键盘导航 能力轴 task (2 task)."""

from __future__ import annotations

from eval.corpus._fixtures import (
    TOKEN_DIALOG_CONFIRM_MSG,
    TOKEN_KEYBOARD_NAV_BOTTOM,
    URL_DIALOG_CONFIRM,
    URL_KEYBOARD_NAV,
)
from eval.predicates import AllOf, Predicate, SubstringPredicate, TraceObsContains
from eval.types import EvalTask

DIALOG_CONFIRM_OBS_READING = EvalTask(
    task_id="v024-dialog-confirm-extract-message",
    goal=(
        "页面有一个 'trigger dialog' button. click 后会弹 confirm dialog. "
        "dialog 已被自动 dismiss, 但下一步 obs 会出现 'dialog confirm: <message>' 信息. "
        "用 done(result=...) 返回完整 dialog message 字符串"
    ),
    fixture_url=URL_DIALOG_CONFIRM,
    capability_axis="dialog",
    expected_step_range=(3, 6),
    max_steps=8,
    max_wallclock_s=45.0,
    description="LLM 真读 dialog obs (V0.24.0 listener + V0.24.1 helper drain to obs); SYSTEM_PROMPT 第 14 条第 5 项",
    tags=("v024", "dialog", "obs-reading"),
)

KEYBOARD_NAV_PAGEDOWN = EvalTask(
    task_id="v024-keyboard-nav-scroll-to-bottom",
    goal=(
        "页面有一个 modal 容器内含 2000px 长内容, 底部有个 'bottom button' button. "
        "用键盘 PageDown / End 滚到底部, click 那个 button 后页面会显示一个 H1 token. "
        "用 done(result=...) 返回 H1 完整文本"
    ),
    fixture_url=URL_KEYBOARD_NAV,
    capability_axis="keyboard-nav",
    expected_step_range=(3, 8),
    max_steps=10,
    max_wallclock_s=60.0,
    description="LLM 真用 keyboard_shortcut(PageDown/End) 而非死磕 scroll; SYSTEM_PROMPT 第 13 条",
    tags=("v024", "keyboard-nav"),
)

DIALOG_KEYBOARD_PREDICATES: dict[str, Predicate] = {
    DIALOG_CONFIRM_OBS_READING.task_id: AllOf(predicates=(
        SubstringPredicate(substring=TOKEN_DIALOG_CONFIRM_MSG),
        TraceObsContains(substring="dialog confirm:"),
    )),
    KEYBOARD_NAV_PAGEDOWN.task_id: SubstringPredicate(substring=TOKEN_KEYBOARD_NAV_BOTTOM),
}
