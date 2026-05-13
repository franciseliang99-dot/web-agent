"""OpenAIClient init + tools 应用单测（不调真实 API）。

如果 openai SDK 未装（uv sync 不带 --extra openai），整个文件跳过。
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "openai",
    reason="openai SDK 未装：uv sync --extra openai 或 pip install 'web-agent[openai]'",
)

from web_agent.llm.openai import DEFAULT_MODEL, OpenAIClient  # noqa: E402


def test_openai_client_init_uses_env_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")
    # V0.26.4: 显式 delenv OPENAI_BASE_URL 防 .env 装 Kimi 时 _is_kimi=True 改 name="openai-kimi"
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    client = OpenAIClient()
    assert client.name == "openai"
    assert client.model == DEFAULT_MODEL
    assert len(client._tools) == 11
    for t in client._tools:
        assert t["type"] == "function"
        f = t["function"]
        assert f["strict"] is True
        assert f["parameters"]["additionalProperties"] is False


def test_openai_client_init_raises_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIClient()


def test_openai_client_respects_base_url_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    client = OpenAIClient()
    assert "openrouter.ai" in str(client._client.base_url)


def test_openai_client_explicit_model_override(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = OpenAIClient(model="gpt-4o")
    assert client.model == "gpt-4o"


def test_make_client_factory_picks_openai_by_provider_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("WEB_AGENT_LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)  # V0.26.4: 防 Kimi 改 name
    from web_agent.llm import make_client

    c = make_client()
    assert c.name == "openai"


def test_make_client_factory_picks_openai_by_model_prefix(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("WEB_AGENT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)  # V0.26.4: 防 Kimi 改 name
    from web_agent.llm import make_client

    c = make_client(model="gpt-4o")
    assert c.name == "openai"
    assert c.model == "gpt-4o"


def test_openai_client_kimi_name_is_openai_kimi(monkeypatch):
    """V0.26.4: base_url 含 moonshot → name 改 "openai-kimi" 让 eval metrics 区分 GPT vs Kimi."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.moonshot.cn/v1")
    client = OpenAIClient()
    assert client.name == "openai-kimi"
    assert client._is_kimi is True


def test_openai_client_non_kimi_non_openrouter_keeps_openai_name(monkeypatch):
    """V0.26.4 + V0.66.4: 非 Kimi 非 OpenRouter base_url (直连 OpenAI / DeepSeek)
    → name 仍 "openai" (类 attribute 默认). OpenRouter 在 V0.66.4 被分到 openai-openrouter."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    client = OpenAIClient()
    assert client.name == "openai"
    assert client._is_kimi is False
    assert client._is_openrouter is False


def test_provider_from_model_kimi_and_moonshot():
    """Kimi/Moonshot model 名前缀应推断到 openai（走 OpenAIClient + base_url）。"""
    from web_agent.llm import provider_from_model

    for m in [
        "kimi-k2.6",
        "kimi-latest",
        "kimi-thinking-preview",
        "moonshot-v1-128k-vision-preview",
        "moonshotai/kimi-k2.6",  # OpenRouter 路径
    ]:
        assert provider_from_model(m) == "openai", f"{m!r} should infer openai"


def test_provider_from_model_deepseek():
    """DeepSeek model 名前缀应推断到 openai（OpenAI compat 端点）。"""
    from web_agent.llm import provider_from_model

    for m in [
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-flash",
    ]:
        assert provider_from_model(m) == "openai", f"{m!r} should infer openai"


def test_openai_client_kimi_detection_via_base_url(monkeypatch):
    """base_url 含 "moonshot" → _is_kimi=True，启用兼容补丁。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.moonshot.ai/v1")
    client = OpenAIClient()
    assert client._is_kimi is True


