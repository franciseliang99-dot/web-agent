"""anthropic.py 单测 (audit gap 收尾): __init__ env/explicit api_key + base_url 路径。

plan() 真 SDK 调用难 mock (vision + tool_use 复杂结构), 已通过 test_llm_schema.py
的 to_anthropic_tools 间接覆盖工具定义层. 此 file 只测 client 构造路径。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from web_agent.llm.anthropic import DEFAULT_MODEL, AnthropicClient


def test_init_missing_api_key_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicClient()


def test_init_uses_env_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-not-real")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    with patch("web_agent.llm.anthropic.AsyncAnthropic") as fake_anthropic:
        client = AnthropicClient()
    assert client.name == "anthropic"
    assert client.model == DEFAULT_MODEL
    fake_anthropic.assert_called_once()
    kwargs = fake_anthropic.call_args.kwargs
    assert kwargs["api_key"] == "sk-ant-test-fake-not-real"
    assert kwargs["max_retries"] == 4
    assert kwargs["timeout"] == 120.0
    assert "base_url" not in kwargs


def test_init_explicit_api_key_overrides_env(monkeypatch):
    """显式传 api_key 应优先于 env。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")

    with patch("web_agent.llm.anthropic.AsyncAnthropic") as fake_anthropic:
        AnthropicClient(api_key="sk-ant-explicit")
    assert fake_anthropic.call_args.kwargs["api_key"] == "sk-ant-explicit"


def test_init_with_base_url_env(monkeypatch):
    """ANTHROPIC_BASE_URL env 应透传到 SDK (OpenRouter / LiteLLM 代理路径)。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")

    with patch("web_agent.llm.anthropic.AsyncAnthropic") as fake_anthropic:
        AnthropicClient()
    kwargs = fake_anthropic.call_args.kwargs
    assert kwargs["base_url"] == "https://openrouter.ai/api"


def test_init_explicit_base_url_overrides_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://env.example/api")

    with patch("web_agent.llm.anthropic.AsyncAnthropic") as fake_anthropic:
        AnthropicClient(base_url="https://explicit.example/api")
    assert fake_anthropic.call_args.kwargs["base_url"] == "https://explicit.example/api"


def test_init_explicit_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch("web_agent.llm.anthropic.AsyncAnthropic"):
        client = AnthropicClient(model="claude-opus-4-7")
    assert client.model == "claude-opus-4-7"


def test_init_loads_tools(monkeypatch):
    """构造后 _tools 应非空 (5 种 action: click/type/scroll/extract/done)。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch("web_agent.llm.anthropic.AsyncAnthropic"):
        client = AnthropicClient()
    assert isinstance(client._tools, list)
    assert len(client._tools) >= 4  # 至少 click/type/scroll/done; extract 也有
