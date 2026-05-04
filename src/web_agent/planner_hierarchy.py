"""分层规划 (W5-C, prompt augmentation 路线): 长任务给 LLM 注入"考虑拆 subgoal"hint。

蓝本明确点 subgoal 拆分; 当前 ReAct loop 单层无 subgoal 概念, 复杂任务
(e.g. "在 Amazon 搜耳机 → 比价 → 加购 → 填地址") 易在中段 stuck。

设计 (减小架构 risk):
- **不调 LLM** (避 SDK 兼容风险 + 零 token 浪费): 只注入 hint 字符串到 trace,
  LLM 自己在 thought 里拆 subgoal
- 复用 V0.14.0 W5-D.2 已建好的 `memories=` 通道 + `step=-1 memory_recall` synthetic step:
  cli.py 把 subgoal hint 拼到 memories_str, loop 不动
- 启发式触发: 长任务 (≥200 字) 或带 ≥2 个序号前缀 (1./①/- ); 短任务跳过零开销
- env `WEB_AGENT_SUBGOAL_DISABLE=true` 完全关
"""

from __future__ import annotations

import os
import re

_LEN_THRESHOLD = 200

# 匹配序号前缀: "1." / "1)" / "1、" / "①-⑩" / "- " / "* "
_NUM_PREFIX_RE = re.compile(
    r"(?m)^\s*(?:[0-9]+[.\)、]|[①②③④⑤⑥⑦⑧⑨⑩]|[-*])\s+"
)


def should_decompose(goal: str) -> bool:
    """启发式判断是否给 LLM 注入 subgoal hint。

    触发: env 未关 AND (长度 ≥200 字 OR 含 ≥2 个序号前缀)。
    短任务 (e.g. "搜苹果价格") 跳过 — 0 token 浪费。
    """
    if os.environ.get("WEB_AGENT_SUBGOAL_DISABLE", "").lower() in ("true", "1", "yes"):
        return False
    if not goal:
        return False
    if len(goal) >= _LEN_THRESHOLD:
        return True
    if len(_NUM_PREFIX_RE.findall(goal)) >= 2:
        return True
    return False


_SUBGOAL_HINT = (
    "=== 任务规划提示 (W5-C subgoal split) ===\n"
    "本任务较复杂. 建议你在执行第一个 click/type 之前, 先在 thought 字段里"
    "把任务拆成 3-6 个 subgoal (如: 1. 搜索 → 2. 筛选/排序 → 3. 进入详情 → 4. 提取数据 → 5. done), "
    "然后逐个 subgoal 推进, 每步 thought 标明当前在第几个 subgoal。"
    "这样能避免在中段忘了大局或反复 scroll 在错误页面浪费步数。"
)


def build_subgoal_hint_text() -> str:
    """返回纯字符串模板 (固定常量, 无 LLM 调用, 零 token 成本)。"""
    return _SUBGOAL_HINT


def merge_into_memories(memories_str: str | None, subgoal_hint: str) -> str:
    """把 subgoal hint 拼到 memories_str 后面 (走 W5-D.2 step=-1 channel)。

    - memories_str 空 → 仅返 hint
    - 都有 → "\n\n" 隔开
    - 总长由 cli 端控制 (loop.py 内部 [:2000] 截断兜底)
    """
    if not subgoal_hint:
        return memories_str or ""
    if memories_str:
        return f"{memories_str}\n\n{subgoal_hint}"
    return subgoal_hint
