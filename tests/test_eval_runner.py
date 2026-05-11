"""V0.26.0: eval 框架骨架单测 — types/predicates/runner mock 跑示范 task.

不真 launch chromium (mock chromium_launcher); 不真调 LLM (mock LLMClient.plan 返
DoneAction). 验框架可拼: EvalTask + Predicate + run_one → TaskMetric + JSON 序列化.

V0.26.1 加真 chromium fixture eval task 后会有 opt-in slow smoke.
"""

from __future__ import annotations

from pathlib import Path
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


def test_corpus_has_20_tasks_covering_v021_v035():
    """V0.35.2: corpus 共 20 task (17 V0.32 + 3 V0.35 A capability×real-world).

    V0.35.0 +1 actuator search (wikipedia), V0.35.2 +2 (github commits click + wiki scroll).
    """
    from eval.corpus import ALL_TASKS
    assert len(ALL_TASKS) == 20
    axes = {t.capability_axis for t in ALL_TASKS}
    expected = {
        "baseline", "multi-tab", "iframe", "drag", "upload",
        "download", "dialog", "keyboard-nav", "failure-recovery",
        "real-world",  # V0.30.2 D 首次落实
    }
    missing = expected - axes
    assert not missing, f"corpus 缺 capability_axis: {missing}"
    # V0.29.4+V0.29.5 W6-C: 至少 2 chain task (CHAIN_REVEAL_2NODE + CHAIN_REFLECT_TRIGGER)
    chain_tasks = [t for t in ALL_TASKS if t.chain_spec is not None]
    assert len(chain_tasks) >= 2, "V0.29.4+V0.29.5 加 2 chain task"
    # V0.30+V0.32+V0.35 D real-world: ≥ 8 task (V0.30 3 + V0.32 2 + V0.35 3 = 8)
    real_net_tasks = [t for t in ALL_TASKS if t.requires_real_net]
    assert len(real_net_tasks) >= 8, "V0.30+V0.32+V0.35 加 ≥ 8 real-net task"


# ---------- V0.35.0 A 真站点 eval 双轴扩 fast 测 ----------


def test_v035_capability_real_world_tasks_loaded():
    """V0.35.0 + V0.35.2: A 真站点 eval 3 task 在 ALL_TASKS 内, 各 actuator 子轴 tags."""
    from eval.corpus import ALL_TASKS
    v035_tasks = [t for t in ALL_TASKS if "v035" in t.tags]
    assert len(v035_tasks) == 3, f"V0.35 加 3 task (0+2), got {len(v035_tasks)}"
    task_ids = {t.task_id for t in v035_tasks}
    assert "v035-wikipedia-search-quantum-field-theory" in task_ids  # V0.35.0 type+click
    assert "v035-github-octocat-commits-first" in task_ids  # V0.35.2 click navigation
    assert "v035-wikipedia-qft-scroll-history-section" in task_ids  # V0.35.2 scroll
    # 各 task tags 含 actuator 子轴
    sub_axes = {tag for t in v035_tasks for tag in t.tags if tag.startswith("actuator-")}
    assert sub_axes == {"actuator-search", "actuator-click-nav", "actuator-scroll"}
    # 全 requires_real_net + flaky_repeat=3
    for t in v035_tasks:
        assert t.requires_real_net is True
        assert t.flaky_repeat == 3


def test_v035_wikipedia_search_axis_real_world():
    """V0.35.0: capability_axis='real-world' (跟 V0.30/V0.32 真站点 task 同 axis, V0.35 用 tags 区分)."""
    from eval.corpus import ALL_TASKS
    v035_task = next(t for t in ALL_TASKS if t.task_id == "v035-wikipedia-search-quantum-field-theory")
    assert v035_task.capability_axis == "real-world"
    assert v035_task.fixture_url == "https://en.wikipedia.org/wiki/Main_Page"


def test_v035_wikipedia_search_predicate_token_specific():
    """V0.35.0: predicate 'Quantum field theory' 19 char ≥ 8, 不在 generic, lint pass."""
    from eval.corpus import ALL_PREDICATES, ALL_TASKS, lint_corpus_tokens
    v035_tasks = [t for t in ALL_TASKS if "v035" in t.tags]
    v035_preds = {t.task_id: ALL_PREDICATES[t.task_id] for t in v035_tasks}
    violations = lint_corpus_tokens(v035_tasks, v035_preds)
    assert violations == [], f"V0.35.0 lint failed: {violations}"


