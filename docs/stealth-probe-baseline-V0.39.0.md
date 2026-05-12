# V0.39.0 sannysoft Stealth Baseline + 真发现 #20

V0.38.3 收尾 user 选 G stealth 加固. V0.39.0 = probe 改造抽 DOM 分数 + baseline + decision doc.
跟 V0.38.0 / V0.36.0 / V0.34.0 framework-first 同节奏 (V0.34 教训第 9 次应用).

## 真测 baseline (sannysoft.com, V0.39.0 commit state)

`data/stealth_probes/sannysoft_<UTC date>.json`:

```json
{
  "mode": "launch_headless",
  "summary": {
    "total": 31,
    "passed_count": 30,
    "failed_count": 1,
    "pass_rate": 0.968,
    "failed_tests": ["WebDriver\n(New)"]
  }
}
```

**真测结果**: **30/31 passed (96.8%)**, 唯一 fail: `WebDriver (New)`.

## 真发现 #20 README "72%" 24 months stale 数据爆推翻

V0.38.3 retrospective + V0.39 主题描述都引 "sannysoft.com 实测 ~72% 通过率" (V0.16.14 patchright
spike 时数). V0.30.0 后大量加固 (`apply_stealth_plus` + V0.30.4 stealth_plus 真发现) **未重测**,
README + ARCHITECTURE §1.3 + V0.34.5 retrospective 引此数据持续 24 months 不更新.

**真测推翻**: 当前真值 **96.8%** (+24.8% vs README 72%).

**Plan 影响**: V0.38.3 retrospective 提的 V0.39 主题 "sannysoft 72% → 85%+" **已自动达成** —
V0.30.0 apply_stealth_plus 已把 72% 提到 96.8% (远超 85%+). V0.39 主题原 ROI 估算 (13% 提升空间)
**完全错误**, 真实空间仅 3.2% (30/31 → 31/31).

**教训**: 文档数值的"上次更新时间"必须刻在 doc 里. README "~72%" 没标 V0.16.14 时间, 用户/Plan
agent 误以为是当前数. V0.39.0 起所有性能/通过率数据**必带版本号 stamp** (e.g. "V0.39.0 96.8%, 30/31").

(累计真发现至 V0.39: 20 个; V0.39 系列 +1: #20.)

## 决策门槛兑现 (V0.34 教训第 9 次, 先写防 rationalize)

V0.39 决策门槛 (V0.38.0 同模式但更严):

| 提升 | 决策 |
|------|------|
| ≥ 10% | 实施保留 + 沉淀真发现 |
| 5-10% | 保留 + 标"边际收益" |
| **< 5%** | **withdraw 不实施** + 沉淀真发现 |

**当前提升空间 = 3.2% (1/31, fix WebDriver New)** → 严格按门槛 **< 5% withdraw**.

## V0.39 加固方向真值评估

| 候选 | V0.34.5 ROI 估 | 真测后空间 | 决策 |
|------|----------------|-----------|------|
| A. CDP-stealth 注入补 | 13% (依 72%) | 3.2% (依 96.8%) | **withdraw** (< 5%) |
| B. Chrome flags 加固 | "中 ROI" | 3.2% ceiling | **withdraw** (同) |
| C. fingerprint randomization | "scope wide" | 3.2% ceiling | **withdraw** (V0.30 时已推) |
| D. 真 Chrome binary 推荐 | 零代码文档 | 不动 src | **保留** (V0.39.4 retrospective 加 maintainer note) |

**V0.39.1+ 加固决策**: **不实施 G #1** (修 WebDriver (New)) — 真测推翻原 plan ROI 假设. V0.39
系列 reframe = 真发现 #20 沉淀 + 文档校正 + probe 改造 infra. 跟 V0.38.2 真测推翻 plan agent
估算后选 B simplification only 同模式 (但 V0.39 更彻底 — V0.38 实施完才发现, V0.39 实施前就发现).

## V0.39 系列 plan reframe (V0.38.3 推 5 commit, 真测后压到 2 commit)

| ver | 原 plan | reframe |
|-----|---------|---------|
| V0.39.0 (本) | baseline + decision | ✅ baseline + 真发现 #20 + 文档校正 (README/ARCHITECTURE) |
| V0.39.1 | G #1 实施 (CDP stealth 注入) | ~~实施~~ **withdraw** (< 5% 决策门槛触发) |
| V0.39.2 | G #2 实施 / V0.39.1 真测 | ~~~~ **跳** |
| V0.39.3 | 真测 after-G + 决策 | ~~~~ **跳** |
| V0.39.4 | 系列收尾 retrospective | **V0.39.1 系列收尾** (压缩 5→2 commit) |

跟 V0.32.1 / V0.33.4 / V0.35.1 / V0.36.2 / V0.37.4 deferred maintainer 同 SemVer 跳号但
**原因不同** — 此次跳因 ROI 决策门槛触发 (< 5%), 非 maintainer 红线.

## V0.34 教训进化轨迹累计 V0.39 (9 系列)

V0.34 教训系统进化: 被动 catch → 主动验证 → 系统预测 → **基于真测决策门槛即时 withdraw**

| 系列 | 教训应用模式 |
|------|-------------|
| V0.34 F1 | 真测被动 catch Plan agent 估算错 |
| V0.35 A | fixture 选型时主动 micro experiment |
| V0.36 I | 现状叙事主动推翻 (du 真测) |
| V0.37 B' | infra 准备 (--dry-run 防意外烧 token) |
| V0.38 F2 | retrospective 预测对, plan agent 仍重蹈 |
| **V0.39 G** | **baseline 真测**触发 decision 门槛**即时 withdraw**, 比 V0.38 早一步 (V0.38 实施完才发现, V0.39 实施前) |

V0.34 教训进化已成熟到"实施前 micro experiment 即时 withdraw 不上心力" — 8 个系列累计沉淀的
方法论真起作用.

## V0.39 系列收尾 plan (V0.39.1)

V0.39.1 retrospective 收尾, 含:
- 系列回顾 (2 commit autonomous)
- 真发现 #20 沉淀 (README 24 months stale)
- V0.34 教训第 9 次应用 (即时 withdraw, 比 V0.38 更早)
- "文档数值必带版本号 stamp" 制度化建议
- 真 Chrome binary 推荐 maintainer note (零代码)
- V0.40 主题候选 inventory (留 user)

## V0.34 教训进化引文 (V0.39 起强制)

> 性能/通过率数据 doc 化时**必带版本号 + 真测日期 stamp** (e.g. "V0.39.0 96.8%, 30/31, 2026-05-11"),
> 防 plan agent / 未来 Claude 引旧数据猜 ROI. V0.39 起所有 stealth / perceiver / token 数据 doc
> 引用都套此规则.
