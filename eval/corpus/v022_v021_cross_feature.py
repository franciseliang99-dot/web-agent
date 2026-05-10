"""V0.26.1 corpus: V0.21 + V0.22 cross-feature task — popup 内含 iframe (stress test).

用 capability_axis="iframe" 标 (popup 部分 V0.21 已 cover by v021 task; 重点是 iframe
inside popup 跨 V0.21+V0.22 边界 LLM 能否处理).
"""

from __future__ import annotations

from eval.corpus._fixtures import TOKEN_CROSS_FEATURE_DONE, URL_CROSS_FEATURE
from eval.predicates import AllOf, Predicate, SubstringPredicate, TraceContainsAction
from eval.types import EvalTask

POPUP_WITH_IFRAME_CLICK = EvalTask(
    task_id="v021-v022-popup-with-iframe-click",
    goal=(
        "页面有一个 'open' 链接, click 弹新 tab. "
        "新 tab 内有 iframe, iframe 内有 'iframe button'. "
        "切到新 tab 后 click iframe 内 button, 父页面会出现一个 H1 token. "
        "用 done(result=...) 返回 H1 完整文本"
    ),
    fixture_url=URL_CROSS_FEATURE,
    capability_axis="iframe",  # 主要考验 iframe 路由 (popup 已 v021 cover)
    expected_step_range=(4, 8),
    max_steps=12,
    max_wallclock_s=60.0,
    description="cross-feature stress test: V0.21 switch_tab + V0.22 iframe frame_path 路由; LLM 跨 commit 能力组合",
    tags=("v021", "v022", "cross-feature", "stress"),
)

CROSS_FEATURE_PREDICATES: dict[str, Predicate] = {
    POPUP_WITH_IFRAME_CLICK.task_id: AllOf(predicates=(
        SubstringPredicate(substring=TOKEN_CROSS_FEATURE_DONE),
        TraceContainsAction(action_type="switch_tab", min_count=1),
        TraceContainsAction(action_type="click", min_count=1),
    )),
}
