# web-agent 架构决策

本文档记录 web-agent 项目从 V0.7.0 → V0.15.2 期间形成（V0.17 起为增量决策，未完整归档）的核心架构决策、模块边界、信号通道复用逻辑、以及多层防御互补机制。

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

#### V0.16.18 浏览器边界明确

CDP 是 **Chromium 独有协议** → 项目仅支持 Chromium 系浏览器。`scripts/start_chrome.sh` V0.16.18 起按优先级检测 11 个 binary：`google-chrome` / `google-chrome-stable` / `chromium` / `chromium-browser` / `brave-browser` / `brave` / `microsoft-edge` / `microsoft-edge-stable` / `msedge` / `vivaldi` / `vivaldi-stable` / `opera`。**Brave / Edge / Vivaldi / Opera 都基于 Chromium，CDP 协议层零差异**，启动加 `--remote-debugging-port=9222` 同样能被 `connect_over_cdp` 接管。用户也可 `CHROME_BIN=/path/to/...` env 覆盖。

**Firefox / Safari 架构上不支持**：协议不同（Firefox = Marionette/BiDi，Safari = Remote Web Inspector），且 Playwright 对它们只能 `launch_persistent_context()` 启**新进程** = 失去登录态接管。要支持必须放弃"无缝接管日常 profile"核心架构 → 与 patchright NO-GO 同根因。**WebDriver BiDi**（Playwright 1.59+ 试验性，W3C 跨浏览器协议）是未来路径但未成熟。

#### V0.16.19 约束 4 软化：auto-spawn Chrome (cli + mcp_server)

V0.16.18 之前用户必须先在终端跑 `bash scripts/start_chrome.sh`，否则 `connect_over_cdp` 报 ECONNREFUSED——这是 onboarding 摩擦最大的硬约束（V0.16.17 cookbook 4 步里第 1 步就是它）。

**V0.16.19 软化**：新模块 `src/web_agent/chrome_launcher.py` 提供 `ensure_chrome_running(cdp_url)`，cli.py / mcp_server.py 在 connect 之前调用：
- 9222 已活 → 零成本返回（与 V0.16.18 行为一致）
- 9222 不可达 + `WEB_AGENT_AUTO_SPAWN_CHROME=true`（默认）→ 自动 `subprocess.Popen([bash, scripts/start_chrome.sh], start_new_session=True, stdio=DEVNULL)` + 30s 健康轮询直到可达 → 接管 → exit 时**不杀** Chrome（用户后续可继续用）
- 9222 不可达 + `WEB_AGENT_AUTO_SPAWN_CHROME=false` → 抛 RuntimeError 引导手启（回退 V0.16.18 行为，给偏好显式控制的用户）

**关键设计**：
- `start_new_session=True`（POSIX setsid）让 Chrome 脱离 Python 进程组——父退出不带走 Chrome
- `stdin=stdout=stderr=DEVNULL` 是 stdio MCP 模式的硬要求——任何 Chrome 启动 log 落到 stdout 都会破坏 JSON-RPC 协议
- 模块级 `_check_chrome_alive` 名字保留在 `mcp_server.py`（delegate 实现到 chrome_launcher），向后兼容现有 monkeypatch 测试 fixture

**约束 4 现状**：从"必须先启 Chrome"软化为"建议先启（更可控），不启也行（自动 spawn）"。**首登 Gmail 仍需 headed 模式手登一次**，auto-spawn 解决不了这个（V0.16.17 cookbook 仍是 source of truth）。

### 1.2 元素感知：Set-of-Mark (SoM) vs Accessibility Tree

**选择**：SoM JS 注入 + Shadow DOM 穿透 (V0.12.0 W5-B)。

否决理由：
- **a11y tree**：DOM 同步、role 计算、隐藏元素剔除都是 Chrome 内部状态，从 CDP 拿出来易错且不带视觉信息；VLM 还得反推位置。
- **SoM (选定)**：在页面 DOM 内画方框 + 数字 mark_id，截图直接喂 vision LLM，LLM 输出 `mark_id=12` 我们对应坐标点击；信息密度高、token 友好、调试直观（截图就是 LLM 看到的）。V0.12.0 加 stack-based open shadowRoot 遍历 + WeakSet 去重处理 web component 嵌套场景。

