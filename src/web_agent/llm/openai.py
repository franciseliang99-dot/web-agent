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
from typing import TYPE_CHECKING, Any

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from web_agent.vault import SecretStore

from web_agent.llm._schema import SYSTEM_PROMPT, build_user_text, to_openai_tools
from web_agent.trace import Trace
from web_agent.types import Action, Mark, Usage, action_from_tool_call

DEFAULT_MODEL = "gpt-5.5"  # 2026-04-24 release，vision-capable；用户可 override


class OpenAIClient:
    """实现 LLMClient Protocol。"""

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
        secret_store: "SecretStore | None" = None,
    ) -> None:
        # V0.27.1: secret_store 注入跟 anthropic.py 同模式. None → EnvSecretStore 默 backend.
        from web_agent.vault import default_store as _default_secret_store
        store = secret_store or _default_secret_store()
        api_key = api_key or store.get("OPENAI_API_KEY")
        if not api_key:
            from web_agent.vault import MissingSecretError
            raise MissingSecretError("OPENAI_API_KEY")
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 4, "timeout": 120.0}
        base_url = base_url or store.get("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)
        self.model = model
        self._tools = to_openai_tools(strict=True)
        # Kimi (Moonshot) OpenAI-compat 端点不支持 tool_choice="required" + 不识 max_completion_tokens
        self._is_kimi = bool(base_url and "moonshot" in base_url.lower())
        # V0.66.4: OpenRouter 透传上游 (Qwen3-VL/Claude/GPT/...), 大多不 honor tool_choice="required"
        # — 实测 qwen/qwen3-vl-32b-instruct 直接 404. 跟 Kimi 同 quirks: auto + max_tokens 旧 alias.
        # 不加 extra_body thinking-disabled (那是 Moonshot 专有, OpenRouter 上游不一定识别).
        self._is_openrouter = bool(base_url and "openrouter.ai" in base_url.lower())
        # V0.26.4: Kimi 显式标 "openai-kimi" 让 eval metrics report 区分 GPT vs Kimi
        # (V0.21.2 plan F 节已用此标记). instance attribute 覆盖 class attribute.
        if self._is_kimi:
            self.name = "openai-kimi"
        elif self._is_openrouter:
            self.name = "openai-openrouter"
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
        # V0.33.3: data URI mime 跟 perceiver 截图格式一致 (env `WEB_AGENT_SCREENSHOT_FORMAT=webp` 切 WebP).
        # OpenAI vision 原生支持 png/jpeg/gif/webp; data URL scheme 无关 OpenAI Kimi/Moonshot 兼容层.
        from web_agent.perceiver import current_screenshot_format
        _mime = f"image/{current_screenshot_format()}"
        # V0.66.6 (Path A — V0.66.5 ticket 假说 2 验证): WEB_AGENT_VISION_DETAIL env var
        # opt-in 切 "low" 给真 task wallclock 实测; default "high" 保 V0.66.4 SoM 识别红线.
        # 非法值 (typo / future variant) → fallback "high" 防 OpenAI 400.
        _detail = os.environ.get("WEB_AGENT_VISION_DETAIL", "high").lower().strip()
        if _detail not in ("low", "high", "auto"):
            _detail = "high"
        user_content: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{_mime};base64,{screenshot_b64}",
                    "detail": _detail,
                },
            },
            {"type": "text", "text": build_user_text(
                goal, marks, trace,
                tabs=tabs, current_idx=current_idx,
                cross_origin_hosts=cross_origin_hosts,
            )},
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "tools": self._tools,
        }
        if self._is_kimi or self._is_openrouter:
            # Kimi: K2.6/K2.5 默认开 thinking mode, reasoning_content 吃光 max_tokens 不吐 tool_call,
            # 且不识 "required". OpenRouter: 上游 (Qwen 等) 普遍不支持 "required" → 404.
            # 共享 auto + max_tokens 兼容路径; extra_body thinking-disabled 仅 Kimi 加 (Moonshot 专有).
            kwargs["max_tokens"] = 4096
            kwargs["tool_choice"] = "auto"
            if self._is_kimi:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        else:
            kwargs["max_completion_tokens"] = 2048
            kwargs["tool_choice"] = "required"
        resp = await self._client.chat.completions.create(**kwargs)

        # V0.26.2 + V0.42.0: 记 token usage (OpenAI / Kimi schema: prompt_tokens/completion_tokens).
        # Kimi extra_body thinking 模式 usage 仍存在 — 必查 hasattr 防边界 None.
        # V0.42.0 cache_read 从 prompt_tokens_details.cached_tokens (OpenAI/Kimi 自动 cache).
        # OpenAI 无 cache_creation 概念 (auto cache, 不分 first-write), creation 永 0.
        if resp.usage is not None:
            cached = 0
            details = getattr(resp.usage, "prompt_tokens_details", None)
            if details is not None:
                cached = getattr(details, "cached_tokens", 0) or 0
            self.last_usage = Usage(
                input_tokens=resp.usage.prompt_tokens,
                output_tokens=resp.usage.completion_tokens,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=cached,
            )

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
        # V0.17.0: action_from_tool_call dispatch 到 5 dataclass union, 删 cast(dict[str, Any])
        return action_from_tool_call(call.function.name, json.loads(call.function.arguments))

    async def reflect(self, prompt: str) -> str:
        """V0.28.1: W6-A 失败反思 — 单次 raw text completion (无 tools / 无 image / 无 system).

        max_tokens=512 (反思 root_cause + hint 1-2 句够); Kimi 也不带 thinking_disabled 因为
        反思场景 thinking 反而帮助 (复杂 trace 分析); 不更 self.last_usage.
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._is_kimi or self._is_openrouter:
            kwargs["max_tokens"] = 512
        else:
            kwargs["max_completion_tokens"] = 512
        resp = await self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError(f"{self.name}({self.model}) reflect 没返 content: {resp!r}")
        return str(content)
