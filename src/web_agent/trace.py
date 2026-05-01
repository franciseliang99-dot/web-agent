"""Action Trace：内存短期记忆 + SQLite 持久化每步截图/思考/行动。"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Step:
    step: int
    ts: float
    thought: str
    action_type: str  # click / type / scroll / extract / done
    action_args: dict
    observation: str = ""

    def for_llm(self) -> dict:
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
    steps: deque = field(default_factory=lambda: deque(maxlen=20))

    def append(self, s: Step) -> None:
        self.steps.append(s)

    def for_llm(self) -> list[dict]:
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
            PRIMARY KEY (task_id, step)
        )
        """
    )
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
    conn.execute(
        "INSERT OR REPLACE INTO steps VALUES (?,?,?,?,?,?,?,?)",
        (
            task_id,
            s.step,
            s.ts,
            s.thought,
            s.action_type,
            json.dumps(s.action_args, ensure_ascii=False),
            screenshot_path,
            s.observation,
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
