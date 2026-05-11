"""V0.36.0 disk baseline framework 单测: measure_dir + measure_sqlite + report + cli.

跟 V0.33.0 token_baseline / V0.34.0 perceive_bench 单测同 pattern: tmp_path 写文件 / sqlite,
不真碰生产 data/.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict


from eval.disk_baseline import (
    DiskBaselineReport,
    build_baseline_report,
    load_baseline_json,
    main,
    measure_dir,
    measure_sqlite,
    render_baseline_markdown,
)


# ---------- measure_dir ----------


def test_measure_dir_missing_returns_zero(tmp_path):
    """V0.36.0: 不存在路径返 bytes=0 / file_count=0 / mtime=None (不抛)."""
    stats = measure_dir(tmp_path / "nonexistent")
    assert stats.bytes == 0
    assert stats.file_count == 0
    assert stats.oldest_mtime is None
    assert stats.newest_mtime is None
    assert stats.avg_file_bytes == 0.0


def test_measure_dir_empty_returns_zero(tmp_path):
    """V0.36.0: 空目录返 bytes=0 / mtime=None (跟 missing 同)."""
    empty = tmp_path / "empty"
    empty.mkdir()
    stats = measure_dir(empty)
    assert stats.file_count == 0
    assert stats.bytes == 0
    assert stats.avg_file_bytes == 0.0


def test_measure_dir_with_files(tmp_path):
    """V0.36.0: 3 files 含 nested subdir, 验 bytes/count/avg + mtime min/max."""
    (tmp_path / "a.png").write_bytes(b"x" * 100)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.png").write_bytes(b"y" * 200)
    (sub / "c.png").write_bytes(b"z" * 300)
    stats = measure_dir(tmp_path)
    assert stats.file_count == 3
    assert stats.bytes == 600
    assert stats.avg_file_bytes == 200.0
    assert stats.oldest_mtime is not None
    assert stats.newest_mtime is not None
    assert stats.oldest_mtime <= stats.newest_mtime


# ---------- measure_sqlite ----------


def test_measure_sqlite_missing(tmp_path):
    """V0.36.0: db 路径不存在返 SqliteStats(0, {}) (不抛)."""
    stats = measure_sqlite(tmp_path / "absent.db")
    assert stats.bytes == 0
    assert stats.tables == {}


def test_measure_sqlite_with_tables(tmp_path):
    """V0.36.0: 临时 db 建 2 表插 N 行, 验 tables 字典 + bytes 非 0."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE steps (id INTEGER PRIMARY KEY, task_id INTEGER)")
    for _ in range(5):
        conn.execute("INSERT INTO tasks DEFAULT VALUES")
    for _ in range(12):
        conn.execute("INSERT INTO steps DEFAULT VALUES")
    conn.commit()
    conn.close()
    stats = measure_sqlite(db)
    assert stats.bytes > 0
    assert stats.tables == {"tasks": 5, "steps": 12}


def test_measure_sqlite_rejects_malicious_table_name(tmp_path):
    """V0.36.0: 表名含 `"` 防御 sqlite_master 注入跳计数不爆 (虽 web-agent 自建表名都 ascii)."""
    db = tmp_path / "evil.db"
    conn = sqlite3.connect(db)
    # 用反斜杠 escape 真建一个含 `"` 的表名 (sqlite 允许 `"` quote 内的 `""` escape)
    conn.execute('CREATE TABLE "ev""il" (x INTEGER)')
    conn.execute("CREATE TABLE clean (y INTEGER)")
    conn.execute("INSERT INTO clean VALUES (1)")
    conn.commit()
    conn.close()
    stats = measure_sqlite(db)
    # `ev"il` 表名含 `"` 应被防御跳过, clean 表正常计数
    assert "clean" in stats.tables
    assert stats.tables["clean"] == 1
    assert 'ev"il' not in stats.tables


# ---------- DiskBaselineReport JSON roundtrip ----------


def test_disk_baseline_report_json_roundtrip(tmp_path):
    """V0.36.0: report.asdict → json.dumps → load_baseline_json → 等价 (V0.36.3 compare 要)."""
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "x.png").write_bytes(b"x" * 50)
    db = tmp_path / "trace.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO tasks DEFAULT VALUES")
    conn.commit()
    conn.close()
    report = build_baseline_report(tmp_path, dirs=("screenshots",), dbs=("trace.db",))
    out = tmp_path / "baseline.json"
    out.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    loaded = load_baseline_json(out)
    assert loaded.total_bytes == report.total_bytes
    assert loaded.data_root == report.data_root
    assert len(loaded.dirs) == len(report.dirs)
    assert loaded.dirs[0].file_count == report.dirs[0].file_count
    assert loaded.dbs[0].tables == report.dbs[0].tables


def test_disk_baseline_per_task_bytes_zero_division_safe(tmp_path):
    """V0.36.0: trace.db 无 tasks 表 (或 task_count=0) → per_task_bytes = None 不爆 ZeroDivisionError."""
    # 不创建 trace.db (全空)
    report = build_baseline_report(tmp_path, dirs=("nonexistent",), dbs=("trace.db",))
    assert report.per_task_bytes is None
    assert isinstance(report, DiskBaselineReport)


def test_disk_baseline_per_task_bytes_computed(tmp_path):
    """V0.36.0: trace.db 有 tasks → per_task_bytes = total / task_count."""
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "a.png").write_bytes(b"x" * 1000)
    db = tmp_path / "trace.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY)")
    for _ in range(4):
        conn.execute("INSERT INTO tasks DEFAULT VALUES")
    conn.commit()
    conn.close()
    report = build_baseline_report(tmp_path, dirs=("screenshots",), dbs=("trace.db",))
    assert report.per_task_bytes is not None
    assert report.per_task_bytes == report.total_bytes / 4


# ---------- render_baseline_markdown ----------


def test_render_markdown_contains_subdirs_and_tables(tmp_path):
    """V0.36.0: markdown 渲含子目录 path + sqlite tables + total bytes."""
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "a.png").write_bytes(b"x" * 100)
    report = build_baseline_report(tmp_path, dirs=("screenshots",), dbs=())
    md = render_baseline_markdown(report)
    assert "screenshots" in md
    assert "100 B" in md or "0.1 KB" in md  # bytes 渲
    assert "disk baseline" in md.lower()


# ---------- cli main ----------


def test_cli_main_stdout_markdown(tmp_path, capsys):
    """V0.36.0: cli 默 stdout markdown, 含 'disk baseline' + 'total'."""
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "x.png").write_bytes(b"x" * 50)
    rc = main(["--data-root", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "disk baseline" in captured.out.lower()
    assert "total" in captured.out.lower()


def test_cli_main_out_json(tmp_path, capsys):
    """V0.36.0: cli --out 写 JSON + stdout 印路径, 不渲 markdown."""
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "x.png").write_bytes(b"x" * 50)
    out_path = tmp_path / "baseline.json"
    rc = main(["--data-root", str(tmp_path), "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert "total_bytes" in data
    assert "dirs" in data
    captured = capsys.readouterr()
    assert str(out_path) in captured.out


def test_cli_main_data_root_missing_returns_1(tmp_path, capsys):
    """V0.36.0: cli --data-root 不存在 → exit 1 + stderr ERROR."""
    rc = main(["--data-root", str(tmp_path / "nonexistent")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
