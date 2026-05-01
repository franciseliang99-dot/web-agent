"""OpenAI GPT client：vision + tool-use (strict mode)。

实现 LLMClient Protocol。支持 OPENAI_BASE_URL 走第三方代理（OpenRouter OpenAI skin / 自部署 LiteLLM / Azure OpenAI）。

注：OpenAI prompt caching 是自动的（≥1024 token 前缀匹配），无需显式 cache_control。
"""

from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from web_agent.llm._schema import SYSTEM_PROMPT, to_openai_tools
from web_agent.llm.base import Action
from web_agent.perceiver import Mark, marks_to_text
from web_agent.trace import Trace

DEFAULT_MODEL = "gpt-5.5"  # 2026-04-24 release，vision-capable；用户可 override


class OpenAIClient:
    """实现 LLMClient Protocol。"""

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY 未设置 — 请填 .env 或 export 环境变量"
            )
        kwargs: dict = {"api_key": api_key}
        base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)
        self.model = model
        self._tools = to_openai_tools(strict=True)

    async def plan(
        self,
        goal: str,
        screenshot_b64: str,
        marks: list[Mark],
        trace: Trace,
    ) -> Action:
        history_text = (
            json.dumps(trace.for_llm(), ensure_ascii=False, indent=2)
            if trace.steps
            else "(空)"
        )
        user_content: list[dict] = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{screenshot_b64}",
                    "detail": "high",  # 'low' 省 token 但 SoM 编号易看不清；'high' 更稳
                },
            },
            {
                "type": "text",
                "text": (
                    f"# 任务目标\n{goal}\n\n"
                    f"# 历史 Action Trace\n{history_text}\n\n"
                    f"# 当前可交互元素清单（编号对应截图边框）\n{marks_to_text(marks)}\n\n"
                    f"请通过 tool 返回下一步操作。"
                ),
            },
        ]

        resp = await self._client.chat.completions.create(
            model=self.model,
            max_completion_tokens=2048,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            tools=self._tools,
            tool_choice="required",
        )

        msg = resp.choices[0].message
        if not msg.tool_calls:
            raise RuntimeError(f"OpenAI 没返回 tool_call: {msg!r}")
        call = msg.tool_calls[0]
        args = json.loads(call.function.arguments)
        thought = args.pop("thought", "")
        return Action(type=call.function.name, args=args, thought=thought)
