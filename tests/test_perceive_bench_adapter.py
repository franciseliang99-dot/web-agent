"""V0.34.1 单元测 perceive_bench_adapter (mock chromium + perceive).

不真起 chromium / Playwright; 走 unittest.mock.AsyncMock 链验 metric 收集 / sample loop /
cleanup. 真 chromium 测见 tests/test_perceive_bench_real.py (slow smoke, WEB_AGENT_RUN_SLOW=1).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.perceive_bench import build_synthetic_fixture
from eval.perceive_bench_adapter import run_bench_against_chromium


def _build_pw_mock() -> tuple[MagicMock, MagicMock, MagicMock]:
    """构造 `async_playwright() → chromium.launch() → new_context() → new_page()` chain mock.

    返 (async_pw_cm, browser_mock, context_mock) — 测可断言 browser.close / context.close
    被 await 的次数验 try/finally cleanup 行为.
    """
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()  # V0.34.2 adapter 加 settle wait

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_async_pw_cm = MagicMock()
    mock_async_pw_cm.__aenter__ = AsyncMock(return_value=mock_p)
    mock_async_pw_cm.__aexit__ = AsyncMock(return_value=None)

    return mock_async_pw_cm, mock_browser, mock_context


async def test_run_bench_collects_mark_count_and_samples() -> None:
    """1 fixture × 3 samples, fake perceive 返 5 marks → mark_count=5 / sample_count=3 / walks=0."""
    pw_mock, _browser, ctx_mock = _build_pw_mock()
    fake_marks = [MagicMock() for _ in range(5)]
    fake_perceive = AsyncMock(return_value=(fake_marks, "fake_b64", []))

    with (
        patch("eval.perceive_bench_adapter.async_playwright", return_value=pw_mock),
        patch("eval.perceive_bench_adapter.perceive", fake_perceive),
    ):
        fixtures = [build_synthetic_fixture(0, 0, 5)]
        results = await run_bench_against_chromium(fixtures, samples_per=3)

    assert len(results) == 1
    r = results[0]
    assert r.fixture_id == "if0-sh0-leaf5"
    assert r.mark_count == 5
    assert r.sample_count == 3
    assert r.shadow_walks == 0
    assert r.iframe_walks == 0
    assert r.perceive_ms >= 0.0
    assert r.memory_kb >= 0.0
    assert fake_perceive.await_count == 3
    assert ctx_mock.close.await_count == 3


async def test_run_bench_multi_fixture_preserves_order() -> None:
    """2 fixtures × 2 samples, 验输入顺序保留 + 每 fixture sample_count 正确."""
    pw_mock, _browser, _ctx = _build_pw_mock()
    fake_perceive = AsyncMock(return_value=([MagicMock(), MagicMock()], "x", []))

    with (
        patch("eval.perceive_bench_adapter.async_playwright", return_value=pw_mock),
        patch("eval.perceive_bench_adapter.perceive", fake_perceive),
    ):
        fixtures = [
            build_synthetic_fixture(0, 0, 3),
            build_synthetic_fixture(2, 0, 4),
        ]
        results = await run_bench_against_chromium(fixtures, samples_per=2)

    assert [r.fixture_id for r in results] == ["if0-sh0-leaf3", "if2-sh0-leaf4"]
    assert all(r.sample_count == 2 for r in results)
    assert all(r.mark_count == 2 for r in results)
    assert fake_perceive.await_count == 4  # 2 fixtures × 2 samples


async def test_run_bench_invalid_samples_per_raises() -> None:
    """samples_per < 1 在 launch 前 raise ValueError, chromium 不启."""
    with pytest.raises(ValueError, match="samples_per"):
        await run_bench_against_chromium([], samples_per=0)
    with pytest.raises(ValueError, match="samples_per"):
        await run_bench_against_chromium([build_synthetic_fixture()], samples_per=-1)


async def test_run_bench_browser_close_on_perceive_failure() -> None:
    """perceive raise 时 browser.close 仍 await (try/finally 守护资源).

    防 chromium leak — 异常路径下还能干净拆掉.
    """
    pw_mock, browser_mock, _ctx = _build_pw_mock()
    fake_perceive = AsyncMock(side_effect=RuntimeError("perceive 故障 mock"))

    with (
        patch("eval.perceive_bench_adapter.async_playwright", return_value=pw_mock),
        patch("eval.perceive_bench_adapter.perceive", fake_perceive),
    ):
        fixtures = [build_synthetic_fixture(0, 0, 5)]
        with pytest.raises(RuntimeError, match="perceive 故障 mock"):
            await run_bench_against_chromium(fixtures, samples_per=2)

    assert browser_mock.close.await_count == 1


async def test_run_bench_propagates_extra_args() -> None:
    """V0.43.1: extra_args 传给 chromium.launch(args=...) (--site-per-process 注入路径)."""
    pw_mock, _browser, _ctx = _build_pw_mock()
    mock_p = pw_mock.__aenter__.return_value
    fake_perceive = AsyncMock(return_value=([], "x", []))

    with (
        patch("eval.perceive_bench_adapter.async_playwright", return_value=pw_mock),
        patch("eval.perceive_bench_adapter.perceive", fake_perceive),
    ):
        fixtures = [build_synthetic_fixture(0, 0, 1)]
        await run_bench_against_chromium(
            fixtures, samples_per=1, extra_args=["--site-per-process", "--no-sandbox"],
        )

    launch_kwargs = mock_p.chromium.launch.call_args.kwargs
    assert launch_kwargs.get("args") == ["--site-per-process", "--no-sandbox"]


async def test_run_bench_default_extra_args_empty() -> None:
    """V0.43.1: 未传 extra_args → args=[] (V0.34.1 行为不破)."""
    pw_mock, _browser, _ctx = _build_pw_mock()
    mock_p = pw_mock.__aenter__.return_value
    fake_perceive = AsyncMock(return_value=([], "x", []))

    with (
        patch("eval.perceive_bench_adapter.async_playwright", return_value=pw_mock),
        patch("eval.perceive_bench_adapter.perceive", fake_perceive),
    ):
        fixtures = [build_synthetic_fixture(0, 0, 1)]
        await run_bench_against_chromium(fixtures, samples_per=1)

    launch_kwargs = mock_p.chromium.launch.call_args.kwargs
    assert launch_kwargs.get("args") == []
