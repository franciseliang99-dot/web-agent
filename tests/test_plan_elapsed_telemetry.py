"""V0.66.1 (TDD red): per-step plan() 调用延迟遥测 — instrumentation only, 0 行为变化.

V0.66.1 契约 (来自 V0.66.0 CHANGELOG b8c5a32):
- trace.Step 加 `plan_elapsed_s: float | None` 字段 (default None).
- trace.py schema + init_db 加同名列 (REAL, NULL allowed) + V0.53.0/V0.33.1 startup
  ALTER TABLE 兼容模式 (老 db 自动补列).
- loop.py plan() 调用块前后包 `time.monotonic()`, 成功后写入 Step.plan_elapsed_s.
- write_step round-trip 持久化 + 读回.

跟 V0.33.1 test_token_per_step.py 同 shape (per-step capture from client.last_*),
但跟 token 不同: plan_elapsed_s 不从 client 字段读, 是 loop.py 自己用 monotonic 测.

TDD red 阶段: V0.66.1 未实现 → 全部 4 测应失败 (AttributeError / sqlite OperationalError /
write_step TypeError / KeyError / 写盘 0/NULL 而非真值).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from web_agent.loop import run_react_loop
from web_agent.perceiver import Mark
from web_agent.trace import Step, init_db, write_step
from web_agent.types import DoneAction, ScrollAction


# ---------- 测试 1: Step 含 plan_elapsed_s 字段, 默认 None ----------

def test_step_has_plan_elapsed_s_field_default_none():
    """V0.66.1: Step dataclass 加 plan_elapsed_s: float | None, default None."""
    field_names = {f.name for f in fields(Step)}
    assert "plan_elapsed_s" in field_names, (
        f"Step 字段应含 plan_elapsed_s (V0.66.1 instrumentation), 实际字段: {field_names}"
    )
    # 默认值 None — 用最小 required 字段构造, 不显式传 plan_elapsed_s
    s = Step(
        step=0, ts=0.0, thought="t",
        action_type="click", action_args={"mark_id": 1},
    )
    assert s.plan_elapsed_s is None, (
        f"未指定时 plan_elapsed_s 应默认 None, 实际: {s.plan_elapsed_s!r}"
    )


def test_step_plan_elapsed_s_accepts_float():
    """V0.66.1: plan_elapsed_s 应接受 float 值 (round-trip 验)."""
    s = Step(
        step=0, ts=0.0, thought="t",
        action_type="click", action_args={"mark_id": 1},
        plan_elapsed_s=1.234,
    )
    assert s.plan_elapsed_s == pytest.approx(1.234)


# ---------- 测试 2: init_db 表含 plan_elapsed_s 列 ----------

def test_init_db_steps_table_has_plan_elapsed_s_column(tmp_path):
    """V0.66.1: init_db 创建 steps 表应含 plan_elapsed_s REAL 列 (NULL allowed)."""
    conn = init_db(tmp_path / "trace.db")
    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(steps)").fetchall()}
    conn.close()
    assert "plan_elapsed_s" in cols, (
        f"steps 表应含 plan_elapsed_s 列 (V0.66.1), 实际列: {list(cols.keys())}"
    )
    # 类型应是 REAL (float), 不是 INTEGER (跟 token 不同 — 延迟是连续值)
    assert cols["plan_elapsed_s"].upper() == "REAL", (
        f"plan_elapsed_s 列应是 REAL 类型 (V0.66.1 instrumentation 测连续延迟), "
        f"实际: {cols['plan_elapsed_s']!r}"
    )


def test_init_db_alter_table_generalize_old_db(tmp_path):
    """V0.66.1: 老 db (V0.66.0 前) 缺 plan_elapsed_s 列, init_db 应幂等 ALTER 补列.

    V0.53.0/V0.33.1 startup generalize 模式 — 老 db schema 升级在 init_db 自动跑.
    """
    db = tmp_path / "trace.db"
    # 手工建 V0.66.0 前的老 schema (无 plan_elapsed_s)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE steps (
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
            PRIMARY KEY (task_id, step)
        )
        """
    )
    conn.commit()
    conn.close()
    # init_db 再开 → 应自动 ALTER 补 plan_elapsed_s, 不抛
    conn2 = init_db(db)
    cols = {r[1] for r in conn2.execute("PRAGMA table_info(steps)").fetchall()}
    conn2.close()
    assert "plan_elapsed_s" in cols, (
        f"init_db 应 ALTER 老 db 加 plan_elapsed_s 列 (V0.66.1 generalize), "
        f"实际列: {cols}"
    )


