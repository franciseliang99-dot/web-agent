"""replay.py 单测: load_task / render_html / main 的覆盖."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from web_agent.replay import (
    load_all_tasks_meta,
    load_task,
    main,
    render_html,
    render_index_html,
)


def _seed_db(db_path: Path, task_id: str = "abc12345", *, started_at: float | None = None) -> None:
    """建表 + 写 1 task + 4 step (含 safety_block + done)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY, goal TEXT NOT NULL,
            started_at REAL NOT NULL, ended_at REAL, result TEXT
        );
        CREATE TABLE IF NOT EXISTS steps (
            task_id TEXT, step INTEGER, ts REAL, thought TEXT,
            action_type TEXT, action_args TEXT, screenshot_path TEXT, observation TEXT,
            PRIMARY KEY (task_id, step)
        );
        """
    )
    started = started_at or time.time()
    conn.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?)",
        (task_id, "搜索量子纠缠 <demo>", started, started + 30.0, "found 量子纠缠简介"),
    )
    rows = [
        (task_id, 0, started + 1.0, "导航中文",
         "click", json.dumps({"mark_id": 3}), f"data/screenshots/{task_id}-00.png", "clicked 搜索框"),
        (task_id, 1, started + 5.0, "type query",
         "type", json.dumps({"text": "量子纠缠", "submit": True}),
         f"data/screenshots/{task_id}-01.png", "typed"),
        (task_id, 2, started + 12.0, "<script>alert(1)</script>",
         "safety_block", json.dumps({"original_type": "click", "rule": "send-or-pay", "mark_id": 9}),
         f"data/screenshots/{task_id}-02.png", "aborted — safety"),
        (task_id, 3, started + 25.0, "返回结果",
         "done", json.dumps({"result": "量子纠缠"}),
         f"data/screenshots/{task_id}-03.png", "finished"),
    ]
    conn.executemany("INSERT INTO steps VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def _create_empty_schema(db_path: Path) -> None:
    """建表但不写任何 task — empty-db SystemExit 用例共用。"""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, goal TEXT, started_at REAL, ended_at REAL, result TEXT);"
        "CREATE TABLE steps (task_id TEXT, step INTEGER, ts REAL, thought TEXT, action_type TEXT, action_args TEXT, screenshot_path TEXT, observation TEXT, PRIMARY KEY (task_id, step));"
    )
    conn.commit()
    conn.close()


def test_load_task_explicit_id(tmp_path):
    db = tmp_path / "trace.db"
    _seed_db(db, task_id="t1")
    task = load_task("t1", db_path=db)
    assert task["task_id"] == "t1"
    assert task["goal"].startswith("搜索量子纠缠")
    assert len(task["steps"]) == 4
    assert task["steps"][2]["action_type"] == "safety_block"
    assert task["steps"][2]["action_args"]["rule"] == "send-or-pay"


def test_load_task_latest_when_none(tmp_path):
    db = tmp_path / "trace.db"
    _seed_db(db, task_id="older", started_at=1000.0)
    _seed_db(db, task_id="newer", started_at=2000.0)
    task = load_task(None, db_path=db)
    assert task["task_id"] == "newer"


def test_load_task_missing_id_exits(tmp_path):
    db = tmp_path / "trace.db"
    _seed_db(db)
    with pytest.raises(SystemExit) as exc:
        load_task("nope", db_path=db)
    assert "nope" in str(exc.value)


def test_load_task_db_missing_exits(tmp_path):
    with pytest.raises(SystemExit) as exc:
        load_task(None, db_path=tmp_path / "nodb.db")
    assert "db 不存在" in str(exc.value)


def test_load_task_empty_tasks_exits(tmp_path):
    db = tmp_path / "trace.db"
    _create_empty_schema(db)
    with pytest.raises(SystemExit) as exc:
        load_task(None, db_path=db)
    assert "tasks 表为空" in str(exc.value)


def test_render_html_contains_goal_and_meta(tmp_path):
    db = tmp_path / "trace.db"
    _seed_db(db, task_id="t1")
    task = load_task("t1", db_path=db)
    html_out = render_html(task)
    # goal 含 < 应被 escape
    assert "&lt;demo&gt;" in html_out
    assert "搜索量子纠缠" in html_out
    assert "t1" in html_out
    assert "<!DOCTYPE html>" in html_out
    assert 'lang="zh-CN"' in html_out


def test_render_html_safety_block_class_and_rule(tmp_path):
    db = tmp_path / "trace.db"
    _seed_db(db, task_id="t1")
    task = load_task("t1", db_path=db)
    html_out = render_html(task)
    assert "step--safety" in html_out
    assert "send-or-pay" in html_out
    assert "step--done" in html_out


def test_render_html_screenshot_relative_path(tmp_path):
    db = tmp_path / "trace.db"
    _seed_db(db, task_id="t1")
    task = load_task("t1", db_path=db)
    html_out = render_html(task)
    assert "../screenshots/t1-00.png" in html_out
    assert "../screenshots/t1-03.png" in html_out


def test_render_html_escapes_thought_xss(tmp_path):
    """thought 含 <script> 必须 escape 不出现裸标签."""
    db = tmp_path / "trace.db"
    _seed_db(db, task_id="t1")
    task = load_task("t1", db_path=db)
    html_out = render_html(task)
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_main_writes_file_and_returns_zero(tmp_path, capsys):
    db = tmp_path / "trace.db"
    out = tmp_path / "replays"
    _seed_db(db, task_id="t1")
    rc = main(["t1", "--db", str(db), "--out", str(out)])
    assert rc == 0
    assert (out / "t1.html").exists()
    captured = capsys.readouterr()
    assert "wrote" in captured.out
    assert "4 steps" in captured.out


def test_main_latest_when_no_arg(tmp_path):
    db = tmp_path / "trace.db"
    out = tmp_path / "replays"
    _seed_db(db, task_id="older", started_at=1000.0)
    _seed_db(db, task_id="newer", started_at=2000.0)
    rc = main(["--db", str(db), "--out", str(out)])
    assert rc == 0
    assert (out / "newer.html").exists()
    assert not (out / "older.html").exists()


# ---------- W4-1.1 索引页 ----------

def test_load_all_tasks_meta_orders_by_started_desc(tmp_path):
    db = tmp_path / "trace.db"
    _seed_db(db, task_id="t1", started_at=100.0)
    _seed_db(db, task_id="t3", started_at=300.0)
    _seed_db(db, task_id="t2", started_at=200.0)
    metas = load_all_tasks_meta(db_path=db)
    assert [m["task_id"] for m in metas] == ["t3", "t2", "t1"]
    # 每 task seed 4 step
    assert all(m["step_count"] == 4 for m in metas)


def test_load_all_tasks_meta_empty_db_exits(tmp_path):
    db = tmp_path / "trace.db"
    _create_empty_schema(db)
    with pytest.raises(SystemExit):
        load_all_tasks_meta(db_path=db)


def test_render_index_html_links_each_task_with_result_class(tmp_path):
    db = tmp_path / "trace.db"
    _seed_db(db, task_id="t_safety", started_at=200.0)
    # 覆盖 _seed_db 默认 result, 注入 SAFETY_BLOCK 关键词命中颜色类
    conn = sqlite3.connect(db)
    conn.execute("UPDATE tasks SET result=? WHERE task_id=?",
                 ("SAFETY_BLOCK at step 0: send-or-pay", "t_safety"))
    conn.commit()
    conn.close()
    _seed_db(db, task_id="t_done", started_at=100.0)

    metas = load_all_tasks_meta(db_path=db)
    out = render_index_html(metas)

    assert '<a href="t_safety.html">' in out
    assert '<a href="t_done.html">' in out
    assert "result--safety" in out  # SAFETY_BLOCK 命中颜色类
    assert "<table class=\"task-list\">" in out
    # 排序 newest first → t_safety (200) 应在 t_done (100) 前
    assert out.index("t_safety") < out.index("t_done")


def test_main_all_flag_writes_each_task_html_plus_index(tmp_path, capsys):
    db = tmp_path / "trace.db"
    out = tmp_path / "replays"
    _seed_db(db, task_id="t1", started_at=100.0)
    _seed_db(db, task_id="t2", started_at=200.0)
    rc = main(["--all", "--db", str(db), "--out", str(out)])
    assert rc == 0
    assert (out / "t1.html").exists()
    assert (out / "t2.html").exists()
    assert (out / "index.html").exists()
    captured = capsys.readouterr()
    assert "2 task pages" in captured.out


def test_main_all_and_task_id_mutex_errors(tmp_path):
    db = tmp_path / "trace.db"
    out = tmp_path / "replays"
    _seed_db(db, task_id="t1")
    with pytest.raises(SystemExit):
        main(["t1", "--all", "--db", str(db), "--out", str(out)])
