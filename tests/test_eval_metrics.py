"""V0.26.2: metrics aggregate / pricing / report 单测.

不真跑 chromium / 真 LLM, 用 mock TaskMetric 验聚合 / cost / markdown 渲染.
"""

from __future__ import annotations

from eval.metrics import (
    aggregate,
    aggregate_by_capability_axis,
)
from eval.predicates import PredicateResult
from eval.pricing import PRICING, cost_usd
from eval.runner import CorpusReport, TaskMetric
from eval.types import EvalTask


def _mk_metric(
    task_id: str, provider: str, model: str = "claude-sonnet-4-6",
    pass_: bool = True, steps: int = 5, wallclock_s: float = 10.0,
    in_tok: int = 1000, out_tok: int = 100, bucket: str = "OK",
) -> TaskMetric:
    in_cost, out_cost = cost_usd(model, in_tok, out_tok)
    return TaskMetric(
        task_id=task_id, provider=provider, run_id="r",
        pass_=pass_, failure_bucket=bucket,
        steps=steps, wallclock_s=wallclock_s,
        web_agent_task_id="abc", final_result="x",
        predicate_result=PredicateResult(matched=pass_, reason="ok", name="Substring"),
        input_tokens=in_tok, output_tokens=out_tok,
        input_cost_usd=in_cost, output_cost_usd=out_cost,
    )


# --- pricing ---


def test_pricing_table_includes_anthropic_openai_kimi():
    """V0.26.2: PRICING 表覆盖 Sonnet 4.6 / gpt-5.5 / Kimi k2.6 (3 主力 provider 必有)."""
    assert "claude-sonnet-4-6" in PRICING
    assert "gpt-5.5" in PRICING
    assert "kimi-k2.6" in PRICING


def test_cost_usd_known_model():
    """V0.26.2: cost_usd 算 anthropic Sonnet 4.6 (input $3/M, output $15/M)."""
    in_cost, out_cost = cost_usd("claude-sonnet-4-6", 1_000_000, 100_000)
    assert in_cost == 3.0
    assert out_cost == 1.5


def test_cost_usd_unknown_model_returns_zero():
    """V0.26.2: 未知 model → (0, 0) (eval 报告标 unknown 不报错)."""
    assert cost_usd("unknown-model-xyz", 1000, 100) == (0.0, 0.0)


# --- aggregate ---


def test_aggregate_empty_returns_empty_dict():
    assert aggregate([]) == {}


def test_aggregate_single_provider_pass_rate():
    """V0.26.2: 单 provider 4 task (3 pass + 1 fail) → pass_rate 0.75."""
    metrics = [
        _mk_metric("t1", "anthropic", pass_=True),
        _mk_metric("t2", "anthropic", pass_=True),
        _mk_metric("t3", "anthropic", pass_=True),
        _mk_metric("t4", "anthropic", pass_=False, bucket="PREDICATE_FAIL"),
    ]
    summaries = aggregate(metrics)
    assert "anthropic" in summaries
    s = summaries["anthropic"]
    assert s.pass_rate == 0.75
    assert s.task_count == 4
    assert s.pass_count == 3
    assert s.failure_buckets == {"OK": 3, "PREDICATE_FAIL": 1}


def test_aggregate_cross_provider_separate_summaries():
    """V0.26.2: 跨 provider 各自聚合 — anthropic 100% vs openai 50%."""
    metrics = [
        _mk_metric("t1", "anthropic", pass_=True),
        _mk_metric("t1", "openai", pass_=False, bucket="LLM_FAILED"),
        _mk_metric("t2", "anthropic", pass_=True),
        _mk_metric("t2", "openai", pass_=True),
    ]
    summaries = aggregate(metrics)
    assert summaries["anthropic"].pass_rate == 1.0
    assert summaries["openai"].pass_rate == 0.5
    assert summaries["openai"].failure_buckets["LLM_FAILED"] == 1


def test_aggregate_median_wallclock():
    """V0.26.2: median_wallclock_s 用 statistics.median (奇数取中, 偶数取均值)."""
    metrics = [
        _mk_metric("t1", "anthropic", wallclock_s=5.0),
        _mk_metric("t2", "anthropic", wallclock_s=10.0),
        _mk_metric("t3", "anthropic", wallclock_s=20.0),
    ]
    s = aggregate(metrics)["anthropic"]
    assert s.median_wallclock_s == 10.0


def test_aggregate_total_cost_sums():
    """V0.26.2: total cost 跨 task 累加 (3 task × 1M in + 100K out × Sonnet 价 = 3 × $4.5)."""
    metrics = [_mk_metric(f"t{i}", "anthropic", in_tok=1_000_000, out_tok=100_000) for i in range(3)]
    s = aggregate(metrics)["anthropic"]
    # 单 task input cost = 1M × $3/M = $3; output cost = 100K × $15/M = $1.5; 共 $4.5
    assert abs(s.total_input_cost_usd - 9.0) < 0.01
    assert abs(s.total_output_cost_usd - 4.5) < 0.01