# ---------- 测试 3: write_step 持久化 plan_elapsed_s round-trip ----------

def test_write_step_persists_plan_elapsed_s_roundtrip(tmp_path):
    """V0.66.1: write_step 应把 Step.plan_elapsed_s 写入 sqlite, SELECT 读回一致."""
    conn = init_db(tmp_path / "trace.db")
    s = Step(
        step=0, ts=1234567890.0, thought="t",
        action_type="click", action_args={"mark_id": 1},
        plan_elapsed_s=0.789,
    )
    write_step(conn, "t1", s)
    row = conn.execute(
        "SELECT plan_elapsed_s FROM steps WHERE task_id='t1' AND step=0"
    ).fetchone()
    conn.close()
    assert row is not None, "write_step 后应有行"
    assert row[0] == pytest.approx(0.789), (
        f"plan_elapsed_s 应 round-trip 一致, 期望 0.789, 实际: {row[0]!r}"
    )


def test_write_step_persists_plan_elapsed_s_none_as_null(tmp_path):
    """V0.66.1: plan_elapsed_s=None (未测延迟 / mock 客户端) 应落 NULL, 不抛."""
    conn = init_db(tmp_path / "trace.db")
    s = Step(
        step=0, ts=0.0, thought="t",
        action_type="click", action_args={"mark_id": 1},
        # 不传 plan_elapsed_s → default None
    )
    write_step(conn, "t1", s)
    row = conn.execute(
        "SELECT plan_elapsed_s FROM steps WHERE task_id='t1' AND step=0"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] is None, f"None 应落 NULL, 实际: {row[0]!r}"


# ---------- 测试 4: loop.py plan() 块包 monotonic 写入 Step.plan_elapsed_s ----------

# 沿用 test_token_per_step.py 的 patch_loop_internals + FakeContext + FakePage 模式
# (V0.33.1 已落地稳态, 复刻防退化).

_DUMMY_MARK = Mark(
    id=1, tag="button", role="", text="ok",
    bbox={"x": 0, "y": 0, "w": 80, "h": 30},
    input_type="", name="", href="",
)
_FAKE_SHOT = "aGVsbG8h"


class _SlowFakeLLMClient:
    """V0.66.1 red: plan() 调用前 sleep 一段 (模拟真 LLM 延迟), 验 loop 用 monotonic 量到差.

    sleep 时长固定 → loop.py 包的 t_end - t_start 应 >= sleep_s (单调时钟保护).
    last_usage = None — V0.66.1 测的是 loop.py 自己测延迟, 不依赖 client 字段.
    """
    name = "fake-slow"
    model = "fake"
    last_usage = None

    def __init__(self, actions: list, sleep_s: float) -> None:
        self._actions = list(actions)
        self._i = 0
        self._sleep_s = sleep_s

    async def plan(self, goal, screenshot_b64, marks, trace, **kwargs):
        import asyncio
        await asyncio.sleep(self._sleep_s)
        a = self._actions[self._i]
        self._i += 1
        return a


class _FakePage:
    class _Keyboard:
        async def press(self, key: str) -> None:
            return None

    def __init__(self) -> None:
        self.url = "about:blank"
        self.keyboard = _FakePage._Keyboard()

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        return None

    async def bring_to_front(self) -> None:
        return None

    async def title(self) -> str:
        return ""


class _FakeContext:
    def __init__(self) -> None:
        self.pages = [_FakePage()]

    def on(self, event: str, handler) -> None:
        pass


