"""V0.26.1 corpus: V0.22 iframe 能力轴 task — srcdoc iframe 内点 button."""

from __future__ import annotations

from eval.corpus._fixtures import TOKEN_IFRAME_CLICKED, URL_IFRAME_CLICK
from eval.predicates import AllOf, Predicate, SubstringPredicate, TraceContainsAction
from eval.types import EvalTask

IFRAME_CLICK_BUTTON = EvalTask(
    task_id="v022-iframe-click-button",
    goal=(
        "页面里有一个 iframe, iframe 内有个 'click me' button. "
        "click 它后页面会出现一个 ack token. 找到这个 token 用 done(result=...) 返回"
    ),
    fixture_url=URL_IFRAME_CLICK,
    capability_axis="iframe",
    expected_step_range=(3, 6),
    max_steps=8,
    max_wallclock_s=45.0,
    description="LLM 真在 iframe 里 click button (frame_path 路由); V0.22.2 actuator iframe 走 frame.locator",
    tags=("v022", "iframe", "click"),
)

IFRAME_PREDICATES: dict[str, Predicate] = {
    IFRAME_CLICK_BUTTON.task_id: AllOf(predicates=(
        SubstringPredicate(substring=TOKEN_IFRAME_CLICKED),
        TraceContainsAction(action_type="click", min_count=1),
    )),
}
