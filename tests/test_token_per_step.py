"""V0.33.1: per-step token accumulator 修 V0.26.2 silent bug #14.

silent bug #14 复盘:
- V0.26.2 runner.py 算 token = `last_usage.input_tokens × len(trace_steps)` (末次 × N).
- Anthropic prompt cache 命中后第 2+ step input_tokens 大降 (~70%).
- last_usage 是末次 call (通常已 cache hit 后稳态), × N 估算 → 高估真实首 step 成本 + 漏算
  cache miss 阶段方差 → baseline 数据失真.

V0.33.1 修法:
- trace.Step 加 input_tokens / output_tokens (default 0, frozen-compat).
- loop.py plan() 成功后 capture client.last_usage → 写入 Step.
- runner.py _read_trace_steps SELECT 加 token 列 → sum(per-step) 替 last × N.
- trace.db schema ALTER 兼容老 db (V0.33.0 之前行 NULL → COALESCE 0).

本文件测:
- A: 各 step token 不同 (cache hit 模拟) → sqlite trace 各 step 真累加跟序列匹配.
- B: 末次 last_usage × N 跟真累加 sum 不等 (silent bug 修复证据).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from web_agent.loop import run_react_loop
from web_agent.perceiver import Mark
from web_agent.types import DoneAction, ScrollAction


_DUMMY_MARK = Mark(
    id=1, tag="button", role="", text="ok",
    bbox={"x": 0, "y": 0, "w": 80, "h": 30},
    input_type="", name="", href="",
)
_FAKE_SHOT = "aGVsbG8h"


@dataclass
class _FakeUsage:
    """模 Anthropic Message.usage / OpenAI ChatCompletion.usage — 只要 input/output_tokens 字段."""
    input_tokens: int
    output_tokens: int


class FakeLLMClientWithUsage:
    """V0.33.1: 每 plan() 调用按序列 set self.last_usage, 模真实 client cache-hit 阶梯."""
    name = "fake-w-usage"
    model = "fake"

    def __init__(self, actions: list, usages: list[_FakeUsage]) -> None:
        assert len(actions) == len(usages), "actions/usages 长度需一致"
        self._actions = list(actions)
        self._usages = list(usages)
        self._i = 0
        self.last_usage: _FakeUsage | None = None

    async def plan(self, goal, screenshot_b64, marks, trace, **kwargs):
        a = self._actions[self._i]
        self.last_usage = self._usages[self._i]  # 每 step 不同 last_usage 模 cache-hit 阶梯
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


def _read_step_tokens(db: Path) -> list[tuple[int, int, int]]:
    """V0.33.1: 读 trace.db steps 表 (step, input_tokens, output_tokens) — 验 schema 落盘."""
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT step, input_tokens, output_tokens FROM steps ORDER BY step"
    ).fetchall()
    conn.close()
    return rows


async def test_per_step_tokens_written_to_trace_db(monkeypatch, tmp_path, patch_loop_internals):
    """V0.33.1 核心: 各 step plan() 后 last_usage 进 Step → sqlite 真按 step 落盘各值.

    模 cache-hit 阶梯: step 0 input=10000 (cache miss), step 1 input=2000 (cache hit), step 2 input=1500.
    验 trace.db steps 表 input_tokens 列等序列, 不是末次 × 3.
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    actions = [
        ScrollAction(thought="x", dy=100),
        ScrollAction(thought="x", dy=200),
        DoneAction(thought="x", result="ok"),
    ]
    usages = [
        _FakeUsage(input_tokens=10000, output_tokens=300),  # cache miss (首 step)
        _FakeUsage(input_tokens=2000, output_tokens=250),   # cache hit (input 大降)
        _FakeUsage(input_tokens=1500, output_tokens=100),
    ]
    client = FakeLLMClientWithUsage(actions, usages)

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _FakeContext(), client, goal="测 per-step token",
        max_steps=3, db_path=db, screenshots_dir=shots,
    )

    assert result == "ok"
    rows = _read_step_tokens(db)
    assert len(rows) == 3, f"应写 3 step row, 实际: {rows}"
    # step / input / output 三元组按序匹配 usages
    expected = [(0, 10000, 300), (1, 2000, 250), (2, 1500, 100)]
    assert rows == expected, f"per-step token 不匹配: 期望 {expected}, 实际 {rows}"