async def _fake_perceive(page):
    return [_DUMMY_MARK], _FAKE_SHOT, []


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def patch_loop_internals(monkeypatch):
    monkeypatch.setattr("web_agent.loop.perceive", _fake_perceive)
    monkeypatch.setattr("web_agent.loop.think", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_click", _noop)
    monkeypatch.setattr("web_agent.loop.human_like_type", _noop)
    monkeypatch.setattr("web_agent.loop.scroll", _noop)


async def test_loop_writes_plan_elapsed_s_monotonic_delta(
    monkeypatch, tmp_path, patch_loop_internals,
):
    """V0.66.1 核心: loop.py plan() 调用块前后包 time.monotonic(),
    step.plan_elapsed_s = t_end - t_start (单调差).

    构造: plan() 内 sleep 0.05s → 写盘 plan_elapsed_s 应 >= 0.05 且 < 5.0 (上界防 flaky).
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    sleep_s = 0.05
    actions = [DoneAction(thought="x", result="ok")]
    client = _SlowFakeLLMClient(actions, sleep_s=sleep_s)

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _FakeContext(), client, goal="测 plan_elapsed_s",
        max_steps=1, db_path=db, screenshots_dir=shots,
    )
    assert result == "ok"

    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT step, plan_elapsed_s FROM steps ORDER BY step"
    ).fetchall()
    conn.close()
    assert len(rows) == 1, f"应写 1 step row, 实际: {rows}"
    step_idx, elapsed = rows[0]
    assert step_idx == 0
    assert elapsed is not None, (
        f"V0.66.1: loop 写盘的 plan_elapsed_s 不应是 NULL "
        f"(plan() 成功调用过, loop 必须测延迟), 实际: {elapsed!r}"
    )
    assert elapsed >= sleep_s, (
        f"plan_elapsed_s ({elapsed!r}) 应 >= 模拟 sleep ({sleep_s}), "
        f"单调差不应小于真实 sleep 时长"
    )
    # 上界宽松 (CI flaky 保护): 0.05s sleep + loop overhead 远小于 5s
    assert elapsed < 5.0, (
        f"plan_elapsed_s ({elapsed!r}) 异常大, 怀疑被错算成 epoch 时间"
    )


async def test_loop_plan_elapsed_s_per_step_independent(
    monkeypatch, tmp_path, patch_loop_internals,
):
    """V0.66.1: 多 step 各自测自己的 plan_elapsed_s, 不累计 / 不共享.

    构造: 3 step 不同 sleep (0.02 / 0.05 / 0.01) → 写盘 3 行各自 >= 对应 sleep.
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    # 三个 step 的 plan() 各 sleep 不同时长 — 用 list-based 客户端
    class _PerStepSlowClient:
        name = "per-step-slow"
        model = "fake"
        last_usage = None

        def __init__(self, actions: list, sleeps: list[float]) -> None:
            assert len(actions) == len(sleeps)
            self._actions = list(actions)
            self._sleeps = list(sleeps)
            self._i = 0

        async def plan(self, goal, screenshot_b64, marks, trace, **kwargs):
            import asyncio
            await asyncio.sleep(self._sleeps[self._i])
            a = self._actions[self._i]
            self._i += 1
            return a

    actions = [
        ScrollAction(thought="x", dy=100),
        ScrollAction(thought="x", dy=200),
        DoneAction(thought="x", result="ok"),
    ]
    sleeps = [0.02, 0.05, 0.01]
    client = _PerStepSlowClient(actions, sleeps)

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    await run_react_loop(
        _FakeContext(), client, goal="测 per-step plan_elapsed",
        max_steps=3, db_path=db, screenshots_dir=shots,
    )

    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT step, plan_elapsed_s FROM steps ORDER BY step"
    ).fetchall()
    conn.close()
    assert len(rows) == 3, f"应写 3 step row, 实际: {rows}"

    for (step_idx, elapsed), expected_sleep in zip(rows, sleeps, strict=True):
        assert elapsed is not None, (
            f"step {step_idx} plan_elapsed_s 不应 NULL"
        )
        assert elapsed >= expected_sleep, (
            f"step {step_idx} plan_elapsed_s ({elapsed!r}) 应 >= sleep "
            f"({expected_sleep})"
        )
        assert elapsed < 5.0, (
            f"step {step_idx} plan_elapsed_s ({elapsed!r}) 异常大"
        )
