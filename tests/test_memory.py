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


# ---------- V0.28.1 W6-A: reflections 表 + record_reflection / recall_reflections_by_domain ----------


def test_init_reflections_db_creates_table_and_index_when_missing(tmp_path):
    """V0.28.1: db 不存在时, init_reflections_db 自动建 reflections 表 + idx_reflections_domain_ts."""
    from web_agent.memory import init_reflections_db

    db = tmp_path / "fresh.db"
    assert not db.exists()
    conn = init_reflections_db(db)
    try:
        # 表存在
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reflections'"
        ).fetchall()
        assert len(rows) == 1
        # index 存在
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_reflections_domain_ts'"
        ).fetchall()
        assert len(rows) == 1
    finally:
        conn.close()


def test_record_reflection_round_trip(tmp_path):
    """V0.28.1: record_reflection 写 → recall_reflections_by_domain 读对称."""
    from web_agent.memory import record_reflection, recall_reflections_by_domain

    db = tmp_path / "memory.db"
    record_reflection(
        db_path=db, task_id="t1", domain="x.test",
        goal="抓取首页 H1", final_result="(max_steps 耗尽未完成)",
        root_cause="页面加载慢", hint="下次先 wait_for_selector",
    )
    rows = recall_reflections_by_domain(db, "x.test")
    assert len(rows) == 1
    r = rows[0]
    assert r.task_id == "t1"
    assert r.domain == "x.test"
    assert r.goal == "抓取首页 H1"
    assert r.final_result == "(max_steps 耗尽未完成)"
    assert r.root_cause == "页面加载慢"
    assert r.hint == "下次先 wait_for_selector"


def test_recall_reflections_by_domain_returns_desc_by_ts(tmp_path):
    """V0.28.1: recall_reflections_by_domain 按 ts DESC 排, 限 limit."""
    from web_agent.memory import record_reflection, recall_reflections_by_domain

    db = tmp_path / "memory.db"
    for i in range(5):
        record_reflection(
            db_path=db, task_id=f"t{i}", domain="x.test",
            goal=f"goal {i}", final_result="r",
            root_cause=f"rc {i}", hint=f"hint {i}",
        )
        time.sleep(0.001)  # ts 递增防 tie

    rows = recall_reflections_by_domain(db, "x.test", limit=3)
    assert len(rows) == 3
    # DESC: 最新的 t4 在 [0]
    assert rows[0].task_id == "t4"
    assert rows[1].task_id == "t3"
    assert rows[2].task_id == "t2"


def test_recall_reflections_by_domain_db_missing_returns_empty(tmp_path):
    """V0.28.1: db 不存在 → 返 [] (不抛, 跟 recall_by_domain 同模式)."""
    from web_agent.memory import recall_reflections_by_domain

    db = tmp_path / "nonexistent.db"
    assert not db.exists()
    assert recall_reflections_by_domain(db, "any.test") == []


def test_record_reflection_truncates_long_fields(tmp_path):
    """V0.28.1: RESULT_TRUNC=200 字段防 LLM 万言反思撑爆 db."""
    from web_agent.memory import record_reflection, recall_reflections_by_domain

    db = tmp_path / "memory.db"
    long_str = "x" * 500
    record_reflection(
        db_path=db, task_id="t", domain="x.test",
        goal=long_str, final_result=long_str,
        root_cause=long_str, hint=long_str,
    )
    r = recall_reflections_by_domain(db, "x.test")[0]
    assert len(r.goal) == 200
    assert len(r.final_result) == 200
    assert len(r.root_cause) == 200
    assert len(r.hint) == 200


# ---------- V0.28.2 W6-B: format_reflections_for_trace (W5-D.2 平行) ----------


def test_format_reflections_empty_returns_empty_string():
    """V0.28.2: empty list → '' (caller 可 if-truthy 跳 inject)."""
    from web_agent.memory import format_reflections_for_trace
    assert format_reflections_for_trace([]) == ""


def test_format_reflections_renders_hint_and_truncates(tmp_path):
    """V0.28.2: 多条 + 长 hint 截到 hint_trunc=120 (V0.28.2 默)."""
    from web_agent.memory import (
        ReflectionEntry,
        format_reflections_for_trace,
    )
    long_hint = "h" * 200
    entries = [
        ReflectionEntry(
            ts=time.time(), task_id="t1", domain="x.test",
            goal="g", final_result="r", root_cause="rc1", hint=long_hint,
        ),
        ReflectionEntry(
            ts=time.time(), task_id="t2", domain="x.test",
            goal="g2", final_result="r2", root_cause="rc2", hint="short",
        ),
    ]
    out = format_reflections_for_trace(entries)
    assert "上次在该 domain 失败教训" in out
    assert "共 2 条" in out
    assert "rc1 →" in out
    assert "rc2 →" in out
    assert "short" in out
    # 长 hint 截到 120
    assert "h" * 120 in out
    assert "h" * 121 not in out