async def test_legacy_estimate_overstates_vs_real_sum(monkeypatch, tmp_path, patch_loop_internals):
    """V0.33.1: 证 silent bug #14 — 末次 last_usage × N 估算 vs per-step 真累加 不等.

    构造数据: cache-hit 阶梯 step 0=10000 / step 1=2000 / step 2=1500 → 真 sum = 13500.
    legacy 估算 (末次 last_usage × N) = 1500 × 3 = 4500 → 大幅低估 (legacy 已知漏 cache miss 大头).
    本测验 V0.33.1 已用 sum 不再走 legacy 公式.
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    actions = [
        ScrollAction(thought="x", dy=100),
        ScrollAction(thought="x", dy=200),
        DoneAction(thought="x", result="ok"),
    ]
    usages = [
        _FakeUsage(input_tokens=10000, output_tokens=300),
        _FakeUsage(input_tokens=2000, output_tokens=250),
        _FakeUsage(input_tokens=1500, output_tokens=100),
    ]
    client = FakeLLMClientWithUsage(actions, usages)

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    await run_react_loop(
        _FakeContext(), client, goal="测 legacy vs sum",
        max_steps=3, db_path=db, screenshots_dir=shots,
    )

    rows = _read_step_tokens(db)
    real_input_sum = sum(r[1] for r in rows)
    real_output_sum = sum(r[2] for r in rows)
    # 末次 client.last_usage × N (V0.26.2 legacy 公式)
    legacy_input = client.last_usage.input_tokens * len(rows)  # 1500 × 3 = 4500
    legacy_output = client.last_usage.output_tokens * len(rows)  # 100 × 3 = 300

    assert real_input_sum == 13500, f"真 sum 应 13500, 得 {real_input_sum}"
    assert legacy_input == 4500, f"legacy 应 4500, 得 {legacy_input}"
    assert real_input_sum != legacy_input, "V0.33.1 修后 sum 必须 ≠ legacy"
    # output 同方向 (legacy 低估末次稳态)
    assert real_output_sum == 650
    assert legacy_output == 300


async def test_legacy_db_alter_compat(tmp_path):
    """V0.33.1: ALTER 兼容老 db (V0.33.0 之前 schema 缺 input_tokens/output_tokens 列).

    构造老 schema sqlite (无 token 列), init_db 应 ALTER 加列, write_step 不报错, COALESCE 返 0.
    """
    from web_agent.trace import Step, init_db, write_step

    db = tmp_path / "legacy.db"
    # 1. 手建老 schema (V0.33.0 前 8 列)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE steps (
            task_id TEXT NOT NULL, step INTEGER NOT NULL, ts REAL NOT NULL,
            thought TEXT, action_type TEXT, action_args TEXT,
            screenshot_path TEXT, observation TEXT,
            PRIMARY KEY (task_id, step)
        )
        """
    )
    conn.execute(
        "INSERT INTO steps VALUES (?,?,?,?,?,?,?,?)",
        ("legacy_task", 0, 1.0, "old thought", "click", "{}", "", "obs"),
    )
    conn.commit()
    conn.close()

    # 2. init_db 走 ALTER 路径 (sqlite3.OperationalError "duplicate column" 时 pass)
    conn = init_db(db)

    # 3. 老行 SELECT 各 token 列应 NULL → 应用层 COALESCE 0
    rows = conn.execute(
        "SELECT step, COALESCE(input_tokens, 0), COALESCE(output_tokens, 0) "
        "FROM steps WHERE task_id='legacy_task'"
    ).fetchall()
    assert rows == [(0, 0, 0)], f"老行 token 列应 NULL → COALESCE 0, 得 {rows}"

    # 4. write_step V0.33.1 新 INSERT 10 列也能写 (验 schema ALTER 已生效)
    s = Step(
        step=1, ts=2.0, thought="new", action_type="scroll",
        action_args={"dy": 100}, observation="new obs",
        input_tokens=8000, output_tokens=200,
    )
    write_step(conn, "legacy_task", s, "/tmp/shot.png")

    rows2 = conn.execute(
        "SELECT step, input_tokens, output_tokens FROM steps "
        "WHERE task_id='legacy_task' ORDER BY step"
    ).fetchall()
    conn.close()
    assert rows2 == [(0, 0, 0), (1, 8000, 200)], f"新 INSERT 落盘失败: {rows2}"


