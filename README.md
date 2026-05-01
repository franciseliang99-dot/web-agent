# web-agent

MultiOn 风格的「高度模仿人操作网页」AI web agent。

技术路径以 [`docs/高度模仿人操作网页的agent技术路径图.txt`](docs/高度模仿人操作网页的agent技术路径图.txt) 为蓝本（用户原文档）。

## 当前状态

V0.2.0 (2026-05-01) — 骨架 + Wikipedia W1 demo + 多 LLM 支持 (Anthropic / OpenAI)

## 栈

- Python 3.12 + Playwright 1.59 async
- 接管用户本地 Chrome（`--remote-debugging-port=9222`）— 不 launch 隔离 Chromium，保留登录态/Cookies/扩展
- Anthropic Claude Sonnet 4.6（vision）+ prompt caching
- Set-of-Mark (SoM) 截图 JS 注入 + DOM 瘦身
- 拟人 actuator（W1 占位实现 → W2 升级到 3 阶贝塞尔 + 正态键入）
- ReAct loop + Action Trace（deque maxlen=20）+ SQLite 持久化

## 安装

```bash
cd /home/myclaw/web-agent
uv sync
uv run playwright install chromium  # stealth 库可能需要本地 Chromium 做兜底
cp .env.example .env
# 编辑 .env，填 ANTHROPIC_API_KEY
```

## 跑 W1 demo

终端 A — 启动带调试端口的 Chrome（独立 user-data-dir，不污染日常 profile）：

```bash
bash scripts/start_chrome.sh
```

终端 B — 跑 demo：

```bash
uv run python demos/wikipedia_search.py "量子纠缠"
```

或直接用 CLI：

```bash
uv run web-agent "在维基百科搜量子纠缠并提取首段" --url https://zh.wikipedia.org/
```

## 路线图

- **W1（本周）**: Wikipedia 搜词条 + 提取首段 ✅ 骨架
- **W2**: GitHub 搜 repo + 看 README; 拟人精度升级（3 阶贝塞尔 + 正态键入 + 偶尔纠错）
- **W3**: 登录态场景（Gmail 总结）+ 授权确认 UI（`safety.py` 白名单：付款/发件/密码/DELETE）
- **W4**: 多步真实任务 + replay 日志面板 + Cloudflare Turnstile 接管 UI

## BYO LLM API key

通过 `LLMClient` Protocol 支持多 provider，按 env 选：

```bash
# === Anthropic Claude（默认）===
ANTHROPIC_API_KEY=sk-ant-...
WEB_AGENT_MODEL=claude-sonnet-4-6      # 可选

# === OpenAI GPT（先装可选依赖）===
# uv sync --extra openai
OPENAI_API_KEY=sk-...
WEB_AGENT_LLM_PROVIDER=openai          # 显式指定，或省略让 model 名前缀自动推断
WEB_AGENT_MODEL=gpt-5.5                 # 或 gpt-4o / o3-vision...

# === 走代理（OpenRouter / 自部署 LiteLLM / Azure OpenAI）===
ANTHROPIC_BASE_URL=https://openrouter.ai/api
ANTHROPIC_API_KEY=sk-or-v1-...        # OpenRouter key
WEB_AGENT_MODEL=anthropic/claude-sonnet-4.6
# 或 OpenAI 风格代理
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-v1-...
WEB_AGENT_LLM_PROVIDER=openai
WEB_AGENT_MODEL=openai/gpt-4o

# === Kimi / Moonshot (OpenAI compat) ===
# 国际版 https://platform.kimi.ai
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.moonshot.ai/v1
WEB_AGENT_MODEL=kimi-k2.6              # 自动推断 provider=openai
# 国内版 https://platform.moonshot.cn 用 https://api.moonshot.cn/v1
```

OpenAIClient 会按 `base_url` 自动检测 Kimi 兼容性补丁：
- `max_completion_tokens` → `max_tokens`（Kimi 不识 GPT-5.x 新参数名）
- `tool_choice="required"` → `"auto"`（Kimi 拒 required）
- 单步成本（kimi-k2.6, ~3k input + 200 output）：cache miss ≈ $0.004，cache hit ≈ $0.001（自动 cache，6× 折扣）

CLI 也可临时覆盖：

```bash
uv run web-agent "..." --provider openai --model gpt-5.5
```

provider 自动推断规则（`provider_from_model`）：
- `claude-*`, `anthropic/*` → anthropic
- `gpt-*`, `o[1-5]-*`, `openai/*` → openai
- `gemini-*` → gemini（暂未实现 client，留扩展位）
- 其他 → 默认 anthropic

## 反检测层（按需升级）

W1 用 `playwright-stealth` 2.0.3。如果碰到 Cloudflare/Datadome/Akamai：

1. 先尝试切 [`patchright-python`](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python)（2026 SOTA），但需改用 `launch_persistent_context` + patchright 的特殊 Chromium，放弃 connect_over_cdp（失去用户登录态）
2. 仍不够再上住宅代理 + TLS 指纹（curl_cffi）
3. 验证码不接 2Captcha 自动绕（越线），用「暂停 → 弹窗让用户解 → 恢复循环」UX

## 法律边界

- ✅ 操作自己账号 / 自家网站 / 公开数据 / 个人辅助
- ❌ 反 ToS 抓取 / 撞库 / 刷票 / 绕 reCAPTCHA 抓商业站

## 目录

```
src/web_agent/
  __init__.py     # __version__ = "0.1.0"
  browser.py      # CDP 接管本地 Chrome + stealth
  perceiver.py    # SoM JS 注入 + 截图 + DOM 瘦身
  actuator.py     # 拟人 click/type/scroll（W1 占位）
  planner.py      # Anthropic vision + prompt caching + tool-use
  loop.py         # ReAct max_steps + Action Trace
  trace.py        # SQLite 持久化每步截图/思考/行动
  cli.py          # 组合根 + entry point
demos/
  wikipedia_search.py
scripts/
  start_chrome.sh  # 启动 9222 调试端口的独立 Chrome
tests/
  test_actuator.py
docs/
  高度模仿人操作网页的agent技术路径图.txt  # 用户原始技术蓝本
data/
  trace.db                 # SQLite (gitignored)
  screenshots/             # 每步截图 (gitignored)
```

## CHANGELOG

见 [`CHANGELOG.md`](CHANGELOG.md)。
