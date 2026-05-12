"""V0.51.1 data-clean CLI unit tests — V0.42 housekeeping (V0.36.2 + V0.41 C5 deferred).

Test scope: find_cleanable_files / find_cleanable_trace_rows / apply_cleanup_* / format_dry_run_report
/ main (dry-run vs --apply). 全 tmp_path + os.utime mock (autonomous safe, 0 真删 main /data/).
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

from web_agent.data_clean import (
    CleanupStats,
    apply_cleanup_files,
    apply_cleanup_trace_rows,
    find_cleanable_files,
    find_cleanable_trace_rows,
    format_dry_run_report,
    main,
)


# --- find_cleanable_files ---


def test_find_cleanable_files_empty_dir(tmp_path: Path) -> None:
    """V0.51.1: 空目录 → 0 stats."""
    target = tmp_path / "screenshots"
    target.mkdir()
    stats = find_cleanable_files(target, ttl_days=90)
    assert stats.files_count == 0
    assert stats.bytes_total == 0
    assert stats.paths_or_rows == []


def test_find_cleanable_files_missing_dir(tmp_path: Path) -> None:
    """V0.51.1: 目录不存在 → 0 stats (不抛)."""
    stats = find_cleanable_files(tmp_path / "nonexistent", ttl_days=90)
    assert stats.files_count == 0


def test_find_cleanable_files_only_old(tmp_path: Path) -> None:
    """V0.51.1: 仅 mtime > ttl 算 cleanable."""
    target = tmp_path / "screenshots"
    target.mkdir()
    old_file = target / "old.png"
    old_file.write_bytes(b"x" * 1000)
    ts_old = time.time() - 100 * 86400
    os.utime(old_file, (ts_old, ts_old))

    new_file = target / "new.png"
    new_file.write_bytes(b"y" * 500)

    stats = find_cleanable_files(target, ttl_days=90)
    assert stats.files_count == 1
    assert stats.bytes_total == 1000
    assert "old.png" in stats.paths_or_rows


def test_find_cleanable_files_sample_capped_at_5(tmp_path: Path) -> None:
    """V0.51.1: sample 前 5 条 (防全列表撑爆 log)."""
    target = tmp_path / "downloads"
    target.mkdir()
    ts_old = time.time() - 100 * 86400
    for i in range(10):
        f = target / f"file_{i}.bin"
        f.write_bytes(b"x")
        os.utime(f, (ts_old, ts_old))
    stats = find_cleanable_files(target, ttl_days=90)
    assert stats.files_count == 10
    assert len(stats.paths_or_rows) == 5


# --- find_cleanable_trace_rows ---


def _setup_trace_db(db: Path, task_ts_list: list[float]) -> None:
    """V0.51.1 helper: 构造 tasks 表 (跟 src/web_agent/trace.py schema 同)."""
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY, goal TEXT NOT NULL, started_at REAL NOT NULL,
            ended_at REAL, result TEXT
        )
    """)
    for i, ts in enumerate(task_ts_list):
        conn.execute(
            "INSERT INTO tasks (task_id, goal, started_at) VALUES (?, ?, ?)",
            (f"t{i}", f"goal {i}", ts),
        )
    conn.commit()
    conn.close()


def test_find_cleanable_trace_rows_no_db(tmp_path: Path) -> None:
    """V0.51.1: trace.db 不存在 → 0 stats."""
    stats = find_cleanable_trace_rows(tmp_path / "nonexistent.db", ttl_days=90)
    assert stats.files_count == 0


def test_find_cleanable_trace_rows_table_missing(tmp_path: Path) -> None:
    """V0.51.1: db 存在但 tasks 表不存在 → 0 stats silent."""
    db = tmp_path / "trace.db"
    sqlite3.connect(db).close()
    stats = find_cleanable_trace_rows(db, ttl_days=90)
    assert stats.files_count == 0


