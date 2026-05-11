"""V0.29.1 W6-C chain runner 单测: run_chain async 编排 + 失败处理 + var 传递 + wallclock.

7 测覆盖 (subagent 推):
1. sequential 2-node 全 PASS + ${a.result} var 传递
2. 中节点 fail + on_failure=abort → 立即出 completed=False, 后续 node 不跑
3. 中节点 fail + on_failure=continue → prev_results 存 abort marker, 后续 node 跑
4. max_total_wallclock_s 累加超时 → 不跑剩 node, completed=False
5. ChainVarError reraise (节点 typo `${nope.result}`)
6. on_node_done_cb async 被调 (per-node)
7. chain_id 默 uuid 12 字符 hex / caller 传值时用 caller 值

mock RunTaskFn = `async def fake(*, goal, max_wallclock_s=None, **_)`. 不真 launch chromium.
"""

from __future__ import annotations

import asyncio

import pytest

from web_agent.chain import (
    ChainNode,
    ChainNodeResult,
    ChainResult,
    ChainSpec,
    ChainVarError,
    parse_chain_spec,
    run_chain,
)


# ---------- Test 1: sequential PASS + var 传递 ----------


async def test_run_chain_sequential_two_nodes_var_passing():
    """V0.29.1: 2 node 串行, node b goal 含 ${a.result} 拿到 a 的 result."""
    captured_goals: list[str] = []

    async def fake_run_task(*, goal: str, max_wallclock_s: float | None = None, **_: object) -> str:
        captured_goals.append(goal)
        if "node a" in goal:
            return "result_of_a"
        return "result_of_b"

    spec = parse_chain_spec({"nodes": [
        {"id": "a", "goal": "node a goal"},
        {"id": "b", "goal": "node b goal, prev was: ${a.result}", "depends_on": ["a"]},
    ]})

    result = await run_chain(spec, fake_run_task)

    assert isinstance(result, ChainResult)
    assert result.completed is True
    assert len(result.node_results) == 2
    assert result.node_results[0].node_id == "a"
    assert result.node_results[0].result == "result_of_a"
    assert result.node_results[0].success is True
    assert result.node_results[1].node_id == "b"
    assert result.node_results[1].success is True
    # var 真传递: b 的 goal 含 a 的 result
    assert "result_of_a" in captured_goals[1]


# ---------- Test 2: fail abort 中断 ----------


async def test_run_chain_node_fail_abort_stops_chain():
    """V0.29.1: 中 node fail + on_failure=abort → 立即出, 剩 node 不跑."""
    n_calls = 0

    async def fake_run_task(*, goal: str, max_wallclock_s: float | None = None, **_: object) -> str:
        nonlocal n_calls
        n_calls += 1
        if n_calls == 2:
            return "(max_steps 耗尽未完成)"  # is_success 判 fail
        return "ok"

    spec = parse_chain_spec({"nodes": [
        {"id": "a", "goal": "g"},
        {"id": "b", "goal": "g", "depends_on": ["a"]},  # 默 abort
        {"id": "c", "goal": "g", "depends_on": ["b"]},
    ]})

    result = await run_chain(spec, fake_run_task)

    assert result.completed is False
    assert len(result.node_results) == 2  # 只跑 a + b, c 不跑
    assert result.node_results[1].success is False
    assert n_calls == 2


# ---------- Test 3: fail continue 后续跑 ----------


async def test_run_chain_node_fail_continue_propagates_marker():
    """V0.29.1: 中 node fail + on_failure=continue → prev_results 存 abort marker, c 跑能拿到."""
    captured: dict[str, str] = {}

    async def fake_run_task(*, goal: str, max_wallclock_s: float | None = None, **_: object) -> str:
        captured["last_goal"] = goal
        if "node b" in goal:
            return "(max_steps 耗尽未完成)"  # b fail
        if "node c" in goal:
            return "ok_c"
        return "ok_a"

    spec = parse_chain_spec({"nodes": [
        {"id": "a", "goal": "node a"},
        {"id": "b", "goal": "node b", "on_failure": "continue"},
        {"id": "c", "goal": "node c, prev b: ${b.result}"},
    ]})

    result = await run_chain(spec, fake_run_task)

    assert result.completed is True  # 全跑完即 True (含 continue 失败)
    assert len(result.node_results) == 3
    assert result.node_results[1].success is False
    # c 的 goal 含 b 的 abort marker (continue 存原文 subagent F 决)
    assert "(max_steps 耗尽未完成)" in captured["last_goal"]


