"""LLM 抽象层：跨 provider 的 plan() 接口 + factory。

公共 API：
    from web_agent.llm import LLMClient, Action, make_client

provider 选择优先级（参数 > env > 推断 > 默认）：
    1. make_client(provider=...) 显式参数
    2. WEB_AGENT_LLM_PROVIDER env
    3. model 名前缀推断（claude-* → anthropic, gpt-* / o[1-5]-* → openai, gemini-* → gemini）
    4. 默认 "anthropic"
"""

from __future__ import annotations

import os

from web_agent.llm.base import Action as Action, LLMClient as LLMClient


def provider_from_model(model: str) -> str:
    """按 model 名前缀推断 provider；不识别则返回 'anthropic'。

    OpenAI 兼容端点（Kimi / Moonshot / DeepSeek 等）走 'openai' provider，
    用户需配 OPENAI_BASE_URL 指向对应供应商的 v1 端点。OpenAIClient 会按
    base_url 自动检测 Kimi 兼容性补丁（max_tokens / tool_choice='auto'）。
    """
    m = model.lower().strip()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "o4", "o5")):
        return "openai"
    if m.startswith(("kimi", "moonshot")):
        return "openai"  # Kimi/Moonshot OpenAI compat 端点
    if m.startswith("gemini"):
        return "gemini"
    if "/" in m:  # OpenRouter 风格 "anthropic/claude-..." → 走对应 skin
        prefix = m.split("/", 1)[0]
        openrouter_map = {
            "anthropic": "anthropic",
            "openai": "openai",
            "moonshotai": "openai",  # OpenRouter 路径 "moonshotai/kimi-k2.6"
            "google": "gemini",
            "gemini": "gemini",
        }
        if prefix in openrouter_map:
            return openrouter_map[prefix]
    return "anthropic"


def make_client(
    provider: str | None = None,
    model: str | None = None,
) -> LLMClient:
    """按 env / 参数选 provider 并实例化对应 LLMClient。

    Raises:
        RuntimeError: provider 不支持 / 对应 SDK 未装 / 对应 API key 未设。
    """
    model = model or os.environ.get("WEB_AGENT_MODEL")
    provider = provider or os.environ.get("WEB_AGENT_LLM_PROVIDER")
    if provider is None:
        provider = provider_from_model(model) if model else "anthropic"
    provider = provider.lower().strip()

    if provider == "anthropic":
        from web_agent.llm.anthropic import DEFAULT_MODEL, AnthropicClient

        return AnthropicClient(model=model or DEFAULT_MODEL)

    if provider == "openai":
        try:
            from web_agent.llm.openai import DEFAULT_MODEL, OpenAIClient
        except ImportError as e:
            raise RuntimeError(
                "openai provider 需要 openai SDK：\n"
                "  uv sync --extra openai\n"
                "或安装时:\n"
                "  pip install 'web-agent[openai]'"
            ) from e

        return OpenAIClient(model=model or DEFAULT_MODEL)

    raise RuntimeError(
        f"未知 provider: {provider!r}（当前支持: anthropic, openai；"
        f"gemini 暂留扩展位未实现）"
    )


__all__ = ["LLMClient", "Action", "make_client", "provider_from_model"]
