"""V0.26.0: eval corpus 任务类型 + capability axis 标签."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from web_agent.chain import ChainSpec

# V0.26.0: capability axis 用 Literal 跟 V0.17.0 Action union discriminated 同档,
# mypy strict 自动 narrow, 加新轴改 1 处不引依赖. enum 在 dataclass JSON 序列化
# 多一层 .value 跟 metrics dump 需求冲突.
CapabilityAxis = Literal[
    "multi-tab",        # V0.21: switch_tab/close_tab/popup
    "iframe",           # V0.22: iframe SoM 注入 + frame.locator 路由
    "drag",             # V0.23: human_like_drag 单段贝塞尔
    "upload",           # V0.23: upload_file DOM walk 隐藏 input
    "download",         # V0.23: download listener 自动落 task 隔离目录
    "dialog",           # V0.24: alert/confirm/prompt/beforeunload auto-handle
    "retry",            # V0.25.0: transient retry budget
    "backtrack",        # V0.25.2: anti-loop go_back + reset
    "keyboard-nav",     # V0.24.2: PageDown/Escape/Tab 优先 scroll
    "failure-recovery", # V0.25.3: ERROR/[reflect]/[backtrack] 信号应对
    "real-world",       # B1: 2-3 真外网 task (二级 opt-in env WEB_AGENT_EVAL_REAL)
    "baseline",         # V0.26.0: 框架示范 task (W1 类: perceive + click + extract)
]


@dataclass(frozen=True, slots=True)
class EvalTask:
    """V0.26.0: 单个 eval 任务定义.

    fixture_url: 优先 data:text/html (确定性 + 0 ban) 兼容偶尔 https://stable-static-site/.
    success_predicate: 接 (final_result_text, trace_steps_dict_list) → bool, 由 predicates.py
    构造 (Substring/Regex/LLMJudge); Predicate Protocol 不进 EvalTask (避免循环 import).
    expected_step_range: (min, max) 用作 step 数 outlier 检测信号 (eval 不强 fail 但 metrics dump).
    """

    task_id: str
    goal: str
    fixture_url: str
    capability_axis: CapabilityAxis
    expected_step_range: tuple[int, int]
    max_steps: int = 10
    max_wallclock_s: float = 60.0
    description: str = ""  # 给 eval 报告 + replay 面板用的 1 句话说明
    tags: tuple[str, ...] = field(default_factory=tuple)  # 自由 tag (e.g. "stripe", "github")
    # V0.29.4 W6-C 收尾验证: chain task 字段. None = 单 task 老路径; ChainSpec → eval/runner.run_one
    # 走 run_chain 分支. fixture_url 是 chain 起点 (page.goto 一次), 跨 node 接力 cdp 当前 tab.
    chain_spec: "ChainSpec | None" = None
