"""V0.29.0 W6-C chain 单测: parse_chain_spec + topological_order + substitute_vars + build_node_goal.

13 测覆盖 (subagent 推):
- parse_chain_spec: minimal 1 node / 多 node + depends_on / 重复 id / 未知 dep / 缺 goal /
  on_failure 非法 / inputs 非 dict
- topological_order: linear / diamond / cycle 抛 / disconnected 多 root
- substitute_vars: single / multi / no var / missing key 抛
- build_node_goal: no vars / with prev result
- ChainNode/ChainSpec frozen 守护
"""

from __future__ import annotations

import pytest

from web_agent.chain import (
    ChainCycleError,
    ChainNode,
    ChainSpec,
    ChainSpecError,
    ChainVarError,
    build_node_goal,
    parse_chain_spec,
    substitute_vars,
    topological_order,
)


# ---------- parse_chain_spec ----------


def test_parse_chain_spec_minimal_one_node():
    spec = parse_chain_spec({"nodes": [{"id": "a", "goal": "g1"}]})
    assert isinstance(spec, ChainSpec)
    assert len(spec.nodes) == 1
    n = spec.nodes[0]
    assert n.id == "a"
    assert n.goal == "g1"
    assert n.depends_on == ()
    assert n.on_failure == "abort"  # 默
    assert n.inputs == {}


def test_parse_chain_spec_with_dependencies():
    spec = parse_chain_spec({"nodes": [
        {"id": "a", "goal": "g1"},
        {"id": "b", "goal": "g2", "depends_on": ["a"], "on_failure": "continue"},
    ]})
    assert len(spec.nodes) == 2
    assert spec.nodes[1].depends_on == ("a",)
    assert spec.nodes[1].on_failure == "continue"


def test_parse_chain_spec_missing_nodes_raises():
    with pytest.raises(ChainSpecError, match="非空 'nodes'"):
        parse_chain_spec({})


def test_parse_chain_spec_duplicate_id_raises():
    with pytest.raises(ChainSpecError, match="重复"):
        parse_chain_spec({"nodes": [
            {"id": "a", "goal": "g1"},
            {"id": "a", "goal": "g2"},
        ]})


def test_parse_chain_spec_unknown_dep_raises():
    with pytest.raises(ChainSpecError, match="depends_on 引未知 id"):
        parse_chain_spec({"nodes": [
            {"id": "a", "goal": "g1", "depends_on": ["nonexistent"]},
        ]})


def test_parse_chain_spec_missing_goal_raises():
    with pytest.raises(ChainSpecError, match="缺 goal"):
        parse_chain_spec({"nodes": [{"id": "a"}]})


def test_parse_chain_spec_invalid_on_failure_raises():
    with pytest.raises(ChainSpecError, match="on_failure 必须"):
        parse_chain_spec({"nodes": [
            {"id": "a", "goal": "g", "on_failure": "retry_3x"},
        ]})


def test_parse_chain_spec_inputs_must_be_dict():
    with pytest.raises(ChainSpecError, match="inputs 必须 dict"):
        parse_chain_spec({"nodes": [
            {"id": "a", "goal": "g", "inputs": ["not", "a", "dict"]},
        ]})


def test_parse_chain_spec_non_dict_input_raises():
    with pytest.raises(ChainSpecError, match="必须 dict"):
        parse_chain_spec("not a dict")  # type: ignore[arg-type]


# ---------- topological_order ----------


def test_topological_order_linear():
    spec = parse_chain_spec({"nodes": [
        {"id": "a", "goal": "g1"},
        {"id": "b", "goal": "g2", "depends_on": ["a"]},
        {"id": "c", "goal": "g3", "depends_on": ["b"]},
    ]})
    ordered = topological_order(spec)
    assert [n.id for n in ordered] == ["a", "b", "c"]


def test_topological_order_diamond():
    """V0.29.0: a → b, c → d (b/c 都依赖 a, d 依赖 b/c). topo 序 a 在前 d 在后."""
    spec = parse_chain_spec({"nodes": [
        {"id": "a", "goal": "g"},
        {"id": "b", "goal": "g", "depends_on": ["a"]},
        {"id": "c", "goal": "g", "depends_on": ["a"]},
        {"id": "d", "goal": "g", "depends_on": ["b", "c"]},
    ]})
    ordered = topological_order(spec)
    ids = [n.id for n in ordered]
    assert ids[0] == "a"
    assert ids[-1] == "d"
    assert set(ids[1:3]) == {"b", "c"}


def test_topological_order_cycle_raises():
    """V0.29.0: a → b → a 环, Kahn 算法剩节点未排 → ChainCycleError."""
    # parse 不查环 (只查 unknown dep), topo 才查
    spec = ChainSpec(nodes=(
        ChainNode(id="a", goal="g", depends_on=("b",)),
        ChainNode(id="b", goal="g", depends_on=("a",)),
    ))
    with pytest.raises(ChainCycleError, match="含环"):
        topological_order(spec)


def test_topological_order_disconnected_multi_root():
    """V0.29.0: 两条独立链 (a→b, c→d), 4 个 node 都 emit 不抛环."""
    spec = parse_chain_spec({"nodes": [
        {"id": "a", "goal": "g"},
        {"id": "b", "goal": "g", "depends_on": ["a"]},
        {"id": "c", "goal": "g"},
        {"id": "d", "goal": "g", "depends_on": ["c"]},
    ]})
    ordered = topological_order(spec)
    assert len(ordered) == 4


# ---------- substitute_vars ----------


def test_substitute_vars_single():
    out = substitute_vars("hello ${a.result} world", {"a": "WORLD"})
    assert out == "hello WORLD world"


def test_substitute_vars_multi():
    out = substitute_vars("${a.result} + ${b.result} = ${c.result}",
                          {"a": "1", "b": "2", "c": "3"})
    assert out == "1 + 2 = 3"


def test_substitute_vars_no_var_template():
    out = substitute_vars("plain string no var", {"a": "X"})
    assert out == "plain string no var"


def test_substitute_vars_missing_key_raises():
    with pytest.raises(ChainVarError, match="未知 node 'typo'"):
        substitute_vars("hello ${typo.result}", {"a": "X"})


def test_substitute_vars_node_id_alphanumeric_dashes():
    """V0.29.0: pattern 允 [\\w-] (字母/数字/下划线/dash), 不允特殊字符防 injection."""
    out = substitute_vars("${node-1.result}", {"node-1": "X"})
    assert out == "X"


# ---------- build_node_goal ----------


def test_build_node_goal_no_vars():
    n = ChainNode(id="a", goal="去网站搜苹果价格")
    assert build_node_goal(n, {}) == "去网站搜苹果价格"


def test_build_node_goal_with_prev_result():
    n = ChainNode(id="b", goal="对比 ${a.result} 和当前价格")
    assert build_node_goal(n, {"a": "iPhone 15 价格"}) == "对比 iPhone 15 价格 和当前价格"


# ---------- ChainNode / ChainSpec frozen 守护 ----------


def test_chain_node_is_frozen():
    n = ChainNode(id="a", goal="g")
    with pytest.raises(Exception):  # FrozenInstanceError
        n.goal = "changed"  # type: ignore[misc]


def test_chain_spec_is_frozen():
    s = ChainSpec(nodes=())
    with pytest.raises(Exception):
        s.nodes = (ChainNode(id="x", goal="g"),)  # type: ignore[misc]
