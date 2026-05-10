"""V0.26.1 corpus: V0.25 失败恢复能力轴 task (1 task).

retry/backtrack 推迟 V0.26.3 cassette ready (data:html 单页 page.go_back 无 history,
mock LLM 难造 anti_loop trigger). 见 CHANGELOG V0.26.1 推迟说明.
"""

from __future__ import annotations

from eval.corpus._fixtures import TOKEN_FAILURE_RECOVERY_VALID, URL_FAILURE_RECOVERY
from eval.predicates import Predicate, SubstringPredicate
from eval.types import EvalTask

FAILURE_RECOVERY_FIND_VALID_BUTTON = EvalTask(
    task_id="v025-failure-recovery-find-valid-button",
    goal=(
        "页面有 3 个 button: 2 个 DECOY (无效) + 1 个 VALID (有效). "
        "请找到 VALID button 并 click. click 后页面 H1 会变成一个 token. "
        "用 done(result=...) 返回 H1 完整文本. "
        "注: 如果选错 button 看不到任何变化, 请换 button 不要死磕同一个"
    ),
    fixture_url=URL_FAILURE_RECOVERY,
    capability_axis="failure-recovery",
    expected_step_range=(2, 6),
    max_steps=8,
    max_wallclock_s=45.0,
    description="LLM 看到 click DECOY 后页面无变化 → 换另一 button (W5-A reflect hint 触发或 LLM 主动换)",
    tags=("v025", "failure-recovery"),
)

RECOVERY_PREDICATES: dict[str, Predicate] = {
    FAILURE_RECOVERY_FIND_VALID_BUTTON.task_id: SubstringPredicate(substring=TOKEN_FAILURE_RECOVERY_VALID),
}