async def test_step_default_tokens_zero_when_no_last_usage(monkeypatch, tmp_path, patch_loop_internals):
    """V0.33.1: client.last_usage 不存在 (老 client / mock 无 usage 字段) → Step token 默 0, 不 raise."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    class FakeClientNoUsage:
        name = "no-usage"
        model = "fake"

        async def plan(self, *args, **kwargs):
            return DoneAction(thought="x", result="ok")
        # 故意不定义 last_usage 属性

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _FakeContext(), FakeClientNoUsage(), goal="测 client 无 last_usage",
        max_steps=2, db_path=db, screenshots_dir=shots,
    )
    assert result == "ok"
    rows = _read_step_tokens(db)
    assert len(rows) == 1
    assert rows[0] == (0, 0, 0), f"无 last_usage 时 token 应默 0, 得 {rows[0]}"


# ---------- V0.42.0 D 主题: cache hit-rate audit telemetry ----------


def _read_step_cache_tokens(db: Path) -> list[tuple[int, int, int, int, int]]:
    """V0.42.0: 读 trace.db steps 表 6 列 (step, input, output, cache_creation, cache_read)."""
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT step, input_tokens, output_tokens, "
        "cache_creation_input_tokens, cache_read_input_tokens FROM steps ORDER BY step"
    ).fetchall()
    conn.close()
    return rows


def test_v042_usage_dataclass_default_cache_fields_zero():
    """V0.42.0: Usage 加 cache_creation/read 字段 default 0, V0.33.1 _FakeUsage 不破."""
    from web_agent.types import Usage

    u = Usage(input_tokens=100, output_tokens=50)
    assert u.cache_creation_input_tokens == 0
    assert u.cache_read_input_tokens == 0

    # 显式 set 也 OK
    u2 = Usage(input_tokens=100, output_tokens=50,
               cache_creation_input_tokens=20, cache_read_input_tokens=80)
    assert u2.cache_creation_input_tokens == 20
    assert u2.cache_read_input_tokens == 80


async def test_v042_v033_fake_usage_still_works_regression(monkeypatch, tmp_path, patch_loop_internals):
    """V0.42.0: V0.33.1 _FakeUsage (2 字段) 跟 V0.42.0 loop.py 还兼容, 不破 833 现测."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    actions = [DoneAction(thought="x", result="ok")]
    usages = [_FakeUsage(input_tokens=5000, output_tokens=200)]  # V0.33.1 老 fake (无 cache 字段)
    client = FakeLLMClientWithUsage(actions, usages)

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _FakeContext(), client, goal="V0.42.0 regression",
        max_steps=2, db_path=db, screenshots_dir=shots,
    )
    assert result == "ok"
    rows = _read_step_cache_tokens(db)
    assert len(rows) == 1
    # V0.33.1 字段保留, V0.42.0 cache 字段 default 0 (老 fake 无 cache 字段, getattr default 0)
    assert rows[0] == (0, 5000, 200, 0, 0), f"V0.33.1 兼容失败: {rows[0]}"


@dataclass
class _FakeUsageV042:
    """V0.42.0: 扩 V0.33.1 _FakeUsage 加 cache 字段, 模 Anthropic V0.42.0 cache_creation/read."""
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class FakeLLMClientWithCacheUsage:
    """V0.42.0: 跟 V0.33.1 FakeLLMClientWithUsage 同, 但 last_usage 是 _FakeUsageV042 (4 字段)."""
    name = "fake-w-cache-usage"
    model = "fake"

    def __init__(self, actions: list, usages: list[_FakeUsageV042]) -> None:
        assert len(actions) == len(usages)
        self._actions = list(actions)
        self._usages = list(usages)
        self._i = 0
        self.last_usage: _FakeUsageV042 | None = None

    async def plan(self, goal, screenshot_b64, marks, trace, **kwargs):
        a = self._actions[self._i]
        self.last_usage = self._usages[self._i]
        self._i += 1
        return a


