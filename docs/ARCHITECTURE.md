# web-agent 架构决策

本文档记录 web-agent 项目从 V0.7.0 → V0.15.2 期间形成的核心架构决策、模块边界、信号通道复用逻辑、以及多层防御互补机制。

读者：未来接手者、或想理解"为什么这样写"的我自己。本文不替代 [`CHANGELOG.md`](../CHANGELOG.md)（事件日志）和 README（用户入口），它只回答 **"哪些选择是定下来的、为什么、以及替代方案被否的原因"**。

---

## 1. 决策树

下面 5 条选择决定了整个项目的形状，每条都列了 **可选项 / 选了什么 / 否决理由**。

### 1.1 浏览器接管：CDP 接管本地 Chrome vs Manifest V3 扩展 vs Playwright launch

**选择**：CDP 接管 (`connect_over_cdp("http://127.0.0.1:9222")`)。

否决理由：
- **MV3 扩展**：用户原蓝本 (`docs/高度模仿人操作网页的agent技术路径图.txt`) 强调"高度模仿人"，扩展受 manifest 权限矩阵 / service worker 30 秒生命周期 / `chrome.tabs` API 限制束缚太多；想要拟人鼠标轨迹、TLS 指纹、stealth 注入、跨 session 持久化都得绕路。
- **Playwright `launch`**：起隔离 Chromium 拿到的是新 user-data-dir，丢失用户登录态/Cookies/扩展，违背蓝本"无缝接管日常 profile"的目标。
- **CDP 接管 (选定)**：用户用 `scripts/start_chrome.sh` 启动带 `--remote-debugging-port=9222` 的独立 user-data-dir Chrome（不污染日常 profile，但同时保留登录态），agent 从 9222 接管即可继承 Cookies / 已登录 Gmail / 已装扩展，且能用 Playwright 全部 API。这是 MultiOn 同款路线。

### 1.2 元素感知：Set-of-Mark (SoM) vs Accessibility Tree

**选择**：SoM JS 注入 + Shadow DOM 穿透 (V0.12.0 W5-B)。

否决理由：
- **a11y tree**：DOM 同步、role 计算、隐藏元素剔除都是 Chrome 内部状态，从 CDP 拿出来易错且不带视觉信息；VLM 还得反推位置。
- **SoM (选定)**：在页面 DOM 内画方框 + 数字 mark_id，截图直接喂 vision LLM，LLM 输出 `mark_id=12` 我们对应坐标点击；信息密度高、token 友好、调试直观（截图就是 LLM 看到的）。V0.12.0 加 stack-based open shadowRoot 遍历 + WeakSet 去重处理 web component 嵌套场景。

### 1.3 反检测：patchright-python vs playwright-stealth 2.0.3

**选择**：先用 `playwright-stealth` 2.0.3，patchright 升级路径留 README "已知缺口"。

否决理由：
- **patchright-python (2026 SOTA)**：要求 `launch_persistent_context` + patchright 自己魔改的 Chromium，放弃 `connect_over_cdp` ⇒ 与决策 1.1 冲突，丢失用户已登录 profile。除非真的撞 Cloudflare 撞硬，否则不值得。
- **playwright-stealth 2.0.3 (选定)**：保留 CDP 接管，反检测虽弱于 patchright，但配合 xvfb headed 模式跑普通站够用。`browser.apply_stealth(page)` 多版本 API fallback (apply_stealth_async / apply_async / 全吞 ImportError)，不阻塞主路径。

### 1.4 数据持久化：单库 trace.db vs 分库 trace.db + memory.db

**选择**：分库（V0.13.0 W5-D）。

否决理由：
- **单库**：trace 表（每步一行 ~kB）和 memory 表（每 task 一行 ~100B）混一起，读写 IO pattern 完全不同；memory 想跨 session domain 查询时还得 JOIN trace 表的 task 表。
- **分库 (选定)**：`data/trace.db` 装本次执行的 step-level 事件流；`data/memory.db` 装跨 session 的 task outcome（domain / goal / result / OK|FAIL）。两库职责正交，备份策略也不同（trace 可定期清，memory 想长期保留）。`WEB_AGENT_MEMORY_DB` env 让 memory db 路径单独可配。

### 1.5 W5-C 分层规划：plan-and-execute LLM call vs prompt augmentation

**选择**：prompt augmentation（V0.15.0）。

否决理由：
- **plan-and-execute (subagent 原方案)**：第一步真调 LLM `plan()` 拿 subgoal 列表再执行；但这要求构造一次"无截图"的 LLM 调用 (`screenshot_b64=""`)，在 Anthropic / OpenAI / Kimi 三个 SDK 上的 vision-content-can-be-empty 兼容性都没验证过，撞坑成本未知。
- **prompt augmentation (选定)**：不调 LLM，只在第一次 plan 前注入一段固定字符串 hint："如果任务复杂，请在 thought 里把任务拆 3-6 个 subgoal 再执行"，让 LLM 自己用 `thought` 字段拆。零 token 浪费、零 SDK 风险、零 Protocol 改动。代价：拆 subgoal 是 nudge 不是约束，效果可能弱于真 plan-and-execute；但 ROI/风险比明显更好。

