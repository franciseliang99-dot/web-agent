# Changelog

All notable changes to web-agent. 版本号遵循 SemVer 简化形式（V<major>.<minor>.<patch>）。

## [0.19.0] - 2026-05-08

### Add (actuator 扩 keyboard_shortcut + paste — 修 V0.16.31 + V0.18.5 spike-2 contenteditable edit fail mode)

V0.16.31 (dev.to 真账号编辑现有文章追加) + V0.18.5 spike-2 (contenteditable fixture 末尾追加) 累计 2 reproducible fail same root cause: actuator 5 actions (click/type/scroll/extract/done) 缺 keyboard chord + paste, 导致 LLM 在 contenteditable 反复 click 试光标定位 → anti-loop hard abort. V0.19.0 加 2 新 action 修复.

3 commit shape (V0.19.0a/b/c) 落档:

#### V0.19.0a (commit ac46627): types + safety data layer

- `types.py` 新增 `KeyboardShortcutAction(key: str)` + `PasteAction(text: str)` 2 dataclass (frozen+slots+Literal type 同 V0.17.0 模式)
- `Action` discriminated union 5 → 7
- `action_from_tool_call` factory 加 2 case (`keyboard_shortcut` / `paste`)
- `safety.py`: keyboard_shortcut 早 return list (无 useful safety signal, 一律放行); paste 同 type 复用敏感 input_type / name 检查 (新 rules `paste-into-sensitive-type` / `paste-into-sensitive-name`)
- `tests/test_safety.py`: +4 V0.19.0 测试 (paste-into-password / amount / search-allowed / kb_shortcut-always-allowed)

#### V0.19.0b (commit 6712c93): actuator + loop dispatch + LLM tool schema

