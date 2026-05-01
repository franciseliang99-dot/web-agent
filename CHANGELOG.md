# Changelog

All notable changes to web-agent. 版本号遵循 SemVer 简化形式（V<major>.<minor>.<patch>）。

## [0.4.4] - 2026-05-01

### Fixed
- `demos/github_search.py` goal prompt 调优：W2-B 首次跑跑出"max_steps 耗尽"（实质是 LLM 在 step 6 已拿到答案但反复 scroll 在 README vs About 间纠结）
  - 改 "从 README 区域读取" → "从右侧 About 区域读取（不必 README 正文，About sidebar 的描述就是权威）"
  - 加 "拿到三个字段立即用 done 工具，不要反复 scroll 验证"
  - 不动 system prompt（W1 demo 没这个问题，避免污染通用行为）

### Why
- LLM extract 工具拿到完整答案后没主动 done，反复确认（典型 over-verification）
- 通过 demo-specific prompt 指明"哪里是权威 + 何时收手"，比改 system prompt 通用化更安全

## [0.4.3] - 2026-05-01

### Fixed
- 默认 CDP URL `http://localhost:9222` → `http://127.0.0.1:9222`（browser.py / cli.py / .env.example）
  - 部分 Linux 发行版（含 Ubuntu 22.04+）IPv6 优先，`localhost` resolve 到 `::1`，但 chrome `--remote-debugging-port` 只 listen IPv4 → `ECONNREFUSED ::1:9222`
  - 实测 W2-B demo 跑出错的根因
- 用户可通过 WEB_AGENT_CDP_URL env 覆盖（如需 IPv6 端点 / 远程 chrome）

## [0.4.2] - 2026-05-01

### Added
- `demos/github_search.py` — W2-B 第二个 demo：在 GitHub 搜 repo → 切「Most stars」排序 → 进第一个 repo → 提取 star 数 + README 一句话简介
  - 验证非 Wikipedia 站（GitHub SPA 路由 / 动态加载 / 多 step 任务）
  - max_steps=18（W1 是 12，W2-B 估 7-10 步留 80% 余量）
  - 复用现有 stack 不动 actuator / perceiver / loop / llm

### Why
- W1 (Wikipedia) 验证了 stack 在传统多页面 + form submit 站工作，但 SPA 路由 / 动态加载 / 多步任务 / sort UI 切换都没碰过
- W2-B 用 GitHub 这种"反 bot 弱 + 全 SPA + 真实生产 UI"的典型站，最快暴露 stack 边界
- 故意先单 commit 提 demo（不动核心代码），跑出失败再决定要不要 patch loop（SPA wait_for_load_state 可能不准）/ perceiver（README 区域 marks 过多）

## [0.4.1] - 2026-05-01

### Refactored
- `actuator.py::human_like_type` simplify pass（V0.4.0 simplify subagent 审查产物）：
  - `_QWERTY_NEIGHBORS.get(ch.lower(), "x")` → `_QWERTY_NEIGHBORS[ch.lower()]`：fallback `"x"` 死代码（外层 `_is_qwerty_letter` 已保证 `ch.lower() ∈ a-z`，dict 26 字母全覆盖），删 fallback 让"未覆盖触发兜底 x"这个不真实的契约消失，KeyError 直接暴露真 bug
  - `recent_delays: list[float] = []` → `deque[float] = deque(maxlen=3)`：原 list 只读 `[-3:]` 但每步 `append` 无界增长（200 字 input 涨到 200 entries 仅看末 3），改 deque 内存恒定 + 意图自描述；`sum(recent_delays[-3:]) / 3` 同步精简为 `sum(recent_delays) / len(recent_delays)`（deque maxlen=3 满后 len 恒为 3，与原均值等价）
- 5 个 simplify 候选中其余 3 个跳过：
  - `_bezier_path` off1/off2 抽 `_perp_offset` helper：仅 2 处相邻使用，按用户硬约束 (>2 处才抽) 跳过
  - `_click_point` sx/sy + clamp 抽 `_truncated_gauss` helper：同上，2 处相邻使用跳过
  - `wrong.upper()` 大小写处理：`random.choice("gyujnb")` 返回单字符，`.upper()` 是 "G"（不是 "GY"），逻辑正确无 bug

