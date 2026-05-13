"""V0.69 navigation side-effect detection — TDD red.

V0.68 dogfood (Supabase Dashboard) 发现 type "https://vanboard.vercel.app"
后页面 React-effect 跳到 Policies, LLM 下一步 perceive 在 wrong page 决策。
方案: Step 加 url_before / url_after, for_llm 仅当变化时追加 nav_side_effect,
LLM trace 历史段自然看见因果归因。
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from web_agent.trace import Step, init_db, write_step


def _make_step(**overrides):
    base = {
        "step": 0,
        "ts": 1234.5,
        "thought": "test",
        "action_type": "type",
        "action_args": {"text": "abc"},
    }
    base.update(overrides)
    return Step(**base)


def test_step_default_url_fields_empty():
    """Step 默认 url_before / url_after 为 "" (向后兼容: 老 caller 不传)."""
    s = _make_step()
    assert s.url_before == ""
    assert s.url_after == ""


def test_step_for_llm_no_nav_side_effect_when_urls_equal():
    """url_before == url_after → for_llm 不出 nav_side_effect (不污染 LLM context)."""
    s = _make_step(url_before="https://example.com/", url_after="https://example.com/")
    d = s.for_llm()
    assert "nav_side_effect" not in d


def test_step_for_llm_no_nav_side_effect_when_both_empty():
    """默认空字符串 → 不出 nav_side_effect (老 trace 兼容)."""
    s = _make_step()
    d = s.for_llm()
    assert "nav_side_effect" not in d


def test_step_for_llm_adds_nav_side_effect_when_url_changed():
    """url_before != url_after → for_llm 含 nav_side_effect 字段, 值含 X / Y 两 URL."""
    s = _make_step(
        url_before="https://supabase.com/dashboard/project/x/auth/url-configuration",
        url_after="https://supabase.com/dashboard/project/x/auth/policies",
    )
    d = s.for_llm()
    assert "nav_side_effect" in d
    val = d["nav_side_effect"]
    assert "url-configuration" in val
    assert "policies" in val


def test_init_db_creates_url_before_after_columns():
    """新 db CREATE TABLE 含 url_before / url_after 列."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "trace.db"
        conn = init_db(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(steps)")}
        assert "url_before" in cols
        assert "url_after" in cols
        conn.close()


def test_init_db_alter_url_columns_idempotent():
    """老 db (无 url 列) 跑 init_db 应 ALTER 加列, 二次跑不抛."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "trace.db"
        # 手造老 schema (缺 url_before / url_after)
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE steps (task_id TEXT, step INTEGER, ts REAL, "
            "thought TEXT, action_type TEXT, action_args TEXT, "
            "screenshot_path TEXT, observation TEXT, "
            "PRIMARY KEY (task_id, step))"
        )
        conn.commit()
        conn.close()
        # 首次 init_db: ALTER 加列
        conn = init_db(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(steps)")}
        assert "url_before" in cols
        assert "url_after" in cols
        conn.close()
        # 二次 init_db: 列已存, 不抛
        conn = init_db(db)
        conn.close()  # 不抛即通过


def test_write_step_persists_url_fields_round_trip():
    """write_step 把 url_before / url_after 写入 db, SELECT 能读回."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "trace.db"
        conn = init_db(db)
        s = _make_step(
            url_before="https://a.com/page1",
            url_after="https://b.com/page2",
        )
        write_step(conn, "task-1", s)
        row = conn.execute(
            "SELECT url_before, url_after FROM steps WHERE task_id=? AND step=?",
            ("task-1", 0),
        ).fetchone()
        assert row == ("https://a.com/page1", "https://b.com/page2")
        conn.close()