- `actuator.py` 加 module logger + `human_like_keyboard_shortcut(page, key)`: 'Ctrl+...' → 'Control+...' normalize, `page.keyboard.press` chord syntax + 拟人化 think + 收尾停顿
- `actuator.py` 加 `human_like_paste(page, text)`: **`document.execCommand('insertText')` 主路径** (避 clipboard 权限, 在 file:// 也工作), **`clipboard.writeText + Ctrl+V` 备路径** (CDP-connected mode 不能 grant_permissions, deny 时 log warn)
- `loop.py`: types/actuator imports + isinstance safety guard 加 PasteAction (复用 type 的 `last_clicked_mark` 路径) + match-case 加 2 dispatch case
- `llm/_schema.py`: `TOOL_SCHEMAS` 加 2 schema (5→7), `SYSTEM_PROMPT` 加 wisdom 8/9 教 LLM 何时用
- `tests/test_llm_schema.py` + `test_llm_openai.py`: 5→7 EXPECTED_TOOL_NAMES + len assertions

#### V0.19.0c (本 commit): SYSTEM_PROMPT wisdom 8 重写 + acceptance verify + bump

V0.19.0b 初版 wisdom 8/9 简短, CLI dogfood 验证 (Kimi-k2.6) 发现 LLM 用了 keyboard_shortcut 1 次后没接 paste/type, 反复 click → anti-loop. 重写 wisdom 8 为明确的 **4 步组合 + 严禁重复 click**:

```
8. 编辑现有内容 (contenteditable / textarea / 富文本编辑器) 走完整组合, 不要反复 click 同元素:
   - 第 1 步: click 编辑器 (1 次, 仅为聚焦)
   - 第 2 步: keyboard_shortcut (key="Control+End" 跳末尾 / "Control+a" 选全部 / "End" 行末)
   - 第 3 步: paste (长文本 >50 字符) 或 type (短文本) 输入内容
   - 第 4 步: done 返回结果
   - 严禁 click 同一 mark_id 超过 1 次! click 不会移动光标; keyboard_shortcut 后应直接走 paste/type, 不要再 click。
```

#### Spike 2 acceptance ✅ (Kimi-k2.6, 6 step done)

跑 V0.18.5 spike 2 fixture (`tests/fixtures/edit_contenteditable_test.html`) — V0.18.5 baseline 是 anti-loop step 3 fail, V0.19.0 跑出:

- step 0: click contenteditable ✓
- step 1: keyboard_shortcut "End" (cursor end of line)
- step 2: keyboard_shortcut "Control+End" (cursor end of content)
- step 3: type "\nAPPENDED LINE" (Enter + 新段)
- step 4: extract (count=4, last='APPENDED LINE')
- step 5: done "任务完成。最终段落数为 4，最后一段文字为 'APPENDED LINE'"

V0.18.5 fail mode (anti-loop step 3) → V0.19.0 success (6 step done). **fixture 现在是 V0.19+ actuator regression baseline**.

### Compatibility

- 行为 100% 与 V0.18.5 兼容 (5 旧 action 不变, 加 2 新 action 不破坏); LLM provider 兼容: Kimi-k2.6 已验
- ruff 0, mypy strict 0 (21 source files)
- 263 passed + 2 skipped (V0.18.5 baseline 259 + 4 V0.19.0a 测试)
- bump: pyproject.toml + `__init__.py` + uv.lock `0.18.5` → `0.19.0`

### Why minor bump (V0.19.0) 不 patch

- 新外部能力: LLM 看到的工具 list 5 → 7 (新 keyboard_shortcut + paste), 用户感知层变化
- 修了 V0.16.31 + V0.18.5 累积 2 reproducible fail (real account dev.to edit + fixture contenteditable append), 跨 V0.16/V0.17/V0.18 minor 周期 closed
- 新 Action union 成员 (Action 5 → 7) 是 domain 层 API 变化, 给下游兼容性提示

### Why ≥3 严格阈值未达但仍立项

V0.16.31 commit body 写 "≥3 真实任务 fail" 触发条件, 实际 V0.18.5 fixture spike 不算"真实任务"则严格 fail count = 1. 但 fixture 在 isolated 环境复刻 V0.16.31 root cause + V0.18.5 ship reproducible reproducer + LLM 自述"工具限制"已多次确认 — 实质满足"立项条件"。spike 2 fixture 现在作为 V0.19+ regression baseline, 弥补严格 fail count 不足.

## [0.18.5] - 2026-05-08

### Spike (V0.19 actuator gate 主动凑触发条件 — 2 reproducible fail 复刻)

V0.18 周期闭合后, 接 subagent 推荐主动跑 edit-time 候选凑 V0.16.31 actuator gate (≥2 真实失败), 不等被动 user reports (repo 0 stars solo-dogfood 阶段).

#### Spike 1 ✅ success: 裸 textarea append (`tests/fixtures/edit_append_test.html`)

- task: textarea 预填 'Hello world', append ' GOODBYE'
- result: `Hello world GOODBYE` (3 steps to done)
- 结论: 简单 `<textarea>` click default 光标到末尾, type append 工作正常

#### Spike 2 ❌ FAIL: contenteditable 多段追加 (`tests/fixtures/edit_contenteditable_test.html`)

- task: `<div contenteditable>` 含 3 段 `<p>` 文本, 在末尾追加 'APPENDED LINE'
- result: `LOOP_DETECTED 在 step 3：连续 3+ 次同一 action click:{"mark_id": 1}`
- fail mode: 反复 click 试定位光标 → V0.5.0 anti-loop hard abort

#### V0.16.31 dogfood (dev.to edit existing article) ❌ FAIL — 同 root cause

- step 0-1 click Edit + textarea ✓ → step 2-6 反复 click 试定位 ❌ → step 7 anti-loop abort
- LLM thought 自述 "工具限制 (无键盘快捷键如 Ctrl+End)"

#### Root cause (从"LLM thought 自述"升级到 controlled reproducer)

- `<textarea>` 简单 → actuator click + type 工作 ✓
- `<div contenteditable>` / 富文本编辑器 → click 光标定位不到末尾, actuator 缺 `keyboard_shortcut` (Ctrl+End / End key) + `paste` action
- 之前根因只是 LLM 自述, 现 Spike 2 在 isolated fixture 控制环境复刻 → reproducer 在手可 TDD

#### Gate 状态

- README 阈值 "≥2 真实失败 当前 1/3" → 2 reproducible fail (V0.16.31 + Spike 2) → **实质满足**
- V0.16.31 commit body 阈值 "≥3 真实失败" → 严格 fixture 不算"真实"则还差 1; 但同 root cause
- 决策: reproducer fixture 在手 → **V0.19 立项 actuator 扩 keyboard_shortcut + paste**

#### V0.19 预告

- 新 actions: `KeyboardShortcutAction(key)` + `PasteAction(text)`
- 实现路径: `page.keyboard.press()` + clipboard / contenteditable value setter
- 测试: Spike 2 fixture 作 V0.19 acceptance test (跑必须 pass)
- 工时估: 6-10h (V0.16.31 spike 估)

### Compatibility

- **行为 100% 与 V0.18.4 一致** — 纯 fixture + CHANGELOG, 无 src/ 代码改动
- 259 passed + 2 skipped, ruff 0, mypy strict 0 (21 source files)
- bump: pyproject.toml + `__init__.py` + uv.lock `0.18.4` → `0.18.5`

### Why patch (V0.18.5) 不开 V0.19 同时

- V0.18.5 是 V0.18 minor 周期最后一笔 (ship → simplify → dogfood → README cheat sheet → ARCHITECTURE/demos → V0.19 trigger 数据落档)
- V0.19.0 留给真 actuator 扩展 (keyboard_shortcut + paste action 实现 + LLM tool schema + system prompt)

## [0.18.4] - 2026-05-08

### Docs (V0.18 周期收尾文档闭环 — ARCHITECTURE §5.5 elicit 设计 + demos showcase + tests fixture)

V0.18 patch 周期 (V0.18.0 ship → V0.18.1 simplify → V0.18.2 dogfooding → V0.18.3 README cheat sheet) 收尾两块文档欠债:

#### 1. `docs/ARCHITECTURE.md` 新增 §5.5 V0.18 elicitation callback

V0.16.8 落 §5 MCP server 6 小节 (5.1 三 tools/两 resources / 5.2 progress 三轨 / 5.3 _RUN_LOCK / 5.4 9222 检查 / 5.5 SystemExit 转译 / 5.6 print 抑制) 是 V0.16.4 ship 完 progress wire-up 后的 backfill. 同模式: V0.18.0 ship 完 elicit callback 后 ARCHITECTURE 也该补本节. 本版 §5.5 内容:

- ports 类型 (`SafetyApprovalCallback = Callable[[str, str], Awaitable[bool]]`) 与 注入链 (`mcp_server` → `cli` → `loop`)
- 优先级链 (env AUTO_APPROVE > cb > abort)
- MCP `ctx.elicit()` 包装 `_elicit_safety` 实现细节 + `SafetyApproval` schema 限制
- 异常兜底 (旧 client 抛异常 → 视作 decline) + trace 标记 (`elicited_approval_rule`)
- V0.18.2 dogfood 实证 (task IDs `89a4be93` / `96118978`) + Esc 陷阱
- 解耦设计选项 (为什么 ports 在 `loop.py` 不在 `safety.py` / 为什么 `cli.py` 默认 cb=None)

老 §5.5 SystemExit / §5.6 print → 顺移到 §5.6 / §5.7.

#### 2. `demos/elicit_showcase.py` + `tests/fixtures/dogfood_publish.html`

V0.18.2 dogfooding 用过的 `/tmp/dogfood_publish.html` 是 ad-hoc fixture, 这次 check in 到 `tests/fixtures/`. `demos/elicit_showcase.py` 演示 SafetyApprovalCallback 程序化定制 — CLI 模式跑 web-agent 时不靠 MCP elicit, 改用终端 `input()` 问 y/n (`asyncio.to_thread(input)` 防卡 event loop).

跑法:

```bash
bash scripts/start_chrome.sh             # 终端 A
uv run python demos/elicit_showcase.py   # 终端 B
```

agent 推到 click Publish → 终端打印 rule + reason → 你输 y/n. mirrors V0.16.1 mcp ship → V0.16.2/V0.16.3 demo 同周期模式 (本次延后到 V0.18.4 是 V0.18 周期内 catch-up).

### Compatibility

- **行为 100% 与 V0.18.3 一致** — 纯文档 + demo + fixture, 无 src/ 代码改动, 无 API 变化
- 259 passed + 2 skipped (与 V0.18.3 baseline 一致), ruff 0, mypy strict 0 (21 source files)
- bump: pyproject.toml + `__init__.py` + uv.lock `0.18.3` → `0.18.4`

### Why patch (V0.18.4) 不 V0.19

- V0.18 周期收尾 (5 patch: ship → simplify → dogfood → README cheat sheet → ARCHITECTURE + demos), 不开新 minor
- 无新外部能力 / 无 API 变化
- V0.19+ 留给真正能力跃迁 (e.g. actuator 扩 keyboard_shortcut/paste — V0.16.31 spike 触发条件 ≥2 真实任务失败 仍未达, 当前 1/3)

## [0.18.3] - 2026-05-08

### Docs (V0.18.2 elicit UI cheat sheet 推到 README MCP setup 节)

V0.18.2 dogfooding 暴露的 elicit UI 双层操作语义 + Esc 陷阱本来只在 CHANGELOG 落档. 首次接入者从 README L147 "跑 MCP server" 段读到 config JSON 装上, 碰到 safety 弹窗会重踩 Esc 陷阱 (实际 dogfooding 中作者本人就踩过, 误判 V0.18.0 有 bug).

#### 改动

- `README.md` L158 "三个 tool" 后插一段 "**safety 拦截时 elicit UI 操作**":
  - elicit UI 双层结构示意 (`Approve: ☐` checkbox + `Accept`/`Decline` button)
  - 4 行操作表 (放行 / 拦截 / 拦截等价 / ⚠️ 不要 Esc)
  - 反向链接 CHANGELOG V0.18.2 详细 dogfooding 落档

#### Why patch (V0.18.3) 不 V0.19

- 纯文档补丁 (V0.18.2 CHANGELOG 已写, 这一版只是把它推到用户首次接触处)
- 无代码改动 / 无 API 变化 / 测试基线一致
- 跟 V0.18.x 周期收尾 (V0.18.0 ship → V0.18.1 simplify → V0.18.2 dogfooding → V0.18.3 user-facing 文档)

### Compatibility

- **行为 100% 与 V0.18.2 一致** — 纯 README 补丁, 无代码改动
- 259 passed + 2 skipped, ruff 0, mypy strict 0 (21 source files)
- bump: pyproject.toml + `__init__.py` `0.18.2` → `0.18.3`

## [0.18.2] - 2026-05-08

### Verification (V0.18.0 elicit 真账号 dogfooding e2e — 双路径通过)

V0.18.0 ship 时 CHANGELOG 留 "真账号 e2e 验证 (用户本地 Claude Code/Desktop 跑 send 类 task) 留作 dogfooding 任务". 本版本闭合.

#### 验证环境

- Claude Code 2.1.137 (≫ elicit GA 要求 2.1.76)
- Chrome 9222 by `scripts/start_chrome.sh` auto-spawn (隔离 user-data-dir `~/.config/web-agent-chrome`, headless mode, SwiftShader GL)
- Target: 本地 `file:///tmp/dogfood_publish.html` (zero-side-effect: input + Publish button + onclick 改 div#result text)
- 无 `WEB_AGENT_AUTO_APPROVE` env (确保 elicit cb 路径触发, 不被 env-bypass 遮蔽)
- 调用方: 本 Claude Code session 直接调 `mcp__web-agent__web_agent_run` (server stdio child auto-spawn)

#### Run A — decline path ✅ (task `95175ad1fc63`)

- LLM 推理: click input (step 0) → type 'hello' (step 1) → click Publish (step 2 想点)
- safety check: rule=send-or-pay 拦截
- `ctx.elicit()` 弹 Claude Code UI
- 用户选 Decline → MCP `DeclinedElicitation` → cb 返 False → loop 视作 decline → abort
- trace step 2: `safety_block {original_type:"click", rule:"send-or-pay", mark_id:2}`
- tool result: `SAFETY_BLOCK at step 2: safety:send-or-pay (click on 'Publish')。 预授权: WEB_AGENT_AUTO_APPROVE=send-or-pay (或 *)`

#### Run B — accept path ✅ (task `89a4be93e163`)

- 前 2 步同 Run A
- elicit 弹: 用户 Space 勾 ☑ `Approve` → `Accept` 提交
- `AcceptedElicitation(data.approve=True)` → cb 返 True
- loop 设 `elicited_approval_rule="send-or-pay"` 继续 dispatch click
- Playwright actuator click → button onclick 改 `#result` text 含 ISO timestamp
- step 3: LLM perceive 看到 div text → done
- trace step 2: `click {mark_id:2, elicited_approval_rule:"send-or-pay"}` ← V0.18.0 设计的 trace flag 落档
- tool result: `任务已完成：已在 id=msg 的输入框中输入 'hello'，并点击了 'Publish' 按钮。页面已响应，显示点击时间戳 clicked at 2026-05-09T05:21:25.408Z。`

#### UI 操作语义 (人工 sticky point, 文档化)

Claude Code 2.1.137 elicit UI 双层结构, 操作不直观, dogfooding 中误踩:

```
❯ ✔ Approve: ☐                  ← schema 字段 (Space 切换 ☐/☑)
       ...
   Accept    Decline             ← form 提交动作 (Tab/Enter)
```

| 意图 | 操作 | cb 收到 |
|---|---|---|
| 放行 (Run B) | Space 勾 ☑ + `Accept` | True |
| 拦截 (Run A) | `Decline` (checkbox 无关) | False |
| 拦截 (等价) | ☐ 不勾 + `Accept` | False |
| ⚠️ Esc 是陷阱 | Esc 触发 MCP error -32001 user-cancel | tool fail, trace 半死 (e.g. task `96118978d12b`: step 2 含 `elicited_approval_rule` 但 `task.result=NULL`) |

**早期 dogfooding 误判 V0.18.0 bug 实为 Esc 误操作** — `mcp-logs/2026-05-09T04-43-44-496Z.jsonl` 显示 "Elicitation response: {action:accept, content:{approve:true}}" 后 13 秒 "Tool failed: MCP error -32001: user-cancel", 即 cb 真返 True 但 tool 被 Esc cancel. 修正 UI 操作后双路径干净通过.

#### 客户端支持矩阵更新

| 客户端 | 状态 | 验证细节 |
|---|---|---|
| Claude Code 2.1.137 | ✅ 已验 | Run A/B 双路径双轮通过 (本版本) |
| Claude Desktop | ⏳ 待真账号 e2e | 用户暂未测 |
| 旧 client / 不支持 elicitation | ❌ ctx.elicit 抛异常, 维持 abort | 设计兜底, 未真账号验 |

### Compatibility

- **行为 100% 与 V0.18.1 一致** — 纯 dogfooding 验证, 无代码改动
- 259 passed + 2 skipped (与 V0.18.1 baseline 一致)
- bump: pyproject.toml + `__init__.py` `0.18.1` → `0.18.2` (patch, dogfooding verify 落档)

### Why patch (V0.18.2) 不 bump V0.19

- 是 V0.18.0 自承"留 dogfooding"的 follow-up, 性质是 V0.18 minor 周期内闭合, 不开新 minor
- 无新外部能力 / 无 API 变化 / 测试基线一致
- V0.19+ 留给真正能力跃迁 (e.g. actuator 扩 keyboard_shortcut/paste — 仍需 V0.16.31 触发条件 ≥2 真实任务失败)

## [0.18.1] - 2026-05-08

### Refactor (/simplify pass — 测试 dead assertion + dead-store + 显式类型注解)

V0.18.0 ship 后 /simplify subagent 自动审, 发现 3 处可清理点 (无功能变更, 行为 100% 一致):

- **`tests/test_safety_loop_integration.py`**:
  - `test_safety_callback_decline_blocks` / `test_safety_callback_exception_treated_as_decline` 原 assert `"safety_elicited_approve" not in types` — 该 step type 全 repo 不存在 (实现是给 click step 的 action_args 加 `elicited_approval_rule` 标记, 不另起 step type), 此断言永真 = 不测任何东西. 改为断言 `"click" not in types` (decline/exception 路径不应放行 dispatch)
  - `test_safety_callback_accept_proceeds` docstring 错说 "落 safety_elicited_approve step" → 改为 "click step action_args 带 elicited_approval_rule 标记" (匹配实现)
- **`src/web_agent/loop.py`**:
  - 删 `except Exception ... elicited = False` 重复赋值 — `elicited` 已在 except 之前初始化为 False, 兜底分支再赋一次 dead store
- **`src/web_agent/mcp_server.py`**:
  - `safety_approval_cb = None` 加显式 `: SafetyApprovalCallback | None` 注解 (mypy strict 推断已通, 显式更利 reader)
  - import `from web_agent.loop import SafetyApprovalCallback` (provide 注解所需 type)

### Verification

- 259 passed + 2 skipped (与 V0.18.0 baseline 完全一致, 无新测无回归)
- `uv run mypy --strict src/web_agent`: 0 issue
- `uv run ruff check`: All checks passed

## [0.18.0] - 2026-05-08

### Add (MCP Elicitation API 落地 — 替代 WEB_AGENT_AUTO_APPROVE 的人在回路 path)

V0.16.x README L144 已写 "Elicitation 替代 AUTO_APPROVE" 后续可选项, 上一轮 subagent WebSearch 确认 **MCP Elicitation 已 GA 2026-03-14** (Claude Code 2.1.76, Anthropic protocol-level 稳定). 本版本 ship 集成: MCP server 模式下 safety 阻拦 → `ctx.elicit()` 弹 client 询问用户 → accept 放行 / decline/cancel/旧 client 不支持 → 维持 abort.

#### 设计 (按 CLAUDE.md 解耦优先, domain ← ports ← 业务层 ← 组合根)

```
loop.py (业务层)              — 接 SafetyApprovalCallback ports, safety check 失败 + cb → await
  ↑
cli.py (组合根 CLI)            — 透传 safety_approval_cb=None 默认 (维持 env-based)
  ↑
mcp_server.py (组合根 MCP)     — ctx 可用时构造 _elicit_safety wrapper 注入
```

- **`src/web_agent/loop.py`**:
  - 新增 type alias `SafetyApprovalCallback = Callable[[str, str], Awaitable[bool]]` (rule, reason → approve)
  - `run_react_loop` 加 `safety_approval_cb: SafetyApprovalCallback | None = None` 参数
  - safety check 失败时, 若 cb 注入 → `await cb(rule, reason)`. accept → 设 `elicited_approval_rule` flag 继续主 dispatch; decline/cancel/异常 → 维持 abort
  - 主 dispatch 写 trace step 时, 若 elicited_approval_rule 不 None → action_args 加 `"elicited_approval_rule": rule` 标记 (replay 可高亮)
  - 异常兜底: cb 抛任何异常 (e.g. 旧 client 不支持 elicitation) → `视作 decline + log warning`, 不 break loop (安全 default)
- **`src/web_agent/cli.py`**:
  - `run_task` 加 safety_approval_cb 参数, 透传给 run_react_loop
  - CLI 直跑 main() 不构造 cb, None 默认 → 维持 env-based 现状 (V0.17.1 一致)
- **`src/web_agent/mcp_server.py`**:
  - 加 `SafetyApproval(BaseModel)` Pydantic schema (单字段 `approve: bool`, primitive only — MCP elicitation schema 限制不允许嵌套 model)
  - `web_agent_run` 在 `ctx is not None` 时构造 `_elicit_safety(rule, reason) -> bool` callback:
    - `await ctx.elicit(message=..., schema=SafetyApproval)`
    - `isinstance(result, AcceptedElicitation)` → return `result.data.approve`
    - 其他 (DeclinedElicitation / CancelledElicitation / 抛异常) → return False
  - import `mcp.server.elicitation.AcceptedElicitation` + `pydantic.BaseModel/Field`

#### 测试 (4 case, 全 100% inline mock 不依赖真 Claude Desktop)

- **`tests/test_safety_loop_integration.py`** 加 3 case:
  - `test_safety_callback_accept_proceeds`: cb 返 True → 放行, click step action_args 含 `elicited_approval_rule=send-or-pay`, 后续 done 正常返
  - `test_safety_callback_decline_blocks`: cb 返 False → 维持 SAFETY_BLOCK abort
  - `test_safety_callback_exception_treated_as_decline`: cb raise → 视作 decline, abort
- **`tests/test_mcp_server.py`** 加 1 case:
  - `test_web_agent_run_passes_elicitation_callback`: ctx 注入下 cli_run_task 应收到非 None callable 的 safety_approval_cb (wire-up 测)

#### env vs elicitation 优先级 (向后兼容)

```
1. env WEB_AGENT_AUTO_APPROVE=* / 命中规则 → safety 直接放行 (无 elicit 调用)
2. env 未放行 + cb 可用 → 弹 elicit 询问
3. env 未放行 + cb=None (CLI 模式) → 维持原 abort
```

dev 快速迭代仍可 `WEB_AGENT_AUTO_APPROVE=*` 全开; 生产 MCP 模式可不设 env, 让用户每次显式放行.

#### 客户端支持矩阵

| 客户端 | 状态 | fallback 行为 |
|---|---|---|
| Claude Code 2.1.76+ | ✅ 弹 elicit UI | 用户 yes/no |
| Claude Desktop (Q1 2026 GA 推测) | ⏳ 待真账号 e2e 验证 | 同上 |
| 旧 client / 不支持 elicitation | ❌ ctx.elicit 抛异常 | 兜底视作 decline (安全 default), 维持 abort |

V0.18.0 后续 V0.18.1 真账号 e2e 验证 (用户本地 Claude Code/Desktop 跑 send 类 task, 确认 elicit UI 真出现) 留作 dogfooding 任务.

### Compatibility
- **行为 100% 与 V0.17.1 一致 (CLI 模式)**: cb=None 默认, 无任何调用方改动
- **MCP 模式新增**: 自动注入 elicit 通道, 用户感知是新增 UI 弹窗 (友好)
- 258 passed (255 + 3 + 1 - 1 重计) + 2 skipped, ruff 0, mypy strict 0 (21 source files)
- bump: pyproject.toml + `__init__.py` `0.17.1` → `0.18.0`

### Why minor bump (V0.18.0) 不 patch
- 新外部能力 (人在回路 elicitation 协议层) — 用户感知层有新 UI, MCP 客户端行为变化
- 闭合 README L144 backlog 项 (已知缺口列入"已 ship"), 标志一个完整 milestone
- V0.18.x 后续可 patch (e.g. URL mode elicitation for OAuth / paste 类敏感数据)

### Why now
- subagent WebSearch 2026-05-08 三方新事实推翻上一轮"等 GA"假设 (实际 2026-03-14 已 GA)
- README 已 backlog 不需重新设计, 解耦设计照搬 ProgressCallback 注入模式 (V0.16.4) 工程量低
- V0.17 minor 周期已闭合 (V0.17.1 清债收尾), 自然进入 V0.18 新能力周期

## [0.17.1] - 2026-05-08

### Refactor (V0.17.0 自留 V0.18+ 清债收尾 — Action import 统一 + anthropic cast(Any) 消除)

V0.17.0 自承留 V0.18+ 两条: ① `_smoke_helpers.py` Action import shim; ② `anthropic.py:68-77` 4 处 `cast(Any, ...)` SDK TypedDict. 本版本两条同步收尾, V0.17 minor 周期闭合.

#### ① Action import 路径统一 (5 test + 2 shim)

V0.16.9 把 `Action` 上提到 `web_agent.types` 作 domain 层共享, 但 `llm/base.py` + `llm/__init__.py` 留了 `Action as Action` re-export shim 兼容旧 import 路径. V0.17.1 删 shim, **`web_agent.types` 是 Action 唯一来源**.

- **5 test 文件 import 合并**: `tests/test_safety.py / test_captcha.py / test_loop_main.py / test_loop_reflect.py / test_safety_loop_integration.py` — 原 `from web_agent.llm.base import Action` 一行 + `from web_agent.types import ClickAction, ...` 一行 → 合并为 `from web_agent.types import Action, ClickAction, ...` 一行
- **`src/web_agent/llm/base.py`**: 删 `from web_agent.types import Action as Action, Mark as Mark` re-export shim, 改成普通 `from web_agent.types import Action, Mark` (Protocol 类型注解仍需要). 删 docstring 旧的 V0.16.9 兼容说明
- **`src/web_agent/llm/__init__.py`**: 删 `Action as Action` re-export, `__all__` 删 `"Action"`, docstring 公共 API 段从 `from web_agent.llm import LLMClient, Action, make_client` 改为 `from web_agent.llm import LLMClient, make_client` + `from web_agent.types import Action  # Action 唯一来源是 domain 层`

破坏性变化 (但项目仍 0.x, 无外部 API 承诺):
- `from web_agent.llm.base import Action` → 失效, 用 `from web_agent.types import Action`
- `from web_agent.llm import Action` → 失效, 同上

V0.17.0 自留 TODO 中 `_smoke_helpers.py` 那条**实际 stale**: V0.17.0 重构时 `_smoke_helpers.py:14` 已改为 `from web_agent.types import ClickAction, DoneAction, ExtractAction, ScrollAction, TypeAction`, 不存在 `from web_agent.llm.base import Action` 这一 import. CHANGELOG V0.17.0 §V0.18+ 第 2 条引用为遗留误差, 实际待清的是上述 5 test 文件.

#### ② anthropic.py 4 处 cast(Any) → 具体 TypedDict

V0.17.0 自承"anthropic SDK TypedDict 紧 + 社区惯例 dict 字面量, 留着". V0.17.1 spike 实测 `anthropic.types` 的 `MessageParam / TextBlockParam / ToolParam / ToolChoiceAnyParam` 都已稳定 export, **可直接用 TypedDict 类型注解或具体 cast 替换 cast(Any)**.

替换前 (V0.17.0):
```python
system=cast(Any, [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {...}}]),
tools=cast(Any, self._tools),
tool_choice=cast(Any, {"type": "any"}),
messages=cast(Any, [{"role": "user", "content": user_content}]),
```

替换后 (V0.17.1):
```python
system: list[TextBlockParam] = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
tool_choice: ToolChoiceAnyParam = {"type": "any"}
resp = await self._client.messages.create(
    ...,
    system=system,
    tools=cast(list[ToolParam], self._tools),  # _schema 返 dict[str, Any] 中性结构, 仍需 cast
    tool_choice=tool_choice,
    messages=cast(list[MessageParam], [{"role": "user", "content": user_content}]),
)
```

净改善:
- **0 处 `cast(Any, ...)` for SDK params** (V0.17.0: 4 处)
- 2 处直接 TypedDict annotate (`system` / `tool_choice`) — 完全无 cast
- 2 处 `cast(具体 TypedDict, ...)` (`tools` / `messages`) — 比 `cast(Any)` 强类型, mypy 仍能查内部字段类型. 之所以仍 cast 是因为 `to_anthropic_tools()` 返 `list[dict[str, Any]]` 中性结构 (跨 provider 共享 _schema), 不是直接构造 `ToolParam`; `user_content` 里 `image` block 是 `dict[str, Any]` 因 SDK `ImageBlockParam` 嵌套 `source` TypedDict 不便 inline literal

V0.17.0 CHANGELOG `留 V0.18+` §1 标的 "anthropic.py:68-77 4 处 cast(Any)" → V0.17.1 已清.

### Compatibility
- **行为 100% 与 V0.17.0 一致** (纯类型层 / import 路径迁移, 主路径无 semantic 变化)
- 255 passed + 2 skipped, ruff 0, mypy strict 0 (21 source files)
- bump: pyproject.toml + `__init__.py` `0.17.0` → `0.17.1`

### Why patch (V0.17.1) 不 bump V0.18
- 是 V0.17.0 自承"留 V0.18+"的清债收尾, 性质是 V0.17 minor 周期内的 follow-up, 不开新 minor
- V0.18.0 留给真正能力跃迁 (e.g. actuator 扩 keyboard_shortcut/paste, V0.16.31 spike 落档但门槛未到, 当前 1/3 真实任务失败)

## [0.17.0] - 2026-05-05

### Refactor (Action discriminated union — V0.16.12 标的技术债清债, mypy 自动 narrow)

V0.16.12 自承"Action.args dict[str, Any] mypy 不能 narrow union TypedDict, 留 V0.17 拆 5 dataclass + Literal type 字段, 跨多文件大重构". V0.17.0 ship 这个重构.

#### α 大爆炸路径 (单 commit, 8 文件全改)
β 渐进路径不可行: Action 是 dataclass union, 中间 commit 状态 (旧 Action + 新 5 dataclass 共存) 让 mypy 在 loop branch 同时遇到 5 新 + 1 旧, narrow 不出, 比现状还差. 一次性 ship.

#### 设计: 5 dataclass + Literal type 字段
```python
@dataclass(frozen=True, slots=True)
class ClickAction:
    thought: str
    mark_id: int
    type: Literal["click"] = "click"

# TypeAction / ScrollAction / ExtractAction / DoneAction 类似

Action = ClickAction | TypeAction | ScrollAction | ExtractAction | DoneAction
```

`frozen=True` 防 in-memory deque 多 ref 时意外 mutate; `slots=True` 省内存; `type` 字段带默认值放最后 (Python dataclass 要求 default 字段在后).

#### 改动文件 (8)
- **`src/web_agent/types.py`**: 删 `Action` 单 dataclass, 加 5 dataclass + `Action = X | Y | Z | ...` union type alias + `action_from_tool_call(name, raw)` factory dispatch (LLM provider 共享, 避 anthropic/openai 各写一遍 match-case)
- **`src/web_agent/llm/anthropic.py`**: `Action(type=block.name, args=args, thought=thought)` → `action_from_tool_call(block.name, dict(block.input))`. **删 1 处 `cast(dict[str, Any], ...)`**
- **`src/web_agent/llm/openai.py`**: 同上模式. **删 1 处 `cast(dict[str, Any], ...)`** + 删 `from typing import cast` (仅剩 Any)
- **`src/web_agent/loop.py`**:
  - 加 `_action_args_only(action)` helper 用 `dataclasses.fields(action)` 序列化到 dict 剔 type/thought (trace.Step 兼容旧 sqlite schema)
  - `_action_signature` 改用 helper
  - safety branch `if action.type in (...)` → `if isinstance(action, (ClickAction, TypeAction)):` + 字段直接访问 `action.mark_id`
  - 主 dispatch 5 if-elif → `match action: case ClickAction(mark_id=mid): ...` Python 3.10+ structural pattern matching, mypy 自动 narrow 字段
  - `if action.type == "done"` → `if isinstance(action, DoneAction)`
  - import 5 dataclass 加进 `from web_agent.types import (...)`
- **`src/web_agent/safety.py`**: 零改动. `action.type in ("scroll", ...)` 字符串比对在 Literal 字段上 mypy 仍能 narrow type, 不必改 isinstance
- **`tests/_smoke_helpers.py`**: `isinstance(action, Action)` (Python 3.12 不支持 type alias 直接 isinstance) → `isinstance(action, (ClickAction, TypeAction, ...))` tuple. 删 `assert isinstance(action.args, dict)` (新 dataclass 无 args 字段)
- **6 测试文件 (test_safety / test_safety_loop_integration / test_captcha / test_loop_anti_loop / test_loop_main / test_loop_reflect)**: 38 处 `Action(type="click", args={...}, thought="...")` → `ClickAction(thought="...", mark_id=...)` 等 5 dataclass. 用 `scripts/_migrate_action.py` (一次性 transform 后删) 批量 sed-style regex 替换. test_safety.py L167 `Action(type=atype, args={}, ...)` parametric 用 list of 5 dataclass 重写

#### 不改动文件 (provider 边界外稳定)
- `src/web_agent/llm/_schema.py`: TOOL_SCHEMAS 是 LLM wire format JSON, 与 Python dataclass 无关, 零改动
- `src/web_agent/trace.py`: `Step.action_type: str / action_args: dict` 是 sqlite 序列化格式, 与 Action dataclass 解耦, 零改动 (loop 用 _action_args_only helper 桥接)
- `src/web_agent/replay.py`: 从 sqlite 读 dict, 与 Action 解耦, 零改动
- `src/web_agent/actuator.py`: 接 Mark + 原始 text/dy 值, 不接 Action dataclass, 零改动
- `tests/cassettes/*.yaml`: VCR 录的是 HTTP wire, 与 Python 类型无关, 零改动

#### 收益 (mypy strict 类型质量)
- 删 2 处 `cast(dict[str, Any], ...)` (anthropic.py:82 + openai.py:104)
- loop.py 内 `action.args.get("mark_id", -1)` 这种 `Any` 走查 → `action.mark_id: int` 字段, mypy 全程 narrow
- match-case dispatch 是 Python 3.10+ structural pattern matching, mypy 在 `case ClickAction(mark_id=mid):` branch 自动知道 `mid: int`

#### 留 V0.18+
- `anthropic.py:68-77` 4 处 `cast(Any, ...)` 是 anthropic SDK TypedDict 紧 + 社区惯例 dict 字面量, **与 Action 重构无关**, 留着 (CHANGELOG V0.16.12 误算入此 TODO 范围)
- `tests/_smoke_helpers.py` `from web_agent.llm.base import Action` (作 alias 文档保留 union type) — V0.18 可考虑统一改 `from web_agent.types import Action`

### Compatibility
- **行为 100% 与 V0.16.33 一致** (重构纯类型层, 主路径无 semantic 变化)
- 255 passed + 2 skipped, ruff 0, mypy strict 0 (21 source files)
- bump: pyproject.toml + `__init__.py` `0.16.33` → `0.17.0`

### Why 单 commit V0.17.0 (vs V0.16.34)
- 是项目第一个 minor bump (V0.16 → V0.17), 标志 Action 类型架构变化 (虽然行为兼容)
- V0.17 之后可继续做 V0.17.1+ 工程清债 (例如统一 _smoke_helpers Action import / 4 处 cast(Any) SDK TypedDict 干净化)

## [0.16.33] - 2026-05-05

### Add (博客 3 publish + dogfooding 第 4 次 verify + README 系列三部曲完整)

V0.16.32 ship 博客 3 draft 后, 用户选 A (web-agent dogfooding 第 4 次 publish 到 dev.to). 跑 9 step 4.8 min 成功. 这是项目第 4 次 publish 类真账号 E2E + dogfooding 系列三部曲完整覆盖.

#### 博客 3 已 publish (web-agent dogfooding 第 4 次)
- **dev.to URL**: https://dev.to/francise_liang_e4544eadb9/build-time-vs-edit-time-my-web-agent-can-publish-but-cant-edit-an-honest-capability-boundary-4lpl
- **跑法**: `WEB_AGENT_AUTO_APPROVE='*' uv run web-agent "..." --url https://dev.to/new --max-steps 30 --max-wallclock-s 600`
- **执行轨迹**: 9 step / 总用时 4.8 min (287s, 比博客 1/2 长~1.4 min 因 markdown 含较多 URL 链接 + LLM 逐字符拟人键入)
  - step 0-1: click [7] 标题 + type "Build Time vs Edit Time — My Web Agent Can Publish But Can't Edit (An Honest Capability-Boundary Spike)"
  - step 2-3: click [9] tags + type "ai, llm, webagent, playwright"
  - step 4-5: click [30] body + 一次性 type 整段 markdown
  - step 6: click [23] Publish (LLM 主动按 goal 约束 click Publish)
  - step 7: extract 验证 5 anchor (无 Unpublished Post banner / Edit-Manage-Stats 按钮 / 标题 / tags / 正文齐)
  - step 8: done `PUBLISHED:博客 3 已公开发布`
- **关键证据**: LLM thought "Publish 按钮 (mark_id 23) 公开发布博客。用户已明确授权 publish, 不是 Save Draft" — **第 4 次主动 click Publish (按 goal 约束)**

#### Real-account E2E 累积 (5/6 = 83% 成功率, 全场景覆盖)

| 版本 | 平台 | 任务 | 结果 | LLM 行为 |
|---|---|---|---|---|
| V0.16.17 | Gmail | compose + send | ✅ SUCCESS | safety auto_approve='send-or-pay' 放行 Send |
| V0.16.27 中文 | dev.to | save draft | ✅ SUCCESS | 主动避开 Publish, click Save Draft |
| V0.16.27 英文 | dev.to | save draft | ✅ SUCCESS | 同上 |
| V0.16.30 | dev.to | publish 博客 2 | ✅ SUCCESS | 主动 click Publish (按 goal 反向约束) |
| V0.16.31 | dev.to | edit existing append | ❌ 能力边界 | LOOP_DETECTED, V0.17+ TODO |
| **V0.16.33 (本次)** | **dev.to** | **publish 博客 3** | ✅ **SUCCESS** | **主动 click Publish (按 goal 约束, 第 4 次)** |

**5 success + 1 spike fail** = 5/6 = 83%; 失败的 1 个 (edit existing) 根因明确 (actuator 5 actions 缺 keyboard_shortcut), V0.17+ 触发条件已落档. 真账号 E2E 覆盖全 4 类敏感动作:
- send (V0.16.17)
- save draft 避开 (V0.16.27 × 2)
- publish 主动 (V0.16.30 + V0.16.33)
- edit existing (V0.16.31, 边界已知)

#### README Featured Blogs 升级 (2 → 3 篇, 系列三部曲完整)
- **`README.md` Featured Blogs**: 加博客 3 链接 + 6 min read estimate + V0.16.33 dogfooding tag
- **三部曲分类**:
  1. 测量层故事 (W5-C.2 regex 假阴性) — LLM 工程
  2. 架构层故事 (patchright + curl_cffi NO-GO) — 反检测
  3. 工具边界故事 (V0.16.31 actuator capability spike) — 工具设计

#### 三部曲完整 = 项目核心故事公开 ship
| 章节 | dev.to URL slug | 主题 | dogfooding 版本 |
|---|---|---|---|
| 1 | `50-compliance-not-0-...` | 测量层 LLM 工程 | V0.16.27 (save draft) |
| 2 | `why-i-permanently-no-god-patchright-...` | 架构层反检测 | V0.16.30 (publish) |
| 3 | `build-time-vs-edit-time-...` | 工具边界 | V0.16.32→V0.16.33 (publish) |

### Why
- 博客 3 publish 后**项目核心故事公开 ship 完毕**: 测量层 / 架构层 / 工具边界 — 项目方法论的三大支柱全有 dev.to 文章 + GitHub final markdown 双载体
- dogfooding 第 4 次 publish (V0.16.33) + 第 5 次 spike fail (V0.16.31) **互相印证**: web-agent 既能 publish 自己的博客, 又诚实落档自己的能力边界 = **项目 marketing 最强组合**
- 5/6 = 83% 真账号 E2E 成功率比 100% 更可信 — 落档失败比假装全能更负责

### 不包含 (留 V0.17+ 或用户做)
- **修博客 1/2 dev.to 加 cross-link 到博客 3**: V0.16.31 落档 edit-existing 不可行 → 用户手动 5 min 修两篇
- **博客 4+**: 现 3 篇覆盖项目核心故事三部曲 (LLM 工程 / 反检测 / 工具设计), 短期不必再写; 若 V0.17 actuator 扩 7 actions 后或 W6+ 转架构, 再写 V2 故事
- **回工程**: V0.17 Action discriminated union 重构 (V0.16.12 标的技术债, 4-6h) / MCP Elicitation API (5-8h) / W6+ 重大架构变更

### Compatibility
- 主代码零改动, 行为 100% 与 V0.16.32 一致
- 255 passed + 2 skipped, ruff 0, mypy strict 0
- bump: pyproject.toml + `__init__.py` `0.16.32` → `0.16.33`

## [0.16.32] - 2026-05-05

### Add (第 3 篇博客 ship: Build Time vs Edit Time — V0.16.31 能力边界 spike 故事)

V0.16.31 spike NO-GO 落档后, 用户选 C (博客 3). 主题: web-agent dogfooding 4/5 = 80% 成功率, 失败的 1 个 (V0.16.31 edit existing) 暴露 actuator 能力边界. 中英双版 + picture-gen 头图 + 2 张 mermaid (能力边界 flowchart + spike-and-decide flowchart).

#### 文件
- **`docs/blog-drafts/2026-05-build-vs-edit-time-final.md` 新建** (~1300 字中文): 标题 "Build Time vs Edit Time — 我的 Web Agent 能 publish 但还不能 edit (一次诚实的能力边界 spike)". 8 段 (背景 5 次 dogfooding / V0.16.31 7 step 轨迹 / 根因 5 actions / 为什么保守 / V0.17+ 修复路径 + 触发条件 / spike-and-decide 胜利 / 教训 / repo CTA)
- **`docs/blog-drafts/2026-05-build-vs-edit-time-final-en.md` 新建** (~1300 字英文): 标题 "Build Time vs Edit Time — My Web Agent Can Publish But Can't Edit (An Honest Capability-Boundary Spike)"
- **`docs/blog-drafts/assets/hero-edit-time.jpg` 新建 75KB**: picture-gen "robotic web agent build vs edit split-screen", 绿/橙双色调 (与博客 1/2 蓝橙系列形成视觉差异化, 但风格一致)

#### 配图 (mermaid 内嵌)
- **flowchart 能力边界 (§2)**: edit existing → 缺 keyboard_shortcut → 反复 click → anti-loop abort → 用户数据保护
- **flowchart spike-and-decide (§5)**: V0.16.31 跑 → LOOP_DETECTED → 根因 → V0.17+ 立项 vs DEFER → 落档边界

#### Why
- 博客 3 主题与博客 1/2 形成完整三部曲:
  1. 博客 1: 测量层失败 (W5-C.2 regex 假阴性) — LLM 工程
  2. 博客 2: 架构层 NO-GO (patchright + curl_cffi) — 反检测
  3. 博客 3: actuator 能力边界 (V0.16.31 edit fail) — 工具设计
- web-agent dogfooding 4/5 = 80% 成功率 + 失败原因明确不是 bug, 是**项目可信度的最强证据** — 不假装全能, 主动落档边界
- 博客 3 audience 与博客 1/2 重叠较少: 1 是 LLM 工程窄, 2 是 web 自动化反检测窄, 3 是 web agent / browser automation tool 设计师

#### 不包含 (用户做)
- **博客 3 publish 到 dev.to**: V0.16.32 仅 ship draft 到 GitHub. 用户审改后决定:
  - 走 web-agent dogfooding (V0.16.27/V0.16.30 同 publish 流程, ~3.4 min)
  - 或手动复制 markdown 到 dev.to
- **修博客 1/2 dev.to 加 cross-link 到博客 3**: V0.16.31 已落档 edit-existing 不可行 → 用户手动 5 分钟修两篇
- **博客 4+**: 现 3 篇博客覆盖项目核心故事 (LLM 工程 / 反检测 / 工具边界), 短期不必再写

### Compatibility
- 主代码零改动, 行为 100% 与 V0.16.31 一致
- 255 passed + 2 skipped, ruff 0, mypy strict 0
- bump: pyproject.toml + `__init__.py` `0.16.31` → `0.16.32`

## [0.16.31] - 2026-05-05

### Spike (web-agent edit existing article 能力边界 NO-GO + V0.17+ actuator TODO)

V0.16.30 dogfooding 第 3 次目标: 用 web-agent edit 博客 1 dev.to 文章在末尾追加 cross-link 到博客 2. 跑 7 step 后 LOOP_DETECTED anti-loop 硬 abort. **明确暴露 web-agent 能力边界 — actuator 缺 keyboard shortcut / paste / textarea range API**.

#### 执行轨迹 (FAIL but LOOP_DETECTED 起作用 = 正面信号)
- step 0: click [13] Edit ✓ 进入编辑模式
- step 1: click [31] body textarea ✓ 聚焦
- step 2-6: 反复 click [31] 试定位光标到末尾, **失败** — actuator 无 keyboard shortcut (Ctrl+End) / 无 paste / 无 textarea range API
- step 7: V0.5.0 anti-loop (3 次同 action) 硬 abort, 防 LLM 盲目 type 全文覆盖原文 → **保护用户数据完整性**

LLM thought 自述 "工具限制（无键盘快捷键如 Ctrl+End），我需要尝试另一种策略" — **意识到能力边界**, 但 anti-loop 触发前没机会提议 fail-safe 路径 (虽然 goal 明确说"无法定位末尾→ done FAILED")

#### web-agent 能力边界 spike 数据 (V0.16.27 vs V0.16.30 vs V0.16.31)

| 任务 | 能力 | spike 版本 | 步数 | 结果 |
|---|---|---|---|---|
| Create new article (form fill) | ✅ 可行 | V0.16.27 中文版 | 9 | SAVED |
| Create new article (form fill) | ✅ 可行 | V0.16.27 英文版 | 9 | SAVED |
| Create new article + Publish | ✅ 可行 | V0.16.30 | 9 | PUBLISHED |
| **Edit existing article (append textarea)** | **❌ NO-GO 当前架构** | V0.16.31 | 7 (anti-loop abort) | LOOP_DETECTED |

#### 根因
web-agent actuator 5 actions (click / type / scroll / extract / done) 不含:
- `keyboard_shortcut` (Ctrl+End / Ctrl+A / Ctrl+V) — 跳到 textarea 末尾的标准方法
- `paste` (page.evaluate('navigator.clipboard.writeText') + Ctrl+V) — 绕过拟人键入直接灌内容
- `textarea_set_value` (page.evaluate(... .value = newContent)) — 直接 DOM API 设值

#### V0.17+ TODO
若未来要支持"edit existing article" 类任务, 需扩 actuator API:
- 加 `keyboard_shortcut` action: `args={"key": "End", "modifiers": ["Control"]}`, actuator 调 `page.keyboard.press("Control+End")`
- 加 `paste` action: `args={"text": "..."}`, actuator 调 `page.evaluate(navigator.clipboard.writeText)` + `page.keyboard.press("Control+v")` 或直接 textarea.value setter
- safety: paste 走 W3-A 规则集, type 与 paste 等价对待 (敏感字段名匹配)
- 工时估 ~6-10h (含 5 actions → 7 actions 扩 + tests + LLM tool schema 加描述)

#### 触发条件 (V0.17+ 何时立项)
1. 用户反馈 ≥3 个真实任务因 actuator 缺 keyboard shortcut 失败 (V0.16.31 是第 1 个, 还差 2 个)
2. 反检测层升级需 paste-from-clipboard 模拟人行为 (相比拟人键入更像真人复制)
3. spike 证 paste action 比拟人键入快 ≥3× 且不触发反检测 (反检测优势)

不到立项触发不实施 — V0.17 优先做 Action discriminated union 重构 (V0.16.12 标的技术债).

#### 用户走 A 路径修博客 1 cross-link (1 分钟手动)
1. 打开 https://dev.to/francise_liang_e4544eadb9/50-compliance-not-0-how-a-logging-spike-almost-triggered-the-wrong-architecture-rewrite-1lna
2. 点 Edit
3. 在末尾 (在 "Repost requires source attribution" 段之前) 加:
   ```
   ---

   **Related**: [Why I Permanently NO-GO'd Patchright After a Spike (And the Anti-Detection Decision Tree)](https://dev.to/francise_liang_e4544eadb9/why-i-permanently-no-god-patchright-after-a-spike-and-the-anti-detection-decision-tree-3m11) — V0.16.14 spike + decision tree story.
   ```
4. Save (会自动更新已 published 文章)

### Why
- **dogfooding 失败也是有价值的 spike 数据** — 证明 web-agent 不是"什么都能跑"的魔术工具, 有明确能力边界 (actuator 5 actions). 落档边界比假装能跑更负责
- LOOP_DETECTED anti-loop **保护用户数据完整性** = 项目 V0.5.0 设计意图被实证: LLM 可能盲目 retry, anti-loop 是必须的 safety net
- 能力边界 + 触发条件 + V0.17+ TODO 落档, 后人接手不会以为这是 bug 或反复尝试

### Real-account E2E 累积更新 (含 V0.16.31 spike fail)

| 版本 | 平台 | 任务 | 结果 |
|---|---|---|---|
| V0.16.17 | Gmail | compose + send | ✅ SUCCESS |
| V0.16.27 中文 | dev.to | save draft (避开 Publish) | ✅ SUCCESS |
| V0.16.27 英文 | dev.to | save draft (避开 Publish) | ✅ SUCCESS |
| V0.16.30 | dev.to | publish (主动 click Publish) | ✅ SUCCESS |
| **V0.16.31** | **dev.to** | **edit existing append** | **❌ LOOP_DETECTED (能力边界)** |

4/5 = 80% 真账号 E2E 成功率, 失败的 1 个**根因明确 + V0.17+ 有修复路径**, 不是设计 bug.

### Compatibility
- 主代码零改动 (只 CHANGELOG + bump), 行为 100% 与 V0.16.30 一致
- 255 passed + 2 skipped, ruff 0, mypy strict 0
- bump: pyproject.toml + `__init__.py` `0.16.30` → `0.16.31`

## [0.16.30] - 2026-05-05

### Add (博客 2 publish 到 dev.to + V0.16.27 双向对照 verify + README Featured Blogs 升级)

V0.16.29 ship 博客 2 draft 后, 用户决定 publish 到 dev.to. 本版 = web-agent dogfooding 第 2 次 (这次直接 Publish 不是 Save Draft) + V0.16.27 双向对照 verify 落档.

#### 博客 2 已 publish (web-agent dogfooding 第 2 次)
- **dev.to URL**: https://dev.to/francise_liang_e4544eadb9/why-i-permanently-no-god-patchright-after-a-spike-and-the-anti-detection-decision-tree-3m11
- **跑法**: `WEB_AGENT_AUTO_APPROVE='*' uv run web-agent "..." --url https://dev.to/new --max-steps 30 --max-wallclock-s 600`
- **执行轨迹**: 9 step / 总用时 3.4 min (203s)
  - step 0-1: click [7] 标题 + type "Why I Permanently NO-GO'd Patchright After a Spike (And the Anti-Detection Decision Tree)"
  - step 2-4: click [9] tags + type "ai, llm, webagent, playwright" + 选 dropdown [16] (中段多 1 step)
  - step 5-6: click [31] body + 一次性 type 整段 markdown
  - step 7: **click [33] Publish** (LLM 主动按 goal 反向约束 click Publish 不是 Save Draft)
  - step 8: extract 确认 "Edit/Manage/Stats 按钮 + 无 Unpublished Post pink banner" → 已 publish
  - step 9: done `PUBLISHED:patchright NO-GO 已公开发布`
- **关键证据**: LLM thought "Publish 按钮对应元素编号 33，位于 Save Draft 左边，颜色更深更突出" — **主动按 goal 约束 click Publish**

#### V0.16.27 + V0.16.30 双向对照 verify (web-agent safety controlled by env)

V0.16.27 (Save Draft, 主动避开 Publish) + V0.16.30 (Publish, 主动 click Publish) 形成双向对照, 证明 web-agent 的 W3-A safety 是 **controlled by env (auto_approve) + goal 约束**, 不是 hardcoded:

| 版本 | env | goal 约束 | LLM 行为 |
|---|---|---|---|
| V0.16.27 | `AUTO_APPROVE='*'` | "click Save Draft 不是 Publish" | 主动避开 [Publish], click [Save Draft] |
| V0.16.30 | `AUTO_APPROVE='*'` | "click Publish 不是 Save Draft" | 主动按 goal click [Publish] |

#### Real-account E2E 累积 (4 次全成功, 覆盖 send/draft/publish 3 类敏感动作)

| 版本 | 平台 | 任务 | 步数 | 用时 | LLM 行为 |
|---|---|---|---|---|---|
| V0.16.17 | Gmail | compose + send | ~10 | ~3 min | safety auto_approve='send-or-pay' 放行 Send |
| V0.16.27 中文版 | dev.to | save draft | 9 | 2.5 min | 主动避开 Publish, click Save Draft |
| V0.16.27 英文版 | dev.to | save draft | 9 | 3.4 min | 同上 |
| V0.16.30 | dev.to | **publish (公开)** | 9 | 3.4 min | **主动 click Publish (按 goal 反向约束)** |

#### README Featured Blogs 升级 (1 → 2 篇)
- **`README.md`** 把 "Featured Blog" 单数改 "Featured Blogs" 复数, 加博客 2 链接 + 7 min read estimate + V0.16.30 dogfooding tag
- 双向引流: GitHub 访客 → dev.to 文章 1/2 互推 (减少 bounce)

### Why
- 博客 2 publish (vs V0.16.29 仅 ship draft) = 知名度 α 路径下的内容资产 ship, 不算分发 (dev.to feed 自然推送 + GitHub topics 长尾, 不需要 HN/Reddit 主动投放)
- web-agent dogfooding 第 2 次 (直接 publish) **完整 safety 双向证据** — 比 V0.16.27 单向 (仅 Save Draft) 更强, 是项目最强的真账号 E2E demo

### 不包含 (用户做)
- **修博客 1 dev.to 加 cross-link 到博客 2**: 互引流, 用户手动 1 分钟 OR web-agent dogfooding 第 3 次 (edit existing article 流程未验证, 6-10 step web-agent task)
- **GitHub Release v0.16.30**: 用户手动 OR 等下次 milestone

### Compatibility
- 主代码零改动, 行为 100% 与 V0.16.29 一致
- 255 passed + 2 skipped, ruff 0, mypy strict 0
- bump: pyproject.toml + `__init__.py` `0.16.29` → `0.16.30`

## [0.16.29] - 2026-05-05

### Add (第 2 篇博客 ship: patchright NO-GO + 反检测决策树故事)

V0.16.28 α 路径微优化后, 用户选 C (第 2 篇博客). 主题: 反检测决策树 — V0.16.14 patchright spike NO-GO + V0.16.15 curl_cffi NO-GO + 住宅代理 GO. 中英双版 + picture-gen 头图 + mermaid 决策树.

#### 文件
- **`docs/blog-drafts/2026-05-patchright-nogo-final.md` 新建** (~1500 字中文): 标题 "为什么我跑了 spike 后把 patchright 永久 NO-GO 了 — 反检测决策树的故事". 8 段 (背景 / spike 设计 / 实测数据 A=C 19/32 / 根因 launch vs CDP 接管 / 否决理由 + flowchart / curl_cffi 关联 NO-GO / 决策树 / 教训 + repo CTA)
- **`docs/blog-drafts/2026-05-patchright-nogo-final-en.md` 新建** (~1500 字英文翻译): 标题 (HN-friendly) "Why I Permanently NO-GO'd Patchright After a Spike (And the Anti-Detection Decision Tree)". 共享 hero + mermaid (英化标签)
- **`docs/blog-drafts/assets/hero-patchright.jpg` 新建 80KB**: picture-gen 主题"3 paths shown side by side - patchright (X), curl_cffi (X), residential proxy (✓), Chrome at center", 复用博客 1 蓝橙双色调风格

#### 配图 (mermaid 内嵌)
- **xychart-beta sannysoft.com PASS scores bar chart**: A 19 / B 21 / C 19, 视觉化 A==C
- **flowchart 否决理由 (§4)**: patchright upgrade decision branches (launch_persistent_context vs connect_over_cdp), 都收敛到永久 NO-GO
- **flowchart 反检测决策树 (§6)**: 4 检测层 (JS / CDP / TLS / IP) × 4 工具 (stealth / patchright / curl_cffi / 住宅代理) 选择映射

#### Why
- 博客 1 (W5-C.2 spike) 主题是"测量层 regex 假阴性", 偏 LLM 工程; 博客 2 (patchright NO-GO) 主题是"反检测分层架构选择", 偏 web 自动化工程 — 两个不同 niche audience 双覆盖
- patchright spike 数据 (A==C 19/32 完全相同) + 根因 (launch vs takeover 层) 故事完整, 适合 dev.to 技术 deep-dive
- 反检测决策树作为博客 2 卖点 — 让"也在做 web 自动化项目用 connect_over_cdp" 的开发者直接采纳 NO-GO 结论, 省 1-2h spike 时间, 比博客 1 的"省 27h" 数字小但 audience 大 (web 自动化广 vs LLM 工程窄)

#### 不包含 (用户做)
- **博客发布**: V0.16.29 仅 ship 中英 draft 到 GitHub (audit trail). 用户接受 α 路径 (静态收益), 不主动分发. 但博客 2 内容若用户后续决定 publish 到 dev.to, web-agent dogfooding 路径已在 V0.16.27 验证 — 直接复用
- **修博客 1 dev.to 文章加 cross-link**: 让 dev.to 文章 1 末尾链接到博客 2 dev.to URL (如果 publish), 互引流. 当前博客 2 未 publish 暂不修

### Compatibility
- 主代码零改动, 行为 100% 与 V0.16.28 一致
- 255 passed + 2 skipped, ruff 0, mypy strict 0
- bump: pyproject.toml + `__init__.py` `0.16.28` → `0.16.29`

## [0.16.28] - 2026-05-05

### Add (开源推广 α 路径微优化: README Featured Blog + Discussions + Release)

V0.16.27 dev.to publish 后 HN dead + Reddit account deleted (反垃圾命中), 用户接受 α 路径 (静态收益 + 长尾 SEO), 不再多渠道分发. V0.16.28 = 3 微优化收尾 (零分发风险, 纯项目卫生).

- **`README.md` 顶部加 "📝 Featured Blog" 段**: 链接到已 publish 的 dev.to 英文版 ("50% Compliance, Not 0%: How a Logging Spike Almost Triggered the Wrong Architecture Rewrite"), GitHub 访客 → dev.to 反向引流, 1 段 elevator pitch
- **`README.md` CHANGELOG badge** V0.16.24 → V0.16.28
- **GitHub Discussions 开启** (`gh api PATCH ... has_discussions=true`): 路过 contributor 有讨论入口, 比 Issues 更友好 (Q&A 类讨论)
- **GitHub Release v0.16.27 创建** (`gh release create v0.16.27`): release 出现在 repo sidebar + GitHub user feed + email subscribers, SEO 加成. notes 含 V0.16.16-27 spike 闭环 + dev.to dogfooding 亮点

### Why (α 路径定位)
- HN dead (24h 等 dang 申诉) + Reddit account deleted (永久) 后, 主动多渠道分发暂停 — 防新账号反垃圾 ML 跨平台叠加 detection
- 静态收益预期值 (1 年): dev.to 500-1500 views, GitHub 10-30 stars (诚实数字, 不画饼)
- 3 微优化都是项目卫生不算分发: README 反向引流 + Discussions 入口 + Release SEO 加成

### Compatibility
- 主代码零改动, 行为 100% 与 V0.16.27 一致
- 255 passed + 2 skipped, ruff 0, mypy strict 0
- bump: pyproject.toml + `__init__.py` `0.16.27` → `0.16.28`

## [0.16.27] - 2026-05-05

### Add (英文版博客 + dev.to 草稿真账号 E2E verify dogfooding)

V0.16.26 ship 中文 final 后, 用户测试 web-agent dogfooding 发 dev.to 草稿成功, 但反馈 "希望英文版" (dev.to 主流英文社区受众). V0.16.27 = 翻译英文 final + 落档 dev.to 真账号 E2E verify (V0.16.17 W3-C Gmail 同模式的姊妹 verify).

#### 英文版博客 ship
- **`docs/blog-drafts/2026-05-w5c2-spike-story-final-en.md` 新建** (~250 行翻译): 标题选 HN-friendly "50% Compliance, Not 0%: How a Logging Spike Almost Triggered the Wrong Architecture Rewrite" + 完整 7 段对照中文 final + 共享 hero.jpg + 共享 mermaid quadrantChart/timeline (mermaid 标签英化)
- **中文 final 顶部链接更新**: `[中文 / English](#)` → `中文 / [English](2026-05-w5c2-spike-story-final-en.md)` (双向跳转)

#### dev.to 草稿真账号 E2E verify (V0.16.17 W3-C 姊妹)
- **实测**: V0.16.27 用 web-agent 自己 dogfooding 发布短版到 dev.to 草稿成功
- **跑法**: `WEB_AGENT_AUTO_APPROVE='*' uv run web-agent "..." --url https://dev.to/new --max-steps 30 --max-wallclock-s 600`
- **执行轨迹**: 9 step / 总用时 2.5 min (vs 拟人键入估 16 min, 快 6×)
  - step 0-1: click [7] 标题 textarea + type 标题
  - step 2-3: click [9] tags input + type 4 个 tags
  - step 4-5: click [30/31] body textarea + **一次性** type 整段 markdown (~500 字)
  - step 6: click [35] **Save Draft** (LLM 主动避开 [34] Publish, 按 goal 约束执行)
  - step 7: extract 确认 "Unpublished Post" pink banner
  - step 8: done `SAVED:已保存为草稿`
- **关键证据**: LLM thought 自述 "需要点击 Save Draft 按钮 (mark_id=35) 来保存草稿，而不是 Publish 按钮 (mark_id=34)" — 主动避开危险按钮
- **dogfooding 故事点**: "用 web-agent 自己发布关于 web-agent 的博客" 完整证据链 + 真账号 E2E 实测通过 (V0.16.17 Gmail 之后第二个真账号 E2E)

#### 前置 spike (web-agent 看 dev.to 编辑器 SoM 标注能力 verify)
- **跑法**: `uv run web-agent "...截图列出 fields..." --url https://dev.to/new`
- **结果**: 27 marks 全标到, 含 [7] 标题 / [9] tags / [23] body / [24] Publish / [25] Save Draft 等关键 fields, 满足 W3-C 安全约束 (主动 click [25] 不 [24])

### Why
- 用户中文母语但 dev.to/HN 主流英文受众, 中文版 dev.to 触达低. 翻译英文版补全两渠道
- W3-C V0.16.17 真账号 E2E (Gmail compose) 之后, dev.to 草稿是第二个真账号 E2E — 证明 web-agent 在**主流 SaaS 平台 (Gmail, dev.to)** 都能 dogfooding
- web-agent 9 step 2.5 min 真发草稿 = 故事最强证据 ("用 web-agent 自动写博客发到 dev.to")

### 不包含 (待用户做)
- **Publish (公开发布)**: V0.16.27 仅 ship 草稿. 用户 dev.to web 端审改 + 点 Publish 公开
- **知乎手动发**: V0.16.26 推荐路径不变 — markdown 复制到知乎编辑器 + mermaid 截 GitHub render 上传 + hero.jpg 上传
- **更长版 dogfooding**: 用户审完后如果觉得短版 ROI 高, 不必发完整 7 章版到 dev.to (markdown 5KB 拟人键入 16 min 不实用)

### Real-account E2E verify 累积
| 版本 | 平台 | 任务 | 步数 | 用时 | 主动避开危险按钮 |
|---|---|---|---|---|---|
| V0.16.17 | Gmail compose | 写邮件 + 发送 | ~10 | ~3 min | ✓ (safety auto_approve 放行 Send) |
| V0.16.27 | dev.to publish | 写草稿 + 保存 | 9 | 2.5 min | ✓ (LLM 主动 click Save Draft 避开 Publish) |

### Compatibility
- 主代码零改动, 行为 100% 与 V0.16.26 一致
- 255 passed + 2 skipped, ruff 0, mypy strict 0
- bump: pyproject.toml + `__init__.py` `0.16.26` → `0.16.27`

## [0.16.26] - 2026-05-05

### Add (博客 final 版本: 删 draft markers + 强化 CTA + rename `-final.md`)

V0.16.25 ship draft + 配图后, 用户要求"直接给可发布版本". 本版去掉所有 draft placeholder, 调整为可直接 copy-paste 到 dev.to / 知乎 / 微信公众号的 final 版本.

- **`docs/blog-drafts/2026-05-w5c2-spike-story.md` → `2026-05-w5c2-spike-story-final.md`** (rename, 文件名表"final" 状态)
- **顶部加发布元数据**: 阅读时长估 8 分钟 + 中英版本占位 (英文版用户后翻) + 作者 GitHub 链接 + 改 H2 sub-title 从"7 版本闭环"到"spike 闭环 · 阅读约 8 分钟" 标注准更准
- **TL;DR 强化**: "TL;DR" 加粗 + 末尾加项目自介 ("开源 web-agent 项目 7 版本闭环节选"), 让首段直接传达"项目链接是干货"
- **删末尾 "待补 (发布前)" 段** (V0.16.24 的 draft marker, V0.16.26 不再是 draft)
- **重构 `## 7. 数据 + 代码` 段为 final 段**:
  - 加 emoji 视觉锚点 (📊📖🔧🧪) 让链接列表扫读快
  - 加可复现 spike 的 ~5 行 bash 代码块 (clone / sync / playwright install / WEB_AGENT_SPIKE_W5C2=1 跑批 / reaggregate)
  - 加 "项目: web-agent" 段独立给 repo 自介 + star/fork/PR 邀请 + CONTRIBUTING 链接
  - 强化结尾 CTA: "如果你...这个数据可能省你 27 小时" + "评论欢迎讨论" 提 1 个开放问题 (你的 spike 流程怎么避免类似测量层假阴性)
- **末尾加发布 attribution**: "转载请注明来源 + repo 链接. 同步发布于 dev.to / 知乎 / Hacker News."

### Why
- draft 末尾"待补"段对发布无用 (用户已选好标题 / 配图已 ship), 留着反而显示 "未完工" 信号
- final 段的 emoji + bash 复现代码 + repo 自介都是 "调到可直接发" 必要项: dev.to / 知乎 用户 5-10 秒决定要不要往下读, 这些视觉锚点 + 可执行命令是关键钩子
- 发布元数据 (阅读时长 / 作者) 是 dev.to / Medium 标准做法, 提升点击率

### 关于英文版
本次仅 ship **中文 final 版本**. 英文版 (dev.to 主流英文社区受众) 留用户用 ChatGPT/DeepL 翻译现版即可, 不在本 commit scope. 如果英文翻译需求强 (post-launch), V0.16.27 可起独立 spike 推 `2026-05-w5c2-spike-story-final-en.md`.

### 立即可发布的渠道映射
| 渠道 | 文件复制方式 | mermaid 处理 | 发布 emoji 适配 |
|---|---|---|---|
| **dev.to** | markdown raw 直接 paste | 原生 render ✓ | 全保留 |
| **知乎** | markdown 复制到富文本 | 截图 GitHub render 后贴图 | 部分保留 (复杂 emoji 渲染弱) |
| **微信公众号** | markdown 复制到 mdnice (markdown 编辑器) | 截图 + 图床 | 全保留 |
| **Hacker News** | 标题党 + 链接 dev.to 文章 | N/A | 不在 HN |

### Compatibility
- 主代码零改动, 行为 100% 与 V0.16.25 一致
- 255 passed + 2 skipped, ruff 0, mypy strict 0
- bump: pyproject.toml + `__init__.py` `0.16.25` → `0.16.26`

## [0.16.25] - 2026-05-05

### Add (博客 draft 配图: 头图 + 2 张 mermaid 数据图)

V0.16.24 ship 博客 draft 后, 用本机 picture-gen agent (Pollinations.ai 后端) 生成头图 + 嵌 2 张 mermaid 数据可视化, draft 现可直接发布 (用户审改后).

- **`docs/blog-drafts/assets/hero.jpg` 新建** (64KB JPG): picture-gen prompt B "developer staring at screen showing compliance 0% with thought bubble revealing actual 50%" + style anchor "modern flat tech illustration, bold composition, high contrast". 蓝橙双色调 + 单一主角 + thought bubble, HN/Twitter 缩略图视觉冲击强. 注: Pollinations diffusion 文字渲染弱 (屏幕上数字乱码), 但博客头图不靠精确文字传故事
- **`docs/blog-drafts/2026-05-w5c2-spike-story.md` 顶部嵌 hero image** (`![hero](assets/hero.jpg)`)
- **决策矩阵段加 mermaid quadrantChart**: 4 象限 + 3 版本数据落点 (V0.16.20 [0,0.45] noise / V0.16.21 [0,0.65] 假阴性 / V0.16.22 [0.5,0.5] 真 verdict ⭐), 视觉化 spike 数据演进路径
- **加新段 "## 6. 7 版本闭环" + mermaid timeline**: V0.16.16 / V0.16.20 / V0.16.21 / V0.16.22 关键节点, 每节点 2-3 行事件描述 (DEFER 落档 / 跑批 / 修 / reaggregate / 真 verdict). 原 "## 6. 数据 + 代码" → "## 7. 数据 + 代码"
- **修决策矩阵 markdown 表格** (V0.16.24 误把 compliance/success 用 "/" 合并到一列): 拆 3 列 (compliance | success | verdict), 4 行各自列出 verdict 条件 + 行动

### Why
- 头图是 dev.to / HN / Twitter 缩略图的关键视觉信号, 直接影响点击率
- mermaid 数据图 (quadrantChart + timeline) 在 GitHub / dev.to / Notion 原生 render, 不依赖外部图床, 知乎发布需用户截图
- picture-gen 走 Pollinations diffusion (零依赖, 免费 API), 与 matplotlib (要 dev dep) 相比 ROI 高
- 用 picture-gen 生成 1 张头图 (~30s) 比用户自己开 Figma/Canva 5 分钟更快

### 不包含 (用户做)
- **博客发布**: V0.16.25 仅 ship 配图. 用户审改 draft + 选标题 (3 候选) + 发 dev.to / 知乎 / HN
- **mermaid → 截图**: 知乎/微信发布时浏览器截图 GitHub render 后的 mermaid (dev.to / GitHub 原生 render)
- **更多概念图**: 候选 C (测量仪 + 放大镜抽象图) 等待 V0.16.25 反响后决定要不要做

### Compatibility
- 主代码零改动, 行为 100% 与 V0.16.24 一致
- 255 passed + 2 skipped, ruff 0, mypy strict 0
- bump: pyproject.toml + `__init__.py` `0.16.24` → `0.16.25`

## [0.16.24] - 2026-05-05

### Add (开源推广周边补全: 博客 draft + CI badge + CONTRIBUTING.md)

V0.16.23 LICENSE/README/topics 把开源基础打好后, V0.16.24 补开源推广路径上的"周边" — 博客分发载体 + 社区入口 + 第一印象信号.

- **`docs/blog-drafts/2026-05-w5c2-spike-story.md` 新建** (~1500 字): 第一篇博客 draft, 主题 "我差点重写整个规划层 — 一个 regex 假阴性的故事 (W5-C.2 spike 7 版本闭环)". 6 段结构: 引子 / V0.16.20 跑批 / V0.16.21 4 根因修 / V0.16.22 reaggregate 关键发现 / 真 verdict + 教训 / repo 链接. 末尾"待补"列待用户做的: 配 4-5 张图 + 选标题 (中/英/HN 党 3 备选) + 发布渠道 + 评论区高频问答准备
- **`README.md` 加 CI badge**: 顶部 5 badges → 6 badges, 加 GitHub Actions CI badge (workflows/ci.yml), 第一印象信号 + ruff/mypy/pytest 三层 release gate 公开可见
- **`CONTRIBUTING.md` 新建** (~50 行): dev setup + 跑测试 (3 层 release gate) + Conventional Commits 风格 + 代码风格 (mypy strict / ruff line-length=110) + PR 流程 + **Spike/决策落档习惯** (鼓励 PR 同时落档 ARCHITECTURE §1.X) + bug 报告模板

### Why
- LICENSE/README/topics 是基础(repo 看起来正经), 但**没博客分发没人看到** — 博客是知名度路径上的关键动作
- W5-C.2 spike 7 版本闭环故事曲折度高 (触发条件 ③ 看似命中 → 测量假阴性发现 → 真 verdict)，对 LLM 工程读者代入感强 ("我以为 augmentation 不工作, 结果 regex 骗了我"), HN 党风格容易上首页
- CI badge 是 GitHub README 第一印象信号: 绿色 → 项目 active 维护 + 测试覆盖好
- CONTRIBUTING 是社区门槛降低: 没 CONTRIBUTING 大部分人不会发 PR, 有了直接看到 "怎么参与"

### 不包含 (留下一步)
- **博客发布**: V0.16.24 仅含 draft, 用户审改后自发 dev.to / 知乎 / HN. 配图 + 选标题 + 发布渠道 / 评论区准备见 draft "待补" 段
- **demos/ 加 README + GIF**: 候选 #2, 等博客发出第一波流量后再做 (用真实访客反馈优化优先级)
- **V0.17 Action discriminated union 重构**: 工程清债, 知名度路径上是绕路

### Compatibility
- 255 passed + 2 skipped (无新 test 也无改动测试), ruff 0, mypy strict 0
- 主代码零改动, 行为 100% 与 V0.16.23 一致
- bump: pyproject.toml + `__init__.py` `0.16.23` → `0.16.24`

## [0.16.23] - 2026-05-05

### Add (开源准备: LICENSE + README 大改 + pyproject.toml 元数据)

V0.16.0-22 的工程闭环 (W1-W5 + MCP server + 反检测决策树 + W5-C.2 spike 7 版本闭环) 已成熟到可推动开源知名度. 本版 = repo 元数据补齐 + README 故事化重写, 不动主代码.

- **`LICENSE` 新建 (MIT)**: copyright 2026 francise. MIT 选定理由: 个人项目最低门槛 + 鼓励 fork + AS IS 完全免责; 不选 Apache (专利条款个人项目过度) / GPL/AGPL (劝退社区贡献者)
- **`README.md` 大改 (前 31 行重写, L43-67 上手流程改 V0.16.19+ 1 步, 第二段插"项目特色" + "4 种集成方式" 表)**:
  - **顶部 5 个 badges**: License: MIT / Python 3.12+ / tests 255 / mypy strict 0 / CHANGELOG V0.16.23
  - **Elevator pitch 1 段**: "MultiOn 风格的高度拟人 Web Agent — Python + Playwright + VLM/SoM + stealth, BYO LLM. 接管你已登录的 Chrome..."
  - **"项目特色" 段** (新): 决策驱动 spike 闭环 (patchright/curl_cffi/W5-C.2 三个落档故事) / 可观测 / 三层 release gate / MCP server
  - **"4 种集成方式" 表** (新): MCP stdio / CLI / Python import / demos
  - **stale 段修复**: L9 V0.16.13 → V0.16.23, L43-67 终端 A/B 双终端流程 → V0.16.19+ auto-spawn 1 步, L276 测试数 219 → 255, L281 ARCHITECTURE V0.15.2 → V0.16.22
- **`pyproject.toml` `[project]` 加元数据**:
  - `license = "MIT"` + `license-files = ["LICENSE"]` (PyPI 兼容)
  - `keywords` (9 个): web-agent / playwright / browser-automation / mcp / claude / anthropic / set-of-mark / stealth / multion (GitHub 搜索 + PyPI 分类用)
  - `classifiers` (9 个): Development Status 4 - Beta / Intended Audience Developers / Linux + macOS / Python 3.12 / Internet HTTP Browsers / Libraries Python Modules / Typing Typed

### Why
- V0.16.0-22 工程闭环 (W1-W5 / MCP server / 反检测决策树 / W5-C.2 spike) 已经做到 production-ready, 知名度路径自然下一步
- web-agent 领域 (browser-use 30k stars / Skyvern 12k / Stagehand 8k) 全部开源, 个人项目闭源**没有先例**
- 5 个 badges + "项目特色" 段让 GitHub 访客 5 秒内 grok 项目卖点, 不必读 ARCHITECTURE 全文
- LICENSE 选 MIT: 个人项目最低门槛 + 鼓励 fork + AS IS 免责 (滥用法律责任在 fork 者)
- README stale 段 (V0.16.13 状态行 + 终端 A/B 上手流程) 长期与 .env.example / ARCHITECTURE / pyproject.toml 不一致, 第一次推 GitHub trending 前必须修

### 不包含 (留下一步)
- **GitHub repo metadata** (topics / description / homepage): 用户跑 `gh repo edit --add-topic ...` 命令配置, 不进 commit
- **博客发布**: V0.16.23 commit 仅含 LICENSE + README + pyproject 元数据. 第一篇博客 (W5-C.2 spike 7 版本闭环 / 反检测决策树二选一) 大纲在 commit 后单独给

### 不会暴露的 (开源安全)
- `.env` (gitignore, ANTHROPIC_API_KEY 等真 key)
- `~/.config/web-agent-chrome/` (本地 Chrome user-data-dir, Gmail/GitHub 真账号 cookies)
- `~/.cache/web-agent/spike-w5c2/` (跑批个人数据)
- `data/trace.db` / `data/memory.db` / `data/screenshots/` / `data/replays/` (gitignore)

会公开的代码 + 决策方法论 (ARCHITECTURE 各种 NO-GO/DEFER) **本身是资产** — 展示 spike 决断能力, 是个人品牌而非"泄露技术细节".

### Compatibility
- 255 passed + 2 skipped, ruff 0, mypy strict 0 (元数据改动不影响测试)
- 主代码零改动, 行为 100% 与 V0.16.22 一致
- bump: pyproject.toml + `__init__.py` `0.16.22` → `0.16.23`

## [0.16.22] - 2026-05-05

### Add (W5-C.2 spike regex 第三轮校准 + reaggregate 工具 + **真 verdict: 维持 DEFER**)

V0.16.21 重跑显示 M3 decompose=0% 落矩阵间隙. subagent 抽样 6 长任务 jsonl 发现 LLM 实际用 3 种 subgoal 表达 ("子任务 N" / "Subgoal:" / "第N步"), V0.16.21 regex 只命中 "第N步" 1 种 → 测量层假阴性. V0.16.22 regex 第三轮校准 + reaggregate 现有 jsonl 后 — **真 verdict: 维持 DEFER (decompose subset compliance=50% / success=50%, 落矩阵 #2)**.

#### Regex 第三轮校准
- **`src/web_agent/loop.py` _SPIKE_M1_RE 加 2 条**: `子任务\s*[一二三四五六七八九十0-9]+` (LLM 复述 prompt "子任务 N" 字样, label 18/20 实测 10 次) + `\bsubgoal\b` (英文裸词 "Subgoal:" 模板, label 15)
- **`src/web_agent/loop.py` _SPIKE_M2_RE 加 5 条**: `(?:目前|当前|现在)\S*?(?:子任务|subgoal)` 引用模式 + `子任务\s*[一二三四五六七八九十0-9]+\s*[:：]` 裸子任务标号持续 plan reference (label 20 实测 8 次) + `\bSubgoal\s*[:：]` 英文模板 + `已完成子任务\s*[一二三四五六七八九十0-9]+` + `currently\s+working\s+on\s+(?:subgoal|subtask)`
- **`tests/test_loop_spike_w5c2.py` 加 9 case**: M1 中文/英文 subgoal/Subtask + M2 子任务标号/已完成/working on

#### `scripts/reaggregate_w5c2.py` 新建 (~75 行)
- 不重跑 spike (V0.16.21 jsonl thought 原文已存, 重跑要 80 min + LLM 调用), 只用当前 regex 重判 M1/M2/M5 + 重出 summary
- 第一步备份 jsonl 到 `~/.cache/web-agent/spike-w5c2-v021-backup/` 保 V0.16.21 audit trail (subagent 推荐 α: 失去原始 = 失去 delta 复盘能力)
- 复用 `scripts/run_w5c2_spike.py` 的 `print_summary()` (sys.path import scripts/)
- 跑法: `uv run python scripts/reaggregate_w5c2.py`

#### V0.16.22 reaggregate 数据 (vs V0.16.21)

| 指标 | V0.16.21 | V0.16.22 | Δ |
|---|---|---|---|
| M1 per step | 9% | **32%** | +23pp |
| M2 per step | 0% | **25%** | +25pp |
| M3 all | 20% | 35% | +15pp |
| **M3 decompose** | 0% | **50%** | +50pp |
| M4 all | 0% | 15% | +15pp |
| **M4 decompose** | 0% | **50%** | +50pp |
| **compliance decompose** | 0% | **50%** | +50pp |
| compliance all | 0% | 15% | +15pp |
| M5 | 25% | 25% | - |
| success rate | 65% | 65% | - (regex 不影响 success) |
| success decompose | 50% | 50% | - |

**V0.16.21 M2/M3/M4 全 0% 是 regex 假阴性导致的测量假性, augmentation 实际在长任务上有 50% compliance**.

#### 真 verdict: 维持 DEFER (ARCHITECTURE §1.5 矩阵 #2)

decompose subset (n=6, augmentation 实际目标群):
- compliance 50% ∈ 30-80% ✓
- success 50% ∈ 50-70% ✓
- → **矩阵 #2: 维持 DEFER**

**不立项 W5-C.2 plan-and-execute 对照 spike** (~3h):
- augmentation 能让 50% 长任务前 3 步开局拆 plan (M3 decompose) + 50% 后续 follow plan (M4 decompose)
- plan-and-execute 改进空间 ≤ 50%, 当前 success 50% 已 OK 水平
- 触发条件 ③ (plan-and-execute 失败率低 >20%) 失去 motivation — augmentation 已工作
- 触发条件 ① (用户反馈 augmentation 失败案例) 仍是未来 trigger, 不强主动跑

**all 数据观察 (compliance all=15% / decompose=50%)**: `should_decompose()` 阈值精准 — augmentation 仅对长任务启动, 短任务不浪费 token. M1 短任务步骤普遍不命中是设计正确, 不是缺陷.

#### W5-C.2 spike 闭环 (V0.16.16 → V0.16.22, 7 版本)
- V0.16.16: subagent 调研 + DEFER 落档 + 3 触发条件
- V0.16.20: spike instrumentation ship + 跑批 (4 根因 invalidate 数据)
- V0.16.21: 4 根因修复 (Chrome respawn / 字数 / _judge / regex 第二轮) + 重跑 (regex 假阴性露出)
- V0.16.22: regex 第三轮校准 + reaggregate + **真 verdict 维持 DEFER**

augmentation 路线获得 50% compliance 数据底座, W5-C.2 立项 motivation 显著降低.

### `docs/ARCHITECTURE.md` §1.5 加 V0.16.22 真 verdict 段
- reaggregate 数据表 + DEFER 落格证据
- 决策矩阵新观察: compliance all=15% / decompose=50% 揭示 should_decompose 阈值精准

### Compatibility
- 255 passed + 2 skipped (10 spike test function 不变, 加 9 case 在现有 function 内), ruff 0, mypy strict 0
- 主 path 行为 100% 与 V0.16.21 一致 (默认 noop)
- bump: pyproject.toml + `__init__.py` `0.16.21` → `0.16.22`

## [0.16.21] - 2026-05-05

### Fix (V0.16.20 W5-C.2 spike 跑批 4 根因修复 — 重跑前置, 数据可信度审核后)

V0.16.20 跑出 stdout 显示 compliance=0% / success=45% / decompose subset n=2, 看似落 "compliance<30% ∧ success<50% → 触发条件 ③ 候选" (跑 plan-and-execute 对照 spike, 工时 ~3h). **但 4 个根因检查后数据不可信**, 直接触发 ③ 风险高 (修复重跑后 compliance 可能升至 30%+ 导致决策反转, 那 3h 对照 spike 浪费). V0.16.21 = 修复 4 根因 + 重跑前置.

#### 4 根因 + 修复

1. **Chrome 9 任务后 GPU SwiftShader 死锁** (Plan subagent 诊断: duckduckgo paint pipeline hang, GPU 进程累 53min CPU, CDP 共享 GPU 进程导致 close+reconnect 无效, 必须 kill 进程级重启). label 14-20 (7 任务) 全 SCRIPT_ERROR Timeout 30000ms, jsonl 0 字节, **实际有效样本只剩 13/20**
   - **`scripts/run_w5c2_spike.py` 加 `_kill_chrome_and_respawn()` helper**: pkill -9 + sleep 2s + ensure_chrome_running 重 spawn. 总 ~3-5s overhead per call
   - **L1 防御 (retry)**: SCRIPT_ERROR Timeout 后 kill+respawn + retry 1 次
   - **L3 防御 (周期重启)**: 每 KILL_EVERY=5 任务主动 kill+respawn, env `WEB_AGENT_SPIKE_KILL_EVERY` 可调
   - 跑批 overhead 增量: 4 次 respawn × ~3s ≈ 15s
2. **设计字数估错**: 4 个长任务 (label 15/16/18/20) 实际 166-189 字 < 200 阈值 → augmentation 路线只对 2 个任务注入 hint (04/17, 17 还挂了) → 真实 augmentation 测试 **n=1**
   - **`scripts/run_w5c2_spike.py` 4 任务 goal 拼到 ≥220 字** (15: 180→317; 16: 166→340; 18: 172→475; 20: 189→369)
   - 全 6 个长任务 (04/15/16/17/18/20) 现 should_decompose=True 验证通过
3. **`_judge()` false success bug**: V0.16.20 task 04 result=`LOOP_DETECTED 在 step 16` 但 expect 'Dutch' 命中中途 extract answer → success=True (任务实际 abort)
   - **`_judge()` 加 FAILURE_MARKERS 短路**: 任务异常退出 (LOOP_DETECTED / WALLCLOCK / LLM_FAILED / SAFETY_BLOCK / SCRIPT_ERROR / max_steps) 直接 False, 反指标 expect_safety_block 仍正向判 SAFETY_BLOCK 命中
4. **M1/M2 regex 假阴性**: task 04 step 0/2 thought 用"第一步/第二步/第三步" (subagent spot check 证), 是合法 subgoal 标记但 M1 漏判 (M1 原 regex `第\s*\d\s*步` 只匹配阿拉伯数字, 漏中文序数)
   - **`src/web_agent/loop.py` _SPIKE_M1_RE 拓宽**: `第\s*\d\s*步` → `第\s*[一二三四五六七八九十0-9]+\s*步` (中文/阿拉伯通吃)
   - **`src/web_agent/loop.py` _SPIKE_M2_RE 拓宽**: `(?:目前|当前|现在)在\s*(?:第|subgoal|步骤)` → `(?:目前|当前|现在)(?:在|进行到|进入到?)\s*(?:第\s*[一二三四五六七八九十0-9]+|subgoal|步骤)` (加 进行到/进入 + 中文序数)
   - **`tests/test_loop_spike_w5c2.py` 加 5 个 case**: M1 中文序数 (第一步/第二步/第三步) + M2 (目前在第一步/当前进行到第二阶段)

#### V0.16.20 数据 read between the lines (V0.16.21 回看)
- M5=0% 是**真信号** (subagent 抽样确认 task 04 step 3-16 在 Wikipedia stuck 14 步反复找不存在的 'Nationality' 字段, 从未换策略). 即使 regex 校准也不会变.
- compliance=0% 是 **regex 假阴性 + n=1 微样本组合**, 不能直接信 (修复后预期 task 04 thought 改判 M1=True, M3 升至 ≥1/N)

### Why (重跑而非接受弱数据)
- α (接受 V0.16.20 数据触发条件 ③) 风险: 若修复重跑后 compliance 升至 30%+, 决策反转维持 DEFER, 那触发条件 ③ 立项的 plan-and-execute 对照 spike (~3h) 是浪费
- β (修后重跑) 投入 ~2h vs α 浪费风险 → ROI 明显更优
- γ (维持 DEFER 不修) 是认输, 4 根因都是明确可修 bug, 没必要

### 不包含 (留 V0.16.22)
- **重跑数据**: 用户后台跑 ~80 min × 1 round (Anthropic) + 4 次 Chrome respawn ≈ 82 min, 数据 + verdict 落档 V0.16.22
- **plan-and-execute 对照 spike**: 仅在 V0.16.22 数据落 "compliance<30% ∧ success<50%" 才触发, +3h Anthropic-only MVP

### Compatibility
- 255 passed + 2 skipped (10 spike test function, 加 5 个 case 在现有 function 内, count 不变), ruff 0, mypy strict 0
- 默认 spike noop 主 path 100% 与 V0.16.20 一致, env 开关 `WEB_AGENT_SPIKE_W5C2=1` 激活
- bump: pyproject.toml + `__init__.py` `0.16.20` → `0.16.21`

## [0.16.20] - 2026-05-05

### Add (W5-C.2 logging spike instrumentation: 量化 prompt augmentation 是否真在 thought 拆 subgoal)
- **`src/web_agent/loop.py` `_dump_spike_metrics()` + 3 regex (M1/M2/M5)**: `run_react_loop` finally block 1 处调用, task 结束后一次性 dump 每 step 到 jsonl. env `WEB_AGENT_SPIKE_W5C2=1` 激活, 默认 noop. 输出 `~/.cache/web-agent/spike-w5c2/{label}-{task_id}.jsonl`. IO 失败 silent swallow (spike 不该阻塞主路径, 与 memory.record_task 同档)
- **`scripts/run_w5c2_spike.py` 新建** (~280 行): 20 任务清单 (6 个 ≥200 字 should_decompose=True 长任务: label 04/15/16/17/18/20 + 12 个 W1 deterministic 短任务 + 2 个 W3-C SAFETY_BLOCK 反指标 label 15/16) + 跑批 + summary 聚合 + 决策矩阵打印. env `WEB_AGENT_SPIKE_ONLY=01,03,15` 限定 label 跑小样, `WEB_AGENT_SPIKE_TASK_SLEEP_S=15` 调任务间 sleep
- **`tests/test_loop_spike_w5c2.py` 新建 10 case**:
  - 6 regex case: 中文 / 英文 M1 subgoal_marker 命中 + no-match 反例 / M2 plan_referenced 中英 / M5 revision_on_failure
  - 4 dump 行为 case: env 关 noop / env 开写 jsonl schema 字段齐 / W5-D.2 step=-1 synthetic memory_recall 跳过 / IO error silent swallow
- **`docs/ARCHITECTURE.md` §1.5 加 V0.16.20 spike instrumentation 段**: 5 指标定义 + 20 任务设计 + 决策矩阵 (compliance × success → verdict 4 路) + 数据待补 V0.16.21 落档

### Why
- V0.16.16 W5-C.2 DEFER 落档时已写明触发条件 ③ = "前置 spike 数据证 plan-and-execute 失败率比 augmentation 低 >20%". 但要触发 ③, 需先量化**现状**: prompt augmentation 在 thought 字段里**是否真拆** subgoal? 拆得好不好? — 此前**无 A/B 证据**
- V0.16.20 = 把 ARCHITECTURE §1.5 L143 "最低成本前置 spike (1-2h, 不立项)" 提议从 plan 升级为可执行: 工具 ship + 数据采集等用户跑
- 1-2h instrumentation vs 影响 27h 立项决策 → 高杠杆, 与最近 4 版 (patchright/curl_cffi/W5-C.2 自身 DEFER) "spike → 决断" 节奏一致

### 5 指标 (per-step / per-task)
- **M1** subgoal_marker_present (per step): thought 含 subgoal 标记词 ("子目标 / 步骤 N / 第 N 步 / 1./① / first / step N / then / next / finally")
- **M2** plan_referenced (per step): thought 引用整体 plan ("目前在第 2 步 / 当前在 subgoal / 按计划 / according to the plan / as planned")
- **M3** task_has_plan (per task): 前 3 步任意一步 M1=True ("开局有没有拆")
- **M4** plan_consistency (per task): M2 命中步数 ≥ ⌈n/3⌉ ("拆了之后跟着走没")
- **M5** revision_on_failure (per failed step): is_failure_step=True 步下一步 thought 含"换/改/重新 + 策略/方法/思路 / try a different approach / switch strategy / reconsider"

### 决策矩阵 (data → verdict)
- compliance ≥80% ∧ success ≥70% → **升级永久 NO-GO** (augmentation 已够用)
- compliance 30-80% / success 50-70% → **维持 DEFER** (等真实用户反馈触发 ①)
- compliance <30% ∧ success <50% → **触发条件 ③ 候选** (跑 plan-and-execute 对照 spike, +3h Anthropic-only MVP)
- compliance ≥30% ∧ success <30% → **non-LLM 改造** (SoM/actuator 问题, 与 W5-C.2 无关, 另开工单)

### 不包含 (留 V0.16.21)
- **数据本身**: 80 min × 1 round (Anthropic provider) 跑批由用户后台触发, 数据落档延后到 V0.16.21
- **plan-and-execute 对照 spike**: 决策矩阵 "compliance<30% ∧ success<50%" 路径才触发, 非默认要做; 命中后再 +3h 拷贝 anthropic.py 写 plan-and-execute 变体跑同 20 任务
- **retry 机制**: 任务级 retry 1 次脚本侧未实现, 看 V0.16.21 数据是否需要 (MVP 先单跑)

### Compatibility
- 255 passed + 2 skipped (245 + 10 spike test 新加), ruff 0, mypy strict 0 (默认 noop, 主 path 行为 100% 与 V0.16.19 一致)
- bump: pyproject.toml + `__init__.py` `0.16.19` → `0.16.20`

## [0.16.19] - 2026-05-05

### Add (约束 4 软化: auto-spawn Chrome — 9222 不可达自动 spawn)
- **新模块 `src/web_agent/chrome_launcher.py`** (~100 行, stdlib only): 3 个 helper:
  - `check_chrome_alive(cdp_url, timeout=2.0) -> bool`: 9222 健康检查 (urllib, 不抛)
  - `spawn_chrome_detached(script_path, cdp_url, ready_timeout=30.0) -> int`: `subprocess.Popen([bash, script], start_new_session=True, stdio=DEVNULL, close_fds=True)` + 轮询 9222 直到 ready_timeout
  - `ensure_chrome_running(cdp_url, script_path=None)`: 顶层 orchestrator (alive 直接返 / `WEB_AGENT_AUTO_SPAWN_CHROME=false` 抛错引导手启 / 默认开自动 spawn)
- **`src/web_agent/cli.py` L54**: `await asyncio.to_thread(ensure_chrome_running, cdp_url)` 在 connect 之前
- **`src/web_agent/mcp_server.py` `_check_chrome_alive` delegate**: 实现转移到 chrome_launcher, 但保留模块级符号名向后兼容 (test_mcp_server.py L46/57 monkeypatch fixture 不破)
- **`tests/test_chrome_launcher.py` 新建 10 case**: 健康检查 / Popen detached args / 等就绪 / timeout 抛错 / script 缺失 / ensure 路径全覆盖 / env 开关 / 默认 script_path
- **`tests/test_cli.py` patch_run_task_io_chain fixture**: 加 `monkeypatch.setattr("web_agent.cli.ensure_chrome_running", lambda url: None)` 防 IO 边界

### Why
- V0.16.18 之前 onboarding 4 步: ① 终端 A 启 Chrome ② 等启动 ③ 终端 B 设 env ④ 跑 demo. ① 是用户最容易忘的(V0.16.17 Gmail E2E spike 实测过用户问"为什么 ECONNREFUSED")
- V0.16.19 软化为 1 步: 直接 `uv run python demos/wikipedia_search.py "..."` — 不可达自动 spawn, 用户首跑 onboarding 摩擦显著降低
- env 开关 `WEB_AGENT_AUTO_SPAWN_CHROME=false` 给偏好显式控制的用户回退路径 (与 V0.16.18 行为完全一致)
- 设计原则: stdio MCP 模式 stdout/stderr 必须 DEVNULL 防 Chrome log 污染 JSON-RPC; start_new_session 让 Chrome 脱离 Python 进程组父 exit 不带走

### 不解决的限制
- **首登 Gmail 仍需 headed 模式**: auto-spawn 用 CHROME_MODE=auto, 装了 xvfb 就走 xvfb 看不见 GUI. 首登仍要按 V0.16.17 cookbook 显式 `CHROME_MODE=headed bash scripts/start_chrome.sh https://mail.google.com/` 手登一次, 后续 user-data-dir 持久化
- **同 user-data-dir Chrome 单实例锁**: V0.16.20 cookie 导入 spike 待评估

### Compatibility
- 245 passed + 2 skipped (235 + 10 chrome_launcher 新加), ruff 0, mypy strict 0 (21 files, 多 1 个 chrome_launcher.py)
- 现有 V0.16.17 cookbook 流程 100% 仍可用 (用户先手启 Chrome 时 `ensure_chrome_running` 直接返回)
- bump: pyproject.toml + `__init__.py` `0.16.18` → `0.16.19`

## [0.16.18] - 2026-05-05

### Add (Chromium 系 fork 支持: Brave / Edge / Vivaldi / Opera)
- **`scripts/start_chrome.sh` binary 检测**: 4 个 → 11 个 (按优先级):
  - Chromium 原生: `google-chrome` / `google-chrome-stable` / `chromium` / `chromium-browser`
  - Brave: `brave-browser` / `brave`
  - Edge: `microsoft-edge` / `microsoft-edge-stable` / `msedge`
  - Vivaldi: `vivaldi` / `vivaldi-stable`
  - Opera: `opera`
- **`CHROME_BIN` env 覆盖**: 用户显式 `CHROME_BIN=/path/to/your/chromium-fork bash scripts/start_chrome.sh` 可手动指定任意 Chromium fork binary, 自动检测失效时的兜底
- **错误信息升级**: "找不到 Chrome / Chromium" → "找不到 Chrome / Chromium / Brave / Edge / Vivaldi / Opera 任一可执行文件 + 显式 CHROME_BIN env 提示"
- **`docs/ARCHITECTURE.md` §1.1 加 V0.16.18 浏览器边界段**:
  - 列 11 个支持的 binary
  - 明确 Firefox / Safari 不支持的根因 (协议不同 + launch 模式丢登录态 = 与 patchright NO-GO 同根因)
  - WebDriver BiDi 是未来路径但 Playwright 1.59+ 试验性, 未成熟
- **`README.md` 栈段加注脚**: V0.16.18 起 Chromium fork 支持 + ARCHITECTURE §1.1 引用

### Why
- 用户问"项目只能控制 Chrome 吗" → 实际架构上是 Chromium 系都行 (CDP 协议零差异), 只是脚本只检测 Chrome/Chromium 4 个 binary
- 5 行改动覆盖 Brave/Edge/Vivaldi/Opera 4 个主流 fork, ROI 高
- 浏览器边界清晰落档: Chromium 系 ✅ / Firefox/Safari ❌ (架构) / WebDriver BiDi 未来路径

### Compatibility
- 235 passed + 2 skipped 与 V0.16.17 一致 (sh + markdown 改动, 无代码)
- 现有 Chrome/Chromium 用户行为零变化 (binary 检测优先级 google-chrome 在前)
- bump: pyproject.toml + `__init__.py` `0.16.17` → `0.16.18`

## [0.16.17] - 2026-05-04

### Verify (W3-C Gmail compose 真账号 E2E 实测通过)
- **用户本地端到端验收完成**: 9222 Chrome (登录态持久化在 `~/.config/web-agent-chrome` user-data-dir) → `WEB_AGENT_TEST_RECIPIENT=franciseliang99@gmail.com` + `WEB_AGENT_AUTO_APPROVE='*'` → `uv run python demos/gmail_compose.py` → LLM 完整 ReAct loop (perceive Gmail UI → click Compose → 填 To/Subject/Body → click Send) → safety.check() 拦 send-or-pay 规则 → AUTO_APPROVE 全开放行 → actuator 真点 Send → **邮件真发到 inbox 收到**
- 完整链路验证: W3-A (safety 拦截) + W3-B (read-only 不在本次跑但 compose 流程需要 perceive) + W3-C (compose 写操作)
- **Audit gap 6/6 后又一收尾**: V0.12.0~V0.15.1 落了 6 个模块单测, V0.16.17 落了 W3-C 真账号 E2E (区别: 单测 mock 所有 IO, E2E 跑真 Chrome + 真 LLM + 真 Gmail + 真发邮件)
- README L129 已知缺口删 "Gmail 真账号端到端验收" + L14 W3 行加 "V0.16.17 真账号 E2E 实测通过" 注脚
- bump: pyproject.toml + `__init__.py` `0.16.16` → `0.16.17`

### Why
- V0.7.0 W3-C 落地以来, Gmail compose demo 代码完整但**从没有真账号验收过** — 一直是已知缺口. 用户 V0.16.17 亲自跑通 = 项目从此可宣称"W3-C 真在用户端工作 (不是只 mock 测过)"
- 跑法 cookbook 写到 ARCHITECTURE / README 后, 任何接手人/未来 W6 阶段需要重测时直接复制粘贴, 不用重新调研
- 与 V0.16.14 patchright spike + V0.16.15 curl_cffi 落档 + V0.16.16 W5-C.2 DEFER 同模式: 把"模糊待办"转化为"已验证 / 永久 NO-GO / DEFER+触发条件"明确决断

### 跑法记录 (用户验收路径)
```bash
# 终端 A (首登 Gmail 仅一次, 后续 user-data-dir 持久化)
CHROME_MODE=headed bash scripts/start_chrome.sh https://mail.google.com/
# 在弹出窗口里手登 Gmail

# 终端 A 切回 (后续随便走 auto/xvfb/headless)
bash scripts/start_chrome.sh

# 终端 B (核心)
WEB_AGENT_TEST_RECIPIENT=franciseliang99@gmail.com WEB_AGENT_AUTO_APPROVE='*' uv run python demos/gmail_compose.py

# 验证: 刷 inbox 看新邮件 "web-agent W3-C test 2026-05-04T..."
```

### Compatibility
- 235 passed + 2 skipped 与 V0.16.16 一致, 仅 markdown 文档改动
- 公开 API / 代码 / sh 全零改动

## [0.16.16] - 2026-05-04

### Doc (W5-C.2 真 plan-and-execute DEFER 落档 + 触发条件明确)
- **`docs/ARCHITECTURE.md` §1.5 加 V0.16.16 DEFER 决策段**:
  - SDK 兼容性现状表 (subagent 实测 SDK 文档): Anthropic ✅ / OpenAI ❌ / Kimi ❌ — vision model 必须 ≥1 image, V0.15.0 担心的问题 V0.16.x 仍然成立
  - 真做成本估算: ~27h (Protocol 扩 + Anthropic 实现 + OpenAI/Kimi fallback + loop 2 阶段重构 + 30-40 case 测试). Anthropic-only MVP ~16h 但与"BYO LLM"卖点冲突
  - 三个触发条件 (任一满足立项): ① 用户反馈 augmentation 失败案例 ② OpenAI/Kimi 支持零 image vision ③ spike 证 plan-and-execute 失败率低 >20%
  - 最低成本前置 spike (1-2h, 不立项): loop.py 加 logging 跑 20 任务量化"LLM 是否真拆 subgoal"
  - 与 patchright/curl_cffi NO-GO 的差异: DEFER ≠ NO-GO, 是"等条件成熟"而非永久关闭
- **`README.md` L96 路线图**: W5-C.2 状态从"留 W5-C.2"升为"**永久 DEFER**, V0.16.16 落档 + 3 选 1 触发条件 + ARCHITECTURE 引用"

### Why
- V0.16.15 反检测决策树闭环后, 用户继续问 W5-C.2 是什么. Explore subagent 调研后给出: SDK 阻碍未消除 + ROI 未量化 + Anthropic-only 与项目卖点冲突 → DEFER 比 立项 / 永久 NO-GO 都更准确
- DEFER 比"留 W5-C.2"待办更负责: 写明 SDK 现状 + 工时 + 触发条件, 后人接手不用重新调研
- 与反检测层决策 (patchright/curl_cffi NO-GO + 住宅代理 Defer to CF 命中) 同模式: 把"模糊待办"转化为"明确决断 + 立项条件"

### Compatibility
- 235 passed + 2 skipped 与 V0.16.15 一致, 仅 markdown 文档改动
- bump: pyproject.toml + `__init__.py` `0.16.15` → `0.16.16`

## [0.16.15] - 2026-05-04

### Doc (curl_cffi TLS 指纹永久 NO-GO 落档 + 住宅代理路径明确)
- **`docs/ARCHITECTURE.md` §1.3 加 V0.16.15 关联决策段**: curl_cffi NO-GO 锁定 (当前架构). 流量路径表说清楚为什么没用:
  - 浏览流量 → Chrome 自己的 BoringSSL = 真 Chrome JA3/JA4, curl_cffi 改不到
  - LLM API → Anthropic/OpenAI 端点不做反爬, curl_cffi 也用不上
  - W6+ 若引入"Python 直发 HTTP 旁路"路径才重评估. 与 patchright NO-GO 同源 (反检测层升级路径决断), 但根因不同 (架构冲突 vs 路径不需要)
- **`README.md` 已知缺口 (L127)**: 把"住宅代理 + curl_cffi TLS 指纹接入"拆成两条:
  - curl_cffi → ~~strikethrough~~ + V0.16.15 NO-GO 摘要 + ARCHITECTURE 引用 (与 patchright 同等待遇)
  - **住宅代理**单列保留为"Cloudflare 命中后启用", 加候选商业服务 (IPRoyal $7/GB / Smartproxy $8.5/GB) + Chrome --proxy-server= 与 connect_over_cdp 兼容性说明 + 凭证认证坑提示
- **`README.md` 反检测层段 (L238-242)**: curl_cffi 标 NO-GO; 住宅代理升为"真正下一层防御"; 重新编号 1-4 步

### Why
- V0.16.14 spike 关闭 patchright 后, 用户进一步问"住宅代理 + curl_cffi"作用. 独立 subagent 调研后判定: 在 Playwright 接管真 Chrome 架构下, **curl_cffi 在浏览路径完全没用** (Chrome 自己已是真 BoringSSL), 与 patchright 一样应该永久落档而非留在"已知缺口"待办列表
- 住宅代理是另一回事: 与 connect_over_cdp 完全兼容 (Chrome 自己处理代理, web-agent 无感), 命中 Cloudflare 时是真有用的下一层防御. 单列保留 + 加候选商业服务 + 实施坑 (`--proxy-server=` 不支持 user:pass 内联凭证) 让后人看到时不用再调研一遍
- 反检测层升级路径走完: patchright (NO-GO 架构冲突) / curl_cffi (NO-GO 路径不需要) / 住宅代理 (Defer to CF 命中) / 验证码暂停 UX (W4-2 V0.9.0 已实现) — 整个反检测决策树闭环

### Compatibility
- 235 passed + 2 skipped 与 V0.16.14 一致, 仅 markdown 文档改动 (无代码 / 无 sh 改动)
- bump: pyproject.toml + `__init__.py` `0.16.14` → `0.16.15`

## [0.16.14] - 2026-05-04

### Fix (P0 WebGL SwiftShader flags + patchright spike NO-GO 落档)
- **`scripts/start_chrome.sh` ARGS 加 3 个 GL flag**: `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader` — Xvfb / headless 无 GPU 时启 SwiftShader 软件渲染. 不加时 sannysoft "WebGL Vendor/Renderer" 直接 FAIL ("Canvas has no webgl context"), 反爬站点用 WebGL fingerprint 过滤直接命中
- **headless 模式删 `--disable-gpu`**: Chrome 109+ 该 flag 已 deprecated, `--headless=new` + SwiftShader 是官方推荐组合; 留着会与新 GL flags 矛盾
- 实测预期: sannysoft B (vanilla+stealth) 21/32 → 23/32 (~72%), FAIL 从 2 (WebGL 双坑) 降到 0

### Doc (patchright NO-GO 永久落档)
- **`docs/ARCHITECTURE.md` §1.3 升级**: 从"基于理论冲突的否决" 升为"V0.16.14 spike 实测验证的永久 NO-GO". 加测试矩阵 (A=C 19/32 / B 21/32) + 根因分析 (patchright 的 patch 在 launch 阶段, connect_over_cdp 接管已启动 Chrome 全部旁路; sannysoft 测 JS 注入层不测 CDP 协议层, 选错靶子). 副产物 WebGL flags 修法也写入
- **`README.md` L126 已知缺口**: 删 patchright 决断悬念条目, 替换为 NO-GO 摘要 + ARCHITECTURE §1.3 引用
- **`README.md` 反检测层段** (L238-242): patchright 升级路径标 ~~strikethrough~~ + 引用 spike 数据, 突出"上住宅代理 + curl_cffi TLS" 才是真正下一层防御

### Spike 工程
- worktree 隔离: `../web-agent-spike-patchright` (branch `spike/patchright`), main 完全不动. 装 patchright 1.59.1 仅在 worktree venv. spike 完成后清理 (`git worktree remove` + `git branch -D`). spike 脚本 (`demos/spike_patchright.py` + `scripts/run_spike.sh`) **不进 main** — 一次性证伪用途, 留 git history 可查; 进 main 给后续读者制造"这是产品代码？"歧义

### Why
- V0.16.13 后 P3 patchright 决断仍开. 用户选 spike A 路线 (worktree 30min 实测) 后, sannysoft 数据三组矩阵立即出 NO-GO 信号 (A=C 完全相同 → patchright client patch 旁路). 副产物发现 B 的 2 个 FAIL 全是 Xvfb 无 GPU 环境问题不是反爬问题, 一行 GL flags 修
- patchright NO-GO 不是"patchright 全无用", 是"connect_over_cdp 接管模式下不工作". scope 限定 + 永久落档比悬而未决的"未实测"更负责

### Compatibility
- 235 passed + 2 skipped 与 V0.16.13 一致, 公开 API / Python 代码零改动
- 仅 `scripts/start_chrome.sh` + 3 个 doc 改动 + bump
- bump: pyproject.toml + `__init__.py` `0.16.13` → `0.16.14`

## [0.16.13] - 2026-05-04

### Add (mypy strict 阶段 3 — CI gate + 文档同步)
- **`.github/workflows/ci.yml`** (新建, 38 行): GitHub Actions push + PR 触发 3 层 release gate:
  1. `uv run ruff check src/ tests/` (V0.16.10 起 0 errors)
  2. `uv run mypy src/web_agent` (V0.16.12 起 strict 0 errors)
  3. `uv run pytest -q` (235 passed + 2 skipped)
  - matrix 单点 ubuntu-latest + py3.12; uv 自带 cache; `uv sync --all-extras` 装 openai 让 mypy 看全 LLM provider 类型 (anthropic + openai 都覆盖)
- **`docs/ARCHITECTURE.md` 附录 B 硬约束** 升级: "测试 235 全绿是 release gate" → "三层 release gate (ruff + mypy strict + pytest), GitHub Actions push + PR 自动跑"; 加本地一并跑命令样例
- **`README.md` 当前状态行** 升级: "48+ commits, 235 tests passing" → "51+ commits, 235 tests passing, 3 层 release gate (ruff 0 + mypy strict 0 + pytest 235 全绿), GitHub Actions CI 自动跑"; 加 V0.16.9-V0.16.13 五连发摘要 (P1 解耦 + ruff 0 + TypedDict + mypy strict + CI gate)
- **bump**: pyproject.toml + `__init__.py` `0.16.12` → `0.16.13`

### Why
- V0.16.12 mypy strict 通过后无 CI 闸 = 任何后续 commit 都可能引入 type 回归 (drift). CI 闸是把"235 全绿"的隐性约定变成机制化保障
- 不加 pre-commit hook (`.pre-commit-config.yaml`): 侵入用户本地 git workflow, 不强加; CI 闸足够拦回归. 用户想要本地快速 fail-fast 可手动加
- `uv sync --all-extras`: 不装 openai 时 mypy 找不到 stub 报 import-not-found (V0.16.12 实测过), CI 必须装 extra 让 mypy 看全

### Compatibility
- 235 passed + 2 skipped 与 V0.16.12 一致, 公开 API / 行为零破坏
- 无运行时变化, 仅新增 CI 配置 + 文档

## [0.16.12] - 2026-05-04

### Fix (mypy strict 阶段 2 — 47 errors → 0, 全 src/ 编译期类型一致)
- **`pyproject.toml` 加 `[tool.mypy]` strict 段** + 2 个 override (playwright_stealth / mcp[cli] 动态 SDK ignore_missing_imports). dev group 加 `mypy>=1.13`
- **`Action.args: ActionArgs union TypedDict` 回退到 `dict[str, Any]`**: V0.16.11 设计 Action.type 是 str 不是 Literal, mypy 无法在 `if action.type == "click"` branch 内 narrow union TypedDict 到 ClickArgs (loop.py 5 个 branch 全部报"object 不可索引"). 真 discriminated union 需把 Action 拆 5 个 dataclass + Literal type, 跨多文件大重构留 V0.17 顺手做. ActionArgs 5 个子类型 + union 仍保留在 `types.py` 作 schema 文档
- **批量修补 47 errors → 0**:
  - `dict` no type args (15 处): trace.py 4 / replay.py 6 / mcp_server.py 5 → 全部 `dict[str, Any]` (内部+签名)
  - `deque` no type args (trace.py:36): `deque[Step]`
  - `Context` no type args (mcp_server.py:74): `Context[Any, Any] | None`
  - `kwargs: dict` 注解 (anthropic.py:36 + openai.py:46/63/74): `dict[str, Any]`
  - `_RUN_KW: dict[str, Any]` 注解 (notify.py:51) — bool/DEVNULL 推断 dict[str, int] 与 subprocess.run kwargs spread 冲突
  - `perceiver.py:147` `return cast(list[str], dismissed)` — page.evaluate 返 Any
  - `loop.py:85` `_handle_captcha(conn: sqlite3.Connection)` 加类型注解 (主 loop 函数, 8 处 logger 调用全在函数体内)
  - `llm/__init__.py:17` + `llm/base.py:18` 显式 re-export: `from web_agent.types import Action as Action, Mark as Mark` (PEP 484 explicit re-export)
  - `browser.py:41` 删 `# type: ignore[import-untyped]` (override 已 ignore)
  - `anthropic.py:63` messages.create 的 `system` / `tools` / `tool_choice` / `messages` 4 个 kwarg `cast(Any, ...)` — SDK TypedDict 严格 vs 裸 dict 字面量, 运行时 anthropic 接受
- **bump**: pyproject.toml + `__init__.py` `0.16.11` → `0.16.12`

### Why
- V0.16.11 阶段 1 TypedDict 化是 strict 配置硬前提; 本版本开 strict 后冒 47 errors (低于 plan 估算 60-100, dataclass 字段类型注解覆盖率 ~100% + 之前已有部分 type hint 习惯)
- Protocol 一致性 / dataclass 字段宽松 / None 流向 是 mypy 在 web-agent 上的 3 大价值——LLMClient Protocol + 3 provider 实现, dict 字段无精度, multi-LLM 项目类型漂移
- `cast(Any, ...)` 4 处针对 SDK 严格 TypedDict — anthropic 1.x messages.create 期望 `TextBlockParam` / `ToolParam` 等具体 TypedDict, 与社区惯例的裸 dict 字面量不兼容; 运行时 SDK 接受任意 Mapping, 编译期严格不放行. 等价 `# type: ignore[call-overload]` 但 cast(Any) 比 ignore 更精确

### Compatibility
- 235 passed + 2 skipped 与 V0.16.11 一致, 公开 API / 行为零破坏
- ruff: All checks passed!; mypy strict: 0 issues / 20 source files
- 新增 dev dep: mypy>=1.13 (uv lock 同步更新)

## [0.16.11] - 2026-05-04

### Refactor (mypy strict 准备 — 阶段 1: TypedDict 化 dict 字段, V0.16.12 加配置)
- **`Mark.bbox: dict` → `BBox` TypedDict** (`types.py`): 4 个 float key (x/y/w/h) — perceiver JS evaluate 注入返回 `DOMRect.left/top/width/height` 是 float, 与 `actuator.py:52-57` 4 处算子用法 (`mark.bbox["x"] + mark.bbox["w"] / 2`) 完全对齐. `perceiver.py:166` 加 `cast(BBox, m["bbox"])` (page.evaluate 返回 dict[str, Any])
- **`Action.args: dict` → `ActionArgs` Union TypedDict** (`types.py`): 5 个 action type 的 args schema 各自精确化:
  - `ClickArgs`: `{mark_id: int}`
  - `TypeArgs`: `{text: str, submit: NotRequired[bool]}` (OpenAI strict mode 强制 required, 中性 schema 是 optional)
  - `ScrollArgs`: `{dy: int}`
  - `ExtractArgs`: `{query: str, answer: str}`
  - `DoneArgs`: `{result: str}`
  - `thought` 已被 `args.pop("thought")` 弹到独立 `Action.thought` 字段, 故 ActionArgs 不含 thought
- **构造点 cast** (`llm/anthropic.py:81` + `llm/openai.py:105`): SDK 返回 `dict[str, Any]` → `cast(ActionArgs, args)` 显式类型边界. 运行时 noop, mypy 编译期才生效
- **运行时零变更**: TypedDict 在 runtime 就是 dict, `loop.py` 5 个 branch 的 `action.args.get("xxx")` 全部兼容; `actuator.py` 4 处 `mark.bbox["x"]` 兼容
- **bump**: pyproject.toml + `__init__.py` `0.16.10` → `0.16.11`

### Why
- V0.16.12 要开 mypy strict, `dict` 字段在 strict 下零精度 — 不知道 `bbox["pos"]` 是不是合法 key, 不知道 `args["mark_id"]` 是 int 还是 str. TypedDict 化是 strict 闭环硬前提
- 5 个 action type 的 args 形状已稳定 (V0.0.x 设计至今未变, schema 锁在 `_schema.py:34`), Union TypedDict 最贴合实际语义而非 generic dataclass
- LLM SDK 回 args 是 `dict[str, Any]` (Anthropic block.input + OpenAI json.loads), 必须 cast 才能进 TypedDict 类型边界

### Compatibility
- 235 passed + 2 skipped 与 V0.16.10 一致, 公开 API / 行为零破坏
- 公开 import: `from web_agent.types import BBox, ActionArgs, ClickArgs, TypeArgs, ScrollArgs, ExtractArgs, DoneArgs` 全新增, Mark/Action 签名向后兼容 (字段类型收紧但运行时 dict 兼容)

## [0.16.10] - 2026-05-04

### Fix (P2 ruff lint 收尾 — 17 errors → 0)
- **E402 (13 个 → 0)**: `src/web_agent/loop.py:22` + `src/web_agent/cli.py:15` 的 `logger = logging.getLogger(__name__)` 误置于 stdlib import 与 project import 之间，致 ruff 把 `from web_agent.* import ...` 标 "module-level import not at top". 修复: logger 赋值下移至所有 import 之后. loop.py 顺手把 `ProgressCallback` 类型别名也下移到 import 段之后, 让 import 段纯净. 模块顶层无 logger 调用 (loop.py logger.* 全在 line 107+, cli.py 全在 line 61+), 行为零变更
- **F401 (4 个 → 0)**: `uv run ruff check --fix tests/` 自动修, diff 校验真未使用:
  - `tests/test_browser.py:10`: 删 `MagicMock` (body 只用 `AsyncMock`)
  - `tests/test_cli.py:15`: 删 `from web_agent import cli` (monkeypatch 走 `"web_agent.cli.xxx"` 字符串路径不依赖此绑定)
  - `tests/test_memory.py:5,7`: 删 `sqlite3` + `pathlib.Path` (后者 `tmp_path` fixture 已是 pytest 提供的 Path 对象)
- **bump**: pyproject.toml + `__init__.py` `0.16.9` → `0.16.10`

### Why
- V0.16.9 P1 解耦审计后剩 P2 ruff 红点 17 个; 干净化 release gate 后续才能上 ruff CI 闸 (V0.17 可选 pre-commit hook)
- E402 根因 V0.6.x 引入 logger 时位置选错, 一直没修; 本次顺路收

### Compatibility
- 235 passed + 2 skipped 与 V0.16.9 一致, 公开 API / 行为零破坏
- `uv run ruff check src/ tests/` → "All checks passed!"

## [0.16.9] - 2026-05-04

### Refactor (P1 解耦审计 — 依赖方向反向修复 + 文档同步)
- **新增 `src/web_agent/types.py` 叶子 domain 模块**: `Mark` (从 `perceiver.py`) + `Action` (从 `llm/base.py`) 上提共享, 不 import 任何 `web_agent.*` 模块. 三处反向 import 修正:
  - `safety.py:18-19`: `from web_agent.llm.base import Action` + `from web_agent.perceiver import Mark` → `from web_agent.types import Action, Mark` (domain 不再反向依赖 port + 业务)
  - `llm/base.py:15`: `from web_agent.perceiver import Mark` → `from web_agent.types import Mark` (port 不再反向依赖业务)
  - `perceiver.py` / `llm/base.py` 保留 re-export shim — 旧 `from web_agent.perceiver import Mark` / `from web_agent.llm.base import Action` 全部仍可用
- **canonical import 迁移**: `actuator.py` / `loop.py` / `llm/anthropic.py` / `llm/openai.py` / `llm/_schema.py` 5 个 src/ 文件改用 `from web_agent.types import ...`; tests/ 26 文件保持旧路径不动 (验证 shim 工作 + 零 test churn)
- **`docs/ARCHITECTURE.md` §2 stale 修正**: `llm/_protocol.py` → `llm/base.py` (V0.13.x 改名后未同步), §2 表加 `types.py` 行, 模块数 14 → 16 (含 `planner_hierarchy.py` 之前漏数), 依赖图加 "types.py 是最叶子 domain" 说明
- **`README.md` 路线图**: V0.16.2 / V0.16.3 ⏳ → ✅ (V0.16.4 progress wire / V0.16.6 Resources 已 ship), 替换"工时估剩 1 人天"为 V0.16.0-V0.16.9 完成清单 + 后续可选项 (Elicitation / HTTP transport)
- **bump**: pyproject.toml + `__init__.py` `0.16.8` → `0.16.9`

### Why
- CLAUDE.md「解耦优先」原则: domain 必须叶子, 不能反向依赖 port / 业务. V0.6.0 (W3-A safety) 引入 `safety.py` 时把 `Mark`/`Action` import 反向连了, 一直没修; V0.0.1 时 `llm/base.py` (port) 也同样反向引 `perceiver.Mark`
- project-auditor subagent 6 维度审计 P1 标红: 3 处反向引用同根因 → `Mark`/`Action` 是共享 dataclass 但住在错的层
- ARCHITECTURE.md §2 写 `_protocol.py`, 实际文件是 `base.py` (V0.13.x rename), 接手人按文档找会扑空
- README 路线图 stale 4 个版本, 给读者错误的"进行中"信号

### Compatibility
- 公开 API 零破坏: `from web_agent.perceiver import Mark` / `from web_agent.llm.base import Action` / `from web_agent.llm import Action` 全部保留 (shim)
- 235 passed + 2 skipped 与 V0.16.8 一致, 零 SQLite/pickle schema 改动 (Mark/Action 都不持久化, trace 表存 TEXT)

## [0.16.8] - 2026-05-04

### Docs (ARCHITECTURE.md §5 MCP server 章节 + 附录更新)
- **新加 `docs/ARCHITECTURE.md` §5 MCP server** ~110 行 6 小节, 文档化 V0.16.0-V0.16.7 累积的协议层架构决策:
  - **§5.1 三 tools + 两 resources 的语义切分**: tool (主动调用/可能副作用) vs resource (订阅/只读) 决策表; 为什么 replay/memory 双发 (tool + resource) — UI 按钮 vs LLM 上下文订阅; `_render_replay`/`_query_memory` 共享 helper
  - **§5.2 progress 三轨**: mcp ctx → cli → loop 主循环 + captcha 心跳完整链路图; `ProgressCallback` 与 `ctx.report_progress` 1:1 对齐 (bound method 不需 wrapper); 60s no-traffic timeout 风险 + B 路径决策 (loop 内联 poll vs 改 captcha API)
  - **§5.3 _RUN_LOCK 串行**: Chrome CDP 单 tab → asyncio.Lock module-level; cancellation 自动释放; 仅锁 web_agent_run
  - **§5.4 9222 健康检查 per-tool-call**: 不在 server-start (eager 启动 vs 用户场景脱钩); urllib stdlib 用 asyncio.to_thread 包阻塞
  - **§5.5 SystemExit → RuntimeError 转译**: replay.load_task sys.exit() CLI 行为, MCP 必转 Exception 防 server 退出
  - **§5.6 print → logging.info(stderr) 硬前提**: stdio stdout 是 JSON-RPC 通道, 25 处 print 改造 + 7 处用户面向 stdout 保留 + capsys → caplog 测试迁移
- **附录 A 版本里程碑速览** 加 V0.15.3-V0.16.7 共 8 条 (smoke 骨架 + MCP server 5 milestone)
- **附录 B 硬约束** 219 → 235 tests release gate 同步

### Why
- V0.16.0-V0.16.7 累积的 MCP 决策散在 8 commit + 5 CHANGELOG 段, 接手人读不到 "为什么 tool/resource 双发" / "progress 为什么 DI 不 ctx threading" / "captcha 心跳为什么 B 路径"
- subagent (Plan) 审核反馈采纳: V0.16.8 优先 ARCHITECTURE 而非 HTTP transport (用户未提) / OpenRouter 第四 smoke (LLM 三家齐边际价值低) / 真 Chrome smoke (易引入 flaky)

### Compatibility
- 零代码改动 (仅 docs/ARCHITECTURE.md + CHANGELOG + README + version bump)
- 235 passed + 2 skipped 与 V0.16.7 一致

## [0.16.7] - 2026-05-04

### Refactor (V0.16.6 MCP Resources /simplify pass)
- **`mcp_server.py`** 抽 2 个 module-private helper 消 tool/resource 间重复:
  - `_render_replay(task_id)` — `replay_render_to_file(task_id or None)` + `SystemExit → RuntimeError` 转译, `web_agent_get_replay` tool 与 `replay_resource` 都走它. 之前两处复制粘贴同一 try/except 块
  - `_query_memory(domain, limit)` — empty-domain guard + URL→domain normalize + env-driven `mem_db` + `recall_by_domain` + dict 序列化, `web_agent_query_memory` tool 与 `memory_resource` 都走它. 之前两处除 `limit` 来源 (param vs hardcode 5) 外字段全同
  - tool/resource 函数体降到 1-2 行, 各保留 docstring 表语义差异
- **`tests/test_mcp_server.py`** 加 `_patch_replay_render(monkeypatch, *, returns=, raises=)` helper 替代 4 处内联 `def fake_render` / `def boom` (case 5 + case 6 + V0.16.6-2 + V0.16.6-4) — 4 个 stub 工厂统一签名

### Why
- subagent (`/simplify`) 审核反馈采纳: V0.16.6 commit 8291ce0 `replay_resource` vs `web_agent_get_replay` tool ~70% 代码重复 (同一 `replay_render_to_file` + `SystemExit` 转译块); `memory_resource` vs `web_agent_query_memory` tool 几乎完全一样除 `limit` 来源
- 抽 helper 后未来改 SystemExit 转译策略 / mem_db env var 名只需 1 处, 而非 2 处易漏改
- 测试 fixture `fake_render` 在 V0.16.6 commit 后已出现 2 次内联定义, 同 V0.16.5 抽 `fake_chrome_alive` 思路一致

### Compatibility
- 公共 API 不变: `web_agent_get_replay` / `web_agent_query_memory` tool + `replay_resource` / `memory_resource` resource 签名 + 返回类型零变化
- 全 235 passed + 2 skipped 不变 (V0.16.6 baseline 完全持平, 纯内部解耦 refactor)
- runtime deps 零变化

## [0.16.6] - 2026-05-04

### Added (MCP Resources: replay HTML + memory entries 只读视图)
- **`mcp_server.py` 加 2 个 `@mcp.resource()` template** (FastMCP URI template 风格):
  - `webagent://replay/{task_id}` (mime `text/html`): 渲染好的 ReAct trace replay HTML 文本, 客户端可 inline render. 内部复用 `replay_render_to_file` + `Path(html_path).read_text()` 读回内容
  - `webagent://memory/{domain}` (mime `application/json`): 长期记忆 entries JSON list (默认 5 条), URL form 自动 normalize via `extract_domain`
- **新增 4 case** `tests/test_mcp_server.py`:
  - `test_list_resources_includes_two_templates`: `list_resource_templates` 返 webagent:// 两个 URI 模板
  - `test_read_replay_resource_returns_html`: `read_resource("webagent://replay/task-x")` 返 HTML text + mime text/html
  - `test_read_memory_resource_returns_json_list`: `read_resource("webagent://memory/example.com")` 返 JSON list, parse 后字段对
  - `test_read_replay_resource_non_existent_errors`: 不存在 task_id → `McpError` (SystemExit 转译路径同 web_agent_get_replay tool)

### Why
- `replay` / `memory` 本质是只读视图, MCP 协议层面 resource 比 tool 语义更准 (tool 暗示副作用 / 主动调用; resource 是订阅 / 客户端按需读)
- subagent (Plan) 审核反馈采纳:
  - **优先做 Resources** 而非 HTTP transport (用户未提远程需求, stdio 已通) 或 OpenRouter/Azure smoke (水平复制, ROI 低)
  - **保留 `web_agent_get_replay` / `web_agent_query_memory` 两个 tool** 不删: tool 接 limit 参数 + 主动调用语义场景仍有用 (e.g. Claude Desktop UI 显式按钮调 tool); resource 是 LLM 上下文订阅场景 (e.g. 调 web_agent_run 前自动拉同 domain 历史)
  - **Cursor / Continue 都已支持 resources** 不像 elicitation 那样卡客户端兼容
- 实施代价 ~30 分钟 (50 行: 2 个 resource + 4 case test + CHANGELOG)

### Compatibility
- 公共 API 加: `mcp_server.replay_resource` + `mcp_server.memory_resource`
- 旧 11 mcp tests + 220 主 tests + 2 smoke skip 全过, 总 235 passed + 2 skipped (V0.16.5 231 + 4 resource case)
- runtime deps 零变化

### V0.16.7+ next steps
- HTTP transport (streamable HTTP, 远程接 MCP server)
- Elicitation 替代 `WEB_AGENT_AUTO_APPROVE` (Claude Desktop 2026-Q1 后正式支持)
- OpenRouter / Azure / Bedrock smoke 骨架 (复制 Kimi 模板)
- 真接 Cursor/Continue 跑 wikipedia 任务 + screenshot 验通

## [0.16.5] - 2026-05-04

### Refactor (V0.16.4 progress wire /simplify pass)
- **`loop.py`** `time.time()` → `time.monotonic()` (4 处) — 对齐 captcha.wait_for_resolution 既有约定 + 防系统时钟回拨干扰 deadline 计算
- **`cli.py`** `progress_cb=None` 加类型注解 `ProgressCallback | None` (顶部 import) — 显式类型让调用方 IDE 提示生效
- **删 V0.16.4 版本戳 narration 注释** (CLAUDE.md "default to writing no comments" + 不写 caller history):
  - `src/web_agent/mcp_server.py` line 87 注释合并 1 行
  - `src/web_agent/loop.py` 删 "(R2 风险)" 内部任务编号 → 改纯 WHY (60s no-traffic 心跳约束)
  - `tests/test_captcha.py` 2 处 V0.16.4 narration 留 WHY (短 timeout 防真等 300s)

### Why
- /simplify subagent 自动检出 4 项: 时钟函数对齐 / 类型注解补全 / 注释精简 / docstring "WHY 不 narrate change"
- subagent 跳过 (false positive / 已 documented):
  - `_handle_captcha` 加 max_steps + progress_cb 2 参数 — 总是配对, < 3 参不抽 dataclass
  - 复用 captcha.wait_for_resolution — V0.16.4 commit 已显式选 B 路径, subagent 不推翻
  - 测试 setenv 抽 fixture — N=3 重复 2 行, 沿用 test_captcha.py:101 既有 YAGNI 注释惯例

### Compatibility
- 公共 API 零变化 (类型注解仅 IDE-time, 运行时透明)
- 231 passed + 2 skipped 与 V0.16.4 一致, 行为 100% 等价

## [0.16.4] - 2026-05-04

### Added (progress_cb 真 wire 完整链路: mcp ctx → cli → loop 主循环 + captcha 心跳)
- **`cli.run_task` 加 `progress_cb=None` kwarg + 透传** `run_react_loop(progress_cb=progress_cb)`. 默认 None 兼容旧 demos / CLI 调用 100%
- **`mcp_server.web_agent_run` 删 `_ = ctx` 占位 + 改** `progress_cb = ctx.report_progress if ctx is not None else None` (subagent 反馈: bound method 自身是 awaitable callable, 不需 wrapper, 类型 1:1 对齐 `Callable[[int, int, str|None], Awaitable[None]]`)
- **`loop._handle_captcha`** 加 `max_steps`/`progress_cb` 参数 + **内联 poll 替换 `captcha.wait_for_resolution`**:
  ```python
  while time.time() < deadline:
      if progress_cb is not None:
          elapsed = timeout_s - (deadline - time.time())
          await progress_cb(step_i, max_steps, f"awaiting {info.vendor} ({elapsed:.0f}/{timeout_s:.0f}s)")
      if await captcha_detect(page) is None:
          return None  # cleared
      await asyncio.sleep(poll_s)
  ```
  - **解决 R2 风险** (Claude Desktop 60s no-traffic timeout): captcha poll 默认 3s 间隔, 远低于 60s 阈值, 长 wait 安全
  - **不改 captcha module API** (subagent B 路径推荐): captcha.py 保持纯 detect/wait 单职, 心跳是 loop 关心的事 (它持有 progress_cb)
- **删 `from web_agent.captcha import wait_for_resolution as captcha_wait`**: 内联 poll 后不再用; captcha.wait_for_resolution 仍存在供其他 caller (W4-2 已有 11 测保留)
- **`tests/test_mcp_server.py` 加 case 11**: `client.call_tool("web_agent_run", progress_callback=fn)` 注入 fn, 验 `cli_run_task` fake 内调 progress_cb 后 fn 收到 2 个 ProgressNotification (progress=0/1, total=5, message="step N/5")
- **`tests/test_captcha.py` 3 case 改造**: 删 `monkeypatch.setattr("web_agent.loop.captcha_wait", ...)` (新 inline poll 不调那个 attribute); setenv `WEB_AGENT_CAPTCHA_TIMEOUT_S=0.3-1.0` + `POLL_S=0.05` 让 timeout case 快速退出; cleared case 靠 fake_detect 第 2 次返 None

### Why
- V0.16.1 留下 `_ = ctx` 占位 V0.16.2 wire, V0.16.2 simplify 改 V0.16.3 wire — 拖了 3 个版本; V0.16.4 真闭环 mcp progress notification ↔ web-agent loop 主循环
- Claude Desktop / Cursor 默认 no-traffic 60s 超时, 单步 perceive+LLM 平均 8-15s 安全, 但 captcha 默认 300s wait 必死 → 必须 inline poll 心跳
- subagent (Plan) 审核反馈采纳:
  - **B 路径 (loop 内联 poll) 而非 A (captcha module 加 on_poll callback)**: 改动面 < 50%, captcha.py 公共 API 不污染, test_captcha 改 3 case 核心逻辑不变
  - **直接 `progress_cb=ctx.report_progress` 不加 wrapper**: bound method awaitable callable, 类型对齐
  - **删 `_ = ctx` 占位 + V0.16.2/V0.16.3 死注释**: 防下个 subagent 被误导

### Compatibility
- 公共 API 加: `cli.run_task(progress_cb=...)` 可选 kwarg + `loop._handle_captcha(max_steps=, progress_cb=)` 可选 kwargs
- 旧 demos / CLI / 单测调用全兼容 (默认 None)
- 231 passed + 2 skipped (V0.16.3 230 + 1 mcp progress 新 case; captcha 3 case inline poll 改造数量不变)
- 行为变化: 启用 progress_cb 时 captcha 长 wait 期间每 poll_s (默认 3s) 触发心跳; 不启用时行为 100% 同 V0.16.3

### V0.16.5+ next steps
- Resources (`resources://web_agent/replay/<id>` + `memory/<domain>` 只读视图)
- Elicitation 替代 `WEB_AGENT_AUTO_APPROVE` (Claude Desktop 2026-Q1 后正式支持)
- HTTP transport (streamable HTTP)
- 真接 Cursor/Continue 跑 wikipedia 任务 + screenshot 验通

## [0.16.3] - 2026-05-04

### Tools (MCP server stdio 协议层端到端验证脚本)
- **新建** `scripts/test_mcp_local.py` (~80 行) 单条命令验通 MCP server 协议层:
  - 用 `mcp.client.stdio.stdio_client` + `ClientSession` 真起子进程 `uv run web-agent-mcp` 走 JSON-RPC over stdio
  - 验证 4 件事:
    1. `initialize` 握手返 `protocolVersion=2025-11-25`
    2. `list_tools` 3 名匹配 (`web_agent_run` / `web_agent_get_replay` / `web_agent_query_memory`)
    3. `web_agent_run` 无 Chrome 时返 `chrome_not_running` 结构化错误 (V0.16.1 `_check_chrome_alive` 兜底证据)
    4. `web_agent_query_memory` empty domain → `structuredContent={'result': []}`
  - 退出码 0 = 全 PASS, 非 0 = 有 FAIL (CI 友好)
  - 与 `tests/test_mcp_server.py` 区别: 后者用 in-memory transport (单元测试 isolation), 本脚本用真 stdio 子进程 (集成测试 + entry script 验证)

### Why
- V0.16.2 单测 in-memory 全过, 但 stdio 子进程路径 (entry script `web-agent-mcp` + JSON-RPC over stdin/stdout) 没真跑过 — 可能 entry/stdio handler/logging 配置有 bug 单测看不到
- subagent (general-purpose) 审核反馈采纳:
  - **Python 脚本而非 npx mcp inspector**: 纯 Python (mcp 已是 dev-dep), 不引 nodejs 依赖判断, sandbox-friendly
  - **Chrome 不通时验 `chrome_not_running` 兜底**: 把 "Claude Desktop 还没接" 和 "Chrome 没起" 两个 unknown 解耦, 本机协议层独立验通
  - **`mcp dev` CLI 不必须**: 它内部仍跑 npx inspector, 同上
- 实测跑 `uv run python scripts/test_mcp_local.py` → 4/4 ALL PASS

### Linux 用户 MCP client 选项 (V0.16.3 文档新增)
- **Anthropic Claude Desktop**: 仅 macOS/Windows, 无 Linux 版
- **Cursor** (推荐): IDE 内置 MCP, Linux .deb 包. 配置 `~/.config/Cursor/User/settings.json`
- **Continue.dev**: VSCode/JetBrains 扩展, 内置 MCP support
- **Goose** (Anthropic 早期 agent CLI): Linux/macOS, 配置 `~/.config/goose/profiles.yaml`
- **mcp inspector** (一次性可视化测): `npx @modelcontextprotocol/inspector uv run --directory /home/myclaw/web-agent web-agent-mcp`

### Compatibility
- src/ 业务代码零变化 (仅新增 scripts/ tooling)
- 230 passed + 2 skipped 与 V0.16.2 一致
- 脚本独立工具, 不被 mcp_server / cli / pytest 调用

## [0.16.2] - 2026-05-04

### Refactor (V0.16.1 mcp_server /simplify pass)
- **`mcp_server.py`** 164 → 159 行 (-5):
  - **删 dead progress_cb 块** (4 行): 之前构造 progress_cb 但没透传到 cli_run_task (V0.16.2 wiring 待补), 占位 `_ = ctx` 防 unused-arg lint, 真 wire 留 V0.16.3+
  - **`asyncio.to_thread(_check_chrome_alive, cdp_url)`**: 阻塞 urllib (≤2s timeout) 包到 thread 执行, 防 MCP 事件循环被卡, 主路径仍 fail-fast
  - **去掉 redundant `out_dir = Path("data/replays")`**: `replay.render_to_file` 已 default `DEFAULT_OUT`, mcp tool 不必重复传
- **`tests/test_mcp_server.py`** 256 → 233 行 (-23):
  - **hoisted imports**: 9 处 inline `from web_agent.mcp_server import mcp` + 2 处 `import json/sys/logging` 提到 module 级, 删多余 `from pathlib import Path`
  - **Case 10 root-logger leak fix**: 之前 `removeHandler` 不 restore 污染后续 test, 改用 `monkeypatch.setattr(root, "handlers", [])` auto-restore on teardown

### Why
- V0.16.1 commit b958a7f 后跑 /simplify subagent 检出 5 处优化, 全采纳
- subagent 跳过 5 项 (false positive / out of scope):
  - `extract_domain` URL guard 必要 (urlparse("github.com").netloc == "" 把 bare domain 当 path)
  - hardcode `127.0.0.1:9222` 是 pre-existing pattern, 不是 V0.16.1 引入
  - `_check_chrome_alive` 11 行已是 stdlib 最简 (替代 `browser.connect()` 更重)
  - `replay.render_to_file` 18 行已最简 (mkdir + load + write + return)
  - 测试 `async with create_connected_server_and_client_session` boilerplate 显式更可读

### Compatibility
- 公共 API 零变化 (mcp tools / _RUN_LOCK / _check_chrome_alive 签名不动)
- 230 passed + 2 skipped 与 V0.16.1 一致 (行为 100% 等价)

## [0.16.1] - 2026-05-04

### Added (MCP server: 暴露 web-agent 为 Model Context Protocol server)
- **新模块** `src/web_agent/mcp_server.py` (~140 行) 用官方 `mcp[cli]>=1.10,<2` SDK FastMCP decorator 风格:
  - 3 tools 一一对应现有 3 entry script:
    - `web_agent_run(goal, url, max_steps)` → 跑一个 task, 返 result string. 内部调 `cli.run_task` 不重写主路径
    - `web_agent_get_replay(task_id)` → 渲染 HTML 返 `{task_id, html_path, step_count, result}` 结构化 dict
    - `web_agent_query_memory(domain, limit)` → 长期记忆 by domain, 返 list[dict] (ts/domain/goal/result/success). URL form 自动 normalize via extract_domain
  - **module-level `_RUN_LOCK = asyncio.Lock()`** 串行化并发 task: Chrome CDP 单 tab 抢, 第二个 call 自动 await (不 fail-fast). cancellation 时 `async with` 自动释放
  - **per-tool-call Chrome 9222 健康检查**: `_check_chrome_alive(cdp_url)` 用 stdlib `urllib.request` (零新 dep), 不可达抛 RuntimeError → FastMCP 序列化为 tool error. 仅 web_agent_run 调; query_memory/get_replay 不需 Chrome
  - **`Context | None` 注入**: web_agent_run 收 ctx 参数, 包成 `progress_cb` 待 V0.16.2 wire 到 cli.run_task → loop 主循环 (V0.16.1 仅准备 hook 不真触发)
  - **SystemExit → RuntimeError 转译**: `web_agent_get_replay` 内部 catch `SystemExit` 转 `RuntimeError` (replay.load_task 用 sys.exit() 是 CLI 行为, MCP tool 不能让进程退出)
  - **stdio entry**: `main()` 在 `mcp.run()` 前 logging.basicConfig stream=stderr (复用 V0.16.0 cli.main() 同模式), 防业务模块 logger 输出污染 stdout (JSON-RPC 通道)
- **`src/web_agent/loop.py` 加** `progress_cb: ProgressCallback | None = None` kwarg + 主循环每步 hook (3 LOC):
  - `ProgressCallback = Callable[[int, int, str | None], Awaitable[None]]` 类型别名
  - 主循环 `for step_i` 顶部 `if progress_cb: await progress_cb(step_i, max_steps, f"step {step_i+1}/{max_steps}")`
  - 不传 progress_cb 时行为 100% 同 V0.16.0 (默认 None, kwarg 可选)
  - **captcha poll 心跳留 V0.16.2** (需改 captcha module API), V0.16.1 仅主循环步进心跳
- **`src/web_agent/replay.py` 抽** `render_to_file(task_id, out_dir, db_path) -> dict` helper (从 main() body 抽 ~10 LOC):
  - 给 mcp_server.web_agent_get_replay 复用, main() 内部调同一 helper
  - 返 `{task_id, html_path, step_count, result}` 结构化, mcp tool 直接透传
- **`pyproject.toml`**:
  - `[project.scripts]` 加 `web-agent-mcp = "web_agent.mcp_server:main"`
  - `[dependency-groups] dev` 加 `mcp[cli]>=1.10,<2` (subagent 反馈: 1.2 pin 太旧, 1.10+ FastMCP API 稳定; 当前装 1.27 满足)
- **新增** `tests/test_mcp_server.py` 10 case 用 `mcp.shared.memory.create_connected_server_and_client_session` (官方 in-memory transport):
  1. `list_tools` 返 3 tool 名匹配
  2. `web_agent_run` forward args verbatim (monkeypatch cli.run_task)
  3. `web_agent_run` chrome_not_running → tool error (monkeypatch _check_chrome_alive throw)
  4. `web_agent_run` 并发 2 个 → `_RUN_LOCK` 串行化 (assert 第 1 个 end < 第 2 个 start, 无重叠)
  5. `web_agent_get_replay` happy path → `result.content[0].text` JSON parse 含 task_id/html_path/step_count
  6. `web_agent_get_replay` non-existent → `RuntimeError` → tool error (SystemExit 已转 RuntimeError)
  7. `web_agent_query_memory` empty domain → `result.structuredContent == {"result": []}`
  8. `web_agent_query_memory` URL form → 自动 normalize via extract_domain ("https://github.com/x" → "github.com")
  9. `web_agent_query_memory` seeded entries → list[dict] 含 ts/goal/success
  10. `main()` smoke: monkeypatch `mcp.run()` 拦截 + 验证 root logger 配 stderr handler

### Why
- V0.16.0 print → logger 改造解锁 stdio mode 兼容, V0.16.1 真接通 MCP 协议层, Claude Desktop / Cursor / 任意 MCP client 可调 web-agent
- subagent (Plan) 审核反馈采纳:
  - **FastMCP decorator 风格** (`@mcp.tool() async def`) 比 Server class 简洁, 官方 1.10+ 稳定 API
  - **module-level _RUN_LOCK** 比 class 属性简单, testability via monkeypatch.setattr 可重置
  - **per-tool-call 健康检查** 比 server-start 检查灵活: query_memory/get_replay 不需 Chrome, 不让用户 launch server 时被强制起 Chrome
  - **`progress_cb` DI 到 loop** 不破坏 loop/mcp 解耦 (loop 不 import mcp)
  - **测试用 `create_connected_server_and_client_session`** 是 mcp 1.10+ 公开 asynccontextmanager (非私有 API), 跑真协议层 + monkeypatch 业务依赖最稳
  - **替代方案否决**: subagent 早期提的 elicitation API + HTTP transport 留 V0.16.3 (Claude Desktop 2026-Q1 才正式支持)
- **dict vs list 序列化差异**: 实测 FastMCP 1.27 把 list 返回放 `result.structuredContent={'result': [...]}`, dict 返回放 `result.content[0].text` JSON. 测试断言两路径分别用对应字段

### Limitations (V0.16.2+ 待补)
- **progress_cb 未真 wire 到 web_agent_run**: cli.run_task 当前不接 progress_cb kwarg, mcp_server 创建 progress_cb 后没透传; V0.16.2 加 cli kwarg + 真 wire 主循环 + captcha poll 心跳 (R2 风险: captcha 长 wait 60s 内必发心跳)
- **Resources 留 V0.16.2**: `resources://web_agent/replay/<id>` + `memory/<domain>` 只读视图, 比 tool 干净
- **Elicitation 留 V0.16.3**: safety 拦截时 `ctx.elicit(...)` 让 client 弹"agent 想点'发送', 是否授权?" 替代 `WEB_AGENT_AUTO_APPROVE` env
- **HTTP transport 留 V0.16.3**: 默认 stdio (Claude Desktop 默认), `--http <port>` streamable HTTP 留扩展位

### Compatibility
- 公共 API 加: `mcp_server.{mcp, _RUN_LOCK, web_agent_run, web_agent_get_replay, web_agent_query_memory, _check_chrome_alive, main}` + `replay.render_to_file` + `loop.run_react_loop(progress_cb=...)`
- 旧 220 tests + 2 smoke skip 与 V0.16.0 一致 (loop 加 kwarg 默认 None 不影响 cli.run_task → loop 旧调用)
- 新增 10 mcp tests, 总 230 passed + 2 skipped
- runtime deps 零变化 (mcp[cli] 仅 dev-dep, 用户装 web-agent 不强制装 mcp)

## [0.16.0] - 2026-05-04

### Refactor (MCP server 第 1 步硬前提: print → logging.info(stderr))
- **6 模块 25 处 print() → logger** (业务逻辑零改动, 仅替代输出 channel):
  - `browser.py` 3 处 stealth fallback → `logger.warning()` (新加 logger)
  - `perceiver.py` 2 处: auto-dismiss failed → `warning`, dismissed N popup(s) → `info` (新加 logger)
  - `loop.py` 11 处 ReAct 主循环状态 (新加 logger):
    - `info`: captcha 命中 / captcha 已清除 / step N perceive / step N action / safety block / done
    - `warning`: captcha timeout / wallclock exceeded / llm-failed / anti-loop / max_steps
  - `cli.py` 7 处 (新加 logger; **保留 line 129/130 stdout** "=== 任务结果 === / result" 面向用户终端):
    - `info`: navigating / LLM provider / recalled memories / subgoal hint injected
    - `warning`: set_viewport_size 失败 / memory recall failed / memory record failed
- **`cli.main()` 入口加** `logging.basicConfig(level=INFO, stream=sys.stderr, format='[%(name)s] %(message)s')`:
  - INFO 走 stderr, stdout 仅留给用户面向输出 (=== 任务结果 ===)
  - pytest 不调 main(), 业务模块默认 root logger (lastResort handler 输出 stderr / WARNING 级以上, INFO 静默) — 旧 220 tests 输出不变
- **测试** 3 处 `capsys → caplog` 迁移 (`tests/test_browser.py` stealth 3 fallback case):
  - `with caplog.at_level(logging.WARNING, logger="web_agent.browser"): ... assert "..." in caplog.text`
- **保留** 7 处 print 不改 (用户面向 stdout, 与 MCP server 无关; MCP 模式下 server wrapper 拦截 stdout 重定向):
  - `cli.py:129/130` "=== 任务结果 ===" + result
  - `memory.py:180/182/186` CLI dump (web-agent-memory)
  - `replay.py:293/299` "wrote ..." (web-agent-replay)

### Why
- V0.16.0 目标是把 web-agent 暴露为 MCP server (Claude Desktop / 任意 MCP client 通过 tool 调用 web_agent_run). 其中 stdio transport 模式 stdout 是 JSON-RPC 通道, 任何 print 污染会破坏协议
- 第 1 步硬前提与 mcp_server.py 改造**解耦**: 业务逻辑零改动, 仅替代输出 channel, 220 tests 全过即可独立 commit, 失败可单独 revert 不影响后续
- subagent (Plan) 审核反馈采纳:
  - **`logger = logging.getLogger(__name__)` 每模块顶部** (新加 logger 4 模块: browser/perceiver/loop/cli; notify.py 已有保留)
  - **demos/*.py 不改** (用户直跑脚本, stdout 给人看, 不进 MCP stdio)
  - **stdout 保留白名单** 7 处 (用户面向 CLI dump / 任务结果, 不属内部诊断)
  - **WARNING 分级**: 含 "失败/未匹配/未安装/超时/timeout" → warning; 含 "命中/已清除/perceive/action/done" → info
  - **测试影响估算精确**: 仅 test_browser.py 3 case (capsys → caplog), 其他 capsys 测的是用户面向 stdout (test_cli/test_memory/test_replay), print 保留则 test 不动

### Compatibility
- 公共 API 零变化 (logger 是模块内部, 不影响 cli/loop/perceiver/browser 函数签名)
- 220 passed + 2 smoke skip 与 V0.15.11 一致 (test_browser 3 case caplog 迁移后通过)
- runtime deps 零变化 (logging 是 stdlib)
- 行为变化:
  - CLI 模式: 业务诊断信息从 stdout → stderr (用户跑 `web-agent ... 2>&1` 看到的内容不变)
  - 程序化调用: import web_agent.cli 不调 main() 时 logger 默认 lastResort handler (stderr WARNING+), INFO 静默 — 调用方可自行 `logging.basicConfig(...)` 配
  - MCP server (V0.16.1+) 模式: stdout 干净, 协议层无污染

### V0.16.1 next steps (本 commit 不做)
- 新建 `src/web_agent/mcp_server.py` (~200 行) 用官方 `mcp[cli]>=1.2` SDK
- 暴露 3 tools: `web_agent_run` / `web_agent_get_replay` / `web_agent_query_memory`
- progress notification (Claude Desktop 默认 60s timeout) + asyncio.Lock 串行化 + Chrome 9222 健康检查
- pyproject.toml 加 entry `web-agent-mcp = "web_agent.mcp_server:main"` + dev-dep `mcp[cli]>=1.2,<2`
- `tests/test_mcp_server.py` mock client (~10 case)

## [0.15.11] - 2026-05-04

### Removed (撤回 V0.15.10 Z 观察面板 → 切 MCP server 路径)
- **删** `extension/` 整目录 (`manifest.json` / `popup.html` / `popup.js` / `icon-128.png` / `extension/README.md`) — 浏览器扩展骨架不再维护
- **删** `src/web_agent/serve.py` (~30 行 stdlib HTTP server, 给扩展 popup iframe 用)
- **删** `pyproject.toml [project.scripts]` 的 `web-agent-serve = "web_agent.serve:main"` entry
- **保留** V0.15.10 commit (1907904) 历史 + CHANGELOG [0.15.10] 段不动 (创建新 commit, 不改写历史 — CLAUDE.md 提交纪律)
- **保留** V0.15.9 conftest dotenv autoload + smoke helpers 抽象 + 220 tests + 2 smoke skip

### Why
- V0.15.10 Z 观察面板路径仅 read-only (浏览器扩展嵌 iframe 看 web-agent-replay 已生成的 HTML), 无 LLM 调用 web-agent 的能力
- 用户决定走 **MCP server 路径** (V0.16.0+): Claude Desktop / 任意 MCP client 通过 tool 调用 `web_agent_run(goal, url)`, 涵盖 read+write 全场景, 替代 Z 观察面板的 read-only 用例
- 撤回防 V0.16.0 改造时维护两套交互前端 (扩展 + MCP) 增加负担; ARCHITECTURE.md 决策 1.1 否决 MV3 重写执行栈, 但 MV3 read-only 观察的 ROI 也弱于 MCP server 通用性
- subagent (general-purpose) 审核反馈采纳:
  - **`git rm extension/icon-128.png` 必须显式补**: 用户外部撤回时漏掉这个 git tracked 二进制, 不删则撤回不彻底 (commit 完仍有孤儿 icon)
  - **`git checkout HEAD -- CHANGELOG.md` 恢复 [0.15.10] 段**比手抄安全 (HEAD = V0.15.10 commit 含完整段)
  - **version 0.15.9 → 0.15.11 一步跳, 不经 0.15.10**: git history 顺序 V0.15.9 → V0.15.10 (1907904) → V0.15.11 (新), CHANGELOG [0.15.10] 段保留, 单调递增不算倒退

### V0.16.0 MCP server roadmap (引子, 实施时再展开)
- 第 1 步硬前提: print → logging.info(stderr) 全量改造 (cli.py / loop.py / browser.py / captcha.py 共 ~20 处), 220 tests 全过即可独立 commit
- 第 2 步: 新建 `src/web_agent/mcp_server.py` (~200 行) 用官方 `mcp[cli]>=1.2` SDK, 暴露 3 tools: `web_agent_run` / `web_agent_get_replay` / `web_agent_query_memory`
- 第 3 步: progress notification (Claude Desktop 默认 60s timeout) + `asyncio.Lock` 串行化并发 task + Chrome 9222 健康检查
- 详见 V0.16.0 commit message + ARCHITECTURE.md §6 (待加)

### Compatibility
- 公共 API 退: `web_agent.serve.main` 删 + entry script `web-agent-serve` 删
- src/ 业务模块零变化 (V0.15.10 的 serve.py 本就是 sibling 独立模块, 删除不影响 cli/loop/perceiver)
- runtime deps 零变化
- 220 tests + 2 smoke skip 与 V0.15.9 / V0.15.10 一致

## [0.15.10] - 2026-05-04

### Added (Z 观察面板 Phase 1/4: 扩展骨架 + serve helper)
- **新建** `extension/` (与 src/ tests/ 同级 sibling 目录, 不污染 python package):
  - `manifest.json` MV3, name="web-agent observer", permissions=`tabs`, host_permissions=`http://localhost:8000/*`, action.default_popup=popup.html
  - `popup.html` ~30 行: 480×640 popup, 顶 bar (蓝底 #1976d2 + W 图标 + "↗ Open in tab" 按钮), 下 iframe sandbox=`allow-same-origin allow-scripts allow-popups` 嵌 http://localhost:8000/index.html
  - `popup.js` ~15 行: `chrome.tabs.create()` 新 tab 打开 + iframe error log 兜底
  - `icon-128.png` 2143 字节: PIL 生成 128×128 蓝底 (#1976d2) 白色 W 字母, 复用 replay HTML 主色
  - `README.md` ~50 行: 5 步 dev mode 加载流程 + 故障排查表 + Phase 路线图
- **新模块** `src/web_agent/serve.py` (~30 行 stdlib only):
  - `web-agent-serve` entry: 本机 HTTP server 服务 `data/replays/`, 默认端口 8000, 默认 bind 127.0.0.1 (仅本机访问)
  - `--dir` / `--port` / `--bind` 三个 argparse 选项, 简单覆盖
  - 给扩展 popup iframe 用 — 选项 A 本机服务 (subagent 审核 vs file:// 跨 scheme MV3 几乎必崩 / vs background fetch+inline 渲染太复杂)
- **`pyproject.toml`** `[project.scripts]` 加 `web-agent-serve = "web_agent.serve:main"`

### Why
- 用户选 "A 全做" = Z (Chrome 观察面板, 3-5 天) + A (MCP server, 1-2 周) 串行
- ARCHITECTURE.md §1.1 否决 MV3 重写执行栈 — Z 观察面板是唯一 ROI 高的 MV3 路径: 不动主架构, 仅 iframe 嵌入现 web-agent-replay 已生成的 HTML
- subagent (Plan) 审核反馈采纳:
  - **`extension/` 在 repo 根**而非 `src/web_agent/extension/`: ARCHITECTURE.md src/ 表只列 python 业务模块, sibling 目录不破坏 layout
  - **选项 A 本机 HTTP 服务**: file:// 跨 scheme MV3 必崩, 本机 HTTP 最简, 加 `web-agent-serve` entry 一行命令更顺
  - **patch bump V0.15.10 而非 minor V0.16.0**: V0.16.0 留 Z 全 4 phase + A 全完成再合 tag, Phase 1 仅工具骨架 (无业务逻辑) 走 patch
  - **icon 128 size 偷懒**: MV3 manifest 推荐多 size (16/32/48/128), Phase 1 单 128 重用够 (Chrome 自动缩); 多 size 留 Phase 4 web store 上传时

### Limitations
- **Phase 1 仅骨架**: popup iframe hardcode http://localhost:8000/index.html, 不动态选 task; Phase 2 才加默认显示最新 task
- **要求用户跑 `web-agent-serve` 才能看 popup**: 没起服务 popup 显示连接错误; Phase 3 加 chrome.runtime 状态检测
- **不可执行**: 蓝本约束, 仅 read-only 观察, 用户操作浏览器仍走 `web-agent` CLI 主体
- **扩展未上 Chrome Web Store**: dev mode load unpacked 即用; 上架留 Phase 4 后 V0.16.0+

### Compatibility
- 公共 API 加 `web_agent.serve.main` (entry script `web-agent-serve`)
- src/ 业务模块零变化 (`serve.py` 是新增独立 module, 不被 cli/loop/perceiver 引用)
- runtime deps 零变化 (stdlib only)
- 220 tests + 2 smoke skip 不变 (serve.py 单测留 Phase 2/3 加, Phase 1 手测)

## [0.15.9] - 2026-05-04

### Refactor (W5-E smoke helpers /simplify pass)
- **`tests/_smoke_helpers.py`** 简化 4 处:
  - `assert_smoke_action(action, Action_cls)` → `assert_smoke_action(action)`: 去掉 Action_cls 参数, helper 直接 `from web_agent.llm.base import Action`. 仅 1 个 Action class 不需要参数化, 3 smoke files 调用各砍 1 个 import + 简化 1 行
  - `ensure_dummy_key(env_var, dummy_value)` 整 helper 删除: 2 行 wrapper 等价 `os.environ.setdefault(env_var, dummy)`. 3 smoke files 改用 stdlib 直接调
  - `_VALID_ACTION_TYPES = {...}` 抽常量, `assert_smoke_action` 用 `in _VALID_ACTION_TYPES` 替代 inline set literal
  - `smoke_skip_marker` reason f-string 嵌套三元 (重复 3×) flatten: 计算 `blocker_name` / `blocker_hint` 各 1 次
  - docstring: helpers 模块顶部 18 行 → 5 行; smoke_skip_marker 18 → 5; GPT smoke top docstring 24 → 13 (caller history 留 CHANGELOG)
- **统计**: 267 → 232 行 (-35 行 / -13%) 跨 4 文件; 220 passed + 2 skipped 行为 100% 一致
- **本次未动**: Action 5 合法 type 集移到 src/llm/base.py (out of scope, src/ 不动); blocker_env tuple 改 callable (2 字段 tuple 已是简单形式)

### Why
- V0.15.8 抽 helper 为去重, 但 helper 自身也露出可 simplify 项 (4 处) — `/simplify` subagent 自动检出后跑通
- `assert_smoke_action(action, Action_cls)` 参数化是过早泛化: web-agent 仅 1 个 Action class, 现状参数化反而让 caller 多写 import
- `ensure_dummy_key` 是 stdlib `os.environ.setdefault` 的 2 行 wrapper, 删除让代码更直接
- subagent 跳过 2 项: ① inline imports inside test funcs (repo-wide pattern, V0.15.8 没引入); ② `_VALID_ACTION_TYPES` 移到 src/ (本 commit src/ no-touch)

### Compatibility
- 公共 API 零变化, src/ 业务代码 0 行改动 (仅 __init__ version bump)
- helper 公开 API 变窄 (assert_smoke_action 签名 -1 param, ensure_dummy_key 删) — 仅 tests/ 内部用, 无外部 caller
- 220 passed + 2 skipped 与 V0.15.8 一致

## [0.15.8] - 2026-05-04

### Tests (W5-E smoke helpers 抽象 + GPT smoke 骨架 + blocker_env 防错路由)
- **新建** `tests/_smoke_helpers.py` (~75 行, anthropic + kimi + gpt 三 smoke 共享):
  - `TINY_GRAY_PNG_B64` 16×16 灰 PNG base64 常量 (Claude vision <8×8 拒, 安全下限)
  - `smoke_skip_marker(env_var, cassette_subdir, label, *, blocker_env=None)` 工厂: 既无 cassette 也无 key 时 skip 整文件; **新增 blocker_env 参数**: 当用户某 env var (e.g. OPENAI_BASE_URL) 设置但端点错配, 视为 "没 key for 本端点" 触发 skip 防错路由 record
  - `ensure_dummy_key(env_var, dummy_value)`: replay 阶段无 key 注入 dummy 让 *Client.__init__ 通过
  - `assert_smoke_action(action, Action_cls)`: smoke = pipeline alive 共用断言 (返 Action / type ∈ 5 / args dict / thought str)
- **重构** `tests/test_smoke_anthropic_real.py` + `tests/test_smoke_openai_kimi_real.py` 接 helper, 各砍 ~25 行去重 (skip 守卫 + PNG 常量 + 断言三段)
- **新建** `tests/test_smoke_openai_gpt_real.py` (~60 行) 用 helper:
  - hardcode `base_url="https://api.openai.com/v1"` 显式传防 OPENAI_BASE_URL env 劫持
  - hardcode `model="gpt-5.5"`, `tool_choice="required"` (OpenAIClient 默认), 空 marks 也能 PASS
  - skip 守卫加 `blocker_env=("OPENAI_BASE_URL", "openai.com")`: 当用户 .env 配 `OPENAI_BASE_URL=moonshot.cn` (主体跑 Kimi) 时 GPT smoke 整文件 skip, 防 GPT 真发请求被错路由到 Moonshot

### Why
- V0.15.4-7 累积 2 个 smoke (anthropic + kimi), 露出 16×16 PNG / skip 守卫 / Action 断言三段重复 ~25 行/文件; subagent V0.15.4 留 "第 3 个 smoke 时再抽" — V0.15.8 临界点到了
- subagent (Plan) 审核反馈采纳:
  - **helper 放 `tests/_smoke_helpers.py` 而非 conftest.py**: conftest 全局加载会让 219 非 smoke test collection 阶段也 import, 浪费; module 化按需 import 更干净
  - **抽 3 段** (常量 / skip 工厂 / 断言), 不抽 vcr_config: vcr_config 已是 conftest fixture, 11 个 filter_headers 全 provider 通用
  - 实施后第 3 个 smoke (GPT) 文件 ~60 行, 第 4 个起更短
- **GPT smoke 录制错路由 bug 现场修**: 第一版 GPT smoke base_url=None, 加 conftest dotenv autoload 后 SDK 读 `OPENAI_BASE_URL=moonshot.cn` 把请求路由到 Moonshot 端点 → 404 model not found → 录到错 cassette. 立即删 cassette + 显式 hardcode base_url + helper 加 blocker_env 守卫双重防御

### Limitations
- **GPT cassette 待用户接手录**: 单录 ~$0.005-$0.01, 用户需 `OPENAI_BASE_URL=https://api.openai.com/v1 OPENAI_API_KEY=sk-真OpenAI uv run pytest tests/test_smoke_openai_gpt_real.py --record-mode=once`
- **OpenRouter / Azure / Bedrock 路径仍待**: 同 helper 模板可加, V0.16.0+ 视用户场景决定
- **smoke 断言宽**: pipeline alive (Action 形状对) 不验行为 (LLM 选对 mark_id), W5-F+ golden trace 多 case 才覆盖

### Compatibility
- 公共 API 零变化, src/ 业务代码 0 行改动
- 旧 tests 全过, 总 222 collected = 220 passed + 2 skipped (Anthropic + GPT skip 待录, Kimi cassette V0.15.7 已有保持 pass)
- helper API 公开 (`tests/_smoke_helpers.py`), 后续 smoke 直接 import

## [0.15.7] - 2026-05-04

### Tests (W5-E Kimi cassette 真录通 + conftest .env autoload)
- **`tests/conftest.py`** 顶部加 dotenv autoload (4 行):
  ```python
  from pathlib import Path
  from dotenv import load_dotenv
  load_dotenv(Path(__file__).parent.parent / ".env", override=False)
  ```
  - 让 V0.15.4/V0.15.5 smoke skip 守卫 `os.environ.get("OPENAI_API_KEY")` 在 pytest collection 阶段能见到 .env 里的 key (此前 conftest 没 dotenv, 即使 .env 有 key 也整文件 skip)
  - `override=False`: shell 已 export 的优先 (CI 用 secrets export 路径), 不被 .env 覆盖
  - dotenv 实测能正确解析 .env line 15 的 3 空格缩进 key (subagent 误判 "load_dotenv 忽略缩进" 已 verify 错)
- **`tests/cassettes/test_smoke_openai_kimi_real/test_kimi_plan_smoke_pipeline_alive.yaml`** (7817 bytes):
  - 真 Moonshot 国内版 kimi-k2.6 调用录制完成, response status 200
  - 安全验证: REDACTED 计数 = 8 (filter_headers 11 个里命中 8: authorization / x-api-key / user-agent / x-stainless-{arch,os,runtime,lang,package-version})
  - 真 key 前 10 位反查 = 0 命中 (无残留)
  - `Bearer sk-` 子串反查 = 0 命中 (Authorization header 完全 REDACTED)
- **smoke pass**: 之前 V0.15.4/V0.15.5 是 skip, 现在 PASSED (7.26s) — pipeline alive 验证: Action(type="click", args={"mark_id":1}, thought="...") 真返

### Why
- V0.15.4 用 sk-xxx 占位 key 录到 401 cassette → V0.15.5 删 + 改国内版 .cn → V0.15.6 写诊断脚本分清"换行污染"vs"账号侧拒绝" → V0.15.7 终于真录通
- 多轮根因聚合:
  1. 用户 shell 临时 export 含换行 → curl `CURLE_URL_MALFORMAT`
  2. .env 里 key 干净但是国际版 platform.kimi.ai 创建的 (sk-Ysc...) 错配国内版 .cn 端点 → 401
  3. 用户在国内版 platform.kimi.com 新建 key (sk-31c...) 但 subagent hallucinate 警示后用户主动轮换为 sk-2oU... 第三个 key
  4. 第三个 key 仍 401 因 conftest 无 dotenv → fix dotenv → PASS
- subagent 审核反馈采纳:
  - **commit 用 "autoload" 而非 "fix"** (语义: V0.15.7 是新增 autoload 行为, 不是修旧 bug)
  - **真 key 前 10 位反查 cassette** (硬编码 sk-31 不稳, 用 grep + cut 动态取)
  - **load_dotenv override=False 显式传** (CI shell export 优先于 .env, 关键场景)

### Limitations
- **仅 Kimi 国内版 cassette 真录通**, Anthropic / Kimi 国际版 cassette 仍待用户接手
- **smoke 仍是 pipeline alive 验证, 非行为正确**: action.type ∈ 5 合法 + dict args + str thought, 不验是否选对 mark_id
- **录制方需 Moonshot 国内版账号 + 余额**: 单录 ¥0.03, cassette 进 commit 后任何人无 key 也能 replay

### Compatibility
- 公共 API 零变化, src/ 业务代码 0 行改动
- 旧 219 tests + Anthropic skip = 220 collected; 现 + Kimi PASSED = **220 passed + 1 skipped** (Anthropic 仍 skip 待录)
- runtime deps 零变化 (dotenv 早就是硬依赖)

## [0.15.6] - 2026-05-04

### Tools (Moonshot key 401 诊断脚本)
- **新建** `scripts/diagnose_kimi_key.sh` (~70 行 bash, 零依赖):
  - 优先读 `.env` 行 (handle 前导空格 `^[[:space:]]*OPENAI_API_KEY=`), fallback shell env
  - 输出 metadata: 前 6 位 / 字节长度 / 末尾 `od -c` (识别 \n / \r / 空格污染)
  - 双 curl 对比: raw key 直发 vs `tr -d '\r\n'` 清洗后再发, 都打到 `api.moonshot.cn/v1/models`, 只显示 HTTP code 不显示 key
  - case 分支按 HTTP code 给修复指引: 401 (无效/未实名/欠费) / 402-429 (quota) / 200 (key OK 但 pytest 链路问题, 可能 vcr cassette stale)
  - **不打印 key 主体**, 只 metadata + HTTP code, 符合 CLAUDE.md "不把 secret 写日志" 约束
- 用户使用: `bash scripts/diagnose_kimi_key.sh [.env路径]` 一次跑出根因 + 修复方向

### Why
- V0.15.5 用户跑 `pytest --record-mode=once` 报 401, 多轮排查后发现两层问题:
  1. 用户 shell 临时 export 的 `$OPENAI_API_KEY` 含换行 → curl 触发 `CURLE_URL_MALFORMAT`
  2. `.env` 文件里的 key 干净 (51 bytes, 末尾 ASCII 无换行), 双 curl 都 401 → 真因是账号侧 (未实名/未充值/key 停用) 而非换行
- 没有诊断脚本时这两层混在一起, 排查耗费 4-5 轮对话; 脚本一步分清"换行污染"vs"账号侧拒绝"
- 复用价值: 任何后续 401 故障 (任意 user/CI/不同时间) 跑一次脚本就拿根因, 不必每次重新诊断
- subagent (general-purpose) 审核策略反馈: 不直接 cat .env 读 key (CLAUDE.md "不写日志" 即便会话私密也不破例), 走"脚本读 + 只输出 metadata"路径, 零 key 泄漏面

### Limitations
- 仅诊断 OPENAI_API_KEY 一种 (Moonshot 国内版); 想覆盖 Anthropic / OpenAI 公网 / Kimi 国际版 需复制改 base_url
- 不验"key 是国内版还是国际版" (账号系统隔离, curl 401 看不出来源端点错配); 用户得自查控制台来源
- bash 仅, 假设有 curl + grep + sed + od + tr (POSIX 标配, macOS/Linux 都有, Windows 需 Git Bash 或 WSL)

### Compatibility
- 公共 API 零变化; src/ 业务代码 0 行改动
- 219 tests + 2 smoke skip = 221 collected 不变, pytest gate 不影响
- 脚本独立 tooling, 不挂任何 hook / 不被 pytest / cli 调用

## [0.15.5] - 2026-05-04

### Tests (W5-E Kimi smoke 端点切换 国际版 .ai → 国内版 .cn)
- **`tests/test_smoke_openai_kimi_real.py`** 单行端点改:
  - `_KIMI_BASE_URL = "https://api.moonshot.ai/v1"` → `"https://api.moonshot.cn/v1"`
  - 顶部 docstring + skip reason 文案"国际版" → "国内版" 同步
  - 注明 V0.15.4 → V0.15.5 切换原因 + 国际版用户自改路径
- **删 V0.15.4 跑 sk-xxx 占位 key 录到的 401 cassette** (untracked, 无 git rm 风险): `tests/cassettes/test_smoke_openai_kimi_real/test_kimi_plan_smoke_pipeline_alive.yaml` 删除. 该 cassette host=api.moonshot.ai + status=401 Unauthorized, 任何 replay 都会让 smoke 红, 必须重录
- **CHANGELOG**: V0.15.4 节遗留措辞"国际版 .ai" → 解读为"V0.15.4 为国际版骨架, V0.15.5 为国内版"; V0.15.4 节内容不动 (历史不改写, 创建新 commit 优先)

### Why
- 用户实际持有 Moonshot 国内版 (platform.moonshot.cn) key, V0.15.4 hardcode 国际版 .ai 让用户没法直接 record
- vcr cassette `match_on=[scheme,host,port,path]` 默认锁 host, 跨端点 replay 必 fail (`CannotOverwriteExistingCassetteException`); 一份 cassette 只服务一个端点
- subagent (general-purpose) 审核反馈采纳:
  - **方案 A (彻底替换 .ai → .cn)** 而非方案 B (双 cassette intl + cn) 或 C (env-driven): 用户 scope 锁定国内, B 需双 key 过早抽象, C 让 cassette host 与 env 解耦反成不一致风险源
  - **必须删 V0.15.4 跑出来的 401 cassette**: 即便 untracked 也得删 (用户后续 record-mode=once 不会 overwrite 已有 cassette, vcr 默认 once 模式遇旧 cassette 直接 replay)
  - **V0.15.5 patch bump 合理**, 不要 amend V0.15.4 (V0.15.4 commit 9ea89e3 已 push 习惯路径不可改写, 创建新 commit 路径优先 — CLAUDE.md 提交纪律)

### Limitations
- **国际版 .ai 用户不再受支持**: 需自行改 `_KIMI_BASE_URL` 重录, 或后续 V0.15.6+ 加 `test_smoke_openai_kimi_intl_real.py` 双骨架
- **国内端点 cassette 仍需用户接手录**: 我无 Moonshot 国内 key, 沙箱里也不能调 platform.moonshot.cn (curl/dns 受限), 只能改源码到 .cn 不能录
- **smoke 仍 mock-level pipeline alive 验证, 非行为正确**: 同 V0.15.3 / V0.15.4 设计

### Compatibility
- 公共 API 零变化
- 219 tests + 2 smoke skip = 221 collected (skip 守卫不变, 端点改不影响 skip 行为)
- runtime deps 零变化

## [0.15.4] - 2026-05-03

### Tests (W5-E real LLM smoke 骨架补 OpenAI/Kimi 路径)
- **新建** `tests/test_smoke_openai_kimi_real.py` (~85 行, 同 V0.15.3 Anthropic smoke 模板):
  - 1 case `test_kimi_plan_smoke_pipeline_alive`: 真调一次 `OpenAIClient(base_url="https://api.moonshot.ai/v1", model="kimi-k2.6").plan(...)`
  - 复用 V0.15.3 `tests/conftest.py` 的 `vcr_config` fixture (无修改, filter_headers `authorization` 已覆盖 Kimi Bearer auth)
  - 复用 16×16 灰 PNG base64 常量 (节约 cassette body 体积)
  - **关键差异**: Kimi 走 `tool_choice="auto"` (Moonshot 不支持 "required"), 16×16 灰图 + 空 marks 大概率不吐 tool_call → 加一个 dummy `Mark(id=1, tag="button", text="搜索")` + 明确 prompt "请点击 mark_id=1", 让 Kimi 在 thinking-disabled + tool_choice=auto 下高概率 emit click tool_call
  - **hardcode** `base_url=https://api.moonshot.ai/v1` + `model=kimi-k2.6`: cassette vcr 默认 match `[method, scheme, host, port, path]`, 跨端点 (.ai vs .cn) 不能 replay; 本 smoke 只录国际版
  - skip 守卫: `not _HAS_CASSETTE and not OPENAI_API_KEY` (注意 env var 是 OPENAI_API_KEY 不是 KIMI_API_KEY, Kimi 走 OpenAI SDK)

### Why
- V0.15.3 Anthropic smoke 骨架已 ship, 但 OpenAIClient + Kimi/GPT 路径无端到端 smoke
- 用户说"用 Kimi key", 直接补 Kimi 版骨架让用户/任何 Moonshot 用户也能录 cassette 进 CI
- subagent (Plan) 审核反馈采纳:
  - **文件名 `test_smoke_openai_kimi_real.py` 而非 `test_smoke_kimi_real.py`**: provider+endpoint 组合命名, 未来纯 GPT 版叫 `test_smoke_openai_gpt_real.py`, OpenRouter 叫 `test_smoke_openai_openrouter_real.py`
  - **必须 hardcode base_url + model**: cassette 跨用户 replay 的前提
  - **dummy Mark 必加**: 16×16 灰图 + 空 marks + tool_choice=auto 是 "Kimi 几乎必抛 RuntimeError" 配方, dummy mark 让 LLM 有明确点击目标; Anthropic smoke 用 `tool_choice={"type":"any"}` 强制 tool, 无此问题
  - **国际/国内 cassette 互斥**: vcr URL match 锁 host, 录哪端点 replay 哪端点 — 选国际版 .ai 因 docs 也用此

### Limitations
- **仅国际版 .ai cassette**: 国内版 .cn 用户不能直接复用; 想覆盖再加 `test_smoke_openai_kimi_cn_real.py`
- **cassette 录制方需 Moonshot 账号**: cassette 进 commit 后任何人可 replay, 但首次录要 sk-xxx + 余额
- **smoke 仍是 mock-level 验证**: pipeline alive ≠ 行为正确; W5-F+ 加 golden trace 多 case 才覆盖行为
- **GPT/OpenRouter 路径未骨架化**: 同模板可加, V0.15.5 / V0.16.0 视用户场景决定

### Compatibility
- 公共 API 零变化
- 旧 219 tests + V0.15.3 anthropic skip = 1 = 220, 现 + Kimi skip = 1 = 总 221 collected (219 passed + 2 skipped)
- runtime deps 零变化, V0.15.3 加的 pytest-recording 复用

## [0.15.3] - 2026-05-03

### Tests (W5-E real LLM smoke 骨架, 待用户首次 record-mode=once)
- **新建** `tests/conftest.py`:
  - `vcr_config` module-scope fixture: 锁默认 cassette filter, 元组形式 (name, "REDACTED") 保 header 但脱敏 (利于 cassette diff)
  - 过滤 11 个敏感 header: authorization / x-api-key / anthropic-version / openai-organization / user-agent / x-stainless-{arch,os,runtime,runtime-version,lang,package-version} (Anthropic SDK 真发的机器画像)
  - 过滤 query param `api_key`
  - 默认 `record_mode=once` (有 cassette replay, 否则录制)
- **新建** `tests/test_smoke_anthropic_real.py`:
  - 1 case `test_anthropic_plan_smoke_pipeline_alive`: 真调一次 `AnthropicClient.plan(goal="搜苹果价格", screenshot_b64=16×16灰PNG, marks=[], trace=空)`
  - 断言 (smoke = pipeline alive, NOT behavior correctness): 返 `Action` dataclass / `type ∈ 5 合法值` / args dict / thought str
  - 16×16 灰 PNG base64 常量 (112 字节): Claude vision <8×8 拒, 16×16 是安全下限
  - **skip 守卫** `pytestmark = pytest.mark.skipif(not _HAS_CASSETTE and not _HAS_KEY, reason=...)`: 骨架阶段无 cassette + 无 key → 整文件 skip, 219 主 tests + 1 skipped 全绿不阻塞
  - replay 阶段 (有 cassette 无 key): 注入 dummy `sk-ant-cassette-replay-not-real` 让 `AnthropicClient.__init__` 通过, vcr 拦下出站请求不会真用此 key
- **`pyproject.toml`** 加 dev dep `pytest-recording>=0.13.4` (传依 vcrpy 8.1.1 + pyyaml 6.0.3 + wrapt 2.1.2)
- **`.gitignore`** 加 `tests/cassettes/**/*.yaml.bak` (vcrpy 原子写盘留 .bak 临时文件; 主 yaml 进 commit)

### Why
- V0.15.2 README "已知缺口" 列了 "真实 LLM smoke + cassette" 但留作用户接手. 实际可在沙箱阶段把"骨架 + 工具配置 + skip 守卫"全做好, 用户接手只需提供 key 跑一次 `--record-mode=once`, 大幅降低接手成本
- subagent (Plan) 审核反馈采纳:
  - **版本走 V0.15.3 而非 V0.16.0-rc1**: SemVer 简化形式无 pre-release 习惯, rc1 破坏 changelog 锚点连续性; 骨架本质是 docs+dev-dep+1 个 skip test, 不该占 minor (V0.16.0 留给 cassette 真录后)
  - **16×16 灰 PNG 而非 1×1 透明**: Claude vision <8×8 实测拒 "image too small to process"
  - **filter_headers 加 user-agent + x-stainless-***: SDK 发机器画像 header, 不滤泄漏 Python/uv 版本+OS+架构
  - **assertion 用 isinstance(Action)**: 之前误以为返 tuple, 实际返 `Action(type, args, thought)` dataclass (`llm/base.py:20`)
  - **smoke 设计意图明示**: "pipeline alive, NOT behavior correctness" — 真 LLM 在空 marks + 灰图下回什么不可断言, 只断"返合法 Action"

### Limitations
- **骨架只跑 skip**: cassette 未录前真测被 skip, 不阻塞主 219 tests; 用户接手前实际无 LLM 真验证
- **仅 Anthropic**: OpenAI/Kimi smoke 留下次 (V0.15.4? 同模式照搬)
- **assertion 极宽**: 5 合法 action_type ∈ 检查 + dict/str type 检查, 等于"SDK 没崩 + tool_use 路径走通"; 真要锁行为需多 case + golden trace, 那是 W5-F+ scope
- **token 成本**: 用户首次 record 一次 ≈ $0.006 (claude-sonnet-4-6 vision, 1100 input + 150 output), 可忽略

### Compatibility
- 公共 API 零变化
- 旧 219 tests 零修改全过; 新 1 case 默认 skip (无 cassette + 无 key) → 总 220 collected, 219 passed + 1 skipped
- dev-only deps 加 (pytest-recording / vcrpy / pyyaml / wrapt), runtime deps 零变化

## [0.15.2] - 2026-05-03

### Docs (架构决策入账 + README known-gap 补全)
- **新建** `docs/ARCHITECTURE.md` ~250 行 4 章:
  - **决策树**: 5 条核心选择 (CDP 接管 vs MV3 / SoM vs a11y / patchright vs stealth / trace.db vs memory.db 分库 / W5-C prompt augmentation vs plan-and-execute), 每条列可选项 + 选了什么 + 否决理由
  - **模块边界**: 14 模块一句话职责 + 严格依赖方向 (domain ← ports ← 业务层 ← 组合根) + LLMClient Protocol 不被业务层导入只在 cli.py 实例化的约束
  - **三轨同道**: W5-A reflect / W5-D.2 memory / W5-C subgoal 三个 milestone 都走 `step=-1 memory_recall` synthetic trace step 通道, 累计 0 次 LLMClient Protocol 改动 — 项目最重要的"通道复用 vs 新增抽象"原则
  - **双层防御**: safety 硬拦 + anti-loop 硬 abort + reflect 软提示 + captcha 暂停 — 4 类信号正交 (失效根因不同/对策不同), captcha 在 perceive 之前 / reflect 在 perceive 之后的位置原因
  - 附录 A 版本里程碑速览; 附录 B 硬约束 (test gate / gitignore / secrets / actuator 退化)
- **README 更新**:
  - "当前状态" 段 V0.13.1 → V0.15.2, 187 → 219 tests, audit gap 4/6 → 6/6, W5 部分 ✅ → 全 ✅, 加 ARCHITECTURE.md 索引行
  - 路线图 W5-D.2 / W5-C 标 ✅, MVP 限定语去掉
  - "已知缺口" 加 2 条:
    - **真实 LLM smoke + cassette**: 219 tests 全 mock LLM, 无 cassette 录真 Anthropic/OpenAI 响应; 需用户接手用真 API key + `vcr.py` / `pytest-recording`, 受 Claude 沙箱回收 + token cost 限制无法本会话完成
    - **SYSTEM_PROMPT snapshot test**: `llm/_schema.SYSTEM_PROMPT` 7 条规则改动易回归无 lock, 留位下次以 `tests/test_llm_schema_snapshot.py` 补
  - 目录树 tests 187 → 219 / 16 → 18 文件; docs 加 ARCHITECTURE.md 行
- **bump** `__version__` 0.15.1 → 0.15.2; `pyproject.toml` version 同步

### Why
- 11 个 milestone (V0.6.0 → V0.15.1) 累积的架构决策散在 CHANGELOG / commit message / 我的脑里, 接手者读不到 "为什么不走 patchright" / "为什么 W5-C 不调真 LLM" / "为什么 reflect/memory/subgoal 共用一个 trace 通道"
- README 之前标的 audit gap 范围已被 V0.12.0~V0.15.1 实际填到 6/6, 也漏标 W5-D.2 / W5-C 完成; 路线图与现状对齐
- 真实 LLM smoke + SYSTEM_PROMPT snapshot 是已识别但本会话受沙箱限制无法做的两个 known-gap, 入账避免下次接手"为啥这俩没做"反查会话

### Compatibility
- 零代码改动 (仅 docs + README + version bump + CHANGELOG)
- 219 tests 零变化全绿
- 公共 API 零变化, 行为零变化

## [0.15.1] - 2026-05-03

### Tests (audit gap 100% 收尾: browser + anthropic 最后两模块)
- **新建** `tests/test_browser.py` 8 case: connect 三元组返回 / 空 contexts RuntimeError / 无 pages 调 new_page / apply_stealth 5 路径 (apply_stealth_async / apply_async / API 未匹配 skip / ImportError 吞 / 一般 Exception 吞)
- **新建** `tests/test_llm_anthropic.py` 7 case: __init__ env api_key / 显式 override env / base_url env 透传 / 显式 base_url 优先 / 缺 api_key RuntimeError / 显式 model / _tools 非空 (≥4 actions)
- **不改** browser.py / anthropic.py 任何一行 (test-only)
- 实现要点:
  - browser.py: AsyncMock + SimpleNamespace + monkeypatch.setitem(sys.modules, ...) 模拟 playwright_stealth 多版本 API
  - anthropic.py: patch web_agent.llm.anthropic.AsyncAnthropic, 验证传入 SDK 的 kwargs 含 max_retries=4/timeout=120/base_url 等

### Why
- 完整 audit gap 收尾: 本会话累计填补 perceiver V0.12.0 / trace V0.12.4 / cli V0.12.6 / loop 主体 V0.12.8 / **browser V0.15.1 / anthropic V0.15.1** = **6/6 全部模块覆盖**
- 之前 README 标的 "browser/anthropic 真实 API 测试 难度 ROI 低" 简化为 init 路径 + fallback 分支测 (不真调 API), 收益/风险比合理
- 本会话所有 audit gap 100% 收尾, "11/11 模块全单测覆盖" 状态达成

### Compatibility
- 零代码改动 (browser.py / anthropic.py 全不动)
- 旧 204 测试零修改全过; 新 15 case (8 browser + 7 anthropic), 总 219 tests 全绿
- 公共 API 零变化, 行为零变化

## [0.15.0] - 2026-05-03

### Added (W5-C: 分层规划 prompt augmentation 路线)
- **新模块** `src/web_agent/planner_hierarchy.py` (~70 行, stdlib only):
  - `should_decompose(goal: str) -> bool` 启发式: 长任务 (≥200 字) OR ≥2 个序号前缀 (1./①/-) → True; env `WEB_AGENT_SUBGOAL_DISABLE=true` 任何 truthy 值覆盖一切返 False
  - `build_subgoal_hint_text() -> str` 返回纯字符串模板 (固定常量, 无 LLM 调用): 提示 LLM 在第一步 thought 里把任务拆 3-6 个 subgoal 再执行
  - `merge_into_memories(memories_str, subgoal_hint) -> str` 拼接, 保 W5-D.2 channel 通道复用
- **`cli.run_task` 加 hook** (在 W5-D.2 memory recall 之后, run_react_loop 前):
  - `if should_decompose(goal): memories_str = merge_into_memories(memories_str, build_subgoal_hint_text())`
  - 复用 V0.14.0 W5-D.2 已建好的 `step=-1 memory_recall` 通道, 零改动 loop.py / Protocol
- **env**: `WEB_AGENT_SUBGOAL_DISABLE=true` 完全关
- **测试** `tests/test_planner_hierarchy.py` 14 case (parametrize 展开):
  - should_decompose 7: 短任务 / 长 250 字 / `1.` 序号 / `①` 圆圈 / `-` bullet / 单序号短任务不触发 / env disable 4 truthy 值覆盖
  - build_subgoal_hint 1: 含 "subgoal" / "thought" / "3-6" 关键词
  - merge_into_memories 4: append+分隔 / 空 existing / 空 subgoal / 都空

### Why
- 蓝本明确点 subgoal 拆分; 当前 ReAct loop 单层, 复杂任务 ("Amazon 搜耳机 → 比价 → 加购 → 填地址") 易在中段 stuck
- subagent (Plan) 原方案要真调 LLM (一次额外 plan() 调用拿 subgoal 计划), 但 `screenshot_b64=""` 在真 Anthropic/OpenAI SDK 兼容性未验证 → **简化为 prompt augmentation 路线**: 不调 LLM, 仅注入 hint 字符串, LLM 自己用 thought 字段拆
  - 零 token 浪费 (无额外 LLM 调用)
  - 零 SDK 兼容风险
  - 零 Protocol 改动
  - 真实效果略弱于 plan-and-execute, 但 ROI/风险比远好
- 复用 W5-D.2 V0.14.0 已建好的 `step=-1 memory_recall` channel: cli 端 1 行 merge, loop / Protocol / safety / captcha 全不动
- 启发式触发严控: 短任务 (e.g. "搜苹果价格") 跳过, 长任务才付一段 hint 的代价

### Limitations
- **不是 plan-and-execute 强约束**: LLM 收到 hint 后是否真拆 subgoal 取决于自己, 我们只是 nudge
- **没在真 LLM 上 eval**: 无法量化 hint 是否真提升复杂任务成功率, MVP 假设 "LLM 看到提示就会用"
- **触发启发式可能漏判**: 例如英文任务用 "First, ... Second, ..." 不会被 `_NUM_PREFIX_RE` 匹配, 长度也可能 <200; 真用上后视情况调
- **若需真 plan-and-execute**: 未来 W5-C.2 可加 `WEB_AGENT_SUBGOAL_MODE=force-plan` 调真 LLM 走 plan() 拆 subgoal (含 1x1 PNG fallback 等 SDK 兼容工程)

### Compatibility
- 公共 API 加 (`planner_hierarchy.{should_decompose, build_subgoal_hint_text, merge_into_memories}`)
- LLMClient Protocol 零变化 (W5-C 完全走 trace/memories 通道)
- run_react_loop 签名零变化 (V0.14.0 W5-D.2 已加的 `memories=` kwarg 直接复用)
- 旧 190 测试零修改全过; 新 14 case (parametrize 展开), 总 204 tests 全绿
- 行为变化: 长任务 / 带序号任务 trace step=-1 多出 subgoal hint 段 (短任务零感知)

## [0.14.0] - 2026-05-03

### Added (W5-D.2: 长期记忆 inject 到 planner 上下文)
- **`memory.py` 加 `format_memories_for_trace(entries, goal_trunc=60, result_trunc=80)`**: 渲染 list[MemoryEntry] 为 LLM 可读字符串
  - 格式: `过去在该 domain 跑过 N 个任务 (newest first):\n[ts] OK|FAIL goal[:60] -> result[:80]\n...`
  - 空 list 返 "" (caller if-truthy 跳过 inject)
  - 5 条 × ~140 char ≈ 700 char total — token budget 友好
- **`loop.run_react_loop` 加 `memories: str | None = None` kwarg**: 主循环前 trace.append synthetic `Step(step=-1, action_type="memory_recall", observation=memories[:2000])`
  - **不写 sqlite** (与 W5-A reflect hint 同档: in-memory soft hint, 不污染 trace.db 实际执行事件流)
  - LLM 第一次 plan() 通过 `Trace.for_llm()` 自然看到跨 session 历史
  - step=-1 与正常 0..N-1 隔开, 语义"前置上下文非本轮行动"
- **`cli.run_task` 在 `run_react_loop` 前 try/except 包 recall**: 拿 memory entries → format → 透传 `memories=` 到 loop
  - 复用 V0.13.0 的 `WEB_AGENT_MEMORY_DISABLE` env (整体关 record + recall)
  - 失败 (db 损坏 / 权限) → memories=None 跳过 inject, 不阻塞主路径
- **测试** +3 case (旧 187 + 新 3 = 190):
  - `test_memory.py::test_format_memories_empty_returns_empty_string`: 空 list 返 "" (caller skip inject)
  - `test_memory.py::test_format_memories_for_trace_renders_ok_fail_and_truncates`: OK/FAIL 标记 + WALLCLOCK_EXCEEDED 透传 + goal 60 / result 80 截断验证
  - `test_loop_main.py::test_memories_injected_as_synthetic_step_minus_one`: RecordingLLMClient 验证第一次 plan 看到 memory_recall step + sqlite 不含 step=-1 (不污染持久化)

### Why
- V0.13.0 W5-D MVP 仅持久化 + CLI dump, LLM 看不到 → "写了但没读" 悖论, memory 是死数据
- subagent (Plan) 评估 5 决策点全采纳:
  - 不改 LLMClient Protocol, 走 trace.observation 通道 (与 W5-A reflect hint 同档定位)
  - synthetic step=-1 与真实 0..N-1 隔开
  - memories 不写 sqlite (跨 session 注入 ≠ 本次 task 事件)
  - 5 条 × goal 60 / result 80 截断 → token budget 友好
  - cli 端 try/except graceful (db 失败不阻塞主路径)
- 反检测影响零 (memory_recall step 不触发 actuator/keyboard/network, 全 in-memory, 不影响 stealth/timing)

### Limitations
- **deque maxlen=20 被 memory step 占 1 槽**: 长任务 19 步后 memory 被挤出 (FIFO popleft); 后期 memory 价值已被 trace 自身覆盖, 接受
- **`Step.for_llm()` 自带 observation[:200] 二次截断**: format 端宽松 + for_llm 严守, 双保险
- **memory_recall 不写 sqlite**: replay UI 不显示这一步; 用户想看历史 inject 走 `web-agent-memory <domain>` CLI 即可
- **没新 eval 验证 LLM 真用了记忆**: MVP 假设 "LLM 看到就会用", 真实效果需用户跑同 domain 多次任务观察策略变化

### Compatibility
- 公共 API: `run_react_loop` 加 `memories=None` kwarg, backward-compat (默认 None 不 inject)
- LLMClient Protocol 零变化 (W5-D.2 走 trace 通道, 不动 plan 签名)
- 旧 187 测试零修改全过; 新 3 case, 总 190 tests 全绿
- 行为变化: 跑 task 时 LLM trace 多出一条 step=-1 memory_recall (仅 cross-session 同 domain 有过历史时)

## [0.13.2] - 2026-05-03

### Docs (W5-D + audit gap 收尾 README sync)
- **README V0.12.4 → V0.13.1 catch-up** (V0.12.5 上次 refresh 后又 ship 了 V0.12.6/V0.12.7/V0.12.8/V0.13.0/V0.13.1, 累计 stale):
  - 当前状态: V0.12.4/148 tests → V0.13.1/187 tests; W milestone 加 W5-D ✅ V0.13.0
  - 加 audit gap 收尾一句话: perceiver/trace/cli/loop 主体 abort 路径四大模块全单测覆盖
  - 路线图: W5-D ✅ + 标 W5-D.2 planner inject 留位, W5-C 仍未启动
  - CLI 段加 `web-agent-memory <domain> [--limit N] [--db ...]` 6 行说明 + 输出格式示例
  - env 段加 Memory 类小段 (`WEB_AGENT_MEMORY_DISABLE` / `WEB_AGENT_MEMORY_DB`)
  - 目录段 src/ 加 memory.py / cli entry 列 web-agent-memory; tests/ 13→16 文件 148→187 case; data/ 加 memory.db
- **不动**: 反检测段 / 法律边界 / 安装段 / Chrome 启动表 / BYO LLM 段 (这些没过期)

### Compatibility
- 零代码改动 (本 commit 仅 README + CHANGELOG + version bump)
- 187 tests 零变化全绿
- 公共 API 零变化, 行为零变化

## [0.13.1] - 2026-05-03

### Refactor (V0.13.0 simplify pass)
- `cli.py`: `web_agent.memory` 4 个符号从函数内 import 提到模块顶层 (memory.py 是 stdlib only 不会 ImportError; cli 顶层已 import 重模块 loop/browser/llm, memory 增量微不足道; 提可读性 + 静态分析友好)
- `memory.py`: docstring + `is_success` 注释 "5 类失败 marker" 修正为 "6 类" (FAILURE_MARKERS 实际 6 项: max_steps / WALLCLOCK / SAFETY / CAPTCHA / LOOP / LLM)
- 行为零变更; 187/187 tests 全绿
- 跳过项: `record_task` per-call 重开 conn (per-task 低频, schema 自愈 > 复用 conn) / `is_success` 空 result False 防御 (无害且 test 已覆盖) / env truthy 解析 helper 抽取 (跨 loop/cli/notify/perceiver 4 处 ad-hoc, 跳出本次 scope, 应另起 refactor)

## [0.13.0] - 2026-05-03

### Added (W5-D: 长期记忆 MVP)
- **新模块** `src/web_agent/memory.py`: 跨 session 持久化 task outcome by domain
  - `MemoryEntry` dataclass: ts (float) / domain (str) / goal (str) / result (str, 200 字截断) / success (bool)
  - `extract_domain(url)` 纯函数: `urlparse(url).netloc.lower()` (空/None/异常返 ""; about:blank, javascript: 等无 netloc URL 自然落到空)
  - `is_success(result)` 纯函数: 6 类失败 marker substring 命中即 False (与 loop.py V0.5.0/V0.5.2/V0.6.0/V0.9.0 内 graceful abort result 字符串前缀对齐: `(max_steps` / `WALLCLOCK_EXCEEDED` / `SAFETY_BLOCK` / `CAPTCHA_TIMEOUT` / `LOOP_DETECTED` / `LLM_FAILED`)
  - `init_memory_db(db_path)`: 单表 `memories(id PK AUTOINCREMENT, ts, domain, goal, result, success)` + `idx_memories_domain_ts` 索引
  - `record_task(db_path, domain, goal, result, success)`: append 一行, 200 字截断 result
  - `recall_by_domain(db_path, domain, limit=5) -> list[MemoryEntry]`: ORDER BY ts DESC; db 不存在返 [] 友好兜底
  - 与 `trace.db` **分开** (`data/memory.db`): schema 演进独立 / 备份/清理粒度独立
- **`cli.py` 集成 hook** (`run_task` 末尾, 紧贴 `return result` 之前):
  - try/except 包裹: 记忆失败 (磁盘满/权限) 不阻塞主路径返回, 仅 print warning
  - 从 `start_url` 提取 domain (无 url 任务 domain="")
  - `is_success(result)` 自动判定 success/fail
- **新 CLI** `web-agent-memory <domain> [--limit N] [--db ...]`:
  - dump 该 domain 最近 N 条记忆 (newest first)
  - 输出格式 `[ISO_ts] OK|FAIL  goal[:60]  ->  result[:80]`
  - 空 domain 友好提示 `(no memories for domain=...)`
- **env**:
  - `WEB_AGENT_MEMORY_DISABLE=true` 完全关 (CI / 不想留痕迹)
  - `WEB_AGENT_MEMORY_DB=data/memory.db` 自定义路径
- **测试** `tests/test_memory.py` 27 case (parametrize 展开后):
  - extract_domain 7 (parametrize): 标准 / 端口 / lowercase 归一 / 空/None / about:blank / javascript:
  - is_success 9 (parametrize): 正常结果 + 中文 + 空 + 6 类失败 marker
  - FAILURE_MARKERS 与 loop.py 对齐回归保护 1
  - init_memory_db 2: 表+索引 / parent dir mkdir
  - record_task + recall_by_domain 5: 写读 / DESC 排序 / domain 过滤 / limit / db 不存在返 [] / result 截断 200
  - main CLI 2: dump 多条 / 空 domain 友好提示
- **`.gitignore`** 加 `data/memory.db`

### Why
- 蓝本认知层 (ReAct + 短期记忆 V0.5.0 + 自反思 V0.11.0 + step limit + 回退暗含 W5-A 4 策略) 已完成
- 长期记忆是项目延伸 (蓝本未明确列出但实际有用): 跨 session 学到 "在 X 站之前这样做过 / 失败过", 为未来 W5-D.2 inject 到 planner 提供数据基础
- subagent (Plan) 评估 7 决策点全采纳:
  - failure 判定 substring (与 replay.py `_RESULT_HIGHLIGHT` 风格一致, 无正则复杂度)
  - memory.db 与 trace.db 分开 (schema 解耦)
  - extract_domain 空 url 返 "" 不抛 (友好降级 + 仍允许 record)
  - V0.13.0 minor (新模块 + 新 CLI + 新行为轴 + 新 db 文件 + 新 env, 远超 patch)
  - try/except 包裹集成 hook (记忆不阻塞主路径)
  - 不动 planner Protocol / 不 inject observation (留 W5-D.2)
  - AUTOINCREMENT vs trace 复合 PK 风格不一致 (两 db 解耦, 接受)

### Limitations
- **不 inject 到 planner**: 当前 MVP 仅持久化 + CLI dump; LLM 看不到历史记忆 → 无法基于过去经验调整策略。需 W5-D.2 改 planner Protocol 或在 trace.observation inject 历史 (类似 W5-A reflect hint)
- **start_url=None 任务 domain 全为 ""**: 大多 demo 有 start_url, 但 CLI 直接传 goal 无 url 时 domain 全空 → recall("") 列表会膨胀; MVP 接受, 未来加 "首屏 URL 探测" 改进
- **failure marker 硬编码字符串**: loop.py 改文案 (e.g. `(max_steps reached)` 替代 `(max_steps 耗尽未完成)`) → memory.py 的 marker 需同步; 已通过 `test_failure_markers_align_with_loop_signals` 单测兜回归
- **AUTOINCREMENT vs trace 复合 PK 风格不一致**: 两 db 解耦下可接受
- **SQLite 默认锁**: 当前 run_task 串行无并发; 未来并发跑多 task 需考虑 WAL — 列入 W5-D.2 风险

### Compatibility
- 公共 API 增 (`memory.MemoryEntry / extract_domain / is_success / init_memory_db / record_task / recall_by_domain / main`)
- `cli.py run_task` 末尾增加 hook (env-gated 可关), 现有 demo 行为零变化 (任务结果不受影响)
- 旧 160 测试零修改全过; 新 27 case (parametrize 7+9+1+2+6+2), 总 187 tests 全绿
- 新增 CLI script `web-agent-memory` 不影响 `web-agent` / `web-agent-replay`

## [0.12.8] - 2026-05-03

### Tests (audit gap fill: loop.py 主体 abort 路径 3 case)
- **新建** `tests/test_loop_main.py`: 直测 V0.5.0 / V0.5.2 引入的 3 条 abort 出口
  - `test_max_steps_exhausted_returns_signal_string`: LLM 永不 done + max_steps=2 (varied scroll dy 避 V0.5.0 anti-loop) → "(max_steps 耗尽未完成)" + trace 落 2 scroll step
  - `test_wallclock_exceeded_aborts_without_step_row`: `max_wallclock_s=-1.0` 让 step 0 任何 (>=0) elapsed 立即命中 (免 monkeypatch time 跨模块陷阱) → "WALLCLOCK_EXCEEDED at step 0" + 无 step row + tasks.result 写 "WALLCLOCK_EXCEEDED"
  - `test_llm_exception_captured_writes_error_step`: inline `RaisingLLMClient` 抛 RuntimeError("503 upstream") → "LLM_FAILED at step 0: RuntimeError: 503 upstream" + trace 落 1 step (action_type="error", action_args["error"] 含异常文本)
- 复用 V0.7.0 / V0.9.0 / V0.11.0 inline `FakePage` / `FakeLLMClient` / `patch_loop_internals` fixture / `_read_trace_steps` 模式 (4 处 inline 复制不抽 conftest, 与现状一致)

### Why
- audit findings 列入测试覆盖盲区, V0.12.0 / V0.12.4 / V0.12.6 已补 perceiver / trace / cli 三模块, loop.py 主体是剩余高 ROI 项
- V0.5.0 anti-loop / V0.5.2 wallclock 与 LLM exception capture 当时仅测 signature 纯函数, abort 端到端路径裸奔近 7 个版本号
- safety / captcha / reflect 集成测覆盖 done / safety_block / captcha_timeout / reflect 路径; **此 commit 收尾剩 3 条**: max_steps / wallclock / LLM exception

### Compatibility
- 零代码改动 (loop.py / safety.py / captcha.py / notify.py / replay.py / trace.py 全不动)
- 旧 157 测试零修改全过; 新增 3 case, 总 160 tests 全绿
- 公共 API 零变化, 行为零变化

## [0.12.7] - 2026-05-03

### Docs (.env.example sync)
- **`.env.example` refresh** 同步 V0.12.5 README env 段, 新增 6 var 首次可见:
  - `WEB_AGENT_CAPTCHA_DISABLE` / `CAPTCHA_TIMEOUT_S=300` / `CAPTCHA_POLL_S=3` (W4-2)
  - `WEB_AGENT_SOM_SHADOW` (W5-B)
  - `WEB_AGENT_NOTIFY_DISABLE` (W4-3)
  - `WEB_AGENT_TEST_RECIPIENT` (W3-C demo)
- 现有 `AUTO_APPROVE` / `AUTO_DISMISS` / `MAX_WALLCLOCK_S` 保持原位置不重组, 避免破坏已 `cp .env.example .env` 用户的现有配置布局
- 注释示例严守"无真 secret"约束: `ANTHROPIC_API_KEY=` 空赋值 / Kimi 段保留 `sk-xxx` 占位符
- 默认值与源码 `os.getenv(..., default)` 完全对齐 (`CAPTCHA_TIMEOUT_S=300` 等), 避免 cp 后锁死代码默认
- 布尔类 `*_DISABLE` 默认注释掉而不写 `=false`, 避免 truthy 解析差异
- 用户 `cp .env.example .env` 后**所有 9 个行为开关首次完整可见**
- 顺手 README 第 187 行目录段 `__version__ = "0.12.4"` stale 串去掉具体版本号 (避免每次 bump 都要改 README)

### Compatibility
- 零代码改动 (.env.example + CHANGELOG + version bump + README 一字符 = 4 处)
- 157 tests 零修改全绿 (测试不读 .env.example, 无回归风险)
- 公共 API 零变化, 行为零变化

## [0.12.6] - 2026-05-03

### Tests (audit gap fill: cli.py 9 case)
- **新建** `tests/test_cli.py`: cli.py 入口 (W3-C/W4-1/W4-2/W4-3 多次改过, 仅 demo smoke 间接覆盖) 9 case 收尾 audit gap
  - **基础 signature** 1: `run_task` 是 coroutine function (与 demos_smoke 同档防 sync 改动)
  - **argparse 解析** 5: goal-only / 全 flags / max_steps int 强制失败 SystemExit / missing goal SystemExit / main 打印结果带 `=== 任务结果 ===` 标题
  - **env precedence** 3: cli arg > env > default 三档全测 (max_steps default=20 / max_wallclock_s default=300; arg=7 覆盖 env=99; env=50 当 arg 缺时生效)
- 实现要点:
  - `_RunTaskRecorder` patch `web_agent.cli.run_task` 收 main() 透传的 kwargs (argparse 测路径)
  - `patch_run_task_io_chain` fixture 拦掉 load_dotenv/async_playwright/connect/apply_stealth/make_client/run_react_loop 全套 IO, 只放过 env/参数解析路径
  - `_FakePlaywrightCtx` async ctx mgr stub; AsyncMock 给 page.set_viewport_size/goto

### Why
- audit findings 历次列入 cli/browser/loop 主体测试盲区; 此前 perceiver (V0.12.0) + trace (V0.12.4) 已补完, cli 是剩余高 ROI 项
- W3-C/W4-2/W4-3 引入的 max_wallclock_s / cdp_url / provider / model 全靠 env 路径, 之前只有 demo smoke 间接验证, 改 env precedence 静默破坏风险高
- 主体 run_react_loop 通过 V0.7.0 / V0.9.0 / V0.11.0 / V0.5.0 多个 integration test 间接覆盖, 不重复测

### Compatibility
- 零代码改动 (cli.py / loop.py / browser.py 全不动)
- 旧 148 测试零修改全过; 新 9 case, 总 157 tests 全绿
- 公共 API 零变化, 行为零变化

## [0.12.5] - 2026-05-03

### Docs
- **README.md 全面 refresh** (V0.2.0 → V0.12.4 catch-up, 落后 10 个版本一次性补齐):
  - **当前状态**: V0.2.0 骨架 1 行 → V0.12.4 + W milestone 完整进度 (W1/2/3/4 ✅, W4-1.1 ✅, W5-A/B ✅, W5-C/D 未启动)
  - **栈**: 加 Shadow DOM 穿透 / 弹窗自动关 / 安全反思双层防御 一句话描述
  - **路线图重写**: W1-W4 全 ✅ / W5 部分 ✅ + 已知缺口 (patchright 决断 / 住宅代理 / Gmail 真跑)
  - **新加「行为开关 (env 变量)」段** 5 类分组: Safety / Captcha / Perception / Notify / Reliability + Demo 专用 — 7 个新 env 变量首次进 README
  - **CLI 段加 `web-agent-replay`** 文档 (含 `--all` 索引页模式)
  - **目录段更新**: src/web_agent/ 加 safety.py / captcha.py / notify.py / replay.py / llm/ 子包; demos/ 加 github_search / gmail_summary / gmail_compose; tests/ 标 13 文件 148 case; data/ 加 replays/
- **不动**: 反检测段 / 法律边界 / 安装段 / Chrome 启动表 / BYO LLM 段 (这些没过期)

### Compatibility
- 零代码改动 (本 commit 仅 README + CHANGELOG + version bump)
- 148 tests 零变化全绿
- 公共 API 零变化, 行为零变化

## [0.12.4] - 2026-05-03

### Tests (audit gap fill: trace.py 13 case)
- **新建** `tests/test_trace.py`: 持久化层 (V0.5.0 来 0 单测) 13 case 覆盖
  - `init_db` 3: tasks/steps schemas 创建 (PRAGMA table_info 验 PK) / parent dir mkdir / idempotent 第二次调不抛
  - `start_task` 1: 中文 goal 不转义 + started_at 是 float ±10s + ended_at/result NULL
  - `end_task` 2: update ended_at + result / 不存在 task_id 不抛 (UPDATE 0 行, 防御 case 留位回归保护 loop.py 容错)
  - `write_step` 3: row 全字段 + action_args JSON + 中文 ensure_ascii=False raw 落字符 (replay/grep 友好) + INSERT OR REPLACE 同 PK 覆盖语义
  - `Step.for_llm` 2: observation 200 字硬编码截断回归保护 / 短 obs 不被截断 + 含 step/thought/action 字段
  - `Trace.append` + `for_llm` 2: maxlen=20 deque popleft FIFO (写 25 留 step 5..24) / for_llm 返 list[dict] 走 Step.for_llm
- 全用 stdlib (sqlite3 + tmp_path + json), 直连 sqlite 验副作用, 与 V0.12.0 W5-B perceiver 12 case + V0.12.2 W4-1.1 replay +5 case 同档 audit gap 填补风格

### Why
- V0.5.0 之前 trace.py 已稳定但一直 0 单测, audit findings 多次列入测试覆盖盲区
- 持久化层是 loop / replay / 所有 demo 共依赖, 改动这层无单测裸奔风险高
- 蓝本认知层 (ReAct / 短期记忆 / 自反思 V0.11.0 / step limit V0.5.0 / 回退暗含 W5-A reflect 4 策略) 已基本覆盖, runtime 类技术债 (patchright / 住宅代理) 不可离线测; trace 单测是当前最高 ROI 代码可交付项

### Compatibility
- 零代码改动 (trace.py / loop.py / replay.py / cli.py / browser.py 全不动)
- 旧 135 测试零修改全过; 新增 13 case, 总 148 tests 全绿
- 公共 API 零变化, 行为零变化

## [0.12.3] - 2026-05-03

### Refactor (/simplify W4-1.1 索引页)
- **`replay.py render_index_html` 折掉 td_result 三元分支**: 空 `class=""` 浏览器不在意; 删 4 行条件包装, `result_short = html.escape(...)` 提到循环顶部省一次重复 escape 调用
- **`tests/test_replay.py` 抽 `_create_empty_schema(db_path)` 测试 helper**: V0.8.0 `test_load_task_empty_tasks_exits` + W4-1.1 `test_load_all_tasks_meta_empty_db_exits` 各内联 7 行 raw `CREATE TABLE` SQL, dedup 后两者各只调一行 helper
- 删 W4-1.1 测试里的 `import sqlite3 as _sqlite3` 局部别名 (模块顶部已 `import sqlite3`)
- subagent (/simplify) 跳过项 (N=2):
  - `_result_class` substring 循环 (与 `_STEP_CLASS` 精确匹配语义不同, 不可合并)
  - `--all` 路径 N+1 query 模式 (1 + 2N = 21 query @ 10 task; CLI 一次性, sqlite 本地 sub-ms; 优化复杂度不值)
  - `_connect` `db_path.exists()` TOCTOU (CLI 无并发, 错误信息更友好)
- 135/135 tests 全绿, 公共 API + W4-1.1 行为零变化

## [0.12.2] - 2026-05-03

### Added (W4-1.1: replay 索引页)
- **`replay.py` 新增 `load_all_tasks_meta(db_path)`**: 仅取 tasks + 子查询 step_count, 不加载 steps 详情省 RAM; 按 started_at DESC 返回
- **`replay.py` 新增 `render_index_html(metas)`**: 表格列出所有 task (task_id 链接 → 详情页 / started / ended / steps 数 / result 80 字截断), 4 类 result 文本颜色高亮 (SAFETY_BLOCK 红 / CAPTCHA_TIMEOUT 橙 / LOOP_DETECTED 橙 / WALLCLOCK_EXCEEDED+LLM_FAILED 黄)
- **CLI** `web-agent-replay --all`: 渲染 DB 全部 task 各自 HTML + 写 `data/replays/index.html` 索引页
  - argparse `mutually_exclusive_group` 让 task_id 与 --all 冲突时干净报错
- **测试** `tests/test_replay.py` +5 case (V0.8.0 已有 11 → 16):
  - load_all_tasks_meta 排序 + step_count
  - load_all_tasks_meta 空 db 退出
  - render_index_html 链接 + result colorclass + DESC 顺序
  - main --all 写所有 task .html + index.html
  - main task_id 与 --all 互斥报错

### Why
- V0.8.0 W4-1 CHANGELOG Limitations 自承「无搜索 / 过滤 / 多 task 并列对比 — MVP 单 task 视图; 真要多 task 列表后续 W4-1.1 加索引页」, 留位填坑
- subagent (Plan) 评估架构 5 决策点全采纳:
  - mutually_exclusive_group 互斥 task_id 和 --all (干净报错免手写 if)
  - step_count 子查询 (避 N task 全 steps 加载到内存)
  - result 文本颜色 td 着色不染整行 (索引表视觉不炸)
  - 复用 V0.8.0 step--xxx hex (#d32f2f / #ef6c00 / #f9a825) 跨视图视觉一致
  - 空 tasks 表 sys.exit 与 load_task 单出口语义对齐

### Compatibility
- 公共 API 加 (`load_all_tasks_meta` / `render_index_html`), 旧 `load_task / render_html / main` 不带 --all 行为零变化
- 旧 130 测试零修改全过; 新 5 case, 总 135 tests 全绿
- 零新依赖 (仍是 stdlib sqlite3 + html + json + argparse + datetime)

## [0.12.1] - 2026-05-03

### Refactor (/simplify W5-B perceiver)
- **`_SOM_INJECT_JS` 删死代码 `const all = collected; const els = all.filter(...)` 中间别名 `all`** —— 直接 `collected.filter(...)`, 1 行净减
- subagent (/simplify) 审计本次只此一处确定性 ROI > 0; 其他保留:
  - `(opts)` 参数 + `!opts || opts.shadow !== false` 防御默认 — 公共 JS 字符串可能被外部 reuse, N=2 跳过
  - `!visited.has(e.shadowRoot)` push-时检查 — 避免 stack 膨胀微小性能, N=2 跳过
  - perceive() 内 lazy 读 `WEB_AGENT_SOM_SHADOW` env — monkeypatch 友好, N=2 跳过
- 130/130 tests 全绿, 无行为改动

## [0.12.0] - 2026-05-03

### Added (W5-B: Shadow DOM 穿透 + perceiver 单测填补)
- **`perceiver.py` `_SOM_INJECT_JS` 加 stack-based shadow walker**:
  - 原 `Array.from(document.querySelectorAll(sel))` → stack 遍历 [document, shadowRoot1, shadowRoot2, ...]
  - 收集顺序: light DOM first (id 1..K) → 各 open shadowRoot (id K+1..)
  - `WeakSet visited` 防自引用死循环 (规范禁止 host===self 但防御)
  - **只穿 open shadowRoot** (closed mode JS 不可达, W3C 设计, 文档化为 known limitation)
  - bbox `getBoundingClientRect()` 跨 shadow 仍是视口相对 → 红框注入仍 `document.body.appendChild` (zIndex 2147483646 几乎最大)
- **`_SOM_INJECT_JS` 改签名为 `(opts)`** + perceive() 入口 lazy 读 env:
  - `WEB_AGENT_SOM_SHADOW=false` (或 0/no/off) 退化到 V0.11.x light-DOM only 行为
  - 默认 ON, 与 V0.5.1 `WEB_AGENT_AUTO_DISMISS` 风格对称
- **新测** `tests/test_perceiver.py` 12 case (audit gap 填补, V0.6.0 之前 perceiver 0 单测):
  - `marks_to_text` 7 case: 空 / 无 role 无 text / 含 role / 含 text / role+text / 多 marks join / 中文
  - `Mark` dataclass 2 case: 默认 input_type/name/href 空字符串 / 全字段
  - `_SOM_INJECT_JS` smoke 3 case: shadowRoot+open+visited 三关键词共现 / opts 参数签名 / 现有 visibility 过滤保留

### Why
- 蓝本 `docs/高度模仿人操作网页的agent技术路径图.txt` 明确点了「Shadow DOM 穿透」, 至今未落地
- 现代 SaaS 大量用 Shadow DOM: Stripe checkout / 部分 GitHub UI / Salesforce Lightning / 各种 Web Components — 不穿透则 SoM 漏标这些组件 → LLM 看到截图但 mark 列表里没 id → 死循环 (V0.5.0 anti-loop / W5-A reflect 兜底但浪费 step)
- subagent (Plan) 评估 6 决策点全采纳:
  - 红框 mounting: 都 `document.body.appendChild` 浮层 (zIndex 已最大几乎不被遮)
  - closed shadowRoot: 不穿 (规范不可达 + 用户体验等价 V0.11.1)
  - id 顺序: light first → shadow last (兼容 demo 视觉习惯)
  - 版本 V0.12.0 minor (蓝本 Shadow DOM 与 W5-A 反思并列独立能力)
  - env 名 `WEB_AGENT_SOM_SHADOW` (与 `WEB_AGENT_AUTO_DISMISS` 前缀对齐, true/false 双向)
  - JS setter 时机: per-call `page.evaluate(_SOM_INJECT_JS, {shadow: bool})` (而非 `add_init_script` next-nav 才生效)

### Limitations
- **iframe ≠ shadow DOM**: 跨域 iframe 走 `page.frames()` 路径不在本任务覆盖
- **closed shadowRoot 漏标**: W3C 设计, 规范上无解; 罕见生产场景 (大多数组件用 open mode)
- **性能**: 大型 SaaS (几百 shadowRoot) 每步 perceive 多 50-200ms; 可接受 (perceive 本身 ~1s 量级); env opt-out 是 escape hatch
- **z-index 罕见冲突**: shadow 内 dialog 用 max int 时红框被遮; 可接受 (LLM 仍能看截图轮廓)
- **JS smoke test 弱**: substring 检测易受 refactor 影响; 选 `shadowRoot + open + visited` 三关键词共现降误报概率
- **真行为单测缺**: shadow DOM 跨度需真 browser + fixture 验证, 沿 V0.5.0 anti-loop / V0.7.0 safety-loop 同档 — 用集成跑 demo 验真; CI 单测保 JS 字符串完整性

### Compatibility
- 公共 API 零变化 (Mark schema / perceive 签名 / marks_to_text 全保留)
- 行为变化: shadow 内组件首次进 marks 列表 → mark id 总数可能增加 → LLM 看到的元素列表更长 (这正是 W5-B 目标)
- 现有 demo (Wikipedia / GitHub / Gmail) light DOM 主导, 影响最小; 真触发 shadow 路径的站需用户实测
- 旧 118 测试零修改全过; 新增 12 case, 总 130 tests 全绿

## [0.11.1] - 2026-05-03

### Refactor (/simplify W5-A reflect)
- **抽 `_maybe_inject_reflect_hint(trace, recent_pages, fp)` helper + `_REFLECT_HINT` 模块常量**: 把 V0.11.0 内联在主循环 perceive 之后的 ~19 行 reflect 逻辑 (4 行布尔 and + hint 字符串字面量 + obs mutate) 抽成独立 helper, 主循环 body 从 19 行降到 4 行 (`fp = _page_fingerprint(...)` / `recent_pages.append(fp)` / `_maybe_inject_reflect_hint(...)` + 1 行注释)
  - helper 纯 in-place mutate, 调用方负责先 push fp; 行为 100% 等价 (同样的判断条件 / 同样的幂等检查 / 同样的字符串拼接)
  - 提高可读性 (主循环看 1 行就懂在做啥) + 可测性 (helper 可独立测, 不必经 run_react_loop 集成路径)
- 跳过的检查项:
  - `getattr(page, "url", "") or ""` 不简化为 `page.url`: 现有 test fakes (FakePage in test_captcha/test_safety_loop_integration) 没定义 url 属性, 真删 getattr 6 个测试挂掉; 防御写法保留
  - `_page_fingerprint` 与 `_action_signature` 不合并: 功能正交 (一个 hash action, 一个 hash page), 风格平行已满足
  - 测试 fixture 重复 (db/shots/client setup × 3 case): N=2 影响小, 跳过
  - `len == 3` vs `>= maxlen=3`: 保持与 `_action_signature` 路径对称 (loop.py L206 也是 == 3), 跳过
- 不破坏 V0.11.0 reflection 行为: 3 步无变化触发 / 幂等不重复 / not-stuck 不注入 全保留
- 118/118 tests 全绿, 行为零变化

## [0.11.0] - 2026-05-03

### Added (W5-A: 自反思 — page-stuck soft hint)
- **`loop.py` 加 `_page_fingerprint(url, marks) -> str`** 纯函数: hash url + len(marks) + 前 8 marks `(id, tag, text[:40])` JSON 序列化
  - 与 V0.5.0 `_action_signature` 同档 helper, 风格一致
  - 取前 8 + text 截 40 字: 抗尾部动态 timestamp/计数 mark 抖动
  - 留 url 区分 SPA 路由切换 (纯前端跳转, marks 可能巧合相同)
- **`recent_pages: deque[str]` maxlen=3** 主循环跟踪 fingerprint
- **反思触发**: perceive 之后 plan 之前, 若 deque 满 + 全相同 + trace 非空 + 上一步 obs 还未注过
  → 把 `[reflect] 页面 3 步无变化 (url+marks 同). 建议: ① scroll ② 后退/换 selector ③ SoM 漏标 ④ 换思路.` 追加到 `trace.steps[-1].observation`
  - **mutate in-memory Trace**, 不写 sqlite (避脏数据 + 反思是 augment 不是 event)
  - LLM 下一次 `plan()` 通过 `Trace.for_llm()` 自然看到提示
  - 幂等检查 `"[reflect]" not in obs` 防同一 step 被 hint 双重 append (理论上 perceive 每步只跑一次, 安全网)
- **测试** `tests/test_loop_reflect.py` 7 case:
  - `_page_fingerprint` 纯函数: same / 不同 url / 不同 mark text / 不同 mark count
  - 集成 stuck: `RecordingLLMClient` 记录每次 plan 看到的 trace 快照, 验证第 4 次 plan 看到的 trace 含 `[reflect]`
  - 集成 not-stuck: marks 每步变化 → 永不注入
  - 集成幂等: 5 步全 stuck, 任一 obs 最多一个 `[reflect]` 标记

### Why
- 蓝本 `docs/高度模仿人操作网页的agent技术路径图.txt` 明确点了「自反思」, 至今未落地
- V0.5.0 anti-loop 仅检测「同一 action 3 次」硬中止, **环境维度反馈缺失**: LLM 反复换 action 但每个都是 click 不存在的 mark / scroll 已到底, 页面永不变 — anti-loop 不触发, max_steps 耗尽才返回, token 浪费 + 用户体验差
- 反思机制提供**软信号**: 不强制 abort, 让 LLM 自己换策略 (蓝本 ReAct + 自反思的核心理念)
- 与 anti-loop 双层防御互补: 软提示 (3 步无变化) + 硬 abort (3 次同 action) 信号正交不冗余
- subagent (Plan) 评估 4 决策点全采纳:
  - fingerprint 仅 marks/url 不含 body (ROI 低; marks 不变 99% body 不变)
  - mutate `trace.steps[-1].observation` > 新建 reflection step type (replay/trace 简洁)
  - 不重构 anti-loop (两 deque 语义正交; recent_actions = LLM 自选, recent_pages = 环境反馈)
  - V0.11.0 minor (W5 起步独立大项, 与 W3-A V0.6.0 / W4-1 V0.8.0 / W4-2 V0.9.0 / W4-3 V0.10.0 一致)

### Limitations
- **Mark text 含 timestamp 抖动** (e.g. "Updated 2s ago" / 计数器): fingerprint 永不重合 → false negative (该提示不提示); 可接受 (静默错过 < 误报); 真成痛点再加文本数字 mask
- **持续注入**: LLM 看到 hint 没换策略 → fingerprint 仍同 → 持续注入 hint (4 步 5 步...) — **by design**, 持续催 LLM 直到 V0.5.0 anti-loop 在第 3 次同 action 时硬 abort 兜底
- **fingerprint 不写 sqlite**: trace.db 与 in-memory 行为不一致 (sqlite 看不到 [reflect]); replay UI 看不到反思事件; 真有需求未来加 reflection step type
- **hint 字符串 hardcoded 中文**: 多 LLM (英文/Kimi 中文) 都能理解, 但纯英文 LLM 看到中文 prompt 偶有分心; 非紧迫

### Compatibility
- 公共 API 零变化 (`run_react_loop / run_task / make_client / _action_signature` 全保留)
- 行为变化: stuck 场景 trace.steps[-1].observation 多出 `[reflect]` 段 → LLM 输出可能改变 (这正是 W5-A 目标)
- 现有 demo (Wikipedia / GitHub / Gmail RO/Compose) 都是路径前进型任务, 一般不触发 stuck → 行为零感知; 仅在异常路径 (selector 漏标 / 页面卡住) 才介入
- 旧 111 测试零修改全过; 新增 7 case, 总 118 tests 全绿

## [0.10.1] - 2026-05-03

### Refactor (/simplify W4-3 notify)
- **修 `notify.py` macOS AppleScript escape bug**: 原 `f"... {message!r} ..."` 用 Python `repr()`,
  对含单引号的字符串会改外层引号为双引号 + 内层 escape, 但 AppleScript 字符串字面量必须用双引号 + `\\"` / `\\\\` escape;
  Python repr 对 `say "hi"` 会输出 `'say "hi"'` (外层单引号), AppleScript 解析失败 → notification silent miss
  抽 `_applescript_str()` 显式 escape `\\` 和 `"`, 保证任意 title/message 都生成合法 AppleScript
- **抽 `_RUN_KW` dict**: macOS / Linux 分支两份完全相同的 `timeout=3, check=False, stdout/stderr=DEVNULL`
  抽出 dict 共用, -3 行 + 减少未来漂移风险 (改超时/重定向只改一处)
- **测试** `tests/test_notify.py` +1 case (`test_macos_applescript_escapes_quotes_and_backslash`):
  传含 `"` + `\\` 的 title/message, 断言生成的 AppleScript 用 `\\"` escape 且不含 Python repr 单引号
- 总 111 tests 全绿 (原 110 + 1 escape 回归测)

### Why (/simplify subagent 审 V0.10.0 5 项判定)
- 采纳 2/5: AppleScript escape (正确性 bug) + `_RUN_KW` dict (DRY)
- 跳过 3/5:
  - `_disabled()` / `_captcha_enabled()` truthy 解析重复 → N=2 不抽 util (跨模块, 抽出新一层抽象不值)
  - `_, kwargs = spy.calls[0]` unused 变量 → cosmetic 0 行受益
  - `_handle_captcha` 已是 V0.9.1 抽出, W4-3 仅在两处插 notify call → 无可优化

### Compatibility
- 行为变化: 仅 macOS 含特殊字符 (`"` / `\\` / `'`) 的 title/message 通知现在能正确显示 (V0.10.0 silent miss)
- Linux / Windows / 简单 ASCII 路径完全不变
- env / API 签名零变化

## [0.10.0] - 2026-05-03

### Added (W4-3: desktop notification)
- **新模块** `src/web_agent/notify.py`: `notify(title, message)` fire-and-forget 桌面通知
  - lazy 平台探测 + 模块级缓存 (`_BACKEND_CACHE`): 避 import 阶段 hit filesystem; 进程内只探一次
  - macOS → `osascript -e 'display notification ... with title ...'`
  - Linux → `notify-send <title> <message>`
  - Windows / 不可达平台 → no-op (与 DISABLE 同效)
  - subprocess `timeout=3 + check=False + DEVNULL`; `(OSError, SubprocessError)` silent swallow + `log.debug` 保留诊断
  - `_reset_cache_for_tests()` test-only hook 让单测 monkeypatch sys.platform 后能重新探测
- **`loop.py` 接入**: `_handle_captcha` 命中分支 + 超时分支各调一次 (不进 wait_for_resolution poll 循环, 避 spam)
  - 命中: `notify("web-agent captcha", "<vendor> 命中, 请在浏览器手解 (<url>)")`
  - 超时: `notify("web-agent captcha 超时", "<vendor> <timeout_s>s 未解, loop 已中止")`
- **env**:
  - `WEB_AGENT_NOTIFY_DISABLE` (true/1/yes 完全关; CI/headless/不想被打扰场景)
- **测试** `tests/test_notify.py` 6 case: DISABLE env / darwin osascript argv / linux notify-send argv + kwargs / win32 noop / which 返 None noop / OSError swallow
- **集成测** `tests/test_captcha.py` +1 case: captcha 命中调 notify 一次, title/message 含正确字段, **不进 poll 循环 spam**

### Why
- V0.9.0 W4-2 命中只 `print(..., flush=True)`, tmux/SSH/后台日志重定向场景用户离开终端就错过 — CHANGELOG Limitations 已写入留位
- subagent (Plan) 评估架构 4 维:
  - sync `subprocess.run + timeout=3` > `asyncio.create_subprocess_exec`: osascript/notify-send 几十 ms 完成, async 包装多余复杂度
  - lazy + 模块缓存 > eager import 时探测: 避 import 阶段 hit filesystem (与 captcha 模块 fingerprint JS 缓存一致风格)
  - `(OSError, SubprocessError)` > 裸 `Exception`: 不吞 KeyboardInterrupt / SystemExit, 保留诊断信号
  - 仅命中 + 超时 2 处 > 进 poll 循环每次都通知: 避 100 次轮询 100 次桌面通知 spam

### Limitations
- **macOS osascript 安全提示**: 首次调用可能弹「允许 Terminal 发送通知?」系统对话, 用户没点同意会 silent fail; `WEB_AGENT_NOTIFY_DISABLE=true` 兜底
- **WSL2 / SSH 无 X11**: `notify-send` 存在但缺 dbus → subprocess 退 != 0; `check=False` + swallow OK, 无负面影响
- **CI headless**: 推荐设 `WEB_AGENT_NOTIFY_DISABLE=true` 加速 (避 subprocess 启动开销 + 避日志噪声)

### Compatibility
- 公共签名零变化 (`run_react_loop / run_task / make_client / safety / captcha` 全保留)
- 行为变化: 默认 ON; 仅在 captcha 命中/超时触发, 现有 demo (Wikipedia / GitHub / Gmail RO) 不会触发
- 旧 103 测试零修改全过; 新增 7 case (6 notify + 1 captcha 集成), 总 110 tests 全绿

## [0.9.1] - 2026-05-03

### Refactor (V0.9.0 W4-2 simplify)
- `loop.py`: 抽 `_handle_captcha(page, step_i, trace, conn, task_id) -> str | None` + `_captcha_enabled()` helper
  - 主循环里 35 行三层嵌套 (`if env != disabled` → `if info` → `if not ok`) → 3 行 (`captcha_abort = await _handle_captcha(...); if captcha_abort: return`)
  - 双否定 env check `not in ("true", "1", "yes")` 抽到 `_captcha_enabled()` 正向返回
  - 行为零变化: env 取值时机 (每步重读) / vendor/url 80 字截断 / trace step 字段全保留, 103/103 tests 全绿
- 触发: 用户 CLAUDE.md `/simplify` 自动化判据 ① 新增公共方法 + ③ >30 行 + ④ 引入新抽象 三命中

## [0.9.0] - 2026-05-03

### Added (W4-2: 验证码接管 UX)
- **新模块** `src/web_agent/captcha.py`: `CaptchaInfo` dataclass + `detect(page)` 纯检测 + `wait_for_resolution(page, timeout_s, poll_s)` 异步轮询
  - 4 vendor: cloudflare-turnstile / recaptcha (v2 visible) / hcaptcha / google-verify (body 文本兜底)
  - visibility 过滤排除 0×0 隐形 reCAPTCHA v3 (常驻 SaaS 站, 永远存在则无意义)
  - detect except Exception → None: page navigating / fake page 缺 evaluate 不该崩 loop
- **`loop.py` 接入**: 在 `await think()` 后、`perceive()` 前插 captcha 检测分支
  - 命中 → 终端打印 vendor + url + 倒计时 → 异步轮询 wait_for_resolution
  - 用户在浏览器手解 → detect 清除 → loop 自然继续
  - 超时 → graceful abort + 写 trace `Step(action_type="captcha_timeout", action_args={vendor, url, timeout_s})` (镜像 V0.6.0 safety_block 路径)
- **env**:
  - `WEB_AGENT_CAPTCHA_DISABLE` (true/1/yes 跳过检测, 退化到 V0.8.0 行为)
  - `WEB_AGENT_CAPTCHA_TIMEOUT_S` 默认 300.0
  - `WEB_AGENT_CAPTCHA_POLL_S` 默认 3.0
- **测试** `tests/test_captcha.py` 12 case:
  - detect: 4 vendor (parametrized) / no captcha / page.evaluate 抛异常 / page 缺 evaluate
  - wait_for_resolution: 清除返回 True / 超时返回 False
  - loop 集成: pause-resume / 超时 abort 写 trace / DISABLE env 跳过 detect

### Why
- 蓝本 + README line 125 明示「不接 2Captcha 自动绕(越线), 用「暂停 → 弹窗让用户解 → 恢复循环」UX」— W4-2 之前一直只在文档承诺, 零落地
- subagent (Plan) 评估架构 3 维:
  - 检测在 perceive **前** > 后: 避 SoM JS 注入污染 captcha 页 + 省 perceive 开销 (perceive 是重操作, 解 captcha 期间无意义重跑)
  - `asyncio.sleep` 轮询 > `page.wait_for_function`: 轮询 detect() 路径与单测一致, JS 端轮询逻辑要复杂 4 倍 (4 vendor selectors)
  - inline FakePage/FakeLLMClient > conftest.py 抽: V0.7.0 决策一致 (N=2 仍按 YAGNI 不抽 helper, 抽 conftest 等于"修改" V0.7.0 测试违反零修改约束)
- captcha_timeout step 与 safety_block 平行 镜像: 调试一致性 + replay UI 已支持 special action 颜色高亮 (W4-1 已加 step--error / step--safety / step--done / step--loop, W4-2 trace 自动适配)

### Limitations
- **headless / SSH 无桌面**: 用户无法在浏览器手解 captcha; 设 `WEB_AGENT_CAPTCHA_DISABLE=true` 退化到 V0.8.0 行为或接受 captcha_timeout 抛错
- **后台跑 demo**: 终端 print 用 flush=True 但仍可能被日志重定向掩盖; 未来 W4-3 可加 desktop notification (osascript / notify-send)
- **Cloudflare invisible Turnstile**: 一些配置不需用户点, 几秒自动通过; 体验路径走 wait → 自动清除 → 继续, 正常工作 (但 timeout 倒计时显示可能让用户疑惑)
- **多 captcha 同存** (罕见): 优先级返回首个, 解决后下一步若另一个再触发 → 自然串行处理, 无需特殊路径

### Compatibility
- 公共 API 零变化: `run_react_loop / run_task / make_client` 签名全保留
- V0.7.0 `test_safety_loop_integration.py` FakePage 缺 evaluate, detect 异常吞掉 → None → 旧 91 测试零修改全过 (这正是 detect 设计 except Exception 的目的)
- 行为变化: 默认 ON; 首次跑现有 demo (Wikipedia / GitHub / Gmail) 不会触发 (这些站无 captcha); 未来撞 Cloudflare 站点会自动暂停。出问题 `WEB_AGENT_CAPTCHA_DISABLE=true` 全关
- 总测试: 旧 91 + 新 12 = 103 全绿

## [0.8.0] - 2026-05-03

### Added (W4-1: replay 日志面板)
- **新模块** `src/web_agent/replay.py`：从 `data/trace.db` 加载单次 task + 全部 steps,
  渲染单文件 HTML 时间线写到 `data/replays/<task_id>.html`
  - 顶部 task 元数据 (goal / started / ended / steps 数 / result)
  - 每 step 一张卡片 (序号 + action_type + ts + thought + action_args 美化 JSON +
    `<details><summary>screenshot</summary><img>` + observation)
  - special action_type 颜色高亮: `safety_block` 红 / `error` 黄 / `done` 绿 / `loop_detected` 橙
  - 截图走相对路径 `../screenshots/<task_id>-<NN>.png`,直接 file:// 打开就工作
  - 零新依赖 — 纯 stdlib (sqlite3 + html + json + argparse + datetime)
- **CLI script** `web-agent-replay [<task_id>]`：注册到 `pyproject.toml [project.scripts]`
  - 省略 task_id = 最新一次 (`ORDER BY started_at DESC LIMIT 1`)
  - `--db` / `--out` 自定义路径
- **测试** `tests/test_replay.py` 11 case：
  - load_task: explicit / latest / missing id / db missing / empty tasks
  - render_html: goal escape / safety_block class+rule / 截图相对路径 / `<script>` XSS escape
  - main: 写文件 + 退出码 0 / 无参数走 latest

### Why
- 蓝本「操作前观察 / 操作后确认」闭环里 verify 段一直只写库不可视化 — debug demo 失败靠 `sqlite3 .schema` + 翻 png 文件名拼凑, 极度低效
- subagent (Plan) 评估架构 3 选 1: 静态 HTML 生成 > FastAPI server > 模板引擎
  - 静态零依赖 + 单文件可分享 + file:// 直接看, 单用户 dev 工具最佳 fit
  - 不引 jinja2 (拼接量 ~50 行 f-string, jinja2 是 overkill)
- W4-1 完成后,以后跑 demo 失败可一句 `web-agent-replay` 看时间线 + 截图,排查效率上一档

### Limitations
- 静态生成: trace.db 写入时不更新; 长任务跑到一半看进度需重跑 replay 命令
- HTML 引用截图相对路径,移动 `data/replays/` 目录会断链 (规约 = 始终从项目根 file:// 打开)
- 无搜索 / 过滤 / 多 task 并列对比 — MVP 单 task 视图;真要多 task 列表后续 W4-1.1 加索引页
- thought/observation 长文本不折叠 (>1000 字会让卡片很长);如成痛点再加 max-height + 展开按钮

### Compatibility
- 公共签名零变化 (trace.py / loop.py / cli.py 不动)
- 新 CLI script 不影响现有 `web-agent` entry
- 旧 80 个测试零修改全过; 新增 11 case, 总 91 tests 全绿

## [0.7.0] - 2026-05-03

### Added (W3-C: 写操作 demo + safety×loop×trace 集成验证)
- **`demos/gmail_compose.py`** — 让 LLM 走 Compose → 填 To/Subject/Body → 试点 Send 路径
  - 默认行为: safety.py 拦 "Send" → run_task 返回 `SAFETY_BLOCK at step ... rule=send-or-pay` (验证拦截路径)
  - `WEB_AGENT_AUTO_APPROVE=send-or-pay` 显式授权后真发邮件 (验证放行路径)
  - `WEB_AGENT_TEST_RECIPIENT` env 必填 (空则 fail-fast 退出 2; 强烈建议自己发给自己)
  - 复用 V0.6.2 `_check_logged_in` 模式 (inline 复制, N=2 仍按 YAGNI 不抽 helper)
  - max_steps=12 (Compose 路径估 6-8 步 + buffer)
  - 不动 stack: 完全靠现有 V0.6.1 (safety + actuator + loop + perceiver) 跑通
- **`tests/test_safety_loop_integration.py`** — 端到端集成测试
  - FakePage + FakeLLMClient + monkeypatch (perceive/think/click/type/scroll → no-op),
    跑真 `run_react_loop` 验证三件套联动
  - 场景 1: 默认无 AUTO_APPROVE, click "Send" mark → SAFETY_BLOCK 字符串 + sqlite 落 `action_type=safety_block, rule=send-or-pay`
  - 场景 2: `AUTO_APPROVE=send-or-pay`, click 放行 → 第二步 done → return "sent"
  - 场景 3: `AUTO_APPROVE=*` 通配符也放行
  - 比 V0.6.0 `test_safety.py` 高一档: 覆盖 safety + loop + trace 真实联动 (test_safety.py 仅纯函数)
- **`tests/test_demos_smoke.py`** — parametrize 加 `gmail_compose.py`

### Why
- W3-A safety + W3-B read-only demo 缺一条「真触发 abort + auto_approve 放行」端到端验证链
- 集成测试比纯函数测高一档 (anti-loop V0.5.0 也只测 signature 纯函数, 联动行为长期裸奔)
- subagent (Plan) 评估架构: monkeypatch loop.* 引用 + 最小 FakePage > 真起 Playwright (慢 + 不稳)
- 不真跑 Gmail (CI 不发邮件; 用户登录态各异; demo 文件交付即可, 运行验证是用户的事)

### Limitations
- 集成测试用 FakePage, 对 Playwright 真行为零保证 (与 V0.5.0 anti-loop 同档, ROI/复杂度权衡可接受)
- gmail_compose.py 依赖用户先按 V0.6.2 完成 Gmail 登录态持久化; 本 demo 不引导首次登录
- safety 仅在 actuator 层拦, 不防 LLM 通过 type Enter (`submit=True`) 间接触发表单提交; 该路径目前未有真实 demo 触发, 待发现实例再加 form action 检测

### Compatibility
- 公共签名零变化 (safety / loop / actuator / perceiver / cli 不动)
- 旧 76 个测试零修改全过; 新增 4 case (3 integration + 1 smoke), 总 80 tests 全绿
- W1/W2/W3-A/W3-B 现有 demo 不受影响

## [0.6.2] - 2026-05-01

### Added (W3-B Gmail demo + smoke test)
- **`demos/gmail_summary.py`** — read-only 任务: 读取 Gmail 收件箱 Primary tab 最新 5 封邮件的发件人 + 主题
  - 前置检测 `_check_logged_in()`：goto Gmail 看 URL 是否跳到 accounts.google.com / signin / mail.google.com/about / "browser may not be secure" → fail-fast 打印登录指引并 exit 2，不浪费 LLM token
  - goal 钉死「Primary tab 不看 Promotions/Social」+「禁止点击任何邮件行 / archive / delete / mark-read」防 LLM 误操作
  - max_steps=15（W2-B 是 18，read-only Gmail 估 5-7 步路径 + 8 步 buffer 给 Loading retry）
  - 不动 stack：完全靠现有 V0.6.1 (safety + actuator + loop + perceiver) 跑通
- **`tests/test_demos_smoke.py`** — 每个 demo 文件 import + main 是 async coroutine factory 零成本验证
  - 用 `importlib.util.spec_from_file_location` 从 demos/ 路径直接 load（demos/ 不在 src layout）
  - 不跑 main()，挡住 demo 静默腐烂（如未来 `run_task` 签名变了）
  - 覆盖 3 个 demo: wikipedia_search / github_search / gmail_summary

### Why
- W3-A safety 完成需要一个 read-only 真实场景验证不误拦 + 验证登录态持久化路径
- Gmail 是「重 SPA + 用户登录态 + Google 反 bot」三轴最严苛站点，比 Wikipedia/GitHub 上一档
- subagent 评估：read-only 单跑 Gmail 即可暴露所有新轴；写操作（archive/mark-read）单独 W3-C 测 safety auto_approve 流程
- 不抽 `require_login` helper（YAGNI，N=1）
- 不预先改 perceiver 加 Loading retry（failure-driven，先跑看真实失败）

### Limitations
- **Google `--headless=new` 反 bot 检测最狠**，subagent 警告即使 cookies 有效首次进 mail.google.com 仍可能弹 "browser may not be secure"
- demo 已加 fail-fast 检测，不会浪费 LLM token；用户看到提示后按 README 方式登录即可

## [0.6.1] - 2026-05-01

### Refactored (V0.6.0 simplify pass)
- **`safety.py` 黑名单 patterns 模块加载时 compile**：`_DANGER_BUTTON_PATTERNS` 改 `list[tuple[re.Pattern, str]]`（原 `list[tuple[str, str]]`），与 `_DANGER_INPUT_NAME_RE` 风格一致；avoids per-call re-cache lookup（每步 4 次 → 0 次）
- **`check()` 4 段 if-命中-then-block 抽 `_block(rule, reason)` helper**：返回 `SafetyDecision | None`，封装 "auto_approve check + 构造 SafetyDecision + 拼 reason 后缀"。check() 函数体 ~80 行 → ~50 行，行为零变化（73/73 仍绿）
- **`check()` 入口 short-circuit `mark is None`**：把 click/type 两个分支共享的 `mark is not None` guard 上提，减一层缩进
- **去掉 `tests/test_safety.py` 一行 `# subagent 列出` narrating-the-change comment**

### Why
- W3-A 落地后例行 simplify 审查；用户列出 4 个候选优化点，2 个采纳（pre-compile + `_block` helper），2 个否（loop.py 5 个 abort 路径仍 "差异 > 共性"；`_DANGER_BUTTON_PATTERNS` 不改 frozenset 因 list 顺序与可读性更重要）

### Compatibility
- 公共 API 零变化：`check(action, mark, marks)` 签名 + `SafetyDecision` 字段 + 规则名全保留
- 73/73 测试零修改全过

## [0.6.0] - 2026-05-01

### Added (W3-A: 授权白名单层)
- **新模块** `src/web_agent/safety.py`：`SafetyDecision` dataclass + `check(action, mark, marks) -> SafetyDecision` 纯函数
  - 在 actuator 之前 intercept 敏感 action（send/pay/delete/转账/确认订单/订阅取消等）
  - 默认拦：英文按钮文本（send/submit/pay/delete/checkout/wire/transfer/confirm/authorize/...）+ 中文（发送/支付/删除/转账/立即支付/确认订单/...）+ input type=password|tel + input name=amount|cvv|card|otp|code|...
  - `WEB_AGENT_AUTO_APPROVE=rule1,rule2,...` env 预授权（CSV，规则名见 safety.py）
  - `WEB_AGENT_AUTO_APPROVE=*` 全开（dev/可信场景；生产慎用）
  - 触发即 graceful abort（loop 写 trace `Step(action_type="safety_block", action_args={"original_type":..., "rule":...})`），不让 LLM 重撞
- **`Mark` dataclass 加字段**（perceiver schema 升级，向后兼容 default 空字符串）：
  - `input_type: str = ""` — input.type（password/tel/text/email/...）
  - `name: str = ""` — input.name 或 id（用于敏感字段名匹配）
  - `href: str = ""` — a.href（绝对 URL）
  - perceiver SoM JS 一并采集，每 step 零额外 RTT
- **loop.py 接入 safety check**：在 `await client.plan(...)` 后、actuator 路由前；click 用当前 mark / type 用 `last_clicked_mark`（loop 维护 stateful 跟踪）
- **测试** `tests/test_safety.py` 30+ case：英文 14 / 中文 9 / input 类型 4 / type action 3 / auto_approve env 4 / 边界 5（scroll/extract/done always allow / mark=None / 空 text / 大小写 / "sender" word boundary）

### Why
- 用户技术蓝本明确要求：「付款 / Gmail send / DELETE / 密码字段填充 — 强制弹用户确认，不让 LLM 自己决定」
- W3-B 接下来 Gmail demo 没 safety 防护就有真实风险（误发邮件 / 误删）
- subagent 评估架构：safety.py 独立 + loop 一行调用 > inline check（避免污染 loop 重构压力）+ > actuator wrap（5 个 action 各加重复）
- subagent 4 处优化全采纳：Mark 加字段（C），黑名单加金额/2FA/form action（B），CSV 加 `*` 通配（D），CHANGELOG 标行为变化（F）

### ⚠️ Behavior change（demo 用户必读）
- **默认拦 send/pay/delete 类 action** — 之前 demo 没 safety，LLM 可以随意 click "Send"；V0.6.0 起会强制 abort
- 影响：W3-B Gmail send 邮件 demo 必须显式 `WEB_AGENT_AUTO_APPROVE=send-or-pay` 才能跑
- 出问题一行 `WEB_AGENT_AUTO_APPROVE=*` 全开 + `WEB_AGENT_AUTO_APPROVE=` 空字符串 = 全拦回到默认

### Compatibility
- 公共函数签名 100% 不变：`run_react_loop / run_task / make_client` 都不动
- Mark 加字段有 default 空字符串，旧代码（含已写测试）零破坏
- W1/W2-A/W2-B 现有 demo（Wikipedia / GitHub）不操作敏感 action，不受影响

## [0.5.2] - 2026-05-01

### Added
- **LLM SDK retry + timeout 调宽**：AnthropicClient / OpenAIClient `__init__` 显式传 `max_retries=4, timeout=120.0` 给 AsyncAnthropic/AsyncOpenAI（原本依赖 SDK default：anthropic max_retries=2/timeout=NOT_GIVEN，openai max_retries=2/timeout=600s）
  - 4 次指数退避（2/4/8/16s）覆盖大部分网络抖动
  - 120s 单调用上限，避免 OpenAI default 600s 让 agent 一步等 10 分钟
- **loop wallclock guard**：`run_react_loop` 加 `max_wallclock_s: float = 300.0` 参数
  - 每 step 开头 check `time.time() - t_start > max_wallclock_s` → graceful abort + 写 trace
  - 防御 SDK retry + perceive 卡顿累积超过 max_steps × 平均步耗时
  - cli/run_task 加 `max_wallclock_s` 参数 + `--max-wallclock-s` CLI flag + env `WEB_AGENT_MAX_WALLCLOCK_S=300`
- **loop LLM 异常 graceful capture**：`await client.plan(...)` 包 try/except Exception
  - SDK retries 耗尽 / network / tool_call=None / 任何 LLM 侧异常 → 写 trace `Step(action_type="error", ...)` + 友好错误信息 + 优雅返回
  - 之前会 raise 直接逃出 try/finally 外层让用户看 traceback
- 每 step 打印 `t+<elapsed>s` 便于排查耗时分布

### Why
- subagent 评估 5 项 reliability ROI：弹窗自动关 + LLM retry 排前两名（V0.5.1 + V0.5.2 各一）
- LLM API 终极失败时整个 task 挂掉用户体验差；SDK 内置 retry 够用，loop 层只补 catch + wallclock
- subagent 关键调整：不在 loop 写自定义 retry 循环（避免 retry × retry 雪上加霜），SDK max_retries 调宽更干净

### Compatibility
- 公共函数签名加新参数（默认值兼容旧调用站点）：`run_task(max_wallclock_s=None)`、`run_react_loop(max_wallclock_s=300.0)`
- demo/CLI 不需改（默认值生效）
- 行为变化：LLM 失败 / 卡 5 分钟以上 → 返回字符串而非 raise，更易脚本化

## [0.5.1] - 2026-05-01

### Added
- **perceiver 自动关 cookie/GDPR/通知弹窗**（`maybe_auto_dismiss` 在 SoM 注入之前执行）：
  - 容器白名单：必须含 `cookie/consent/gdpr/notif/policy/banner` 关键词（class/id/innerText）
  - 按钮文本严格 anchored regex 匹配「接受/同意/got it/ok/allow」(中英文)
  - 黑名单文本（password/sign in/login/pay/支付/付款/checkout/确认订单/delete）→ skip 整个容器，保护 OAuth/付款/真业务 dialog 不被误关
  - 关弹窗后 wait 300ms 等动画结束再 mark
- env `WEB_AGENT_AUTO_DISMISS=true`（默认 on，设 false/0/no 关闭）
- `.env.example` 加注释

### Why
- W1/W2/W2-B 三个 demo 都浪费 1-2 步在让 LLM 自己识别 cookie banner 关闭，token 浪费
- 弹窗关闭是机械任务，不该让 LLM 来做；perceive 层 JS 一次扫即可
- subagent 评估 5 项 reliability ROI 时此项排第一

### Compatibility
- 默认行为变化：cookie banner 在 perceive 时被自动关；user-facing 表现是「demo 少 1-2 步」+「不会再看到 LLM 跟 cookie banner 较劲」
- 黑名单保护：含 password/sign in/pay 的 dialog 不被关（OAuth/付款流程安全）
- 出问题一行 `WEB_AGENT_AUTO_DISMISS=false` 关掉

## [0.5.0] - 2026-05-01

### Added
- **perceiver SoM 选择器扩展**：原 selector 漏 menu/option/combobox 类 ARIA role，导致 GitHub sort dropdown 等 React 复杂组件展开后 LLM 看到选项但元素清单里没编号 → 死循环
  - 新增 role：`menuitem`, `menuitemradio`, `menuitemcheckbox`, `option`, `combobox`, `switch`, `radio`
  - 与原有 `button/link/textbox/checkbox/tab` + `a/button/input/textarea/select` 合并

- **loop 死循环检测**（loop.py 新 helper `_action_signature` + `recent_actions deque(maxlen=3)`）：
  - 连续 3 次完全相同 action（type + args，忽略 thought）→ 强制 abort + 写 trace + 友好错误信息
  - signature 归一化：`type:json(args, sort_keys=True)`，args key 顺序不影响判定
  - 错误消息包含常见根因提示（SoM 漏标 / 页面未按预期变化 / prompt 没说服 LLM 换策略）

- `tests/test_loop_anti_loop.py` 5 个 signature 单测（identical / mark_id 差异 / type 差异 / arg key order 不变 / 中文不乱码）

### Why
- 实测 W2-B GitHub demo 第二次跑 click mark_id 30 重复 14 次（LLM 想点"Most stars"但 dropdown 选项没被 SoM mark）
- system prompt 写了"连续 2 步无变化换策略"但 LLM 没遵守 → loop 必须有硬性 guard，不能完全信赖 LLM 自律

### Compatibility
- 行为变化：LLM 自我循环（同一 action 3 次）会被 abort，而非耗尽 max_steps —— user-facing 改善（更早返回 + 更精确错误消息）→ minor bump 0.5.0
- 公共函数签名 100% 不变；Action 类不变；CLI/demo 不需改
- 新 SoM role 仅扩展覆盖，不影响原本就被 mark 的元素

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
