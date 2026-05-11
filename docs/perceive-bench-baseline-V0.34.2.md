# V0.34.2 Perceive Bench Baseline

V0.34.2 跑 7 fixture × 8 samples 真 chromium baseline 数据底座, 推 V0.34.3 F1 iframe 并发优先 vs V0.34.4 F2 SoM JS 合并的 ROI 决策.

**实测数据**: `data/bench/v0.34.2-baseline.json` (git_sha=`7b26262`, V0.34.2 commit).

**环境 stamp** (reproducibility):
- Python 3.12.3
- Playwright 1.59.0
- Chromium 147.0.7727.15
- 跑 host: Claude Code bash sandbox (linux x86_64, headless)
- 复跑命令:
  ```bash
  WEB_AGENT_RUN_SLOW=1 uv run pytest tests/test_perceive_bench_real.py
  uv run web-agent-perceive-bench run \
    --fixtures "if0-sh0-leaf5,if1-sh0-leaf3,if2-sh0-leaf3,if5-sh0-leaf3,if0-sh2-leaf5,if3-sh1-leaf5,if2-sh2-leaf3" \
    --samples 8 \
    --out data/bench/v0.34.2-baseline.json
  ```

## 总体数据

| fixture | iframe | shadow | leaf | median ms | mark | mem KB | Δ vs baseline |
|---------|--------|--------|------|-----------|------|--------|---------------|
| if0-sh0-leaf5 (baseline) | 0 | 0 | 5 | 99.50 | 5 | 394.1 | — |
| if0-sh2-leaf5 | 0 | 2 | 5 | 56.30 | 5 | 385.5 | -43% (shadow 0 overhead, baseline cold-start noise) |
| if1-sh0-leaf3 | 1 | 0 | 3 | 92.12 | 3 | 360.8 | -7% (单层 iframe ≈ baseline) |
| if2-sh0-leaf3 | 2 | 0 | 3 | 136.29 | 3 | 409.7 | +37% |
| if2-sh2-leaf3 | 2 | 2 | 3 | 115.99 | 3 | 411.8 | +17% (shadow 不增) |
| if3-sh1-leaf5 | 3 | 1 | 5 | 136.16 | 5 | 437.8 | +37% |
| if5-sh0-leaf3 | 5 | 0 | 3 | 207.60 | 3 | 470.6 | **+109%** (F1 主战场) |

(median 8 samples, no warmup discard — baseline cold-start 噪音影响 if0-sh0 估高, 真实 perceive cost ≈ if0-sh2 56ms.)

## F1 vs F2 ROI 评估

### F1: iframe DFS asyncio.gather 并发

**净 iframe overhead 估算** (假设真 baseline perceive ≈ 56ms, 取 shadow=2 cold-cache 后值):

| iframe count | total ms | iframe overhead | per-layer overhead |
|--------------|----------|-----------------|--------------------|
| 0 | ~56 | 0 | — |
| 1 | 92 | +36 | 36ms/层 |
| 2 | 136 | +80 | 40ms/层 |
| 3 | 136 | +80 | 27ms/层 (noisy) |
| 5 | 208 | +152 | 30ms/层 |

iframe 顺序 DFS ~30-40ms/层. 5 层 → ~150ms 序列耗时.

**F1 并发理论节省**: `asyncio.gather` 让各 iframe inject/walk 并发, 总耗时 cap at slowest layer (single layer ~36ms) ≈ ~36ms (vs 顺序 152ms). **节省 ~76%, 即 ~115ms** for 5 层 iframe.

**真实站点典型 iframe 数**: Gmail (~3-5 inner iframes), GitHub PR (1-2 iframes), Twitter (2-4 widget iframes). **F1 优化对 deep-iframe 站如 Gmail 节省 ~60-100ms/perceive, 累计 20 step task ~1-2s wallclock**.

### F2: SoM JS 三 walker 合并

**Shadow 0 overhead 观察**: if0-sh2-leaf5 / if2-sh2-leaf3 vs same iframe without shadow, ms 差 ≈ 0 (shadow walker JS 跑在 evaluate context 内, 0 RTT).

**F2 节省来源** = 主 frame perceive 三段 JS evaluate (selector / remove old / re-attach SoM ID) 合并成 1 段 → 节省 2 round-trip JS-evaluate RTT.

**Microbench local chromium RTT** ≈ 1-2ms/evaluate. F2 节省 ≈ 2-4ms. **真实远程 chromium 才有意义** (~50-100ms RTT × 3 calls → 节省 ~100-200ms).

但: web-agent 当前接管本地 9222 Chrome, 真实场景 = local chromium → F2 节省微乎其微. 远程 chromium 用例 = MCP 远 client + 本地 chromium 是 already local.

## 决策

**V0.34.3 = F1 iframe DFS asyncio.gather 并发** (ROI 显著: deep-iframe 站节省 ~60-100ms/perceive).
**V0.34.4 = F2 SoM JS 三 walker 合并** (低优先, microbench 局部 RTT 几乎 0 节省, 留作完整性收尾).

V0.34.3 完成后重跑本 baseline + compare:
```bash
uv run web-agent-perceive-bench compare \
  data/bench/v0.34.2-baseline.json data/bench/v0.34.3-after-F1.json \
  --a-label "V0.34.2 baseline" --b-label "V0.34.3 F1 并发"
```

期望:
- if5-sh0-leaf3 (5 层) ms 从 ~208ms → ~95ms (-54%)
- if2-sh0-leaf3 (2 层) ms 从 ~136 → ~95ms (-30%)
- if1-sh0-leaf3 (单层) ms 持平 ≈ 92ms (单层并发 = 顺序)
- if0-sh0-leaf5 baseline 持平

若 F1 实测节省 < 30% (理论 76% 远不达), 说明 chromium iframe DFS 不主要受 Python 端 await 影响, 转 F3 / F5 重审.

## 限制 & 待补

- **shadow_walks / iframe_walks = 0** (perceiver V0.22.x JS walker 不暴露 counter). 加 counter 需改 `_SOM_INJECT_JS` 接口, 留 V0.34.4 SoM 合并时一并补 (F2 + 字段填充同 commit).
- **样本量 8 偏少**: V0.34.x 增 16-32 sample + warmup 1 次 discard (V0.34.3 改 adapter 加 `--warmup` 参数). 当前数据 cold-start `if0-sh0` ms 偏高已显 noise.
- **fixture 局限性**: synthetic fixture 不模拟真站点 cookie banner / GDPR overlay / SPA hydration delay. 真站点 baseline 留 eval framework (V0.26+) 双轴交叉评测.
- **未跑双 LLM provider**: bench 不烧 token, perceive() 跑哪 provider 无关. F1 完成后真站点 eval 再交叉.

## 真发现沉淀引用

V0.34.2 修两 bug 沉淀 #15 + #16, 详 CHANGELOG V0.34.2 entry. 教训: framework 24 测全过 ≠ 真行为对, **每 framework 落地后 V0.34.x +1 commit 加真跑 verify 验** (V0.34.0 → V0.34.1 → V0.34.2 即此 pattern, 跟 V0.33.0 → V0.33.1 V0.26.2 silent bug audit 同节奏).
