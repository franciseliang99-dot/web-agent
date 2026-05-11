"""V0.26.1 corpus 整合: 9 task 覆盖 V0.21-V0.25 各能力轴 (drop V0.25 retry+backtrack 推迟 V0.26.3).

V0.26.1 sanity (subagent 论证):
- drop transient retry task (V0.25.0 单测已覆盖, LLM 0 主动行为, 加 corpus 0 信息增量)
- 推迟 backtrack task 到 V0.26.3 cassette ready (data:html 单页 go_back 无 history; mock LLM
  难造稳定 anti_loop trigger; 真 LLM 行为得 vcr 录回放才能稳定 baseline)

ALL_TASKS: 9 task (1 baseline + 8 V0.21-V0.25 能力).
ALL_PREDICATES: dict[task_id, Predicate] — runner 用 task_id 反查 predicate.
"""

from __future__ import annotations

import urllib.parse

from eval.corpus.v021_multitab import MULTITAB_POPUP_EXTRACT, MULTITAB_PREDICATES
from eval.corpus.v022_iframe import IFRAME_CLICK_BUTTON, IFRAME_PREDICATES
from eval.corpus.v022_v021_cross_feature import (
    CROSS_FEATURE_PREDICATES,
    POPUP_WITH_IFRAME_CLICK,
)
from eval.corpus.v023_drag_upload_download import (
    DOWNLOAD_LINK_CLICK,
    DRAG_DROP_TRELLO,
    DRAG_UPLOAD_DOWNLOAD_PREDICATES,
    UPLOAD_FILE_TO_INPUT,
)
from eval.corpus.v024_dialog_keyboard import (
    DIALOG_CONFIRM_OBS_READING,
    DIALOG_KEYBOARD_PREDICATES,
    KEYBOARD_NAV_PAGEDOWN,
)
from eval.corpus.v025_recovery import (
    FAILURE_RECOVERY_FIND_VALID_BUTTON,
    RECOVERY_PREDICATES,
)
from eval.corpus.v029_chain import (
    CHAIN_PREDICATES,
    CHAIN_REFLECT_TRIGGER,
    CHAIN_REVEAL_2NODE,
)
from eval.corpus.v030_real_world import (
    GITHUB_OCTOCAT_README,
    REAL_WORLD_PREDICATES,
    WIKIPEDIA_APPLE_INC,
    WIKIPEDIA_QUANTUM_FIRST_PARA,
)
from eval.corpus.v032_chain_real_world import (
    CHAIN_REAL_WORLD_PREDICATES,
    GITHUB_TOPIC_PYTHON_FIRST_README,
    WIKIPEDIA_APPLE_TO_CUPERTINO_CHAIN,
)
from eval.corpus.v035_capability_real_world import (
    CAPABILITY_REAL_WORLD_PREDICATES,
    WIKIPEDIA_SEARCH_QUANTUM_FIELD_THEORY,
)
from eval.predicates import Predicate, SubstringPredicate
from eval.types import EvalTask

# V0.26.0 baseline (1 task) — 留作框架 smoke
_BASELINE_HTML = (
    "<html><body>"
    "<h1>量子纠缠是粒子之间的关联</h1>"
    "<p>无论距离多远, 测一个就立刻知道另一个状态.</p>"
    "<button>无关 button</button>"
    "</body></html>"
)
BASELINE_EXTRACT_H1 = EvalTask(
    task_id="baseline-extract-h1-001",
    goal="读这个页面的 H1 标题文本, 用 done(result=...) 返回完整标题字符串",
    fixture_url="data:text/html," + urllib.parse.quote(_BASELINE_HTML),
    capability_axis="baseline",
    expected_step_range=(1, 3),
    max_steps=5,
    max_wallclock_s=30.0,
    description="V0.26.0 框架示范: perceive + extract/done 单步任务验骨架",
    tags=("framework-smoke",),
)
_BASELINE_PREDICATES: dict[str, Predicate] = {
    BASELINE_EXTRACT_H1.task_id: SubstringPredicate(substring="量子纠缠是粒子之间的关联"),
}

