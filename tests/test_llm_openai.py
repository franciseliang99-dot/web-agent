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
    client = OpenAIClient()
    assert client.name == "openai"
    assert client.model == DEFAULT_MODEL
    assert len(client._tools) == 5
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
    from web_agent.llm import make_client

    c = make_client()
    assert c.name == "openai"


def test_make_client_factory_picks_openai_by_model_prefix(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("WEB_AGENT_LLM_PROVIDER", raising=False)
    from web_agent.llm import make_client

    c = make_client(model="gpt-4o")
    assert c.name == "openai"
    assert c.model == "gpt-4o"
