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


# ---------- V0.28.3 W6 收尾: build_inject_string + clear_reflections (cli + eval 共用 helper) ----------


def test_build_inject_string_memories_only(tmp_path):
    """V0.28.3: include_memories=True + include_reflections=False → 只 memories 段."""
    from web_agent.memory import build_inject_string, record_task

    db = tmp_path / "memory.db"
    record_task(db, "x.test", "g1", "result1", success=True)
    out = build_inject_string(db, "x.test", include_memories=True, include_reflections=False)
    assert out is not None
    assert "过去在该 domain 跑过" in out
    assert "失败教训" not in out


def test_build_inject_string_reflections_only(tmp_path):
    """V0.28.3: include_reflections=True + include_memories=False → 只 reflections 段."""
    from web_agent.memory import build_inject_string, record_reflection

    db = tmp_path / "memory.db"
    record_reflection(
        db, task_id="t1", domain="x.test", goal="g", final_result="(max_steps)",
        root_cause="rc", hint="h",
    )
    out = build_inject_string(db, "x.test", include_memories=False, include_reflections=True)
    assert out is not None
    assert "失败教训" in out
    assert "rc → h" in out
    assert "过去在该 domain 跑过" not in out


def test_build_inject_string_both_concatenated(tmp_path):
    """V0.28.3: 双 True → memories 在前 + reflections 在后 (双 \\n\\n 分隔)."""
    from web_agent.memory import build_inject_string, record_reflection, record_task

    db = tmp_path / "memory.db"
    record_task(db, "x.test", "g1", "result1", success=True)
    record_reflection(db, task_id="t1", domain="x.test", goal="g",
                      final_result="(max_steps)", root_cause="rc", hint="h")
    out = build_inject_string(db, "x.test")
    assert out is not None
    mem_idx = out.index("过去在该 domain")
    refl_idx = out.index("失败教训")
    assert mem_idx < refl_idx, "memories 在前 reflections 在后"


def test_build_inject_string_both_disabled_returns_none(tmp_path):
    """V0.28.3: 双 False / 两 db 都空 → None (caller 可 if-truthy 跳)."""
    from web_agent.memory import build_inject_string

    db = tmp_path / "memory.db"
    assert build_inject_string(db, "x.test", include_memories=False, include_reflections=False) is None
    assert build_inject_string(db, "missing.test") is None  # db 不存在


def test_clear_reflections_deletes_all_rows(tmp_path):
    """V0.28.3 Risk #1 修: eval 跨 task 跑前清 reflections 表防 domain 污染."""
    from web_agent.memory import (
        clear_reflections,
        recall_reflections_by_domain,
        record_reflection,
    )

    db = tmp_path / "memory.db"
    for i in range(3):
        record_reflection(db, task_id=f"t{i}", domain="x.test",
                          goal="g", final_result="r", root_cause="rc", hint=f"h{i}")
    assert len(recall_reflections_by_domain(db, "x.test")) == 3

    clear_reflections(db)

    assert recall_reflections_by_domain(db, "x.test") == []


def test_clear_reflections_db_missing_silent(tmp_path):
    """V0.28.3: db 不存在 → silent (跟 recall 同模式)."""
    from web_agent.memory import clear_reflections

    db = tmp_path / "nonexistent.db"
    clear_reflections(db)  # 不抛


# ---------- V0.41.0 C 主题: domain success-rate aggregator ----------


def test_v041_aggregate_domain_stats_basic(tmp_path):
    """V0.41.0: 5 task 3 success → pass_rate=0.6, total=5."""
    from web_agent.memory import aggregate_domain_stats

    db = tmp_path / "memory.db"
    record_task(db, "wiki.test", "g1", "r1", True)
    record_task(db, "wiki.test", "g2", "r2", True)
    record_task(db, "wiki.test", "g3", "r3", True)
    record_task(db, "wiki.test", "g4", "r4", False)
    record_task(db, "wiki.test", "g5", "r5", False)
    stats = aggregate_domain_stats(db, "wiki.test")
    assert stats is not None
    assert stats.total == 5
    assert stats.success == 3
    assert stats.pass_rate == 0.6
    assert stats.recent_n_days == 30
    assert stats.last_ts > 0


