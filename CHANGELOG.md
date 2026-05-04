# Changelog

All notable changes to web-agent. 版本号遵循 SemVer 简化形式（V<major>.<minor>.<patch>）。

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
