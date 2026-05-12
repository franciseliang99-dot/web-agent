"""V0.40.0 A' V0.35 真站点 corpus 扩 5+ task — 开篇 2 task.

V0.35 已加 3 actuator 真站点 task (search/click-nav/scroll). V0.40 扩 5+ task 覆盖更多
capability axis × real-world. 用户选 A' 主题 from V0.39.1 inventory.

V0.34 教训应用第 N+1 次: V0.40.0 实施前 curl micro experiment 验每个 fixture predicate 真存
(跟 V0.35.0 W3C iframe 推翻 / V0.35.2 4 候选选 2 同模式):

```bash
# V0.40.0 candidate C1 Mercury element page 真测
curl -sS -L "https://en.wikipedia.org/wiki/Mercury_(element)" | grep -oE "atomic number 80"
# → "atomic number 80" 真在首段 "Mercury is a chemical element; it has symbol Hg and atomic
#    number 80. It is commonly known as quicksilver..." (5+ 年永稳, 元素 atomic number 不变)

# V0.40.0 candidate C3 IANA example-domains 真测
curl -sS -L "https://www.iana.org/help/example-domains" | grep -oE "are maintained"
# → "example.com and example.org are maintained for documentation purposes..." (RFC 2606 永稳)

# V0.40.0 candidate C2 (推翻) Wikipedia missing-article fallback
curl -sS -L "https://en.wikipedia.org/wiki/Nonexistent_Page_xyz999" | grep -oE "does not have an article"
# → 空! Wikipedia 现 missing-article 跳"创建文章"页, 不显 "does not have an article" 文本.
# V0.34 教训 catch: plan agent C2 fixture 推翻, 改 C3 IANA 代替.
```

V0.40 系列 plan:
- V0.40.0 (本): 2 task (C1 + C3) — actuator-page-extract 子轴起步
- V0.40.1: +3 task (C4 octocat blob raw / C5 httpbin form type / C6 wikipedia disambiguation click)
  → 累计 5 task 达 "5+ task" 验收线
- V0.40.2: 系列收尾 retrospective (压缩 4→3 commit, 跟 V0.39 同模式如 ROI 真测推翻)
- V0.40.x.1 deferred maintainer 真录 cassette (~$1-2 token, 跟 V0.35.1/V0.37.4 同模式红线)
"""

from __future__ import annotations

from eval.predicates import Predicate, SubstringPredicate
from eval.types import EvalTask

# V0.40.0 C1: Mercury 元素页 actuator navigate + extract.
# Mercury_(element) 首段含 "atomic number 80" — 元素物理属性 5+ 年永稳, 比 V0.30 wikipedia
# "phenomenon" 类首段词更 specific (atomic number 是元素唯一标识, 不会改).
WIKIPEDIA_MERCURY_ELEMENT_EXTRACT = EvalTask(
    task_id="v040-wikipedia-mercury-element-extract",
    goal=(
        "去 https://en.wikipedia.org/wiki/Mercury_(element) 页面, 提取首段 (lead paragraph) "
        "含 'atomic number' 的句子, done(result=完整句子)."
    ),
    fixture_url="https://en.wikipedia.org/wiki/Mercury_(element)",
    capability_axis="real-world",
    expected_step_range=(2, 6),
    max_steps=8,
    max_wallclock_s=120.0,
    description=(
        "V0.40.0 A' 真站点 corpus 扩 task #1: Mercury 元素页 perceiver extract. predicate "
        "'atomic number 80' (16 char) 元素物理属性永稳, 跟 V0.30 wikipedia 静态 extract 同 "
        "actuator-page-extract 子轴 (V0.40 起子 axis 标签). curl probe 已验 (V0.40.0 docstring)."
    ),
    tags=("v040", "a-real-world-extended", "actuator-page-extract", "wikipedia"),
    requires_real_net=True,
    flaky_repeat=3,
)

# V0.40.0 C3: IANA example-domains doc 页 perceiver extract.
# RFC 2606 永稳 doc 页, "example.com and example.org are maintained" 句永不会改 (官方维护).
IANA_EXAMPLE_DOMAINS_EXTRACT = EvalTask(
    task_id="v040-iana-example-domains-doc-extract",
    goal=(
        "去 https://www.iana.org/help/example-domains 页面, 提取页面说明 'example.com' 和 "
        "'example.org' 用途的句子 (含 'maintained' 词), done(result=完整句子)."
    ),
    fixture_url="https://www.iana.org/help/example-domains",
    capability_axis="real-world",
    expected_step_range=(2, 6),
    max_steps=8,
    max_wallclock_s=120.0,
    description=(
        "V0.40.0 A' 真站点 corpus 扩 task #2: IANA 官方 doc 跨 wiki/github source baseline. "
        "predicate 'are maintained' (14 char) RFC 2606 永稳 (官方域名保留). curl probe 已验."
    ),
    tags=("v040", "a-real-world-extended", "actuator-page-extract", "iana"),
    requires_real_net=True,
    flaky_repeat=3,
)

