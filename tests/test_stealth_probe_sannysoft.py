"""V0.30.2 + V0.39.0 G stealth 真生效验 — sannysoft probe slow opt-in test.

双 env 守门 (subagent V0.30.2 plan D 决):
- WEB_AGENT_RUN_SLOW=1 (跟 V0.21+ chromium slow smoke 同模式)
- WEB_AGENT_STEALTH_PROBE=1 (V0.30.2 新, 防意外真访 sannysoft)

V0.30.2: 真访 https://bot.sannysoft.com → screenshot 存 data/stealth_probes/<UTC date>.png +
size > 10KB. 不真断分数, 仅 dump artifact maintainer 肉眼 review.

V0.39.0 改造: **抽 DOM 分数 + dump JSON**. sannysoft 表 `tr td` 解析 passed/failed count +
fail 项名字列表 → JSON 存 `data/stealth_probes/sannysoft_<date>.json`. V0.34 教训应用第 9 次:
真测推翻 README "72%" 24 months stale → 真值 96.8% (30/31).

sannysoft 不可达 → pytest.skip (subagent V0.30.1 隐藏风险 #3).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest


_PROBE_DIR = Path("data/stealth_probes")

# V0.39.0: real-net probe 守门 list — 移到 real test decorator (单 test 套), 让 fast unit
# 测 (_summarize / _EXTRACT_RESULTS_JS smoke) 默 CI 不 skip.
_REAL_PROBE_MARKS = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("WEB_AGENT_RUN_SLOW", "") != "1",
        reason="real chromium probe; opt-in via WEB_AGENT_RUN_SLOW=1",
    ),
    pytest.mark.skipif(
        os.environ.get("WEB_AGENT_STEALTH_PROBE", "") != "1",
        reason="sannysoft real-net probe; opt-in via WEB_AGENT_STEALTH_PROBE=1",
    ),
]


# V0.39.0: 抽 sannysoft DOM 分数 JS — 找 table tr td, passed 标 'result-passed' / 'passed' /
# 'ok' / class 含 passed; failed 标 'result-failed' / 'failed' / class 含 failed.
# 跟 sannysoft 表 schema (sub-row pattern: name col + result col[s]) 鲁棒兼容.
_EXTRACT_RESULTS_JS = """
() => {
    const rows = Array.from(document.querySelectorAll('table tr'));
    const data = {passed: [], failed: [], unknown_rows: 0};
    rows.forEach(tr => {
        const tds = tr.querySelectorAll('td');
        if (tds.length < 2) return;
        const name = tds[0].innerText.trim().substring(0, 80);
        if (!name) return;
        let classified = false;
        for (let i = 1; i < tds.length; i++) {
            const cls = (tds[i].className || '').toLowerCase();
            const txt = (tds[i].innerText || '').trim().toLowerCase();
            if (cls.includes('passed') || cls.includes('result-passed') || txt === 'passed' || txt === 'ok') {
                data.passed.push(name);
                classified = true;
                break;
            }
            if (cls.includes('failed') || cls.includes('result-failed') || txt === 'failed') {
                data.failed.push(name);
                classified = true;
                break;
            }
        }
        if (!classified) data.unknown_rows += 1;
    });
    return data;
}
"""


def _summarize(results: dict[str, Any]) -> dict[str, Any]:
    """V0.39.0: 把抽出的 raw results 压成 summary (total / pass_rate / fails 列表)."""
    passed = results.get("passed", [])
    failed = results.get("failed", [])
    total = len(passed) + len(failed)
    return {
        "total": total,
        "passed_count": len(passed),
        "failed_count": len(failed),
        "pass_rate": (len(passed) / total) if total > 0 else 0.0,
        "failed_tests": sorted(set(failed)),  # 去重 + 排序稳定 diff
        "unknown_rows": results.get("unknown_rows", 0),
    }


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("WEB_AGENT_RUN_SLOW", "") != "1",
    reason="real chromium probe; opt-in via WEB_AGENT_RUN_SLOW=1",
)
@pytest.mark.skipif(
    os.environ.get("WEB_AGENT_STEALTH_PROBE", "") != "1",
    reason="sannysoft real-net probe; opt-in via WEB_AGENT_STEALTH_PROBE=1",
)
async def test_stealth_probe_sannysoft_screenshot():
    """V0.30.2 + V0.39.0: 真 launch chromium → apply_stealth+plus → goto sannysoft →
    screenshot + DOM 抽分数 → dump JSON.

    artifact 路径:
    - data/stealth_probes/sannysoft_<UTC date>.png (V0.30.2, 不变)
    - data/stealth_probes/sannysoft_<UTC date>.json (V0.39.0 新, summary + raw)

    sannysoft 不可达 → pytest.skip 不挂 CI / dev iteration.
    """
    from playwright.async_api import async_playwright

    from web_agent.browser import apply_stealth, apply_stealth_plus

    _PROBE_DIR.mkdir(parents=True, exist_ok=True)
    date_stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    screenshot_path = _PROBE_DIR / f"sannysoft_{date_stamp}.png"
    json_path = _PROBE_DIR / f"sannysoft_{date_stamp}.json"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await apply_stealth(page)
            await apply_stealth_plus(page)
            try:
                await page.goto("https://bot.sannysoft.com/", timeout=15_000)
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception as e:
                pytest.skip(f"sannysoft unreachable ({type(e).__name__}: {e})")
            # V0.39.0: 等 JS detector 跑完 (sannysoft 部分 test 异步)
            await page.wait_for_timeout(3_000)
            # V0.39.0: 截图 + 抽分数
            await page.screenshot(path=str(screenshot_path), full_page=True)
            raw_results = await page.evaluate(_EXTRACT_RESULTS_JS)
        finally:
            await browser.close()

    # V0.30.2 size 断保留 (向后兼容)
    assert screenshot_path.exists(), f"screenshot 未存到 {screenshot_path}"
    size = screenshot_path.stat().st_size
    assert size > 10_000, (
        f"screenshot size {size} bytes < 10KB, 可能空白页或 sannysoft 返错; 检查 {screenshot_path}"
    )

    # V0.39.0: dump summary + raw 到 JSON, 给 maintainer 见 fail 项 + 给 V0.39.0 baseline
    summary = _summarize(raw_results)
    payload = {
        "date": date_stamp,
        "mode": "launch_headless",  # V0.39.x 后扩 connect_over_cdp 模式
        "summary": summary,
        "raw": raw_results,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # V0.39.0: 真测 baseline assert — total >= 20 (sannysoft 表至少 20+ test, 防完全没抽到)
    assert summary["total"] >= 20, (
        f"V0.39.0 抽分异常: total {summary['total']} < 20, 检查 sannysoft 表结构是否改 "
        f"({json_path})"
    )


# ---------- V0.39.0 fast unit 测 (mock HTML fixture, 不真访外网) ----------


_MOCK_SANNYSOFT_HTML = """
<html><body>
<table>
  <tr><td>WebDriver (New)</td><td class="result-failed">failed</td></tr>
  <tr><td>WebDriver (Old)</td><td class="result-passed">passed</td></tr>
  <tr><td>Chrome</td><td class="result-passed">passed</td></tr>
  <tr><td>Permissions</td><td class="result-passed">passed</td></tr>
  <tr><td>Plugins Length</td><td class="result-passed">passed</td></tr>
  <tr><td>Random Row Without Result</td></tr>
