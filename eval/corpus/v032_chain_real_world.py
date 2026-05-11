"""V0.32.0 D' 真高级 task: chain × real-world 交叉 (V0.29 W6-C synthetic chain × V0.30 D real-world).

V0.29 W6-C synthetic chain (data:text/html DOM 接力) + V0.30 D real-world (单 task wikipedia/GitHub
真外网) 之上叠加 — 真外网多 page chain task (e.g. GitHub topic search → first repo README 提取).

V0.32 系列 4 commit (subagent 推):
- V0.32.0 (本): 1 chain real-world task + corpus init + 测
- V0.32.1: maintainer 真录 cassette + simplify
- V0.32.2: +1 chain real-world (Wikipedia cross-ref) 验非 GitHub 域
- V0.32.3: cli --corpus chain-real-world 复合 axis filter + 收尾

设计 (subagent A-F 6 决策全采纳):
- A GitHub topic search → first repo README (subagent 推 #1)
- B fixture github.com/topics/python + node a click first repo card / node b extract README description
- C vcr cassette wrap 整 run_one (V0.30.3 已覆 chain branch, ~150KB cassette OK)
- D flaky_repeat=1 (V0.30.3 chain × flaky 互斥 assert)
- E mock 模式 corpus loaded + slow opt-in real net 录 cassette
- F max_steps=12 / max_wallclock_s=180 留 buffer 防 GitHub UI banner/dynamic JS

注: predicate `SubstringPredicate("Python")` 而非 repo name (subagent B 决: GitHub topic 第一名
repo 月度漂, "Python" 任何 repo README/about 必含).
"""

from __future__ import annotations

from eval.predicates import Predicate, SubstringPredicate
from eval.types import EvalTask
from web_agent.chain import ChainNode, ChainSpec

GITHUB_TOPIC_PYTHON_FIRST_README = EvalTask(
    task_id="v032-github-topic-python-first-readme",
    goal=(
        "本 task 走 chain 路径 (V0.32 D' real-world chain × axis 交叉): "
        "node a 在 https://github.com/topics/python 点击排第一的 repository card 跳转到 repo 主页; "
        "node b 在跳转后 page 提取 README 描述/about section, done(result=完整描述)."
    ),
    fixture_url="https://github.com/topics/python",
    capability_axis="real-world",  # V0.30.2 D real-world axis (chain task 用 real-world axis 不破)
    expected_step_range=(4, 12),  # chain 2 node × 2-6 step (click + perceive + extract + done)
    max_steps=12,  # GitHub UI banner/dynamic JS 留 buffer (V0.30.4 octocat 同 risk)
    max_wallclock_s=180.0,  # chain 2 node × 90s wallclock cap
    description=(
        "V0.32.0 D' chain × real-world: GitHub topic search → first repo README 提取. "
        "predicate 'Python' (而非 repo name) 抗 GitHub topic 月度第一名 repo 漂. "
        "chain runner 跨 node 复用 ctx (V0.29.4 _run_chain_branch), node a click → 真 navigate → "
        "node b 在 navigate 后 page extract."
    ),
    tags=("v032", "d-prime", "chain", "real-world", "github"),
    requires_real_net=True,  # V0.30.1 LIVE_NET filter 默跳, EVAL_LIVE_NET=1 才放行
    flaky_repeat=1,  # V0.30.3 chain × flaky 互斥 assert (chain 内 node 自带 retry)
    chain_spec=ChainSpec(nodes=(
        ChainNode(
            id="a",
            goal=(
                "找页面顶部 'Repositories' 或 trending list 排第一的 repository card 链接 "
                "(usually <a href='/owner/repo' class='Link--muted'> 类), click 它跳转 repo 主页. "
                "click 后 done(result='clicked first repo')."
            ),
        ),
        ChainNode(
            id="b",
            goal=(
                "当前 page 是 GitHub repo 主页 (跳转后), 找 About section / repo description 文本 "
                "(usually 右栏 <p class='f4 my-3'>), done(result=完整 description 文本)."
            ),
            depends_on=("a",),
        ),
    )),
)

# subagent B: predicate 选 8+ char + 抗 GitHub topic 第一名 repo 月度漂.
# "programming language" 20 char — Python topic 任何 repo README/about 几乎必含
# (Python 是 programming language 是 universal description), 跟 wiki "phenomenon" 同抗漂逻辑.
CHAIN_REAL_WORLD_PREDICATES: dict[str, Predicate] = {
    GITHUB_TOPIC_PYTHON_FIRST_README.task_id: SubstringPredicate(substring="programming language"),
}