# --- by capability_axis ---


def test_aggregate_by_capability_axis_groups_by_axis_and_provider():
    """V0.26.2: by_axis dict[axis][provider] = pass_rate 决定 V0.27 vault 分级."""
    task_axis: dict[str, str] = {
        "iframe-1": "iframe", "iframe-2": "iframe",
        "drag-1": "drag",
    }
    metrics = [
        _mk_metric("iframe-1", "anthropic", pass_=True),
        _mk_metric("iframe-2", "anthropic", pass_=False),
        _mk_metric("iframe-1", "openai", pass_=False),
        _mk_metric("iframe-2", "openai", pass_=False),
        _mk_metric("drag-1", "anthropic", pass_=True),
        _mk_metric("drag-1", "openai", pass_=True),
    ]
    by_axis = aggregate_by_capability_axis(metrics, task_axis)  # type: ignore[arg-type]
    assert by_axis["iframe"]["anthropic"] == 0.5
    assert by_axis["iframe"]["openai"] == 0.0
    assert by_axis["drag"]["anthropic"] == 1.0
    assert by_axis["drag"]["openai"] == 1.0


def test_aggregate_by_capability_axis_skips_metrics_without_axis():
    """V0.26.2: task_id 不在 task_axis dict → metric 跳过 (防异步 corpus 漂移崩)."""
    metrics = [_mk_metric("orphan-task", "anthropic", pass_=True)]
    by_axis = aggregate_by_capability_axis(metrics, {})  # 空 dict
    assert by_axis == {}


# --- report markdown ---


def test_render_provider_summary_markdown_contains_headers_and_rows():
    """V0.26.2: provider 对比 markdown 表含 header 行 + provider 行."""
    from eval.report import render_provider_summary_markdown
    metrics = [_mk_metric("t1", "anthropic"), _mk_metric("t1", "openai", pass_=False)]
    md = render_provider_summary_markdown(CorpusReport(
        run_id="r1", started_at=0.0, ended_at=1.0, metrics=metrics,
    ))
    assert "| provider |" in md
    assert "| anthropic |" in md
    assert "| openai |" in md
    assert "100.0%" in md  # anthropic pass_rate
    assert "0.0%" in md   # openai pass_rate


def test_render_capability_axis_markdown_provider_columns():
    """V0.26.2: by-axis 表 column 是 providers 排序后, row 是 axis."""
    from eval.report import render_capability_axis_markdown
    tasks = [
        EvalTask(task_id="t1", goal="g", fixture_url="u",
                  capability_axis="iframe", expected_step_range=(1, 3)),
    ]
    metrics = [
        _mk_metric("t1", "anthropic", pass_=True),
        _mk_metric("t1", "openai", pass_=False),
    ]
    md = render_capability_axis_markdown(CorpusReport(
        run_id="r1", started_at=0.0, ended_at=1.0, metrics=metrics,
    ), tasks)
    assert "anthropic" in md
    assert "openai" in md
    assert "iframe" in md


def test_render_provider_summary_empty_returns_no_metrics():
    """V0.26.2: 空 metrics → 友好提示而非 KeyError."""
    from eval.report import render_provider_summary_markdown
    md = render_provider_summary_markdown(CorpusReport(
        run_id="r", started_at=0.0, ended_at=0.0, metrics=[],
    ))
    assert "no metrics" in md


# --- TaskMetric V0.26.2 字段兼容 ---


def test_task_metric_v0262_token_cost_fields():
    """V0.26.2: TaskMetric 含 input_tokens/output_tokens/input_cost_usd/output_cost_usd."""
    m = _mk_metric("t1", "anthropic", in_tok=2000, out_tok=200)
    assert m.input_tokens == 2000
    assert m.output_tokens == 200
    # Sonnet 价: 2000 × $3/M = $0.006 input; 200 × $15/M = $0.003 output
    assert abs(m.input_cost_usd - 0.006) < 1e-6
    assert abs(m.output_cost_usd - 0.003) < 1e-6


def test_metric_to_dict_includes_v0262_token_fields():
    """V0.26.2: metric_to_dict JSON 含 token cost 字段 (round 6 位精度)."""
    from eval.runner import metric_to_dict
    m = _mk_metric("t1", "anthropic", in_tok=1000, out_tok=100)
    d = metric_to_dict(m)
    assert "input_tokens" in d
    assert "output_tokens" in d
    assert "input_cost_usd" in d
    assert "output_cost_usd" in d
    assert d["input_tokens"] == 1000
    assert d["output_tokens"] == 100
