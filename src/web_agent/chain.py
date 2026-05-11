"""V0.29.0: W6-C 长 task chain 编排器开篇 — 纯函数 + spec 校验, 不接 cli/loop/mcp/eval.

W6-C 设计意图: 多 task DAG 编排器 + 中间失败时 reflect → 调下一 task plan + 跨 task 数据流.
跟 V0.28 W6-A/B (cross-task memory inject) 是不同抽象层 (W6-A/B 是 memory 层, W6-C 是 plan 层).

V0.29 系列 commit 拆解 (Plan subagent 推, 5 commit):
- V0.29.0 (本): chain.py 纯函数 + 校验 (ChainNode/ChainSpec dataclass + parse + topo_order + var subst)
- V0.29.1: chain runner async run_chain + cli wire `web-agent-chain` console_script
- V0.29.2: mcp tool `web_agent_run_chain` (接 spec dict inline, 跨进程不共享文件系统)
- V0.29.3: eval --chain 集成 + 2-3 chain corpus task + chain_completion_rate metric
- V0.29.4: simplify subagent 审 + uv.lock chore

V0.29 关键决策 (Plan subagent 全采纳):
- spec 格式: Python list[ChainNode] dataclass (mypy strict 友好) + V0.29.1 加 yaml loader (caller 调 yaml.safe_load 传 dict)
- 数据流: simple `${node_id.result}` substitution (拒 structured pipeline / LLM 自决, V0.21.2 Protocol 模式)
- 失败处理: 默 `continue` + 复用 V0.28.1+V0.28.2 reflect 自动桥接 (per-node on_failure=abort|continue)
- DAG 复杂度: V0.29 限 linear (序列, topo sort 后 sequential emit), V0.30 加分支并发
- spec 来源: 仅用户写 YAML / mcp client 传 dict, V0.29 不做 LLM 自动拆 chain (Auto-GPT V0.31+)
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Protocol, runtime_checkable

from web_agent.memory import is_success


class ChainSpecError(ValueError):
    """V0.29.0: spec 结构异常 (缺字段 / 重复 id / 未知 dep id)."""


class ChainCycleError(ValueError):
    """V0.29.0: depends_on 形成环 (Kahn 算法 detect)."""


class ChainVarError(ValueError):
    """V0.29.0: substitute_vars 引用未知 node id (caller goal 写 `${typo.result}`)."""


@dataclass(frozen=True, slots=True)
class ChainNode:
    """V0.29.0: chain 单节点 spec (跟 web_agent.types.Action / Mark / Usage 同 frozen+slots 模式).

    fields:
        id: 节点唯一 id (chain 内 unique). substitute_vars `${id.result}` 引用此 id.
        goal: 该节点 task goal (可含 ${prev_id.result} 模板, build_node_goal 时 substitute).
        depends_on: 依赖节点 id tuple (V0.29 限 linear 但建图 V0.30 真 DAG 复用).
        on_failure: "abort" 整 chain 终止 / "continue" 跳过此节点继续下一. 默 "abort".
        inputs: V0.30 预留 (declarative input mapping), V0.29 不消费仅占位 schema.
    """

    id: str
    goal: str
    depends_on: tuple[str, ...] = ()
    on_failure: Literal["abort", "continue"] = "abort"
    inputs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChainSpec:
    """V0.29.0: chain 完整 spec (nodes tuple). 不带 metadata / version (V0.30 视需求加)."""

    nodes: tuple[ChainNode, ...]


def parse_chain_spec(data: dict[str, Any]) -> ChainSpec:
    """V0.29.0: dict → ChainSpec, 校验结构 + 重复 id + 未知 dep id (subagent 决: V0.29.0 只接 dict).

    V0.29.1 caller 在 cli/mcp 层调 yaml.safe_load(yaml_str) 后传 dict, 让 chain.py 不引 yaml dep
    (mypy strict 友好). mcp tool web_agent_run_chain 也接 spec dict inline.

    expected dict shape:
        {"nodes": [{"id": str, "goal": str, "depends_on": [str,...]?, "on_failure": str?, "inputs": dict?}, ...]}

    Raises:
        ChainSpecError: 缺 nodes / id 重复 / on_failure 非法 / depends_on 引未知 id
    """
    if not isinstance(data, dict):
        raise ChainSpecError(f"spec 必须 dict, got {type(data).__name__}")
    nodes_raw = data.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise ChainSpecError("spec 必须含非空 'nodes' list")
    nodes: list[ChainNode] = []
    seen_ids: set[str] = set()
    for i, n in enumerate(nodes_raw):
        if not isinstance(n, dict):
            raise ChainSpecError(f"node[{i}] 必须 dict, got {type(n).__name__}")
        node_id = n.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise ChainSpecError(f"node[{i}] 缺 id 或非 str")
        if node_id in seen_ids:
            raise ChainSpecError(f"node id {node_id!r} 重复 (chain 内 id 必须 unique)")
        seen_ids.add(node_id)
        goal = n.get("goal")
        if not isinstance(goal, str):
            raise ChainSpecError(f"node {node_id!r} 缺 goal 或非 str")
        deps_raw = n.get("depends_on", [])
        if not isinstance(deps_raw, list) or not all(isinstance(d, str) for d in deps_raw):
            raise ChainSpecError(f"node {node_id!r} depends_on 必须 list[str]")
        on_failure = n.get("on_failure", "abort")
        if on_failure not in ("abort", "continue"):
            raise ChainSpecError(
                f"node {node_id!r} on_failure 必须 'abort'|'continue', got {on_failure!r}"
            )
        inputs_raw = n.get("inputs", {})
        if not isinstance(inputs_raw, dict):
            raise ChainSpecError(f"node {node_id!r} inputs 必须 dict")
        nodes.append(ChainNode(
            id=node_id, goal=goal,
            depends_on=tuple(deps_raw),
            on_failure=on_failure,
            inputs=dict(inputs_raw),
        ))
    # 二次扫: 校验 depends_on 都引已声明 id
    all_ids = {n.id for n in nodes}
    for n in nodes:
        for dep in n.depends_on:
            if dep not in all_ids:
                raise ChainSpecError(
                    f"node {n.id!r} depends_on 引未知 id {dep!r} (已声明: {sorted(all_ids)})"
                )
    return ChainSpec(nodes=tuple(nodes))


def topological_order(spec: ChainSpec) -> list[ChainNode]:
    """V0.29.0: Kahn 算法 topo sort, 检环抛 ChainCycleError. V0.29 仍 linear emit (subagent D 决).

    V0.30 真 DAG 并发 emit 复用此函数 (返 list 仍是 partial order, caller 决并发策略).
    """
    by_id = {n.id: n for n in spec.nodes}
    in_degree: dict[str, int] = defaultdict(int)
    out_edges: dict[str, list[str]] = defaultdict(list)
    for n in spec.nodes:
        in_degree[n.id]  # ensure key exists
        for dep in n.depends_on:
            in_degree[n.id] += 1
            out_edges[dep].append(n.id)

    queue: deque[str] = deque(nid for nid in (n.id for n in spec.nodes) if in_degree[nid] == 0)
    ordered: list[ChainNode] = []
    while queue:
        nid = queue.popleft()
        ordered.append(by_id[nid])
        for child in out_edges[nid]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(ordered) < len(spec.nodes):
        unresolved = sorted(n.id for n in spec.nodes if n.id not in {x.id for x in ordered})
        raise ChainCycleError(
            f"chain 含环 / 未解依赖 (Kahn 终止时剩 {len(spec.nodes) - len(ordered)} node 未排, "
            f"涉及 id: {unresolved})"
        )
    return ordered


# substitute_vars: 匹配 `${node_id.result}` 模板, node_id 仅允许 [\w-] 防 injection.
_VAR_PATTERN = re.compile(r"\$\{([\w-]+)\.result\}")


def substitute_vars(template: str, results: dict[str, str]) -> str:
    """V0.29.0: `${node_id.result}` → results[node_id]. miss key 抛 ChainVarError.

    Subagent 决: V0.29 限 `.result` suffix (DoneAction.result str), V0.30 加 `.steps` / `.usage`
    等多字段时扩 pattern. node_id pattern [\\w-] 防特殊字符 injection.
    """
    def _sub(m: re.Match[str]) -> str:
        node_id = m.group(1)
        if node_id not in results:
            raise ChainVarError(
                f"substitute_vars 引未知 node {node_id!r} "
                f"(已知 results: {sorted(results.keys())})"
            )
        return results[node_id]
    return _VAR_PATTERN.sub(_sub, template)


def build_node_goal(node: ChainNode, prev_results: dict[str, str]) -> str:
    """V0.29.0: 构造单 node 真 goal — substitute_vars(node.goal, prev_results).

    caller 跑完 prev node 后把 final result 存进 prev_results dict (key=node.id), 调本函数
    拼最终下传 run_react_loop 的 goal string.
    """
    return substitute_vars(node.goal, prev_results)


@runtime_checkable
class RunTaskFn(Protocol):
    """V0.29.1: chain runner DI 接口 — async run_task callable, 防 chain.py 直 import cli.run_task 循环.

    cli.chain_main 用 closure 包 cli.run_task 把 cdp_url/provider/model 等 chain-level args bind 进去,
    chain runner 只需传 goal + max_wallclock_s. **kwargs 兜底防 V0.30 加 reset_session 等参数破签名.

    跟 V0.21.2 LLMClient Protocol + V0.27.1 SecretStore Protocol 同 @runtime_checkable 模式.
    """

    async def __call__(
        self, *, goal: str, max_wallclock_s: float | None = None, **kwargs: Any,
    ) -> str: ...


# on_node_done callback type alias (chain runner 调, async 让 cb 能 awaitable)
OnNodeDoneCb = Callable[["ChainNodeResult"], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ChainNodeResult:
    """V0.29.1: chain 单 node 跑完结果. web_agent_task_id V0.29.1 留 None (loop task_id 没暴露
    return path, V0.29.2/3 加 trace.db schema chain_id migration 时填; 字段先占位避后续 schema 改).
    """

    node_id: str
    result: str
    success: bool
    wallclock_s: float
    web_agent_task_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChainResult:
    """V0.29.1: chain 跑完总结果. completed=True iff 全 node success 或 全 abort 完整跑完
    (含 on_failure=continue 链尾); False iff 中途 abort / wallclock 超时中断."""

    chain_id: str
    started_at: float
    ended_at: float
    node_results: tuple[ChainNodeResult, ...]
    completed: bool


async def run_chain(
    spec: ChainSpec,
    run_task_fn: RunTaskFn,
    *,
    on_node_done_cb: OnNodeDoneCb | None = None,
    max_total_wallclock_s: float = 1800.0,
    chain_id: str | None = None,
) -> ChainResult:
    """V0.29.1 W6-C 编排器: topo 序逐 node 跑 + 失败处理 + 跨 node var 传递 + 总 wallclock cap.

    Args:
        spec: V0.29.0 parse_chain_spec 输出
        run_task_fn: DI Protocol — caller (cli.chain_main / mcp web_agent_run_chain) 用 closure
            包 cli.run_task 把 cdp/provider/model bind 进, chain 只传 goal + max_wallclock_s
        on_node_done_cb: per-node 完成 cb (cli/mcp 用来 progress 输出)
        max_total_wallclock_s: chain 整体 wallclock cap (默 1800s = 30min, 防 chain 跑天)
        chain_id: 默 uuid.uuid4().hex[:12]; caller 提供时用 (V0.30 spec-hash 关联多 run 用)

    Returns:
        ChainResult — completed=True iff 完整跑完 (含 continue 失败的链尾); False iff abort/wallclock

    Raises:
        ChainCycleError: spec 含环 (Kahn detect)
        ChainVarError: build_node_goal 引未知 node id (spec 设计 bug, 跑前 reraise 不污染半截 result)

    Chrome session: chain runner 不持 ctx/page (DI run_task_fn 是黑盒, run_task 内自己开关
    cdp 连接). 跨 node session 复用是 cdp 9222 持久 Chrome 的天然行为, V0.29.1 不加 reset_session
    字段 (V0.30 真实施时要决 cookies/localStorage/SW 谁清).
    """
    cid = chain_id or uuid.uuid4().hex[:12]
    ordered = topological_order(spec)
    prev_results: dict[str, str] = {}
    node_results: list[ChainNodeResult] = []
    chain_started_at = time.time()
    t0 = time.monotonic()

    for node in ordered:
        elapsed = time.monotonic() - t0
        remaining = max_total_wallclock_s - elapsed
        if remaining <= 0:
            # chain wallclock 耗尽, 不跑剩 node, completed=False
            return ChainResult(
                chain_id=cid, started_at=chain_started_at, ended_at=time.time(),
                node_results=tuple(node_results), completed=False,
            )

        # build_node_goal 抛 ChainVarError 让 caller 知 spec bug, 不 graceful (subagent 决 H)
        goal = build_node_goal(node, prev_results)

        node_t0 = time.monotonic()
        try:
            # asyncio.wait_for +5s 边界冗余防 run_task 内部 graceful return 也卡;
            # 内 run_task 路径会先 return WALLCLOCK_EXCEEDED 字符串 (loop.py:475)
            result = await asyncio.wait_for(
                run_task_fn(goal=goal, max_wallclock_s=remaining),
                timeout=remaining + 5.0,
            )
            success = is_success(result)
        except Exception as e:
            # run_task 已 catch LLM/wallclock/loop 6 marker 走 graceful return,
            # 真 raise 是 connect/Chrome 启动级别 / asyncio.TimeoutError
            result = f"CHAIN_NODE_EXCEPTION: {type(e).__name__}: {e}"
            success = False

        node_wallclock = time.monotonic() - node_t0
        node_result = ChainNodeResult(
            node_id=node.id, result=result, success=success, wallclock_s=node_wallclock,
        )
        node_results.append(node_result)
        if on_node_done_cb is not None:
            await on_node_done_cb(node_result)

        # subagent 决 F: continue 时存 abort marker 原文让下个 node prompt 含失败 hint;
        # success 总存; abort 立即出 (completed=False)
        if success:
            prev_results[node.id] = result
        elif node.on_failure == "continue":
            prev_results[node.id] = result
        else:  # abort
            return ChainResult(
                chain_id=cid, started_at=chain_started_at, ended_at=time.time(),
                node_results=tuple(node_results), completed=False,
            )

    return ChainResult(
        chain_id=cid, started_at=chain_started_at, ended_at=time.time(),
        node_results=tuple(node_results), completed=True,
    )


__all__ = [
    "ChainCycleError",
    "ChainNode",
    "ChainNodeResult",
    "ChainResult",
    "ChainSpec",
    "ChainSpecError",
    "ChainVarError",
    "OnNodeDoneCb",
    "RunTaskFn",
    "build_node_goal",
    "parse_chain_spec",
    "run_chain",
    "substitute_vars",
    "topological_order",
]
