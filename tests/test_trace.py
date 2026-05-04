"""trace.py 持久化层单测 (audit gap 填补 — V0.5.0 来 0 单测)。

覆盖: init_db / start_task / end_task / write_step / Step.for_llm / Trace.append+for_llm
全用 stdlib (sqlite3 + tmp_path), 直连 sqlite 验副作用 (与 test_replay.py 同风格)。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from web_agent.trace import (
    Step,
    Trace,
    end_task,
    init_db,
    start_task,
    write_step,
)


def _open_db(tmp_path: Path) -> sqlite3.Connection:
    """共用 helper: tmp_path/trace.db init_db 后返回 conn。"""
    return init_db(tmp_path / "trace.db")


# ---------- init_db ----------

def test_init_db_creates_tasks_and_steps_tables(tmp_path):
    conn = _open_db(tmp_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "tasks" in tables
    assert "steps" in tables
    # tasks PK = task_id
    cols = {r[1]: r[5] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    assert cols["task_id"] == 1, "task_id 应是 tasks PK"
    # steps PK = (task_id, step) — pk=1/2 表示 composite
    step_cols = {r[1]: r[5] for r in conn.execute("PRAGMA table_info(steps)").fetchall()}
    assert step_cols["task_id"] >= 1 and step_cols["step"] >= 1, "steps PK 应是 (task_id, step)"
    conn.close()


def test_init_db_creates_parent_dir(tmp_path):
    db = tmp_path / "nested" / "deeper" / "trace.db"
    conn = init_db(db)
    assert db.exists()
    assert db.parent.is_dir()
    conn.close()


def test_init_db_idempotent_second_call_no_raise(tmp_path):
    db = tmp_path / "trace.db"
    conn1 = init_db(db)
    conn1.close()
    conn2 = init_db(db)  # CREATE TABLE IF NOT EXISTS 不抛
    tables = {r[0] for r in conn2.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"tasks", "steps"} <= tables
    conn2.close()


# ---------- start_task / end_task ----------

def test_start_task_inserts_row_with_chinese_goal_and_float_ts(tmp_path):
    conn = _open_db(tmp_path)
    t0 = time.time()
    start_task(conn, "t1", "搜索量子纠缠")
    row = conn.execute(
        "SELECT task_id, goal, started_at, ended_at, result FROM tasks WHERE task_id=?", ("t1",)
    ).fetchone()
    conn.close()
    assert row[0] == "t1"
    assert row[1] == "搜索量子纠缠"  # 中文不转义
    assert isinstance(row[2], float)
    assert abs(row[2] - t0) < 10.0  # ±10s 防慢 CI flaky
    assert row[3] is None  # ended_at NULL
    assert row[4] is None  # result NULL


def test_end_task_updates_ended_at_and_result(tmp_path):
    conn = _open_db(tmp_path)
    start_task(conn, "t1", "g")
    started_at = conn.execute("SELECT started_at FROM tasks WHERE task_id='t1'").fetchone()[0]
    end_task(conn, "t1", "OK")
    row = conn.execute(
        "SELECT ended_at, result FROM tasks WHERE task_id='t1'"
    ).fetchone()
    conn.close()
    assert isinstance(row[0], float)
    assert row[0] >= started_at
    assert row[1] == "OK"


def test_end_task_missing_id_does_not_raise(tmp_path):
    """trace.py 用 raw UPDATE WHERE task_id, 不存在时 0 行影响; loop.py 容错语义保护。"""
    conn = _open_db(tmp_path)
    end_task(conn, "no_such_task", "should not raise")  # 不抛
    # tasks 表仍空
    cnt = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert cnt == 0
    conn.close()


# ---------- write_step ----------

def test_write_step_inserts_row_with_all_fields(tmp_path):
    conn = _open_db(tmp_path)
    s = Step(
        step=0, ts=1234567890.5, thought="t",
        action_type="click", action_args={"mark_id": 3},
        observation="clicked",
    )
    write_step(conn, "t1", s, "data/screenshots/t1-00.png")
    row = conn.execute(
        "SELECT task_id, step, ts, thought, action_type, action_args, screenshot_path, observation "
        "FROM steps WHERE task_id='t1' AND step=0"
    ).fetchone()
    conn.close()
    assert row[0] == "t1"
    assert row[1] == 0
    assert row[2] == 1234567890.5
    assert row[3] == "t"
    assert row[4] == "click"
    assert json.loads(row[5]) == {"mark_id": 3}
    assert row[6] == "data/screenshots/t1-00.png"
    assert row[7] == "clicked"


def test_write_step_chinese_args_not_ascii_escaped(tmp_path):
    """ensure_ascii=False — 中文应直接落字符不是 \\uXXXX 转义 (replay/grep 友好)。"""
    conn = _open_db(tmp_path)
    s = Step(step=0, ts=0.0, thought="x", action_type="type",
             action_args={"text": "搜索量子纠缠"}, observation="typed")
    write_step(conn, "t1", s)
    raw = conn.execute(
        "SELECT action_args FROM steps WHERE task_id='t1' AND step=0"
    ).fetchone()[0]
    conn.close()
    assert "搜索量子纠缠" in raw, f"中文应直接落, 实际: {raw!r}"
    assert "\\u" not in raw  # 不该被 ascii 转义


def test_write_step_replace_on_duplicate_pk(tmp_path):
    """INSERT OR REPLACE 语义: 同 (task_id, step) 二次写应覆盖。"""
    conn = _open_db(tmp_path)
    write_step(conn, "t1", Step(step=0, ts=0.0, thought="first", action_type="click", action_args={}))
    write_step(conn, "t1", Step(step=0, ts=0.0, thought="second", action_type="click", action_args={}))
    rows = conn.execute(
        "SELECT thought FROM steps WHERE task_id='t1' AND step=0"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "second"


# ---------- Step.for_llm ----------

def test_step_for_llm_truncates_observation_at_200_chars():
    s = Step(step=0, ts=0.0, thought="t", action_type="click",
             action_args={"mark_id": 1}, observation="x" * 500)
    out = s.for_llm()
    assert len(out["observation"]) == 200  # 硬编码阈值回归保护
    assert out["observation"] == "x" * 200


def test_step_for_llm_short_observation_unchanged_and_includes_keys():
    s = Step(step=2, ts=0.0, thought="quick think", action_type="type",
             action_args={"text": "hi"}, observation="ok")
    out = s.for_llm()
    assert out["observation"] == "ok"
    assert out["step"] == 2
    assert out["thought"] == "quick think"
    assert out["action"] == {"type": "type", "text": "hi"}  # action_args 展开到 action dict


# ---------- Trace ----------

def test_trace_append_maxlen_20_evicts_oldest():
    trace = Trace(task_id="t1", goal="g")
    for i in range(25):
        trace.append(Step(step=i, ts=0.0, thought="x", action_type="click", action_args={}))
    assert len(trace.steps) == 20
    # FIFO popleft → 留下 step 5..24
    steps = list(trace.steps)
    assert steps[0].step == 5
    assert steps[-1].step == 24


def test_trace_for_llm_returns_list_of_step_dicts():
    trace = Trace(task_id="t1", goal="g")
    for i in range(3):
        trace.append(Step(step=i, ts=0.0, thought=f"think-{i}",
                          action_type="click", action_args={"mark_id": i}))
    out = trace.for_llm()
    assert isinstance(out, list)
    assert len(out) == 3
    assert out[0]["step"] == 0
    assert out[2]["thought"] == "think-2"
    assert out[1]["action"] == {"type": "click", "mark_id": 1}
