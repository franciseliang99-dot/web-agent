# web-agent

MultiOn 风格的「高度模仿人操作网页」AI web agent。

技术路径以 [`docs/高度模仿人操作网页的agent技术路径图.txt`](docs/高度模仿人操作网页的agent技术路径图.txt) 为蓝本（用户原文档）。

## 当前状态

V0.12.4 (2026-05-03) — 35+ commits, 148 tests passing

**W milestone 进度**:
- W1 ✅ Wikipedia 搜词条 + 提取首段 (骨架 + 多 LLM 支持)
- W2 ✅ GitHub 搜 repo + 拟人 actuator (3 阶贝塞尔 + smootherstep + 正态键入 + typo+backspace)
- W3 ✅ Gmail 登录态: read-only 总结 (W3-B) + compose 写操作 (W3-C) + `safety.py` 授权白名单 (W3-A)
- W4 ✅ replay 日志面板 (W4-1) + index 索引页 (W4-1.1) + Cloudflare/reCAPTCHA 暂停接管 UX (W4-2) + 桌面通知 (W4-3)
- W5 部分 ✅ — 自反思 page-stuck hint (W5-A) + Shadow DOM 穿透 (W5-B); W5-C 分层规划 / W5-D 长期记忆 未启动

## 栈

- Python 3.12 + Playwright 1.59 async
- 接管用户本地 Chrome（`--remote-debugging-port=9222`）— 不 launch 隔离 Chromium，保留登录态/Cookies/扩展
- Anthropic Claude Sonnet 4.6（vision）+ prompt caching；OpenAI / Kimi / OpenRouter 同 Protocol 接入
- Set-of-Mark (SoM) 截图 JS 注入 + Shadow DOM 穿透 (V0.12.0) + cookie/GDPR 弹窗自动关 (V0.5.1)
- 拟人 actuator (3 阶贝塞尔 + smootherstep + 截断正态键入 + typo+backspace + 鼠标连贯落点)
- ReAct loop + Action Trace (deque maxlen=20) + SQLite 持久化 + 单文件 HTML replay 面板
- 安全/反思双层防御: `safety.py` 白名单拦 send/pay/delete + V0.5.0 anti-loop 同 action 3 次硬 abort + V0.11.0 自反思页面 3 步无变化软提示

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

脚本默认 `CHROME_MODE=auto`，按环境自选：

| 环境 | 自动选 | 说明 |
|---|---|---|
| 装了 `xvfb` | **xvfb**（推荐）| 虚拟 X server，Chrome 拿到的所有 API 与有界面一致，符合反爬"非 headless"偏好 |
| 设了 `$DISPLAY`（本机 GUI / `ssh -X`）| headed | 有界面 Chrome |
| 都没（SSH 无 GUI 裸服）| **headless** | `--headless=new`，零依赖，能跑普通站；CDP 指纹仍可被 Cloudflare/DataDome 识别 |

显式覆盖：`CHROME_MODE=xvfb bash scripts/start_chrome.sh`（或 `headless`/`headed`）。

**SSH headless server 推荐**：先 `sudo apt install xvfb`，之后 auto 自动升级到 xvfb；不想装也行，默认 fallback 到 `--headless=new` 跑普通站没问题。

终端 B — 跑 demo：

```bash
uv run python demos/wikipedia_search.py "量子纠缠"
```

或直接用 CLI：

```bash
# 跑 task
uv run web-agent "在维基百科搜量子纠缠并提取首段" --url https://zh.wikipedia.org/

# replay 面板 (V0.8.0 W4-1 + V0.12.2 W4-1.1)
uv run web-agent-replay              # 渲染最新一次 task → data/replays/<task_id>.html
uv run web-agent-replay <task_id>    # 渲染指定 task
uv run web-agent-replay --all        # 渲染 DB 全部 task + index.html 索引页 (按 started DESC)
xdg-open data/replays/index.html     # 浏览器打开
```

## 路线图

- W1 ✅ / W2 ✅ / W3 ✅ / W4 ✅ — 详见 [`CHANGELOG.md`](CHANGELOG.md)
- W5-A 自反思 page-stuck soft hint ✅ (V0.11.0)
- W5-B Shadow DOM 穿透 ✅ (V0.12.0)
- W5-C 分层规划 (subgoal split + replan) — 未启动
- W5-D 长期记忆 (cross-session episodic store) — 未启动

