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


# V0.47.2: protection_observations 表 — 跟 reflections 表分开 (schema 演进独立, 同模式).
# 同 db 文件 (data/memory.db). V0.47.3 cli inject 时 recall_protection_by_domain 拉最近 1 条
# inject 给 planner ("本 domain 上次保护等级: high").


@dataclass
class ProtectionObservation:
    """V0.47.2: 单次防护识别记录, V0.47.3 cli inject 时 recall 最近一条注入 planner."""

    ts: float
    domain: str
    level: str  # protection.ProtectionLevel literal value (low/medium/high/unknown)
    signals_json: str  # JSON of ProtectionSignal (server/status/cookies/cf_ray/captcha_vendor)


def init_protections_db(db_path: Path) -> sqlite3.Connection:
    """V0.47.2: 建 protection_observations 表 + index. 跟 init_reflections_db 同模式."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS protection_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            domain TEXT NOT NULL,
            level TEXT NOT NULL,
            signals_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_protections_domain_ts "
        "ON protection_observations(domain, ts DESC)"
    )
    conn.commit()
    return conn


def record_protection(
    db_path: Path,
    domain: str,
    level: str,
    signals_json: str,
) -> None:
    """V0.47.2: 写一条 protection observation. 跟 record_reflection 同 try/finally 模式."""
    conn = init_protections_db(db_path)
    try:
        conn.execute(
            "INSERT INTO protection_observations (ts, domain, level, signals_json) VALUES (?,?,?,?)",
            (time.time(), domain, level, signals_json[:RESULT_TRUNC]),
        )
        conn.commit()
    finally:
        conn.close()


def format_protection_for_trace(obs: ProtectionObservation | None) -> str:
    """V0.47.3: 1 行精炼 protection level signal 给 planner inject (跟 V0.41 stats_str 同精炼).

    None / unknown 返 "" (caller if-truthy skip). low/medium/high 返 "[protection] <domain>
    上次保护等级: <level>" — planner 看到等级自决重 retry / 换 task / 调整 plan.
    不暴露 signals_json 细节 (planner 不需 raw header, signals 留 audit dump 看).
    """
    if obs is None or obs.level == "unknown":
        return ""
    return f"[protection] {obs.domain} 上次保护等级: {obs.level}"


def recall_protection_by_domain(
    db_path: Path,
    domain: str,
) -> ProtectionObservation | None:
    """V0.47.2: 查 domain 最近 1 条 protection 记录. db / 表不存在返 None.

    比 reflections (3 条) 更紧 — protection level 是 latest-snapshot 性质 (上次见此 domain 啥等级),
    不需历史 trend (那是 stats 表的事, V0.41 C1 已 cover domain_stats).
    """
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        try:
            row = conn.execute(
                "SELECT ts, domain, level, signals_json FROM protection_observations "
                "WHERE domain = ? ORDER BY ts DESC LIMIT 1",
                (domain,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None  # 表不存在 (V0.47.2 部署前 db) — silent (跟 recall_reflections 同模式)
    finally:
        conn.close()
    if not row:
        return None
    return ProtectionObservation(ts=row[0], domain=row[1], level=row[2], signals_json=row[3])


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


@dataclass(frozen=True, slots=True)
class DomainStats:
    """V0.41.0 C 主题: cross-task 学习 — domain-level success rate 聚合.

    跟 MemoryEntry 平行, 但 aggregate (sum/count) 而非 raw row. recent_days 锁查询窗口,
    pass_rate 是 success/total (float 0..1). last_ts 是该 domain 最近一次 task 时间戳.

    用例: planner 看到 'wikipedia.org 历史 6 task 67% pass (last 2026-05-08)' 后, 在 wikipedia
    上的 task 探索/退避策略可以基于 cross-task 历史而非纯当 task LLM 直觉.
    """

    total: int
    success: int
    pass_rate: float
    recent_n_days: int
    last_ts: float


def aggregate_domain_stats(
    db_path: Path,
    domain: str,
    *,
    recent_days: int = 30,
    min_total: int = 3,
) -> DomainStats | None:
    """V0.41.0 C 主题: 聚合 domain 历史 task pass rate.

    返 None 条件 (V0.34 教训应用 — 不 inject noise):
    - db_path 不存在 (silent, 跟 recall_by_domain 同 pattern)
    - domain 为空字符串 (V0.41.0 真发现 #21+: 生产 memory.db 含 625 行 domain='' 测试污染, 聚合等于污染 cross-task 学习)
    - total < min_total (信号不足, 默 3 task — 1-2 task 算不出可靠 pass rate)

    db_path: data/memory.db Path
    domain: extract_domain(start_url) 输出
    recent_days: 查询窗口 (默 30 天, 防 90 天前老数据稀释 recent signal)
    min_total: 信号阈值 (默 3, 低于此返 None 不 inject)

    Returns:
        DomainStats(total, success, pass_rate, recent_n_days, last_ts) 或 None
    """
    if not db_path.exists() or not domain.strip():
        return None
    cutoff_ts = time.time() - recent_days * 86400
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(success), 0), COALESCE(MAX(ts), 0) "
            "FROM memories WHERE domain = ? AND ts >= ?",
            (domain, cutoff_ts),
        ).fetchone()
    finally:
        conn.close()
    if not row or row[0] < min_total:
        return None
    total = int(row[0])
    success = int(row[1])
    return DomainStats(
        total=total,
        success=success,
        pass_rate=success / total,
        recent_n_days=recent_days,
        last_ts=float(row[2]),
    )


def format_domain_stats_for_trace(stats: DomainStats | None) -> str:
    """V0.41.0 C 主题: 渲染 DomainStats 为 LLM 可读 1 行字符串 (跟 format_memories_for_trace 平行).

    格式: '本 domain 最近 N 天历史 X task, P% pass rate (last seen YYYY-MM-DD)'
    None / 空 stats 返 ''. token-budget 友好 ~100 char, 跟 memories 5 条 + reflections 3 条
    相加仍在 loop.py:508 [:2000] 截断内.
    """
    if stats is None:
        return ""
    last_date = datetime.fromtimestamp(stats.last_ts).strftime("%Y-%m-%d")
    return (
        f"本 domain 最近 {stats.recent_n_days} 天历史 {stats.total} task, "
        f"{stats.pass_rate * 100:.0f}% pass rate (last seen {last_date})"
    )


@dataclass(frozen=True, slots=True)
class FailurePattern:
    """V0.41.1 C3 主题: domain-level failure root-cause 频度.

    跟 DomainStats 平行 (聚合层非 raw row), 但维度从 success rate → failure marker 频度.
    用例: planner 看到 'wikipedia.org 历史 fail 3/5 因 SAFETY_BLOCK' 后, 在 wiki 上跑前
    preemptive 准备 safety prompt 或 cassette 已知 fail mode.

    reframe 用 memories.result 抽 FAILURE_MARKERS 而非 V0.28 reflections 表 — 因真发现 #21
    生产 db reflections 表不存在, memories.result 才有 raw fail 信号 (V0.41.0 真测 36 行真站点
    数据中 ~10-15 行有 FAILURE_MARKERS prefix).
    """

    marker: str  # FAILURE_MARKERS 之一 (e.g. "SAFETY_BLOCK", "LOOP_DETECTED")
    count: int
    fraction: float  # count / total_failures (在该 domain 内)


def summarize_domain_failures(
    db_path: Path,
    domain: str,
    *,
    recent_days: int = 30,
    top_n: int = 3,
    min_failures: int = 2,
) -> list[FailurePattern]:
    """V0.41.1 C3 主题: 抽 domain failure root-cause 频度 (跟 aggregate_domain_stats 平行).

    返 [] 条件 (V0.34 教训应用 — 不 inject noise):
    - db_path 不存在
    - domain 为空字符串 (跟 V0.41.0 aggregate 同, 避测试污染聚合)
    - total failures < min_failures (默 2, 1 fail 算不出 pattern)

    db_path: data/memory.db Path
    domain: extract_domain(start_url) 输出
    recent_days: 查询窗口 (默 30 天)
    top_n: 返 top N 个 marker (默 3)
    min_failures: 信号阈值 (默 2, 低于此返 [])

    Returns:
        list[FailurePattern] DESC by count, top_n 个 (空 list 表无信号或 db 不存在)
    """
    if not db_path.exists() or not domain.strip():
        return []
    cutoff_ts = time.time() - recent_days * 86400
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT result FROM memories WHERE domain = ? AND success = 0 AND ts >= ?",
            (domain, cutoff_ts),
        ).fetchall()
    finally:
        conn.close()
    if len(rows) < min_failures:
        return []
    # 抽 FAILURE_MARKERS 频度 (跟 is_success 同 substring 匹配, V0.41.1 reframe 用 memories.result)
    counts: dict[str, int] = {}
    for (result,) in rows:
        for marker in FAILURE_MARKERS:
            if marker in result:
                counts[marker] = counts.get(marker, 0) + 1
                break  # 每 fail 计 1 marker 最先匹配的
    if not counts:
        return []
    total_failures = sum(counts.values())
    patterns = sorted(
        (
            FailurePattern(marker=m, count=c, fraction=c / total_failures)
            for m, c in counts.items()
        ),
        key=lambda p: -p.count,
    )
    return patterns[:top_n]


def format_domain_failures_for_trace(patterns: list[FailurePattern]) -> str:
    """V0.41.1 C3 主题: 渲 list[FailurePattern] 为 LLM 可读 1 行 (跟 format_domain_stats 平行).

    格式: '本 domain 最常 fail 因: SAFETY_BLOCK (3, 50%), LOOP_DETECTED (2, 33%), ...'
    空 list 返 ''. token-budget 友好 (~100 char).
    """
    if not patterns:
        return ""
    parts = [
        f"{p.marker} ({p.count}, {p.fraction * 100:.0f}%)"
        for p in patterns
    ]
    return "本 domain 最常 fail 因: " + ", ".join(parts)


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


def build_inject_string(
    db_path: Path,
    domain: str,
    *,
    include_memories: bool = True,
    include_reflections: bool = True,
    memories_limit: int = 5,
    reflections_limit: int = 3,
) -> str | None:
    """V0.28.3 W6-B 收尾: cli + eval 共用的 memories + reflections 构造器 (subagent Z 路径).

    抽 cli.py V0.28.2 inline 路径 (recall + format + merge_into_memories) 让 eval/runner.py
    也能复用. 任一 recall 失败 silent swallow + 返 None (caller 可 if-truthy 跳 inject).

    Args:
        db_path: memory.db Path
        domain: extract_domain(start_url) 输出
        include_memories: opt-in W5-D.2 memories (cli 用 WEB_AGENT_MEMORY_DISABLE env, eval 直传 bool)
        include_reflections: opt-in W6-B reflections (cli 用 WEB_AGENT_REFLECTIONS_DISABLE env)
        memories_limit / reflections_limit: 各自 recall limit (cli 默 5/3, eval 可调)

    Returns:
        memories_str + reflections_str 拼接 (memories 在前, reflections 在后), 都空返 None.
    """
    parts: list[str] = []
    if include_memories:
        # V0.47.3 主题: prepend domain protection level (1 行 most-high-level 信号 — planner 先看
        # "本 domain 有没有 CF/Akamai 高防护" 再看 trend / failure markers / raw memories).
        # recall 失败 silent skip.
        try:
            prot_obs = recall_protection_by_domain(db_path, domain)
            prot_str = format_protection_for_trace(prot_obs)
            if prot_str:
                parts.append(prot_str)
        except Exception:
            pass
        # V0.41.0 C1 主题: prepend domain success rate aggregate (1 行 cross-task signal 让
        # planner 先看 high-level pass rate, 再看 raw 5 条 task). aggregate 失败 silent skip.
        try:
            stats = aggregate_domain_stats(db_path, domain)
            stats_str = format_domain_stats_for_trace(stats)
            if stats_str:
                parts.append(stats_str)
        except Exception:
            pass
        # V0.41.1 C3 主题: prepend failure root-cause cache (跟 stats 同层级 cross-task 学习,
        # 但维度从 success rate → fail marker 频度). reframe 用 memories.result 不用 reflections.
        try:
            failures = summarize_domain_failures(db_path, domain)
            failures_str = format_domain_failures_for_trace(failures)
            if failures_str:
                parts.append(failures_str)
        except Exception:
            pass
        try:
            mem_entries = recall_by_domain(db_path, domain, limit=memories_limit)
            mem_str = format_memories_for_trace(mem_entries)
            if mem_str:
                parts.append(mem_str)
        except Exception:
            pass
    if include_reflections:
        try:
            refl_entries = recall_reflections_by_domain(db_path, domain, limit=reflections_limit)
            refl_str = format_reflections_for_trace(refl_entries)
            if refl_str:
                parts.append(refl_str)
        except Exception:
            pass
    return "\n\n".join(parts) if parts else None


def clear_reflections(db_path: Path) -> None:
    """V0.28.3 eval 隔离: 跨 task 跑前清 reflections 表防 domain 污染 (Risk #1 修).

    Plan subagent 揭关键 bug: reflections 按 **domain** 索引非 task_id, 两 task 共 domain
    时 task A run1 写的反思会被 task B run2 拉到 → 跨 task 污染 uplift signal. eval/runner.py
    每 task 跑 2 次前必清表, 保证 run2 只看到自己 run1 的反思.

    DB 不存在 / 表不存在 silent (跟 recall_reflections_by_domain 同模式).
    """
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM reflections")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # reflections 表不存在 (W6-A 失败时才建) — 没数据可清, OK
    finally:
        conn.close()


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
