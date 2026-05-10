"""V0.26.0: success predicate Protocol + 内建 SubstringPredicate / RegexPredicate.

LLMJudgePredicate 留 V0.26.2 (依赖 web_agent.llm.make_client 跨 provider Haiku 廉价 model).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PredicateResult:
    """V0.26.0: predicate 评估结果 — bool + 可读理由 (落 metrics JSON 让人审)."""

    matched: bool
    reason: str = ""
    name: str = ""  # predicate 类名 (e.g. "Substring") 让 metrics 知道用哪个判定器


class Predicate(Protocol):
    """V0.26.0: success predicate 接口.

    接 final_result (run_react_loop 返字符串) + trace_steps (loop 写入 trace.db 的 step list,
    每 step 是 dict, 跟 trace.Step.to_dict() 同形). 返 PredicateResult 含 matched + reason.

    实现类用 frozen dataclass (跟 Action discriminated union 同 pattern) 让 metrics JSON 可
    序列化 + replay 面板可重建.
    """

    def evaluate(self, final_result: str, trace_steps: list[dict[str, Any]]) -> PredicateResult: ...


@dataclass(frozen=True, slots=True)
class SubstringPredicate:
    """V0.26.0: 主路径 — final_result 含指定 substring (case-sensitive 默认).

    强制每 task 至少 1 个 SubstringPredicate 含 task-specific token (e.g. "12.5k stars" 而非
    "成功") 防 agent done(result="任务完成") 假阳性.
    """

    substring: str
    case_insensitive: bool = False

    def evaluate(self, final_result: str, trace_steps: list[dict[str, Any]]) -> PredicateResult:
        haystack = final_result if not self.case_insensitive else final_result.lower()
        needle = self.substring if not self.case_insensitive else self.substring.lower()
        matched = needle in haystack
        return PredicateResult(
            matched=matched,
            reason=(
                f"matched substring {self.substring!r}"
                if matched
                else f"substring {self.substring!r} not in result {final_result[:120]!r}"
            ),
            name="Substring",
        )


@dataclass(frozen=True, slots=True)
class RegexPredicate:
    """V0.26.0: 中路径 — final_result 匹配指定 regex (extract action 答案验格式如
    `repo: \\w+/\\w+, stars: \\d+`).
    """

    pattern: str
    flags: int = 0

    def evaluate(self, final_result: str, trace_steps: list[dict[str, Any]]) -> PredicateResult:
        m = re.search(self.pattern, final_result, self.flags)
        return PredicateResult(
            matched=m is not None,
            reason=(
                f"regex {self.pattern!r} matched: {m.group(0)[:80]!r}"
                if m
                else f"regex {self.pattern!r} not in result {final_result[:120]!r}"
            ),
            name="Regex",
        )


@dataclass(frozen=True, slots=True)
class AllOf:
    """V0.26.0: 复合 predicate — 多个子 predicate 全过才算成功 (AND 语义).

    场景: 强制每 task 1 个 SubstringPredicate + 1-2 个 RegexPredicate 组合验.
    """

    predicates: tuple[Predicate, ...]

    def evaluate(self, final_result: str, trace_steps: list[dict[str, Any]]) -> PredicateResult:
        sub_results = [p.evaluate(final_result, trace_steps) for p in self.predicates]
        all_matched = all(r.matched for r in sub_results)
        reason = " | ".join(
            f"{r.name}: {'OK' if r.matched else 'FAIL'} ({r.reason[:80]})"
            for r in sub_results
        )
        return PredicateResult(matched=all_matched, reason=reason, name="AllOf")
