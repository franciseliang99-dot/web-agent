"""V0.28.3 W6 收尾: eval --reflect 2-pass + reflective_uplift metric 单测.

测覆盖 4 层 (subagent 推):
1. compute_reflective_uplift per_task / per_axis / overall + reflections_written 计数
2. compute_reflective_uplift 缺配对 / 全 0 配对边界
3. render_reflective_uplift_markdown 含 overall + axis + per_task + reflections_written
4. render_reflective_uplift_markdown 空 metrics → "(no reflective data)"

不真跑 chromium (subagent F 决: 真跑推迟 V0.27.0 cross-provider baseline 一并). FakeLLMClient
+ chromium_launcher mock 路径已在 test_eval_runner.py 模板, 本 module 测 metrics/render 纯逻辑足.
"""

from __future__ import annotations

from typing import cast

import pytest

from eval.metrics import ReflectiveUpliftReport, compute_reflective_uplift
from eval.predicates import PredicateResult
from eval.report import render_reflective_uplift_markdown
from eval.runner import CorpusReport, TaskMetric
from eval.types import CapabilityAxis, EvalTask


def _mk_metric(
    task_id: str,
    provider: str,
    pass_: bool,
    inject_reflections: bool,
    failure_bucket: str = "PREDICATE_FAIL",
) -> TaskMetric:
    """V0.28.3 测 helper: 构 TaskMetric 默 0 token cost / 跳预测细节."""
    return TaskMetric(
        task_id=task_id, provider=provider, run_id="r", pass_=pass_,
        failure_bucket="OK" if pass_ else failure_bucket,
        steps=1, wallclock_s=1.0, web_agent_task_id="x", final_result="r",
        predicate_result=PredicateResult(matched=pass_, reason="r", name="N"),
        inject_reflections=inject_reflections,
    )


def _mk_task(task_id: str, axis: CapabilityAxis) -> EvalTask:
    """V0.28.3 测 helper: 构 EvalTask 默 fixture 跳运行细节."""
    return EvalTask(
        task_id=task_id, goal="g", fixture_url="data:text/html,<h1>x</h1>",
        capability_axis=axis, expected_step_range=(1, 3), max_steps=5,
    )


# ---------- compute_reflective_uplift 三粒度 ----------


def test_compute_reflective_uplift_per_task_per_axis_overall():
    """V0.28.3: 4 task pair → per_task -1/0/+1, per_axis 平均, overall 平均.

    构造:
    - t1 axis=iframe: pass1=F pass2=T → +1
    - t2 axis=iframe: pass1=T pass2=T → 0
    - t3 axis=multi-tab: pass1=F pass2=F → 0
    - t4 axis=multi-tab: pass1=F pass2=T → +1
    Expected:
    - per_task = {t1: +1, t2: 0, t3: 0, t4: +1}
    - per_axis = {iframe: 0.5 (1/2 - 1/2 + 1/2 = +0.5? 不), multi-tab: 0.5}
      iframe pass1 rate = 0.5 (1 of 2 pass), pass2 rate = 1.0 (2 of 2) → uplift +0.5
      multi-tab pass1 rate = 0.0 (0 of 2 pass), pass2 rate = 0.5 (1 of 2 pass) → uplift +0.5
    - overall = (+1 + 0 + 0 + +1) / 4 = +0.5
    - reflections_written = 0 (failure_bucket 默 PREDICATE_FAIL 不在 max_steps/LOOP_DETECTED 集合)
    """
    metrics = [
        _mk_metric("t1", "anthropic", pass_=False, inject_reflections=False),
        _mk_metric("t1", "anthropic", pass_=True, inject_reflections=True),
        _mk_metric("t2", "anthropic", pass_=True, inject_reflections=False),
        _mk_metric("t2", "anthropic", pass_=True, inject_reflections=True),
        _mk_metric("t3", "anthropic", pass_=False, inject_reflections=False),
        _mk_metric("t3", "anthropic", pass_=False, inject_reflections=True),
        _mk_metric("t4", "anthropic", pass_=False, inject_reflections=False),
        _mk_metric("t4", "anthropic", pass_=True, inject_reflections=True),
    ]
    task_axis = cast("dict[str, CapabilityAxis]", {
        "t1": "iframe", "t2": "iframe", "t3": "multi-tab", "t4": "multi-tab",
    })

    rep = compute_reflective_uplift(metrics, task_axis)
    assert isinstance(rep, ReflectiveUpliftReport)
    assert rep.per_task == {"t1": +1, "t2": 0, "t3": 0, "t4": +1}
    assert rep.per_axis["iframe"] == pytest.approx(0.5)
    assert rep.per_axis["multi-tab"] == pytest.approx(0.5)
    assert rep.overall == pytest.approx(0.5)