def test_v041_aggregate_domain_stats_below_threshold_returns_none(tmp_path):
    """V0.41.0: total < 3 → None (信号不足不 inject, 防 1-2 task 算不出可靠 pass rate)."""
    from web_agent.memory import aggregate_domain_stats

    db = tmp_path / "memory.db"
    record_task(db, "wiki.test", "g1", "r1", True)
    record_task(db, "wiki.test", "g2", "r2", True)
    assert aggregate_domain_stats(db, "wiki.test") is None


def test_v041_aggregate_domain_stats_db_not_exist_returns_none(tmp_path):
    """V0.41.0: db 不存在 → None (silent, 跟 recall_by_domain 同 pattern)."""
    from web_agent.memory import aggregate_domain_stats

    assert aggregate_domain_stats(tmp_path / "nonexistent.db", "wiki.test") is None


def test_v041_aggregate_domain_stats_empty_domain_returns_none(tmp_path):
    """V0.41.0: domain='' → None (避真发现 #21 生产 db 625 行空 domain 测试污染聚合)."""
    from web_agent.memory import aggregate_domain_stats

    db = tmp_path / "memory.db"
    for i in range(5):
        record_task(db, "", f"g{i}", f"r{i}", True)  # 625 行污染模拟
    assert aggregate_domain_stats(db, "") is None
    assert aggregate_domain_stats(db, "   ") is None  # whitespace-only 同视空


def test_v041_aggregate_domain_stats_recent_filter(tmp_path):
    """V0.41.0: recent_days 锁查询窗口, 老于 30 天 task 不算 (防 90 天前老数据稀释 recent signal)."""
    import time as time_module

    from web_agent.memory import aggregate_domain_stats, init_memory_db

    db = tmp_path / "memory.db"
    now = time_module.time()
    old_ts = now - 60 * 86400
    recent_ts = now - 5 * 86400
    conn = init_memory_db(db)
    try:
        for i in range(5):
            conn.execute(
                "INSERT INTO memories (ts, domain, goal, result, success) VALUES (?, ?, ?, ?, ?)",
                (old_ts, "wiki.test", f"old{i}", f"r{i}", 1),
            )
        for i in range(3):
            conn.execute(
                "INSERT INTO memories (ts, domain, goal, result, success) VALUES (?, ?, ?, ?, ?)",
                (recent_ts, "wiki.test", f"new{i}", f"r{i}", 0),
            )
        conn.commit()
    finally:
        conn.close()
    stats = aggregate_domain_stats(db, "wiki.test", recent_days=30)
    assert stats is not None
    assert stats.total == 3
    assert stats.success == 0


def test_v041_format_domain_stats_for_trace_renders(tmp_path):
    """V0.41.0: 格式 '本 domain 最近 N 天历史 X task, P% pass rate (last seen YYYY-MM-DD)'."""
    from web_agent.memory import aggregate_domain_stats, format_domain_stats_for_trace

    db = tmp_path / "memory.db"
    for i in range(5):
        record_task(db, "wiki.test", f"g{i}", f"r{i}", i < 3)
    stats = aggregate_domain_stats(db, "wiki.test")
    rendered = format_domain_stats_for_trace(stats)
    assert "本 domain" in rendered
    assert "30 天" in rendered
    assert "5 task" in rendered
    assert "60%" in rendered  # 3/5 = 60% pass
    assert "last seen" in rendered


def test_v041_format_domain_stats_none_returns_empty():
    """V0.41.0: None stats → '' (caller if-truthy 跳 inject)."""
    from web_agent.memory import format_domain_stats_for_trace

    assert format_domain_stats_for_trace(None) == ""


def test_v041_build_inject_string_includes_stats_prefix(tmp_path):
    """V0.41.0: build_inject_string prepend domain stats 行 (在 5 条 raw memory 前)."""
    from web_agent.memory import build_inject_string

    db = tmp_path / "memory.db"
    for i in range(5):
        record_task(db, "wiki.test", f"g{i}", f"r{i}", i < 3)
    out = build_inject_string(db, "wiki.test")
    assert out is not None
    stats_idx = out.find("本 domain 最近")
    memories_idx = out.find("过去在该 domain")
    assert stats_idx >= 0, "stats prefix 必出现"
    assert memories_idx > stats_idx, "stats 必在 memories raw 前"
