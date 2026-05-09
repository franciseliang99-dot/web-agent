"""V0.20.0 jd_extract module tests — db / rate-limit / upsert.

不覆盖 LLM extract / Playwright 路径 (依赖外部); 这两块靠 e2e 真实跑验证.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from web_agent.jd_extract import (
    RATE_LIMIT_SESSION_CAP,
    _url_match,
    check_rate_limit,
    init_upwork_db,
    parse_jd_result,
    upsert_jd,
)


def _row(url: str, scraped_at: float, **extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "url": url,
        "scraped_at": scraped_at,
        "title": "test job",
        "description": "test body",
        "budget": None,
        "hourly": None,
        "client_country": None,
        "client_rating": None,
        "posted_at": None,
        "proposals_count": None,
        "connect_cost": None,
        "raw_thought": None,
    }
    base.update(extra)
    return base


def test_init_upwork_db_idempotent(tmp_path: Path) -> None:
    """连建两次不报错, 表结构含 url/score/recommendation 关键列."""
    db = tmp_path / "test.db"
    conn1 = init_upwork_db(db)
    conn1.close()
    conn2 = init_upwork_db(db)
    cols = [r[1] for r in conn2.execute("PRAGMA table_info(upwork_jds)").fetchall()]
    assert "url" in cols
    assert "score" in cols
    assert "recommendation" in cols
    assert "fit_json" in cols
    conn2.close()


def test_check_rate_limit_empty_db_passes(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    conn = init_upwork_db(db)
    check_rate_limit(conn)  # no rows → no raise
    conn.close()


def test_check_rate_limit_under_60s_blocks(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    conn = init_upwork_db(db)
    now = time.time()
    upsert_jd(conn, _row("https://upwork.com/x1", now - 30))
    with pytest.raises(SystemExit, match="rate-limit"):
        check_rate_limit(conn, now=now)
    conn.close()


def test_check_rate_limit_after_60s_passes(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    conn = init_upwork_db(db)
    now = time.time()
    upsert_jd(conn, _row("https://upwork.com/x1", now - 70))
    check_rate_limit(conn, now=now)  # > 60s → no raise
    conn.close()


def test_check_rate_limit_session_cap_blocks(tmp_path: Path) -> None:
    """30min 窗口内 30 行 (全 5min 前, 都 > 60s 间隔) → session-cap 拒."""
    db = tmp_path / "test.db"
    conn = init_upwork_db(db)
    now = time.time()
    for i in range(RATE_LIMIT_SESSION_CAP):
        upsert_jd(conn, _row(f"https://upwork.com/x{i}", now - 300))
    with pytest.raises(SystemExit, match="session-cap"):
        check_rate_limit(conn, now=now)
    conn.close()


def test_check_rate_limit_old_rows_outside_window(tmp_path: Path) -> None:
    """31min 前的旧 row 不计入 session window cap."""
    db = tmp_path / "test.db"
    conn = init_upwork_db(db)
    now = time.time()
    # 30 行全部 31min 前 (滚动窗口外) + 1 行 70s 前 (窗口内但 > 60s 间隔)
    for i in range(RATE_LIMIT_SESSION_CAP):
        upsert_jd(conn, _row(f"https://upwork.com/old{i}", now - 31 * 60))
    upsert_jd(conn, _row("https://upwork.com/recent", now - 70))
    check_rate_limit(conn, now=now)  # 应该 pass: 窗口内只 1 行, 上次 70s > 60s
    conn.close()


def test_upsert_jd_new_row(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    conn = init_upwork_db(db)
    upsert_jd(conn, _row(
        "https://upwork.com/abc", 1000.0,
        title="Test JD", hourly=1, client_rating=4.8, client_country="US",
    ))
    row = conn.execute(
        "SELECT url, title, hourly, client_rating, client_country "
        "FROM upwork_jds WHERE url=?",
        ("https://upwork.com/abc",),
    ).fetchone()
    assert row == ("https://upwork.com/abc", "Test JD", 1, 4.8, "US")
    conn.close()


def test_upsert_jd_conflict_preserves_score(tmp_path: Path) -> None:
    """同 url 重 upsert: 字段刷新, id 保留, score/recommendation/fit_json 不被覆盖 (UPSERT 不写 score 字段)."""
    db = tmp_path / "test.db"
    conn = init_upwork_db(db)
    upsert_jd(conn, _row("https://upwork.com/y", 1000.0, title="old"))
    id1 = conn.execute(
        "SELECT id FROM upwork_jds WHERE url=?", ("https://upwork.com/y",)
    ).fetchone()[0]

    # score_upwork.py 模拟写入 score
    conn.execute(
        "UPDATE upwork_jds SET score=85, recommendation='draft', fit_json='{}' "
        "WHERE url=?",
        ("https://upwork.com/y",),
    )
    conn.commit()

    # 重新 extract 同一 URL
    upsert_jd(conn, _row("https://upwork.com/y", 2000.0, title="new"))

    row = conn.execute(
        "SELECT id, title, scraped_at, score, recommendation FROM upwork_jds "
        "WHERE url=?",
        ("https://upwork.com/y",),
    ).fetchone()
    assert row[0] == id1
    assert row[1] == "new"
    assert row[2] == 2000.0
    assert row[3] == 85
    assert row[4] == "draft"
    conn.close()


# ===== V0.20.4: parse_jd_result 三层 fallback tests =====


def test_parse_strict_json() -> None:
    """Layer 1: 严格 JSON 直接 parse."""
    parsed = parse_jd_result('{"title": "Test", "description": "body"}')
    assert parsed["title"] == "Test"
    assert parsed["description"] == "body"


def test_parse_md_code_block() -> None:
    """Layer 2: ```json ... ``` fence 包裹的 JSON."""
    result = '好的, JSON 是:\n```json\n{"title": "Test"}\n```\n完成.'
    parsed = parse_jd_result(result)
    assert parsed["title"] == "Test"


def test_parse_bare_brace() -> None:
    """Layer 3: LLM prose 前后包裹的裸 {} block."""
    result = 'JSON: {"title": "Test", "budget": null} 完成.'
    parsed = parse_jd_result(result)
    assert parsed["title"] == "Test"
    assert parsed["budget"] is None


def test_parse_loop_error_sentinel_raises() -> None:
    """run_react_loop 6 sentinel 字符串识别 → SystemExit (jd extract aborted)."""
    sentinels = (
        "CAPTCHA_TIMEOUT at step 0: cloudflare 未在 300s 内解决",
        "WALLCLOCK_EXCEEDED at step 5: 超 max_wallclock_s",
        "LOOP_DETECTED 在 step 3: 连续 3+ 次同一 action",
        "(max_steps 耗尽未完成)",
        "SAFETY_BLOCK at step 2: send-or-pay rule",
        "LLM_FAILED at step 1: APIError",
    )
    for s in sentinels:
        with pytest.raises(SystemExit, match="aborted"):
            parse_jd_result(s)


def test_parse_garbage_raises() -> None:
    """完全不是 JSON 也不含 sentinel → SystemExit."""
    with pytest.raises(SystemExit, match="不是 JSON"):
        parse_jd_result("这是一段普通文字, 没有 JSON.")


def test_parse_non_dict_top_raises() -> None:
    """JSON 顶层不是 object (list/scalar) → SystemExit."""
    with pytest.raises(SystemExit, match="顶层不是 object"):
        parse_jd_result('["a", "b"]')
    with pytest.raises(SystemExit, match="顶层不是 object"):
        parse_jd_result('"just a string"')


# ===== V0.20.5: _url_match URL normalization tests =====


def test_url_match_exact() -> None:
    """exact match (含 https + 同 host + 同 path)."""
    assert _url_match(
        "https://www.upwork.com/jobs/~01abc",
        "https://www.upwork.com/jobs/~01abc",
    )


def test_url_match_query_string_diff_passes() -> None:
    """用户贴 clean URL, Chrome page.url 含 tracking query → 仍 match (path 同)."""
    assert _url_match(
        "https://www.upwork.com/jobs/~01abc",
        "https://www.upwork.com/jobs/~01abc?pageTitle=foo&utm_source=email",
    )


def test_url_match_host_diff_rejects() -> None:
    """path 同但 host 不同 (eg upwork.com vs upwork.fr) → 不同 JD."""
    assert not _url_match(
        "https://www.upwork.com/jobs/~01abc",
        "https://www.upwork.fr/jobs/~01abc",
    )


def test_url_match_fragment_ignored() -> None:
    """fragment (#proposals 等) 不影响 match."""
    assert _url_match(
        "https://www.upwork.com/jobs/~01abc",
        "https://www.upwork.com/jobs/~01abc#proposals",
    )


def test_url_match_trailing_slash_normalized() -> None:
    """trailing slash 兜 /jobs/~01abc vs /jobs/~01abc/ — 同 JD."""
    assert _url_match(
        "https://www.upwork.com/jobs/~01abc",
        "https://www.upwork.com/jobs/~01abc/",
    )
