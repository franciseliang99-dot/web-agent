"""Anthropic Claude client：vision + prompt caching + tool-use。

实现 LLMClient Protocol。支持通过 ANTHROPIC_BASE_URL 走第三方代理（OpenRouter Anthropic skin / 自部署 LiteLLM）。
"""

from __future__ import annotations

import os
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import (
    MessageParam,
    TextBlockParam,
    ToolChoiceAnyParam,
    ToolParam,
)

from web_agent.llm._schema import SYSTEM_PROMPT, build_user_text, to_anthropic_tools
from web_agent.trace import Trace
from web_agent.types import Action, Mark, action_from_tool_call

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicClient:
    """实现 LLMClient Protocol。"""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY 未设置 — 请填 .env 或 export 环境变量"
            )
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 4, "timeout": 120.0}
        base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)
        self.model = model
        self._tools = to_anthropic_tools()

    async def plan(
        self,
        goal: str,
        screenshot_b64: str,
        marks: list[Mark],
        trace: Trace,
    ) -> Action:
        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_b64,
                },
            },
            {"type": "text", "text": build_user_text(goal, marks, trace)},
        ]

        # V0.17.1: anthropic SDK TypedDict 直接 annotate, 替 4 处 cast(Any).
        # tools/messages 仍走 cast 因为 _schema/user_content 是 dict[str, Any] 中性结构.
        system: list[TextBlockParam] = [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        tool_choice: ToolChoiceAnyParam = {"type": "any"}
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            tools=cast(list[ToolParam], self._tools),
            tool_choice=tool_choice,
            messages=cast(list[MessageParam], [{"role": "user", "content": user_content}]),
        )

        for block in resp.content:
            if block.type == "tool_use":
                # V0.17.0: action_from_tool_call dispatch 到 5 dataclass union, 删 cast(dict[str, Any])
                return action_from_tool_call(block.name, dict(block.input))

        raise RuntimeError(f"Anthropic 没返回 tool_use: {resp.content!r}")