</table>
</body></html>
"""


def test_v039_summarize_extracts_pass_count():
    """V0.39.0: _summarize 抽出 passed/failed count + pass_rate 对."""
    raw = {
        "passed": ["a", "b", "c"],
        "failed": ["x"],
        "unknown_rows": 0,
    }
    summary = _summarize(raw)
    assert summary["total"] == 4
    assert summary["passed_count"] == 3
    assert summary["failed_count"] == 1
    assert summary["pass_rate"] == 0.75


def test_v039_summarize_empty_returns_zero_rate():
    """V0.39.0: 空 results → pass_rate=0 不 ZeroDivisionError."""
    summary = _summarize({"passed": [], "failed": [], "unknown_rows": 0})
    assert summary["total"] == 0
    assert summary["pass_rate"] == 0.0


def test_v039_summarize_dedupes_and_sorts_failed_tests():
    """V0.39.0: failed_tests 去重 + 排序 (sannysoft 偶 row 重复时不双数)."""
    raw = {
        "passed": [],
        "failed": ["WebDriver", "Chrome", "WebDriver", "Permissions"],
        "unknown_rows": 0,
    }
    summary = _summarize(raw)
    assert summary["failed_tests"] == ["Chrome", "Permissions", "WebDriver"]


def test_v039_extract_js_constant_well_formed():
    """V0.39.0: _EXTRACT_RESULTS_JS 内含 table tr td selector + passed/failed 分类 (smoke)."""
    assert "table tr" in _EXTRACT_RESULTS_JS
    assert "passed" in _EXTRACT_RESULTS_JS
    assert "failed" in _EXTRACT_RESULTS_JS
    assert "result-passed" in _EXTRACT_RESULTS_JS
    assert "result-failed" in _EXTRACT_RESULTS_JS