### Compatibility
- 行为 100% 等价：`deque(maxlen=3)` 满后 `sum/len == sum([-3:])/3`，未满时 `len(recent_delays) < 3` 短路防御对齐；典型 ASCII letter 输入 `_QWERTY_NEIGHBORS[ch.lower()]` 永远命中
- pytest 30/30 仍绿
- 公共函数签名零变化（`human_like_type(page, text, typo_rate=0.02)` 不动）

## [0.4.0] - 2026-05-01

### Changed
- **拟人 actuator W2 升级**（src/web_agent/actuator.py 全替换 W1 占位实现，参数已按反爬研究 + 打字研究优化）：
  - **鼠标轨迹**：直线 `page.mouse.move(steps=15-25)` → 3 阶贝塞尔（P0/P3 端点 + P1/P2 在 1/3 和 2/3 处垂直 N(0, jitter*dist) 偏移、clamp ±80px）+ **smootherstep (6t⁵-15t⁴+10t³)** ease（加加速度连续，minimum-jerk 廉价近似，比 smoothstep 更难被反爬识别）
  - **鼠标起点**：W1 直线 → **WeakKeyDictionary[Page, (x,y)]** 跟踪 per-page 上次落点（连贯轨迹；W3 multi-tab 不串扰；Page GC 后自动清）
  - **步数自适应**：固定 15-25 → `max(15, min(40, dist/20 + 5-10))`，远距离多走几步
  - **键入间隔**：uniform(80, 200)ms → 截断正态 N(120, 40)ms ∈ [40, 300]
  - **键入 typo**：~2% 概率（`typo_rate=0.02`，参考 Salthouse 1986 + IKI 数据集）+ **触发门槛：最近 3 字平均间隔 < 150ms**（慢打字不会频繁错）+ **真人 reaction time 200-400ms 后 backspace**（打错→察觉→删除，不是瞬间退格）
  - **点击坐标**：均匀 ±5px → 截断正态 std=`max(3, min(w/6, 15))` + 截断到按钮 **90% 内区**（小按钮加底防视觉太集中，大按钮加顶防离散过分；80%→90% 让点击偶尔落到近边缘，更真人）
  - **滚动**：单次 wheel → 4-7 段 sin 包络 + **段间停顿 50-120ms**（避免连发被反爬识别）+ 末段补差防舍入丢失
  - 新内部 helper：`_bezier_path` / `_type_delay` / `_is_qwerty_letter`
  - 新 state：`_last_mouse_pos: WeakKeyDictionary[Page, tuple[float,float]]`
- **测试重写**（tests/test_actuator.py）：原 2 个 ±5 假设测试废，新 14 个测试覆盖：
  - `_click_point`: 不出按钮 / 均值居中 / 集中度 >50% 在 ±std 内 / 1px tiny button / 0x0 退化 / 小按钮 std 不退化到 0
  - `_bezier_path`: 步数 / 端点匹配 / 无突跳 / 零距离 corner case / smootherstep 开始慢 / jitter=0 时 x 单调
  - `_type_delay`: 截断范围 / 均值近 120ms

### Why
- 用户技术蓝本核心要求：「鼠标移动不应是直线，使用 n 阶贝塞尔曲线模拟人类手部的微颤和非匀速弧形轨迹」+「按键间隔随机延迟」+「偶尔打错一个字母，然后退格修正」+「点击不要点在几何中心点，而是按钮范围内服从正态分布的随机点」
- W1 占位实现（直线鼠标 / 均匀间隔 / 中心 ±5）已挂账技术债；W1 demo 跑通后立刻还
- Plan subagent 反馈优化（jitter 0.15→0.08、smoothstep→smootherstep、typo 0.04→0.02 + 速度门槛 + reaction time、std 公式带底+顶、滚动段间停顿、_last_mouse_pos→WeakKeyDictionary）合并进同一 commit，避免发布已知不优的版本

### Compatibility
- 公共函数签名 100% 向后兼容：`human_like_click(page, mark)` / `human_like_type(page, text, typo_rate=0.02)` / `scroll(page, dy)` / `think()` — `loop.py` 零改动
- 新参数 `typo_rate` 有 default，旧调用站点零改动
- 行为变化：鼠标轨迹明显不同（弧线 vs 直线）、键入会偶现 typo+backspace、滚动有惯性 — user-facing 拟人度提升 → minor bump 0.4.0

## [0.3.2] - 2026-05-01

