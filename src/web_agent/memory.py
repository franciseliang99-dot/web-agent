"""长期记忆 (W5-D MVP): 跨 session 持久化 task outcome by domain。

蓝本认知层延伸 — 短期记忆 (Action Trace, V0.5.0 deque maxlen=20 + trace.db) 已有,
本模块负责跨 session 持久化任务结果, 以 domain (URL netloc) 为索引, 供
`web-agent-memory <domain>` CLI 查询历史 / 未来 W5-D.2 inject 到 planner 上下文。

设计:
- 与 `trace.db` **分开** (`data/memory.db`): schema 演进独立, 备份/清理粒度独立
- 失败判定 substring 匹配 5 类 marker (与 loop.py L147/L155/L172/L218 等错误前缀对齐)
- record/recall 失败 silently swallow: 记忆不该阻塞主路径
- 当前 MVP 仅持久化 + CLI dump; 不动 planner Protocol, 不 inject 到 trace.observation
  (那是 W5-D.2 的事, 涉及大架构改动)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_DB = Path("data/memory.db")
RESULT_TRUNC = 200

# 与 loop.py 内 graceful abort result 字符串前缀对齐 (V0.5.0 / V0.5.2 / V0.6.0 / V0.9.0):
# - "(max_steps 耗尽未完成)" — L294
# - "WALLCLOCK_EXCEEDED at step N: ..." — L148
# - "SAFETY_BLOCK at step N: ..." — L202
# - "CAPTCHA_TIMEOUT at step N: ..." — L99 (_handle_captcha)
# - "LOOP_DETECTED 在 step N: ..." — L218
# - "LLM_FAILED at step N: ..." — L179
FAILURE_MARKERS: tuple[str, ...] = (
    "(max_steps",
    "WALLCLOCK_EXCEEDED",
    "SAFETY_BLOCK",
    "CAPTCHA_TIMEOUT",
    "LOOP_DETECTED",
    "LLM_FAILED",
)


@dataclass
class MemoryEntry:
    ts: float
    domain: str
    goal: str
    result: str
    success: bool


def extract_domain(url: str | None) -> str:
    """从 URL 提取 netloc (lowercase). None / "" / 异常 一律返 ""。

    `urlparse("about:blank").netloc` = "", `urlparse("javascript:...").netloc` = ""
    自然落到 fallback; IPv6 / 端口 走 netloc 标准解析。
    """
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def is_success(result: str) -> bool:
    """5 类失败 marker 任一 substring 命中 → False; 空 result 视为 fail (防御默认)。"""
    if not result:
        return False
    return not any(m in result for m in FAILURE_MARKERS)


def init_memory_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            domain TEXT NOT NULL,
            goal TEXT NOT NULL,
            result TEXT NOT NULL,
            success INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_domain_ts ON memories(domain, ts DESC)"
    )
    conn.commit()
    return conn


def record_task(
    db_path: Path,
    domain: str,
    goal: str,
    result: str,
    success: bool,
) -> None:
    conn = init_memory_db(db_path)
    try:
        conn.execute(
            "INSERT INTO memories (ts, domain, goal, result, success) VALUES (?,?,?,?,?)",
            (time.time(), domain, goal, result[:RESULT_TRUNC], 1 if success else 0),
        )
        conn.commit()
    finally:
        conn.close()


def recall_by_domain(
    db_path: Path,
    domain: str,
    limit: int = 5,
) -> list[MemoryEntry]:
    """查 domain 下最近 N 条记忆 (DESC by ts)。db 不存在返 []。"""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ts, domain, goal, result, success FROM memories "
            "WHERE domain = ? ORDER BY ts DESC LIMIT ?",
            (domain, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        MemoryEntry(
            ts=r[0], domain=r[1], goal=r[2], result=r[3], success=bool(r[4])
        )
        for r in rows
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="web-agent-memory",
        description="dump 长期记忆 (跨 session task outcome by domain)",
    )
    p.add_argument("domain", help='domain (URL netloc, e.g. "github.com"; 空 URL 任务用 ""​)')
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--db", default=str(DEFAULT_DB))
    args = p.parse_args(argv)

    entries = recall_by_domain(Path(args.db), args.domain, limit=args.limit)
    if not entries:
        print(f"(no memories for domain={args.domain!r})")
        return 0
    print(f"=== {len(entries)} memories for domain={args.domain!r} (newest first) ===")
    for e in entries:
        ts = datetime.fromtimestamp(e.ts).isoformat(timespec="seconds")
        flag = "OK  " if e.success else "FAIL"
        print(f"[{ts}] {flag}  {e.goal[:60]}  ->  {e.result[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
