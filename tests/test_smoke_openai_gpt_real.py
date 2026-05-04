"""V0.15.8 W5-E real OpenAI GPT smoke (api.openai.com + gpt-5.5 路径).

OpenAI SDK + 默认公网端点. GPT-5.x 用 `tool_choice="required"` 强制 tool_use,
空 marks 也能 PASS (与 Kimi auto 模式不同, 与 Anthropic any 模式同).

env var 与 Kimi smoke 同名 OPENAI_API_KEY (都走 OpenAI SDK), 但 key 来源不同 —
GPT 要 platform.openai.com 的 sk-..., 不与 Moonshot 国内版互通. skip_marker 加
blocker_env=("OPENAI_BASE_URL", "openai.com") 防 .env 配 moonshot.cn 主体跑 Kimi
时, GPT smoke 错路由到 Moonshot 录到 404 cassette.

首次录制 (用户接手, 1 次):
   OPENAI_BASE_URL=https://api.openai.com/v1 OPENAI_API_KEY=sk-真OpenAI \
     uv run pytest tests/test_smoke_openai_gpt_real.py --record-mode=once

单录成本: gpt-5.5 vision ~1100 input + 150 output ≈ $0.005-$0.01.
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

_GPT_BASE_URL = "https://api.openai.com/v1"
_GPT_MODEL = "gpt-5.5"

pytestmark = smoke_skip_marker(
    env_var="OPENAI_API_KEY",
    cassette_subdir="test_smoke_openai_gpt_real",
    label="OpenAI GPT (api.openai.com)",
    blocker_env=("OPENAI_BASE_URL", "openai.com"),
)


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_gpt_plan_smoke_pipeline_alive():
    from web_agent.llm.openai import OpenAIClient
    from web_agent.trace import Trace

    os.environ.setdefault("OPENAI_API_KEY", "sk-gpt-cassette-replay-not-real")

    # 显式传 base_url 防 OPENAI_BASE_URL env (用户主体配 moonshot.cn) 劫持请求
    client = OpenAIClient(base_url=_GPT_BASE_URL, model=_GPT_MODEL)
    trace = Trace(task_id="smoke-gpt-real", goal="搜苹果价格", steps=deque())
    action = await client.plan(
        goal="搜苹果价格",
        screenshot_b64=TINY_GRAY_PNG_B64,
        marks=[],  # GPT-5.x tool_choice="required" 强制 emit tool, 空 marks 可 PASS
        trace=trace,
    )
    assert_smoke_action(action)