### Fixed
- Kimi K2.6/K2.5 thinking 模式吃光 max_tokens 导致 `tool_calls=None` → loop 第 4 步崩溃
  - `OpenAIClient.plan()` Kimi 路径加 `extra_body={"thinking": {"type": "disabled"}}` 关 thinking
  - max_tokens 4096（关 thinking 后 reasoning_content 不再占预算，4096 远超 tool_call 输出需求）
- `OpenAIClient.plan()` `tool_calls=None` 时报错信息加 reasoning/content 预览，方便排查

### Why
- 实测 Kimi 跑 W1 demo 第 4 步崩：模型已读到维基首段、reasoning 反复琢磨该 done 还是 extract，2048 token 在 thinking 阶段烧完没机会 emit tool_call
- subagent 查到 Moonshot 官方 `extra_body={"thinking":{"type":"disabled"}}` 是根因开关；官方文档明示「tool-heavy agent flow 推荐关 thinking」（builtin $web_search 与 thinking mode 互不兼容也是同源问题）
- 选「关 thinking」而非「加大 max_tokens」：后者只是掩盖症状还烧 token 预算（每步 thinking 几千 token 即使最后用不上也按 output 计费）

### Compatibility
- 仅影响 Kimi 路径；Anthropic / OpenAI / OpenRouter 完全不动
- 老 model id `moonshot-v1-*-vision-preview` 没有 thinking 模式，`extra_body` 会被忽略，无副作用

## [0.3.1] - 2026-05-01

### Added
- `scripts/start_chrome.sh` 改造为四模式（CHROME_MODE env）：
  - `auto`（默认）：装了 xvfb → xvfb / 有 DISPLAY → headed / 都没 → `--headless=new`
  - `xvfb` / `headless` / `headed` 显式覆盖
- 新支持 env：`CHROME_DEBUG_PORT`（默认 9222）、`CHROME_USER_DATA_DIR`（默认 `~/.config/web-agent-chrome`）
- 增加 Chrome 启动参数 `--disable-blink-features=AutomationControlled`（缓解部分反爬指标）
- README 加 mode 自动推断对照表 + SSH headless server 推荐路径（`apt install xvfb` 一行升级到拟人模式）

### Why
- 用户 SSH 登录无 GUI 机器，原 `start_chrome.sh` 直接 `exec google-chrome` 在 headless server 上 cannot open display 报错
- 用户技术蓝本（`docs/高度模仿人操作网页的agent技术路径图.txt`）明确反对 `--headless` 模式
- subagent 评估三方案：A `--headless=new`（CDP 指纹漏）/ B Xvfb（贴合蓝本但需装包）/ C env 切换（默认贴合蓝本，缺包友好 fallback），选 C
- auto 模式让"立刻能跑（fallback headless）"和"装包后自动升级到 xvfb"都满足

### Compatibility
- 默认行为变化：本机有 GUI 的用户，从「直接有界面」变成「有 DISPLAY 时仍走 headed」（行为等价）
- 完全无破坏：`bash scripts/start_chrome.sh` 仍是入口；显式 `CHROME_MODE=headed` 能恢复旧行为

## [0.3.0] - 2026-05-01

### Added
- **Kimi / Moonshot 支持**（走 OpenAIClient + base_url），无需新增 client 类
  - `provider_from_model` 加 `kimi-*` / `moonshot-*` 前缀 → openai 推断
  - OpenRouter 路径 `moonshotai/kimi-k2.6` 也走 openai
  - `OpenAIClient.__init__` 加 `_is_kimi` 自动检测（base_url 含 "moonshot" 时 True）
  - `OpenAIClient.plan()` 在 Kimi 模式下：
    - `max_completion_tokens` → `max_tokens`（Kimi 不识 GPT-5.x 新参数名）
    - `tool_choice="required"` → `"auto"`（Kimi OpenAI compat 端点不支持 required，会拒）
- `.env.example` 加 Kimi 国际版 / 国内版配置注释
- `README.md` BYO LLM 节加 Kimi 用法 + 单步成本估算（cache miss ≈ $0.004 / hit ≈ $0.001）
- `tests/test_llm_openai.py` 加 Kimi 检测 + provider_from_model 推断的测试

### Why
- 用户问「我想用 kimi2.5 key」
- 选路径 B（subagent 评估 A 即"零改动直接走 OpenAIClient"会因 `tool_choice="required"` + `max_completion_tokens` 双爆而 broken；C 即独立 KimiClient 与 OpenAIClient 90% 重复违反 DRY）
- 不引入新 client 类、不动 LLMClient Protocol；增量是 OpenAIClient 内的兼容性 if 分支，符合「不引入新耦合」

