# Contributing to web-agent

欢迎 PR / Issue / 想法。本项目是个人 maintain 的 web agent 探索, 优先收 (1) bug fix (2) 新 demo (3) 反检测 / 规划层的 spike 实证 + 落档 PR。

## Dev Setup

```bash
git clone https://github.com/franciseliang99-dot/web-agent.git
cd web-agent
uv sync
uv run playwright install chromium
cp .env.example .env
# 编辑 .env: ANTHROPIC_API_KEY=sk-ant-xxx
```

## 跑测试 (3 层 release gate)

```bash
uv run pytest         # 751 passed + 18 skipped 应全绿 (V0.34.0)
uv run ruff check     # 0 errors
uv run mypy           # 0 errors (strict, files=src/web_agent)
```

PR 必须 3 层全绿才合并。GitHub Actions CI 自动跑 (`.github/workflows/ci.yml`)。

## Commit 风格

按 [Conventional Commits](https://www.conventionalcommits.org/) 简化:

- `feat(V0.X.Y): 一句话主题` — 新功能 / milestone 推进
- `fix(V0.X.Y): 一句话主题` — bug fix
- `refactor(V0.X.Y): /simplify pass | 主题` — 重构, 不改功能
- `doc(V0.X.Y): 主题` — 仅文档
- `chore: 主题` — 元数据 / 配置 (e.g. uv.lock sync)
- `verify(V0.X.Y): 主题` — 真账号 / 真环境实测

CHANGELOG + 版本 bump 与代码改动**搭车进同一 commit**。

## 代码风格

- mypy strict mode, 0 errors (`files=["src/web_agent"]`, 不查 tests/ demos/)
- ruff `line-length = 110`, `target-version = "py312"`
- Python 3.12+ 特性 (TypedDict / `X | None` syntax / NotRequired)
- 解耦: domain ← ports ← 业务 ← 组合根, 跨层走事件 / 接口
- 注释: 写**为什么** (WHY), 不写**做什么** (WHAT, 命名清楚就够)

## PR 流程

1. Fork repo + branch from `main`
2. 改完跑 release gate 全绿 (`uv run pytest && uv run ruff check && uv run mypy`)
3. PR 描述说明:
   - 改了什么 / 为什么 / 怎么测
   - 链接 issue (如有)
   - CHANGELOG entry (如改动 ≥30 行 / 加新 helper / 引入抽象)
4. CI 自动跑, 全绿即可 review 合并

## Spike / 决策落档习惯

如果你跑了 reproducible 的 spike (反检测 / LLM 路线 / 规划层等), **强烈鼓励**:

1. 写 PR 同时落档 `docs/ARCHITECTURE.md §1.X`: spike 命令 + 数据 + 决策 (NO-GO / DEFER / GO)
2. 触发条件如有, 显式列出 (e.g. "若未来 X 满足才重评估")
3. 与已有 NO-GO/DEFER 落档 (patchright / curl_cffi / W5-C.2) 同模式

例: V0.16.16-22 的 7 版本 W5-C.2 spike 闭环 → ARCHITECTURE §1.5 维持 DEFER + 真 verdict 数据。

## 报 bug

[GitHub Issues](https://github.com/franciseliang99-dot/web-agent/issues), 含:

- 跑的命令 + 完整 stderr (logger 输出)
- Python / Chrome / OS 版本 (`python --version` / `google-chrome --version` / `uname -a`)
- 是否 V0.16.19 auto-spawn 路径还是手启 Chrome
- LLM provider 与 model
- 复现步骤 (5 步内能复现优先看)

## 联系

- Issues: 优先
- Twitter / X: TBD
- Email: 不公开 (走 Issues 或 Discussions)