def test_v035_wikipedia_search_predicate_matches_first_para():
    """V0.35.0: predicate 真测 wikipedia QFT 首段第一句典型形式."""
    from eval.corpus import ALL_PREDICATES
    pred = ALL_PREDICATES["v035-wikipedia-search-quantum-field-theory"]
    # 真 wikipedia QFT 首段第一句典型形式 (5+ 年稳)
    sample = "Quantum field theory is the result of the combination of classical field theory."
    result = pred.evaluate(final_result=sample, trace_steps=[])
    assert result.matched


def test_v035_capability_real_world_predicates_dict_isolated():
    """V0.35.0+V0.35.2: CAPABILITY_REAL_WORLD_PREDICATES 独立 dict, 与 V0.30 REAL_WORLD_PREDICATES 不冲突."""
    from eval.corpus.v030_real_world import REAL_WORLD_PREDICATES
    from eval.corpus.v035_capability_real_world import CAPABILITY_REAL_WORLD_PREDICATES
    overlap = set(REAL_WORLD_PREDICATES) & set(CAPABILITY_REAL_WORLD_PREDICATES)
    assert not overlap, f"V0.35 task_id 与 V0.30 重 ({overlap})"
    assert len(CAPABILITY_REAL_WORLD_PREDICATES) == 3  # V0.35.0 1 + V0.35.2 2


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


# ---------- V0.30.1 D real-world: vcr config + flaky_repeat + EvalTask field ----------


def test_eval_task_requires_real_net_field_default_false():
    """V0.30.1: EvalTask requires_real_net 默 False (老 task 兼容)."""
    from eval.types import EvalTask

    t = EvalTask(
        task_id="t", goal="g", fixture_url="data:text/html,<h1>x</h1>",
        capability_axis="baseline", expected_step_range=(1, 3),
    )
    assert t.requires_real_net is False
    assert t.flaky_repeat == 1


def test_get_eval_vcr_config_filters_llm_keys():
    """V0.30.1: _get_eval_vcr_config 含 11 项 LLM key redact (跟 conftest vcr_config 对齐)."""
    from eval.runner import _get_eval_vcr_config

    cfg = _get_eval_vcr_config()
    assert "filter_headers" in cfg
    headers_filtered = {h[0] for h in cfg["filter_headers"]}
    assert "authorization" in headers_filtered
    assert "x-api-key" in headers_filtered
    assert "anthropic-version" in headers_filtered
    assert "openai-organization" in headers_filtered
    # stainless metadata
    assert any("stainless" in h for h in headers_filtered)
    # query param
    assert ("api_key", "REDACTED") in cfg["filter_query_parameters"]
    assert cfg["record_mode"] == "once"


def test_filter_requires_real_net_skips_when_no_live_net_env(monkeypatch):
    """V0.30.1: WEB_AGENT_EVAL_LIVE_NET 未设 → requires_real_net=True task 默跳."""
    from eval.cli import _filter_requires_real_net
    from eval.types import EvalTask

    monkeypatch.delenv("WEB_AGENT_EVAL_LIVE_NET", raising=False)
    tasks = [
        EvalTask(task_id="t1", goal="g", fixture_url="d:,",
                 capability_axis="baseline", expected_step_range=(1, 3),
                 requires_real_net=False),
        EvalTask(task_id="t2", goal="g", fixture_url="d:,",
                 capability_axis="real-world", expected_step_range=(1, 3),
                 requires_real_net=True),
    ]
    out = _filter_requires_real_net(tasks)
    assert len(out) == 1
    assert out[0].task_id == "t1"


def test_filter_requires_real_net_passes_when_live_net_env_set(monkeypatch):
    """V0.30.1: WEB_AGENT_EVAL_LIVE_NET=1 → requires_real_net=True task 放行不滤."""
    from eval.cli import _filter_requires_real_net
    from eval.types import EvalTask

    monkeypatch.setenv("WEB_AGENT_EVAL_LIVE_NET", "1")
    tasks = [
        EvalTask(task_id="t2", goal="g", fixture_url="d:,",
                 capability_axis="real-world", expected_step_range=(1, 3),
                 requires_real_net=True),
    ]
    out = _filter_requires_real_net(tasks)
    assert len(out) == 1
    assert out[0].task_id == "t2"


