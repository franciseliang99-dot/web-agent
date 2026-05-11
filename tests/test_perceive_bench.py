"""V0.34.0 perceive bench harness framework 单测: fixture builder + load + compare + render + cli."""

from __future__ import annotations

import json

import pytest

from eval.perceive_bench import (
    BenchCompareReport,
    BenchFixture,
    BenchResult,
    build_synthetic_fixture,
    compare_benches,
    load_bench_json,
    main,
    render_bench_compare_markdown,
)


def _write_bench(tmp_path, name: str, results: list[dict]):
    """V0.34.0 测 helper: 写 minimal bench JSON dump."""
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"bench_results": results}), encoding="utf-8")
    return p


# ---------- build_synthetic_fixture ----------


def test_build_synthetic_fixture_baseline_no_iframe_no_shadow():
    """V0.34.0: 默 iframe=0 shadow=0 leaf=5 → 5 button 单 frame light DOM, fixture_id 含 if0-sh0-leaf5."""
    f = build_synthetic_fixture()
    assert f.fixture_id == "if0-sh0-leaf5"
    assert f.iframe_count == 0
    assert f.shadow_count == 0
    assert f.leaf_per_branch == 5
    # 5 个 leaf button 都在 HTML 里
    for i in range(5):
        assert f'id="b{i}"' in f.html


def test_build_synthetic_fixture_iframe_3_layers():
    """V0.34.0: iframe=3 → 3 层 srcdoc 嵌套, fixture_id 含 if3, srcdoc 出现 3 次."""
    f = build_synthetic_fixture(iframe_count=3, shadow_count=0, leaf_per_branch=2)
    assert f.fixture_id == "if3-sh0-leaf2"
    assert f.iframe_count == 3
    assert f.html.count("srcdoc=") == 3, f"3 层 iframe 应有 3 个 srcdoc, got {f.html.count('srcdoc=')}"


def test_build_synthetic_fixture_shadow_2_layers():
    """V0.34.0: shadow=2 → 嵌套 attachShadow, fixture_id 含 sh2, script attachShadow 出现 2 次."""
    f = build_synthetic_fixture(iframe_count=0, shadow_count=2, leaf_per_branch=3)
    assert f.fixture_id == "if0-sh2-leaf3"
    assert f.shadow_count == 2
    assert f.html.count("attachShadow") == 2


def test_build_synthetic_fixture_combined_iframe_shadow():
    """V0.34.0: iframe + shadow 同时, fixture_id 三参数都拼."""
    f = build_synthetic_fixture(iframe_count=2, shadow_count=1, leaf_per_branch=4)
    assert f.fixture_id == "if2-sh1-leaf4"
    assert "srcdoc=" in f.html
    assert "attachShadow" in f.html


def test_build_synthetic_fixture_invalid_params_raises():
    """V0.34.0: 非法参数 (负 iframe / 负 shadow / leaf<1) → ValueError."""
    for kwargs in [
        {"iframe_count": -1},
        {"shadow_count": -1},
        {"leaf_per_branch": 0},
    ]:
        with pytest.raises(ValueError, match="非法 fixture"):
            build_synthetic_fixture(**kwargs)


def test_build_synthetic_fixture_html_self_contained():
    """V0.34.0: HTML self-contained (含 DOCTYPE / html / head / body), 可直接 page.set_content()."""
    f = build_synthetic_fixture(iframe_count=1, shadow_count=1, leaf_per_branch=2)
    assert f.html.startswith("<!DOCTYPE html>")
    assert "<head>" in f.html
    assert "<body>" in f.html
    assert "</html>" in f.html


# ---------- load_bench_json ----------


def test_load_bench_json_minimal(tmp_path):
    """V0.34.0: 单 result dump load + BenchResult 字段映射 (含 default 兼容)."""
    p = _write_bench(tmp_path, "a", [{
        "fixture_id": "if0-sh0-leaf5",
        "perceive_ms": 12.5,
        "mark_count": 5,
        "memory_kb": 100.0,
        "shadow_walks": 0,
        "iframe_walks": 0,
        "sample_count": 5,
    }])
    out = load_bench_json(p)
    assert len(out) == 1
    r = out[0]
    assert r.fixture_id == "if0-sh0-leaf5"
    assert r.perceive_ms == 12.5
    assert r.mark_count == 5
    assert r.sample_count == 5