async def test_v042_per_step_cache_tokens_written(monkeypatch, tmp_path, patch_loop_internals):
    """V0.42.0 核心: 各 step plan() 后 last_usage 4 字段 → sqlite trace.db 真按 step 落盘.

    模 Anthropic cache 模式: step 0 cache_creation=10000 (首 write) / step 1 cache_read=10000
    (命中) / step 2 cache_read=10000 + creation=500 (mark 变 partial cache).
    """
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)

    actions = [
        ScrollAction(thought="x", dy=100),
        ScrollAction(thought="x", dy=200),
        DoneAction(thought="x", result="ok"),
    ]
    usages = [
        _FakeUsageV042(input_tokens=10000, output_tokens=300,
                       cache_creation_input_tokens=10000, cache_read_input_tokens=0),
        _FakeUsageV042(input_tokens=10000, output_tokens=250,
                       cache_creation_input_tokens=0, cache_read_input_tokens=10000),
        _FakeUsageV042(input_tokens=10500, output_tokens=100,
                       cache_creation_input_tokens=500, cache_read_input_tokens=10000),
    ]
    client = FakeLLMClientWithCacheUsage(actions, usages)

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _FakeContext(), client, goal="V0.42.0 cache audit",
        max_steps=3, db_path=db, screenshots_dir=shots,
    )
    assert result == "ok"
    rows = _read_step_cache_tokens(db)
    assert len(rows) == 3
    # (step, input, output, cache_creation, cache_read)
    expected = [
        (0, 10000, 300, 10000, 0),
        (1, 10000, 250, 0, 10000),
        (2, 10500, 100, 500, 10000),
    ]
    assert rows == expected, f"V0.42.0 cache 字段落盘失败: {rows} vs {expected}"


async def test_v042_2_token_budget_disabled_default(monkeypatch, tmp_path, patch_loop_internals):
    """V0.42.2: 默 WEB_AGENT_TOKEN_BUDGET_USD 未设 → token_budget_usd=0 disable, 不触发 abort."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    monkeypatch.delenv("WEB_AGENT_TOKEN_BUDGET_USD", raising=False)

    actions = [
        ScrollAction(thought="x", dy=100),
        DoneAction(thought="x", result="ok"),
    ]
    usages = [
        _FakeUsage(input_tokens=10_000_000, output_tokens=10_000_000),  # 巨大 cost ~$180
        _FakeUsage(input_tokens=100, output_tokens=50),
    ]
    client = FakeLLMClientWithUsage(actions, usages)

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _FakeContext(), client, goal="V0.42.2 disabled budget",
        max_steps=3, db_path=db, screenshots_dir=shots,
    )
    # 即使 step 0 cost 巨大, budget=0 disable → 走完 step 1 (Done) 不触发 abort
    assert result == "ok"


async def test_v042_2_token_budget_exceeded_aborts(monkeypatch, tmp_path, patch_loop_internals):
    """V0.42.2: budget=$0.05, step 0 cost ~$0.165 (10K input × 0.003 + 10K output × 0.015) 累超
    → step 1 顶 check 触发 TOKEN_BUDGET_EXCEEDED graceful abort."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    monkeypatch.setenv("WEB_AGENT_TOKEN_BUDGET_USD", "0.05")

    actions = [
        ScrollAction(thought="x", dy=100),
        ScrollAction(thought="x", dy=200),
        DoneAction(thought="x", result="ok-not-reached"),
    ]
    usages = [
        # step 0 真 cost = 10K × 0.003/1K + 10K × 0.015/1K = $0.03 + $0.15 = $0.18 > $0.05
        _FakeUsage(input_tokens=10_000, output_tokens=10_000),
        _FakeUsage(input_tokens=100, output_tokens=50),
        _FakeUsage(input_tokens=100, output_tokens=50),
    ]
    client = FakeLLMClientWithUsage(actions, usages)

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _FakeContext(), client, goal="V0.42.2 budget exceed",
        max_steps=5, db_path=db, screenshots_dir=shots,
    )
    # step 1 顶检测到累计 cost > budget → graceful abort
    assert "TOKEN_BUDGET_EXCEEDED" in result
    assert "$0.05" in result  # budget 数值进 result message
    # 验只跑到 step 0 (后续 step 不再调 plan)
    assert client._i == 1, f"V0.42.2 触发 abort 后不再调 plan: 真调 {client._i} 次"


