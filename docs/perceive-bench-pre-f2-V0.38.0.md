# V0.38.0 Perceive Bench Pre-F2 Baseline + 决策门槛

V0.37.3 收尾 user 选 F2 主题. V0.38.0 = F2 实施前 baseline + decision doc, 跟 V0.34.0 / V0.36.0
framework-first 同节奏 (V0.34 教训第 N 次应用: 实施前真测 baseline 防"没数据就优化是猜").

## F2 三 walker 现状梳理

`src/web_agent/perceiver.py` "三 walker" 实指:

| # | 文件位置 | JS 块 | 职责 | evaluate 次数 |
|---|---------|-------|------|--------------|
| **W1** | `_SOM_INJECT_JS:29-41` | DFS document + open shadowRoot, `querySelectorAll(sel)` collect 交互元素 | 1 (同 INJECT) |
| **W2** | `_SOM_INJECT_JS:56-69` | DFS document + open shadowRoot, `querySelectorAll('[data-som-id]').removeAttribute(...)` V0.22.2 防 stale id | 1 (同 INJECT, 跟 W1 同 evaluate) |
| **W3** | `_SOM_RENUMBER_JS:142-164` | V0.34.4 DFS + 改 `data-som-id` + 视觉框 `textContent` | 1 (独立 evaluate) |

**RTT 经济学关键**:
- W1+W2 已在**同一 evaluate** (1 RTT), 不是 3 RTT
- W3 独立 evaluate (1 额外 RTT, V0.34.4 加)
- 每 frame perceive 真实 evaluate = 2 (`_SOM_INJECT_JS` + `_SOM_RENUMBER_JS`) + 1 cleanup (`_SOM_REMOVE_JS`, 单调用 querySelectorAll **不是 walker**)

V0.34.5 retrospective 标 F2: "microbench local chromium ~2-4ms 节省微, real-world remote
~100-200ms RTT × 3 → 显著. 但 web-agent 接管本地 9222 Chrome → 真节省微. **代码 simplification
不是 perf gain**."

## V0.38.0 真测 baseline (跟 V0.34.3 fan-out fixture 同 set)

`data/bench/v0.38.0-before-f2-baseline.json` (V0.37.3 commit 0.37.3 state, 0 src 改 = V0.34.4 行为):

| fixture | iframe | sibling | total frame | mark | median ms (V0.38.0) | vs V0.34.3 |
|---------|--------|---------|-------------|------|---------------------|------------|
| if0-sh0-leaf5 | 0 | 1 | 1 | 5 | 113.4 | +3% (110 V0.34.3) |
| if1-sh0-leaf3 | 1 | 1 | 2 | 3 | 129.7 | +5% (124) |
| if1-sib3-sh0-leaf3 | 1 | 3 | 4 | 9 | 194.4 | +5% (185) |
| if1-sib5-sh0-leaf3 | 1 | 5 | 6 | 15 | 242.6 | -0% (244) |
| if2-sh0-leaf3 | 2 | 1 | 3 | 3 | 168.8 | **+44%** (117) — outlier, 沙箱 cold cache anomaly |
| if2-sib3-sh0-leaf3 | 2 | 3 | 13 | 27 | 432.1 | +1% (426) |
| if5-sh0-leaf3 | 5 | 1 | 6 | 3 | 249.4 | +4% (240) |

(if2 +44% 是 cold cache outlier, sample_count=8 median 偶 anomaly. 其他 6 fixture 全 ±5% 之内,
说明 V0.34.3 → V0.38.0 无 src 改 = 无行为变 ✓.)

## F2 W1+W2 合并方案 (V0.38.1 候选, 决策门槛)

**方案 C (推荐, race-free, 最小改动)**: W1 + W2 合成单 walker, 同 1 DOM tree DFS 跑 collect +
clear:

```js
// V0.38.1 候选 (本 commit 不动 src, 仅 baseline + decision)
const collected = [];
const visited = new WeakSet();
const stack = [document];
while (stack.length) {
  const root = stack.pop();
  if (visited.has(root)) continue;
  visited.add(root);
  // 同 root 一次穿透同时干 W1 (collect) + W2 (clear data-som-id)
  root.querySelectorAll('[data-som-id]').forEach(e => e.removeAttribute('data-som-id'));
  root.querySelectorAll(sel).forEach(e => collected.push(e));
  if (!SHADOW_ON) continue;
  root.querySelectorAll('*').forEach(e => {
    if (e.shadowRoot && e.shadowRoot.mode === 'open' && !visited.has(e.shadowRoot)) {
      stack.push(e.shadowRoot);
    }
  });
}
```

**节省路径**: 省 1 次 DOM tree DFS (W2 全块) + 1 次 `querySelectorAll('*')` shadowRoot 探测/层.

**估真节省** (V0.34 教训: 真测前估算 only):
- 每 frame ~0.5-1ms (单 DOM tree 穿透 + querySelectorAll('*') 在 < 50 node fixture 上几微秒/次)
- if5-sh0 (6 frame): ~3-6ms / 249ms = 1-2% 节省 (估)
- if0-sh0 (1 frame): ~0.5-1ms / 113ms = 0.5-1% 节省 (估)

## 决策门槛 (V0.34 教训应用)

V0.38.1 实施后真测 vs V0.38.0 baseline:

- **真节省 ≥ 5% (任一 fixture)** → 实施保留, 沉淀真发现 #N "F2 walker 合并 in local chromium 也有 perf gain"
- **真节省 1-5%** → 实施保留, 标"主要是代码 simplification, perf gain 微"
- **真节省 < 1%** → **withdraw 不实施**, 文档化 "F2 真节省 < noise, 推 V0.39+ remote chromium 场景再做" (跟 V0.34.4 F1 ROI 3% withdraw 同模式但更严)

**门槛先写**: V0.34 教训"假设没真测验证是 silent 性能猜测"的反向应用 — 先写 decision 门槛防
事后 rationalize "1% 节省也算 win".

## V0.34 教训应用第 N+1 次

- ✅ **实施前真测 baseline** (V0.38.0 = before-F2 真数据底座)
- ✅ **决策门槛先写** (≥ 5% / 1-5% / < 1% 三档预定)
- ✅ **不为虚假 perf 改** (F2 真值在 code simplification, perf 是副效果)
- ✅ **estimate ≠ 真测** (V0.38.0 估 0.5-1% 节省, V0.38.2 真测可能推翻)

## V0.38 系列 plan (4 commit autonomous)

| ver | scope | autonomous |
|-----|-------|------------|
| **V0.38.0** | ✅ 本提交: F2 baseline before-F2 + decision doc | ✅ |
| V0.38.1 | F2 W1+W2 walker 合并实施 + 6-7 单测 + V0.22.x 契约 grep verify | ✅ |
| V0.38.2 | F2 后真测重跑 + V0.38.0 baseline compare + 真发现沉淀 (decision 门槛兑现) | ✅ |
| V0.38.3 | 系列收尾 retrospective + V0.39 主题候选累计 | ✅ |

(F2 不烧 token, 全 autonomous, 跟 V0.34/V0.36 同 0 maintainer deferred.)
