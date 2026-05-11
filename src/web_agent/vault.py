"""V0.27.1: SecretStore Protocol + EnvSecretStore + KeyringSecretStore 占位 stub.

V0.27 系列 vault scope:
- A1 (本): API key 安全存取, 让 anthropic.py / openai.py 不再硬 import os.environ.get
- A4 (V0.27.2): per-task provider routing — 数据驱动 select_provider
- A2 web 登录态: 推迟 V0.28 (V0.16.18+ Chrome 接管已 zero-config)
- A3 加密: 推迟 V0.28 (KeyringSecretStore 占位 stub)

依赖方向 (CLAUDE.md 解耦优先): domain (types) ← ports (本文件 SecretStore Protocol) ← 业务层
(make_client 注入) ← 组合根 (cli / mcp_server / eval/cli 装配 EnvSecretStore).
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SecretStore(Protocol):
    """V0.27.1: 跨 backend 的 secret 取值接口.

    实现:
    - EnvSecretStore (本): 包 os.environ, 默 backend (跟现有 .env loading 兼容)
    - KeyringSecretStore: V0.27.1 占位 stub raise NotImplementedError, V0.28 实现 (跨平台
      macOS keychain / Linux Secret Service / Windows Credential Manager)
    - FakeSecretStore (test): mock backend 让单测可注入任意 key→value 不依赖真 .env

    跟 LLMClient Protocol (V0.21.2 base.py) 同 @runtime_checkable + frozen dataclass 实现模式.
    """

    def get(self, key: str, default: str | None = None) -> str | None:
        """取 secret 值. 缺失返 default (默 None). 失败 raise RuntimeError 让 caller 决定 abort/retry."""
        ...

    def has(self, key: str) -> bool:
        """check secret 是否存在 (不返值, 防日志泄漏). 用于 fail-fast 启动校验."""
        ...


class EnvSecretStore:
    """V0.27.1: 默 backend — 包 os.environ 不再 load_dotenv (caller 入口已 load 一次防 race).

    EnvSecretStore() 跟现有 anthropic.py / openai.py `os.environ.get("ANTHROPIC_API_KEY")`
    100% 等价. V0.27.1 加注入让 V0.27.3 elicit + V0.28 keyring 可替换 backend.
    """

    def get(self, key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default)

    def has(self, key: str) -> bool:
        return key in os.environ


_KEYRING_SERVICE = "web-agent"  # V0.31.0: 单一 service, key 名复用 EnvSecretStore (1:1 swap)


class KeyringSecretStore:
    """V0.31.0 真实现: 跨平台 OS-native secret store (macOS keychain / Linux Secret Service /
    Windows Credential Manager) 通过 keyring lib (PyPI 标准跨平台).

    keyring 是 opt-in extra dep — `pip install web-agent[keyring]` (Linux 还需 dbus + libsecret).
    lazy import 防默 install 不装 keyring 时本类构造也能 work (V0.31.2 opt-in env 切换), 调用
    get/has/set/delete 时才真 import + RuntimeError 指 extra.

    service name 单一 "web-agent" + key 名复用 EnvSecretStore key ("ANTHROPIC_API_KEY" 等), 让
    `KeyringSecretStore()` 跟 `EnvSecretStore()` 1:1 swap (cli/mcp caller 0 改).

    跟 EnvSecretStore 同 SecretStore Protocol (get/has 同步), 加 set/delete 让 cli web-agent-vault
    (V0.31.1) 可写 vault.
    """

    def _import_keyring(self) -> Any:
        """V0.31.0: lazy import keyring + ImportError 友好错误指 extra."""
        try:
            import keyring
        except ImportError as e:
            raise RuntimeError(
                "KeyringSecretStore 需 keyring 包: pip install 'web-agent[keyring]' "
                "(Linux 还需 dbus + libsecret). 当前缺包 → 用 EnvSecretStore() 默 backend."
            ) from e
        return keyring

    def get(self, key: str, default: str | None = None) -> str | None:
        keyring = self._import_keyring()
        try:
            value = keyring.get_password(_KEYRING_SERVICE, key)
        except Exception:
            # keyring backend fail (e.g. Linux dbus unavailable) → 视作缺值
            return default
        return value if value is not None else default

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def set(self, key: str, value: str) -> None:
        """V0.31.0: 写 key 到 keyring (cli web-agent-vault set 用). 不在 SecretStore Protocol 内
        (Protocol 只 get/has). caller 用 isinstance(store, KeyringSecretStore) 取 set 能力."""
        keyring = self._import_keyring()
        keyring.set_password(_KEYRING_SERVICE, key, value)

    def delete(self, key: str) -> None:
        """V0.31.0: 删 key (cli web-agent-vault delete 用). key 不存在时 raise PasswordDeleteError
        (keyring lib 行为), caller 自行 catch."""
        keyring = self._import_keyring()
        keyring.delete_password(_KEYRING_SERVICE, key)


class ChainedSecretStore:
    """V0.31.0: 链式 SecretStore — 按 stores 顺序短路 has/get (前者 hit 即返).

    V0.31.2 用 `default_store()` opt-in `WEB_AGENT_USE_KEYRING=1` 时切
    `ChainedSecretStore([KeyringSecretStore(), EnvSecretStore()])`, 让 keyring miss 自动 fallback env.

    跟 EnvSecretStore 同 SecretStore Protocol, V0.27.1 SecretStore.get/has 模式一致.
    """

    def __init__(self, stores: list["SecretStore"]) -> None:
        self._stores = list(stores)

    def get(self, key: str, default: str | None = None) -> str | None:
        for store in self._stores:
            if store.has(key):
                return store.get(key, default)
        return default

    def has(self, key: str) -> bool:
        return any(store.has(key) for store in self._stores)


def default_store() -> SecretStore:
    """V0.27.1: 默 SecretStore — EnvSecretStore. make_client 默调用避免 None check 散乱.

    V0.28 加 keyring backend 时只改本函数 (e.g. KeyringSecretStore() if env enabled else
    EnvSecretStore()), make_client / anthropic.py / openai.py 0 改.
    """
    return EnvSecretStore()


class MissingSecretError(RuntimeError):
    """V0.27.4: SecretStore 缺 key 时 raise — RuntimeError 子类保 V0.27.1 14 测兼容.

    带 `key` attr 让 mcp_server elicit retry 知道 prompt 哪个 key 名 (不靠 message 字符串
    parsing 脆点 — Plan subagent 决: 比 message-startswith 检测干净).
    """

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"{key} 未设置 — 请填 .env 或 export 环境变量")


class InMemorySecretStore:
    """V0.27.4: dict-wrapped SecretStore — 0 IO + 0 env mutate, mcp_server elicit 后 retry 用.

    跟 EnvSecretStore 同 SecretStore Protocol, 构造接 `data: dict[str, str]` (key → value).
    mcp_server 拿到 elicit 用户输入后 `InMemorySecretStore({"ANTHROPIC_API_KEY": value})` 注
    `make_client(secret_store=...)` retry 一次. 内存即生命周期 (per-call), task 跑完即释放,
    secret 不落 env / 不落磁盘.
    """

    def __init__(self, data: dict[str, str]) -> None:
        self._data = dict(data)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._data.get(key, default)

    def has(self, key: str) -> bool:
        return key in self._data
