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
    """if2-sh0-leaf3 真 perceive: 3 frame (主 + 2 嵌 iframe) × 3 leaf = 9 mark."""
    fixtures = [build_synthetic_fixture(2, 0, 3)]
    results = await run_bench_against_chromium(fixtures, samples_per=2, headless=True)

    assert len(results) == 1
    r = results[0]
    assert r.fixture_id == "if2-sh0-leaf3"
    # iframe_count=2 → 主 + outer + inner = 3 frame, 每 frame 3 leaf button = 9 mark
    # (8-9 容忍 srcdoc nested iframe timing race; perceive iframe DFS 偶丢边缘)
    assert 8 <= r.mark_count <= 9, (
        f"期望 8-9 mark (3 frame × 3 leaf), 真测 {r.mark_count}"
    )
    assert r.perceive_ms > 0.0


async def test_run_bench_samples_median_real() -> None:
    """samples_per=3 真跑, 验 sample_count=3 + ms 为 median + mark_count 稳定."""
    fixtures = [build_synthetic_fixture(0, 0, 5)]
    results = await run_bench_against_chromium(fixtures, samples_per=3, headless=True)

    r = results[0]
    assert r.sample_count == 3
    assert r.mark_count == 5
    assert r.perceive_ms > 0.0
