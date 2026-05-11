"""Action Trace：内存短期记忆 + SQLite 持久化每步截图/思考/行动。"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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

    def for_llm(self) -> dict[str, Any]:
        """给 LLM 看的精简版（不带截图、observation 截断）。"""
        return {
            "step": self.step,
            "thought": self.thought,
            "action": {"type": self.action_type, **self.action_args},
            "observation": self.observation[:200],
        }


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
            PRIMARY KEY (task_id, step)
        )
        """
    )
    # V0.33.1: ALTER 兼容老 db (V0.33.0 之前 schema 缺 token 列). sqlite ADD COLUMN 幂等性靠
    # try/except (重复 ALTER raise OperationalError "duplicate column").
    for col in ("input_tokens", "output_tokens"):
        try:
            conn.execute(f"ALTER TABLE steps ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column 已存 (新 db CREATE 时已加 / 老 db 之前 ALTER 过)
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
    # V0.33.1: 加 input_tokens/output_tokens 列 INSERT (per-step token 累加修 silent bug #14)
    conn.execute(
        "INSERT OR REPLACE INTO steps "
        "(task_id, step, ts, thought, action_type, action_args, screenshot_path, "
        "observation, input_tokens, output_tokens) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
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
