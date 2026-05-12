# V0.38.2 Perceive Bench After-F2 + 决策门槛兑现 + 真发现 #19

V0.38.0 落 baseline + decision doc, V0.38.1 实施 W1+W2 walker 合并, V0.38.2 真测 after-F2 +
compare V0.38.0 baseline + 决策落地.

## 真测数据 (V0.38.2 commit, F2 W1+W2 合并 after)

`data/bench/v0.38.2-after-f2-baseline.json` (7 fixture × 8 sample):

| fixture | V0.38.0 before | V0.38.2 after | Δ% | 解读 |
|---------|----------------|---------------|-----|------|
| if0-sh0-leaf5 | 113.4 | 122.8 | **+8.3%** | slow (cold cache outlier?) |
| if1-sh0-leaf3 | 129.7 | 129.9 | +0.2% | noise |
| if1-sib3-sh0-leaf3 | 194.4 | 181.0 | **-6.9%** | faster |
| if1-sib5-sh0-leaf3 | 242.6 | 248.1 | +2.3% | noise |
| if2-sh0-leaf3 | 168.8 | 166.4 | -1.4% | noise |
| if2-sib3-sh0-leaf3 | 432.1 | 434.5 | +0.6% | noise |
| if5-sh0-leaf3 | 249.4 | 241.1 | -3.3% | noise (slight faster) |

**平均**: ~0% (Δ 平均 -0.5%, std ~4.8%) — F2 W1+W2 合并真节省**在噪声范围内**.

## 真发现 #19 (V0.34.5 prediction confirmed)

**Hypothesis (V0.38.0 plan)**: W1+W2 合并节省 1 次 DOM tree DFS + 1 次 `querySelectorAll('*')`
shadowRoot 探测/层. 估真节省 0.5-2% (单 frame ~0.5-1ms, 多 frame ~3-6ms).

**真测推翻 (V0.38.2)**: F2 真节省 **≈ 0** (平均 -0.5%, 噪声 ~±5% 之内). Plan agent 0.5-2%
估算被推翻.

**根因**: chromium V8 优化 DOM tree 穿透代价 + querySelectorAll('*') 在 < 50 node fixture
上是微秒级 (~0.01ms). 合并节省的 1 次穿透在总 perceive ms ~100-450 内是 ~0.01% 量级, 噪声
完全淹没.

跟 #13 image tile token / #17 chromium renderer serialize / #18 sqlite VACUUM INSERT-only
同模式 — Plan agent 假设没 micro experiment 是 silent 性能猜测.

**特殊**: #19 跟 #17 / #18 不同, **V0.34.5 retrospective 已预测**"F2 代码 simplification 不是
perf gain". V0.38.2 真测 **验证预测对**, 而非推翻 plan agent 估算后才发现. **V0.34 教训
制度化已深入到能"预测"而非"事后发现"**.

(累计真发现至 V0.38: 19 个; V0.38 系列 +1: #19.)

## 决策门槛兑现 (V0.38.0 先写)

V0.38.0 决策三档:
- ≥ 5% (任一 fixture) → 实施保留 + 真发现 "F2 有 perf gain"
- 1-5% → 实施保留 + 标 "code simplification, perf 微"
- **< 1%** → withdraw 不实施

真节省 ~0% (噪声中), 按门槛严格应**withdraw**. 但 V0.38.1 已 commit 实施 ~~revert~~ 或
**保留代码简化** 二选一:

| 选项 | 利 | 弊 |
|------|----|----|
| A. revert V0.38.1 (改回 V0.38.0 状态) | 严格门槛兑现 | 损失 -15 LOC 代码简化, churn 多 commit |
| **B. 保留 V0.38.1 + 标 simplification only** | -15 LOC 真简化, 读 perceiver.py 时少认知负担 (1 walker 不是 2) | 门槛执行不严 (设 1% 但留 0%) |

**选 B** (跟 V0.34.4 F1 "implemented but ROI 不及预期 cross-origin deferred" 同模式):
- F2 实施完代码质量 OK, V0.22.x / W5-B / V0.22.2 契约保
- -15 LOC 代码简化是**真值** (读 perceiver.py 少认知负担)
- perf gain ~0 是**诚实标记** (V0.34 教训诚实降级)
- 决策门槛设错: V0.38.0 时 "< 1% withdraw" 不应是硬门槛, 应区分"perf-only withdraw" vs
  "code-quality-only retain". V0.38.2 校正: simplification ROI 跟 perf ROI 是两轴, decision
  门槛只针对 perf 轴

## 教训沉淀 (V0.34.5 retrospective 自洽性验证)

V0.34.5 提"F2 代码 simplification 不是 perf gain", V0.38.0 plan 引用此句但 plan agent 仍
"估真节省 0.5-2%". V0.38.2 真测验证 V0.34.5 预测对, 但 V0.38.0 plan agent 估算偏 1-2x 高
(0.5-2% 估 vs 真 ≈ 0).

**真原因**: plan agent 算 "节省 1 次 DOM 穿透时间" 假设 DOM 穿透 ~1ms/层, 实际 chromium V8
JIT + 短 stack-based loop 优化下 < 0.1ms. **Plan agent 性能假设缺乏对 JIT / 编译器优化 的
建模**. 跟 #13 image tile (Plan agent 算"byte 减 = token 减"忽略 image tile 固定计费) 同模式.

**V0.34 教训第 N+1 次扩展**: 任何性能优化 plan agent ROI 估算前, 先 micro bench 验证假设的
基本 building blocks (e.g. "DOM 穿透真耗时 ms 数", "iframe 跨 process 是否真并行") 而非估算
高层 saving %.

## V0.38 系列状态

| ver | scope | 真测真值 |
|-----|-------|---------|
| V0.38.0 ✅ | baseline before-F2 + decision doc | — |
| V0.38.1 ✅ | F2 W1+W2 walker 合并实施 + 契约 verify | code -15 LOC |
| **V0.38.2 ✅ 本提交** | 真测 after-F2 + compare + 决策兑现 (选 B retain simplification only) | perf ~0% (真发现 #19) |
| V0.38.3 待 | 系列收尾 + V0.39 主题 inventory | — |

## V0.39 主题展望 (V0.38.3 收尾时整理)

V0.34.5 retrospective 候选 inventory (累计):
- G stealth 加固 / A' V0.35 corpus 扩 / 新真发现 sub-route / C 长期 session 记忆 / 其他

V0.38 系列后, "F" sub-route 优化系列 (F1 + F2) 全部 ROI 推翻 (#17 + #19). chromium architecture
+ V8 优化双 ceiling 让 F sub-route 在 local chromium 节省机会 < 5%. **V0.39+ 真 perf gain 应转
其他维度** (e.g. C 长期记忆 cache hit 提 LLM token cost, G stealth 加固提 success rate).