def test_load_bench_json_missing_fields_default(tmp_path):
    """V0.34.0: 缺字段 (老 dump 没 shadow_walks 等) → 默 0."""
    p = _write_bench(tmp_path, "a", [{
        "fixture_id": "x", "perceive_ms": 1.0, "mark_count": 1,
        # 故意缺 memory_kb / shadow_walks / iframe_walks / sample_count
    }])
    out = load_bench_json(p)
    assert out[0].memory_kb == 0.0
    assert out[0].shadow_walks == 0
    assert out[0].iframe_walks == 0
    assert out[0].sample_count == 1


def test_load_bench_json_missing_path_raises(tmp_path):
    """V0.34.0: path 不存在 → FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="不存在"):
        load_bench_json(tmp_path / "nonexistent.json")


# ---------- compare_benches ----------


def _mk_result(fid: str, ms: float, marks: int, mem: float = 0.0) -> BenchResult:
    return BenchResult(
        fixture_id=fid, perceive_ms=ms, mark_count=marks, memory_kb=mem,
        shadow_walks=0, iframe_walks=0, sample_count=1,
    )


def test_compare_benches_basic_delta():
    """V0.34.0: B 比 A 快 → ms_delta 负值, percent_ms 负."""
    a = [_mk_result("f1", 100.0, 10), _mk_result("f2", 200.0, 20)]
    b = [_mk_result("f1", 80.0, 10), _mk_result("f2", 150.0, 20)]
    r = compare_benches(a, b, a_label="full", b_label="opt")
    assert r.a_label == "full"
    assert r.b_label == "opt"
    assert r.per_fixture["f1"]["ms_delta"] == -20.0
    assert r.per_fixture["f1"]["percent_ms"] == -20.0
    assert r.per_fixture["f2"]["ms_delta"] == -50.0
    assert r.per_fixture["f2"]["percent_ms"] == -25.0
    # avg_ms_delta = (-20 + -50) / 2 = -35
    assert r.overall["avg_ms_delta"] == -35.0


def test_compare_benches_skip_unpaired():
    """V0.34.0: A 有 B 没 (或反之) → 跳过, 不入 per_fixture / overall."""
    a = [_mk_result("f1", 100, 10), _mk_result("f2", 50, 5)]
    b = [_mk_result("f1", 80, 10)]  # f2 没
    r = compare_benches(a, b)
    assert "f1" in r.per_fixture
    assert "f2" not in r.per_fixture
    assert len(r.per_fixture) == 1


def test_compare_benches_empty_overall_zero():
    """V0.34.0: 全 empty / 配对 0 → overall 全 0 不 ZeroDivisionError."""
    r = compare_benches([], [])
    assert r.per_fixture == {}
    assert r.overall["avg_ms_delta"] == 0.0
    assert r.overall["avg_percent_ms"] == 0.0


def test_compare_benches_zero_ms_no_div_zero():
    """V0.34.0: a.perceive_ms=0 (degenerate) → percent_ms=0 不 raise."""
    a = [_mk_result("f1", 0.0, 1)]
    b = [_mk_result("f1", 5.0, 1)]
    r = compare_benches(a, b)
    assert r.per_fixture["f1"]["percent_ms"] == 0.0


# ---------- render_bench_compare_markdown ----------


def test_render_bench_compare_markdown_table_format():
    """V0.34.0: 渲染含 overall 行 + per-fixture 行 + table header."""
    a = [_mk_result("f1", 100, 10, mem=50)]
    b = [_mk_result("f1", 80, 8, mem=40)]
    r = compare_benches(a, b, a_label="full", b_label="opt")
    md = render_bench_compare_markdown(r)
    assert "| scope | ms Δ" in md  # header
    assert "**overall avg (full→opt)**" in md
    assert "f1" in md
    assert "-20.00" in md  # ms_delta
    assert "-2" in md  # mark_delta -2


def test_render_bench_compare_markdown_empty_message():
    """V0.34.0: per_fixture 空 → 友好提示."""
    r = compare_benches([], [])
    md = render_bench_compare_markdown(r)
    assert "no bench compare data" in md


# ---------- main cli ----------


def test_main_fixture_default_stdout(capsys):
    """V0.34.0: cli `fixture` 默无 --out → stdout HTML."""
    rc = main(["fixture", "--leaf", "3"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "<!DOCTYPE html>" in captured.out
    assert 'id="b0"' in captured.out


def test_main_fixture_to_file(tmp_path, capsys):
    """V0.34.0: cli `fixture --out` → 写 file + 打印 路径 + bytes."""
    out_path = tmp_path / "fixture.html"
    rc = main(["fixture", "--iframe", "2", "--shadow", "1", "--leaf", "2", "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    captured = capsys.readouterr()
    assert "if2-sh1-leaf2" in captured.out
    html = out_path.read_text()
    assert "srcdoc=" in html
    assert "attachShadow" in html


def test_main_fixture_invalid_returns_2(capsys):
    """V0.34.0: cli `fixture` 非法参数 → exit 2 + 错误信息 stderr."""
    rc = main(["fixture", "--leaf", "0"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "非法 fixture" in captured.err


def test_main_compare_basic(tmp_path, capsys):
    """V0.34.0: cli `compare A B` → 渲染 markdown 到 stdout."""
    a_p = _write_bench(tmp_path, "a", [{
        "fixture_id": "f1", "perceive_ms": 100.0, "mark_count": 10,
    }])
    b_p = _write_bench(tmp_path, "b", [{
        "fixture_id": "f1", "perceive_ms": 80.0, "mark_count": 10,
    }])
    rc = main(["compare", str(a_p), str(b_p), "--a-label", "full", "--b-label", "opt"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "**overall avg (full→opt)**" in captured.out
    assert "-20.00" in captured.out


def test_main_stats_basic(tmp_path, capsys):
    """V0.34.0: cli `stats path` → 列出每 fixture metric."""
    p = _write_bench(tmp_path, "a", [{
        "fixture_id": "f1", "perceive_ms": 12.5, "mark_count": 8,
        "memory_kb": 100.0, "shadow_walks": 2, "iframe_walks": 3, "sample_count": 5,
    }])
    rc = main(["stats", str(p)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "1 fixture results" in captured.out
    assert "f1" in captured.out
    assert "ms=12.50" in captured.out
    assert "shadow_walks=2" in captured.out


def test_main_compare_missing_file_returns_1(tmp_path, capsys):
    """V0.34.0: cli `compare` 路径不存在 → exit 1 + stderr."""
    p = _write_bench(tmp_path, "a", [])
    rc = main(["compare", str(p), str(tmp_path / "nonexistent.json")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err


# ---------- dataclass smoke ----------


def test_bench_fixture_frozen_slots():
    """V0.34.0: BenchFixture frozen → 改字段 raise."""
    f = BenchFixture(fixture_id="x", iframe_count=0, shadow_count=0, leaf_per_branch=1, html="")
    with pytest.raises((AttributeError, TypeError)):
        f.iframe_count = 5  # type: ignore[misc]


def test_bench_result_frozen_slots():
    """V0.34.0: BenchResult frozen → 改字段 raise."""
    r = _mk_result("x", 1.0, 1)
    with pytest.raises((AttributeError, TypeError)):
        r.perceive_ms = 99.0  # type: ignore[misc]


def test_bench_compare_report_frozen_slots():
    """V0.34.0: BenchCompareReport frozen → 改字段 raise."""
    r = compare_benches([], [])
    assert isinstance(r, BenchCompareReport)
    with pytest.raises((AttributeError, TypeError)):
        r.a_label = "X"  # type: ignore[misc]
