"""V0.38.0 F2 pre-F2 baseline 单测 — 验 baseline JSON 数据完整性 + walker count invariant.

跟 V0.34.0 perceive_bench fast 测 + V0.36.0 disk_baseline 同模式: fast 测 (mock-free 但读真
data/bench JSON), 不真跑 chromium.

V0.38.0 是 F2 实施前 baseline + decision doc commit. tests 验:
1. baseline JSON 存在 + 数据完整
2. fixture set 跟 V0.34.3 fan-out baseline 同 (V0.38.x compare 用)
3. sample_count >= 8 (噪声 mitigate)
4. mark_count 跟 V0.34.3 同 fixture 完全一致 (V0.38.0 0 src 改 = 0 行为变)
5. _SOM_INJECT_JS 内 walker 数 = 2 (V0.38.1 后改 = 1, 留 invariant 测)
"""

from __future__ import annotations

import json
import re
from pathlib import Path


_DATA_BENCH = Path(__file__).resolve().parent.parent / "data" / "bench"
_V038_BASELINE = _DATA_BENCH / "v0.38.0-before-f2-baseline.json"
_V034_3_BASELINE = _DATA_BENCH / "v0.34.3-fanout-baseline.json"


def test_v038_pre_f2_baseline_file_exists_and_valid_json():
    """V0.38.0: baseline JSON 存在 + valid JSON + 含 bench_results list."""
    assert _V038_BASELINE.exists(), f"V0.38.0 baseline 不存在: {_V038_BASELINE}"
    data = json.loads(_V038_BASELINE.read_text(encoding="utf-8"))
    assert "bench_results" in data
    assert isinstance(data["bench_results"], list)
    assert len(data["bench_results"]) == 7  # 7 fixture (跟 V0.34.3 fan-out 同)


def test_v038_pre_f2_baseline_fixture_set_matches_v034_3():
    """V0.38.0: fixture set 跟 v0.34.3-fanout-baseline.json 完全一致 (compare 基础)."""
    v038 = json.loads(_V038_BASELINE.read_text(encoding="utf-8"))
    v034_3 = json.loads(_V034_3_BASELINE.read_text(encoding="utf-8"))
    v038_ids = {r["fixture_id"] for r in v038["bench_results"]}
    v034_3_ids = {r["fixture_id"] for r in v034_3["bench_results"]}
    assert v038_ids == v034_3_ids, f"fixture set 不匹配: V0.38 {v038_ids} vs V0.34.3 {v034_3_ids}"


def test_v038_pre_f2_baseline_sample_count_at_least_8():
    """V0.38.0: 每 fixture sample_count >= 8 (噪声 mitigate, 跟 V0.34.3 同标准)."""
    data = json.loads(_V038_BASELINE.read_text(encoding="utf-8"))
    for r in data["bench_results"]:
        assert r["sample_count"] >= 8, f"{r['fixture_id']} sample_count={r['sample_count']} < 8"


def test_v038_pre_f2_baseline_mark_count_matches_v034_3():
    """V0.38.0: 每 fixture mark_count 跟 V0.34.3 完全一致 (0 src 改 = 0 行为变契约).

    ms 因 chromium 沙箱 noise 可能 ±5-44% 不验, 但 mark_count 是 deterministic, 任何差异 = 行为变.
    """
    v038_by_id = {r["fixture_id"]: r for r in json.loads(_V038_BASELINE.read_text())["bench_results"]}
    v034_3_by_id = {r["fixture_id"]: r for r in json.loads(_V034_3_BASELINE.read_text())["bench_results"]}
    for fid in v038_by_id:
        v038_mark = v038_by_id[fid]["mark_count"]
        v034_3_mark = v034_3_by_id[fid]["mark_count"]
        assert v038_mark == v034_3_mark, (
            f"{fid} mark_count 行为变: V0.38 {v038_mark} vs V0.34.3 {v034_3_mark}"
        )


def test_v038_pre_f2_som_inject_js_has_two_walkers():
    """V0.38.0: _SOM_INJECT_JS 内 `while (stack.length)` 数 = 2 (W1 collect + W2 clear data-som-id).

    invariant 测 — V0.38.1 实施 F2 合并 W1+W2 后, 数 = 1, 该测必同步改. 防 V0.38.1 漏改某 walker.
    """
    perceiver_py = Path(__file__).resolve().parent.parent / "src" / "web_agent" / "perceiver.py"
    src = perceiver_py.read_text(encoding="utf-8")
    # 抽 _SOM_INJECT_JS 字符串 (start to closing triple-quote)
    m = re.search(r'_SOM_INJECT_JS\s*=\s*"""(.*?)"""', src, re.DOTALL)
    assert m is not None, "_SOM_INJECT_JS 未找到"
    inject_js = m.group(1)
    walker_count = inject_js.count("while (stack.length)")
    assert walker_count == 2, (
        f"V0.38.0 _SOM_INJECT_JS 期望 2 walker (W1 collect + W2 clear), 真测 {walker_count}. "
        f"V0.38.1 实施 F2 后应改 == 1, 该测同步改."
    )