### Compatibility
- 完全向后兼容：未配 `OPENAI_BASE_URL=...moonshot...` 时 `_is_kimi=False`，OpenAI 路径行为 100% 等价 V0.2.x
- Anthropic 路径完全不动

## [0.2.1] - 2026-05-01

### Refactored
- 抽 `build_user_text(goal, marks, trace)` 到 `llm/_schema.py`：`anthropic.py` 与 `openai.py` 的 `plan()` 内 history_text 序列化 + user 文本构造完全相同（goal / Action Trace / SoM 元素清单 4 个 markdown 段），各 client 内重复 ~12 行；现统一走 helper，差异只剩 image content block 格式（Anthropic `source.base64` vs OpenAI `image_url` data URL）
- `llm/__init__.py::provider_from_model` OpenRouter 分支拍平嵌套三元：`return "anthropic" if prefix == "anthropic" else ("openai" if … else "gemini")` → 4-key dict 直查（`google` 也映射到 `gemini`）

### Why
- simplify subagent 触发的 V0.1.2 + V0.2.0 多 LLM 抽象审查；R1（plan() 模板部分重复）+ Q1（嵌套三元）属真阳，已修；其他候选（合并两个 client 文件、Protocol → ABC、TOOL_SCHEMAS → dataclass、make_client dict 映射、为 GeminiClient 预留 hook、复杂化 provider_from_model）按用户硬约束 / YAGNI 跳过

### Compatibility
- 行为零变化：user text 串完全等价（同样的 f-string 模板，同样的 marks_to_text + json.dumps 顺序与参数）；`provider_from_model` 输出表完全等价
- pytest 13/13 仍绿

## [0.2.0] - 2026-05-01

### Added
- `src/web_agent/llm/openai.py` — `OpenAIClient` 实现 LLMClient Protocol
  - vision: `image_url` 内嵌 base64 data URL，`detail: high` 保 SoM 编号清晰度
  - tool-use: strict mode (`additionalProperties:false` + 全字段进 required + `function.strict:true`)
  - `tool_choice="required"` 强制工具调用
  - `max_completion_tokens` (GPT-5.x 系列参数)
  - 自动 prompt caching（OpenAI ≥1024 token 前缀匹配，无需显式 cache_control）
  - 接 `OPENAI_BASE_URL` env：支持 OpenRouter OpenAI skin / 自部署 LiteLLM / Azure OpenAI
  - DEFAULT_MODEL = `gpt-5.5`（2026-04-24 release）
- `pyproject.toml::[project.optional-dependencies]`：`openai = ["openai>=2.33,<3"]`，`uv sync --extra openai` 按需装
- `tests/test_llm_openai.py` 6 个新测试（pytest.importorskip 让未装 openai 时整文件跳过）
- `.env.example` 加 OPENAI_API_KEY / OPENAI_BASE_URL / WEB_AGENT_LLM_PROVIDER 注释
- `README.md` 加 「BYO LLM API key」 节，覆盖 Anthropic / OpenAI / OpenRouter / 自部署 LiteLLM 4 种用法

### Why
- 用户问「可以用其他 LLM 的 API key 吗」 → 选路线 B（自抽 LLMClient Protocol）
- W1 范围 = Anthropic + OpenAI 两家：Gemini cache+schema 差异最大，硬塞会让 Protocol 抽象设计被 Gemini 反向绑架，留 `provider_from_model` 推断位 + factory raise 友好报错，等真用户提需求再实现 GeminiClient

### Compatibility
- 完全向后兼容：未设 OPENAI_API_KEY / WEB_AGENT_LLM_PROVIDER 时默认走 Anthropic，与 V0.1.x 行为一致
- 不装 openai 可选依赖时：`make_client(provider="openai")` 抛 RuntimeError 提示「uv sync --extra openai」

## [0.1.2] - 2026-05-01

