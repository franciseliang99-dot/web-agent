"""V0.34.1 F sub-route 优化系列 2/N: 真跑 chromium adapter 兑现 V0.34.0 deferred.

V0.34.0 落 framework (BenchFixture/Result/Compare + cli fixture/compare/stats), 本提交加
chromium adapter 真跑 perceive() 测 ms / mark_count / memory_kb. gate WEB_AGENT_RUN_SLOW=1
(跟 V0.21+ test_loop_iframe / V0.30.2 test_stealth_probe_sannysoft 同模式).

memory profiler 用 tracemalloc (stdlib, 测 Python heap peak) 不用 psutil (RSS 含 chromium child
noise; 标准库 0 新依赖). shadow_walks / iframe_walks V0.34.1 暂不收集 (perceiver JS walker
不暴露 counter), 留 V0.34.x SoM 优化时补.

依赖方向 (CLAUDE.md 解耦审查): domain (eval.perceive_bench dataclass) ← adapter (本文件)
← caller (eval.perceive_bench:main run subparser, lazy import). 本文件唯一允许 import Playwright
/ web_agent.perceiver, framework 反向无依赖.
"""

from __future__ import annotations

import logging
import statistics
import time
import tracemalloc
from urllib.parse import quote

from playwright.async_api import async_playwright

from eval.perceive_bench import BenchFixture, BenchResult
from web_agent.perceiver import perceive

logger = logging.getLogger(__name__)


async def run_bench_against_chromium(
    fixtures: list[BenchFixture],
    *,
    samples_per: int = 5,
    headless: bool = True,
    extra_args: list[str] | None = None,
) -> list[BenchResult]:
    """V0.34.1: 真跑 chromium 测 perceive() metric.

    每 fixture 跑 samples_per 次 (默 5) 取 median 防 GC noise; 同 fixture 复用 browser,
    各 sample 新建 context+page (隔离 state). data URI 加载 fixture.html (跟 V0.22.1
    _PARENT_URL 同模式) 不写临时文件.

    V0.43.1: extra_args 注入 chromium.launch(args=...) 路径, 测 `--site-per-process` 等
    flag 对 iframe DFS 并发的影响 (#17 chromium same-origin renderer serialize 再戳).
    默 None → args=[] (V0.34.1 行为不变).

    返 list[BenchResult]:
        - perceive_ms = median(各 sample 耗时 ms)
        - mark_count = 各 sample 收集 mark 数 (期望同, 取 last)
        - memory_kb = median(各 sample tracemalloc peak KB)
        - shadow_walks / iframe_walks = 0 (V0.34.1 留补)
        - sample_count = samples_per
    """
    if samples_per < 1:
        raise ValueError(f"samples_per 需 >= 1 (got {samples_per})")

    results: list[BenchResult] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=extra_args or [])
        try:
            for fixture in fixtures:
                ms_samples: list[float] = []
                mem_samples_kb: list[float] = []
                mark_count = 0
                for _i in range(samples_per):
                    context = await browser.new_context()
                    page = await context.new_page()
                    try:
                        data_url = "data:text/html;charset=utf-8," + quote(fixture.html)
                        # V0.34.2: wait_until="load" 等主 frame 含直接 child iframe 全 load;
                        # 多层 dynamic-created (JS DOM API) iframe chain 是 async, networkidle 不
                        # 覆盖 grand-child load → 加 500ms settle wait 让 chain JS run + 各层 load
                        # 结算 (典型 ~50-100ms/层 × ≤5 层 = 250-500ms). 不计 perceive 段, 不污染
                        # perceive_ms metric.
                        await page.goto(data_url, wait_until="load", timeout=10_000)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=2_000)
                        except Exception:
                            logger.debug("networkidle timeout for fixture %s, 继续", fixture.fixture_id)
                        await page.wait_for_timeout(500)  # iframe chain settle

                        tracemalloc.start()
                        t0 = time.perf_counter()
                        marks, _screenshot_b64, _dismissed = await perceive(page)
                        elapsed_ms = (time.perf_counter() - t0) * 1000.0
                        _current, peak = tracemalloc.get_traced_memory()
                        tracemalloc.stop()

                        ms_samples.append(elapsed_ms)
                        mem_samples_kb.append(peak / 1024.0)
                        mark_count = len(marks)
                    finally:
                        await context.close()

                results.append(
                    BenchResult(
                        fixture_id=fixture.fixture_id,
                        perceive_ms=statistics.median(ms_samples),
                        mark_count=mark_count,
                        memory_kb=statistics.median(mem_samples_kb),
                        shadow_walks=0,
                        iframe_walks=0,
                        sample_count=samples_per,
                    ),
                )
        finally:
            await browser.close()
    return results


__all__ = ["run_bench_against_chromium"]