def test_metric_to_dict_includes_flaky_repeat_idx():
    """V0.30.1: metric_to_dict 加 flaky_repeat_idx 字段 (默 0)."""
    from eval.predicates import PredicateResult
    from eval.runner import TaskMetric, metric_to_dict

    m = TaskMetric(
        task_id="t", provider="anthropic", run_id="r",
        pass_=True, failure_bucket="OK", steps=1, wallclock_s=1.0,
        web_agent_task_id="x", final_result="r",
        predicate_result=PredicateResult(matched=True, reason="r", name="N"),
        flaky_repeat_idx=2,
    )
    assert metric_to_dict(m)["flaky_repeat_idx"] == 2
    # default
    m2 = TaskMetric(
        task_id="t", provider="a", run_id="r",
        pass_=True, failure_bucket="OK", steps=1, wallclock_s=1.0,
        web_agent_task_id="x", final_result="r",
        predicate_result=PredicateResult(matched=True, reason="r", name="N"),
    )
    assert metric_to_dict(m2)["flaky_repeat_idx"] == 0


async def test_run_corpus_flaky_reflect_mutex_assert():
    """V0.30.1: flaky_repeat>1 + reflect=True 互斥, 早 RuntimeError 不跑 (subagent D 决)."""
    from unittest.mock import MagicMock
    from eval.runner import run_corpus
    from eval.types import EvalTask

    task = EvalTask(
        task_id="t-flaky", goal="g", fixture_url="d:,",
        capability_axis="baseline", expected_step_range=(1, 3),
        flaky_repeat=3,
    )
    fake_chromium = MagicMock()
    with pytest.raises(RuntimeError, match="flaky_repeat=3 跟 reflect=True 互斥"):
        await run_corpus(
            [task], [], {},
            db_path=Path("/tmp/dummy.db"), screenshots_dir=Path("/tmp/dummy"),
            chromium_launcher=fake_chromium,
            reflect=True, memory_db_path=Path("/tmp/dummy_mem.db"),
        )


async def test_run_corpus_chain_flaky_repeat_mutex_assert():
    """V0.30.1: chain task + flaky_repeat>1 互斥 (chain 内 node-level retry 已存外层冗余)."""
    from unittest.mock import MagicMock
    from eval.runner import run_corpus
    from eval.types import EvalTask
    from web_agent.chain import ChainNode, ChainSpec

    task = EvalTask(
        task_id="t-chain-flaky", goal="g", fixture_url="d:,",
        capability_axis="baseline", expected_step_range=(1, 3),
        chain_spec=ChainSpec(nodes=(ChainNode(id="a", goal="g"),)),
        flaky_repeat=2,
    )
    fake_chromium = MagicMock()
    with pytest.raises(RuntimeError, match=r"chain task.*flaky_repeat=2.*禁用"):
        await run_corpus(
            [task], [], {},
            db_path=Path("/tmp/dummy.db"), screenshots_dir=Path("/tmp/dummy"),
            chromium_launcher=fake_chromium,
        )


# ---------- V0.30.2 D real-world: wikipedia corpus task ----------


def test_wikipedia_quantum_corpus_task_loaded():
    """V0.30.2: eval.corpus 含 WIKIPEDIA_QUANTUM_FIRST_PARA + requires_real_net=True + flaky_repeat=3."""
    from eval.corpus import ALL_PREDICATES
    from eval.corpus.v030_real_world import WIKIPEDIA_QUANTUM_FIRST_PARA

    assert WIKIPEDIA_QUANTUM_FIRST_PARA.requires_real_net is True
    assert WIKIPEDIA_QUANTUM_FIRST_PARA.flaky_repeat == 3
    assert WIKIPEDIA_QUANTUM_FIRST_PARA.capability_axis == "real-world"
    assert WIKIPEDIA_QUANTUM_FIRST_PARA.fixture_url.startswith("https://en.wikipedia.org/wiki/")
    assert WIKIPEDIA_QUANTUM_FIRST_PARA.task_id in ALL_PREDICATES


def test_wikipedia_corpus_filtered_when_no_live_net_env(monkeypatch):
    """V0.30.2: WEB_AGENT_EVAL_LIVE_NET 未设 → wikipedia task 默被 _filter_requires_real_net 跳."""
    from eval.cli import _filter_requires_real_net
    from eval.corpus import ALL_TASKS

    monkeypatch.delenv("WEB_AGENT_EVAL_LIVE_NET", raising=False)
    out = _filter_requires_real_net(list(ALL_TASKS))
    out_ids = {t.task_id for t in out}
    assert "v030-wikipedia-quantum-entanglement" not in out_ids, (
        "V0.30.2 wikipedia task 默应被 LIVE_NET filter 跳"
    )