---

## 2. 模块边界

`src/web_agent/` 14 个模块，依赖方向严格 **domain ← ports ← 业务层 ← 组合根**：

| 模块 | 职责（一句话） | 层级 |
|---|---|---|
| `__init__.py` | `__version__` 单常量 | domain |
| `trace.py` | `Step` / `Trace` dataclass + SQLite 持久化 | domain |
| `safety.py` | W3-A 授权白名单（send/pay/delete/敏感字段拦截规则）| domain |
| `memory.py` | W5-D 跨 session 长期记忆（domain ↔ past goals/results） | domain |
| `llm/_schema.py` | SYSTEM_PROMPT + 5 个 tool schema + provider 适配函数 | port |
| `llm/_protocol.py` | `LLMClient` Protocol（`plan()` 唯一抽象边界） | port |
| `llm/anthropic.py` | Claude SDK 实现 + prompt caching | adapter |
| `llm/openai.py` | OpenAI / Kimi / OpenRouter 兼容（base_url 嗅探） | adapter |
| `browser.py` | `connect()` CDP 三元组 (browser/ctx/page) + `apply_stealth()` | adapter |
| `perceiver.py` | SoM JS 注入 + Shadow DOM 穿透 + cookie 弹窗自动关 | 业务 |
| `actuator.py` | 拟人 click/type/scroll（3 阶贝塞尔 + 截断正态键入 + typo） | 业务 |
| `captcha.py` | W4-2 Cloudflare/reCAPTCHA/hCaptcha 检测 + 暂停轮询 UX | 业务 |
| `notify.py` | W4-3 桌面通知 fire-and-forget（osascript / notify-send） | 业务 |
| `replay.py` | W4-1/W4-1.1 单文件 HTML replay 面板 + 索引页 | 业务 |
| `loop.py` | ReAct 主循环：perceive → plan → safety → actuate → trace.append | 业务 |
| `planner_hierarchy.py` | W5-C `should_decompose` 启发式 + subgoal hint 字符串 | 业务 |
| `cli.py` | 组合根：拼装上面所有模块 + 3 个 entry script | composition |

依赖方向（核心）：

```
cli.py ───┬──→ browser/perceiver/actuator/captcha/notify/safety/memory/planner_hierarchy
          ├──→ loop.py ──→ llm._protocol.LLMClient (Protocol, 不导入具体实现)
          └──→ llm.anthropic / llm.openai (具体类只在组合根实例化)

trace.py 只被业务层用; safety.py / memory.py / __init__.py 是叶子 domain
llm/_schema.py 不导 SDK, 纯 dataclass + 函数, 让 anthropic / openai 各自适配
```

**关键约束**：`loop.py` 只接受 `LLMClient` Protocol，不知道是 Anthropic 还是 OpenAI；具体类全部在 `cli.py` 这个组合根里 `if env == ...: client = AnthropicClient()`。意味着加 Gemini provider 不需要改 `loop.py` 一行。

---

## 3. 三轨同道：reflect / memory / subgoal 都走 `step=-1 memory_recall` 通道

V0.11.0 (W5-A)、V0.14.0 (W5-D.2)、V0.15.0 (W5-C) 三个独立 milestone 引入了三种"软提示给 LLM"的需求，但都共用同一个 trace 通道。

### 三个软提示的共同点

| Milestone | 提示内容 | 何时插入 |
|---|---|---|
| W5-A reflect | 页面 3 步无变化 → "fingerprint 重复，换策略" | 主循环中 perceive 后、plan 前 |
| W5-D.2 memory | 同 domain 历史 task outcome ("过去跑过 N 个，最近 OK/FAIL goal -> result") | 主循环开始前 |
| W5-C subgoal | "任务长，请用 thought 拆 3-6 个 subgoal" | 主循环开始前 |

三者都是 **soft hint**：不是硬约束，LLM 可以选择忽略；不污染 trace.db 的执行事件流；只在内存 `Trace.steps` deque 里存在，让下一次 `Trace.for_llm()` 渲染时 LLM 看到。

### 通道复用：`Step(step=-1, action_type="memory_recall", observation=...)`

V0.14.0 W5-D.2 第一次设计了"前置上下文非本轮行动"的语义：用 `step=-1` 区别于正常 `0..N-1`，`action_type="memory_recall"` 是已有 enum，`observation` 字段塞渲染好的字符串。

V0.15.0 W5-C 复用同一通道：subgoal hint 通过 `merge_into_memories(memories_str, build_subgoal_hint_text())` 拼到同一段 string 里，在 `cli.run_task` 透传 `memories=` 给 `loop.run_react_loop`。

