"""V0.30.2 D real-world corpus: 真外网 task — wikipedia static page 提取.

设计 (subagent V0.30.2 plan E + C 决):
- fixture URL: https://en.wikipedia.org/wiki/Quantum_entanglement (subagent V0.30 推 stable static)
- predicate: SubstringPredicate("phenomenon") — 核心定义术语, 漂移概率 < 月度
- requires_real_net=True (V0.30.1 字段) → cli LIVE_NET filter 默跳, EVAL_LIVE_NET=1 才放行
- flaky_repeat=3 真外网 wallclock 不稳, median pass (V0.30.1 框架)
- max_wallclock_s=120s, max_steps=8

V0.30.2 scope (subagent 决, 简化):
- 1 wikipedia task 起步 (V0.30.3 加 +2 wiki + GitHub README)
- run_one 真接 vcr.use_cassette 推 V0.30.3+ (vcrpy 8.x httpx 兼容研究, V0.26.x silent bug #11 deferred)
- sannysoft probe (G 真生效验) 在 tests/test_stealth_probe_sannysoft.py slow opt-in
"""

from __future__ import annotations

from eval.predicates import Predicate, SubstringPredicate
from eval.types import EvalTask

# subagent C: predicate 选 "phenomenon" 单词 (wikipedia 改首段时核心术语漂移概率最低)
# wiki 首段 "Quantum entanglement is the phenomenon..." 已稳 5+ 年, 即使改主语也常保留 "phenomenon"
WIKIPEDIA_QUANTUM_FIRST_PARA = EvalTask(
    task_id="v030-wikipedia-quantum-entanglement",
    goal=(
        "去 https://en.wikipedia.org/wiki/Quantum_entanglement 页面, "
        "提取首段 (lead paragraph) 第一句, done(result=完整一句)."
    ),
    fixture_url="https://en.wikipedia.org/wiki/Quantum_entanglement",
    capability_axis="real-world",  # V0.26.0 CapabilityAxis 占位, V0.30.2 首次落实
    expected_step_range=(2, 6),  # navigate + perceive + extract + done
    max_steps=8,
    max_wallclock_s=120.0,  # wiki load + LLM 双链路 (V0.30 plan #4 隐藏风险 wallclock 不稳)
    description=(
        "V0.30.2 D real-world 起步 task: wikipedia 静态 page 首段提取. requires_real_net=True 默跳, "
        "EVAL_LIVE_NET=1 + EVAL_REAL=1 真录 cassette. flaky_repeat=3 应对网络 flake."
    ),
    tags=("v030", "d-real-world", "wikipedia"),
    requires_real_net=True,  # V0.30.1 字段, cli LIVE_NET filter 默跳
    flaky_repeat=3,  # V0.30.1 字段, 真外网 wallclock 不稳 median pass
)

REAL_WORLD_PREDICATES: dict[str, Predicate] = {
    WIKIPEDIA_QUANTUM_FIRST_PARA.task_id: SubstringPredicate(substring="phenomenon"),
}


# V0.30.4 D real-world: 第 2 wikipedia (公司 page 跨 academic page baseline) — Apple_Inc.
# predicate "Cupertino" 总部地名 5+ 年稳, 编辑改总部概率 < 月度 (subagent A 决).
WIKIPEDIA_APPLE_INC = EvalTask(
    task_id="v030-wikipedia-apple-inc",
    goal=(
        "去 https://en.wikipedia.org/wiki/Apple_Inc. 页面, 提取首段含总部所在地的句子, "
        "done(result=完整句子)."
    ),
    fixture_url="https://en.wikipedia.org/wiki/Apple_Inc.",
    capability_axis="real-world",
    expected_step_range=(2, 6),
    max_steps=8,
    max_wallclock_s=120.0,
    description=(
        "V0.30.4 D real-world: 第 2 wikipedia (公司 page 跨 V0.30.2 academic page baseline). "
        "predicate Cupertino 总部地名 5+ 年稳."
    ),
    tags=("v030", "d-real-world", "wikipedia"),
    requires_real_net=True,
    flaky_repeat=3,
)
REAL_WORLD_PREDICATES[WIKIPEDIA_APPLE_INC.task_id] = SubstringPredicate(substring="Cupertino")


# V0.30.4 D real-world: GitHub octocat repo (web UI 含 description, SoM-friendly).
# predicate "My first repository" octocat 招牌账户 description 永不会改 (不像普通 repo, subagent B 决).
# max_steps=10 + max_wallclock_s=180 因 GitHub web UI 比 wiki 重 (JS bundle + login banner).
GITHUB_OCTOCAT_README = EvalTask(
    task_id="v030-github-octocat-hello-world",
    goal=(
        "去 https://github.com/octocat/Hello-World 页面, 找到 repository description 文本 "
        "(About section / 右栏), done(result=完整 description 文本)."
    ),
    fixture_url="https://github.com/octocat/Hello-World",
    capability_axis="real-world",
    expected_step_range=(3, 8),
    max_steps=10,  # GitHub web UI 重 (JS + banner) 留 buffer 防 LLM 多探一步
    max_wallclock_s=180.0,
    description=(
        "V0.30.4 D real-world: GitHub web UI description 提取. predicate 'My first repository' "
        "octocat 招牌账户描述永稳, 不像普通 repo description 漂移."
    ),
    tags=("v030", "d-real-world", "github"),
    requires_real_net=True,
    flaky_repeat=3,
)
REAL_WORLD_PREDICATES[GITHUB_OCTOCAT_README.task_id] = SubstringPredicate(
    substring="My first repository",
)