### Refactored
- 抽 `LLMClient` Protocol 到 `src/web_agent/llm/`（base.py / _schema.py / anthropic.py / __init__.py）
- 拆 `planner.py` → `llm/` 子包：SYSTEM_PROMPT + TOOL_SCHEMAS（中性）+ AnthropicClient + factory
- 删 `planner.py`（功能全部搬入 llm/）
- `loop.run_react_loop` signature 改：`client: AsyncAnthropic, model: str` → `client: LLMClient`，model 由 client 持有
- `cli.run_task` signature 加 `provider: str | None`；调用 `make_client(provider=, model=)` 装配
- 增加 `WEB_AGENT_LLM_PROVIDER` env 支持 + `--provider` CLI 参数
- AnthropicClient 顺便把 `ANTHROPIC_BASE_URL` env 接进来（透传给 SDK，支持 OpenRouter Anthropic skin / 自部署 LiteLLM 代理）

### Why
- 为 V0.2.0 加 OpenAI client 做铺垫；按用户全局 CLAUDE.md「解耦优先」原则：domain (perceiver/trace) ← ports (llm/base.py) ← 业务层 (loop.py) ← 组合根 (cli.py)
- 中性 schema + per-provider 转换：避免业务工具语义重复定义在多个 client（SSOT）
- factory 在 `llm/__init__.py`：cli 仍是组合根，factory 是 llm 模块的「公开入口」

行为零变化（Anthropic 路径完全等价；新加的 OpenAI 分支在 C2 实现，C1 阶段 import 时友好报错）。pytest 7/7 通过（原 2 个 actuator + 新 5 个 schema 转换）。

## [0.1.1] - 2026-05-01

### Refactored
- `loop.py::_find_mark`: for-loop → `next(generator, None)`（5 行 → 1 行）
- `loop.py::run_react_loop`: 合并 `done` 分支与底部统一的 `Step` 写入路径，去掉 10 行重复构造（`done` 分支只设 `obs=result`，落到统一 write_step 后用 `if action.type == "done"` 收尾 end_task）

行为零变化：done 路径仍写一次 Step、调一次 end_task、返回同样 result。pytest 2/2 仍绿。

### Why
- 由 simplify subagent 触发的代码质量审查；其余 simplify 候选（jitter_sleep helper、_env_int helper、Action enum 等）经评估属过度抽象未采纳

## [0.1.0] - 2026-05-01

### Added
- 项目骨架：`src/web_agent/{browser,perceiver,actuator,planner,loop,trace,cli}.py`
- Playwright 1.59 async + playwright-stealth 2.0.3 + Anthropic SDK 0.97 接入
- Set-of-Mark (SoM) JS 注入实现：枚举 `a/button/input/textarea/select/[role]`，给每个加彩色边框 + 数字 ID
- 拟人 actuator W1 占位实现：直线鼠标 (15-25 steps) + 80-200ms 键入抖动 + 2.5s 思考延迟 + 中心点 ±5px jitter
- ReAct loop：max_steps + Action Trace (deque maxlen=20) + 每步 5 工具 (click/type/scroll/extract/done)
- SQLite 持久化每步截图 + thought + action + observation，可 replay
- Anthropic 调用启用 prompt caching（system prompt 末尾标 ephemeral）+ tool-use 强制结构化输出
- W1 demo: `demos/wikipedia_search.py` 在中文 Wikipedia 搜词条 + 提取首段
- `scripts/start_chrome.sh` 启动带 9222 调试端口的本地 Chrome（独立 user-data-dir）
- 技术蓝本归档：`docs/高度模仿人操作网页的agent技术路径图.txt`
- `tests/test_actuator.py` 占位单元测试（_click_point jitter 边界）

### Why
- **视觉 SoM 路线**优于纯 a11y tree（对 canvas / Shadow DOM / 动态渲染更鲁棒，且能直接喂 Claude vision）
- **接管本地 Chrome** 而非 launch 隔离 Chromium：保留用户登录态、Cookies、已装扩展
- **W1 拟人精度占位**（直线鼠标 + 简单抖动）：避免在 loop 通顺前过早优化；Wikipedia 不反 bot
- **uv + hatchling** 而非 setuptools：现代标准，pyproject.toml 单文件管 deps + dev-deps + build
- **playwright-stealth 而非 patchright**：当前 connect_over_cdp 模式下 patchright 的 build-time 二进制改造用不上；以后切独立 Chromium 时再换

### Next
- W2: GitHub demo + 拟人精度升级（3 阶贝塞尔 + 正态键入 + 偶尔纠错回退）
- W3: 登录态场景 + `safety.py` 授权白名单 UI
- W4: 多步任务 replay 面板 + Cloudflare Turnstile 接管 UI
