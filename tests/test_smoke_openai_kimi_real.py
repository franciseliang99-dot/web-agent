"""V0.15.4 W5-E real LLM smoke (OpenAI SDK + Moonshot/Kimi 端点) — 真 OpenAI SDK 调用 + cassette 回放。

设计意图同 `test_smoke_anthropic_real.py`: 验证 plan() pipeline 走通, 不验行为正确。

**与 Anthropic smoke 的关键差异 (subagent 审核反馈)**:
- Kimi 走 `tool_choice="auto"` (Moonshot 不支持 "required"), 16×16 灰图 + 空 marks 时
  Kimi 大概率不吐 tool_call → `OpenAIClient.plan` 第 99-102 行抛 RuntimeError, smoke 永远红
- 解决: 给一个 dummy Mark(id=1, role="button", text="搜索") + 明确 prompt "click mark_id=1",
  让 Kimi 在 thinking-disabled + tool_choice=auto 下大概率会 emit tool_call

**hardcode base_url + model 的原因**: cassette vcr 默认 match `[method,scheme,host,port,path]`,
跨端点 (api.moonshot.ai vs api.moonshot.cn) 不能 replay; 本 smoke 只录国际版。
demo 走 env 是 demo 的事, smoke 不复用 env, 保 cassette 跨用户可 replay。

运行模式 3 选 1:
1. **首次录制 (用户接手, 1 次)**: 提供 Moonshot 国际版 OPENAI_API_KEY (sk-xxx) 跑
   `pytest tests/test_smoke_openai_kimi_real.py --record-mode=once`
2. **后续 replay (CI/任何人, 无 key)**: 默认 `pytest` 直接读 cassette
3. **当前骨架状态 (无 cassette 无 key)**: 整文件 skip, 不阻塞主 219 tests

成本估算 (录一次): kimi-k2.6, ~3k input + 200 output, cache miss ≈ $0.004。
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path

import pytest

# Kimi 国际版 (cassette host 锁; 国内版 .cn 录的不能跨端点 replay)
_KIMI_BASE_URL = "https://api.moonshot.ai/v1"
_KIMI_MODEL = "kimi-k2.6"

# ---- skip 守卫 ----
_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "test_smoke_openai_kimi_real"
_HAS_CASSETTE = _CASSETTE_DIR.exists() and any(_CASSETTE_DIR.glob("*.yaml"))
_HAS_KEY = bool(os.environ.get("OPENAI_API_KEY"))
_SHOULD_SKIP = not _HAS_CASSETTE and not _HAS_KEY

pytestmark = pytest.mark.skipif(
    _SHOULD_SKIP,
    reason="real Kimi smoke skeleton: 既无 cassette 也无 OPENAI_API_KEY (Moonshot 国际版 sk-xxx) — "
    "首次录制请 export OPENAI_API_KEY 后跑 --record-mode=once",
)


# 16×16 灰 PNG (复用 Anthropic smoke 同常量, 节约 cassette body 体积)
_GRAY_16X16_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAGUlEQVR4nGNsaGhgIAUwkaR6VMOoh"
    "iGlAQDJTAGgLgFHggAAAABJRU5ErkJggg=="
)


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_kimi_plan_smoke_pipeline_alive():
    """smoke = pipeline alive, NOT behavior correctness.

    Kimi 比 Anthropic smoke 多一个 dummy Mark + 明确 prompt, 防 thinking-disabled +
    tool_choice=auto 模式下 Kimi 不吐 tool_call (会让 OpenAIClient 抛 RuntimeError).
    """
    from web_agent.llm.base import Action
    from web_agent.llm.openai import OpenAIClient
    from web_agent.perceiver import Mark
    from web_agent.trace import Trace

    # 无 key 但有 cassette: 注入 dummy 让 OpenAIClient.__init__ 通过 (vcr 拦下出站请求, 不真用)
    if not _HAS_KEY:
        os.environ["OPENAI_API_KEY"] = "sk-kimi-cassette-replay-not-real"

    client = OpenAIClient(
        base_url=_KIMI_BASE_URL,
        model=_KIMI_MODEL,
    )
    # dummy Mark: 让 Kimi 有明确点击目标; SoM 编号 1, role=button, 防空 marks 下 Kimi 没机会 emit tool_call
    dummy_mark = Mark(
        id=1,
        tag="button",
        role="button",
        text="搜索",
        bbox={"x": 0, "y": 0, "w": 50, "h": 20},
    )
    trace = Trace(task_id="smoke-kimi-real", goal="点击搜索按钮", steps=deque())
    action = await client.plan(
        goal="请点击 mark_id=1 的搜索按钮",  # 明确指向 dummy_mark, 高概率回 click
        screenshot_b64=_GRAY_16X16_PNG_B64,
        marks=[dummy_mark],
        trace=trace,
    )

    assert isinstance(action, Action), f"plan() 应返 Action dataclass, got {type(action)!r}"
    assert action.type in {"click", "type", "scroll", "extract", "done"}, \
        f"action.type 必须是 5 合法值之一, got {action.type!r}"
    assert isinstance(action.args, dict)
    assert isinstance(action.thought, str)