# ---------- V0.30.3 D real-world: vcr 真接 (修 #11 silent bug) ----------


def test_get_eval_vcr_config_record_mode_param():
    """V0.30.3: _get_eval_vcr_config 接 record_mode kwarg + 默 'once'."""
    from eval.runner import _get_eval_vcr_config

    cfg_default = _get_eval_vcr_config()
    assert cfg_default["record_mode"] == "once"

    cfg_strict = _get_eval_vcr_config(record_mode="none")
    assert cfg_strict["record_mode"] == "none"


def test_get_eval_vcr_config_allows_playback_repeats():
    """V0.30.3 R4 修: allow_playback_repeats=True 让 flaky_repeat=N 复用同 cassette N 次."""
    from eval.runner import _get_eval_vcr_config

    cfg = _get_eval_vcr_config()
    assert cfg["allow_playback_repeats"] is True


def test_resolve_cassette_path_per_provider():
    """V0.30.3: cassette path = eval/cassettes/real_world/{task_id}_{provider}.yaml (per-provider)."""
    from eval.runner import _resolve_cassette_path
    from eval.types import EvalTask

    t = EvalTask(
        task_id="v030-test", goal="g", fixture_url="https://x.test/",
        capability_axis="real-world", expected_step_range=(1, 3),
        requires_real_net=True,
    )
    p_anthropic = _resolve_cassette_path(t, "anthropic")
    p_openai = _resolve_cassette_path(t, "openai")
    assert p_anthropic.name == "v030-test_anthropic.yaml"
    assert p_openai.name == "v030-test_openai.yaml"
    assert "cassettes/real_world" in str(p_anthropic)


def test_resolve_record_mode_strict_replay_default(monkeypatch):
    """V0.30.3: env 未设 → 'none' (严回放, cassette 缺则 raise)."""
    from eval.runner import _resolve_record_mode

    monkeypatch.delenv("WEB_AGENT_EVAL_REAL", raising=False)
    monkeypatch.delenv("WEB_AGENT_EVAL_LIVE_NET", raising=False)
    assert _resolve_record_mode() == "none"


def test_resolve_record_mode_once_when_both_env_set(monkeypatch):
    """V0.30.3: EVAL_REAL=1 + EVAL_LIVE_NET=1 → 'once' (真录)."""
    from eval.runner import _resolve_record_mode

    monkeypatch.setenv("WEB_AGENT_EVAL_REAL", "1")
    monkeypatch.setenv("WEB_AGENT_EVAL_LIVE_NET", "1")
    assert _resolve_record_mode() == "once"


def test_resolve_record_mode_strict_when_only_one_env_set(monkeypatch):
    """V0.30.3: 只 EVAL_REAL 或只 LIVE_NET 设 → 'none' (双 env 必须一起设才录)."""
    from eval.runner import _resolve_record_mode

    monkeypatch.setenv("WEB_AGENT_EVAL_REAL", "1")
    monkeypatch.delenv("WEB_AGENT_EVAL_LIVE_NET", raising=False)
    assert _resolve_record_mode() == "none"

    monkeypatch.delenv("WEB_AGENT_EVAL_REAL", raising=False)
    monkeypatch.setenv("WEB_AGENT_EVAL_LIVE_NET", "1")
    assert _resolve_record_mode() == "none"


# ---------- V0.30.4 D real-world: +2 tasks loaded + cli double-env assert ----------


def test_v030_apple_inc_task_loaded():
    """V0.30.4: WIKIPEDIA_APPLE_INC + requires_real_net=True + flaky_repeat=3 + predicate Cupertino."""
    from eval.corpus import ALL_PREDICATES
    from eval.corpus.v030_real_world import WIKIPEDIA_APPLE_INC

    assert WIKIPEDIA_APPLE_INC.requires_real_net is True
    assert WIKIPEDIA_APPLE_INC.flaky_repeat == 3
    assert WIKIPEDIA_APPLE_INC.capability_axis == "real-world"
    assert "Apple_Inc" in WIKIPEDIA_APPLE_INC.fixture_url
    assert WIKIPEDIA_APPLE_INC.task_id in ALL_PREDICATES


