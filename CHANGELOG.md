# Changelog

All notable changes to web-agent. 版本号遵循 SemVer 简化形式（V<major>.<minor>.<patch>）。

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
