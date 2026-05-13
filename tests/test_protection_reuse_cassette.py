"""V0.48.1: cassette test infra for V0.47.4 推荐 — 先 cassette 真测证 reuse 检测在 V0.30 之上仍真问题, 再 V0.48.x 实施 fingerprint pool.

3 真站 (cloudflare/sannysoft/akamai) × 10 visit 同 fingerprint 复访, record ProtectionSignal each
visit (跟 V0.47.1 listener 通道) → dump JSON cassette → escalated() 纯函数自动判.

Decision 门槛 (V0.48.0 doc 先写):
- ≥1 站 10 次内 escalate (level 升级 / status 200→403/503 / captcha vendor 从空→命中 /
  cookies 集合扩) → retain pool + V0.48.x 实施 preset + seed-by-domain
- 3 站 × 10 次全 stable → sink pool + V0.48 doc 收尾 + 转 V0.49 别主题

V0.48.1 = autonomous infra (test file + decision 函数 + fast unit). V0.48.2 真跑 = maintainer 红线
(真站 IP-level footprint 应人审, 跟 V0.39 STEALTH_PROBE / V0.46.x.1 / V0.47.x.1 同模式).

双 env 守门 (跟 V0.39.0 sannysoft 同):
- WEB_AGENT_RUN_SLOW=1: chromium real 真测 (V0.21+ smoke 同模式)
- WEB_AGENT_REUSE_PROBE=1: V0.48.1 新, 防意外真访 cloudflare/akamai/sannysoft 10×3 次
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from web_agent.protection import ProtectionSignal

_PROBE_DIR = Path("data/stealth_probes")


# V0.48.1 真测目标 list (3 真站, 跟 V0.48.0 plan)
_REUSE_TARGETS: list[tuple[str, str, str]] = [
    # (domain, url, expected baseline level)
    ("cloudflare.com", "https://www.cloudflare.com/", "medium"),
    ("sannysoft.com", "https://bot.sannysoft.com/", "low"),
    ("akamai.com", "https://www.akamai.com/", "medium"),
]


_VISITS_PER_TARGET = 10
_VISIT_INTERVAL_MS = 2_000  # 跟 V0.16.21 spike 15s sleep 同思路 (节奏 polite 防 burst 干扰)


# V0.48.1: real-net probe 守门 — 单 real test decorator, 让 fast unit (escalated / _record_visit
# mock / _dump_cassette tmp_path) 默 CI 不 skip.
_REAL_PROBE_MARKS = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("WEB_AGENT_RUN_SLOW", "") != "1",
        reason="real chromium probe; opt-in via WEB_AGENT_RUN_SLOW=1",
    ),
    pytest.mark.skipif(
        os.environ.get("WEB_AGENT_REUSE_PROBE", "") != "1",
        reason="V0.48.1 reuse cassette real-net probe; opt-in via WEB_AGENT_REUSE_PROBE=1",
    ),
]


# --- 纯函数 helpers (autonomous fast unit cover) ---


def _signal_to_dict(signal: ProtectionSignal) -> dict[str, Any]:
    """V0.48.1: ProtectionSignal → JSON-friendly dict (frozenset → sorted list)."""
    d = dataclasses.asdict(signal)
    d["cookies"] = sorted(signal.cookies)  # frozenset → sorted list 给 JSON 可读 + 稳定
    return d


def _record_visit(ctx: Any, visit_idx: int) -> dict[str, Any]:
    """V0.48.1: 抓 ctx._web_agent_protection_signals[-1] (V0.47.1 listener 累积) + classify level.

    无 signal (e.g. main-frame nav 未完成) → 返 {visit_idx, level: unknown, signal: None}.
    """
    from web_agent.protection import classify

    signals = getattr(ctx, "_web_agent_protection_signals", [])
    if not signals:
        return {"visit_idx": visit_idx, "level": "unknown", "signal": None}
    latest = signals[-1]
    return {
        "visit_idx": visit_idx,
        "level": classify(latest),
        "signal": _signal_to_dict(latest),
    }


def _dump_cassette(domain: str, visits: list[dict[str, Any]]) -> Path:
    """V0.48.1: 写 data/stealth_probes/v0.48-reuse-cassette-{domain}_{UTC date}.json (跟 V0.39 同模式)."""
    _PROBE_DIR.mkdir(parents=True, exist_ok=True)
    date_stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    domain_safe = domain.replace(".", "_")
    out = _PROBE_DIR / f"v0.48-reuse-cassette-{domain_safe}_{date_stamp}.json"
    out.write_text(
        json.dumps(
            {"domain": domain, "visits": visits, "ts": date_stamp},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return out


_LEVEL_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


def escalated(visits: list[dict[str, Any]]) -> bool:
    """V0.48.1: 纯函数判 visit list 是否 escalate (V0.48.0 decision 门槛自动化).

    Escalate 信号 (任一命中即 True):
    1. level 升级: visits[-1].level rank > visits[0].level rank (low→medium / medium→high 等)
    2. status 升级: visits[0].status in (200, 301, 302) but visits[-1].status in (403, 503, 429)
    3. captcha vendor 从空→命中
    4. cookies 集合扩 (visits[-1].signal.cookies ⊋ visits[0].signal.cookies, 新增 cf_clearance 等)
    """
    if len(visits) < 2:
        return False
    first = visits[0]
    last = visits[-1]
    # 1. level 升级
    if _LEVEL_RANK.get(last["level"], 0) > _LEVEL_RANK.get(first["level"], 0):
        return True
    # 2-4 需要 signal 非 None
    first_sig = first.get("signal")
    last_sig = last.get("signal")
    if not first_sig or not last_sig:
        return False
    # 2. status 升级
    if first_sig["status"] in (200, 301, 302) and last_sig["status"] in (403, 429, 503):
        return True
    # 3. captcha vendor 从空→命中
    if not first_sig["captcha_vendor"] and last_sig["captcha_vendor"]:
        return True
    # 4. cookies 集合扩 (last 严格 superset 且新增)
    first_cookies = set(first_sig["cookies"])
    last_cookies = set(last_sig["cookies"])
    if last_cookies > first_cookies and (last_cookies - first_cookies):
        return True
    return False


# --- fast unit tests (V0.48.1 autonomous) ---


def test_signal_to_dict_serializes_frozenset_cookies() -> None:
    """V0.48.1: ProtectionSignal frozenset → sorted list (JSON friendly + 稳定顺序)."""
    s = ProtectionSignal(
        server="cloudflare", status=200, cookies=frozenset({"cf_clearance", "__cfduid"}),
        cf_ray="abc123", captcha_vendor="",
    )
    d = _signal_to_dict(s)
    assert d["server"] == "cloudflare"
    assert d["status"] == 200
    assert d["cookies"] == ["__cfduid", "cf_clearance"]  # sorted
    assert d["cf_ray"] == "abc123"


def test_dump_cassette_creates_json_with_visits(tmp_path: Path, monkeypatch) -> None:
    """V0.48.1: _dump_cassette 写 JSON + path 含 domain + UTC timestamp."""
    monkeypatch.setattr(
        "tests.test_protection_reuse_cassette._PROBE_DIR", tmp_path / "stealth_probes",
    )
    visits = [
        {"visit_idx": 0, "level": "low", "signal": None},
        {"visit_idx": 1, "level": "medium", "signal": None},
    ]
    out = _dump_cassette("test.com", visits)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["domain"] == "test.com"
    assert len(data["visits"]) == 2
    assert "v0.48-reuse-cassette-test_com" in out.name


def test_record_visit_no_signal_returns_unknown() -> None:
    """V0.48.1: ctx 无 listener / 无 signal → record_visit 返 unknown (不 crash)."""

    class _MockCtx:
        _web_agent_protection_signals: list = []

    d = _record_visit(_MockCtx(), visit_idx=5)
    assert d == {"visit_idx": 5, "level": "unknown", "signal": None}


def test_record_visit_latest_signal_classified() -> None:
    """V0.48.1: ctx 有 signal → record_visit classify level + serialize signal."""

    class _MockCtx:
        _web_agent_protection_signals = [
            ProtectionSignal(server="cloudflare", status=200,
                             cookies=frozenset({"cf_clearance"}), cf_ray="x", captcha_vendor=""),
        ]

    d = _record_visit(_MockCtx(), visit_idx=3)
    assert d["visit_idx"] == 3
    assert d["level"] == "high"  # cf_clearance cookie → classify high
    assert d["signal"]["server"] == "cloudflare"
    assert "cf_clearance" in d["signal"]["cookies"]


# --- escalated() decision 门槛 矩阵 ---


@pytest.mark.parametrize("visits,expected", [
    # 单 visit / 空 list — 无足够数据 → False
    ([], False),
    ([{"visit_idx": 0, "level": "low", "signal": None}], False),
    # 全 stable low → False (sink path)
    (
        [{"visit_idx": i, "level": "low",
          "signal": {"server": "", "status": 200, "cookies": [], "cf_ray": "", "captcha_vendor": ""}}
         for i in range(10)],
        False,
    ),
    # level 升级 low → high → True (retain path 信号 1)
    (
        [
            {"visit_idx": 0, "level": "low",
             "signal": {"server": "", "status": 200, "cookies": [], "cf_ray": "", "captcha_vendor": ""}},
            {"visit_idx": 9, "level": "high",
             "signal": {"server": "cloudflare", "status": 403, "cookies": ["cf_clearance"],
                        "cf_ray": "x", "captcha_vendor": ""}},
        ],
        True,
    ),
    # status 升级 200 → 403 (level 假设算 medium → medium 不变, 但 status 升级触发) → True
    (
        [
            {"visit_idx": 0, "level": "medium",
             "signal": {"server": "cloudflare", "status": 200, "cookies": [], "cf_ray": "x",
                        "captcha_vendor": ""}},
            {"visit_idx": 9, "level": "medium",
             "signal": {"server": "cloudflare", "status": 403, "cookies": [], "cf_ray": "x",
                        "captcha_vendor": ""}},
        ],
        True,
    ),
    # captcha vendor 从空 → 命中 → True
    (
        [
            {"visit_idx": 0, "level": "low",
             "signal": {"server": "", "status": 200, "cookies": [], "cf_ray": "", "captcha_vendor": ""}},
            {"visit_idx": 9, "level": "high",
             "signal": {"server": "", "status": 200, "cookies": [],
                        "cf_ray": "", "captcha_vendor": "cloudflare-turnstile"}},
        ],
        True,
    ),
    # cookies 集合扩 (first 空 → last 有 cf_clearance) — 但 level 已 high (cookie → high) → 主路径走 level 升级
    # 验 cookies-only escalation: level 同 medium 但 cookies superset (不实际可达, 单测 logic)
    (
        [
            {"visit_idx": 0, "level": "medium",
             "signal": {"server": "cloudflare", "status": 200, "cookies": [],
                        "cf_ray": "x", "captcha_vendor": ""}},
            {"visit_idx": 9, "level": "medium",
             "signal": {"server": "cloudflare", "status": 200, "cookies": ["new_cookie"],
                        "cf_ray": "x", "captcha_vendor": ""}},
        ],
        True,
    ),
    # signal None (无 listener 数据) — 仅 level 比较 → 同 level None+None → False
    (
        [
            {"visit_idx": 0, "level": "low", "signal": None},
            {"visit_idx": 9, "level": "low", "signal": None},
        ],
        False,
    ),
])
def test_escalated_decision_matrix(visits: list[dict[str, Any]], expected: bool) -> None:
    """V0.48.1: escalated() 决策门槛矩阵 (跟 V0.48.0 doc 4 信号路径)."""
    assert escalated(visits) is expected


# --- real chromium probe (V0.48.2 maintainer 红线, V0.48.1 仅写 placeholder) ---


@pytest.mark.parametrize("domain,url,expected_baseline", _REUSE_TARGETS)
@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("WEB_AGENT_RUN_SLOW", "") != "1",
    reason="real chromium probe; opt-in via WEB_AGENT_RUN_SLOW=1",
)
@pytest.mark.skipif(
    os.environ.get("WEB_AGENT_REUSE_PROBE", "") != "1",
    reason="V0.48.1 reuse cassette real-net probe; opt-in via WEB_AGENT_REUSE_PROBE=1",
)
async def test_reuse_detection_real(domain: str, url: str, expected_baseline: str) -> None:
    """V0.48.2 maintainer 红线: 真访 {domain} × {_VISITS_PER_TARGET} 次同 fingerprint, dump cassette JSON.

    跑法: `WEB_AGENT_RUN_SLOW=1 WEB_AGENT_REUSE_PROBE=1 uv run pytest tests/test_protection_reuse_cassette.py -v`
    总 ~10 min (3 站 × 10 visit × (2s interval + ~5s goto + listener buffer)).

    target 不可达 → pytest.skip (跟 V0.39.0 sannysoft 同模式, 不挂 CI / dev iteration).
    """
    from playwright.async_api import async_playwright

    from web_agent.browser import apply_stealth, apply_stealth_plus
    from web_agent.protection import attach_protection_listener

    async with async_playwright() as p:
        # V0.60.0: cassette test direct launch proxy 双 env opt-in (cassette 已 WEB_AGENT_REUSE_PROBE
        # opt-in, 加 proxy 时同 cassette 录 proxy header → user 红线显式).
        from web_agent.proxy_util import get_eval_proxy_kwargs
        _proxy = get_eval_proxy_kwargs()
        _launch_kwargs: dict = {"headless": True, "args": ["--no-sandbox"]}
        if _proxy is not None:
            _launch_kwargs["proxy"] = _proxy
        browser = await p.chromium.launch(**_launch_kwargs)
        try:
            ctx = await browser.new_context()
            attach_protection_listener(ctx)  # V0.47.1 listener 装 ctx
            page = await ctx.new_page()
            await apply_stealth(page)
            await apply_stealth_plus(page)
            visits: list[dict[str, Any]] = []
            for i in range(_VISITS_PER_TARGET):
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                except Exception as e:
                    if i == 0:
                        pytest.skip(f"{domain} unreachable on visit 0 ({type(e).__name__}: {e})")
                    # 中途失败 — record skip 但继续 (中途 escalate 后 server 拦截也是 signal)
                    visits.append({"visit_idx": i, "level": "unknown", "signal": None,
                                   "error": f"{type(e).__name__}: {e}"})
                    continue
                await page.wait_for_timeout(_VISIT_INTERVAL_MS)  # polite 节奏
                visits.append(_record_visit(ctx, i))
        finally:
            await browser.close()

    cassette_path = _dump_cassette(domain, visits)
    # V0.48.2 maintainer 跑完后 escalated() 自动判 retain/sink (不 assert in test, 数据看 cassette)
    assert cassette_path.exists()
    assert len(visits) == _VISITS_PER_TARGET, (
        f"V0.48.2 {domain}: 期望 {_VISITS_PER_TARGET} visit, 实际 {len(visits)}"
    )
