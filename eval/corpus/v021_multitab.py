"""V0.26.1 corpus: V0.21 multi-tab 能力轴 task — popup 出来后 switch_tab 提取标题."""

from __future__ import annotations

from eval.corpus._fixtures import TOKEN_MULTITAB_POPUP_H1, URL_MULTITAB_POPUP
from eval.predicates import Predicate, SubstringPredicate
from eval.types import EvalTask

MULTITAB_POPUP_EXTRACT = EvalTask(
    task_id="v021-multitab-popup-extract",
    goal=(
        "页面有一个 'open new tab' 链接, click 它会弹一个新 tab. "
        "切到新 tab 看 H1 文本, 用 done(result=...) 返回完整 H1 字符串"
    ),
    fixture_url=URL_MULTITAB_POPUP,
    capability_axis="multi-tab",
    expected_step_range=(3, 6),  # click → switch_tab → perceive popup → done
    max_steps=8,
    max_wallclock_s=45.0,
    description="LLM 真用 switch_tab(idx=1) 切到 popup 提取 H1; SYSTEM_PROMPT 第 10 条指南",
    tags=("v021", "multi-tab", "popup"),
)

MULTITAB_PREDICATES: dict[str, Predicate] = {
    MULTITAB_POPUP_EXTRACT.task_id: SubstringPredicate(substring=TOKEN_MULTITAB_POPUP_H1),
}
