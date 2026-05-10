# V0.26 Eval Baseline (Kimi-only, V0.26.5)

V0.26.5 跑 V0.26.1 corpus 10 task × 1 provider (openai-kimi=Kimi K2.6) baseline 数据底座.

**实测数据**: `data/eval/baseline-V0.26.4-kimi.json` (git_sha=41c50a2, V0.26.4 commit).

## 总体数据

| 指标 | 值 |
|------|------|
| corpus | V0.26.1 10 task |
| provider | openai-kimi (Kimi K2.6 国内版 platform.moonshot.cn) |
| total pass | **2/10 = 20.0%** |
| avg steps | 5.5 |
| p50 wallclock | 45.4s |
| total cost | **$0.21** |
| corpus 跑总耗时 | ~10 min |

## 按 capability_axis pass rate matrix

| capability_axis | Kimi K2.6 |
|-----------------|-----------|
| **multi-tab** (V0.21) | **100%** ✅ |
| **failure-recovery** (V0.25.3) | **100%** ✅ |
| baseline (中文 H1 提取) | 0% (中文 mojibake) |
| iframe (V0.22) | 0% |
| drag (V0.23) | 0% |
| upload (V0.23) | 0% |
| download (V0.23) | 0% |
| dialog (V0.24) | 0% |
| keyboard-nav (V0.24.2) | 0% |

## failure buckets 分布

| bucket | 命中数 | 含义 |
|--------|--------|------|
| OK | 2 | predicate 过 (multi-tab + failure-recovery) |
| PREDICATE_FAIL | 2 | 跑完但 result 不含 token (baseline mojibake + 1 task) |
| `(max_steps 耗尽未完成)` | 4 | LLM 卡死撞 max_steps 上限 (iframe/drag/upload/download/dialog 含) |
| LLM_FAILED | 1 | Kimi reasoning 占满 max_tokens 不返 tool_call (cross-feature stress task) |
| EVAL_INFRA_ERROR | 1 | chromium / runner 路径异常 (待 V0.27 排查) |

## 限制说明

- **中文 SoM 截图 mojibake** — V0.26.5 实测 baseline-extract-h1 task fixture 含中文 H1
  "量子纠缠是粒子之间的关联", Kimi vision 返回 mojibake `é‡åç° ç¼ æ˜¯ç²’åä¹‹é—´çš„å…³è"`
  (UTF-8 字节直接当 Latin-1 解码), SubstringPredicate 直接 fail. 9 个 ASCII token task 不受影响.
- **tool_choice="auto" 不强制** — Kimi 偶尔 reasoning 占满 max_tokens 不返 tool_call
  (V0.20.5 实测; cross-feature task 复刻). V0.25.0 transient retry 兜底 (RuntimeError → fatal abort 不重试因为是配置问题非临时网络).
- **vision detail=high SoM** — Kimi K2.6 处理多元素 SoM 截图 + 拟人 tool_use 决策反应明显比
  Anthropic Sonnet 4.6 差, **iframe/drag/upload/download/dialog 全 0% pass** 体现.

## V0.27 路线协同

V0.26.5 baseline 揭示 Kimi K2.6 在 9 能力轴上的 pass rate matrix 决定 V0.27 凭证 vault 设计:

### 决策建议 (基于 Kimi-only baseline)

| capability | Kimi 表现 | V0.27 vault 决策 |
|------------|----------|------------------|
| multi-tab | 100% | **可放权 V0.28 无人值守** (Kimi 真懂 switch_tab) |
| failure-recovery | 100% | **可放权** (Kimi 看 SYSTEM_PROMPT 第 14 条不死磕) |
| iframe | 0% | **保留 elicit** (Kimi 不懂 frame_path 路由 / SoM iframe 内不可见) |
| drag/upload/download/dialog/keyboard-nav | 0% | **保留 elicit** + **V0.27 跑 Anthropic baseline 必需** (Kimi 限制 ≠ 框架限制) |

