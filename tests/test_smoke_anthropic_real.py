"""V0.15.3 W5-E real Anthropic smoke (V0.15.8 接 _smoke_helpers 去重).

设计意图: 验证 plan() pipeline 端到端走通, 而非验证行为正确性. 详细说明见
tests/_smoke_helpers.py. 单录成本 (claude-sonnet-4-6 vision): ~$0.006.

运行 3 模式 (同 Kimi smoke):
1. 首次录制: ANTHROPIC_API_KEY=sk-ant-... pytest --record-mode=once
2. replay: 默认 pytest 走 cassette
3. 骨架: 既无 cassette 也无 key → 整文件 skip
"""

from __future__ import annotations

import os
from collections import deque

import pytest

from tests._smoke_helpers import (
    TINY_GRAY_PNG_B64,
    assert_smoke_action,
    smoke_skip_marker,
)

pytestmark = smoke_skip_marker(
    env_var="ANTHROPIC_API_KEY",
    cassette_subdir="test_smoke_anthropic_real",
    label="Anthropic",
)


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_anthropic_plan_smoke_pipeline_alive():
    from web_agent.llm.anthropic import AnthropicClient
    from web_agent.trace import Trace

    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-cassette-replay-not-real")

    client = AnthropicClient()
    trace = Trace(task_id="smoke-real", goal="搜苹果价格", steps=deque())
    action = await client.plan(
        goal="搜苹果价格",
        screenshot_b64=TINY_GRAY_PNG_B64,
        marks=[],  # Anthropic tool_choice="any" 强制 emit tool, 空 marks 也能 PASS
        trace=trace,
    )
    assert_smoke_action(action)
