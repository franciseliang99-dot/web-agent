"""V0.36.0 I 内存优化系列开篇: disk baseline framework — measure data/ + sqlite db.

跟 V0.33.0 token_baseline / V0.34.0 perceive_bench framework 同节奏:
- DirStats / SqliteStats / DiskBaselineReport frozen+slots dataclass
- measure_dir / measure_sqlite 纯函数 (无 web_agent.* 依赖)
- compare_baselines + render_markdown (跟 token_baseline 同 pattern 占位, V0.36.3 收尾用)
- main(argv): cli `web-agent-disk-baseline` (snapshot / compare subcommand)

V0.36 主题诚实降级: 当前 data/ ~87 MB (74M screenshots + 12M downloads, V0.36.0 真测), **算不上
"内存爆炸"** — 是**预防性优化**给 1000+ task 长期项目准备. V0.34 教训应用: 真 baseline 数据
推后续 V0.36.1+ 真做 cleanup 之前的 ROI 判定基础, 防 "没数据就优化是猜".

V0.36.0 scope: framework only, **不真删 data/**. 真清理 V0.36.2 留 (autonomous 红线 — retention
policy 是产品决策需 user 输入, destructive 真删需用户显式同意).

V0.36 系列规划:
- V0.36.0 (本): disk baseline framework + CLI snapshot 跑通
- V0.36.1: loop.py 改 per-task subdir 让 cleanup 粒度对齐 task (autonomous + BC fallback)
- V0.36.2: data-clean CLI (TTL + --dry-run, 真删 stop ask user) — autonomous 红线
- V0.36.3: sqlite VACUUM + index 体检 + 系列收尾 (autonomous + backup 保护)
- V0.36.4 (可选): downloads listener 过激 root cause + per-task quota
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DirStats:
    """V0.36.0: 单目录测量 (data/ 下任一 subdir).

    bytes 是所有 file (递归) size 之和; file_count 递归计数. oldest/newest_mtime 给 TTL-based
    cleanup (V0.36.2) 判依据. avg_file_bytes = bytes/file_count, 空目录 = 0.0.
    """

    path: str
    bytes: int
    file_count: int
    oldest_mtime: float | None
    newest_mtime: float | None
    avg_file_bytes: float


@dataclass(frozen=True, slots=True)
class SqliteStats:
    """V0.36.0: 单 sqlite db 测量 (trace.db / memory.db / upwork.db).

    bytes 是 file size (含 unused page, VACUUM 前后差是 fragmentation 量). tables 是
    {table_name: row_count} dict, V0.36.3 VACUUM 前后对比验整合后 row 不漏.
    """

    path: str
    bytes: int
    tables: dict[str, int]


@dataclass(frozen=True, slots=True)
class DiskBaselineReport:
    """V0.36.0: data/ 全量 snapshot, JSON 可序列化, V0.36.3 compare 用.

    captured_at = time.time() 给时间戳. per_task_bytes = total / max(task_count, 1), task_count
    从 trace.db tasks 表读 (V0.12.4 schema). 空 db / 无 tasks 表 → per_task_bytes = None
    (不是 ZeroDivisionError).
    """

    captured_at: float
    data_root: str
    dirs: list[DirStats]
    dbs: list[SqliteStats]
    total_bytes: int
    per_task_bytes: float | None


DEFAULT_DIRS = ("screenshots", "downloads", "replays", "eval", "bench", "stealth_probes")
"""V0.36.0 默扫的 data/ 子目录 (跟当前 data/ 实际结构对齐, V0.36.x 加新 subdir 时同步加)."""

DEFAULT_DBS = ("trace.db", "memory.db", "upwork.db")
"""V0.36.0 默扫的 sqlite db: V0.12.4 trace + V0.13.0 memory + V0.20 upwork (jd_extract)."""


def measure_dir(path: Path) -> DirStats:
    """V0.36.0: 测单目录 (递归) bytes + file_count + 最旧/新 mtime. 不存在/空目录返 0/None."""
    if not path.exists() or not path.is_dir():
        return DirStats(
            path=str(path), bytes=0, file_count=0,
            oldest_mtime=None, newest_mtime=None, avg_file_bytes=0.0,
        )
    files = [f for f in path.rglob("*") if f.is_file()]
    if not files:
        return DirStats(
            path=str(path), bytes=0, file_count=0,
            oldest_mtime=None, newest_mtime=None, avg_file_bytes=0.0,
        )
    sizes = [f.stat().st_size for f in files]
    mtimes = [f.stat().st_mtime for f in files]
    total = sum(sizes)
    return DirStats(
        path=str(path),
        bytes=total,
        file_count=len(files),
        oldest_mtime=min(mtimes),
        newest_mtime=max(mtimes),
        avg_file_bytes=total / len(files),
    )


def measure_sqlite(db_path: Path) -> SqliteStats:
    """V0.36.0: 测单 sqlite db file size + 各表 row_count. 不存在返 SqliteStats(0, {}).

    防御 sqlite_master 表名注入: f-string quote 用 `"..."` 包裹 + 拒含 `"` 的表名 (跟 V0.12.4
    安全编写 schema 一致, web-agent 自建表名全 ascii alphanum + 下划线).
    """
    if not db_path.exists():
        return SqliteStats(path=str(db_path), bytes=0, tables={})
    size = db_path.stat().st_size
    tables: dict[str, int] = {}
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (name,) in rows:
            if not isinstance(name, str) or '"' in name:
                # 防御: 拒含 `"` 的表名 (sqlite_master 注入 mitigation, 跳计数不爆)
                continue
            try:
                count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                tables[name] = int(count)
            except sqlite3.Error:
                # 视图 / fts shadow table 等非真表 count 失败, 跳不爆
                continue
    finally:
        conn.close()
    return SqliteStats(path=str(db_path), bytes=size, tables=tables)


def build_baseline_report(
    data_root: Path,
    dirs: tuple[str, ...] = DEFAULT_DIRS,
    dbs: tuple[str, ...] = DEFAULT_DBS,
) -> DiskBaselineReport:
    """V0.36.0: 全量 data/ 测量 → DiskBaselineReport.

    per_task_bytes 从 trace.db tasks 表读 task_count 推算. trace.db 不存在或无 tasks 表 → None.
    """
    dir_stats = [measure_dir(data_root / d) for d in dirs]
    db_stats = [measure_sqlite(data_root / db) for db in dbs]
    total = sum(d.bytes for d in dir_stats) + sum(db.bytes for db in db_stats)
    # task_count: 从 trace.db tasks 表读 (V0.12.4 schema)
    task_count = 0
    trace_stats = next((s for s in db_stats if s.path.endswith("trace.db")), None)
    if trace_stats is not None and "tasks" in trace_stats.tables:
        task_count = trace_stats.tables["tasks"]
    per_task = (total / task_count) if task_count > 0 else None
    return DiskBaselineReport(
        captured_at=time.time(),
        data_root=str(data_root),
        dirs=dir_stats,
        dbs=db_stats,
        total_bytes=total,
        per_task_bytes=per_task,
    )


def load_baseline_json(path: Path) -> DiskBaselineReport:
    """V0.36.0: 从 JSON dump 加载 DiskBaselineReport (V0.36.3 compare 用).

    JSON schema 跟 dataclass asdict 一致, list[DirStats] / list[SqliteStats] 嵌套手动重建.
    """
    if not path.exists():
        raise FileNotFoundError(f"baseline JSON 不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return DiskBaselineReport(
        captured_at=float(data["captured_at"]),
        data_root=data["data_root"],
        dirs=[DirStats(**d) for d in data["dirs"]],
        dbs=[SqliteStats(**db) for db in data["dbs"]],
        total_bytes=int(data["total_bytes"]),
        per_task_bytes=(float(data["per_task_bytes"]) if data["per_task_bytes"] is not None else None),
    )


def _format_bytes(n: int) -> str:
    """V0.36.0 helper: bytes → 人类可读 KB/MB/GB."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def render_baseline_markdown(report: DiskBaselineReport) -> str:
    """V0.36.0: 渲染 DiskBaselineReport 为 markdown 表格 (跟 V0.33.0 / V0.34.0 同模式).

    顶部总览 + 子目录表 + sqlite db 表. per_task_bytes 给后续 V0.36.2 cleanup ROI 估算用.
    """
    lines = [
        f"# disk baseline @ {time.strftime('%Y-%m-%d %H:%M', time.localtime(report.captured_at))}",
        f"data_root: `{report.data_root}`",
        f"**total: {_format_bytes(report.total_bytes)}**"
        + (f" ({_format_bytes(int(report.per_task_bytes))}/task)"
           if report.per_task_bytes is not None else " (per-task = N/A, trace.db 无 tasks)"),
        "",
        "## 子目录",
        "| path | bytes | files | avg/file | oldest mtime |",
        "|------|-------|-------|----------|--------------|",
    ]
    for d in sorted(report.dirs, key=lambda x: -x.bytes):
        oldest = (
            time.strftime("%Y-%m-%d", time.localtime(d.oldest_mtime))
            if d.oldest_mtime is not None else "—"
        )
        lines.append(
            f"| {d.path} | {_format_bytes(d.bytes)} | {d.file_count} | "
            f"{_format_bytes(int(d.avg_file_bytes))} | {oldest} |",
        )
    lines.extend([
        "",
        "## sqlite db",
        "| path | bytes | tables |",
        "|------|-------|--------|",
    ])
    for db in sorted(report.dbs, key=lambda x: -x.bytes):
        tables_str = ", ".join(f"{n}={c}" for n, c in sorted(db.tables.items())) or "(none)"
        lines.append(f"| {db.path} | {_format_bytes(db.bytes)} | {tables_str} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """V0.36.0: web-agent-disk-baseline cli — snapshot data/ disk usage.

    用法:
        web-agent-disk-baseline                          # 测当前 data/, 渲 markdown stdout
        web-agent-disk-baseline --out baseline.json      # JSON dump (V0.36.3 compare 用)
        web-agent-disk-baseline --data-root /path/data   # 默 ./data
    """
    parser = argparse.ArgumentParser(
        prog="web-agent-disk-baseline",
        description=(
            "V0.36.0 I 内存优化系列开篇: 测 data/ 各子目录 + sqlite db disk usage baseline. "
            "framework only, 不真删/不动 data/."
        ),
    )
    parser.add_argument(
        "--data-root", default="data",
        help="data root 目录路径 (默 ./data, 含 screenshots/downloads/...)",
    )
    parser.add_argument(
        "--out", help="JSON 输出路径 (默 stdout markdown; 设则 dump JSON 不渲 markdown)",
    )
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    if not data_root.exists():
        sys.stderr.write(f"ERROR: data root 不存在: {data_root}\n")
        return 1
    report = build_baseline_report(data_root)
    if args.out:
        payload = asdict(report)
        Path(args.out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        sys.stdout.write(
            f"baseline → {args.out} (total {_format_bytes(report.total_bytes)}, "
            f"{len(report.dirs)} dirs + {len(report.dbs)} dbs)\n",
        )
    else:
        sys.stdout.write(render_baseline_markdown(report) + "\n")
    return 0


__all__ = [
    "DEFAULT_DBS",
    "DEFAULT_DIRS",
    "DirStats",
    "DiskBaselineReport",
    "SqliteStats",
    "build_baseline_report",
    "load_baseline_json",
    "main",
    "measure_dir",
    "measure_sqlite",
    "render_baseline_markdown",
]