def test_v030_github_octocat_task_loaded():
    """V0.30.4: GITHUB_OCTOCAT_README + requires_real_net=True + max_steps=10 (web UI 重)."""
    from eval.corpus import ALL_PREDICATES
    from eval.corpus.v030_real_world import GITHUB_OCTOCAT_README

    assert GITHUB_OCTOCAT_README.requires_real_net is True
    assert GITHUB_OCTOCAT_README.flaky_repeat == 3
    assert GITHUB_OCTOCAT_README.capability_axis == "real-world"
    assert "github.com/octocat/Hello-World" in GITHUB_OCTOCAT_README.fixture_url
    assert GITHUB_OCTOCAT_README.max_steps == 10  # 比 wiki 大 (web UI JS bundle)
    assert GITHUB_OCTOCAT_README.task_id in ALL_PREDICATES


def test_v030_real_world_tasks_pass_lint_corpus_tokens():
    """V0.30.4: 新 token (Cupertino + 'My first repository') 不违 lint_corpus_tokens 规则."""
    from eval.corpus import ALL_PREDICATES, ALL_TASKS, lint_corpus_tokens

    violations = lint_corpus_tokens(ALL_TASKS, ALL_PREDICATES)
    assert violations == [], f"V0.30.4 corpus lint 违: {violations}"


# ---------- V0.30.4 cli double-env assert (subagent V0.30.3 R3 收) ----------


def test_assert_live_net_consistency_real_real_no_live_with_real_task_exits(monkeypatch):
    """V0.30.4 R3: EVAL_REAL=1 + tasks 含 requires_real_net=True 但 LIVE_NET 未设 → SystemExit."""
    from eval.cli import _assert_live_net_consistency
    from eval.types import EvalTask

    monkeypatch.setenv("WEB_AGENT_EVAL_REAL", "1")
    monkeypatch.delenv("WEB_AGENT_EVAL_LIVE_NET", raising=False)
    real_task = EvalTask(
        task_id="t-real", goal="g", fixture_url="https://x.test/",
        capability_axis="real-world", expected_step_range=(1, 3),
        requires_real_net=True,
    )
    with pytest.raises(SystemExit):
        _assert_live_net_consistency([real_task])


def test_assert_live_net_consistency_both_env_set_passes(monkeypatch):
    """V0.30.4 R3: EVAL_REAL=1 + LIVE_NET=1 + real-net task → 不 raise."""
    from eval.cli import _assert_live_net_consistency
    from eval.types import EvalTask

    monkeypatch.setenv("WEB_AGENT_EVAL_REAL", "1")
    monkeypatch.setenv("WEB_AGENT_EVAL_LIVE_NET", "1")
    real_task = EvalTask(
        task_id="t-real", goal="g", fixture_url="https://x.test/",
        capability_axis="real-world", expected_step_range=(1, 3),
        requires_real_net=True,
    )
    _assert_live_net_consistency([real_task])  # 不 raise


def test_assert_live_net_consistency_no_real_net_tasks_passes(monkeypatch):
    """V0.30.4 R3: EVAL_REAL=1 + LIVE_NET=0 + 无 real-net task → 不 raise (老 corpus)."""
    from eval.cli import _assert_live_net_consistency
    from eval.types import EvalTask

    monkeypatch.setenv("WEB_AGENT_EVAL_REAL", "1")
    monkeypatch.delenv("WEB_AGENT_EVAL_LIVE_NET", raising=False)
    fake_task = EvalTask(
        task_id="t1", goal="g", fixture_url="data:text/html,",
        capability_axis="baseline", expected_step_range=(1, 3),
        requires_real_net=False,  # 老 task
    )
    _assert_live_net_consistency([fake_task])  # 不 raise


def test_assert_live_net_consistency_no_eval_real_passes(monkeypatch):
    """V0.30.4 R3: EVAL_REAL 未设 (cassette replay) + real-net task → 不 raise (cassette 模式无需 LIVE_NET)."""
    from eval.cli import _assert_live_net_consistency
    from eval.types import EvalTask

    monkeypatch.delenv("WEB_AGENT_EVAL_REAL", raising=False)
    monkeypatch.delenv("WEB_AGENT_EVAL_LIVE_NET", raising=False)
    real_task = EvalTask(
        task_id="t-real", goal="g", fixture_url="https://x.test/",
        capability_axis="real-world", expected_step_range=(1, 3),
        requires_real_net=True,
    )
    _assert_live_net_consistency([real_task])  # 不 raise (cassette 严回放路径)


# ---------- V0.32.0 D' chain × real-world: GitHub topic → README ----------


