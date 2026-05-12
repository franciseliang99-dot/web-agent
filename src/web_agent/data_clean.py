"""V0.51.1: data-clean CLI — V0.42 housekeeping (V0.36.2 + V0.41 C5 deferred).

Default `--dry-run`: 仅打印将删文件 + 释放大小, 不真删. 真删需用户 `--apply` 显式 (跟 CLAUDE.md
"destructive operations 用户显式确认" + V0.48.2 maintainer 红线 + V0.36.2 retention 决策红线一致).

3 cleanup target (default ttl 90 天):
- `data/screenshots/`: mtime > ttl → unlink (dev iteration loop 每 step PNG)
- `data/downloads/`: mtime > ttl → unlink (V0.23 download 累积)
- `data/trace.db tasks`: started_at < cutoff → DELETE rows + 关联 steps (schema 不动)
- `data/replays/`: mtime > ttl → unlink

保留 (长期价值, hardcoded exclude):
- `data/stealth_probes/` (V0.39/V0.48 baseline + cassette ref)
- `data/bench/` (V0.34+ baseline JSON perf 对照)
- `data/eval/` (eval 历史)
- `data/memory.db` (W5-D 长期记忆, 跨 session)
- `data/upwork.db` (active dogfooding)

依赖方向 (CLAUDE.md 解耦): pathlib + sqlite3 stdlib only, 不依赖 web_agent.* (allow cleanup 跑
even if web_agent module broken). console_script entry: `web-agent-data-clean`.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_TTL_DAYS = 90
_DEFAULT_ROOT = Path("data")


@dataclass(frozen=True, slots=True)
class CleanupStats:
    """V0.51.1: cleanup target stats (dry-run 输出 + caller 测).

    Args:
        target_label: human-readable 名 ("screenshots" / "downloads" / "trace.db tasks" / "replays").
        files_count: 文件数 / sqlite 行数.
        bytes_total: 字节累计 (sqlite 0, 仅 fs).
        paths_or_rows: 前 N 条样本 (dry-run 显示, 防全列表撑爆 log).
    """

    target_label: str
    files_count: int
    bytes_total: int
    paths_or_rows: list[str]


def _is_older_than(path: Path, cutoff_ts: float) -> bool:
    """V0.51.1: file mtime < cutoff (cutoff = now - ttl_days * 86400)."""
    try:
        return path.stat().st_mtime < cutoff_ts
    except OSError:
        return False  # 不可读 → 不删 (safe)


def find_cleanable_files(target_dir: Path, ttl_days: int) -> CleanupStats:
    """V0.51.1: 扫目录找 mtime > ttl 文件. dry-run + apply 共用.

    返 CleanupStats. 目录不存在 → 0 stats. Sample paths 前 5 条 (relative to target_dir).
    """
    cutoff_ts = time.time() - ttl_days * 86400
    if not target_dir.exists():
        return CleanupStats(target_dir.name, 0, 0, [])
    paths: list[Path] = []
    bytes_total = 0
    for path in target_dir.iterdir():
        if not path.is_file():
            continue  # 仅清 file (subdir 不递归 — V0.51 conservative scope)
        if _is_older_than(path, cutoff_ts):
            try:
                bytes_total += path.stat().st_size
            except OSError:
                pass
            paths.append(path)
    sample = [str(p.name) for p in paths[:5]]
    return CleanupStats(target_dir.name, len(paths), bytes_total, sample)


def find_cleanable_trace_rows(db_path: Path, ttl_days: int) -> CleanupStats:
    """V0.51.1: SELECT COUNT trace.db tasks WHERE started_at < cutoff (schema 不动)."""
    if not db_path.exists():
        return CleanupStats("trace.db tasks", 0, 0, [])
    cutoff_ts = time.time() - ttl_days * 86400
    conn = sqlite3.connect(db_path)
    try:
        try:
            rows = conn.execute(
                "SELECT task_id, started_at FROM tasks WHERE started_at < ? ORDER BY started_at LIMIT 5",
                (cutoff_ts,),
            ).fetchall()
            count = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE started_at < ?", (cutoff_ts,),
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return CleanupStats("trace.db tasks", 0, 0, [])  # 表/列不存在
    finally:
        conn.close()
    sample = [f"{r[0]}@{r[1]:.0f}" for r in rows]
    return CleanupStats("trace.db tasks", count, 0, sample)


def apply_cleanup_files(target_dir: Path, ttl_days: int) -> int:
    """V0.51.1: 真删 mtime > ttl 文件. 返删除数. Error silent (跟 record_task 同档).

    跟 CLAUDE.md "destructive operations 用户确认" — caller 必先 user `--apply`.
    """
    cutoff_ts = time.time() - ttl_days * 86400
    if not target_dir.exists():
        return 0
    deleted = 0
    for path in target_dir.iterdir():
        if not path.is_file() or not _is_older_than(path, cutoff_ts):
            continue
        try:
            path.unlink()
            deleted += 1
        except OSError:
            pass
    return deleted


def apply_cleanup_trace_rows(db_path: Path, ttl_days: int) -> int:
    """V0.51.1: DELETE FROM tasks + steps WHERE started_at/ts < cutoff. 返删除 rows."""
    if not db_path.exists():
        return 0
    cutoff_ts = time.time() - ttl_days * 86400
    conn = sqlite3.connect(db_path)
    try:
        try:
            cur = conn.execute("DELETE FROM tasks WHERE started_at < ?", (cutoff_ts,))
            tasks_deleted = cur.rowcount
            try:
                conn.execute("DELETE FROM steps WHERE ts < ?", (cutoff_ts,))
            except sqlite3.OperationalError:
                pass  # steps 表不存在 — silent
            conn.commit()
            return tasks_deleted
        except sqlite3.OperationalError:
            return 0
    finally:
        conn.close()


def format_dry_run_report(stats_list: list[CleanupStats], ttl_days: int) -> str:
    """V0.51.1: dry-run 输出 — 人类可读 markdown 表 (target / count / size + 样本前 5)."""
    lines = [
        f"# data-clean dry-run (ttl={ttl_days}d, autonomous 默 dry-run, 真删需 `--apply`)\n",
        "| target | count | bytes | sample (first 5) |",
        "|--------|------:|------:|------------------|",
    ]
    total_bytes = 0
    total_count = 0
    for s in stats_list:
        sample_str = ", ".join(s.paths_or_rows) if s.paths_or_rows else "(none)"
        lines.append(f"| {s.target_label} | {s.files_count} | {s.bytes_total} | {sample_str} |")
        total_bytes += s.bytes_total
        total_count += s.files_count
    lines.append(f"\n**Total: {total_count} files/rows, {total_bytes:,} bytes ({total_bytes / 1_000_000:.1f} MB)**")
    lines.append("\nRun with `--apply` to真删. autonomous 默 `--dry-run` 不真删.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """V0.51.1: console_script entry. 默 --dry-run, --apply 真删."""
    parser = argparse.ArgumentParser(
        prog="web-agent-data-clean",
        description="V0.51.1: cleanup data/ old files (default 90d ttl, dry-run).",
    )
    parser.add_argument(
        "--ttl-days", type=int, default=_DEFAULT_TTL_DAYS,
        help=f"file mtime ttl in days (default {_DEFAULT_TTL_DAYS})",
    )
    parser.add_argument(
        "--root", type=Path, default=_DEFAULT_ROOT,
        help=f"data root (default {_DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="真删 (默 dry-run; 不可逆, 用户显式授权)",
    )
    args = parser.parse_args(argv)

    targets = [
        args.root / "screenshots",
        args.root / "downloads",
        args.root / "replays",
    ]
    trace_db = args.root / "trace.db"

    stats_list = [find_cleanable_files(t, args.ttl_days) for t in targets]
    stats_list.append(find_cleanable_trace_rows(trace_db, args.ttl_days))

    sys.stdout.write(format_dry_run_report(stats_list, args.ttl_days) + "\n")

    if args.apply:
        sys.stdout.write("\n--apply 真删执行...\n")
        for t in targets:
            n = apply_cleanup_files(t, args.ttl_days)
            sys.stdout.write(f"  {t.name}: deleted {n} files\n")
        rows = apply_cleanup_trace_rows(trace_db, args.ttl_days)
        sys.stdout.write(f"  trace.db tasks: deleted {rows} rows\n")

    return 0


__all__ = [
    "CleanupStats",
    "apply_cleanup_files",
    "apply_cleanup_trace_rows",
    "find_cleanable_files",
    "find_cleanable_trace_rows",
    "format_dry_run_report",
    "main",
]
