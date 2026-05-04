"""V0.15.5 W5-E real Kimi smoke (V0.15.8 接 _smoke_helpers 去重).

OpenAI SDK + Moonshot 国内版 .cn 端点. Kimi tool_choice="auto" + 空 marks 大概率
不吐 tool_call → 加 dummy Mark 让 LLM 有明确目标. 详细说明见 _smoke_helpers.py.

V0.15.7 cassette 真录通 (HTTP 200, REDACTED=8, key 反查 0). 单录: ¥0.03 (~$0.004).
hardcode .cn: cassette vcr URL match 锁 host, 跨端点 (.ai vs .cn) 不能 replay.
"""

from __future__ import annotations

from collections import deque

import pytest

from tests._smoke_helpers import (
    TINY_GRAY_PNG_B64,
    assert_smoke_action,
    ensure_dummy_key,
    smoke_skip_marker,
)

_KIMI_BASE_URL = "https://api.moonshot.cn/v1"
_KIMI_MODEL = "kimi-k2.6"

pytestmark = smoke_skip_marker(
    env_var="OPENAI_API_KEY",
    cassette_subdir="test_smoke_openai_kimi_real",
    label="Kimi 国内版 .cn",
)


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_kimi_plan_smoke_pipeline_alive():
    from web_agent.llm.base import Action
    from web_agent.llm.openai import OpenAIClient
    from web_agent.perceiver import Mark
    from web_agent.trace import Trace

    ensure_dummy_key("OPENAI_API_KEY", "sk-kimi-cassette-replay-not-real")

    client = OpenAIClient(base_url=_KIMI_BASE_URL, model=_KIMI_MODEL)
    # dummy Mark: tool_choice="auto" + 空 marks 易不吐 tool_call, 给明确点击目标
    dummy_mark = Mark(
        id=1,
        tag="button",
        role="button",
        text="搜索",
        bbox={"x": 0, "y": 0, "w": 50, "h": 20},
    )
    trace = Trace(task_id="smoke-kimi-real", goal="点击搜索按钮", steps=deque())
    action = await client.plan(
        goal="请点击 mark_id=1 的搜索按钮",
        screenshot_b64=TINY_GRAY_PNG_B64,
        marks=[dummy_mark],
        trace=trace,
    )
    assert_smoke_action(action, Action)
