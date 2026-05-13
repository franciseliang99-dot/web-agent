"""V0.66.3 OpenRouter Qwen3-VL-32B-Instruct vision unblock smoke.

验 V0.65 DeepSeek 400 'image_url' → V0.66.3 切 Qwen3-VL 后 vision pipeline alive.
顺带量 plan_elapsed_s wallclock baseline (V0.66.2 OpenRouter/Qwen 当前无数据点).
"""

from __future__ import annotations

import os
import time
from collections import deque

import pytest

from tests._smoke_helpers import (
    TINY_GRAY_PNG_B64,
    assert_smoke_action,
    smoke_skip_marker,
)

_OR_BASE_URL = "https://openrouter.ai/api/v1"
_OR_MODEL = "qwen/qwen3-vl-32b-instruct"

pytestmark = smoke_skip_marker(
    env_var="OPENAI_API_KEY",
    cassette_subdir="test_smoke_openrouter_qwen3vl_real",
    label="OpenRouter Qwen3-VL-32B",
    blocker_env=("OPENAI_BASE_URL", "openrouter.ai"),
)


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_qwen3vl_plan_smoke_pipeline_alive(capsys):
    from web_agent.llm.openai import OpenAIClient
    from web_agent.perceiver import Mark
    from web_agent.trace import Trace

    if not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "sk-or-cassette-replay-not-real"

    client = OpenAIClient(base_url=_OR_BASE_URL, model=_OR_MODEL)
    dummy_mark = Mark(
        id=1,
        tag="button",
        role="button",
        text="搜索",
        bbox={"x": 0, "y": 0, "w": 50, "h": 20},
    )
    trace = Trace(task_id="smoke-qwen3vl", goal="点击搜索按钮", steps=deque())

    t0 = time.perf_counter()
    action = await client.plan(
        goal="请点击 mark_id=1 的搜索按钮",
        screenshot_b64=TINY_GRAY_PNG_B64,
        marks=[dummy_mark],
        trace=trace,
    )
    elapsed = time.perf_counter() - t0

    assert_smoke_action(action)
    usage = getattr(client, "last_usage", None)
    with capsys.disabled():
        print(
            f"\n[V0.66.3 baseline] qwen3-vl-32b plan_elapsed_s={elapsed:.2f}s "
            f"action={action.type} thought={action.thought[:60]!r} "
            f"usage_in={getattr(usage, 'input_tokens', '?')} "
            f"usage_out={getattr(usage, 'output_tokens', '?')}"
        )
