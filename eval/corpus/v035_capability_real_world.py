"""V0.35.0 A 真站点 eval 双轴扩开篇 1/N: capability axis × real-world 交叉.

V0.26 eval framework 现有 capability axis (multi-tab/iframe/drag/upload/download/dialog/...) 全是
synthetic data:text/html fixture; V0.30 real-world axis 3 task 全 perceiver 静态 first-page extract;
V0.32 chain × real-world 双轴 2 task 也是静态 perceiver. **没 task 覆盖 actuator 真站点动作轴**
(type / click / scroll 真站点交互).

V0.35.0 开篇加 1 task: wikipedia 搜索框 actuator type + 提交搜索 + 落地页 extract. 走 actuator
真站点轴, 跟 V0.30 静态 extract 区分.

micro experiment 验证 (V0.34 教训):
- `curl https://en.wikipedia.org/wiki/Main_Page | grep 'id="searchInput"'` → 搜索框 input 存在
- `curl https://en.wikipedia.org/wiki/Quantum_field_theory | grep "Quantum field theory is"` → 首段稳

V0.35 系列 plan:
- V0.35.0 1 task actuator search + extract (本 commit)
- V0.35.1 deferred maintainer 真录 cassette (autonomous 红线 — 需 ANTHROPIC_API_KEY + 真烧 token)
- V0.35.2 +2 task (其他 actuator 真站点轴: scroll-pagination / multi-step click)
- V0.35.3 系列收尾 retrospective + virtual axis filter
"""

from __future__ import annotations

from eval.predicates import Predicate, SubstringPredicate
from eval.types import EvalTask

# V0.35.0: wikipedia 搜索 actuator 真站点轴.
# fixture 起点 = Main_Page (含 <input id="searchInput" name="search">), agent type "quantum field
# theory" 后提交 (Enter 或 click search 按钮), 落地 Quantum_field_theory article, extract 首段第一句.
# predicate "Quantum field theory" — 标题词必出现首段 (5+ 年稳, 即使页面改写仍含整名).
WIKIPEDIA_SEARCH_QUANTUM_FIELD_THEORY = EvalTask(
    task_id="v035-wikipedia-search-quantum-field-theory",
    goal=(
        "去 https://en.wikipedia.org/wiki/Main_Page 页面, 在搜索框输入 'quantum field theory' 并"
        "提交搜索 (按 Enter 或点搜索按钮), 在落地的 article 页 extract 首段第一句, "
        "done(result=完整一句)."
    ),
    fixture_url="https://en.wikipedia.org/wiki/Main_Page",
    capability_axis="real-world",
    expected_step_range=(3, 8),  # navigate → type → submit → wait nav → perceive → extract → done
    max_steps=12,  # 真站点 LLM 可能多探 (autocomplete dropdown / re-perceive)
    max_wallclock_s=120.0,
    description=(
        "V0.35.0 A 双轴扩开篇: wikipedia 搜索 actuator type + click 真站点轴 (V0.30 全 perceiver "
        "静态 extract, V0.35 加 actuator 动作真站点). predicate 'Quantum field theory' 标题词 "
        "5+ 年稳."
    ),
    tags=("v035", "a-real-world", "actuator-search", "wikipedia"),
    requires_real_net=True,
    flaky_repeat=3,
)
# V0.35.2: actuator click + multi-step navigation 真站点轴.
# octocat/Hello-World 招牌账户 3 commits freezed since 2014, 第 1 commit title
# "Merge pull request #6 from Spaceghost/patch-1" 永稳. predicate "Spaceghost" 用户名 10+ char
# 在 commit message 主体不依赖 GitHub UI 改版.
GITHUB_OCTOCAT_COMMITS_FIRST = EvalTask(
    task_id="v035-github-octocat-commits-first",
    goal=(
        "去 https://github.com/octocat/Hello-World 页面, 点击 'Commits' 链接 (repo 文件列表上方"
        "'3 Commits' 按钮或 history 图标), 跳到 commits 列表页, 提取最上方 (最新) 那条 commit "
        "的 title 文本, done(result=完整 commit title)."
    ),
    fixture_url="https://github.com/octocat/Hello-World",
    capability_axis="real-world",
    expected_step_range=(4, 10),
    max_steps=12,
    max_wallclock_s=180.0,
    description=(
        "V0.35.2 actuator click navigation 真站点轴. octocat 招牌账户 + 3 commits freezed 2014, "
        "第 1 commit 'Merge pull request #6 from Spaceghost/patch-1' 永不变. predicate 'Spaceghost' "
        "user name 在 commit message 主体, 抗任何 GitHub UI 改版."
    ),
    tags=("v035", "a-real-world", "actuator-click-nav", "github"),
    requires_real_net=True,
    flaky_repeat=3,
)

# V0.35.2: actuator scroll 真站点轴.
# QFT 长 article 含 id="History" anchor 5+ 年稳, History section 首句含 "theoretical physicists"
# (1920s QED 历史叙述不会改). goal 文案强约束 "不要 click toc, 用 scroll" 防 LLM 走 toc 锚点
# 绕过 scroll 路径 (V0.35.2 plan A 风险 mitigation).
WIKIPEDIA_QFT_SCROLL_HISTORY = EvalTask(
    task_id="v035-wikipedia-qft-scroll-history-section",
    goal=(
        "去 https://en.wikipedia.org/wiki/Quantum_field_theory 页面, 找到名为 'History' 的 section "
        "标题 (h2 heading, page 较深位置 #History anchor). **不要 click toc 锚链接**, 直接 scroll "
        "page 把 History section 滚到 viewport 内, 提取 History section 第一句, "
        "done(result=完整第一句)."
    ),
    fixture_url="https://en.wikipedia.org/wiki/Quantum_field_theory",
    capability_axis="real-world",
    expected_step_range=(3, 10),
    max_steps=12,
    max_wallclock_s=120.0,
    description=(
        "V0.35.2 actuator scroll 真站点轴. QFT 长 article 'History' section 首句含 'theoretical "
        "physicists' (1920s QED 历史叙述 5+ 年不动). goal 显式禁 toc click, 强 actuator scroll "
        "路径 (LLM 选 click toc 绕 scroll 风险 mitigation)."
    ),
    tags=("v035", "a-real-world", "actuator-scroll", "wikipedia"),
    requires_real_net=True,
    flaky_repeat=3,
)

CAPABILITY_REAL_WORLD_PREDICATES: dict[str, Predicate] = {
    WIKIPEDIA_SEARCH_QUANTUM_FIELD_THEORY.task_id: SubstringPredicate(substring="Quantum field theory"),
    GITHUB_OCTOCAT_COMMITS_FIRST.task_id: SubstringPredicate(substring="Spaceghost"),
    WIKIPEDIA_QFT_SCROLL_HISTORY.task_id: SubstringPredicate(substring="theoretical physicists"),
}
