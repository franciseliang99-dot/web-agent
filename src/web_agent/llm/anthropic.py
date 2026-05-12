"""Anthropic Claude client：vision + prompt caching + tool-use。

实现 LLMClient Protocol。支持通过 ANTHROPIC_BASE_URL 走第三方代理（OpenRouter Anthropic skin / 自部署 LiteLLM）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from anthropic import AsyncAnthropic

if TYPE_CHECKING:
    from web_agent.vault import SecretStore
from anthropic.types import (
    MessageParam,
    TextBlockParam,
    ToolChoiceAnyParam,
    ToolParam,
)

from web_agent.llm._schema import SYSTEM_PROMPT, build_user_text, to_anthropic_tools
from web_agent.trace import Trace
from web_agent.types import Action, Mark, Usage, action_from_tool_call

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicClient:
    """实现 LLMClient Protocol。"""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
        secret_store: "SecretStore | None" = None,
    ) -> None:
        # V0.27.1: secret_store 注入让 anthropic 不再硬 import os.environ; None → EnvSecretStore
        # 默 backend (跟现有 .env loading 100% 兼容). V0.28 加 keyring backend 时 0 改本类.
        from web_agent.vault import default_store as _default_secret_store
        store = secret_store or _default_secret_store()
        api_key = api_key or store.get("ANTHROPIC_API_KEY")
        if not api_key:
            from web_agent.vault import MissingSecretError
            raise MissingSecretError("ANTHROPIC_API_KEY")
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 4, "timeout": 120.0}
        base_url = base_url or store.get("ANTHROPIC_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)
        self.model = model
        self._tools = to_anthropic_tools()
        self.last_usage: Usage | None = None  # V0.26.2: eval/runner 累加用

    async def plan(
        self,
        goal: str,
        screenshot_b64: str,
        marks: list[Mark],
        trace: Trace,
        *,
        tabs: list[tuple[int, str]] | None = None,
        current_idx: int = 0,
        cross_origin_hosts: list[str] | None = None,
    ) -> Action:
        # V0.33.3: media_type 跟 perceiver 截图格式一致 (env `WEB_AGENT_SCREENSHOT_FORMAT=webp` 切 WebP).
        # Anthropic vision 原生支持 png/jpeg/gif/webp 4 种.
        from web_agent.perceiver import current_screenshot_format
        _media_type = f"image/{current_screenshot_format()}"
        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _media_type,
                    "data": screenshot_b64,
                },
            },
            {"type": "text", "text": build_user_text(
                goal, marks, trace,
                tabs=tabs, current_idx=current_idx,
                cross_origin_hosts=cross_origin_hosts,
            )},
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

        # V0.26.2 + V0.42.0: 记 token usage 让 eval/runner 累加 cost (含 cache_creation/read).
        # Anthropic SDK Usage SDK getattr (default 0 兼容老 SDK / 无 cache 路径).
        self.last_usage = Usage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cache_creation_input_tokens=getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        )
        for block in resp.content:
            if block.type == "tool_use":
                # V0.17.0: action_from_tool_call dispatch 到 5 dataclass union, 删 cast(dict[str, Any])
                return action_from_tool_call(block.name, dict(block.input))

        raise RuntimeError(f"Anthropic 没返回 tool_use: {resp.content!r}")

    async def reflect(self, prompt: str) -> str:
        """V0.28.1: W6-A 失败反思 — 单次 raw text completion (无 tools / 无 image / 无 cache_control).

        max_tokens=512 (反思 root_cause + hint 1-2 句够用); 不带 system prompt (反思 prompt 自含
        指令); 不带 cache (反思一次性 cache 命中率 0); 不更 self.last_usage (V0.28.3 再单独算).
        """
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=512,
            messages=cast(
                list[MessageParam],
                [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            ),
        )
        for block in resp.content:
            if block.type == "text":
                return block.text
        raise RuntimeError(f"Anthropic reflect 没返 text block: {resp.content!r}")