@pytest.mark.asyncio
async def test_openai_client_plan_vision_detail_default_high(monkeypatch):
    """V0.66.6 (Path A): WEB_AGENT_VISION_DETAIL 未设 → image_url.detail = 'high' (默认)."""
    from collections import deque
    from unittest.mock import AsyncMock, MagicMock

    from web_agent.perceiver import Mark
    from web_agent.trace import Trace

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("WEB_AGENT_VISION_DETAIL", raising=False)
    client = OpenAIClient()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.tool_calls = [
        MagicMock(function=MagicMock(name="done", arguments='{"thought":"t","result":"r"}'))
    ]
    mock_resp.choices[0].message.tool_calls[0].function.name = "done"
    mock_resp.usage = None
    client._client.chat.completions.create = AsyncMock(return_value=mock_resp)
    trace = Trace(task_id="t", goal="g", steps=deque())
    await client.plan(goal="g", screenshot_b64="b", marks=[Mark(id=1, tag="a", role="a", text="a", bbox={"x":0,"y":0,"w":1,"h":1})], trace=trace)
    kwargs = client._client.chat.completions.create.call_args.kwargs
    image_block = kwargs["messages"][1]["content"][0]
    assert image_block["image_url"]["detail"] == "high"


@pytest.mark.asyncio
async def test_openai_client_plan_vision_detail_low_via_env(monkeypatch):
    """V0.66.6 (Path A): WEB_AGENT_VISION_DETAIL=low → image_url.detail = 'low' (省 token + 快)."""
    from collections import deque
    from unittest.mock import AsyncMock, MagicMock

    from web_agent.perceiver import Mark
    from web_agent.trace import Trace

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("WEB_AGENT_VISION_DETAIL", "low")
    client = OpenAIClient()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.tool_calls = [
        MagicMock(function=MagicMock(name="done", arguments='{"thought":"t","result":"r"}'))
    ]
    mock_resp.choices[0].message.tool_calls[0].function.name = "done"
    mock_resp.usage = None
    client._client.chat.completions.create = AsyncMock(return_value=mock_resp)
    trace = Trace(task_id="t", goal="g", steps=deque())
    await client.plan(goal="g", screenshot_b64="b", marks=[Mark(id=1, tag="a", role="a", text="a", bbox={"x":0,"y":0,"w":1,"h":1})], trace=trace)
    kwargs = client._client.chat.completions.create.call_args.kwargs
    image_block = kwargs["messages"][1]["content"][0]
    assert image_block["image_url"]["detail"] == "low"


@pytest.mark.asyncio
async def test_openai_client_plan_vision_detail_invalid_falls_back_to_high(monkeypatch):
    """V0.66.6 (Path A): 非法值 (typo / future variant) → fallback 'high' 防止 OpenAI 400."""
    from collections import deque
    from unittest.mock import AsyncMock, MagicMock

    from web_agent.perceiver import Mark
    from web_agent.trace import Trace

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("WEB_AGENT_VISION_DETAIL", "ultra-high-typo")
    client = OpenAIClient()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.tool_calls = [
        MagicMock(function=MagicMock(name="done", arguments='{"thought":"t","result":"r"}'))
    ]
    mock_resp.choices[0].message.tool_calls[0].function.name = "done"
    mock_resp.usage = None
    client._client.chat.completions.create = AsyncMock(return_value=mock_resp)
    trace = Trace(task_id="t", goal="g", steps=deque())
    await client.plan(goal="g", screenshot_b64="b", marks=[Mark(id=1, tag="a", role="a", text="a", bbox={"x":0,"y":0,"w":1,"h":1})], trace=trace)
    kwargs = client._client.chat.completions.create.call_args.kwargs
    image_block = kwargs["messages"][1]["content"][0]
    assert image_block["image_url"]["detail"] == "high"


def test_openai_client_openrouter_detection_via_base_url(monkeypatch):
    """V0.66.4: base_url 含 "openrouter.ai" → _is_openrouter=True, 走 tool_choice="auto"
    (OpenRouter Qwen3-VL 等上游不支持 "required" 直接 404, 跟 Kimi 同 quirks)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    client = OpenAIClient()
    assert client._is_openrouter is True
    assert client._is_kimi is False


def test_openai_client_kimi_cn_endpoint_detection(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.moonshot.cn/v1")
    client = OpenAIClient()
    assert client._is_kimi is True


def test_openai_client_default_not_kimi(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    client = OpenAIClient()
    assert client._is_kimi is False


def test_openai_client_openrouter_not_kimi(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    client = OpenAIClient()
    assert client._is_kimi is False
