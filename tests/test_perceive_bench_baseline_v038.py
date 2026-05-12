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


def test_v038_1_som_inject_js_walker_merged_to_one():
    """V0.38.1: _SOM_INJECT_JS 内 `while (stack.length)` 数 = 1 (W1+W2 合并单 walker).

    F2 实施后 W1 collect + W2 clear data-som-id 合并成单 walker 同 1 DOM tree DFS 跑.
    V0.22.x shadow DOM 穿透契约 + V0.22.2 actuator data-som-id 契约保 (clear 时机不变).
    """
    perceiver_py = Path(__file__).resolve().parent.parent / "src" / "web_agent" / "perceiver.py"
    src = perceiver_py.read_text(encoding="utf-8")
    m = re.search(r'_SOM_INJECT_JS\s*=\s*"""(.*?)"""', src, re.DOTALL)
    assert m is not None, "_SOM_INJECT_JS 未找到"
    inject_js = m.group(1)
    walker_count = inject_js.count("while (stack.length)")
    assert walker_count == 1, (
        f"V0.38.1 F2 _SOM_INJECT_JS 期望 1 walker (W1+W2 合并), 真测 {walker_count}"
    )
    # V0.22.2 契约: clear data-som-id 仍在 inject 入口跑 (合并到主 walker 内)
    assert "removeAttribute('data-som-id')" in inject_js, (
        "V0.22.2 contract: clear stale data-som-id 仍必跑 (防 actuator 走错 id)"
    )
    # V0.22.x shadow 穿透契约
    assert "shadowRoot.mode === 'open'" in inject_js, (
        "W5-B contract: shadow DOM open mode walker 必保"
    )