def test_compute_reflective_uplift_counts_reflections_written_correctly():
    """V0.28.3: reflections_written = run1 失败且 failure_bucket in (max_steps/LOOP_DETECTED) 数.

    V0.29.5: bucket "(max_steps" 含左括号 (runner.py:67 split 输出格式), 跟 reflect.should_reflect
    触发集对齐. V0.28.3 起 fixture 用 bare "max_steps" 是 stale, 实 runner 永不产此 bucket.
    """
    metrics = [
        # t1: (max_steps 触发 reflection (V0.29.5: 实 runner 输出格式)
        _mk_metric("t1", "anthropic", pass_=False, inject_reflections=False, failure_bucket="(max_steps"),
        _mk_metric("t1", "anthropic", pass_=True, inject_reflections=True),
        # t2: LOOP_DETECTED 触发 reflection
        _mk_metric("t2", "anthropic", pass_=False, inject_reflections=False, failure_bucket="LOOP_DETECTED"),
        _mk_metric("t2", "anthropic", pass_=False, inject_reflections=True),
        # t3: PREDICATE_FAIL 不触发 reflection (外因子集外)
        _mk_metric("t3", "anthropic", pass_=False, inject_reflections=False, failure_bucket="PREDICATE_FAIL"),
        _mk_metric("t3", "anthropic", pass_=False, inject_reflections=True),
        # t4: 成功 → 不触发
        _mk_metric("t4", "anthropic", pass_=True, inject_reflections=False),
        _mk_metric("t4", "anthropic", pass_=True, inject_reflections=True),
    ]
    task_axis = cast("dict[str, CapabilityAxis]", {
        "t1": "iframe", "t2": "iframe", "t3": "iframe", "t4": "iframe",
    })

    rep = compute_reflective_uplift(metrics, task_axis)
    assert rep.reflections_written == 2  # t1 + t2 only


def test_compute_reflective_uplift_missing_pair_returns_skipped():
    """V0.28.3: 缺 pair (老 metrics 不带 inject_reflections / 单 run) → 跳过该 task."""
    # 只 1 metric (没配对) → 不进 per_task
    metrics = [_mk_metric("t1", "anthropic", pass_=True, inject_reflections=False)]
    task_axis = cast("dict[str, CapabilityAxis]", {"t1": "iframe"})

    rep = compute_reflective_uplift(metrics, task_axis)
    assert rep.per_task == {}
    assert rep.per_axis == {}
    assert rep.overall == 0.0


def test_compute_reflective_uplift_empty_metrics():
    """V0.28.3: 空 metrics → 全 0 边界."""
    rep = compute_reflective_uplift([], {})
    assert rep.per_task == {}
    assert rep.per_axis == {}
    assert rep.overall == 0.0
    assert rep.reflections_written == 0


# ---------- render_reflective_uplift_markdown ----------


def test_render_reflective_uplift_markdown_full():
    """V0.28.3: 渲染 markdown 含 overall + axis + per_task + reflections_written."""
    metrics = [
        _mk_metric("t1", "anthropic", pass_=False, inject_reflections=False, failure_bucket="(max_steps"),
        _mk_metric("t1", "anthropic", pass_=True, inject_reflections=True),
        _mk_metric("t2", "anthropic", pass_=True, inject_reflections=False),
        _mk_metric("t2", "anthropic", pass_=True, inject_reflections=True),
    ]
    tasks = [_mk_task("t1", "iframe"), _mk_task("t2", "iframe")]
    report = CorpusReport(run_id="r", started_at=0.0, ended_at=1.0, metrics=metrics)

    md = render_reflective_uplift_markdown(report, tasks)
    assert "overall" in md
    assert "iframe" in md
    assert "per-task" in md
    assert "t1: +1" in md
    assert "t2: +0" in md
    assert "reflections_written" in md
    assert "1 / 2" in md  # t1 触发 reflection / 2 配对


def test_render_reflective_uplift_markdown_empty_no_pairs():
    """V0.28.3: 0 配对 → '(no reflective data — run with --reflect)'."""
    report = CorpusReport(run_id="r", started_at=0.0, ended_at=1.0, metrics=[])
    md = render_reflective_uplift_markdown(report, [])
    assert "no reflective data" in md


# ---------- V0.29.5 W6-C 收口: chain task --reflect + V0.28.3 bucket bug fix ----------


