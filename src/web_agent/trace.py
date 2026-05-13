"""Action Trace：内存短期记忆 + SQLite 持久化每步截图/思考/行动。"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# V0.70: 对哪些 action 期望触发 nav, 决定 for_llm 是否注入 no_nav_after_action positive signal.
# extract/scroll/done/upload 本不该 nav, url 不变正常, 不触发避免误导 LLM.
_NAV_EXPECTING_ACTIONS = frozenset({"click", "keyboard_shortcut", "switch_tab", "type"})


@dataclass
class Step:
    step: int
    ts: float
    thought: str
    action_type: str  # click / type / scroll / extract / done
    action_args: dict[str, Any]
    observation: str = ""
    # V0.33.1: per-step token cost (修 V0.26.2 silent bug #14 — last_usage × len(steps) 高估,
    # prompt cache 命中后第 2+ step input_tokens 大降, 改 per-step 真累加从 client.last_usage 读).
    input_tokens: int = 0
    output_tokens: int = 0
    # V0.42.0 D 主题 cache hit-rate audit: Anthropic cache_creation (首次写, 1.25× input cost) +
    # cache_read (命中, 0.1× input cost). OpenAI/Kimi 只有 cache_read (auto cache 无 creation 概念).
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    # V0.66.1: plan() 单步 wall clock latency (time.monotonic 差, 含 SDK retry). None 表示该 step
    # 没成功 plan (LLM_FAILED) — 给 V0.66.2 Provider-aware wallclock 数据驱动定 baseline.
    plan_elapsed_s: float | None = None
    # V0.69: action 前后 page.url snapshot — 当 url_before != url_after, for_llm 注入
    # nav_side_effect 字段让 LLM 因果归因 "上一 action 触发了 nav" vs "自然加载". V0.68 Supabase
    # dogfood: type URL 后 React effect 跳页, LLM 下一步在 wrong page 决策的根因解决.
    url_before: str = ""
    url_after: str = ""

    def for_llm(self) -> dict[str, Any]:
        """给 LLM 看的精简版（不带截图、observation 截断）。"""
        d: dict[str, Any] = {
            "step": self.step,
            "thought": self.thought,
            "action": {"type": self.action_type, **self.action_args},
            "observation": self.observation[:200],
        }
        if self.url_before and self.url_after and self.url_before != self.url_after:
            d["nav_side_effect"] = f"{self.url_before} → {self.url_after}"
        elif (
            self.url_before
            and self.url_after
            and self.action_type in _NAV_EXPECTING_ACTIONS
        ):
            # V0.70: nav-expecting action 但 url 没变 → 显式 positive signal, 防 LLM 重试无效 mark.
            # V0.69 dogfood Supabase mark 49 click 后 url 没变 + LLM 没察觉连点 3 次撞 anti-loop 根因解决.
            d["no_nav_after_action"] = True
        return d


@dataclass
class Trace:
    task_id: str
    goal: str
    steps: deque[Step] = field(default_factory=lambda: deque(maxlen=20))

    def append(self, s: Step) -> None:
        self.steps.append(s)

    def for_llm(self) -> list[dict[str, Any]]:
        return [s.for_llm() for s in self.steps]


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS steps (
            task_id TEXT NOT NULL,
            step INTEGER NOT NULL,
            ts REAL NOT NULL,
            thought TEXT,
            action_type TEXT,
            action_args TEXT,
            screenshot_path TEXT,
            observation TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_creation_input_tokens INTEGER DEFAULT 0,
            cache_read_input_tokens INTEGER DEFAULT 0,
            plan_elapsed_s REAL,
            url_before TEXT DEFAULT '',
            url_after TEXT DEFAULT '',
            PRIMARY KEY (task_id, step)
        )
        """
    )
    # V0.33.1 + V0.42.0 + V0.66.1: ALTER 兼容老 db (新列幂等 try/except). V0.66.1 plan_elapsed_s
    # 是 REAL nullable (无 default), 跟 V0.33.1 V0.42.0 INTEGER DEFAULT 0 类型不同 → 分组 ALTER.
    for col in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        try:
            conn.execute(f"ALTER TABLE steps ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column 已存 (新 db CREATE 时已加 / 老 db 之前 ALTER 过)
    try:
        conn.execute("ALTER TABLE steps ADD COLUMN plan_elapsed_s REAL")
    except sqlite3.OperationalError:
        pass  # column 已存
    # V0.69: url_before / url_after ALTER 兼容老 db.
    for col in ("url_before", "url_after"):
        try:
            conn.execute(f"ALTER TABLE steps ADD COLUMN {col} TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            started_at REAL NOT NULL,
            ended_at REAL,
            result TEXT
        )
        """
    )
    conn.commit()
    return conn


def write_step(
    conn: sqlite3.Connection,
    task_id: str,
    s: Step,
    screenshot_path: str = "",
) -> None:
    # V0.33.1 + V0.42.0 + V0.66.1 + V0.69: 加 cache_creation/cache_read + plan_elapsed_s + url_before/after INSERT
    conn.execute(
        "INSERT OR REPLACE INTO steps "
        "(task_id, step, ts, thought, action_type, action_args, screenshot_path, "
        "observation, input_tokens, output_tokens, "
        "cache_creation_input_tokens, cache_read_input_tokens, plan_elapsed_s, "
        "url_before, url_after) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            task_id,
            s.step,
            s.ts,
            s.thought,
            s.action_type,
            json.dumps(s.action_args, ensure_ascii=False),
            screenshot_path,
            s.observation,
            s.input_tokens,
            s.output_tokens,
            s.cache_creation_input_tokens,
            s.cache_read_input_tokens,
            s.plan_elapsed_s,
            s.url_before,
            s.url_after,
        ),
    )
    conn.commit()


def start_task(conn: sqlite3.Connection, task_id: str, goal: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO tasks VALUES (?,?,?,NULL,NULL)",
        (task_id, goal, time.time()),
    )
    conn.commit()


def end_task(conn: sqlite3.Connection, task_id: str, result: str) -> None:
    conn.execute(
        "UPDATE tasks SET ended_at=?, result=? WHERE task_id=?",
        (time.time(), result, task_id),
    )
    conn.commit()
