"""V0.26.0: 示范 corpus task — 1 个简单 baseline task 验框架可跑.

V0.26.1 充实到 10 task 覆盖 V0.21-V0.25 各能力轴. 本 commit 仅放 1 task 让 V0.26.0
runner + predicate + types 三件套端到端可测.
"""

from __future__ import annotations

import urllib.parse

from eval.predicates import SubstringPredicate
from eval.types import EvalTask

# data:text/html fixture: 简单页面含已知 H1 + 1 button. agent 任务 = 找 H1 文本.
# 强制 SubstringPredicate 含 task-specific token "量子纠缠是" 防 agent done(result="完成") 假阳性.
_BASELINE_HTML = (
    "<html><body>"
    "<h1>量子纠缠是粒子之间的关联</h1>"
    "<p>无论距离多远, 测一个就立刻知道另一个状态.</p>"
    "<button>无关 button</button>"
    "</body></html>"
)
_BASELINE_URL = "data:text/html," + urllib.parse.quote(_BASELINE_HTML)


BASELINE_EXTRACT_H1 = EvalTask(
    task_id="baseline-extract-h1-001",
    goal="读这个页面的 H1 标题文本, 用 done(result=...) 返回完整标题字符串",
    fixture_url=_BASELINE_URL,
    capability_axis="baseline",
    expected_step_range=(1, 3),
    max_steps=5,
    max_wallclock_s=30.0,
    description="V0.26.0 框架示范: perceive + extract/done 单步任务验骨架",
    tags=("framework-smoke",),
)

# Predicate 跟 task 1:1 绑 (V0.26.0 简化), V0.26.1 可考虑 task → multi-predicate dict
BASELINE_PREDICATES = {
    BASELINE_EXTRACT_H1.task_id: SubstringPredicate(substring="量子纠缠是粒子之间的关联"),
}

ALL_TASKS = [BASELINE_EXTRACT_H1]  # V0.26.1 充实
