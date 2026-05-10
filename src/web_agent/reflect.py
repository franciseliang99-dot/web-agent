"""V0.28.0: W6-A reflective replay 开篇 — 失败 trace LLM 反思纯函数.

W6 vs W5-A 边界 (Plan subagent 决, V0.28 plan 落定):
- W5-A `_maybe_inject_reflect_hint` (loop.py): intra-step deterministic, 0 LLM call,
  obs append "[reflect]" 通道, 触发条件页面 3 步 fingerprint 无变化
- W6-A `reflect_on_failure` (本): inter-task LLM-driven, 1 LLM call (V0.28.1 wire),
  structured Reflection 输出, 跟 memory.py 长期记忆通道协同 (V0.28.2 wire inject 跨 task)

V0.28.0 scope: 只做 prompt build + parse 纯函数 + should_reflect 触发判断, **不调 LLMClient**
(V0.28.1 wire loop 时再决接口选择 — 复用 plan() vs 加 reflect() Protocol 方法). 不接 loop /
cli / memory / SYSTEM_PROMPT. 这跟 V0.27.1 vault framework "纯接口 + 后续接入" 节奏一致.

V0.28 W6 系列 commit 拆解 (subagent 推, W6-C 推 V0.29+):
- V0.28.0 (本): reflect.py 纯函数 + 7 单测
- V0.28.1: loop.py max_steps/LOOP_DETECTED 耗尽 → 调 reflect_on_failure + 写 reflections 表
- V0.28.2: cli.py 启动按 domain 拉 reflections inject 进 memories_str (跟 W5-D.2 同通道)
- V0.28.3: eval/runner --reflect flag + 算 reflective_uplift = pass2_rate - pass1_rate metric
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# tolerate ```json ... ``` / ``` ... ``` markdown fence (Anthropic Sonnet 偶尔加).
# 跟 jd_extract.py:71 _MD_CODE_BLOCK_RE 同套 (DRY 接受复制 — 单行 regex 跨模块抽常量 over-eng).
_MD_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Reflection:
    """V0.28.0: W6-A 反思结果 — root_cause + hint 2 字段 (subagent C 决, suggested_action over-eng).

    跟 web_agent.types.Action/Mark/Usage 同 frozen+slots 模式, V0.28.2 inject memory 时 hashable safe.
    """

    root_cause: str
    hint: str


# subagent A 决: max_steps + LOOP_DETECTED 触发, 排除 WALLCLOCK/SAFETY/CAPTCHA/LLM_FAILED
# 外因 (网络慢 / 规则拦 / 人机验证 / SDK fault) reflect 给不出可操作 hint, 烧 token 无价值.
# 跟 loop.py FAILURE_MARKERS 子集对齐.
TRIGGERING_FAILURE_MARKERS: frozenset[str] = frozenset({
    "max_steps",        # "(max_steps 耗尽未完成)" loop 上限触发, plan 缺陷
    "LOOP_DETECTED",    # V0.5.0 anti-loop 硬 abort, plan 撞墙
})


def should_reflect(final_result: str) -> bool:
    """V0.28.0: 决 final_result 是否触发 W6-A reflect (subagent A 决).

    triggering: max_steps / LOOP_DETECTED 两类 plan 缺陷.
    skipping: WALLCLOCK_EXCEEDED / SAFETY_BLOCK / CAPTCHA / LLM_FAILED 外因 / 成功 result.
    """
    return any(marker in final_result for marker in TRIGGERING_FAILURE_MARKERS)


def build_reflect_prompt(
    goal: str,
    trace_steps: list[dict[str, Any]],
    final_result: str,
) -> str:
    """V0.28.0: 构造 W6-A 反思 prompt (subagent B 决: 全文本 trace, screenshot V0.28.1 wire 时加).

    Args:
        goal: 原 task goal
        trace_steps: trace.for_llm() 输出 (list of dict, 含 step/thought/action/observation)
        final_result: task 失败 marker 字符串 (e.g. "(max_steps 耗尽未完成)")

    Returns:
        prompt 字符串供 LLM 输入, 要求返 JSON {root_cause: str, hint: str}.
    """
    trace_str = "\n".join(
        f"[step {s['step']}] thought={s['thought']!r} action={s['action']!r} obs={s['observation']!r}"
        for s in trace_steps
    )
    return (
        f"# 失败任务反思 (V0.28 W6-A)\n\n"
        f"## 原任务 goal\n{goal}\n\n"
        f"## 失败 trace ({len(trace_steps)} steps)\n{trace_str}\n\n"
        f"## 失败 result\n{final_result}\n\n"
        f"## 请反思\n"
        f"返回 JSON 格式 {{\"root_cause\": \"<1-2 句失败根因>\", \"hint\": \"<1-2 句下次同 domain "
        f"task 启动时该注意的 actionable hint>\"}}. 不要返其他内容, 不要 markdown code fence."
    )


def parse_reflection(response_text: str) -> Reflection:
    """V0.28.0: 从 LLM 返值 parse Reflection JSON, 失败 fallback 防阻塞 V0.28.1 wire 路径.

    Fallback: response_text 不能 parse 成 {root_cause, hint} → Reflection("(reflect_parse_failed)",
    response_text[:200]) — root_cause 标失败, hint 留 raw text 给人工调查.
    Tolerate: ```json ... ``` markdown fence (LLM 偶尔加).
    """
    text = response_text.strip()
    md_match = _MD_CODE_BLOCK_RE.search(text)
    if md_match:
        text = md_match.group(1)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return Reflection(root_cause="(reflect_parse_failed)", hint=response_text[:200])
    if isinstance(data, dict) and "root_cause" in data and "hint" in data:
        return Reflection(
            root_cause=str(data["root_cause"]),
            hint=str(data["hint"]),
        )
    return Reflection(root_cause="(reflect_parse_failed)", hint=response_text[:200])


__all__ = [
    "Reflection",
    "TRIGGERING_FAILURE_MARKERS",
    "build_reflect_prompt",
    "parse_reflection",
    "should_reflect",
]