async def test_v042_2_token_budget_invalid_env_fallback_zero(monkeypatch, tmp_path, patch_loop_internals):
    """V0.42.2: env 非数值 (e.g. 'abc') → fallback 0 disable, 不 raise."""
    monkeypatch.delenv("WEB_AGENT_AUTO_APPROVE", raising=False)
    monkeypatch.setenv("WEB_AGENT_TOKEN_BUDGET_USD", "abc-not-number")

    actions = [DoneAction(thought="x", result="ok")]
    usages = [_FakeUsage(input_tokens=100, output_tokens=50)]
    client = FakeLLMClientWithUsage(actions, usages)

    db = tmp_path / "trace.db"
    shots = tmp_path / "shots"
    result = await run_react_loop(
        _FakeContext(), client, goal="V0.42.2 invalid env",
        max_steps=2, db_path=db, screenshots_dir=shots,
    )
    # 非数值 env → fallback 0, 不 raise ValueError, 不触发 abort
    assert result == "ok"


async def test_v042_db_alter_compat_cache_columns(tmp_path):
    """V0.42.0: ALTER 兼容 V0.33.1 db (V0.42.0 之前 schema 缺 cache 列), COALESCE 0."""
    from web_agent.trace import Step, init_db, write_step

    db = tmp_path / "v033_legacy.db"
    # 1. 手建 V0.33.1 schema (含 input_tokens/output_tokens, 缺 cache 列)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE steps (
            task_id TEXT NOT NULL, step INTEGER NOT NULL, ts REAL NOT NULL,
            thought TEXT, action_type TEXT, action_args TEXT,
            screenshot_path TEXT, observation TEXT,
            input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
            PRIMARY KEY (task_id, step)
        )
        """
    )
    conn.execute(
        "INSERT INTO steps VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("v033_task", 0, 1.0, "thought", "click", "{}", "", "obs", 8000, 200),
    )
    conn.commit()
    conn.close()

    # 2. init_db ALTER 加 cache 2 列
    conn = init_db(db)

    # 3. 老行 cache 列 NULL → COALESCE 0
    rows = conn.execute(
        "SELECT step, COALESCE(cache_creation_input_tokens, 0), "
        "COALESCE(cache_read_input_tokens, 0) FROM steps WHERE task_id='v033_task'"
    ).fetchall()
    assert rows == [(0, 0, 0)], f"V0.33.1 老行 cache 列应 NULL → COALESCE 0: {rows}"

    # 4. V0.42.0 新 Step write (4 token 字段)
    s = Step(
        step=1, ts=2.0, thought="new", action_type="scroll",
        action_args={"dy": 100}, observation="new",
        input_tokens=12000, output_tokens=300,
        cache_creation_input_tokens=2000, cache_read_input_tokens=10000,
    )
    write_step(conn, "v033_task", s, "/tmp/shot.png")

    rows2 = conn.execute(
        "SELECT step, input_tokens, output_tokens, "
        "cache_creation_input_tokens, cache_read_input_tokens FROM steps "
        "WHERE task_id='v033_task' ORDER BY step"
    ).fetchall()
    conn.close()
    assert rows2 == [
        (0, 8000, 200, 0, 0),
        (1, 12000, 300, 2000, 10000),
    ], f"V0.42.0 新 INSERT 落盘失败: {rows2}"