V0.11.0 W5-A reflect 同模式：plan 前 `trace.append(Step(step=-1 ...))` 让 LLM 看到，不写 sqlite。

### 为什么不改 `LLMClient` Protocol？

诱惑路线是给 Protocol 加 `plan(... extra_hints: list[str] = [])` kwarg，但代价：

- Protocol 改一次，3 个 adapter (anthropic / openai / 未来的 gemini) 都要改
- LLM 看到 `extra_hints` 还是一段字符串，最终还是塞到 user message 或 system prompt 里 — 等于 trace 通道的副本
- 测试矩阵从 N 翻到 N×2

走 trace 通道：cli 加 1 行 / loop 加 1 个 kwarg + 1 个 synthetic step 拼接，Protocol / adapter / safety / captcha 全 0 改动。三个 milestone 累计 0 次 Protocol 改动。

**这是本项目最重要的架构原则之一：能从已有数据通道复用就不要新增抽象边界。**

---

## 4. 双层防御：safety 硬拦 + reflect 软提示 + anti-loop 硬 abort + captcha 暂停

主循环有 4 类信号互补，且**信号正交**——每个解决一个独立失效模式。

| 层 | 信号 | 触发条件 | 行为 | 何时介入 |
|---|---|---|---|---|
| **safety** (W3-A V0.6.0) | 硬拦 | LLM 选 send/pay/delete/敏感字段 type 命中白名单规则 | abort step 写 trace, 错误结束循环 | plan 之后、actuate 之前 |
| **anti-loop** (V0.5.0) | 硬 abort | 同 (action_type, args 关键字段) 连出 3 次 | abort 整个 task 写 trace, 标 LOOP_DETECTED | actuate 之前 |
| **reflect** (W5-A V0.11.0) | 软提示 | `_page_fingerprint` deque (maxlen=3) 三次重复 | 注入 hint "页面 3 步无变化" 到下次 plan, 不 abort | perceive 之后、plan 之前 |
| **captcha** (W4-2 V0.9.0) | 暂停 | DOM 命中 `cf-turnstile / g-recaptcha / h-captcha / google-verify` | 通知用户、暂停轮询、超时记 CAPTCHA_TIMEOUT | perceive 之前 |

### 信号为什么正交

- **safety**：拦"该做但不该自动做"的事（送钱、发邮件、删账户）→ 阻断单步
- **anti-loop**：拦"LLM 卡死循环"（agent 重复点同一按钮 3 次）→ 阻断整 task
- **reflect**：拦"LLM 没卡死但页面没动"（点了但没反应、或站点 JS 慢）→ 软提示让 LLM 换策略
- **captcha**：拦"网站要人验证"（不是 agent 错误也不是 LLM 错误）→ 暂停等用户

四种失效根因不同、症状不同、对策不同，叠加而不是互斥。

### captcha 为什么在 perceive 之前

captcha 检测 (`captcha.detect_captcha(page)`) 在 `loop.py` 主循环最开头（perceive 之前）。原因：

- 如果 perceive 先跑，SoM JS 注入会在 captcha iframe 内部画 mark，污染截图、误导 LLM 去点 captcha
- captcha 本质是"暂停 agent，让人接管"，越早检测越好

reflect 在 perceive 之后（用 `_page_fingerprint` 算 DOM 摘要），是因为 reflect 的判据是"看到的页面没变"，得先 perceive。

---

## 附录 A：版本里程碑速览

蓝本对应关系（详见 [`CHANGELOG.md`](../CHANGELOG.md)）：

- V0.6.0 W3-A safety 白名单
- V0.7.0 W3-C Gmail compose
- V0.8.0 W4-1 replay HTML 面板
- V0.9.0 W4-2 captcha 暂停 UX
- V0.10.0 W4-3 桌面通知
- V0.11.0 W5-A 自反思 page-stuck soft hint
- V0.12.0 W5-B Shadow DOM 穿透
- V0.12.2 W4-1.1 replay index 索引页
- V0.12.0~V0.15.1 audit gap 6/6 模块单测覆盖（perceiver / trace / cli / loop 主体 / browser / anthropic）
- V0.13.0 W5-D 跨 session 长期记忆（持久化 + dump CLI）
- V0.14.0 W5-D.2 长期记忆 inject 到 planner 上下文
- V0.15.0 W5-C 分层规划 prompt augmentation
- V0.15.1 audit gap 100% 收尾（browser + anthropic 最后两模块）
- V0.15.2 docs：本架构文档 + README known-gap 入账

## 附录 B：尚未在文档中体现的硬约束

- 测试 219 全绿是 release gate；任何 commit pre-commit hook 要走 ruff + pytest
- `data/*.db` / `data/screenshots/` / `data/replays/` 全 gitignored（存私密 trace + 截图）
- `.env` / API key / 真实邮箱地址永远不进 commit
- 拟人 actuator 默认开启（`scripts/start_chrome.sh` 配 xvfb 才完整生效），CI/headless 默认退化但保留 API