### 1.3 反检测：patchright-python vs playwright-stealth 2.0.3

**选择**：`playwright-stealth` 2.0.3 — V0.16.14 spike 实测后**永久关闭** patchright 升级路径（在 connect_over_cdp 接管模式下）。

#### V0.16.14 spike 实测数据（worktree 隔离, sannysoft.com 35+ 项指纹检测）

| ID | 配置 | PASS / 计分 | FAIL |
|---|---|---|---|
| A | vanilla playwright + 裸接管 | 19 / 32 (~59%) | 4 |
| B | vanilla + apply_stealth (当前) | 21 / 32 (~66%, 扣 WebGL 双坑实际 23/32 ~72%) | 2 (WebGL Vendor/Renderer, 环境问题非反爬) |
| C | patchright + 裸接管 | 19 / 32 (~59%) | 4 |

**A == C 完全相同**：patchright 在 `connect_over_cdp` 9222 模式下的 client patch 被旁路。

#### 根因（subagent 分析）

- patchright 的核心 patch 大部分在 **launch 阶段**：改 launch flags、改 driver bin、抑制 `Runtime.enable` CDP 探针
- web-agent 接管的是用户**已启动**的 Chrome（`scripts/start_chrome.sh`），launch 阶段全部旁路
- sannysoft 的 35 项检测全在 **JS 注入层**（`navigator.*` / WebGL / canvas / `chrome.runtime`）；patchright 改的是 **CDP 协议层** — sannysoft 根本看不到

**B 比 A 多的 2 项 PASS**（HEADCHR_UA + CHR_MEMORY）正是 stealth 真正在防的 head-chr 探测；patchright 没补这层 JS 注入。

#### 否决理由

- **patchright-python**：要求 `launch_persistent_context` + 它自己魔改的 Chromium 才能让 launch flags / Runtime.enable patch 生效，放弃 `connect_over_cdp` ⇒ 与决策 1.1 冲突，丢失用户已登录 profile（项目核心架构）。即便如此，spike 已证伪它在接管模式下无任何观察到的增量。除非未来转向 `launch_persistent_context` 路径（W6 重大架构变更），否则**永久 NO-GO**。
- **playwright-stealth 2.0.3 (选定)**：保留 CDP 接管，反检测在 sannysoft 上实测 ~72% 通过率（扣环境 WebGL 后），配合 V0.16.14 GL flags + xvfb headed 模式跑普通站够用。`browser.apply_stealth(page)` 多版本 API fallback (apply_stealth_async / apply_async / 全吞 ImportError)，不阻塞主路径。

#### V0.16.14 副产物：WebGL SwiftShader flags

spike 暴露 sannysoft 上 B 的 2 个 FAIL 全是 `WebGL Vendor/Renderer = "Canvas has no webgl context"` — Xvfb 无 GPU 导致 SwiftShader 没启。修法：`scripts/start_chrome.sh` ARGS 加 `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader`，headless 模式删 deprecated 的 `--disable-gpu`。预期 B 跳到 23/32 (~72%) 且 FAIL=0。

#### V0.16.15 关联决策：curl_cffi TLS 指纹 NO-GO（当前架构）

**选择**：永久 NO-GO（直到 W6+ 引入"内部 HTTP 旁路"路径才重评估）。