# V0.40.1 C4: GitHub octocat repo "Raw" button actuator click + extract.
# octocat/Hello-World README 内容 "Hello World!" 是 GitHub 招牌账户永稳内容 (10+ 年不会改).
# raw 视图 URL: raw.githubusercontent.com/octocat/Hello-World/master/README, 但 actuator 路径
# 是 web UI 点 "Raw" button 跳 raw 页 extract.
GITHUB_OCTOCAT_RAW_BLOB_VIEW = EvalTask(
    task_id="v040-github-octocat-raw-blob-extract",
    goal=(
        "去 https://github.com/octocat/Hello-World/blob/master/README 页面, 点击 'Raw' 按钮 "
        "(GitHub 文件视图右上角) 或导航到 raw 视图, 提取文件全部内容, "
        "done(result=完整文件文本)."
    ),
    fixture_url="https://github.com/octocat/Hello-World/blob/master/README",
    capability_axis="real-world",
    expected_step_range=(3, 8),
    max_steps=10,
    max_wallclock_s=180.0,
    description=(
        "V0.40.1 A' 真站点 corpus 扩 task #3: GitHub raw blob 视图 click + multi-step extract. "
        "predicate 'Hello World!' (12 char) octocat 招牌账户 README 永稳, 跟 V0.30 'My first "
        "repository' 同 octocat 信誉. curl probe 已验."
    ),
    tags=("v040", "a-real-world-extended", "actuator-click-raw", "github"),
    requires_real_net=True,
    flaky_repeat=3,
)

# V0.40.1 C5: httpbin form actuator type + extract response echo.
# httpbin.org/forms/post 是 HTTP testing service 静态 form 页, label "Customer name" 等
# field name 5+ 年永稳 (RFC test server 不会改 form spec).
HTTPBIN_FORM_TYPE_LABEL_EXTRACT = EvalTask(
    task_id="v040-httpbin-form-customer-name-label-extract",
    goal=(
        "去 https://httpbin.org/forms/post 页面, 找到 form 内 'Customer name' 这个 label, "
        "提取此 label 文本 + 其后 input field 的 name 属性, done(result=完整 label 文本)."
    ),
    fixture_url="https://httpbin.org/forms/post",
    capability_axis="real-world",
    expected_step_range=(2, 6),
    max_steps=8,
    max_wallclock_s=120.0,
    description=(
        "V0.40.1 A' 真站点 corpus 扩 task #4: httpbin form 静态 label extract. predicate "
        "'Customer name' (13 char) HTTP test service form spec 永稳. 跨 site source baseline "
        "(wikipedia/github/iana 之外加 httpbin)."
    ),
    tags=("v040", "a-real-world-extended", "actuator-form-read", "httpbin"),
    requires_real_net=True,
    flaky_repeat=3,
)

# V0.40.1 C6: Wikipedia Mercury disambiguation click follow link to Mercury (planet) page.
# disambiguation page 列若干 "Mercury" 含义, click "Mercury (planet)" 链落 planet page,
# extract "smallest planet in the Solar System" (太阳系最小行星, 物理事实永稳).
WIKIPEDIA_MERCURY_DISAMBIG_PLANET_FOLLOW = EvalTask(
    task_id="v040-wikipedia-mercury-disambig-planet-follow",
    goal=(
        "去 https://en.wikipedia.org/wiki/Mercury_(disambiguation) 页面, 找到 'Mercury "
        "(planet)' 这个含义的链接, 点击进入 planet 页, 提取首段含 'smallest' 描述太阳系行星的句, "
        "done(result=完整句子)."
    ),
    fixture_url="https://en.wikipedia.org/wiki/Mercury_(disambiguation)",
    capability_axis="real-world",
    expected_step_range=(4, 10),
    max_steps=12,
    max_wallclock_s=180.0,
    description=(
        "V0.40.1 A' 真站点 corpus 扩 task #5 (达 5+ task 验收线): Wikipedia disambiguation "
        "click + multi-page navigation extract. predicate 'smallest planet' (15 char) "
        "太阳系物理事实永稳 (Mercury 最小行星 5+ 年不会改). curl probe 已验."
    ),
    tags=("v040", "a-real-world-extended", "actuator-disambig-click", "wikipedia"),
    requires_real_net=True,
    flaky_repeat=3,
)

CAPABILITY_REAL_WORLD_EXTENDED_PREDICATES: dict[str, Predicate] = {
    WIKIPEDIA_MERCURY_ELEMENT_EXTRACT.task_id: SubstringPredicate(substring="atomic number 80"),
    IANA_EXAMPLE_DOMAINS_EXTRACT.task_id: SubstringPredicate(substring="are maintained"),
    GITHUB_OCTOCAT_RAW_BLOB_VIEW.task_id: SubstringPredicate(substring="Hello World!"),
    HTTPBIN_FORM_TYPE_LABEL_EXTRACT.task_id: SubstringPredicate(substring="Customer name"),
    WIKIPEDIA_MERCURY_DISAMBIG_PLANET_FOLLOW.task_id: SubstringPredicate(substring="smallest planet"),
}
