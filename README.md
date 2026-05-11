# web-agent

[![CI](https://github.com/franciseliang99-dot/web-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/franciseliang99-dot/web-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](pyproject.toml)
[![tests](https://img.shields.io/badge/tests-769_passed-green.svg)](tests/)
[![mypy strict](https://img.shields.io/badge/mypy-strict_0_errors-blue.svg)](pyproject.toml)
[![CHANGELOG](https://img.shields.io/badge/CHANGELOG-V0.34.0-orange.svg)](CHANGELOG.md)

## 📝 Featured Blogs (3 篇系列, 全部 web-agent dogfooding publish)

1. **[50% Compliance, Not 0%: How a Logging Spike Almost Triggered the Wrong Architecture Rewrite](https://dev.to/francise_liang_e4544eadb9/50-compliance-not-0-how-a-logging-spike-almost-triggered-the-wrong-architecture-rewrite-1lna)** — dev.to · 8 min read
   测量层故事: W5-C.2 spike 7 版本闭环 regex 假阴性差点引发错误架构重写 (V0.16.27 dogfooding).

2. **[Why I Permanently NO-GO'd Patchright After a Spike (And the Anti-Detection Decision Tree)](https://dev.to/francise_liang_e4544eadb9/why-i-permanently-no-god-patchright-after-a-spike-and-the-anti-detection-decision-tree-3m11)** — dev.to · 7 min read
   架构层故事: V0.16.14 patchright spike NO-GO + V0.16.15 curl_cffi NO-GO + 反检测决策树 4 层选择 (V0.16.30 dogfooding).

3. **[Build Time vs Edit Time — My Web Agent Can Publish But Can't Edit (An Honest Capability-Boundary Spike)](https://dev.to/francise_liang_e4544eadb9/build-time-vs-edit-time-my-web-agent-can-publish-but-cant-edit-an-honest-capability-boundary-4lpl)** — dev.to · 6 min read
   工具边界故事: V0.16.31 dogfooding 4/5 = 80% 成功率, edit existing article 触发 V0.5.0 anti-loop 暴露 actuator 5 actions 边界 (V0.16.32 dogfooding 第 4 次 publish 自身博客).

---

**MultiOn 风格的高度拟人 Web Agent — Python + Playwright + VLM/SoM + stealth, BYO LLM (Anthropic/OpenAI/Kimi)**.

接管你**已登录的 Chrome**（不 launch 隔离 Chromium，保留 cookies/扩展/profile），通过 Set-of-Mark 视觉标注 + Anthropic Claude Sonnet 4.6 vision tool calling 完成「自然语言任务 → 真浏览器操作」闭环。

支持 4 路集成: **MCP server (stdio)** / **CLI** / **Python import** / **Claude Desktop** — 见下方"用法"。

技术路径以 [`docs/高度模仿人操作网页的agent技术路径图.txt`](docs/高度模仿人操作网页的agent技术路径图.txt) 为蓝本（用户原文档）。

## 项目特色

🧠 **决策驱动的 spike 闭环**：每次反检测/规划方案前先跑 spike 拿数据再决断，不"看似有用就实施"。代表性闭环:
- **patchright-python NO-GO** (V0.16.14) — sannysoft.com A=C 19/57 实测证伪 + ARCHITECTURE §1.3 永久落档
- **curl_cffi NO-GO** (V0.16.15) — Chrome 已是真 BoringSSL，curl_cffi 旁路在浏览器路径完全无用
- **W5-C.2 真 plan-and-execute DEFER** (V0.16.16-22, 7 版本闭环) — augmentation 路线 50% compliance 数据底座 + ARCHITECTURE §1.5 决策矩阵

📊 **可观测**：每步截图 + 思考 + 行动 → SQLite 持久化 → 单文件 HTML replay 面板；跨 session 长期记忆 (domain ↔ past goals/results, V0.13.0+)。

🛡 **三层 release gate**：ruff 0 + mypy strict 0 + pytest 769 passed + 18 skipped 全绿 + GitHub Actions CI (V0.16.13)。

🤝 **MCP server (V0.16.0-9 + V0.18 elicit + V0.29.2 chain)**：4 tools (`web_agent_run` / `_get_replay` / `_query_memory` / `_run_chain`) + 2 resources + progress 心跳 + asyncio.Lock 串行 + 9222 健康检查 + V0.18.0 `ctx.elicit()` 人在回路 safety 批准。Claude Desktop 加 2 行 config 即用。

## 当前状态

**V0.34.0** (2026-05-11) — 189 commits, **769 tests passed + 18 skips** (含 chromium slow smoke 15/15 全过), 3 层 release gate 全绿, GitHub Actions CI 自动跑.

**W milestone 进度**:
- W1 ✅ Wikipedia 搜词条 + 提取首段 (骨架 + 多 LLM 支持)
- W2 ✅ GitHub 搜 repo + 拟人 actuator (3 阶贝塞尔 + smootherstep + 正态键入 + typo+backspace)
- W3 ✅ Gmail 登录态: read-only 总结 (W3-B) + compose 写操作 (W3-C, V0.16.17 真账号 E2E 实测通过) + `safety.py` 授权白名单 (W3-A)
- W4 ✅ replay 日志面板 (W4-1) + index 索引页 (W4-1.1) + Cloudflare/reCAPTCHA 暂停接管 UX (W4-2) + 桌面通知 (W4-3)
- W5 ✅ — 自反思 page-stuck hint (W5-A) + Shadow DOM 穿透 (W5-B) + 跨 session 长期记忆 (W5-D) + memory inject planner (W5-D.2) + 分层规划 augmentation (W5-C) + W5-C.2 真 plan-and-execute spike 闭环维持 DEFER (V0.16.16-22)
- W6 ✅ — V0.28 `reflect_on_failure` 跨 task LLM 反思 (W6-A/B, 触发 max_steps + LOOP_DETECTED, root_cause+hint 结构化输出) + V0.29 W6-C 长 task chain DAG 编排 (ChainSpec / topo sort / on_failure abort|continue / `${node.result}` substitute_vars + `web-agent-chain` CLI + MCP `web_agent_run_chain` tool)
- E ✅ (V0.33 性能优化系列, 5 commit 闭环) — token baseline 框架 + SoM 字段 lean mode opt-in + screenshot WebP opt-in
- F ⏳ (V0.34.0 开篇 1/x) — perceive() bench harness framework (eval/perceive_bench.py + `web-agent-perceive-bench` CLI, 真跑 chromium adapter 留 V0.34.1+)

**MCP server (V0.16.0-9 + V0.18 + V0.29.2)** ✅: stdio + **4 tools** (`web_agent_run` / `web_agent_get_replay` / `web_agent_query_memory` / `web_agent_run_chain`) + 2 resources (`webagent://replay/<id>` / `webagent://memory/<domain>`) + progress wire + asyncio.Lock + 健康检查 + V0.18.0 `ctx.elicit()` 人在回路 safety 批准 (V0.18.2 真账号 dogfood 验证) + ARCHITECTURE §5 完整文档化.

**Audit gap 收尾 (6/6 全)**: perceiver (V0.12.0) / trace (V0.12.4) / cli (V0.12.6) / loop 主体 (V0.12.8) / browser (V0.15.1) / anthropic (V0.15.1).

**V0.17 ~ V0.34 新增能力概览**: V0.17 Action discriminated union (5 dataclass) → V0.19 +keyboard_shortcut/paste (7) → V0.21 +switch_tab/close_tab (9) → V0.23 +drag/upload + download listener (11 actions); V0.18 MCP elicit 人在回路 batch confirm; V0.20 / V0.20.6 Upwork JD 抽取 (`web-agent-jd` / `web-agent-list-jds`); V0.22 iframe perceive (Mark.frame_path 同源穿透); V0.24 dialog auto-handle (alert/confirm/prompt/beforeunload); V0.25 transient retry budget (RateLimit/Timeout/5xx 同 step 重 perceive); V0.26 eval golden corpus (`web-agent-eval` + 16 task + capability axis); V0.27 vault SecretStore Protocol; V0.28 W6-A/B reflect_on_failure 跨 task LLM 反思; V0.29 W6-C 长 task chain DAG 编排 (ChainSpec / topo / on_failure / substitute_vars / `web-agent-chain` + MCP `web_agent_run_chain` tool); V0.30 stealth_plus (webdriver/WebGL/permissions); V0.31 keyring 真实现 (opt-in `pip install web-agent[keyring]` + `web-agent-vault` CLI); V0.33 E 性能优化 (token baseline 框架 + SoM lean mode + WebP opt-in); V0.34 F perceive bench harness framework (`web-agent-perceive-bench` CLI).

**架构决策**: 见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 决策树 / 模块边界 / 三轨同道 (reflect/memory/subgoal 共用 trace 通道) / 双层防御 (safety+anti-loop+reflect+captcha 信号正交) / W5-C.2 spike 7 版本闭环 verdict.

## 栈

- Python 3.12 + Playwright 1.59 async
- 接管用户本地 Chrome（`--remote-debugging-port=9222`）— 不 launch 隔离 Chromium，保留登录态/Cookies/扩展。V0.16.18 起 `start_chrome.sh` 也支持 Chromium 系 fork: Brave / Edge / Vivaldi / Opera (CDP 协议零差异), 或 `CHROME_BIN=/path/to/...` env 覆盖. Firefox/Safari 不支持 (协议不同 + 走 launch 模式会丢登录态), 详见 ARCHITECTURE §1.1
- **V0.16.19 auto-spawn Chrome**: 9222 不可达时 cli/mcp_server 自动 `subprocess.Popen scripts/start_chrome.sh` (start_new_session=True, exit 不杀), 用户不必先启 Chrome — `WEB_AGENT_AUTO_SPAWN_CHROME=false` 关. 首登 Gmail 仍需 headed 模式手登一次
- Anthropic Claude Sonnet 4.6（vision）+ prompt caching；OpenAI / Kimi / OpenRouter 同 Protocol 接入
- Set-of-Mark (SoM) 截图 JS 注入 + Shadow DOM 穿透 (V0.12.0) + cookie/GDPR 弹窗自动关 (V0.5.1)
- 拟人 actuator (3 阶贝塞尔 + smootherstep + 截断正态键入 + typo+backspace + 鼠标连贯落点) — 11 个 Action: click / type / scroll / **keyboard_shortcut + paste** (V0.19) / **switch_tab + close_tab** (V0.21) / **drag + upload + download listener** (V0.23) / extract / done; 跨 iframe 定位 (V0.22 Mark.frame_path 同源穿透)
- ReAct loop + Action Trace (deque maxlen=20) + SQLite 持久化 + 单文件 HTML replay 面板 + V0.24 dialog auto-handle (alert/confirm/prompt/beforeunload) + V0.25 transient retry budget (RateLimit/Timeout/5xx 同 step 重 perceive)
- 安全/反思双层防御: `safety.py` 白名单拦 send/pay/delete + V0.5.0 anti-loop 同 action 3 次硬 abort + V0.11.0 自反思页面 3 步无变化软提示

## 安装 + 上手 (3 步, V0.16.19+ auto-spawn)

```bash
# 1. 装包 + 浏览器
cd web-agent
uv sync
uv run playwright install chromium

# 2. 配 API key (二选一: Anthropic 默认 / OpenAI / Kimi)
cp .env.example .env
# 编辑 .env: ANTHROPIC_API_KEY=sk-ant-xxx

# 3. 跑 demo (Chrome 9222 不可达自动 spawn, 不必先开终端启 Chrome)
uv run python demos/wikipedia_search.py "量子纠缠"
```

V0.16.19 auto-spawn Chrome: cli 与 mcp_server 在 connect 前都 `subprocess.Popen scripts/start_chrome.sh`（`start_new_session=True`，exit 不杀），用户**不必先启 Chrome**。env `WEB_AGENT_AUTO_SPAWN_CHROME=false` 关。

`scripts/start_chrome.sh` 默认 `CHROME_MODE=auto`：装了 `xvfb` → xvfb / 有 `$DISPLAY` → headed / 都无 → `--headless=new`。SSH 裸服推荐 `apt install xvfb` 升级到 xvfb 提升反爬通过率。

V0.16.18 起 `start_chrome.sh` 自动检测 11 个 Chromium 系 binary：Chrome / Chromium / **Brave / Edge / Vivaldi / Opera**，或 `CHROME_BIN=/path/to/...` env 覆盖。Firefox/Safari 不支持 (协议不同 + 走 launch 模式丢登录态)。

## 4 种集成方式

| 方式 | 适用 | 命令 |
|---|---|---|
| **MCP server (stdio)** | Claude Desktop / Cursor / Continue | `web-agent-mcp` (见下方 config) |
| **CLI** | 任意 shell / Node / 跨语言 | `uv run web-agent "..."` |
| **Python import** | 同 venv Python agent | `from web_agent.cli import run_task` |
| **demos** | 学用法 / 参考实现 | `uv run python demos/<name>.py "..."` |

### CLI

```bash
# 跑 task
uv run web-agent "在维基百科搜量子纠缠并提取首段" --url https://zh.wikipedia.org/

# replay 面板 (V0.8.0 W4-1 + V0.12.2 W4-1.1)
uv run web-agent-replay              # 渲染最新一次 task → data/replays/<task_id>.html
uv run web-agent-replay <task_id>    # 渲染指定 task
uv run web-agent-replay --all        # 渲染 DB 全部 task + index.html 索引页 (按 started DESC)
xdg-open data/replays/index.html     # 浏览器打开
```

```bash
# memory dump (V0.13.0 W5-D 长期记忆) — 跨 session 同 domain 历史查询
uv run web-agent-memory github.com              # 默认 5 条
uv run web-agent-memory github.com --limit 10
uv run web-agent-memory wikipedia.org --db data/memory.db
# 输出: [2026-05-03T12:34:56] OK    搜 trending repo[:60]    ->    repo: x/y, stars: 1k[:80]
```

## 路线图

- W1 ✅ / W2 ✅ / W3 ✅ / W4 ✅ — 详见 [`CHANGELOG.md`](CHANGELOG.md)
- W5-A 自反思 page-stuck soft hint ✅ (V0.11.0)
- W5-B Shadow DOM 穿透 ✅ (V0.12.0)
- W5-D 长期记忆 cross-session episodic ✅ (V0.13.0 持久化 + CLI dump)
- W5-D.2 memory inject 到 planner 上下文 ✅ (V0.14.0)
- W5-C 分层规划 ✅ (V0.15.0, prompt augmentation 路线; 真 plan-and-execute = W5-C.2 **永久 DEFER**, V0.16.16 落档 — SDK 阻碍未解 (OpenAI/Kimi vision 不能零截图调用) + ROI 未量化, 触发条件 3 选 1: ① 用户反馈 augmentation 失败案例 ② OpenAI/Kimi 支持零 image vision ③ spike 证 plan-and-execute 失败率低 >20%, 详见 ARCHITECTURE §1.5)
- W6-A/B 跨 task `reflect_on_failure` ✅ (V0.28, root_cause+hint 结构化输出, max_steps + LOOP_DETECTED 触发)
- W6-C 长 task chain DAG 编排 ✅ (V0.29, ChainSpec yaml/dict + topo sort + on_failure abort|continue + `${node.result}` 数据流 + `web-agent-chain` CLI + MCP `web_agent_run_chain` tool, V0.29.2)
- E 性能优化系列 ✅ (V0.33, token baseline 框架 + SoM lean mode + WebP opt-in, 5 commit 闭环 V0.33.0-V0.33.4)
- F 感知 sub-route 优化系列 ⏳ (V0.34.0 perceive bench harness 开篇 1/x — eval/perceive_bench.py + `web-agent-perceive-bench` CLI, fixture/compare/stats subparser, 真跑 chromium adapter 留 V0.34.1+)

**MCP server** ✅ (V0.16.0 ~ V0.16.9 累计 10 commit, 已完整 ship):
- 暴露 web-agent 为 MCP server (Claude Desktop / 任意 MCP client 通过 tool 调用 `web_agent_run(goal, url)`)
- V0.16.0 ✅ 25 处 print → logger.info(stderr), 业务零改动 220 tests 全过
- V0.16.1 ✅ `mcp_server.py` 用官方 `mcp[cli]>=1.10` SDK 暴露 3 tools + asyncio.Lock 串行化 + Chrome 9222 健康检查 + 10 case test
- V0.16.4 ✅ progress_cb 真 wire mcp ctx → cli → loop 主循环 + captcha poll 心跳
- V0.16.6 ✅ Resources (`webagent://replay/<id>` HTML + `webagent://memory/<domain>` JSON 只读视图)
- V0.16.7 ✅ V0.16.6 Resources `/simplify` pass
- V0.16.8 ✅ ARCHITECTURE.md §5 MCP server 6 小节完整文档化
- V0.16.9 ✅ P1 解耦: `Mark`/`Action` 上提到 `web_agent.types`, 消除 safety/llm.base 反向依赖

**后续可选** (不阻塞主流程):
- ~~Elicitation 替代 `WEB_AGENT_AUTO_APPROVE` (人在回路批准)~~ — V0.18.0 已 ship: safety 阻拦时 MCP server 走 `ctx.elicit()` 弹 client 询问 (Claude Desktop / Code 显式 yes/no), 用户拒绝/超时/旧 client 不支持 → 维持原 abort 行为 (安全 default). env `WEB_AGENT_AUTO_APPROVE=*` 仍优先 (向后兼容 + dev 快速迭代). **V0.18.2 真账号 dogfooding 已验**: Claude Code 2.1.137 双路径通过 (Run A decline → SAFETY_BLOCK / Run B accept → 真 click + trace `elicited_approval_rule` 落档). UI 操作语义文档化见 CHANGELOG V0.18.2 (Esc 是 user-cancel 陷阱不是 decline)
- HTTP transport (替代 stdio, 便于远程 MCP client)

跑 MCP server (Claude Desktop config 加 entry):
```json
{
  "mcpServers": {
    "web-agent": {
      "command": "uv",
      "args": ["--directory", "/home/myclaw/web-agent", "run", "web-agent-mcp"]
    }
  }
}
```
Claude Desktop 重启后会出现 web_agent_run / web_agent_get_replay / web_agent_query_memory 三个 tool。

**safety 拦截时 elicit UI 操作** (Claude Code 2.1.137+ / 任意支持 elicitation 的 client):

碰到敏感动作 (send/publish/pay/delete/transfer/unsubscribe 等) 时, MCP server 调 `ctx.elicit()` 弹双层 UI:

    ❯ ✔ Approve: ☐                  ← schema 字段 (Space 切换 ☐/☑)
       Accept    Decline             ← form 提交 (Tab/Enter)

| 意图 | 操作 | 结果 |
|---|---|---|
| **放行** | Space 勾 ☑ + `Accept` | 真 click 继续, trace 标记 `elicited_approval_rule` |
| **拦截** | `Decline` (checkbox 无关) | task SAFETY_BLOCK abort |
| **拦截 (等价)** | ☐ 不勾 + `Accept` | 同上 |
| ⚠️ **不要 Esc** | Esc | MCP error -32001 user-cancel, tool fail + trace 半死. 要拦截请用 `Decline` |

V0.18.2 真账号 dogfooding e2e 双路径已验, 详见 CHANGELOG V0.18.2.

**已知缺口** (不在主蓝本但需追):
- ~~patchright-python 决断~~ — V0.16.14 spike 实测关闭: `connect_over_cdp` 接管模式下 patchright 的 client patch 旁路 (A=C 19/32 完全相同), 仅在 launch_persistent_context 模式才有效 → 与项目 CDP 接管核心架构冲突, 永久 NO-GO. 详见 ARCHITECTURE §1.3
- ~~curl_cffi TLS 指纹接入~~ — V0.16.15 永久 NO-GO: web-agent 接管真 Chrome, 所有浏览流量走 Chrome 自己的 BoringSSL = 真 Chrome JA3/JA4, curl_cffi 在浏览路径完全没用 (LLM API 端点不做反爬也用不上). W6+ 若引入"Python 直发 HTTP 旁路"才重评估. 详见 ARCHITECTURE §1.3
- **住宅代理** (Cloudflare/DataDome 命中后启用): 与 connect_over_cdp 完全兼容 — `scripts/start_chrome.sh` ARGS 加 `--proxy-server=`, 候选 IPRoyal $7/GB / Smartproxy $8.5/GB. 坑: Chrome `--proxy-server=` 不支持 user:pass 内联凭证, 需 IP whitelist 模式
- ~~Gmail 真账号端到端验收~~ — V0.16.17 已实测通过: 用户本地 9222 Chrome (登录态在 user-data-dir) + `WEB_AGENT_TEST_RECIPIENT` + `WEB_AGENT_AUTO_APPROVE='*'` 跑 `demos/gmail_compose.py`, LLM 真完成 compose 流程, safety auto_approve 放行 Send, 邮件真发到 inbox. 跑法见 README "跑 W3 demo" 段
- **真实 LLM smoke + cassette** (V0.15.3 + V0.15.5 双骨架已落, Anthropic + OpenAI(Kimi 国内版 .cn) 两路径):
  ```bash
  cd /home/myclaw/web-agent  # 必须在项目根, 不然 pytest-recording plugin 不注册

  # Anthropic 路径 (V0.15.3)
  ANTHROPIC_API_KEY=sk-ant-xxx uv run pytest tests/test_smoke_anthropic_real.py --record-mode=once

  # OpenAI/Kimi 国内版路径 (V0.15.5, platform.moonshot.cn 真 key, 不要用 sk-xxx 占位会录到 401)
  OPENAI_API_KEY=sk-真key uv run pytest tests/test_smoke_openai_kimi_real.py --record-mode=once

  git add tests/cassettes/  # cassette header 已 filter, 无 key 泄漏
  ```
  之后任何人/CI 无 key 也能跑 (走 cassette replay)。单录成本: Anthropic ≈ $0.006 / Kimi ≈ ¥0.03 (~$0.004)。
  Kimi 国际版 .ai 端点骨架待 V0.15.6+ (改 `_KIMI_BASE_URL` 重录或加双骨架)。
  GPT 骨架 V0.15.8 已落, 录命令:
  ```bash
  # 注意必须显式 OPENAI_BASE_URL 防 .env 里 moonshot.cn 劫持
  OPENAI_BASE_URL=https://api.openai.com/v1 OPENAI_API_KEY=sk-真OpenAI \
    uv run pytest tests/test_smoke_openai_gpt_real.py --record-mode=once
  ```
  OpenRouter / Azure / Bedrock 路径骨架待 V0.16.0+, 同 helper 模板可补
- **SYSTEM_PROMPT snapshot test** (撤): subagent 审核反对 — 7 条规则文案微调本就常见, snapshot 锁会每次改文案都更新 cassette → false positive 噪音 > 真回归捕获价值。`test_llm_schema.py` 已锁工具数+name 集+required 字段, 够用; 改 SYSTEM_PROMPT 走 review 而非自动测

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

# === Memory (V0.13.0 W5-D) ===
WEB_AGENT_MEMORY_DISABLE=      # 默认空 (开); true 关跨 session task outcome 持久化
WEB_AGENT_MEMORY_DB=data/memory.db  # 自定义 memory db 路径 (默认 data/memory.db)

# === Reliability ===
WEB_AGENT_MAX_WALLCLOCK_S=300  # 单 task 硬超时 (避 SDK retry + perceive 累积超过 max_steps × 平均步耗)
WEB_AGENT_CDP_URL=http://127.0.0.1:9222  # 接管的 Chrome 调试端口

# === Dialog (V0.24.0) ===
WEB_AGENT_DIALOG_POLICY=safe-defaults  # safe-defaults (alert/beforeunload accept; confirm/prompt dismiss)
                                       # | auto-accept | auto-dismiss

# === Smart Retry (V0.25.0) ===
WEB_AGENT_TRANSIENT_RETRY_MAX=3        # RateLimit/Timeout/5xx 同 step 重 perceive 上限; 0 关回退 V0.24.2

# === Vault (V0.27.1 + V0.31.0) ===
WEB_AGENT_USE_KEYRING=                 # V0.31.2 opt-in 切 [Keyring, Env] 链; 默 EnvSecretStore
                                       # 需 pip install web-agent[keyring]

# === Perception 性能 (V0.33 E 系列) ===
WEB_AGENT_SOM_FIELDS=                  # "lean" 砍 href 等字段 (~16k tok/run 估省); 默 full 兼容 V0.32.x
WEB_AGENT_SCREENSHOT_FORMAT=png        # "webp" 切 WebP (磁盘 -70%; 注: image tile 固定计费 token 不直减)
WEB_AGENT_SCREENSHOT_QUALITY=75        # WebP lossy [1, 100]

# === Demo 专用 ===
WEB_AGENT_TEST_RECIPIENT=      # gmail_compose demo 收件人 (W3-C, 强烈建议自己发给自己)
```

## 反检测层（按需升级）

W1 用 `playwright-stealth` 2.0.3 + V0.16.14 起 SwiftShader GL flags（`scripts/start_chrome.sh`）。sannysoft.com 实测 ~72% 通过率。如果碰到 Cloudflare/Datadome/Akamai：

1. ~~切 patchright-python~~ — V0.16.14 spike 关闭，详见 ARCHITECTURE §1.3
2. **上住宅代理**（Chrome `--proxy-server=` flag, 与 connect_over_cdp 兼容）— 真正下一层防御。IP 信誉是 CF 第一道闸，Chrome 的真 TLS 指纹再像也救不了 DC IP 段
3. ~~curl_cffi TLS 指纹~~ — V0.16.15 NO-GO，Chrome 已是真 BoringSSL JA3/JA4，curl_cffi 在浏览路径无用，详见 ARCHITECTURE §1.3
4. 验证码不接 2Captcha 自动绕（越线），用「暂停 → 弹窗让用户解 → 恢复循环」UX（W4-2 V0.9.0 已实现）

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
  memory.py        # W5-D 跨 session 长期记忆 (domain → past goals/results, SQLite)
  cli.py                # 组合根 + 11 entry points (web-agent / -chain / -replay / -memory / -mcp / -vault / -jd / -list-jds / -eval / -token-baseline / -perceive-bench)
  mcp_server.py         # V0.16 MCP server (stdio, 4 tools + 2 resources + V0.18 elicit + V0.29.2 chain tool)
  chain.py              # V0.29 W6-C 长 task DAG 编排 (ChainSpec / topo / on_failure abort|continue / ${node.result} substitute_vars)
  reflect.py            # V0.28 W6-A/B reflect_on_failure 跨 task LLM 反思
  planner_hierarchy.py  # V0.15 W5-C 分层规划 augmentation
  vault.py              # V0.27/V0.31 SecretStore Protocol + Env/Keyring backend
  routing.py            # V0.27.2 per-task provider routing (数据驱动)
  jd_extract.py         # V0.20 Upwork JD 单 URL 抽 9 字段 (web-agent-jd)
  list_extract.py       # V0.20.6 Upwork list 页抽 JD URL (web-agent-list-jds)
  chrome_launcher.py    # V0.16.19 9222 auto-spawn 抽出
  types.py              # V0.16.9 + V0.17 Mark/Action 共享 dataclass (discriminated union)
  llm/                  # 跨 provider Protocol (anthropic / openai / Kimi 兼容)
eval/                   # V0.26 golden corpus + 评测框架
  types.py / predicates.py / runner.py / metrics.py / pricing.py / report.py
  cli.py                # web-agent-eval CLI (V0.26)
  token_baseline.py     # V0.33.0 token baseline (web-agent-token-baseline CLI)
  perceive_bench.py     # V0.34.0 F 系列开篇 perceive bench harness (web-agent-perceive-bench CLI)
  corpus/               # golden task fixture (16 task + capability axis)
demos/
  wikipedia_search.py    # W1
  github_search.py       # W2-B
  gmail_summary.py       # W3-B (read-only)
  gmail_compose.py       # W3-C (write, safety 拦 Send 默认 abort)
scripts/
  start_chrome.sh  # 启动 9222 调试端口的独立 Chrome (auto/xvfb/headed/headless)
tests/             # 769 passed + 18 skipped, 46 文件 (含 audit gap 6/6 + W5-D + W5-C + W5-C.2 spike + V0.17 Action / V0.19 actuator / V0.21 multi-tab / V0.22 iframe / V0.23 drag-upload / V0.24 dialog / V0.25 smart_retry / V0.26 eval / V0.27 vault / V0.28 reflect / V0.29 chain / V0.30 stealth_plus / V0.31 keyring / V0.33 token_baseline / V0.34 perceive_bench + Anthropic/Kimi/GPT 三骨架)
  conftest.py      # vcr_config 锁 cassette filter (V0.15.3)
  cassettes/       # vcrpy yaml (V0.15.3, .bak gitignored, 主 yaml 进 commit)
docs/
  高度模仿人操作网页的agent技术路径图.txt  # 用户原始技术蓝本
  ARCHITECTURE.md  # V0.16.22 架构决策 / 模块边界 / 三轨同道 / 双层防御 / W5-C.2 spike 7 版本闭环 verdict
data/
  trace.db                 # SQLite trace (gitignored)
  memory.db                # W5-D cross-session 长期记忆 (gitignored)
  screenshots/             # 每步截图 (gitignored)
  replays/                 # web-agent-replay 输出 HTML (gitignored)
```

## CHANGELOG

见 [`CHANGELOG.md`](CHANGELOG.md)。
