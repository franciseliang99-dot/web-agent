"""V0.26.0: eval 框架骨架单测 — types/predicates/runner mock 跑示范 task.

不真 launch chromium (mock chromium_launcher); 不真调 LLM (mock LLMClient.plan 返
DoneAction). 验框架可拼: EvalTask + Predicate + run_one → TaskMetric + JSON 序列化.

V0.26.1 加真 chromium fixture eval task 后会有 opt-in slow smoke.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from eval.predicates import (
    AllOf,
    PredicateResult,
    RegexPredicate,
    SubstringPredicate,
)
from eval.runner import _classify_failure_bucket, metric_to_dict
from eval.types import EvalTask


# --- predicates 纯函数 ---


def test_substring_predicate_matched():
    p = SubstringPredicate(substring="量子纠缠")
    r = p.evaluate("结果: 量子纠缠是粒子关联", [])
    assert r.matched is True
    assert "matched substring" in r.reason
    assert r.name == "Substring"


def test_substring_predicate_not_matched():
    p = SubstringPredicate(substring="量子纠缠")
    r = p.evaluate("hello world", [])
    assert r.matched is False
    assert "not in result" in r.reason


def test_substring_predicate_case_insensitive():
    p = SubstringPredicate(substring="QUANTUM", case_insensitive=True)
    assert p.evaluate("quantum entanglement", []).matched is True
    p2 = SubstringPredicate(substring="QUANTUM", case_insensitive=False)
    assert p2.evaluate("quantum entanglement", []).matched is False


def test_regex_predicate_matched():
    p = RegexPredicate(pattern=r"stars: \d+")
    r = p.evaluate("repo: foo/bar, stars: 12500", [])
    assert r.matched is True
    assert r.name == "Regex"


def test_regex_predicate_not_matched():
    p = RegexPredicate(pattern=r"stars: \d+")
    r = p.evaluate("no numbers here", [])
    assert r.matched is False


def test_allof_predicate_all_pass():
    p = AllOf(predicates=(
        SubstringPredicate(substring="stars"),
        RegexPredicate(pattern=r"\d+"),
    ))
    r = p.evaluate("stars: 12500", [])
    assert r.matched is True
    assert "Substring: OK" in r.reason
    assert "Regex: OK" in r.reason


def test_allof_predicate_one_fails():
    p = AllOf(predicates=(
        SubstringPredicate(substring="stars"),
        RegexPredicate(pattern=r"\d+"),
    ))
    r = p.evaluate("stars: many", [])  # 字面 stars 在但无 \d+
    assert r.matched is False
    assert "Regex: FAIL" in r.reason


# --- types 兼容 ---


def test_eval_task_construct_minimal():
    task = EvalTask(
        task_id="x", goal="g", fixture_url="data:text/html,",
        capability_axis="baseline", expected_step_range=(1, 3),
    )
    assert task.task_id == "x"
    assert task.max_steps == 10  # default
    assert task.tags == ()


def test_eval_task_frozen():
    task = EvalTask(
        task_id="x", goal="g", fixture_url="u",
        capability_axis="baseline", expected_step_range=(1, 3),
    )
    with pytest.raises(AttributeError):
        task.task_id = "y"  # type: ignore[misc]


def test_eval_task_capability_axis_includes_v021_v025_axes():
    """V0.26.0: CapabilityAxis Literal 至少含 V0.21-V0.25 9 个能力 + baseline + real-world."""
    from typing import get_args
    from eval.types import CapabilityAxis
    axes = set(get_args(CapabilityAxis))
    expected = {
        "multi-tab", "iframe", "drag", "upload", "download",
        "dialog", "retry", "backtrack", "keyboard-nav", "failure-recovery",
        "real-world", "baseline",
    }
    missing = expected - axes
    assert not missing, f"V0.26.0: CapabilityAxis 缺 {missing}"


# --- failure_bucket 分类 ---


def test_classify_bucket_ok_when_predicate_matched():
    pr = PredicateResult(matched=True, reason="x", name="Substring")
    assert _classify_failure_bucket(pr, "anything") == "OK"


def test_classify_bucket_loop_sentinel_takes_precedence():
    pr = PredicateResult(matched=False, reason="x", name="Substring")
    assert _classify_failure_bucket(pr, "LLM_FAILED at step 3") == "LLM_FAILED"
    assert _classify_failure_bucket(pr, "WALLCLOCK_EXCEEDED at step 5") == "WALLCLOCK_EXCEEDED"
    assert _classify_failure_bucket(pr, "SAFETY_BLOCK at step 0") == "SAFETY_BLOCK"
    assert _classify_failure_bucket(pr, "LOOP_DETECTED 在 step 4") == "LOOP_DETECTED"


def test_classify_bucket_predicate_fail_when_loop_complete():
    pr = PredicateResult(matched=False, reason="not found", name="Substring")
    assert _classify_failure_bucket(pr, "agent done: 完成了") == "PREDICATE_FAIL"


def test_classify_bucket_max_steps_exhausted():
    pr = PredicateResult(matched=False, reason="x", name="Substring")
    assert _classify_failure_bucket(pr, "(max_steps 耗尽未完成)") == "(max_steps"


# --- metric_to_dict 序列化 ---


def test_metric_to_dict_writes_pass_key_not_pass_underscore():
    """V0.26.0: TaskMetric.pass_ → JSON 'pass' key (Python 关键字冲突 dataclass 加 _)."""
    from eval.runner import TaskMetric
    m = TaskMetric(
        task_id="t", provider="anthropic", run_id="r",
        pass_=True, failure_bucket="OK", steps=5, wallclock_s=1.234,
        web_agent_task_id="abc123", final_result="x",
        predicate_result=PredicateResult(matched=True, reason="ok", name="Substring"),
    )
    d = metric_to_dict(m)
    assert d["pass"] is True
    assert "pass_" not in d
    assert d["wallclock_s"] == 1.23  # 2 位小数
    assert d["predicate_result"] == {"matched": True, "reason": "ok", "name": "Substring"}


# --- run_one 集成 (mock chromium_launcher + LLMClient + run_react_loop) ---


# --- V0.26.1: TraceContainsAction / TraceObsContains predicates ---


def test_trace_contains_action_matched():
    from eval.predicates import TraceContainsAction
    p = TraceContainsAction(action_type="click", min_count=2)
    trace = [
        {"step": 0, "action_type": "click", "action_args": {}, "observation": "x"},
        {"step": 1, "action_type": "type", "action_args": {}, "observation": "y"},
        {"step": 2, "action_type": "click", "action_args": {}, "observation": "z"},
    ]
    r = p.evaluate("ok", trace)
    assert r.matched is True
    assert "2 次" in r.reason
    assert r.name == "TraceContainsAction"


def test_trace_contains_action_not_matched():
    from eval.predicates import TraceContainsAction
    p = TraceContainsAction(action_type="upload", min_count=1)
    trace = [{"step": 0, "action_type": "click", "action_args": {}, "observation": ""}]
    r = p.evaluate("ok", trace)
    assert r.matched is False


def test_trace_obs_contains_matched():
    from eval.predicates import TraceObsContains
    p = TraceObsContains(substring="downloaded:")
    trace = [
        {"step": 0, "action_type": "click", "action_args": {}, "observation": "clicked button"},
        {"step": 1, "action_type": "click", "action_args": {}, "observation": "downloaded: report.pdf"},
    ]
    r = p.evaluate("ok", trace)
    assert r.matched is True
    assert "step 1" in r.reason


def test_trace_obs_contains_not_matched_hints_v024_helper():
    """V0.26.1: TraceObsContains 失败 reason 提示检查 V0.24.1 helper drain — 防 corpus 演化时静默漏."""
    from eval.predicates import TraceObsContains
    p = TraceObsContains(substring="dialog confirm:")
    trace = [{"step": 0, "action_type": "click", "action_args": {}, "observation": "x"}]
    r = p.evaluate("ok", trace)
    assert r.matched is False
    assert "V0.24.1" in r.reason  # 防漏 drain 的 hint


# --- V0.26.1 corpus 完整性 + token-specific lint ---


def test_corpus_has_12_tasks_covering_v021_v029():
    """V0.26.1+V0.29.4+V0.29.5: corpus 共 12 task (V0.26.1 10 + V0.29.4 1 chain + V0.29.5 1 chain reflect).
    drop retry/backtrack 推迟 V0.26.3."""
    from eval.corpus import ALL_TASKS
    assert len(ALL_TASKS) == 12
    axes = {t.capability_axis for t in ALL_TASKS}
    expected = {
        "baseline", "multi-tab", "iframe", "drag", "upload",
        "download", "dialog", "keyboard-nav", "failure-recovery",
    }
    missing = expected - axes
    assert not missing, f"corpus 缺 capability_axis: {missing}"
    # V0.29.4+V0.29.5 W6-C: 至少 2 chain task (CHAIN_REVEAL_2NODE + CHAIN_REFLECT_TRIGGER)
    chain_tasks = [t for t in ALL_TASKS if t.chain_spec is not None]
    assert len(chain_tasks) >= 2, "V0.29.4+V0.29.5 加 2 chain task"


def test_all_tasks_have_predicate_binding():
    """V0.26.1: 每 task 必绑 1 个 predicate (lint_corpus_tokens 也验, 但显式测)."""
    from eval.corpus import ALL_PREDICATES, ALL_TASKS
    for t in ALL_TASKS:
        assert t.task_id in ALL_PREDICATES, f"task {t.task_id} 缺 predicate 绑定"


def test_lint_corpus_tokens_all_pass():
    """V0.26.1: 所有 SubstringPredicate token 长度 ≥ 8 + 不在通用词集 (B7 强制 task-specific)."""
    from eval.corpus import ALL_PREDICATES, ALL_TASKS, lint_corpus_tokens
    violations = lint_corpus_tokens(ALL_TASKS, ALL_PREDICATES)
    assert violations == [], f"V0.26.1 token-specific lint failed: {violations}"


def test_lint_corpus_tokens_catches_short_token():
    """V0.26.1 lint 真能拦短 token (假阳性风险)."""
    from eval.corpus import lint_corpus_tokens
    from eval.predicates import SubstringPredicate
    from eval.types import EvalTask
    task = EvalTask(task_id="bad-1", goal="x", fixture_url="data:text/html,",
                    capability_axis="baseline", expected_step_range=(1, 3))
    pred = SubstringPredicate(substring="ok")  # 长度 2 < 8
    violations = lint_corpus_tokens([task], {task.task_id: pred})
    assert any("长度 < 8" in v for v in violations)


def test_lint_corpus_tokens_catches_generic_word():
    """V0.26.1 lint 拦通用词 'done' (即便长度 ≥ 8 也要拦, 但 done 长度 4 也拦短)."""
    from eval.corpus import lint_corpus_tokens
    from eval.predicates import SubstringPredicate
    from eval.types import EvalTask
    task = EvalTask(task_id="bad-2", goal="x", fixture_url="data:text/html,",
                    capability_axis="baseline", expected_step_range=(1, 3))
    pred = SubstringPredicate(substring="completed")  # 长度 9 ≥ 8 但在 _GENERIC_WORDS
    violations = lint_corpus_tokens([task], {task.task_id: pred})
    assert any("通用词集" in v for v in violations)


def test_lint_walks_allof_recursively():
    """V0.26.1: AllOf 嵌套 SubstringPredicate 也要 lint (防 AllOf 内塞水货 token 蒙混)."""
    from eval.corpus import lint_corpus_tokens
    from eval.predicates import AllOf, RegexPredicate, SubstringPredicate
    from eval.types import EvalTask
    task = EvalTask(task_id="bad-3", goal="x", fixture_url="data:text/html,",
                    capability_axis="baseline", expected_step_range=(1, 3))
    pred = AllOf(predicates=(
        SubstringPredicate(substring="long-enough-token-123"),
        SubstringPredicate(substring="ok"),  # 嵌套水货
        RegexPredicate(pattern=".*"),
    ))
    violations = lint_corpus_tokens([task], {task.task_id: pred})
    assert any("长度 < 8" in v for v in violations)


async def test_run_one_infra_error_returns_metric(monkeypatch):
    """V0.26.0: chromium.launch 抛 → TaskMetric.failure_bucket='EVAL_INFRA_ERROR', 不传染异常."""
    from eval.runner import run_one

    chromium = MagicMock()
    chromium.launch = AsyncMock(side_effect=RuntimeError("chromium binary missing"))

    task = EvalTask(
        task_id="t", goal="g", fixture_url="data:text/html,<html></html>",
        capability_axis="baseline", expected_step_range=(1, 3),
    )
    pred = SubstringPredicate(substring="x")
    client = MagicMock()
    client.name = "fake"

    metric = await run_one(
        task, client, pred,
        db_path=monkeypatch.tmp if hasattr(monkeypatch, "tmp") else __import__("pathlib").Path("/tmp/v0260_eval_test.db"),
        screenshots_dir=__import__("pathlib").Path("/tmp/v0260_eval_test_shots"),
        chromium_launcher=chromium,
    )
    assert metric.pass_ is False
    assert metric.failure_bucket == "EVAL_INFRA_ERROR"
    assert "chromium binary missing" in metric.final_result


# ---------- V0.29.4 W6-C: chain task dispatch + TaskMetric 字段 ----------


def test_eval_task_chain_spec_field_default_none():
    """V0.29.4: EvalTask 默 chain_spec=None (backward-compat, 老 task 不动)."""
    from eval.types import EvalTask

    t = EvalTask(
        task_id="t", goal="g", fixture_url="data:text/html,<h1>x</h1>",
        capability_axis="baseline", expected_step_range=(1, 3),
    )
    assert t.chain_spec is None


def test_task_metric_chain_node_pass_rate_default_none():
    """V0.29.4: TaskMetric 默 chain_node_pass_rate=None (非 chain task)."""
    from eval.predicates import PredicateResult
    from eval.runner import TaskMetric

    m = TaskMetric(
        task_id="t", provider="anthropic", run_id="r",
        pass_=True, failure_bucket="OK",
        steps=1, wallclock_s=1.0, web_agent_task_id="x",
        final_result="r",
        predicate_result=PredicateResult(matched=True, reason="r", name="N"),
    )
    assert m.chain_node_pass_rate is None


def test_metric_to_dict_includes_chain_node_pass_rate():
    """V0.29.4: metric_to_dict 加 chain_node_pass_rate 字段 (默 None 序列化为 null)."""
    from eval.predicates import PredicateResult
    from eval.runner import TaskMetric, metric_to_dict

    m = TaskMetric(
        task_id="t", provider="anthropic", run_id="r",
        pass_=True, failure_bucket="OK",
        steps=1, wallclock_s=1.0, web_agent_task_id="x",
        final_result="r",
        predicate_result=PredicateResult(matched=True, reason="r", name="N"),
        chain_node_pass_rate=0.5,
    )
    d = metric_to_dict(m)
    assert d["chain_node_pass_rate"] == 0.5
    # default None task
    m2 = TaskMetric(
        task_id="t2", provider="a", run_id="r",
        pass_=True, failure_bucket="OK", steps=1, wallclock_s=1.0,
        web_agent_task_id="x", final_result="r",
        predicate_result=PredicateResult(matched=True, reason="r", name="N"),
    )
    assert metric_to_dict(m2)["chain_node_pass_rate"] is None


def test_chain_corpus_task_loaded_with_chain_spec():
    """V0.29.4: eval.corpus.v029_chain.CHAIN_REVEAL_2NODE 含 chain_spec 2 node + predicate 绑."""
    from eval.corpus import ALL_PREDICATES
    from eval.corpus.v029_chain import CHAIN_REVEAL_2NODE

    assert CHAIN_REVEAL_2NODE.chain_spec is not None
    assert len(CHAIN_REVEAL_2NODE.chain_spec.nodes) == 2
    assert CHAIN_REVEAL_2NODE.chain_spec.nodes[0].id == "a"
    assert CHAIN_REVEAL_2NODE.chain_spec.nodes[1].id == "b"
    assert CHAIN_REVEAL_2NODE.chain_spec.nodes[1].depends_on == ("a",)
    # predicate 绑入 ALL_PREDICATES
    assert CHAIN_REVEAL_2NODE.task_id in ALL_PREDICATES