ALL_TASKS: list[EvalTask] = [
    BASELINE_EXTRACT_H1,
    MULTITAB_POPUP_EXTRACT,
    IFRAME_CLICK_BUTTON,
    DRAG_DROP_TRELLO,
    UPLOAD_FILE_TO_INPUT,
    DOWNLOAD_LINK_CLICK,
    DIALOG_CONFIRM_OBS_READING,
    KEYBOARD_NAV_PAGEDOWN,
    FAILURE_RECOVERY_FIND_VALID_BUTTON,
    POPUP_WITH_IFRAME_CLICK,
    CHAIN_REVEAL_2NODE,  # V0.29.4 W6-C 收尾: chain task (eval --chain pipeline 验)
    CHAIN_REFLECT_TRIGGER,  # V0.29.5 W6-C 收口: chain task 触发 reflect 验 reflective_uplift on chain
    WIKIPEDIA_QUANTUM_FIRST_PARA,  # V0.30.2 D real-world: wikipedia 静态 page (requires_real_net=True 默跳)
    WIKIPEDIA_APPLE_INC,  # V0.30.4 D real-world: 第 2 wikipedia (公司 page 跨 academic baseline)
    GITHUB_OCTOCAT_README,  # V0.30.4 D real-world: GitHub web UI description (跨 source baseline)
    GITHUB_TOPIC_PYTHON_FIRST_README,  # V0.32.0 D' chain × real-world (GitHub topic search → README)
    WIKIPEDIA_APPLE_TO_CUPERTINO_CHAIN,  # V0.32.2 D' chain × real-world (wiki cross-ref Apple→Cupertino)
    WIKIPEDIA_SEARCH_QUANTUM_FIELD_THEORY,  # V0.35.0 A capability × real-world (actuator type+click)
]

# 合并所有 predicate 到单 dict (runner 反查用). 各子 dict value 类型 mypy 默认推断为
# concrete class (SubstringPredicate / AllOf), 强制 cast 到 Predicate 让 dict 类型一致.
ALL_PREDICATES: dict[str, Predicate] = {}
for _sub_dict in (
    _BASELINE_PREDICATES,
    MULTITAB_PREDICATES,
    IFRAME_PREDICATES,
    DRAG_UPLOAD_DOWNLOAD_PREDICATES,
    DIALOG_KEYBOARD_PREDICATES,
    RECOVERY_PREDICATES,
    CROSS_FEATURE_PREDICATES,
    CHAIN_PREDICATES,  # V0.29.4 W6-C
    REAL_WORLD_PREDICATES,  # V0.30.2 D real-world
    CHAIN_REAL_WORLD_PREDICATES,  # V0.32.0 D' chain × real-world
    CAPABILITY_REAL_WORLD_PREDICATES,  # V0.35.0 A capability × real-world
):
    ALL_PREDICATES.update(_sub_dict)


# --- token-specific lint (V0.26.1 plan B7 强制) ---

# 通用词集 (LLM 常 done(result="完成") 这种含义不强的词不能算 task-specific token)
_GENERIC_WORDS = frozenset({
    "完成", "成功", "done", "ok", "OK", "success", "completed", "finished",
    "结果", "result", "返回", "answer",
})


def lint_corpus_tokens(tasks: list[EvalTask], predicates: dict[str, Predicate]) -> list[str]:
    """V0.26.1: 检查所有 task 的 SubstringPredicate.substring 符合 task-specific 强制约束.

    递归遍历 AllOf.predicates, 找所有 SubstringPredicate 节点检查 substring:
    - 长度 ≥ 8 字符
    - 不在 _GENERIC_WORDS 通用词集

    返回 violations list[str]; 空 list 表示全过. 测试 + V0.26.3 web-agent-eval CLI 启动时
    跑 (lint failure 直接 exit 1 防 corpus 演化几个月混入水货 token).
    """
    violations: list[str] = []
    for task in tasks:
        pred = predicates.get(task.task_id)
        if pred is None:
            violations.append(f"{task.task_id}: 缺 predicate 绑定")
            continue
        for sub_pred in _walk_substring_predicates(pred):
            if len(sub_pred.substring) < 8:
                violations.append(
                    f"{task.task_id}: substring {sub_pred.substring!r} 长度 < 8 (易蒙混)"
                )
            if sub_pred.substring in _GENERIC_WORDS:
                violations.append(
                    f"{task.task_id}: substring {sub_pred.substring!r} 在通用词集 (假阳性风险)"
                )
    return violations


def _walk_substring_predicates(pred: Predicate) -> list[SubstringPredicate]:
    """递归找 Predicate 内所有 SubstringPredicate 节点 (含 AllOf 嵌套)."""
    from eval.predicates import AllOf
    out: list[SubstringPredicate] = []
    if isinstance(pred, SubstringPredicate):
        out.append(pred)
    elif isinstance(pred, AllOf):
        for child in pred.predicates:
            out.extend(_walk_substring_predicates(child))
    return out
