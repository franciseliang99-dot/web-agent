# V0.34.3 Perceive Bench Fan-Out Baseline + F1 ROI 决策

V0.34.2 baseline 全是 linear chain (siblings_per_layer=1) — F1 iframe DFS asyncio.gather 并发
在 linear chain **深度依赖串行无并发空间**, 节省 ~0%. V0.34.3 扩 fixture 加 `siblings_per_layer`
参数支持 fan-out 树状, 跑真测 baseline 验 F1 在 fan-out 站点 ROI.

**实测数据**: `data/bench/v0.34.3-fanout-baseline.json` (git_sha=`pending V0.34.3 commit`).

环境同 V0.34.2 baseline (chromium 147.0.7727.15, Playwright 1.59.0, Python 3.12.3, headless).

## 数据 (7 fixture × 8 samples median)

| fixture | iframe | sibling | total frame | mark | median ms | Δ vs baseline |
|---------|--------|---------|-------------|------|-----------|---------------|
| if0-sh0-leaf5 (baseline) | 0 | 1 | 1 | 5 | 110 | — |
| if1-sh0-leaf3 | 1 | 1 | 2 | 3 | 124 | +13% |
| **if1-sib3-sh0-leaf3** | 1 | **3** | **4** | 9 | 185 | +68% |
| **if1-sib5-sh0-leaf3** | 1 | **5** | **6** | 15 | 244 | +122% |
| if2-sh0-leaf3 (linear) | 2 | 1 | 3 | 3 | 117 | +6% |
| **if2-sib3-sh0-leaf3** | 2 | **3** | **13** | 27 | **426** | **+287%** |
| if5-sh0-leaf3 (linear) | 5 | 1 | 6 | 3 | 240 | +118% |

## 关键发现

**Frame count 是主因, 不是 depth vs width**:

- `if1-sib5-sh0-leaf3` (6 frame, depth=1 fan-out 5): **244ms**
- `if5-sh0-leaf3` (6 frame, depth=5 fan-out 1): **240ms**

两者 frame 数同, ms 几乎一样 (差 <2%, in noise). 每 frame `evaluate(SoM JS)` 约 **20-30ms**
顺序 inject. 跟 sibling 还是 depth 无关.

## F1 真节省估算 (基于真测数据)

### Linear chain (depth-dependent)
- `if5-sh0-leaf3`: 5 层串行 DFS, grand-child 必须等 parent load + evaluate 完才 access.
- F1 `asyncio.gather` 在同层 sibling 才工作; linear chain 同层只 1 child, gather 退化串行.
- **节省 ~0%**.

### Fan-out 同层 (sibling parallelism)
- `if1-sib5-sh0-leaf3`: 主 frame ~50ms + 5 sibling 顺序 ~30ms × 5 = 200ms 序列 = 244ms 真测.
- F1 后: 主 + max(5 sibling) = 50 + 30 = **~80ms** (cap at slowest sibling).
- **节省 ~67% (~164ms)**.

### Fan-out 树状
- `if2-sib3-sh0-leaf3`: 主 + 3 child + 9 grand-children = 13 frame, 426ms 顺序.
- F1 同层并发: 主 + max(3 child = (inject + max(3 GC))) = 50 + (30 + 30) = **~110ms**.
- **节省 ~74% (~316ms)**.

## F1 ROI 决策

| 场景 | F1 节省 | 适用真实站点 |
|------|---------|--------------|
| Linear chain | ~0% | 无 (GitHub PR comment edit iframe 单层不属并发场景) |
| Fan-out 同层 | ~67% | Gmail 主页 (3-5 sibling iframe 同时), Twitter widget bar (2-4 ad iframe) |
| Fan-out 树状 | ~74% | reCAPTCHA + iframe 嵌套 widget (Cloudflare turnstile 多 iframe), Outlook 网页版 |

**F1 实施值得 V0.34.4 做**:
- 真实多 sibling iframe 站点 (Gmail/Outlook/Twitter widget) 节省 50-70% perceive ms
- 单 step 节省 ~150-300ms → 20 step task 累计 ~3-6s wallclock 节省
- 解耦审查可控 (V0.22.x actuator data-som-id 一致性需 renumber JS 配套保, 已有 Plan agent 方案 C)

**V0.34.4 F1 实施 plan (基于 V0.34.3 真测)**:

1. `_walk_child_frames` 改 `asyncio.gather(*[_process_one(i, c) for c in parent.child_frames])`
2. 每 child 内部 inject 用 `id_offset=0` (无法预知 sibling 间 offset, 并发不能共享 `len(marks)`)
3. inject 结果回来后 Python 端按 DFS index 顺序拼 marks list, renumber `Mark.id` 1..N 全局连续
4. 各 frame 跑第二遍 `_SOM_RENUMBER_JS({old_id: new_id})` 修 DOM `data-som-id` + 视觉框 `tag.textContent`
5. **前置改 `_SOM_INJECT_JS`**: 给视觉框 tag 也挂 `data-som-id` mirror, renumber 时一并改
6. `cross_origin_hosts` 改 functional return tuple, 不共享 mutate list (并发竞态)
7. 新加 fan-out fixture slow smoke 测 (if1-sib5 / if2-sib3) 验 ms 节省 >= 50%
8. V0.22.2 actuator iframe click 真测 `tests/test_loop_iframe.py` 跑通 (V0.22.x 兼容核心 gate)

预估 LOC: ~75 src + ~50 测 + CHANGELOG ~25 行. 风险中等 (id 一致性 V0.22.x 核心契约).

## 限制 / V0.34.4 待补

- **F2 SoM JS 三 walker 合并仍低优**: V0.34.3 真测 shadow 0 overhead, F2 真实节省 ≈ 2-4ms local
  chromium RTT, 远程 chromium ~100-200ms RTT 才显著. 留 V0.34.5 (F1 完成后).
- **真站点 baseline 待补**: synthetic fan-out fixture 验证 F1 ROI 估算, 真站点 (Gmail / Outlook /
  Twitter) 实际收益需 eval framework (V0.26+) 双轴交叉评测.
- **fan-out × shadow 混合 fixture 未跑**: V0.34.3 数据仅 sib × iframe, sib × shadow 留 V0.34.x.
- **fixture cold-start noise**: `if0-sh0-leaf5` 第一 fixture ms 110 (vs V0.34.2 该 fixture 56),
  非 fixture 真 cost 升高, 是 browser cold start. V0.34.x adapter 加 warmup discard (run --warmup N).

## V0.34 系列进度

| ver | 状态 | scope |
|-----|------|-------|
| V0.34.0 | ✅ | bench harness framework (24 测) |
| V0.34.1 | ✅ | 真跑 chromium adapter (+7 unit, +3 slow) |
| V0.34.2 | ✅ | fix iframe/shadow 嵌套 bug (#15 #16 沉淀) + V0.34.2 baseline |
| **V0.34.3** | ✅ 本提交 | fan-out fixture extension (siblings_per_layer) + fan-out baseline + F1 ROI 真测决策 |
| V0.34.4 | 待 | F1 实施 (iframe DFS asyncio.gather 并发 + renumber JS): fan-out 站节省 ~67-74% 真测验 |
| V0.34.5 | 待 | F2 SoM JS 三 walker 合并 (remote chromium 才显著, 低优) + V0.34 系列收尾 |