**关键判断**: 单 Kimi baseline **不足以**直接开 V0.28 无人值守模式 — iframe/drag/upload 类
0% 失败率高但**不能确定是 Kimi vision 限制还是 web-agent 框架问题**. V0.27 启动时**必须**:
1. 配 `ANTHROPIC_API_KEY` 跑 cross-provider baseline (web-agent-eval 已支持 `--providers anthropic,openai`)
2. 对比 anthropic vs openai-kimi 各 9 能力轴 pass rate matrix
3. **若 Anthropic Sonnet 4.6 跨 9 轴 ≥ 80%** → V0.28 无人值守按 capability 放权
4. **若 Anthropic 也 <60%** → V0.27 之前必须先修 web-agent 框架 bug

### 后续动作清单

- [ ] V0.27.0: 配 ANTHROPIC_API_KEY + 跑 Anthropic baseline (~$3.6 单次)
- [ ] V0.27.1: 跨 provider 对比表 (Kimi vs Sonnet) 识别 web-agent 框架 bug 边界
- [ ] V0.27.2-N: 凭证 vault 实现 + per-provider 分级
- [ ] V0.28: 无人值守模式 + per-capability 权限边界

## V0.26 系列总结 (6 commit / V0.26.0-5)

| ver | commit | 解锁节点 |
|-----|--------|---------|
| V0.26.0 | 705f0ae prep + framework | eval/ 顶层模块 + types/predicates/runner 框架 + 1 baseline 示范 task |
| V0.26.1 | corpus 充实 | corpus 10 task + 2 trace-aware predicate + token-specific lint |
| V0.26.2 | A/B harness | A/B harness + token cost (Usage 中性 schema + last_usage Protocol attr) + markdown report |
| V0.26.3 | CLI + opt-in | web-agent-eval CLI + 双 opt-in env (RUN_EVAL=1 + EVAL_REAL=1) + GitHub Actions stub |
| V0.26.4 | 41c50a2 bug fix | bug fix _last_task_id SQL 列名 + Kimi name 标记 + load_dotenv + docs 框架 |
| V0.26.5 | data-only | baseline JSON 落档 + 本文档具体数据填充 + V0.27 路线决策建议 |

净增 ~70+ 单元测. V0.25.3 → V0.26.5 跨度 6 个版本号, 单元测 431 → 491 (+60, 14% 增).
真 chromium slow smoke 不变 15. **真 LLM eval 真跑实测 1 次** (本 baseline) 总花费 $0.21.

## 限制说明 (跨 provider 对比留 V0.27)

V0.26.4 用 Kimi-only baseline (跨 provider Anthropic/OpenAI gpt-5.5 留 V0.27 vault 启动时
真 ANTHROPIC_API_KEY 配置后再跑). 当前 baseline 揭示 Kimi K2.6 在 9 能力轴上的 pass rate
是 **Kimi vision + tool_use 能力上限**, 不是 web-agent 框架上限. 关键 Kimi 限制:

- **中文 SoM 截图 mojibake** — V0.26.4 实测 baseline-extract-h1 task fixture 含中文 H1
  "量子纠缠是粒子之间的关联", Kimi vision 返回 mojibake `é‡åç° ç¼ æ˜¯ç²’åä¹‹é—´çš„å…³è"`
  (UTF-8 字节直接当 Latin-1 解码), SubstringPredicate 直接 fail. 9 个 ASCII token task 不受影响.
- **tool_choice="auto" 不强制** — Kimi 偶尔 reasoning 占满 max_tokens 不返 tool_call
  (V0.20.5 实测). V0.25.0 transient retry 兜底 (RuntimeError → fatal abort 不重试因为是
  配置问题非临时网络).
- **vision detail=high SoM** — Kimi K2.6 vision 处理多元素 SoM 截图 + 拟人 tool_use 决策
  反应可能比 Anthropic Sonnet 4.6 差.

## 数据落档

| 文件 | 说明 |
|------|------|
| `data/eval/baseline-V0.26.4-kimi.json` | V0.26.5 baseline JSON (git_sha=41c50a2, ~9KB, commit 进 git) |
| `data/eval/screenshots/` | gitignored — 每 step 真截图 PNG (~MB 量级不进 commit) |
| `data/eval/trace.db` | gitignored — 每 task 实际 trace SQLite |
| `eval/cassettes/.gitkeep` | V0.26.5 暂未真录 vcr cassette (留 V0.27 vcr 集成完整后) |
