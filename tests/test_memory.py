"""W5-D 长期记忆 MVP 单测: extract_domain / is_success / init_memory_db / record / recall / main CLI."""

from __future__ import annotations

import time

import pytest

from web_agent.memory import (
    FAILURE_MARKERS,
    MemoryEntry,
    extract_domain,
    format_memories_for_trace,
    init_memory_db,
    is_success,
    main,
    recall_by_domain,
    record_task,
)


# ---------- extract_domain ----------

@pytest.mark.parametrize("url,expected", [
    ("https://github.com/foo/bar", "github.com"),
    ("https://example.com:8080/path", "example.com:8080"),
    ("HTTPS://Example.COM/x", "example.com"),  # lowercase 归一
    ("", ""),
    (None, ""),
    ("about:blank", ""),
    ("javascript:alert(1)", ""),
])
def test_extract_domain(url, expected):
    assert extract_domain(url) == expected


# ---------- is_success ----------

@pytest.mark.parametrize("result,success", [
    ("repo: foo/bar, stars: 1k", True),  # 正常结果
    ("量子纠缠是量子力学中...", True),
    ("", False),  # 空 result 视为 fail (防御)
    ("(max_steps 耗尽未完成)", False),
    ("WALLCLOCK_EXCEEDED at step 3: ...", False),
    ("SAFETY_BLOCK at step 0: send-or-pay", False),
    ("CAPTCHA_TIMEOUT at step 1: cloudflare", False),
    ("LOOP_DETECTED 在 step 5: ...", False),
    ("LLM_FAILED at step 2: RuntimeError", False),
])
def test_is_success(result, success):
    assert is_success(result) is success


def test_failure_markers_align_with_loop_signals():
    """守约束: FAILURE_MARKERS 与 loop.py 内 graceful abort 字符串前缀对齐。"""
    assert "(max_steps" in FAILURE_MARKERS
    assert "WALLCLOCK_EXCEEDED" in FAILURE_MARKERS
    assert "SAFETY_BLOCK" in FAILURE_MARKERS
    assert "CAPTCHA_TIMEOUT" in FAILURE_MARKERS
    assert "LOOP_DETECTED" in FAILURE_MARKERS
    assert "LLM_FAILED" in FAILURE_MARKERS


# ---------- init_memory_db ----------

def test_init_memory_db_creates_table_and_index(tmp_path):
    db = tmp_path / "memory.db"
    conn = init_memory_db(db)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "memories" in tables
    indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()}
    assert "idx_memories_domain_ts" in indexes
    conn.close()


def test_init_memory_db_creates_parent_dir(tmp_path):
    db = tmp_path / "nested" / "memory.db"
    init_memory_db(db).close()
    assert db.exists()


# ---------- record_task + recall_by_domain ----------

def test_record_and_recall_returns_inserted_entry(tmp_path):
    db = tmp_path / "memory.db"
    record_task(db, "github.com", "搜 web agent", "repo: x/y, stars: 1k", True)

    entries = recall_by_domain(db, "github.com", limit=5)
    assert len(entries) == 1
    e = entries[0]
    assert isinstance(e, MemoryEntry)
    assert e.domain == "github.com"
    assert e.goal == "搜 web agent"
    assert e.result == "repo: x/y, stars: 1k"
    assert e.success is True
    assert isinstance(e.ts, float) and e.ts > 0


def test_recall_orders_by_ts_desc(tmp_path):
    db = tmp_path / "memory.db"
    record_task(db, "x.com", "old goal", "ok", True)
    time.sleep(0.01)  # 保 ts 严格不同
    record_task(db, "x.com", "newer goal", "ok", True)
    time.sleep(0.01)
    record_task(db, "x.com", "newest goal", "fail", False)

    entries = recall_by_domain(db, "x.com")
    assert [e.goal for e in entries] == ["newest goal", "newer goal", "old goal"]
    assert entries[0].success is False
    assert entries[1].success is True


def test_recall_filters_by_domain(tmp_path):
    db = tmp_path / "memory.db"
    record_task(db, "a.com", "g_a", "ok", True)
    record_task(db, "b.com", "g_b", "ok", True)

    a_entries = recall_by_domain(db, "a.com")
    b_entries = recall_by_domain(db, "b.com")
    assert len(a_entries) == 1 and a_entries[0].goal == "g_a"
    assert len(b_entries) == 1 and b_entries[0].goal == "g_b"


def test_recall_respects_limit(tmp_path):
    db = tmp_path / "memory.db"
    for i in range(7):
        record_task(db, "x.com", f"g{i}", "ok", True)
    entries = recall_by_domain(db, "x.com", limit=3)
    assert len(entries) == 3


def test_recall_missing_db_returns_empty_list(tmp_path):
    """db 不存在不该抛 — 友好兜底用于首次跑还没 record 时的查询。"""
    db = tmp_path / "noexist.db"
    assert recall_by_domain(db, "any.com") == []


def test_record_truncates_long_result(tmp_path):
    db = tmp_path / "memory.db"
    long_result = "x" * 500
    record_task(db, "x.com", "g", long_result, True)
    entries = recall_by_domain(db, "x.com")
    assert len(entries[0].result) == 200  # RESULT_TRUNC


# ---------- main CLI ----------

def test_main_dumps_entries(tmp_path, capsys):
    db = tmp_path / "memory.db"
    record_task(db, "test.com", "g1", "ok", True)
    record_task(db, "test.com", "g2", "SAFETY_BLOCK at step 0: ...", False)

    rc = main(["test.com", "--db", str(db)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "test.com" in out
    assert "g1" in out
    assert "g2" in out
    assert "OK" in out
    assert "FAIL" in out


def test_main_no_memories_for_domain(tmp_path, capsys):
    db = tmp_path / "memory.db"
    init_memory_db(db).close()  # 表存在但空
    rc = main(["nope.com", "--db", str(db)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no memories" in out


# ---------- W5-D.2 format_memories_for_trace ----------

def test_format_memories_empty_returns_empty_string():
    assert format_memories_for_trace([]) == ""


def test_format_memories_renders_ok_fail_and_truncates():
    entries = [
        MemoryEntry(ts=1700000000.0, domain="x.com",
                    goal="搜 web agent", result="repo: x/y, stars: 1k", success=True),
        MemoryEntry(ts=1699900000.0, domain="x.com",
                    goal="发邮件", result="WALLCLOCK_EXCEEDED at step 5: ...", success=False),
        MemoryEntry(ts=1699800000.0, domain="x.com",
                    goal="x" * 100,  # 长 goal 待截断
                    result="y" * 200,  # 长 result 待截断
                    success=True),
    ]
    out = format_memories_for_trace(entries)

    assert "过去在该 domain 跑过 3 个任务" in out
    assert out.count("OK") >= 2
    assert out.count("FAIL") == 1
    assert "WALLCLOCK_EXCEEDED" in out  # FAIL marker 透传给 LLM
    # 长 goal 截到 60, 长 result 截到 80 (default trunc)
    assert "x" * 60 in out and "x" * 61 not in out
    assert "y" * 80 in out and "y" * 81 not in out
