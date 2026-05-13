"""LLM vision-capability lookup（V0.66.3）。

web-agent 整个 domain 假设 LLM 支持 vision（SoM + screenshot）。在 make_client()
构造前 fail-fast，避免构造一个跑不动的 client 后第一次 chat() 才 400。

查表归一: model 先 lower+strip, 再剥已知 OpenRouter vendor 前缀
(`anthropic/`, `openai/`, `google/`, `qwen/`, `moonshotai/`, `deepseek/`),
让 `gpt-4o` 和 `openai/gpt-4o` 走同一条前缀, 避免维护两份。

黑名单优先于白名单：`qwen3-instruct` 在黑名单里, `qwen3-vl-` 在白名单里,
查 `qwen3-vl-32b-instruct` 时白名单命中; 查 `qwen3-instruct` 时黑名单先命中。
"""

from __future__ import annotations

import warnings

# OpenRouter 风格 vendor 前缀, 与 provider_from_model() 的 openrouter_map 对齐。
# 改这里时同步改 __init__.py 的 openrouter_map (反过来也是)。
_VENDOR_PREFIXES: tuple[str, ...] = (
    "anthropic/",
    "openai/",
    "google/",
    "gemini/",
    "qwen/",
    "moonshotai/",
    "deepseek/",
)

VISION_INCAPABLE_PREFIXES: tuple[str, ...] = (
    # DeepSeek 全系无 vision (chat, reasoner, v4-flash, v4-pro, r1)
    "deepseek-",
    # OpenAI o1-mini / gpt-3.5 text-only
    "o1-mini",
    "gpt-3.5",
    # Qwen text-only variants (turbo / plus / max / 3-instruct)
    "qwen-turbo",
    "qwen-plus",
    "qwen-max",
    "qwen3-instruct",
    # 老 haiku 无 vision (3-haiku-20240307 之前的 SKU)
    "claude-3-haiku-20240307",
)

VISION_CAPABLE_PREFIXES: tuple[str, ...] = (
    # Anthropic Claude 3.5+/4.x 全 vision
    "claude-",
    # OpenAI multi-modal SKUs
    "gpt-4o",
    "gpt-4.1",
    "gpt-4-vision",
    "gpt-5",
    "o1",
    "o3",
    "o4",
    # Gemini
    "gemini-",
    # Kimi / Moonshot
    "kimi-",
    "moonshot-",
    # Qwen vision variants
    "qwen3-vl-",
    "qwen2.5-vl-",
    "qwen-vl-",
)

_SUGGESTED_ALTERNATIVES = (
    "gpt-4o-mini",
    "claude-sonnet-4.6",
    "kimi-k2.6",
    "qwen3-vl-32b-instruct",
)


def _strip_vendor(model: str) -> str:
    """剥 OpenRouter `vendor/` 前缀, 让 `openai/gpt-4o` 与 `gpt-4o` 走同一表查。"""
    for v in _VENDOR_PREFIXES:
        if model.startswith(v):
            return model[len(v):]
    return model


def is_vision_capable(model: str) -> bool:
    """查 model 是否支持 vision input (image_url / image block)。

    未知 model 默认 True + UserWarning, 避免锁死新发布的 model。
    """
    m = _strip_vendor(model.lower().strip())
    if any(m.startswith(p) for p in VISION_INCAPABLE_PREFIXES):
        return False
    if any(m.startswith(p) for p in VISION_CAPABLE_PREFIXES):
        return True
    warnings.warn(
        f"vision capability of {model!r} is unknown; defaulting to True. "
        f"如确认不支持 vision 请在 _capabilities.VISION_INCAPABLE_PREFIXES 加前缀。",
        UserWarning,
        stacklevel=2,
    )
    return True


def assert_vision_capable(provider: str, model: str) -> None:
    """Vision-required guard for web-agent. 不支持 raise RuntimeError 含 actionable hint."""
    if is_vision_capable(model):
        return
    alts = " / ".join(_SUGGESTED_ALTERNATIVES)
    raise RuntimeError(
        f"{provider}/{model} 不支持 vision input, web-agent 需要 vision (SoM + screenshot). "
        f"请切换支持 vision 的 model: {alts}. "
        f"详见 src/web_agent/llm/_capabilities.py."
    )
