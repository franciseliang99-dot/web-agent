"""V0.29.4 W6-C 收尾: chain corpus task — 跨 2 node DOM 接力验 eval --chain pipeline.

设计 (subagent E + B + G 决):
- fixture URL_CHAIN_REVEAL 单 page 含 placeholder H1 + reveal button
- chain spec 2 node:
  - a: click reveal button (页面 H1 替换为 TOKEN_CHAIN_FINAL_REVEAL)
  - b: extract H1 文本 (depends_on=[a], 此时 H1 已是 token)
- predicate substring 验末 node result 含 token

V0.29.4 scope: 1 chain task 起步 (W6-C pipeline 接通), V0.29.5 加 max_steps trigger task 主动验
reflection 跨 node 污染 (V0.29 系列最大未知).
"""

from __future__ import annotations

from eval.corpus._fixtures import TOKEN_CHAIN_FINAL_REVEAL, URL_CHAIN_REVEAL
from eval.predicates import Predicate, SubstringPredicate
from eval.types import EvalTask
from web_agent.chain import ChainNode, ChainSpec

CHAIN_REVEAL_2NODE = EvalTask(
    task_id="v029-chain-reveal-2node",
    goal=(
        "本 task 走 chain 路径 (V0.29 W6-C): chain spec 内 2 node — node a click reveal button, "
        "node b extract H1 文本. 末 node result 含 token 即 PASS."
    ),
    fixture_url=URL_CHAIN_REVEAL,
    capability_axis="baseline",  # V0.29 chain 暂用 baseline axis (V0.30 加 'task-chain' axis 统计)
    expected_step_range=(2, 6),  # node a 1-2 step click + node b 1-2 step extract
    max_steps=8,  # per-node, chain runner remaining 累加 cap = max_wallclock_s
    max_wallclock_s=90.0,  # chain 总 cap (2 node × 45s)
    description=(
        "V0.29.4 W6-C 收尾验证: 单 page 跨 2 node DOM 接力. fixture 起点 placeholder H1, "
        "node a click reveal 后 H1 变 token, node b extract."
    ),
    tags=("v029", "w6-c", "chain"),
    chain_spec=ChainSpec(nodes=(
        ChainNode(
            id="a",
            goal="找到页面上 'reveal answer button' 按钮并 click 它. click 后 done(result='clicked').",
        ),
        ChainNode(
            id="b",
            goal="读当前 page 的 H1 文本, done(result=完整 H1 字符串)",
            depends_on=("a",),
        ),
    )),
)

CHAIN_PREDICATES: dict[str, Predicate] = {
    CHAIN_REVEAL_2NODE.task_id: SubstringPredicate(substring=TOKEN_CHAIN_FINAL_REVEAL),
}
