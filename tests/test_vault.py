"""V0.27.1 vault framework 单测: SecretStore Protocol + EnvSecretStore + KeyringSecretStore stub.

测 Protocol runtime check + EnvSecretStore os.environ 包装 + KeyringSecretStore raise +
default_store 默 EnvSecretStore + make_client 注入零破坏现有 caller.
"""

from __future__ import annotations

import pytest

from web_agent.vault import (
    EnvSecretStore,
    KeyringSecretStore,
    SecretStore,
    default_store,
)


# --- SecretStore Protocol runtime check ---


def test_env_secret_store_is_secret_store_protocol():
    """V0.27.1: EnvSecretStore satisfies SecretStore Protocol (@runtime_checkable)."""
    s = EnvSecretStore()
    assert isinstance(s, SecretStore)


def test_keyring_secret_store_is_secret_store_protocol():
    """V0.27.1: KeyringSecretStore stub 也 satisfies Protocol (V0.28 实现时不破 Protocol contract)."""
    s = KeyringSecretStore()
    assert isinstance(s, SecretStore)


def test_default_store_returns_env_secret_store():
    """V0.27.1: default_store() 默 EnvSecretStore (V0.28 改返 keyring 时不影响 V0.27 测试)."""
    assert isinstance(default_store(), EnvSecretStore)


# --- EnvSecretStore ---


def test_env_secret_store_get_existing_key(monkeypatch):
    """V0.27.1: env 已设 → store.get 返值."""
    monkeypatch.setenv("V0271_TEST_KEY", "test-value-abc")
    s = EnvSecretStore()
    assert s.get("V0271_TEST_KEY") == "test-value-abc"


def test_env_secret_store_get_missing_returns_default(monkeypatch):
    """V0.27.1: env 缺 + default 提供 → 返 default."""
    monkeypatch.delenv("V0271_NONEXISTENT_KEY", raising=False)
    s = EnvSecretStore()
    assert s.get("V0271_NONEXISTENT_KEY", "fallback") == "fallback"


def test_env_secret_store_get_missing_no_default_returns_none(monkeypatch):
    """V0.27.1: env 缺 + 无 default → 返 None (跟 os.environ.get 行为一致)."""
    monkeypatch.delenv("V0271_NONEXISTENT_KEY", raising=False)
    s = EnvSecretStore()
    assert s.get("V0271_NONEXISTENT_KEY") is None


def test_env_secret_store_has_existing_key(monkeypatch):
    monkeypatch.setenv("V0271_HAS_TEST", "x")
    s = EnvSecretStore()
    assert s.has("V0271_HAS_TEST") is True


def test_env_secret_store_has_missing_key(monkeypatch):
    monkeypatch.delenv("V0271_HAS_MISSING", raising=False)
    s = EnvSecretStore()
    assert s.has("V0271_HAS_MISSING") is False


# --- KeyringSecretStore stub ---


def test_keyring_secret_store_get_raises_not_implemented():
    """V0.27.1: stub 防误用 — V0.28 真实现, V0.27 raise NotImplementedError + 提示用 EnvSecretStore."""
    s = KeyringSecretStore()
    with pytest.raises(NotImplementedError, match="V0.28 实现"):
        s.get("any-key")


def test_keyring_secret_store_has_raises_not_implemented():
    s = KeyringSecretStore()
    with pytest.raises(NotImplementedError, match="V0.28 实现"):
        s.has("any-key")


# --- make_client 注入 (V0.27.1) ---


def test_anthropic_client_accepts_secret_store_kwarg(monkeypatch):
    """V0.27.1: AnthropicClient(secret_store=...) 注入读 store 而非 os.environ."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # 确保 env 没

    class _StoreWithKey:
        def get(self, key, default=None):
            if key == "ANTHROPIC_API_KEY":
                return "sk-ant-test-injected-via-store"
            return default

        def has(self, key):
            return key == "ANTHROPIC_API_KEY"

    from web_agent.llm.anthropic import AnthropicClient
    client = AnthropicClient(secret_store=_StoreWithKey())  # type: ignore[arg-type]
    assert client.model  # 构造成功证明 store 真生效


def test_openai_client_accepts_secret_store_kwarg(monkeypatch):
    """V0.27.1: OpenAIClient(secret_store=...) 同 anthropic."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    class _StoreWithKey:
        def get(self, key, default=None):
            if key == "OPENAI_API_KEY":
                return "sk-test-injected"
            return default

        def has(self, key):
            return key == "OPENAI_API_KEY"

    from web_agent.llm.openai import OpenAIClient
    client = OpenAIClient(secret_store=_StoreWithKey())  # type: ignore[arg-type]
    assert client.name == "openai"  # 非 Kimi (无 moonshot base_url)


def test_anthropic_client_default_store_reads_env(monkeypatch):
    """V0.27.1: 不传 secret_store → 内部 EnvSecretStore() 默 backend, 100% 兼容现有 caller."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-from-env")
    from web_agent.llm.anthropic import AnthropicClient
    client = AnthropicClient()  # 不传 secret_store
    assert client.model  # 构造成功证明 default EnvSecretStore 真生效


def test_anthropic_client_missing_key_raises_runtimeerror(monkeypatch):
    """V0.27.1: store 也无 key → 跟现有 RuntimeError 兼容 (V0.18.0 行为不变)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class _EmptyStore:
        def get(self, key, default=None):
            return default

        def has(self, key):
            return False

    from web_agent.llm.anthropic import AnthropicClient
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY 未设置"):
        AnthropicClient(secret_store=_EmptyStore())  # type: ignore[arg-type]
