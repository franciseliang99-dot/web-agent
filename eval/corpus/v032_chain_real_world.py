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


# V0.32.2 第 2 chain real-world task: Wikipedia cross-ref (验非 GitHub 域 + 跨 wiki 内链 navigation).
# fixture 复用 V0.30.4 WIKIPEDIA_APPLE_INC 同 URL (Apple_Inc page), 但 chain 跨 page (a click
# Cupertino link → 跳 Cupertino page → b extract on Cupertino page).
#
# subagent A 决: node a goal 必须明指"首段中文字为 'Cupertino' 的 wikilink" 防 LLM click 错
# (Apple_Inc 首段含多个 wikilink: Cupertino/California/Steve Jobs/Cook, 误点 California 跳错 page).
WIKIPEDIA_APPLE_TO_CUPERTINO_CHAIN = EvalTask(
    task_id="v032-wikipedia-apple-to-cupertino-chain",
    goal=(
        "本 task 走 chain 路径 (V0.32 D' real-world chain × axis 交叉, 非 GitHub 域验证): "
        "node a 在 https://en.wikipedia.org/wiki/Apple_Inc. 找首段中文字为 'Cupertino' 的"
        "wikilink (蓝色超链接), click 跳到 Cupertino wiki page; "
        "node b 在跳转后的 Cupertino page extract 首段含县名信息, done(result=完整首段)."
    ),
    fixture_url="https://en.wikipedia.org/wiki/Apple_Inc.",  # 复用 V0.30.4 fixture URL
    capability_axis="real-world",  # chain × real-world 双标 (跟 V0.32.0 GitHub task 同 axis)
    expected_step_range=(3, 10),  # chain 2 node × 2-5 step (find link + click + perceive + extract)
    max_steps=10,  # wiki 比 GitHub 轻 (无 banner/JS), 比 V0.32.0 的 12 少 2 合理
    max_wallclock_s=120.0,  # wiki 静态 HTML 120s 比 V0.32.0 的 180 少 60 合理
    description=(
        "V0.32.2 D' chain × real-world (非 GitHub 域): Wikipedia cross-ref Apple_Inc → Cupertino "
        "via 首段 wikilink. predicate 'Santa Clara County' 18 char 抗 wiki city page 行政信息漂 "
        "(county 归属 5+ 年不变, 比 'California' 通用度低不假阳性)."
    ),
    tags=("v032", "d-prime", "chain", "real-world", "wikipedia"),
    requires_real_net=True,
    flaky_repeat=1,
    chain_spec=ChainSpec(nodes=(
        ChainNode(
            id="a",
            goal=(
                "在 Apple_Inc 页面首段 (lead paragraph) 中找文字为 'Cupertino' 的 wikilink "
                "(蓝色超链接, 通常出现在 'headquartered in Cupertino' 类句子里), click 它. "
                "**注意区分**: 不要点 'California' 或其他 wikilink, 必须文字为 'Cupertino'. "
                "click 后 done(result='clicked Cupertino link')."
            ),
        ),
        ChainNode(
            id="b",
            goal=(
                "当前 page 是 Cupertino wiki (跳转后), extract 首段内容含县名/州名行政信息, "
                "done(result=完整首段文本)."
            ),
            depends_on=("a",),
        ),
    )),
)
CHAIN_REAL_WORLD_PREDICATES[WIKIPEDIA_APPLE_TO_CUPERTINO_CHAIN.task_id] = SubstringPredicate(
    substring="Santa Clara County",
)
