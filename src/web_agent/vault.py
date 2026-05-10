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
from typing import Protocol, runtime_checkable


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


class KeyringSecretStore:
    """V0.27.1 占位 stub: V0.28 真实现 (keyring lib 跨平台 macOS keychain / Linux Secret Service /
    Windows Credential Manager).

    Raise NotImplementedError 防 V0.27.1 误用 — 接口预留是为让 V0.28 加 backend 时
    make_client(secret_store=KeyringSecretStore(...)) 立即可用 0 改 caller.
    """

    def get(self, key: str, default: str | None = None) -> str | None:
        raise NotImplementedError(
            "V0.27.1 KeyringSecretStore 是占位 stub, V0.28 实现 (跨平台 keyring lib). "
            "当前用 EnvSecretStore() 默 backend."
        )

    def has(self, key: str) -> bool:
        raise NotImplementedError(
            "V0.27.1 KeyringSecretStore 占位 stub, V0.28 实现."
        )


def default_store() -> SecretStore:
    """V0.27.1: 默 SecretStore — EnvSecretStore. make_client 默调用避免 None check 散乱.

    V0.28 加 keyring backend 时只改本函数 (e.g. KeyringSecretStore() if env enabled else
    EnvSecretStore()), make_client / anthropic.py / openai.py 0 改.
    """
    return EnvSecretStore()
