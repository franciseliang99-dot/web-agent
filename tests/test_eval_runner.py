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
