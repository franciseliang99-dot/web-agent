"""V0.27.1 vault framework 单测: SecretStore Protocol + EnvSecretStore + KeyringSecretStore stub.

测 Protocol runtime check + EnvSecretStore os.environ 包装 + KeyringSecretStore raise +
default_store 默 EnvSecretStore + make_client 注入零破坏现有 caller.

V0.27.4 加 MissingSecretError + InMemorySecretStore 测 (mcp_server elicit retry 链路依赖).
"""

from __future__ import annotations

import pytest

from web_agent.vault import (
    EnvSecretStore,
    InMemorySecretStore,
    KeyringSecretStore,
    MissingSecretError,
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


# V0.31.0: KeyringSecretStore 真实现 (V0.27.1 stub 已替换). Memory backend mock 跑 CI 安全.


def _setup_memory_backend(monkeypatch):
    """V0.31.0: keyring memory backend mock (CI 无 dbus 也跑)."""
    import keyring

    # Reset 防上次测残留
    class _MemBackend(keyring.backend.KeyringBackend):
        priority = 1000  # type: ignore[assignment]

        def __init__(self):
            self._store: dict[tuple[str, str], str] = {}

        def get_password(self, service, username):
            return self._store.get((service, username))

        def set_password(self, service, username, password):
            self._store[(service, username)] = password

        def delete_password(self, service, username):
            if (service, username) not in self._store:
                from keyring.errors import PasswordDeleteError
                raise PasswordDeleteError(f"no entry: {service}/{username}")
            del self._store[(service, username)]

    backend = _MemBackend()
    monkeypatch.setattr(keyring, "get_password",
                        lambda s, u: backend.get_password(s, u))
    monkeypatch.setattr(keyring, "set_password",
                        lambda s, u, p: backend.set_password(s, u, p))
    monkeypatch.setattr(keyring, "delete_password",
                        lambda s, u: backend.delete_password(s, u))
    return backend


def test_keyring_secret_store_get_missing_returns_default(monkeypatch):
    """V0.31.0: keyring 没值 → 返 default."""
    _setup_memory_backend(monkeypatch)
    s = KeyringSecretStore()
    assert s.get("MISSING_KEY", "fallback") == "fallback"
    assert s.get("MISSING_KEY") is None


def test_keyring_secret_store_set_then_get(monkeypatch):
    """V0.31.0: set + get round-trip."""
    _setup_memory_backend(monkeypatch)
    s = KeyringSecretStore()
    s.set("ANTHROPIC_API_KEY", "sk-ant-test-keyring")
    assert s.get("ANTHROPIC_API_KEY") == "sk-ant-test-keyring"
    assert s.has("ANTHROPIC_API_KEY") is True


def test_keyring_secret_store_delete(monkeypatch):
    """V0.31.0: delete 后 get 返 None / has False."""
    _setup_memory_backend(monkeypatch)
    s = KeyringSecretStore()
    s.set("KEY_TO_DELETE", "val")
    assert s.has("KEY_TO_DELETE") is True
    s.delete("KEY_TO_DELETE")
    assert s.has("KEY_TO_DELETE") is False
    assert s.get("KEY_TO_DELETE") is None


def test_keyring_secret_store_satisfies_secret_store_protocol(monkeypatch):
    """V0.31.0: 跟 EnvSecretStore 同 Protocol (1:1 swap)."""
    _setup_memory_backend(monkeypatch)
    s = KeyringSecretStore()
    assert isinstance(s, SecretStore)


def test_keyring_secret_store_import_error_when_keyring_not_installed(monkeypatch):
    """V0.31.0: keyring lib 未装 → RuntimeError 友好提示 pip install [keyring]."""
    import sys
    # 模拟 keyring 未装
    monkeypatch.setitem(sys.modules, "keyring", None)
    s = KeyringSecretStore()
    with pytest.raises(RuntimeError, match=r"web-agent\[keyring\]"):
        s.get("any-key")


def test_keyring_get_backend_fail_returns_default(monkeypatch):
    """V0.31.0: keyring backend raise (e.g. dbus unavail) → silent 返 default."""
    import keyring

    def _boom(service, username):
        raise RuntimeError("dbus unavailable")

    monkeypatch.setattr(keyring, "get_password", _boom)
    s = KeyringSecretStore()
    assert s.get("ANY", "fallback") == "fallback"


# ---- ChainedSecretStore (V0.31.0) ----


def test_chained_secret_store_short_circuit_first_hit(monkeypatch):
    """V0.31.0: ChainedSecretStore 按 stores 顺序短路 — 第一 store hit 直接返."""
    from web_agent.vault import ChainedSecretStore, EnvSecretStore

    _setup_memory_backend(monkeypatch)
    keyring_store = KeyringSecretStore()
    keyring_store.set("FIRST_KEY", "from-keyring")

    monkeypatch.setenv("FIRST_KEY", "from-env")  # env 也有, 但 keyring 优先
    monkeypatch.setenv("ENV_ONLY_KEY", "env-only-val")

    chain = ChainedSecretStore([keyring_store, EnvSecretStore()])
    assert chain.get("FIRST_KEY") == "from-keyring"  # keyring 在前
    assert chain.get("ENV_ONLY_KEY") == "env-only-val"  # keyring 缺 → env fallback
    assert chain.get("MISSING") is None


def test_chained_secret_store_has_short_circuit(monkeypatch):
    """V0.31.0: ChainedSecretStore.has 任一 store hit 即 True."""
    from web_agent.vault import ChainedSecretStore, EnvSecretStore

    _setup_memory_backend(monkeypatch)
    monkeypatch.setenv("ENV_KEY", "v")
    monkeypatch.delenv("MISSING_BOTH", raising=False)

    chain = ChainedSecretStore([KeyringSecretStore(), EnvSecretStore()])
    assert chain.has("ENV_KEY") is True
    assert chain.has("MISSING_BOTH") is False


def test_chained_secret_store_satisfies_protocol(monkeypatch):
    from web_agent.vault import ChainedSecretStore

    _setup_memory_backend(monkeypatch)
    chain = ChainedSecretStore([KeyringSecretStore()])
    assert isinstance(chain, SecretStore)


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


# --- V0.27.1.1: bug fix make_client API drift (subagent 发现 V0.27.1 设计承诺空头支票) ---


def test_make_client_accepts_secret_store_and_passes_through_anthropic(monkeypatch):
    """V0.27.1.1: make_client(secret_store=...) 真透传给 AnthropicClient (subagent 实测发现 bug).

    V0.27.1 vault.py docstring + CHANGELOG 反复承诺 "make_client(secret_store=...) 0 改 caller",
    但 V0.27.1 落地时 make_client 签名根本没加 kwarg → V0.28 加 keyring 时 caller 必须直绕
    factory 走 AnthropicClient(secret_store=...) — 违反设计承诺. V0.27.1.1 修复.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class _StoreWithKey:
        def get(self, key, default=None):
            if key == "ANTHROPIC_API_KEY":
                return "sk-ant-test-via-make-client"
            return default

        def has(self, key):
            return key == "ANTHROPIC_API_KEY"

    from web_agent.llm import make_client
    client = make_client(provider="anthropic", secret_store=_StoreWithKey())  # type: ignore[arg-type]
    assert client.name == "anthropic"  # 构造成功证明 store 真透传到 AnthropicClient


def test_make_client_accepts_secret_store_and_passes_through_openai(monkeypatch):
    """V0.27.1.1: make_client(provider='openai', secret_store=...) 透传 OpenAIClient."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    class _StoreWithKey:
        def get(self, key, default=None):
            if key == "OPENAI_API_KEY":
                return "sk-test-via-make-client"
            return default

        def has(self, key):
            return key == "OPENAI_API_KEY"

    from web_agent.llm import make_client
    client = make_client(provider="openai", secret_store=_StoreWithKey())  # type: ignore[arg-type]
    assert client.name == "openai"


def test_make_client_default_secret_store_none_keeps_old_behavior(monkeypatch):
    """V0.27.1.1: make_client() 不传 secret_store → 默 None → AnthropicClient 内部 default_store()
    EnvSecretStore 100% 兼容老 caller (cli/jd/list/eval/runner 0 改)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    from web_agent.llm import make_client
    client = make_client(provider="anthropic")  # 不传 secret_store
    assert client.name == "anthropic"


# --- V0.27.4: MissingSecretError + InMemorySecretStore (mcp_server elicit retry 依赖) ---


def test_missing_secret_error_is_runtimeerror_subclass():
    """V0.27.4: MissingSecretError 子类化 RuntimeError 保 V0.27.1 14 测兼容
    (`pytest.raises(RuntimeError, match=...)` 仍触发)."""
    e = MissingSecretError("ANTHROPIC_API_KEY")
    assert isinstance(e, RuntimeError)
    assert "ANTHROPIC_API_KEY 未设置" in str(e)


def test_missing_secret_error_carries_key_attr():
    """V0.27.4: e.key 让 mcp_server 知道 elicit 哪个 key (不靠 message 字符串 parsing)."""
    e = MissingSecretError("OPENAI_API_KEY")
    assert e.key == "OPENAI_API_KEY"


def test_anthropic_client_raises_missing_secret_error_not_plain_runtimeerror(monkeypatch):
    """V0.27.4: AnthropicClient 缺 key → raise MissingSecretError 不是 plain RuntimeError.
    V0.27.1 测 `pytest.raises(RuntimeError, match=...)` 仍触发因子类化, 但 mcp_server
    可 catch MissingSecretError 区分 'API key 缺失' vs 其他 RuntimeError (e.g. SDK 错).
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from web_agent.llm.anthropic import AnthropicClient
    with pytest.raises(MissingSecretError) as exc_info:
        AnthropicClient()
    assert exc_info.value.key == "ANTHROPIC_API_KEY"


def test_openai_client_raises_missing_secret_error(monkeypatch):
    """V0.27.4: OpenAIClient 缺 key 同 anthropic — raise MissingSecretError."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    from web_agent.llm.openai import OpenAIClient
    with pytest.raises(MissingSecretError) as exc_info:
        OpenAIClient()
    assert exc_info.value.key == "OPENAI_API_KEY"


def test_in_memory_secret_store_satisfies_protocol():
    """V0.27.4: InMemorySecretStore 跟 EnvSecretStore 同满足 SecretStore Protocol runtime check."""
    s = InMemorySecretStore({"KEY": "val"})
    assert isinstance(s, SecretStore)


def test_in_memory_secret_store_get_existing():
    s = InMemorySecretStore({"FOO": "bar", "BAZ": "qux"})
    assert s.get("FOO") == "bar"
    assert s.get("BAZ") == "qux"


def test_in_memory_secret_store_get_missing_returns_default():
    s = InMemorySecretStore({"FOO": "bar"})
    assert s.get("MISSING", "fallback") == "fallback"
    assert s.get("MISSING") is None


def test_in_memory_secret_store_has():
    s = InMemorySecretStore({"K": "v"})
    assert s.has("K") is True
    assert s.has("MISSING") is False


def test_in_memory_secret_store_constructor_copies_dict():
    """V0.27.4: InMemorySecretStore 构造时 copy 入参 dict, 防 caller 后续 mutate 泄漏."""
    src = {"K": "v"}
    s = InMemorySecretStore(src)
    src["K"] = "MUTATED"
    src["NEW"] = "added"
    assert s.get("K") == "v"  # 不受 caller mutate 影响
    assert s.has("NEW") is False


# ---------- V0.31.1 web-agent-vault cli (set/get/delete/list) ----------


def test_vault_cli_set_then_get_round_trip(monkeypatch, capsys):
    """V0.31.1: set (getpass) → get → 真显 value (round-trip mock backend)."""
    from web_agent.vault import main

    _setup_memory_backend(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "sk-test-via-getpass")

    rc = main(["set", "ANTHROPIC_API_KEY"])
    assert rc == 0
    out_set = capsys.readouterr().out
    assert "ANTHROPIC_API_KEY" in out_set
    assert "已写入 keyring" in out_set

    rc = main(["get", "ANTHROPIC_API_KEY"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "sk-test-via-getpass"


def test_vault_cli_set_from_stdin(monkeypatch, capsys):
    """V0.31.1: --from-stdin 路径 (CI 自动化), pipe 友好."""
    import io
    from web_agent.vault import main

    _setup_memory_backend(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("sk-from-stdin\n"))

    rc = main(["set", "OPENAI_API_KEY", "--from-stdin"])
    assert rc == 0
    capsys.readouterr()  # 清 set 输出
    rc = main(["get", "OPENAI_API_KEY"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "sk-from-stdin"


def test_vault_cli_set_non_tty_requires_stdin_flag(monkeypatch, capsys):
    """V0.31.1: stdin 非 tty + 不带 --from-stdin → exit 1 防 getpass silent fallback echo 泄."""
    from web_agent.vault import main

    _setup_memory_backend(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    rc = main(["set", "K"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "tty" in err
    assert "--from-stdin" in err


def test_vault_cli_get_missing_key(monkeypatch, capsys):
    """V0.31.1: get 不存在 key → exit 1 + 友好 stderr."""
    from web_agent.vault import main

    _setup_memory_backend(monkeypatch)

    rc = main(["get", "NOT_SET_KEY"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "NOT_SET_KEY" in err
    assert "set 先" in err


def test_vault_cli_delete_existing(monkeypatch, capsys):
    """V0.31.1: delete 已存 key → 删除 + has=False."""
    from web_agent.vault import KeyringSecretStore, main

    _setup_memory_backend(monkeypatch)
    KeyringSecretStore().set("KEY_TO_DELETE", "val")

    rc = main(["delete", "KEY_TO_DELETE"])
    assert rc == 0
    assert "已删" in capsys.readouterr().out
    assert KeyringSecretStore().has("KEY_TO_DELETE") is False


def test_vault_cli_delete_missing_key(monkeypatch, capsys):
    """V0.31.1: delete 不存在 key → exit 1 + 友好 stderr (catch keyring.errors.PasswordDeleteError)."""
    from web_agent.vault import main

    _setup_memory_backend(monkeypatch)

    rc = main(["delete", "NEVER_SET"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "NEVER_SET" in err
    assert "失败" in err


def test_vault_cli_list_shows_known_keys_status(monkeypatch, capsys):
    """V0.31.1: list 枚举 _KNOWN_KEYS, set 的显 SET / 未 set 显 MISSING (不显 value)."""
    from web_agent.vault import KeyringSecretStore, main

    _setup_memory_backend(monkeypatch)
    KeyringSecretStore().set("ANTHROPIC_API_KEY", "sk-secret-not-shown")

    rc = main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ANTHROPIC_API_KEY: SET" in out
    assert "OPENAI_API_KEY: MISSING" in out
    # 不泄 value
    assert "sk-secret-not-shown" not in out


def test_vault_cli_set_empty_value_rejected(monkeypatch, capsys):
    """V0.31.1: getpass 返空串 → exit 1 拒写 (防意外回车空串污染)."""
    from web_agent.vault import main

    _setup_memory_backend(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "")

    rc = main(["set", "K"])
    assert rc == 1
    assert "value 不能为空" in capsys.readouterr().err


def test_vault_cli_keyring_extra_not_installed(monkeypatch, capsys):
    """V0.31.1: keyring lib 未装 → exit 3 + 提示 pip install web-agent[keyring]."""
    import sys
    from web_agent.vault import main

    monkeypatch.setitem(sys.modules, "keyring", None)
    rc = main(["get", "ANY"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "web-agent[keyring]" in err


def test_vault_cli_entry_point_registered():
    """V0.31.1: web-agent-vault console_script 注册到 entry points (验 pyproject.scripts)."""
    import importlib.metadata as md

    entry_points = md.entry_points(group="console_scripts")
    matching = [ep for ep in entry_points if ep.name == "web-agent-vault"]
    assert len(matching) == 1, f"web-agent-vault 未注册, found: {[e.name for e in entry_points]}"
    assert matching[0].value == "web_agent.vault:main"


# ---------- V0.31.2 default_store opt-in env WEB_AGENT_USE_KEYRING ----------


def test_default_store_returns_env_when_no_use_keyring(monkeypatch):
    """V0.31.2: WEB_AGENT_USE_KEYRING 未设 → 默 EnvSecretStore (V0.31 不改默 100% 兼容)."""
    monkeypatch.delenv("WEB_AGENT_USE_KEYRING", raising=False)
    assert isinstance(default_store(), EnvSecretStore)


def test_default_store_returns_chained_when_use_keyring_env_set(monkeypatch):
    """V0.31.2: WEB_AGENT_USE_KEYRING=1 → ChainedSecretStore([Keyring, Env])."""
    from web_agent.vault import ChainedSecretStore

    monkeypatch.setenv("WEB_AGENT_USE_KEYRING", "1")
    s = default_store()
    assert isinstance(s, ChainedSecretStore)
    # 内 stores 顺序: Keyring 优先, Env fallback
    assert isinstance(s._stores[0], KeyringSecretStore)
    assert isinstance(s._stores[1], EnvSecretStore)


@pytest.mark.parametrize("env_val", ["true", "1", "yes", "TRUE", "Yes"])
def test_default_store_use_keyring_accepts_truthy_values(monkeypatch, env_val):
    """V0.31.2: WEB_AGENT_USE_KEYRING 接 ('true','1','yes' case-insensitive) — 跟 codebase 风格统一."""
    from web_agent.vault import ChainedSecretStore

    monkeypatch.setenv("WEB_AGENT_USE_KEYRING", env_val)
    assert isinstance(default_store(), ChainedSecretStore)


def test_keyring_has_returns_false_when_keyring_extra_missing(monkeypatch):
    """V0.31.2: keyring extra 未装 → KeyringSecretStore.has 不 raise (try/except RuntimeError → False).

    让 ChainedSecretStore.has 链不断, fallback 下个 store 而非 raise 阻塞 LLM client init.
    """
    import sys

    monkeypatch.setitem(sys.modules, "keyring", None)
    s = KeyringSecretStore()
    assert s.has("ANY_KEY") is False  # 不 raise


def test_chained_default_store_falls_back_to_env_when_keyring_extra_missing(monkeypatch):
    """V0.31.2 集成: env=1 + keyring 未装 → ChainedSecretStore 自然 fallback Env, get 通过."""
    import sys

    monkeypatch.setenv("WEB_AGENT_USE_KEYRING", "1")
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env-fallback")

    s = default_store()
    # KeyringSecretStore.has 返 False (extra 未装) → ChainedSecretStore fallback Env
    assert s.get("ANTHROPIC_API_KEY") == "sk-from-env-fallback"
    assert s.has("ANTHROPIC_API_KEY") is True
