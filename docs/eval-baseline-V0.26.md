# V0.26 Eval Baseline (Kimi-only, V0.26.4)

V0.26.4 跑 V0.26.1 corpus 10 task × 1 provider (openai-kimi) baseline 数据底座.

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
| `data/eval/<run_id>.json` | V0.26.2 metrics schema (含 metrics list + aggregate + by_axis) |
| `eval/cassettes/.gitkeep` | V0.26.4 暂未真录 vcr cassette (留 V0.26.5 vcr 集成完整后) |
| 本文件 | V0.26 系列 baseline 总结 + V0.27 路线协同 |

## V0.27 路线协同

V0.26.4 baseline 揭示的 9 能力轴 pass rate 决定 V0.27 凭证 vault 设计:

- pass rate ≥ 80% 能力 → V0.28 无人值守模式可放权 (drag/upload 等动作型)
- pass rate < 60% 能力 → 留 V0.18.0 elicit 流程 (LLM 决策不稳, 必须用户每次确认)
- Kimi 中文 mojibake → V0.27 vault 默认 provider 选 Anthropic (任务含中文时), Kimi 走 ASCII fallback

后续 V0.27 启动时**必须**:
1. 配 ANTHROPIC_API_KEY 跑 cross-provider baseline (V0.26.2 metrics aggregator 已支持 incremental update)
2. 对比 anthropic vs openai-kimi 各 9 能力轴 pass rate matrix
3. 决定 V0.28 无人值守模式开权限边界 (per-capability)

## V0.26 系列总结 (5 commit / V0.26.0-4)

| ver | commit | 解锁节点 |
|-----|--------|---------|
| V0.26.0 | (commit hash) | eval/ 顶层模块 + types/predicates/runner 框架 + 1 baseline 示范 task |
| V0.26.1 | (commit hash) | corpus 10 task + 2 trace-aware predicate (TraceContainsAction/TraceObsContains) + token-specific lint |
| V0.26.2 | (commit hash) | A/B harness + token cost (Usage 中性 schema + last_usage Protocol attr) + markdown report |
| V0.26.3 | (commit hash) | web-agent-eval CLI + 双 opt-in env + GitHub Actions stub |
| V0.26.4 | (commit hash) | Kimi-only baseline 跑 + JSON 落档 + 本文档 + V0.27 路线协同 |

净增 ~50+ 单元测. V0.25.3 → V0.26.4 跨度 5 个版本号, 单元测 431 → ~500+ (~70 新), 真 chromium
slow smoke 不变 15 (eval 端到端真跑不在 slow smoke 范围, opt-in env 单独 channel).