def test_v032_github_topic_chain_task_loaded():
    """V0.32.0: GITHUB_TOPIC_PYTHON_FIRST_README chain × real-world 双标 task loaded."""
    from eval.corpus import ALL_PREDICATES
    from eval.corpus.v032_chain_real_world import GITHUB_TOPIC_PYTHON_FIRST_README

    t = GITHUB_TOPIC_PYTHON_FIRST_README
    assert t.requires_real_net is True
    assert t.flaky_repeat == 1  # V0.30.3 chain × flaky 互斥
    assert t.capability_axis == "real-world"
    assert t.chain_spec is not None  # 双标
    assert len(t.chain_spec.nodes) == 2
    assert t.chain_spec.nodes[0].id == "a"
    assert t.chain_spec.nodes[1].id == "b"
    assert t.chain_spec.nodes[1].depends_on == ("a",)
    assert "github.com/topics/python" in t.fixture_url
    assert t.task_id in ALL_PREDICATES
    # max_steps=12 / max_wallclock=180 (GitHub UI banner buffer, V0.30.4 octocat 同 risk)
    assert t.max_steps == 12
    assert t.max_wallclock_s == 180.0


def test_v032_chain_real_world_double_axis_filter_match():
    """V0.32.0: real-world axis filter 含 chain task (real-world ∩ chain_spec≠None 双标命中)."""
    from eval.cli import _select_tasks

    real_world = _select_tasks("real-world")
    chain_real_world = [t for t in real_world if t.chain_spec is not None]
    assert any(t.task_id == "v032-github-topic-python-first-readme" for t in chain_real_world)


def test_v032_chain_real_world_predicate_lenient_substring():
    """V0.32.0: predicate 'programming language' (20 char + 抗 GitHub topic 月度第一名 repo 漂 +
    Python topic 任何 repo README/about 几乎必含 universal description)."""
    from eval.corpus import ALL_PREDICATES
    from eval.predicates import SubstringPredicate

    pred = ALL_PREDICATES["v032-github-topic-python-first-readme"]
    assert isinstance(pred, SubstringPredicate)
    assert pred.substring == "programming language"


# ---------- V0.32.2 D' chain × real-world (Wikipedia cross-ref 非 GitHub 域) ----------


def test_v032_wikipedia_apple_to_cupertino_chain_loaded():
    """V0.32.2: WIKIPEDIA_APPLE_TO_CUPERTINO_CHAIN 双标 task loaded (real-world axis + chain_spec)."""
    from eval.corpus import ALL_PREDICATES
    from eval.corpus.v032_chain_real_world import WIKIPEDIA_APPLE_TO_CUPERTINO_CHAIN

    t = WIKIPEDIA_APPLE_TO_CUPERTINO_CHAIN
    assert t.requires_real_net is True
    assert t.flaky_repeat == 1
    assert t.capability_axis == "real-world"
    assert t.chain_spec is not None
    assert len(t.chain_spec.nodes) == 2
    assert t.chain_spec.nodes[1].depends_on == ("a",)
    assert "Apple_Inc" in t.fixture_url  # 复用 V0.30.4 WIKIPEDIA_APPLE_INC fixture URL
    assert t.task_id in ALL_PREDICATES
    # wiki 比 GitHub 轻: max_steps=10 < V0.32.0 12, max_wallclock=120 < V0.32.0 180
    assert t.max_steps == 10
    assert t.max_wallclock_s == 120.0


def test_v032_wikipedia_chain_axis_filter_includes_two_chain_real_world():
    """V0.32.2: --corpus real-world 含 V0.32.0 GitHub + V0.32.2 wiki cross-ref 共 2 chain real-world."""
    from eval.cli import _select_tasks

    real_world = _select_tasks("real-world")
    chain_real_world = [t for t in real_world if t.chain_spec is not None]
    chain_ids = {t.task_id for t in chain_real_world}
    assert "v032-github-topic-python-first-readme" in chain_ids
    assert "v032-wikipedia-apple-to-cupertino-chain" in chain_ids
    assert len(chain_real_world) == 2  # V0.32.0 + V0.32.2


def test_v032_wikipedia_chain_predicate_santa_clara_county():
    """V0.32.2: predicate 'Santa Clara County' 18 char (subagent B 决: 抗 wiki 城市 page 行政信息漂,
    比 'California' 通用度低不假阳性, 比 'Cupertino' 不撞 page H1 自我断言)."""
    from eval.corpus import ALL_PREDICATES
    from eval.predicates import SubstringPredicate

    pred = ALL_PREDICATES["v032-wikipedia-apple-to-cupertino-chain"]
    assert isinstance(pred, SubstringPredicate)
    assert pred.substring == "Santa Clara County"