def test_compute_reflective_uplift_includes_chain_task_pair():
    """V0.29.5: chain task 跑 --reflect 2-pass 产 2 metric 配对, V0.28.3 compute_reflective_uplift
    自然适用 (按 (task_id, provider) 配对 inject_reflections=False/True). 0 改 metrics 层."""
    metrics = [
        # chain task run1: max_steps fail → bucket "(max_steps" (含左括号, V0.28.3 bug)
        _mk_metric("v029-chain-reflect-trigger", "anthropic",
                   pass_=False, inject_reflections=False, failure_bucket="(max_steps"),
        # chain task run2: inject reflection 后 PASS
        _mk_metric("v029-chain-reflect-trigger", "anthropic",
                   pass_=True, inject_reflections=True),
    ]
    task_axis = cast("dict[str, CapabilityAxis]", {"v029-chain-reflect-trigger": "failure-recovery"})

    rep = compute_reflective_uplift(metrics, task_axis)
    assert "v029-chain-reflect-trigger" in rep.per_task
    assert rep.per_task["v029-chain-reflect-trigger"] == +1
    assert rep.overall == pytest.approx(1.0)
    assert "failure-recovery" in rep.per_axis
    assert rep.per_axis["failure-recovery"] == pytest.approx(1.0)


def test_reflections_written_handles_max_steps_bucket_with_paren_v0285_fix():
    """V0.29.5 fix V0.28.3 bucket 命名 bug: runner.py:67 marker.split(' ')[0] 处理
    '(max_steps 耗尽未完成)' 返 '(max_steps' (含左括号), V0.28.3 reflections_written
    `failure_bucket in ("max_steps", "LOOP_DETECTED")` 永不命中 → silent 0.

    V0.29.5 改 startswith 容错, 兼容 'max_steps' / '(max_steps' / 'LOOP_DETECTED'.
    """
    metrics = [
        # bucket "(max_steps" (实际 V0.26.0 _classify_failure_bucket 输出格式)
        _mk_metric("t1", "anthropic", pass_=False, inject_reflections=False,
                   failure_bucket="(max_steps"),
        _mk_metric("t1", "anthropic", pass_=True, inject_reflections=True),
        # bucket "LOOP_DETECTED" (无前缀, 也命中)
        _mk_metric("t2", "anthropic", pass_=False, inject_reflections=False,
                   failure_bucket="LOOP_DETECTED"),
        _mk_metric("t2", "anthropic", pass_=False, inject_reflections=True),
        # bucket "PREDICATE_FAIL" 不该命中
        _mk_metric("t3", "anthropic", pass_=False, inject_reflections=False,
                   failure_bucket="PREDICATE_FAIL"),
        _mk_metric("t3", "anthropic", pass_=False, inject_reflections=True),
    ]
    task_axis = cast("dict[str, CapabilityAxis]", {
        "t1": "failure-recovery", "t2": "failure-recovery", "t3": "iframe",
    })

    rep = compute_reflective_uplift(metrics, task_axis)
    # V0.28.3 silent bug: t1+t2 都触发 reflect 但 reflections_written=0
    # V0.29.5 fix: t1 ((max_steps) + t2 (LOOP_DETECTED) 都命中 = 2
    assert rep.reflections_written == 2, (
        f"V0.29.5 fix 未生效 — t1 '(max_steps' bucket + t2 'LOOP_DETECTED' 都该计 "
        f"reflections_written, 实 {rep.reflections_written}"
    )


def test_chain_reflect_trigger_corpus_task_loaded():
    """V0.29.5: eval.corpus.v029_chain.CHAIN_REFLECT_TRIGGER 含 chain_spec 2 node + node a
    on_failure='continue' (信号双向 — 让 node b 跑) + predicate 绑."""
    from eval.corpus import ALL_PREDICATES
    from eval.corpus.v029_chain import CHAIN_REFLECT_TRIGGER

    assert CHAIN_REFLECT_TRIGGER.chain_spec is not None
    assert len(CHAIN_REFLECT_TRIGGER.chain_spec.nodes) == 2
    # node a 必须 on_failure=continue (signal 双向, V0.29.5 设计)
    assert CHAIN_REFLECT_TRIGGER.chain_spec.nodes[0].id == "a"
    assert CHAIN_REFLECT_TRIGGER.chain_spec.nodes[0].on_failure == "continue"
    # node b 依赖 a
    assert CHAIN_REFLECT_TRIGGER.chain_spec.nodes[1].depends_on == ("a",)
    # predicate 绑入 ALL_PREDICATES
    assert CHAIN_REFLECT_TRIGGER.task_id in ALL_PREDICATES
    # capability_axis 是 failure-recovery (V0.29.5 chain trigger reflect = failure recovery 轴)
    assert CHAIN_REFLECT_TRIGGER.capability_axis == "failure-recovery"
