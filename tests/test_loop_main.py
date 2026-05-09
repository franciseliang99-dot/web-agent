"""loop.py 主体 abort 路径单测 (audit gap 收尾)。

V0.7.0 safety-loop / V0.9.0 captcha / V0.11.0 reflect 间接覆盖了 done / safety_block /
captcha_timeout 路径; 此 file 直测剩 3 条 abort 出口:
- max_steps 耗尽 → "(max_steps 耗尽未完成)" (loop.py L291)
- wallclock 超时 → "WALLCLOCK_EXCEEDED at step N" (loop.py L147-154, 不写 step 仅 end_task)
- LLM 异常 graceful capture → "LLM_FAILED at step N" + trace 落 action_type="error" (L176-190)

复用 V0.7.0 / V0.9.0 / V0.11.0 inline FakePage/FakeLLMClient/patch_loop_internals 模式。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from web_agent.types import Action, DoneAction, ScrollAction
from web_agent.loop import run_react_loop
from web_agent.perceiver import Mark


_DUMMY_MARK = Mark(
    id=1, tag="button", role="", text="ok",
    bbox={"x": 0, "y": 0, "w": 80, "h": 30},
    input_type="", name="", href="",
)
_FAKE_SHOT = "aGVsbG8h"


class FakeLLMClient:
    name = "fake"
    model = "fake"

    def __init__(self, actions: list[Action]) -> None:
        self._actions = list(actions)
        self._i = 0

    async def plan(self, goal, screenshot_b64, marks, trace) -> Action:
        a = self._actions[min(self._i, len(self._actions) - 1)]
        self._i += 1
        return a


class FakePage:
    class _Keyboard:
        async def press(self, key: str) -> None:
            return None

    keyboard = _Keyboard()

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        return None


async def _fake_perceive(page):
    return [_DUMMY_MARK], _FAKE_SHOT


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def patch_loop_internals(monkeypatch):
    monkeypatch.setattr("web_agent.loop.perceive", _fake_perceive)
    monkeypatch.setattr("web_agent.loop.think", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_click", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_type", _noop)
    monkeypatch.setattr("web_agent.loop.scroll", _noop)


def _read_trace_steps(db: Path) -> list[tuple[int, str, dict]]:
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT step, action_type, action_args FROM steps ORDER BY step"
    ).fetchall()
    conn.close()
    return [(r[0], r[1], json.loads(r[2])) for r in rows]


def _read_task_result(db: Path) -> str:
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT result FROM tasks LIMIT 1").fetchone()
    conn.close()
    return row[0] if row else ""


# ---------- 三条 abort 路径 ----------

async def test_max_steps_exhausted_returns_signal_string(
    monkeypatch, tmp_path, patch_loop_internals
):
    """LLM 永不返 done; max_steps 跑完 → "(max_steps 耗尽未完成)"; trace 落 max_steps 个 step。

    用 varied scroll dy 避 V0.5.0 anti-loop 在第 3 次同 action 时提前硬 abort。
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    client = FakeLLMClient([
        ScrollAction(thought="x", dy=100),
        ScrollAction(thought="x", dy=200),
    ])  # 2 步 + max_steps=2 → 第 2 步用尽不 done → 出 max_steps 路径

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        FakePage(), client, goal="测 max_steps 耗尽",
        max_steps=2, db_path=db, screenshots_dir=shots,
    )

    assert result == "(max_steps 耗尽未完成)"
    steps = _read_trace_steps(db)
    assert len(steps) == 2
    assert all(s[1] == "scroll" for s in steps)
    assert _read_task_result(db) == "(max_steps 耗尽未完成)"


async def test_wallclock_exceeded_aborts_without_step_row(
    monkeypatch, tmp_path, patch_loop_internals
):
    """elapsed > max_wallclock_s → 走 L147-154 wallclock 出口; 仅 end_task, 不 trace.append/write_step。

    用 max_wallclock_s=-1.0 让 step 0 任何 (>=0) elapsed 立即触发, 免 monkeypatch time。
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    client = FakeLLMClient([
        ScrollAction(thought="x", dy=100),
    ])
    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"

    result = await run_react_loop(
        FakePage(), client, goal="测 wallclock 超时",
        max_steps=5, max_wallclock_s=-1.0,
        db_path=db, screenshots_dir=shots,
    )

    assert result.startswith("WALLCLOCK_EXCEEDED at step 0"), result
    assert "max_wallclock_s=-1" in result
    # wallclock 路径不写 step row
    assert _read_trace_steps(db) == []
    # 但 tasks 表 result 列已被 end_task 写
    assert _read_task_result(db).startswith("WALLCLOCK_EXCEEDED")


async def test_memories_injected_as_synthetic_step_minus_one(
    monkeypatch, tmp_path, patch_loop_internals
):
    """W5-D.2: memories 字符串 → run_react_loop 主循环前 prepend Step(step=-1,
    action_type='memory_recall'); LLM 第一次 plan 应看到; 不写 sqlite (不污染持久化)。
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    seen_traces: list[list[dict]] = []

    class RecordingLLMClient:
        name = "fake"
        model = "fake"

        async def plan(self, goal, screenshot_b64, marks, trace):
            seen_traces.append(list(trace.for_llm()))
            return DoneAction(thought="x", result="ok")

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    memories_str = "过去在该 domain 跑过 2 个任务 (newest first):\n[ts] OK foo -> bar"

    result = await run_react_loop(
        FakePage(), RecordingLLMClient(), goal="测 W5-D.2 inject",
        max_steps=2, db_path=db, screenshots_dir=shots,
        memories=memories_str,
    )

    assert result == "ok"
    # plan() 第一次看到的 trace[0] 应是 memory_recall synthetic step
    assert len(seen_traces) == 1
    first_step_in_trace = seen_traces[0][0]
    assert first_step_in_trace["action"]["type"] == "memory_recall"
    assert "过去在该 domain 跑过" in first_step_in_trace["observation"]
    # sqlite 不含 step=-1 (不污染 trace.db 实际执行事件流)
    sqlite_steps = _read_trace_steps(db)
    sqlite_step_indices = [s[0] for s in sqlite_steps]
    assert -1 not in sqlite_step_indices


async def test_llm_exception_captured_writes_error_step(
    monkeypatch, tmp_path, patch_loop_internals
):
    """client.plan 抛 RuntimeError → loop graceful capture, 写 trace error step + end_task。

    模拟 SDK 内置 max_retries 耗尽 / network / tool_call=None 等真实 LLM 失败。
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    class RaisingLLMClient:
        name = "fake"
        model = "fake"

        async def plan(self, goal, screenshot_b64, marks, trace):
            raise RuntimeError("503 upstream timeout")

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        FakePage(), RaisingLLMClient(), goal="测 LLM 异常",
        max_steps=5, db_path=db, screenshots_dir=shots,
    )

    assert result.startswith("LLM_FAILED at step 0"), result
    assert "RuntimeError" in result
    assert "503 upstream" in result

    steps = _read_trace_steps(db)
    assert len(steps) == 1
    step_i, action_type, action_args = steps[0]
    assert step_i == 0
    assert action_type == "error"
    assert "503 upstream" in action_args["error"]
    assert _read_task_result(db).startswith("LLM_FAILED")