# ---------- Test 4: max_total_wallclock 中断 ----------


async def test_run_chain_max_total_wallclock_truncates_remaining_nodes():
    """V0.29.1: 第一 node 跑完 elapsed > max_total_wallclock → 第二 node 不跑."""
    async def slow_run_task(*, goal: str, max_wallclock_s: float | None = None, **_: object) -> str:
        await asyncio.sleep(0.15)  # 故意 sleep > max_total
        return "ok"

    spec = parse_chain_spec({"nodes": [
        {"id": "a", "goal": "g"},
        {"id": "b", "goal": "g", "depends_on": ["a"]},
    ]})

    result = await run_chain(spec, slow_run_task, max_total_wallclock_s=0.1)

    assert result.completed is False
    assert len(result.node_results) == 1  # 只 a 跑


# ---------- Test 5: ChainVarError reraise ----------


async def test_run_chain_var_error_reraises_for_spec_bug():
    """V0.29.1: spec 节点 b goal 引未知 ${nope.result} → reraise ChainVarError (subagent H 决, 不 graceful)."""
    async def fake_run_task(*, goal: str, max_wallclock_s: float | None = None, **_: object) -> str:
        return "ok"

    spec = ChainSpec(nodes=(
        ChainNode(id="a", goal="g"),
        ChainNode(id="b", goal="b refs ${nope.result}", depends_on=("a",)),
    ))

    with pytest.raises(ChainVarError, match="未知 node 'nope'"):
        await run_chain(spec, fake_run_task)


# ---------- Test 6: on_node_done_cb async 被调 ----------


async def test_run_chain_on_node_done_cb_invoked_per_node():
    """V0.29.1: on_node_done_cb async 被调每 node 一次, 拿到 ChainNodeResult."""
    cb_calls: list[ChainNodeResult] = []

    async def cb(nr: ChainNodeResult) -> None:
        cb_calls.append(nr)

    async def fake_run_task(*, goal: str, max_wallclock_s: float | None = None, **_: object) -> str:
        return "ok"

    spec = parse_chain_spec({"nodes": [
        {"id": "a", "goal": "g"},
        {"id": "b", "goal": "g", "depends_on": ["a"]},
    ]})

    await run_chain(spec, fake_run_task, on_node_done_cb=cb)

    assert len(cb_calls) == 2
    assert cb_calls[0].node_id == "a"
    assert cb_calls[1].node_id == "b"


# ---------- Test 7: chain_id 默 uuid / caller 传值 ----------


async def test_run_chain_chain_id_default_uuid_and_caller_override():
    async def fake(*, goal: str, max_wallclock_s: float | None = None, **_: object) -> str:
        return "ok"

    spec = parse_chain_spec({"nodes": [{"id": "a", "goal": "g"}]})

    # 默 uuid 12 字符 hex
    r1 = await run_chain(spec, fake)
    assert len(r1.chain_id) == 12
    assert all(c in "0123456789abcdef" for c in r1.chain_id)

    # caller 提供 chain_id 用 caller 值
    r2 = await run_chain(spec, fake, chain_id="custom-cid-123")
    assert r2.chain_id == "custom-cid-123"


# ---------- bonus: exception path graceful (asyncio.TimeoutError) ----------


async def test_run_chain_exception_in_run_task_caught_as_failed_node():
    """V0.29.1: run_task_fn 真 raise (e.g. Chrome connect fail) → 节点标 fail + result 含 EXCEPTION marker."""
    async def boom_run_task(*, goal: str, max_wallclock_s: float | None = None, **_: object) -> str:
        raise RuntimeError("chrome dead")

    spec = parse_chain_spec({"nodes": [{"id": "a", "goal": "g"}]})

    result = await run_chain(spec, boom_run_task)

    assert result.completed is False
    assert len(result.node_results) == 1
    assert result.node_results[0].success is False
    assert "CHAIN_NODE_EXCEPTION" in result.node_results[0].result
    assert "chrome dead" in result.node_results[0].result
