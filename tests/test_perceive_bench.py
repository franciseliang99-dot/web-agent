"""V0.34.0 perceive bench harness framework 单测: fixture builder + load + compare + render + cli."""

from __future__ import annotations

import json

import pytest

from eval.perceive_bench import (
    BenchCompareReport,
    BenchFixture,
    BenchResult,
    _parse_fixture_spec,
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
    """V0.34.2: iframe=3 → 3 层 JS DOM chain (不再用 HTML srcdoc attribute), 每层 1 个
    `iframe-depth-N` p 标签 → substring 出现 3 次 (含 JS literal escape)."""
    f = build_synthetic_fixture(iframe_count=3, shadow_count=0, leaf_per_branch=2)
    assert f.fixture_id == "if3-sh0-leaf2"
    assert f.iframe_count == 3
    # V0.34.2 fix: 每层 chain 1 个 <p>iframe-depth-{N}</p>; 外层 raw + 内层 JS-escaped
    # (json.dumps 不变 raw text, 不破 iframe-depth- substring)
    assert f.html.count("iframe-depth-") == 3, f"3 层 chain 应有 3 个 iframe-depth-, got {f.html.count('iframe-depth-')}"


def test_build_synthetic_fixture_shadow_2_layers():
    """V0.34.2: shadow=2 → 顶层 IIFE 一段 buildChain JS, 调 buildChain(2, leaf, root) 跑递归
    attachShadow (不再每层 host span + innerHTML 注入 script, V0.34.0 broken pattern)."""
    f = build_synthetic_fixture(iframe_count=0, shadow_count=2, leaf_per_branch=3)
    assert f.fixture_id == "if0-sh2-leaf3"
    assert f.shadow_count == 2
    # V0.34.2 fix: shadow_count 通过 buildChain(N, leaf, root) 参数传 JS, attachShadow 字符串
    # 1 次 (在递归 fn 体内, 不每层复制).
    assert "buildChain(2, 3," in f.html
    assert "attachShadow" in f.html
    # 不走 V0.34.0 broken pattern (sr.innerHTML=`...<script>...`)
    assert "sr.innerHTML=`" not in f.html


def test_build_synthetic_fixture_combined_iframe_shadow():
    """V0.34.2: iframe + shadow 同时, fixture_id 三参数都拼; HTML 含 iframe chain + shadow JS."""
    f = build_synthetic_fixture(iframe_count=2, shadow_count=1, leaf_per_branch=4)
    assert f.fixture_id == "if2-sh1-leaf4"
    assert "iframe-depth-" in f.html  # iframe chain (V0.34.2)
    assert "attachShadow" in f.html   # shadow chain (V0.34.2)


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
    assert "iframe-depth-" in html  # V0.34.2: JS DOM chain 替代 srcdoc HTML attr
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


# ---------- _parse_fixture_spec (V0.34.1 cli helper) ----------


def test_parse_fixture_spec_baseline():
    """V0.34.1: 'if0-sh0-leaf5' → BenchFixture (与 build_synthetic_fixture fixture_id 互逆)."""
    f = _parse_fixture_spec("if0-sh0-leaf5")
    assert f.fixture_id == "if0-sh0-leaf5"
    assert f.iframe_count == 0
    assert f.shadow_count == 0
    assert f.leaf_per_branch == 5


def test_parse_fixture_spec_nontrivial_and_whitespace():
    """V0.34.1: 'if3-sh2-leaf7' 多位数 + 前后空白容忍 (.strip())."""
    f = _parse_fixture_spec("  if3-sh2-leaf7  ")
    assert f.fixture_id == "if3-sh2-leaf7"
    assert f.iframe_count == 3
    assert f.shadow_count == 2
    assert f.leaf_per_branch == 7


def test_parse_fixture_spec_invalid_raises():
    """V0.34.1: 非法 spec (空 / 缺连字符 / 含非数字 / leaf=0) 抛 ValueError."""
    for bad in ["", "if0sh0leaf5", "ifX-sh0-leaf5", "if-1-sh0-leaf5"]:
        with pytest.raises(ValueError, match=r"非法 fixture spec"):
            _parse_fixture_spec(bad)
    # leaf=0 经 build_synthetic_fixture 抛 (规则 leaf>=1)
    with pytest.raises(ValueError, match=r"leaf"):
        _parse_fixture_spec("if0-sh0-leaf0")


# ---------- V0.34.2 HTML 结构 fast 测 (catch script close raw / chain count / shadow buildChain) ----------


def test_synthetic_html_iframe_chain_script_close_escaped():
    """V0.34.2: iframe_count>=1 时 main HTML 必须 `</` JS-escape 成 `<\\/`, 否则 HTML
    raw text parser 看到 `</script>` 在 JS string 内即终止 outer script → outer iframe
    永远不创建 (V0.34.2 真测发现 bug 沉淀).
    """
    f = build_synthetic_fixture(2, 0, 3)
    # JS string literal 内嵌的 inner HTML 必须含 escape 形 `<\/script>`
    assert r"<\/script>" in f.html
    # raw `</script>` 只能出现一次 (最外 script 真关闭), 中间嵌入位置不能有
    # raw text mode 下 HTML parser 看到 `</script>` 立即 close, 严格不允许中间出现
    assert f.html.count("</script>") == 1


def test_synthetic_html_iframe_chain_layer_count():
    """V0.34.2: iframe_count=N 时 HTML 含 N 个 iframe-depth-X 标签 (外层 raw + 内层 JS literal)."""
    for n in [1, 2, 3, 5]:
        f = build_synthetic_fixture(n, 0, 3)
        # 每层 chain 1 个 <p>iframe-depth-{X}</p>, json.dumps 不变 raw text → substring 总 N 次
        assert f.html.count("iframe-depth-") == n, (
            f"if{n}: 期望 {n} 个 iframe-depth-, 真测 {f.html.count('iframe-depth-')}"
        )
        assert "createElement" in f.html
        # 不走 V0.34.0 broken pattern (raw srcdoc HTML attribute 嵌套)
        assert "srcdoc=" not in f.html


def test_synthetic_html_shadow_chain_param():
    """V0.34.2: shadow_count=N 时 顶层 script 调 buildChain(N, leaf, root) 传 N 参数."""
    for n in [1, 2, 3]:
        f = build_synthetic_fixture(0, n, 4)
        # 主 frame 内顶层 script (shadow_count>0 模式) 调 buildChain({n}, 4, root)
        assert f"buildChain({n}, 4," in f.html, f"sh{n}: 期望 buildChain({n}, 4, root) 调用"
        # attachShadow 字符串出现 (DOM API 模式标志)
        assert "attachShadow" in f.html
        # 不走 innerHTML 注入 script 路径 (V0.34.0 broken pattern)
        assert "sr.innerHTML=`" not in f.html


# ---------- V0.34.3 fan-out fixture (siblings_per_layer) fast 测 ----------


def test_build_synthetic_fixture_fanout_default_sib_1():
    """V0.34.3: siblings_per_layer 默 1 → fixture_id 不含 'sib' (V0.34.2 baseline 兼容)."""
    f = build_synthetic_fixture(iframe_count=2, shadow_count=0, leaf_per_branch=3)
    assert f.fixture_id == "if2-sh0-leaf3", f"sib=1 默 fixture_id 不含 sib, got {f.fixture_id}"
    # html 仍含 iframe-host-0 (即使 K=1, _build_iframe_chain_html 也 host-0)
    assert 'id="iframe-host-0"' in f.html


def test_build_synthetic_fixture_fanout_explicit_sib_3():
    """V0.34.3: siblings_per_layer=3, iframe_count=2 → fixture_id 'if2-sib3-sh0-leaf3',
    每层 3 个 iframe-host div, JS for loop 跑 3 次."""
    f = build_synthetic_fixture(iframe_count=2, shadow_count=0, leaf_per_branch=3, siblings_per_layer=3)
    assert f.fixture_id == "if2-sib3-sh0-leaf3"
    # 每层 3 个 host div: depth=2 主 frame 3 个, depth=1 在 JS literal 内 3 个 (escape 形)
    # raw `id="iframe-host-` 出现 3 次 (主 frame 三 host), JS literal escape `id=\"iframe-host-`
    # 每层 3 个 × 1 inner layer = 3 次 (depth=1 host 在 JS literal). 主 frame + inner = 6 次.
    assert f.html.count('id="iframe-host-') == 3, (
        f"主 frame raw 期望 3 host div, 真测 {f.html.count('id=\"iframe-host-')}"
    )
    # JS for loop 跑 3 次 (`s < 3` 在 JS source raw)
    assert "s < 3" in f.html


def test_build_synthetic_fixture_invalid_siblings_raises():
    """V0.34.3: siblings_per_layer < 1 → ValueError."""
    with pytest.raises(ValueError, match=r"非法 fixture|siblings"):
        build_synthetic_fixture(iframe_count=1, shadow_count=0, leaf_per_branch=3, siblings_per_layer=0)
    with pytest.raises(ValueError, match=r"非法 fixture|siblings"):
        build_synthetic_fixture(iframe_count=1, shadow_count=0, leaf_per_branch=3, siblings_per_layer=-1)


def test_parse_fixture_spec_fanout():
    """V0.34.3: parse 'if2-sib3-sh1-leaf4' → siblings_per_layer=3 (新 sib 段 optional)."""
    f = _parse_fixture_spec("if2-sib3-sh1-leaf4")
    assert f.fixture_id == "if2-sib3-sh1-leaf4"
    assert f.iframe_count == 2
    assert f.shadow_count == 1
    assert f.leaf_per_branch == 4
    # V0.34.3 fast 测: html 含 3 host div 主 frame
    assert f.html.count('id="iframe-host-') == 3


def test_parse_fixture_spec_fanout_backward_compatible():
    """V0.34.3: 'if2-sh0-leaf3' (V0.34.2 spec, 无 sib) 仍 parse OK, siblings 默 1."""
    f = _parse_fixture_spec("if2-sh0-leaf3")
    assert f.fixture_id == "if2-sh0-leaf3"  # 不含 sib (默 1)
