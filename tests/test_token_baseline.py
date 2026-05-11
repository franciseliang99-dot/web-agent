"""V0.33.0 token baseline framework 单测: load + compare + render + cli."""

from __future__ import annotations

import json

import pytest

from eval.token_baseline import (
    BaselineCompareReport,
    TaskTokenStats,
    compare_baselines,
    load_baseline_json,
    main,
    render_baseline_compare_markdown,
)


def _write_baseline(tmp_path, name: str, metrics: list[dict]):
    """V0.33.0 测 helper: 写 minimal eval JSON dump."""
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
    return p


# ---------- load_baseline_json ----------


def test_load_baseline_json_minimal(tmp_path):
    """V0.33.0: 单 metric dump load + TaskTokenStats 字段映射."""
    p = _write_baseline(tmp_path, "a", [{
        "task_id": "t1", "provider": "anthropic",
        "input_tokens": 1000, "output_tokens": 200,
        "input_cost_usd": 0.003, "output_cost_usd": 0.0006,
        "steps": 5,
    }])
    out = load_baseline_json(p)
    assert len(out) == 1
    s = out[0]
    assert s.task_id == "t1"
    assert s.provider == "anthropic"
    assert s.input_tokens == 1000
    assert s.steps == 5


def test_load_baseline_json_missing_path_raises(tmp_path):
    """V0.33.0: path 不存在 → FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="不存在"):
        load_baseline_json(tmp_path / "nonexistent.json")


# ---------- compare_baselines ----------


def test_compare_baselines_per_task_delta_and_overall(tmp_path):
    """V0.33.0: A vs B per-(task,provider) delta + overall sum + percent change."""
    a = [TaskTokenStats("t1", "anthropic", 1000, 200, 0.003, 0.0006, 5)]
    b = [TaskTokenStats("t1", "anthropic", 600, 150, 0.0018, 0.00045, 4)]  # 优化: 省 40% input
    report = compare_baselines(a, b, a_label="full", b_label="lean")

    assert isinstance(report, BaselineCompareReport)
    assert report.a_label == "full"
    assert report.b_label == "lean"
    key = ("t1", "anthropic")
    assert key in report.per_task
    delta = report.per_task[key]
    assert delta["input_delta"] == -400.0  # 优化 (B 比 A 少)
    assert delta["output_delta"] == -50.0
    overall = report.overall
    assert overall["total_input_delta"] == -400.0
    assert overall["percent_input"] == pytest.approx(-40.0)


def test_compare_baselines_missing_pair_skipped():
    """V0.33.0: 一边有另一边没 → 跳过 (跟 V0.28.3 reflective_uplift 配对算法一致)."""
    a = [TaskTokenStats("t1", "anthropic", 1000, 200, 0.003, 0.0006, 5)]
    b = [TaskTokenStats("t2", "anthropic", 500, 100, 0.0015, 0.0003, 3)]  # 不同 task_id
    report = compare_baselines(a, b)
    assert report.per_task == {}
    assert report.overall["total_input_delta"] == 0.0


def test_compare_baselines_zero_a_no_division_error():
    """V0.33.0: A 为 0 → percent 返 0.0 (不 div by zero)."""
    a = [TaskTokenStats("t1", "anthropic", 0, 0, 0.0, 0.0, 0)]
    b = [TaskTokenStats("t1", "anthropic", 100, 50, 0.0003, 0.00015, 2)]
    report = compare_baselines(a, b)
    assert report.overall["percent_input"] == 0.0
    assert report.overall["percent_cost"] == 0.0


# ---------- render_baseline_compare_markdown ----------


def test_render_baseline_compare_markdown_full():
    """V0.33.0: 渲染 markdown 含 overall + per-task 行."""
    a = [TaskTokenStats("t1", "anthropic", 1000, 200, 0.003, 0.0006, 5)]
    b = [TaskTokenStats("t1", "anthropic", 700, 150, 0.0021, 0.00045, 4)]
    report = compare_baselines(a, b, a_label="full", b_label="lean")
    md = render_baseline_compare_markdown(report)

    assert "overall" in md
    assert "full→lean" in md
    assert "t1 (anthropic)" in md
    assert "-300" in md  # input_delta
    assert "-50" in md  # output_delta


def test_render_baseline_compare_markdown_empty():
    """V0.33.0: 0 配对 → '(no baseline compare data)'."""
    a = [TaskTokenStats("t1", "anthropic", 1000, 200, 0.003, 0.0006, 5)]
    b = [TaskTokenStats("t2", "openai", 500, 100, 0.0015, 0.0003, 3)]  # 0 pair
    md = render_baseline_compare_markdown(compare_baselines(a, b))
    assert "no baseline compare" in md


# ---------- cli main ----------


def test_main_compare_subcommand(monkeypatch, capsys, tmp_path):
    """V0.33.0: web-agent-token-baseline compare A B → stdout markdown."""
    a_path = _write_baseline(tmp_path, "a", [{
        "task_id": "t1", "provider": "anthropic",
        "input_tokens": 1000, "output_tokens": 200,
        "input_cost_usd": 0.003, "output_cost_usd": 0.0006, "steps": 5,
    }])
    b_path = _write_baseline(tmp_path, "b", [{
        "task_id": "t1", "provider": "anthropic",
        "input_tokens": 700, "output_tokens": 150,
        "input_cost_usd": 0.0021, "output_cost_usd": 0.00045, "steps": 4,
    }])

    rc = main(["compare", str(a_path), str(b_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "overall" in out
    assert "t1 (anthropic)" in out


def test_main_stats_subcommand(monkeypatch, capsys, tmp_path):
    """V0.33.0: web-agent-token-baseline stats A → 列 per (task, provider) stats."""
    a_path = _write_baseline(tmp_path, "a", [
        {"task_id": "t1", "provider": "anthropic", "input_tokens": 1000, "output_tokens": 200,
         "input_cost_usd": 0.003, "output_cost_usd": 0.0006, "steps": 5},
        {"task_id": "t2", "provider": "openai", "input_tokens": 500, "output_tokens": 100,
         "input_cost_usd": 0.0015, "output_cost_usd": 0.0003, "steps": 3},
    ])
    rc = main(["stats", str(a_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 (task, provider) pairs" in out
    assert "t1 (anthropic)" in out
    assert "t2 (openai)" in out


def test_main_missing_path_exits(capsys, tmp_path):
    """V0.33.0: missing path → exit 1 + stderr."""
    rc = main(["compare", str(tmp_path / "nonexistent.json"), str(tmp_path / "also-missing.json")])
    assert rc == 1
    assert "不存在" in capsys.readouterr().err


def test_console_script_entry_registered():
    """V0.33.0: web-agent-token-baseline console_script 注册到 entry points."""
    import importlib.metadata as md

    eps = md.entry_points(group="console_scripts")
    matching = [ep for ep in eps if ep.name == "web-agent-token-baseline"]
    assert len(matching) == 1
    assert matching[0].value == "eval.token_baseline:main"
