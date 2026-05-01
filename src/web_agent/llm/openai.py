"""OpenAI GPT client：vision + tool-use (strict mode)。

实现 LLMClient Protocol。支持 OPENAI_BASE_URL 走第三方代理（OpenRouter OpenAI skin / 自部署 LiteLLM / Azure OpenAI）。

兼容补丁：检测到 base_url 含 "moonshot"（Kimi 国际/国内端点）时，自动：
- `max_completion_tokens` → `max_tokens`（Kimi 不识 GPT-5.x 新参数名）
- `tool_choice="required"` → `tool_choice="auto"`（Kimi 不支持 required，会拒）
- 加 `extra_body={"thinking": {"type": "disabled"}}` 关 thinking 模式（K2.6/K2.5 默认开）；
  Moonshot 官方对 tool-heavy agent flow 推荐关 thinking（reasoning_content 会吃光 max_tokens）

注：OpenAI prompt caching 是自动的（≥1024 token 前缀匹配），无需显式 cache_control；
Kimi 也是自动 cache，命中后 ~6× 折扣。
"""

from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from web_agent.llm._schema import SYSTEM_PROMPT, build_user_text, to_openai_tools
from web_agent.llm.base import Action
from web_agent.perceiver import Mark
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
        kwargs: dict = {"api_key": api_key, "max_retries": 4, "timeout": 120.0}
        base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)
        self.model = model
        self._tools = to_openai_tools(strict=True)
        # Kimi (Moonshot) OpenAI-compat 端点不支持 tool_choice="required" + 不识 max_completion_tokens
        self._is_kimi = bool(base_url and "moonshot" in base_url.lower())

    async def plan(
        self,
        goal: str,
        screenshot_b64: str,
        marks: list[Mark],
        trace: Trace,
    ) -> Action:
        user_content: list[dict] = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{screenshot_b64}",
                    "detail": "high",  # 'low' 省 token 但 SoM 编号易看不清；'high' 更稳
                },
            },
            {"type": "text", "text": build_user_text(goal, marks, trace)},
        ]

        kwargs: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "tools": self._tools,
        }
        if self._is_kimi:
            # Kimi K2.6/K2.5 默认开 thinking mode，reasoning_content 会吃光 max_tokens 导致没机会
            # emit tool_call。Moonshot 官方对 tool-heavy agent flow 推荐关 thinking。
            kwargs["max_tokens"] = 4096
            kwargs["tool_choice"] = "auto"
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        else:
            kwargs["max_completion_tokens"] = 2048
            kwargs["tool_choice"] = "required"
        resp = await self._client.chat.completions.create(**kwargs)

        msg = resp.choices[0].message
        if not msg.tool_calls:
            # Kimi thinking 模式下偶尔 reasoning 占满 token 没吐 tool_call。
            # 用 reasoning_content / content 作为提示信息抛 RuntimeError 让 loop 重试或上抛。
            reasoning = getattr(msg, "reasoning_content", None) or ""
            preview = (reasoning or msg.content or "").strip()[:300]
            raise RuntimeError(
                f"{self.name}({self.model}) 没返回 tool_call（可能 thinking 占满 max_tokens）。"
                f"reasoning/content 预览: {preview!r}"
            )
        call = msg.tool_calls[0]
        args = json.loads(call.function.arguments)
        thought = args.pop("thought", "")
        return Action(type=call.function.name, args=args, thought=thought)