curl_cffi（[lexiforest/curl_cffi](https://github.com/lexiforest/curl_cffi)，patched BoringSSL 把 ClientHello 字节级伪装成真 Chrome 145/146）解决 JA3/JA4 TLS 指纹反爬——Cloudflare bot management / DataDome / PerimeterX 在 HTTP 之前的 TLS 层识别"非浏览器"。

**为什么 web-agent 当前架构下 ROI = 0**：

| 流量路径 | 出口 TLS 栈 | 反爬目标？ | curl_cffi 增量？ |
|---|---|---|---|
| 浏览（goto / click / type） | Chrome 自己的 BoringSSL | ✓（CF/DataDome 看 JA3） | ❌ 已是真 Chrome 指纹，curl_cffi 改不到 |
| LLM API（anthropic/openai SDK） | Python httpx → OpenSSL | ❌（API 端点不做反爬） | ❌ Anthropic/OpenAI 不会拦 |

**核心**：所有网页流量从 `connect_over_cdp` 接管的真 Chrome 出去 → 默认就是真 Chrome JA3/JA4。curl_cffi 在浏览路径**完全没用**。LLM API 调用是与项目合作方的合规端点，不需要伪装。

**何时重评估**：W6+ 若引入"Python 直发 HTTP 旁路抓某 JSON API"的优化路径（绕过 Chrome 加速），那时候 curl_cffi 才有意义。**当前永久锁 NO-GO**，避免后人误以为是待办。

**与 patchright 的对比**（同根：反检测层升级路径决断）：
- patchright NO-GO 因为 connect_over_cdp 模式下 launch 阶段 patch 旁路（架构冲突）
- curl_cffi NO-GO 因为 Chrome 已经是真 TLS 栈（路径不需要）
- 两者**都不阻塞** "命中 Cloudflare 时上住宅代理" 这条真正的下一层防御路径

### 1.4 数据持久化：单库 trace.db vs 分库 trace.db + memory.db

**选择**：分库（V0.13.0 W5-D）。

否决理由：
- **单库**：trace 表（每步一行 ~kB）和 memory 表（每 task 一行 ~100B）混一起，读写 IO pattern 完全不同；memory 想跨 session domain 查询时还得 JOIN trace 表的 task 表。
- **分库 (选定)**：`data/trace.db` 装本次执行的 step-level 事件流；`data/memory.db` 装跨 session 的 task outcome（domain / goal / result / OK|FAIL）。两库职责正交，备份策略也不同（trace 可定期清，memory 想长期保留）。`WEB_AGENT_MEMORY_DB` env 让 memory db 路径单独可配。

### 1.5 W5-C 分层规划：plan-and-execute LLM call vs prompt augmentation

**选择**：prompt augmentation（V0.15.0）。W5-C.2 真 plan-and-execute **永久 DEFER**（V0.16.16 落档）。

否决理由：
- **plan-and-execute (subagent 原方案)**：第一步真调 LLM `plan()` 拿 subgoal 列表再执行；但这要求构造一次"无截图"的 LLM 调用 (`screenshot_b64=""`)，在 Anthropic / OpenAI / Kimi 三个 SDK 上的 vision-content-can-be-empty 兼容性都没验证过，撞坑成本未知。
- **prompt augmentation (选定)**：不调 LLM，只在第一次 plan 前注入一段固定字符串 hint："如果任务复杂，请在 thought 里把任务拆 3-6 个 subgoal 再执行"，让 LLM 自己用 `thought` 字段拆。零 token 浪费、零 SDK 风险、零 Protocol 改动。代价：拆 subgoal 是 nudge 不是约束，效果可能弱于真 plan-and-execute；但 ROI/风险比明显更好。

#### V0.16.16 W5-C.2 DEFER 决策（subagent 调研后落档）

V0.16.x 重新评估真 plan-and-execute 的 ROI，结论 **DEFER 直到三个触发条件之一满足**。

**SDK 兼容性现状**（V0.16.15，subagent 实测 SDK 文档）：

| Provider | 零截图 plan() 可行 | 原因 |
|---|---|---|
| Anthropic | ✅ | `messages.create()` vision content block 是 optional |
| OpenAI | ❌ | vision model（gpt-4o）必须 ≥1 image，text-only 要换模型混用 |
| Kimi | ❌ | OpenAI 兼容端点同上限制 |

**三 provider 中两个不可行**——这是 V0.15.0 当时担心的 SDK 兼容性问题，V0.16.x 仍然成立。

**真做的成本**（subagent 估）：~27h（Protocol 扩 + Anthropic 实现 + OpenAI/Kimi fallback 设计 + loop 2 阶段重构 + 30-40 case 测试 + cassette 重录）。Anthropic-only MVP 限定方案 ~16h，但与"BYO LLM"项目卖点冲突。

**触发条件**（任一满足才立项 W5-C.2）：

1. 用户反馈多个"prompt augmentation 没拆 task 导致失败"的真实案例（数据驱动证伪当前路线）
2. OpenAI/Kimi vision model 官方支持零 image 调用（如 `allow_empty_images=true` 参数）→ 三 provider 一致可行
3. 前置 spike 数据证明真 plan-and-execute 失败率比 augmentation **低 >20%**

**最低成本前置 spike**（V0.16.20 已实施 instrumentation, 数据待补 V0.16.21）：在 `loop.py` 加 logging 记录"LLM 是否在 thought 里实际拆了 subgoal"，跑 20 个复杂任务统计比例——给 W5-C.2 ROI 一个数据底座。当前 prompt augmentation 在 W1-W3 实战中是否真不够用，**无 A/B 证据**——可能 soft nudge 已经够。

#### V0.16.20 spike instrumentation 实施

`src/web_agent/loop.py` `_dump_spike_metrics()` (`run_react_loop` finally 1 处调用) + `scripts/run_w5c2_spike.py` (20 任务跑批 + summary 聚合) + `tests/test_loop_spike_w5c2.py` (10 case 验证 regex 与 jsonl schema)。激活: `WEB_AGENT_SPIKE_W5C2=1` env 开关 (默认 noop, overhead 极小)。

**5 指标定义** (per-step / per-task):

| ID | 名称 | 粒度 | 判定 |
|---|---|---|---|
| **M1** | subgoal_marker_present | per step | thought 含 "子目标 / 步骤 N / 第 N 步 / 1./① / first / step N / then / next / finally" |
| **M2** | plan_referenced | per step | thought 含 "目前在第 2 步 / 当前在 subgoal / 按计划 / according to the plan / as planned" |
| **M3** | task_has_plan | per task | 前 3 步任意一步 M1=True ("开局有没有拆") |
| **M4** | plan_consistency | per task | M2 命中步数 ≥ ⌈n/3⌉ ("拆了之后跟着走没") |
| **M5** | revision_on_failure | per failed step | is_failure_step=True 时下一步 thought 含 "换/改/重新+策略 / try a different approach / switch strategy / reconsider" |

**20 任务设计**: 6 个 should_decompose=True 长任务 (label 04/15/16/17/18/20 goal ≥200 字: Wikipedia 跨页 / Tokyo 人口 / WW2 Allies / GitHub vue stars→issues + 2 个 W3-C SAFETY_BLOCK 反指标) + 14 个 deterministic 短任务 (Wikipedia / HN / httpbin / GitHub / DuckDuckGo)。每任务 expect 字段或 expect_callable 客观判 success。

**决策矩阵 (data → verdict)**:

| compliance (M3∧M4) | task success | verdict |
|---|---|---|
| ≥80% | ≥70% | 升级**永久 NO-GO** (augmentation 已够用, 触发条件 ③ 不可能再被满足) |
| 30-80% | 50-70% | **维持 DEFER** (等真实用户反馈触发 ①) |
| <30% | <50% | **触发条件 ③ 候选** (+3h 跑 plan-and-execute 对照 spike, 失败率低 >20% 则立项 W5-C.2) |
| ≥30% | <30% | **non-LLM 改造** (SoM/actuator 问题, 与 W5-C.2 无关, 另开工单) |

**Risks**:
- 网络抖动 / Wikipedia 限流 → 单任务失败被算成"plan 失败"扭曲 success rate. 缓解: 任务间 sleep 15s + 跑前 5 个域名健康检查
- Chrome 反检测被 ban (GitHub/DDG) → 误判策略失败. 缓解: 任务 14 用 DDG 不用 Google
- Claude tier rate limit 后段任务全 LLM_FAILED → 含 LLM_FAILED 的任务从指标分母剔除标 excluded
- 样本量 n=20 统计意义弱 → V0.16.21 落档明确写"二次证据需 ≥50 任务", 当前仅做 ROI 排序而非 final verdict
- 指标过敏 (M1 假阳性) → V0.16.21 跑完手动抽 3 任务 thought 原文做 spot check, 校准 regex

**输出**: `~/.cache/web-agent/spike-w5c2/{label}-{task_id}.jsonl` (每任务每步) + `summary.jsonl` (每任务一行汇总) + 末尾 stdout 决策矩阵。

#### V0.16.21 跑批 4 根因修复（重跑前置）

V0.16.20 首跑数据 (compliance=0% / success=45% / decompose subset n=2) 看似落 "触发条件 ③ 候选", 但 4 根因审核后**数据不可信**:

1. **Chrome GPU SwiftShader 死锁** (Plan subagent 诊断: duckduckgo paint pipeline hang, GPU 累 53min CPU, CDP 共享 GPU 进程 close+reconnect 无效) → label 14-20 (7 任务) 全 SCRIPT_ERROR Timeout, 实际有效样本 13/20. 修: `scripts/run_w5c2_spike.py` `_kill_chrome_and_respawn()` + L1 retry + L3 每 5 任务周期重启 (~15s overhead)
2. **设计字数估错** → 4 长任务 < 200 字未被 should_decompose 识别, augmentation 真实测试样本 n=1. 修: `scripts/run_w5c2_spike.py` 4 任务 goal 拼到 ≥220 字
3. **`_judge()` false success bug**: task 04 LOOP_DETECTED 但 expect 命中中途 extract → success=True. 修: FAILURE_MARKERS 短路
4. **M1 regex 假阴性**: task 04 thought 用"第一步/第二步/第三步" (中文序数), V0.16.20 regex 只匹配阿拉伯数字漏判. 修: `src/web_agent/loop.py` _SPIKE_M1_RE / _SPIKE_M2_RE 拓宽中文序数 + "进行到/进入" 短语

详见 CHANGELOG V0.16.21.

#### V0.16.22 真 verdict: **维持 DEFER** (decompose subset compliance=50% / success=50%)

V0.16.21 重跑显示 M3 decompose=0% 落矩阵间隙. subagent 抽样 6 长任务 jsonl 发现 LLM 实际用 3 种 subgoal 表达 ("子任务 N" / "Subgoal:" / "第N步"), V0.16.21 regex 只命中"第N步" 1 种 → 测量层假阴性. V0.16.22 regex 第三轮校准 + `scripts/reaggregate_w5c2.py` 重处理 jsonl (不重跑 spike, V0.16.21 thought 原文已存) 后:

| 指标 | decompose subset (n=6) | all (n=20) |
|---|---|---|
| M1 per step | — | 32% |
| M2 per step | — | 25% |
| M3 task_has_plan | **50%** | 35% |
| M4 plan_consistency | **50%** | 15% |
| compliance (M3∧M4) | **50%** | 15% |
| success | 50% | 65% |

**decompose subset 落矩阵 #2: 维持 DEFER** (compliance 50% ∈ 30-80% + success 50% ∈ 50-70%).

**不立项 W5-C.2 plan-and-execute 对照 spike** (~3h):
- augmentation 能让 50% 长任务前 3 步开局拆 plan + 50% 后续 follow plan
- plan-and-execute 改进空间 ≤ 50%, 当前 success 50% 已 OK 水平
- 触发条件 ③ (plan-and-execute 失败率低 >20%) **失去 motivation** — augmentation 已工作
- 触发条件 ① (用户反馈 augmentation 失败案例) 仍是未来 trigger, 不强主动跑

**all 数据观察 (compliance all=15% / decompose=50%)**: `should_decompose()` 阈值精准 — augmentation 仅对长任务启动, 短任务不浪费 token, 短任务步骤普遍 M1 不命中是设计正确不是缺陷.

详见 CHANGELOG V0.16.22.

**与 patchright NO-GO / curl_cffi NO-GO 的差异**：
- patchright NO-GO = 架构冲突（与 connect_over_cdp 接管模式不兼容）
- curl_cffi NO-GO = 路径不需要（Chrome 已是真 BoringSSL）
- W5-C.2 DEFER = ROI 未量化 + SDK 阻碍未消除（不是永久 NO-GO，是"等条件成熟"）

---

## 2. 模块边界

`src/web_agent/` 16 个模块，依赖方向严格 **domain ← ports ← 业务层 ← 组合根**：

| 模块 | 职责（一句话） | 层级 |
|---|---|---|
| `__init__.py` | `__version__` 单常量 | domain |
| `types.py` | 共享 dataclass：`Mark` (SoM 元素) + `Action` (LLM 决策)，叶子 | domain |
| `trace.py` | `Step` / `Trace` dataclass + SQLite 持久化 | domain |
| `safety.py` | W3-A 授权白名单（send/pay/delete/敏感字段拦截规则）| domain |
| `memory.py` | W5-D 跨 session 长期记忆（domain ↔ past goals/results） | domain |
| `llm/_schema.py` | SYSTEM_PROMPT + 5 个 tool schema + provider 适配函数 | port |
| `llm/base.py` | `LLMClient` Protocol（`plan()` 唯一抽象边界）；`Action` re-export shim | port |
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
          ├──→ loop.py ──→ llm.base.LLMClient (Protocol, 不导入具体实现)
          └──→ llm.anthropic / llm.openai (具体类只在组合根实例化)

types.py 是最叶子 domain (Mark + Action), 不 import 任何 web_agent.* 模块, 被 perceiver / safety / llm.base / loop 共享
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

## 5. MCP server：暴露 web-agent 给 Claude Desktop / Cursor / Continue

V0.16.0–V0.16.7 把 web-agent 包装成 Model Context Protocol server (`web-agent-mcp` entry)，让任意 MCP client（Claude Desktop / Cursor / Continue.dev / Goose / 自写 Python 客户端）通过协议层调 web-agent。

### 5.1 三 tools + 两 resources 的语义切分

| 类型 | 名字 | 副作用 | 何时用 |
|---|---|---|---|
| **tool** | `web_agent_run(goal, url, max_steps)` | 跑真 ReAct loop / 改浏览器状态 | LLM 主动决定"我要让 agent 跑这个任务" |
| **tool** | `web_agent_get_replay(task_id)` | 写 HTML 文件到 `data/replays/` | LLM 主动决定"我要看这次执行的步骤" |
| **tool** | `web_agent_query_memory(domain, limit)` | 无（只读 SQLite） | LLM 主动查"该 domain 历史" |
| **resource** | `webagent://replay/{task_id}` | 无 | client 自动订阅渲染好的 HTML 文本（inline render） |
| **resource** | `webagent://memory/{domain}` | 无 | client 把 domain 历史当上下文订阅给 LLM（默认 5 条 JSON） |

**为什么 replay/memory 既给 tool 又给 resource**：tool 暗示"主动调用 + 可能有副作用"，resource 暗示"订阅 + 只读"。Claude Desktop UI 显式按钮场景适合 tool；LLM 在调 `web_agent_run` 前自动拉同 domain 历史的场景适合 resource。两者底层共享 `_render_replay` / `_query_memory` helper（V0.16.7 抽出），代码 70% dedup。

### 5.2 progress 三轨：mcp ctx → cli → loop 主循环 + captcha 心跳

Claude Desktop 默认 60s no-traffic timeout，单 ReAct step 平均 8-15s 安全，但 captcha 默认 300s wait 必撞超时。所以 progress notification 必须从 mcp ctx 下穿到 captcha poll：

```
client.call_tool(progress_callback=fn)
  ↓ MCP 协议层
mcp_server.web_agent_run(ctx)
  ↓ progress_cb = ctx.report_progress (bound method, 1:1 类型对齐)
cli.run_task(progress_cb=...)
  ↓ kwarg 透传
loop.run_react_loop(progress_cb=...)
  ↓ 主循环每步: await progress_cb(step_i, max_steps, f"step N/M")
  ↓ _handle_captcha 内联 poll: await progress_cb(step_i, max_steps, f"awaiting cf-turnstile (Xs/Ys)")
```

**架构关键**：`ProgressCallback = Callable[[int, int, str | None], Awaitable[None]]` 与 mcp `ctx.report_progress(progress, total, message)` 三参 1:1 对齐——不需 wrapper，bound method 自身可直接 DI 透传。

**captcha 心跳为什么走 inline poll 而不是改 captcha module API**：subagent V0.16.4 选 B 路径——captcha module 保持纯 detect/wait 单职，心跳是 loop 关心的事（它持有 progress_cb）。让 captcha 知道 progress_cb 是不必要的耦合。代价是 `_handle_captcha` 多出 7 行 inline poll，受益是 captcha module + test_captcha API 不变。

### 5.3 `_RUN_LOCK` 串行：Chrome CDP 单 tab 抢

```python
_RUN_LOCK = asyncio.Lock()  # module-level

async def web_agent_run(...):
    async with _RUN_LOCK:
        return await cli_run_task(...)
```

CDP `connect_over_cdp` 拿到的 BrowserContext 是单 tab 持有；并发 web_agent_run 会撞 SoM JS 注入 / actuator 鼠标轨迹 race condition。第二个并发请求自动 `await` lock（不 fail-fast 直接 reject，让 client 自然排队）。`async with` 在 cancellation 时自动释放，无 dead-lock 风险。

`_RUN_LOCK` 仅锁 `web_agent_run`——`get_replay` / `query_memory` 不动 Chrome 不需锁。

### 5.4 9222 健康检查：per-tool-call 而非 server-start

```python
async def web_agent_run(...):
    cdp_url = os.environ.get("WEB_AGENT_CDP_URL", "http://127.0.0.1:9222")
    await asyncio.to_thread(_check_chrome_alive, cdp_url)  # urllib stdlib, ≤2s
    ...
```

**为什么不在 server 启动时检查一次**：Claude Desktop 启 MCP server eager（用户不一定立刻用）；server-start fail-fast 会让"我只想 query_memory"的场景被卡。per-call 检查只惩罚需要 Chrome 的 tool（`web_agent_run`），其他 tool/resource 不付代价。

**为什么 `asyncio.to_thread` 包阻塞 urllib**：urllib `urlopen(timeout=2)` 是同步阻塞 ≤2s；不包 to_thread 会卡住 MCP 事件循环，进而卡住其他 tool/resource 的并发请求。stdlib 路径（不引 aiohttp 依赖）+ 异步友好。

### 5.5 V0.18 elicitation callback：safety 拦 → 询问用户 → continue/abort

V0.18.0 把 safety hardcoded "拦截即 abort" 改为可注入的 callback, 让 MCP client 决定阻拦动作的去留:

```
loop.py (业务层)              — 接 SafetyApprovalCallback ports, safety check 失败 + cb → await
  ↑
cli.py (组合根 CLI)            — 透传 safety_approval_cb=None 默认 (维持 env-based)
  ↑
mcp_server.py (组合根 MCP)     — ctx 可用时构造 _elicit_safety wrapper 注入
```

**ports 类型** (`web_agent.loop.SafetyApprovalCallback`):

```python
SafetyApprovalCallback = Callable[[str, str], Awaitable[bool]]
# (rule, reason) → approve (True=放行 / False=拦截)
```

**优先级链** (`loop.py` 主循环):

```
1. env WEB_AGENT_AUTO_APPROVE=* / 命中规则 → safety._block 直接放行 (cb 不调)
2. env 未放行 + cb 可用 → await cb(rule, reason); accept → 继续 dispatch + 标 elicited_approval_rule; decline → abort
3. env 未放行 + cb=None (CLI 模式默认) → 维持原 SAFETY_BLOCK abort
```

**MCP elicit 注入** (`mcp_server._elicit_safety` 由 `ctx` 触发构造):

```python
async def _elicit_safety(rule: str, reason: str) -> bool:
    try:
        result = await ctx.elicit(message=..., schema=SafetyApproval)
    except Exception as e:
        logger.warning("ctx.elicit 失败 (%r) → 视作 decline", e)
        return False
    if isinstance(result, AcceptedElicitation):
        return bool(result.data.approve)
    return False  # DeclinedElicitation / CancelledElicitation / 其他
```

**Schema 限制**: `SafetyApproval = BaseModel(approve: bool)` — MCP elicitation primitive `_validate_elicitation_schema` 只允许 primitive 字段 (str/int/float/bool), 不能嵌套 model.

**异常兜底**: cb 抛任何异常 (e.g. 旧 client 不支持 elicitation) → loop.py 视作 decline + log warning, 不 break loop. 安全 default.

**trace 标记**: cb 返 True 时, 主 dispatch 写 trace step 时给 `action_args` 加 `"elicited_approval_rule": rule`. replay HTML 可高亮"用户授权放行"的 step. V0.18.2 dogfood task `89a4be93e163` 的 step 2 click `action_args` 实证: `{"mark_id": 2, "elicited_approval_rule": "send-or-pay"}`.

**Esc 陷阱** (V0.18.2 dogfooding 实测): Claude Code 2.1.137 elicit 弹窗按 Esc → MCP error -32001 user-cancel, **不是 decline**. tool 整体 fail, trace 半死 (e.g. task `96118978d12b`: step 2 已写 `elicited_approval_rule` 但 `task.result=NULL`). 客户端 UI 操作语义见 README MCP setup 节 (V0.18.3 落档).

**为什么 ports 在 `loop.py` 不在 `safety.py`**:
- `safety.py` 是纯函数 (无 IO, 无 await), 改它接 cb 会污染 domain 层语义
- `loop.py` 是业务层, 本就持有 `progress_cb` (V0.16.4) 和 safety 调用上下文, 加 `safety_approval_cb` 自然
- 符合 CLAUDE.md "解耦优先" 依赖方向: domain (safety / types) ← ports (loop SafetyApprovalCallback) ← 业务层 (loop) ← 组合根 (cli / mcp_server)

**为什么 `cli.py` 默认 `cb=None` 而不构造终端 prompt 默认实现**:
- CLI 模式默认应保持向后兼容 (V0.17.x 行为 = abort), 用户主动覆盖才走 cb 路径
- 想要 CLI 模式带 cb (终端 prompt) → `demos/elicit_showcase.py` 是 reference 实现, 用户拷贝改造即可

### 5.6 SystemExit → RuntimeError 转译

`replay.load_task` 用 `sys.exit("db 不存在: ...")` 报错（CLI 行为）。MCP tool/resource 调用方拿 SystemExit 会让 server 进程退出（FastMCP 不 catch BaseException）。所以 `_render_replay` 内 catch SystemExit → `raise RuntimeError(...) from e`，让 SDK 序列化为 tool/resource error 而不让 server 死。

### 5.7 print → logging.info(stderr) 硬前提

stdio transport 模式下 stdout 是 JSON-RPC 通道，**任何 `print()` 污染会破坏协议**。所以 V0.16.0 把业务模块 25 处 print 改 `logger.warning/info`（`browser` / `perceiver` / `loop` / `cli`）；保留 7 处用户面向 stdout（`cli` 任务结果 / `memory` CLI dump / `replay` "wrote ..."）。`cli.main()` + `mcp_server.main()` 都 `logging.basicConfig(stream=sys.stderr)` 让 INFO 走 stderr。

**测试 capsys → caplog**：`tests/test_browser.py` 3 处 stealth fallback case 改 `caplog.at_level(WARNING)` + `caplog.text` 抓 logger 输出。其他 capsys 测的是用户面向 stdout（test_cli/memory/replay）保留 print 不改。

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
- V0.15.3-V0.15.8 W5-E 真实 LLM smoke 骨架（Anthropic + Kimi 国内 + GPT 三 provider，Kimi 国内 cassette V0.15.7 真录通）
- V0.15.10 → V0.15.11 撤回 Z 观察面板（浏览器扩展 read-only），切 MCP server 路径
- V0.16.0 print → logger.info(stderr) 硬前提（25 处机械替换）
- V0.16.1 MCP server 真接通（3 tools + asyncio.Lock + 9222 健康检查）
- V0.16.4 progress 三轨真 wire（mcp ctx → cli → loop 主循环 + captcha 心跳）
- V0.16.6 MCP Resources（replay HTML + memory entries 只读视图）
- V0.16.7 simplify pass（_render_replay/_query_memory 共享 helper）

## 附录 B：尚未在文档中体现的硬约束

- **三层 release gate** (V0.16.13 GitHub Actions `.github/workflows/ci.yml` push + PR 触发):
  - `uv run ruff check src/ tests/` → 0 errors（V0.16.10 起 17 → 0）
  - `uv run mypy src/web_agent` → 0 errors / strict mode（V0.16.12 起 47 → 0）
  - `uv run pytest -q` → 235 passed + 2 skipped（V0.16.7：220 主 + 15 mcp + 2 smoke skip）
- 任何上 main 的 commit 三关都要绿；本地可 `uv sync --all-extras && uv run ruff check src/ tests/ && uv run mypy src/web_agent && uv run pytest -q` 一并跑
- `data/*.db` / `data/screenshots/` / `data/replays/` 全 gitignored（存私密 trace + 截图）
- `.env` / API key / 真实邮箱地址永远不进 commit
- 拟人 actuator 默认开启（`scripts/start_chrome.sh` 配 xvfb 才完整生效），CI/headless 默认退化但保留 API
