"""长期记忆 (W5-D MVP): 跨 session 持久化 task outcome by domain。

蓝本认知层延伸 — 短期记忆 (Action Trace, V0.5.0 deque maxlen=20 + trace.db) 已有,
本模块负责跨 session 持久化任务结果, 以 domain (URL netloc) 为索引, 供
`web-agent-memory <domain>` CLI 查询历史 / 未来 W5-D.2 inject 到 planner 上下文。

设计:
- 与 `trace.db` **分开** (`data/memory.db`): schema 演进独立, 备份/清理粒度独立
- 失败判定 substring 匹配 6 类 marker (与 loop.py L147/L155/L172/L218 等错误前缀对齐)
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
    """6 类失败 marker 任一 substring 命中 → False; 空 result 视为 fail (防御默认)。"""
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


# V0.28.1: W6-A reflections 表 — 跟 memories 表分开 (subagent 决, schema 演进独立).
# 同 db 文件 (data/memory.db) 减一次 connect, V0.28.2 cli inject 时一次 connect 读两表方便.


@dataclass
class ReflectionEntry:
    """V0.28.1: W6-A 反思记录, V0.28.2 cli 启动时 recall_reflections_by_domain 拉来 inject memories_str."""

    ts: float
    task_id: str
    domain: str
    goal: str
    final_result: str
    root_cause: str
    hint: str


def init_reflections_db(db_path: Path) -> sqlite3.Connection:
    """V0.28.1: 建 reflections 表 + index. 跟 init_memory_db 同模式."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            task_id TEXT NOT NULL,
            domain TEXT NOT NULL,
            goal TEXT NOT NULL,
            final_result TEXT NOT NULL,
            root_cause TEXT NOT NULL,
            hint TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reflections_domain_ts ON reflections(domain, ts DESC)"
    )
    conn.commit()
    return conn


def record_reflection(
    db_path: Path,
    task_id: str,
    domain: str,
    goal: str,
    final_result: str,
    root_cause: str,
    hint: str,
) -> None:
    """V0.28.1: 写一条反思记录. 跟 record_task 同模式 (truncate + try/finally close)."""
    conn = init_reflections_db(db_path)
    try:
        conn.execute(
            "INSERT INTO reflections (ts, task_id, domain, goal, final_result, root_cause, hint) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                time.time(),
                task_id,
                domain,
                goal[:RESULT_TRUNC],
                final_result[:RESULT_TRUNC],
                root_cause[:RESULT_TRUNC],
                hint[:RESULT_TRUNC],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def recall_reflections_by_domain(
    db_path: Path,
    domain: str,
    limit: int = 3,
) -> list[ReflectionEntry]:
    """V0.28.1: 查 domain 下最近 N 条反思 (DESC by ts). db 不存在返 [] (跟 recall_by_domain 同).

    V0.28.2 cli inject 时调, 默 limit=3 比 recall_by_domain (5) 少 — 反思 hint 比 task outcome
    更精炼, 3 条够给 LLM 上下文不污染.
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ts, task_id, domain, goal, final_result, root_cause, hint FROM reflections "
            "WHERE domain = ? ORDER BY ts DESC LIMIT ?",
            (domain, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        ReflectionEntry(
            ts=r[0], task_id=r[1], domain=r[2], goal=r[3],
            final_result=r[4], root_cause=r[5], hint=r[6],
        )
        for r in rows
    ]


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


def format_reflections_for_trace(
    entries: list[ReflectionEntry],
    hint_trunc: int = 120,
) -> str:
    """V0.28.2 W6-B: 渲染 list[ReflectionEntry] 为 LLM 可读字符串供 trace 注入.

    格式 (跟 format_memories_for_trace 平行, 但精简 — 不带 goal/final_result, 反思是经验提炼
    不重复 memories 的 "任务结果" 信息):
        上次在该 domain 失败教训 (newest first, 共 N 条):
        [2026-05-09T14:22:01] 页面加载慢 → 下次先 wait_for_selector('.results') 再 click
        [2026-05-08T09:05:33] 误点了广告 banner → 优先用 role=link name=正文标题 定位

    空 list 返 "" (caller 可 if-truthy 跳过 inject). token-budget 友好: 3 条 × ~140 char ≈
    420 char total, 跟 memories 5 条相加 ≈ 1.1k char 仍在 loop.py:508 [:2000] 截断内.
    """
    if not entries:
        return ""
    lines = [f"上次在该 domain 失败教训 (newest first, 共 {len(entries)} 条):"]
    for e in entries:
        ts = datetime.fromtimestamp(e.ts).isoformat(timespec="seconds")
        lines.append(f"[{ts}] {e.root_cause} → {e.hint[:hint_trunc]}")
    return "\n".join(lines)


def format_memories_for_trace(
    entries: list[MemoryEntry],
    goal_trunc: int = 60,
    result_trunc: int = 80,
) -> str:
    """W5-D.2: 渲染 list[MemoryEntry] 为 LLM 可读字符串供 trace 注入。

    格式 (与 main CLI 输出一致):
        过去在该 domain 跑过 N 个任务 (newest first):
        [2026-05-03T10:22:01] OK   订机票 BOS->JFK -> 已下单订单号 ABC123
        [2026-05-02T18:00:00] FAIL 改签机票 -> SAFETY_BLOCK at step 4: ...

    空 list 返 "" (caller 可 if-truthy 跳过 inject)。token-budget 友好:
    5 条 × ~140 char ≈ 700 char total。
    """
    if not entries:
        return ""
    lines = [f"过去在该 domain 跑过 {len(entries)} 个任务 (newest first):"]
    for e in entries:
        ts = datetime.fromtimestamp(e.ts).isoformat(timespec="seconds")
        flag = "OK  " if e.success else "FAIL"
        lines.append(
            f"[{ts}] {flag} {e.goal[:goal_trunc]} -> {e.result[:result_trunc]}"
        )
    return "\n".join(lines)


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
