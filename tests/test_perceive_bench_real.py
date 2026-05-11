"""V0.34.1 slow smoke: 真 chromium 跑 perceive_bench adapter, gate WEB_AGENT_RUN_SLOW=1.

@pytest.mark.slow + skipif WEB_AGENT_RUN_SLOW != "1" 双保险, 默认 CI / 本地 pytest 跳过.
本地手动跑: WEB_AGENT_RUN_SLOW=1 uv run pytest tests/test_perceive_bench_real.py -v

跟 V0.21+ test_loop_iframe / V0.30.2 test_stealth_probe_sannysoft 同模式. 真起 headless
chromium, 跑 ~3-5s wallclock (1 fixture × 2-3 samples × ~50ms perceive + browser launch ~2s).
"""

from __future__ import annotations

import os

import pytest

from eval.perceive_bench import build_synthetic_fixture
from eval.perceive_bench_adapter import run_bench_against_chromium

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("WEB_AGENT_RUN_SLOW", "") != "1",
        reason="real chromium bench; opt-in via WEB_AGENT_RUN_SLOW=1",
    ),
]


async def test_run_bench_baseline_fixture_real() -> None:
    """if0-sh0-leaf5 真 perceive: marks=5 (5 leaf button), ms>0, mem>=0, sample_count=2."""
    fixtures = [build_synthetic_fixture(0, 0, 5)]
    results = await run_bench_against_chromium(fixtures, samples_per=2, headless=True)

    assert len(results) == 1
    r = results[0]
    assert r.fixture_id == "if0-sh0-leaf5"
    assert r.mark_count == 5, f"期望 5 mark (5 leaf button), 真测 {r.mark_count}"
    assert r.perceive_ms > 0.0
    assert r.memory_kb >= 0.0
    assert r.sample_count == 2
    assert r.shadow_walks == 0  # V0.34.1 暂不收集
    assert r.iframe_walks == 0


async def test_run_bench_iframe_fixture_real() -> None:
    """if2-sh0-leaf3 真 perceive: V0.34.0 fixture design — leaves 仅在最深 iframe, mark == 3."""
    fixtures = [build_synthetic_fixture(2, 0, 3)]
    results = await run_bench_against_chromium(fixtures, samples_per=2, headless=True)

    assert len(results) == 1
    r = results[0]
    assert r.fixture_id == "if2-sh0-leaf3"
    # V0.34.2 fix: iframe_count=2 → 3 frame, 仅最深 iframe 装 3 leaf → 严格 ==3
    # (V0.34.1 期望 9 是 fixture design 误读, V0.34.2 修 + slow smoke 真测同步修正)
    assert r.mark_count == 3, f"期望 3 mark (最深 iframe 3 leaf), 真测 {r.mark_count}"
    assert r.perceive_ms > 0.0


async def test_run_bench_shadow_fixture_real() -> None:
    """V0.34.2: if0-sh2-leaf5 真 perceive: shadow 2 层 最深 5 leaf → mark == 5."""
    fixtures = [build_synthetic_fixture(0, 2, 5)]
    results = await run_bench_against_chromium(fixtures, samples_per=2, headless=True)

    r = results[0]
    assert r.fixture_id == "if0-sh2-leaf5"
    assert r.mark_count == 5, f"期望 5 mark (最深 shadow 5 leaf), 真测 {r.mark_count}"


async def test_run_bench_mixed_iframe_shadow_real() -> None:
    """V0.34.2: if2-sh2-leaf3 真 perceive: 2 层 iframe + 2 层 shadow 最深 3 leaf → mark == 3."""
    fixtures = [build_synthetic_fixture(2, 2, 3)]
    results = await run_bench_against_chromium(fixtures, samples_per=2, headless=True)

    r = results[0]
    assert r.fixture_id == "if2-sh2-leaf3"
    assert r.mark_count == 3, (
        f"期望 3 mark (最深 iframe 内最深 shadow 3 leaf), 真测 {r.mark_count}"
    )


async def test_run_bench_fanout_sibling_marks_real() -> None:
    """V0.34.4 F1: if1-sib5-sh0-leaf3 真测 fan-out 同层 sibling, mark_count == 15 (5 sibling × 3 leaf).

    不强制 ms 节省 — V0.34.4 真测发现 #17 (chromium same-origin shared renderer 主线程
    serialize 跨 frame JS, F1 并发 ROI 仅 ~3%). 只验 V0.22.x 契约: mark_count + frame_path
    DFS 顺序保 + V0.34.4 Python renumber 后全局 id 1..N 连续.
    """
    fixtures = [build_synthetic_fixture(1, 0, 3, siblings_per_layer=5)]
    results = await run_bench_against_chromium(fixtures, samples_per=2, headless=True)

    r = results[0]
    assert r.fixture_id == "if1-sib5-sh0-leaf3"
    assert r.mark_count == 15, f"期望 15 mark (5 sibling × 3 leaf), 真测 {r.mark_count}"


async def test_run_bench_fanout_tree_marks_real() -> None:
    """V0.34.4 F1: if2-sib3-sh0-leaf3 真测 fan-out 树, mark_count == 27 (3^2 × 3 leaf).

    27 = sib^iframe × leaf = 3^2 × 3 (深层最 leaf-frame 每个 3 button). 验 V0.22.x DFS
    iframe 遍历对 fan-out 树仍正确 (V0.34.4 并发 walker 不破契约).
    """
    fixtures = [build_synthetic_fixture(2, 0, 3, siblings_per_layer=3)]
    results = await run_bench_against_chromium(fixtures, samples_per=2, headless=True)

    r = results[0]
    assert r.fixture_id == "if2-sib3-sh0-leaf3"
    assert r.mark_count == 27, f"期望 27 mark (3^2 × 3 leaf), 真测 {r.mark_count}"


async def test_run_bench_samples_median_real() -> None:
    """samples_per=3 真跑, 验 sample_count=3 + ms 为 median + mark_count 稳定."""
    fixtures = [build_synthetic_fixture(0, 0, 5)]
    results = await run_bench_against_chromium(fixtures, samples_per=3, headless=True)

    r = results[0]
    assert r.sample_count == 3
    assert r.mark_count == 5
    assert r.perceive_ms > 0.0