def test_find_cleanable_trace_rows_old_only(tmp_path: Path) -> None:
    """V0.51.1: 仅 started_at < cutoff 算 cleanable."""
    db = tmp_path / "trace.db"
    now = time.time()
    _setup_trace_db(db, [
        now - 100 * 86400,
        now - 50 * 86400,
        now - 200 * 86400,
    ])
    stats = find_cleanable_trace_rows(db, ttl_days=90)
    assert stats.files_count == 2
    assert len(stats.paths_or_rows) == 2


# --- apply_cleanup_files / apply_cleanup_trace_rows ---


def test_apply_cleanup_files_deletes_old(tmp_path: Path) -> None:
    """V0.51.1: --apply 真删 mtime > ttl 文件."""
    target = tmp_path / "screenshots"
    target.mkdir()
    old = target / "old.png"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 100 * 86400,) * 2)
    new = target / "new.png"
    new.write_bytes(b"y")
    n = apply_cleanup_files(target, ttl_days=90)
    assert n == 1
    assert not old.exists()
    assert new.exists()


def test_apply_cleanup_files_missing_dir(tmp_path: Path) -> None:
    """V0.51.1: 目录不存在 → 0 删 (不抛)."""
    assert apply_cleanup_files(tmp_path / "nonexistent", ttl_days=90) == 0


def test_apply_cleanup_trace_rows_deletes_old(tmp_path: Path) -> None:
    """V0.51.1: --apply DELETE rows WHERE started_at < cutoff. schema 不动."""
    db = tmp_path / "trace.db"
    now = time.time()
    _setup_trace_db(db, [now - 100 * 86400, now - 50 * 86400, now - 200 * 86400])
    n = apply_cleanup_trace_rows(db, ttl_days=90)
    assert n == 2
    conn = sqlite3.connect(db)
    try:
        remaining = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    finally:
        conn.close()
    assert remaining == 1


# --- format_dry_run_report ---


def test_format_dry_run_report_includes_total_bytes() -> None:
    """V0.51.1: dry-run 输出含 total bytes + MB."""
    stats = [
        CleanupStats("screenshots", 100, 50_000_000, ["a.png", "b.png"]),
        CleanupStats("downloads", 50, 20_000_000, []),
    ]
    out = format_dry_run_report(stats, ttl_days=90)
    assert "screenshots" in out
    assert "100" in out
    assert "50000000" in out  # per-row 不带 comma (raw int)
    assert "70,000,000" in out  # total 带 comma format
    assert "70.0 MB" in out
    assert "--apply" in out
    assert "dry-run" in out


def test_format_dry_run_report_empty_sample() -> None:
    """V0.51.1: 0 file → sample 显示 '(none)'."""
    stats = [CleanupStats("replays", 0, 0, [])]
    out = format_dry_run_report(stats, ttl_days=90)
    assert "(none)" in out


# --- main CLI (dry-run vs --apply) ---


def test_main_dry_run_default_no_real_delete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """V0.51.1: main 默 dry-run, 不真删 (传 --root tmp_path 模拟)."""
    sc = tmp_path / "screenshots"
    sc.mkdir()
    old = sc / "old.png"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 100 * 86400,) * 2)

    rc = main(["--root", str(tmp_path), "--ttl-days", "90"])
    assert rc == 0
    assert old.exists()  # dry-run 不删
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "screenshots" in out


def test_main_apply_truly_deletes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """V0.51.1: main --apply 真删. 跟 CLAUDE.md destructive 显式授权一致."""
    sc = tmp_path / "screenshots"
    sc.mkdir()
    old = sc / "old.png"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 100 * 86400,) * 2)
    rc = main(["--root", str(tmp_path), "--ttl-days", "90", "--apply"])
    assert rc == 0
    assert not old.exists()  # 真删
    out = capsys.readouterr().out
    assert "--apply 真删执行" in out
    assert "deleted 1 files" in out