**已知缺口** (不在 W5 路线但需追):
- patchright-python 决断 (仍用 `playwright-stealth` 2.0.3, 未实测 Cloudflare 突破率)
- 住宅代理 + curl_cffi TLS 指纹接入
- Gmail 真账号端到端验收 (CI 不发邮件; W3-C demo 需用户 `WEB_AGENT_TEST_RECIPIENT` 真投)

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

## 行为开关 (env 变量)

按类别分组, 默认值适合大多数场景:

```bash
# === Safety / 弹窗 ===
WEB_AGENT_AUTO_APPROVE=        # 默认空 (拦 send/pay/delete); 设规则名 CSV 放行 (e.g. "send-or-pay")
                                # 或 "*" 全开 (生产慎用); 规则见 src/web_agent/safety.py
WEB_AGENT_AUTO_DISMISS=true    # cookie/GDPR/notification 弹窗自动关 (V0.5.1; 黑名单含 password/pay 保护)

# === Captcha 接管 UX (W4-2) ===
WEB_AGENT_CAPTCHA_DISABLE=     # 默认空 (开); true/1/yes 退化到 V0.8.x light-DOM-only 行为
WEB_AGENT_CAPTCHA_TIMEOUT_S=300  # 用户在浏览器手解 captcha 超时秒数
WEB_AGENT_CAPTCHA_POLL_S=3       # 每隔几秒重检 captcha 是否清除

# === Perception (V0.12.0 W5-B) ===
WEB_AGENT_SOM_SHADOW=true      # SoM 走 open shadowRoot 穿透; false 退化到 V0.11.x light-DOM-only
WEB_AGENT_AUTO_DISMISS=true    # (见上)

# === Notify (W4-3) ===
WEB_AGENT_NOTIFY_DISABLE=      # 默认空 (开); true 关桌面通知 (CI/headless/不想被打扰)

# === Reliability ===
WEB_AGENT_MAX_WALLCLOCK_S=300  # 单 task 硬超时 (避 SDK retry + perceive 累积超过 max_steps × 平均步耗)
WEB_AGENT_CDP_URL=http://127.0.0.1:9222  # 接管的 Chrome 调试端口

# === Demo 专用 ===
WEB_AGENT_TEST_RECIPIENT=      # gmail_compose demo 收件人 (W3-C, 强烈建议自己发给自己)
```

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
  __init__.py      # __version__
  browser.py       # CDP 接管本地 Chrome + stealth
  perceiver.py     # SoM JS 注入 + Shadow DOM 穿透 + 弹窗自动关
  actuator.py      # 拟人 click/type/scroll (3 阶贝塞尔 + 正态键入)
  loop.py          # ReAct + safety + captcha + 反思 + anti-loop + trace
  trace.py         # SQLite 持久化 + Step/Trace dataclass
  safety.py        # W3-A 授权白名单 (send/pay/delete/敏感字段)
  captcha.py       # W4-2 Cloudflare/reCAPTCHA/hCaptcha 检测 + 暂停 UX
  notify.py        # W4-3 桌面通知 (osascript / notify-send)
  replay.py        # W4-1/W4-1.1 replay HTML 面板 + 索引页
  cli.py           # 组合根 + web-agent / web-agent-replay entry
  llm/             # 跨 provider Protocol (anthropic / openai / Kimi 兼容)
demos/
  wikipedia_search.py    # W1
  github_search.py       # W2-B
  gmail_summary.py       # W3-B (read-only)
  gmail_compose.py       # W3-C (write, safety 拦 Send 默认 abort)
scripts/
  start_chrome.sh  # 启动 9222 调试端口的独立 Chrome (auto/xvfb/headed/headless)
tests/             # 148 case, 13 文件 (含 audit gap 填补 trace/perceiver)
docs/
  高度模仿人操作网页的agent技术路径图.txt  # 用户原始技术蓝本
data/
  trace.db                 # SQLite (gitignored)
  screenshots/             # 每步截图 (gitignored)
  replays/                 # web-agent-replay 输出 HTML (gitignored)
```

## CHANGELOG

见 [`CHANGELOG.md`](CHANGELOG.md)。
