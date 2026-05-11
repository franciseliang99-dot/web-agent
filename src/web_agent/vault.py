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
        # V0.31.2: try/except RuntimeError 防 keyring extra 未装时 ChainedSecretStore.has 链断
        # (subagent 决: get 已 except Exception 返 default, has 同模式吞 RuntimeError 让 chain
        # 自然 fallback 下个 store).
        try:
            return self.get(key) is not None
        except RuntimeError:
            return False

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


# V0.31.1 cli web-agent-vault list 命令枚举的 web-agent 自管 key 集 (硬编码).
# 用户自定义 key 不显示 (V0.32 加 index-key 方案 — 维护 set 同步 set/delete).
_KNOWN_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
)


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
    """V0.27.1+V0.31.2: 默 SecretStore. opt-in env `WEB_AGENT_USE_KEYRING=1` 切
    `ChainedSecretStore([KeyringSecretStore(), EnvSecretStore()])` (Keyring 优先 / Env fallback).
    默仍 `EnvSecretStore()` 100% 兼容老 caller (V0.32 评估改默).

    keyring extra 未装时 (env=1 但 pip install web-agent[keyring] 没跑): ChainedSecretStore.has
    短路 — KeyringSecretStore.has 内 try/except RuntimeError 返 False (V0.31.2 修), 自然
    fallback EnvSecretStore. caller 0 改, lazy import 哲学保留.
    """
    use_keyring = os.environ.get("WEB_AGENT_USE_KEYRING", "").lower() in ("true", "1", "yes")
    if use_keyring:
        return ChainedSecretStore([KeyringSecretStore(), EnvSecretStore()])
    return EnvSecretStore()


class MissingSecretError(RuntimeError):
    """V0.27.4: SecretStore 缺 key 时 raise — RuntimeError 子类保 V0.27.1 14 测兼容.

    带 `key` attr 让 mcp_server elicit retry 知道 prompt 哪个 key 名 (不靠 message 字符串
    parsing 脆点 — Plan subagent 决: 比 message-startswith 检测干净).
    """

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"{key} 未设置 — 请填 .env 或 export 环境变量")


def main(argv: list[str] | None = None) -> int:
    """V0.31.1: web-agent-vault cli — set/get/delete/list keyring vault.

    subagent 7 决策全采纳:
    - argparse subparsers 4 子命令 (set/get/delete/list)
    - set 默 getpass 隐式输入 + opt-in --from-stdin (CI 自动化), 非 tty 强制 --from-stdin (拒 silent fallback)
    - get 默真显 (用户调显式取值, mask 反烦; shell hist 风险用户自管 HISTCONTROL=ignorespace)
    - delete 不询问 (scriptable cli 默不交互), missing key 友好 stderr + exit 1
    - list 仅枚举 _KNOWN_KEYS (硬编码 ANTHROPIC/OPENAI key + URL), 显 SET/MISSING 不显 value
    - keyring extra 未装 → RuntimeError catch + exit 3 + 提示 pip install 'web-agent[keyring]'
    """
    import argparse
    import getpass
    import sys

    parser = argparse.ArgumentParser(
        prog="web-agent-vault",
        description="V0.31.1 keyring vault cli — 跨平台 OS-native secret store (macOS keychain / "
                    "Linux Secret Service / Windows Credential Manager). 需装 extra: "
                    "pip install 'web-agent[keyring]'",
        epilog=(
            "V0.31.2: opt-in env `WEB_AGENT_USE_KEYRING=1` 切默 SecretStore backend → "
            "ChainedSecretStore([Keyring, Env]). Keyring 优先 / Env 自动 fallback (extra 未装时 "
            "也安全). 默 EnvSecretStore 完全兼容. export 永久: "
            "`echo 'export WEB_AGENT_USE_KEYRING=1' >> ~/.bashrc`"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp_set = sub.add_parser("set", help="写 key 到 keyring (默 getpass 隐式输入)")
    sp_set.add_argument("key", help="key 名 (e.g. ANTHROPIC_API_KEY)")
    sp_set.add_argument(
        "--from-stdin", action="store_true",
        help="从 stdin 读 value (CI/自动化用; 非 tty 终端强制此 flag)",
    )

    sp_get = sub.add_parser("get", help="读 key value (默真显)")
    sp_get.add_argument("key")

    sp_del = sub.add_parser("delete", help="删 key (不询问)")
    sp_del.add_argument("key")

    sub.add_parser("list", help=f"列已知 key SET/MISSING 状态 (枚举 {len(_KNOWN_KEYS)} 个 web-agent 自管 key)")

    args = parser.parse_args(argv)

    store = KeyringSecretStore()

    try:
        if args.cmd == "set":
            if args.from_stdin:
                value = sys.stdin.read().rstrip("\n")
            else:
                if not sys.stdin.isatty():
                    sys.stderr.write(
                        "ERROR: stdin 非 tty 终端必须用 --from-stdin (防 getpass silent fallback echo 泄 password).\n"
                        "用法: echo 'sk-xxx' | web-agent-vault set ANTHROPIC_API_KEY --from-stdin\n",
                    )
                    return 1
                value = getpass.getpass(f"Enter value for {args.key}: ")
            if not value:
                sys.stderr.write("ERROR: value 不能为空 (空串拒).\n")
                return 1
            store.set(args.key, value)
            sys.stdout.write(f"OK: {args.key} 已写入 keyring (service=web-agent).\n")
            return 0

        if args.cmd == "get":
            v = store.get(args.key)
            if v is None:
                sys.stderr.write(f"ERROR: key {args.key!r} 不在 keyring (set 先).\n")
                return 1
            sys.stdout.write(f"{v}\n")
            return 0

        if args.cmd == "delete":
            try:
                store.delete(args.key)
            except Exception as e:  # noqa: BLE001 — keyring.errors.PasswordDeleteError 等
                sys.stderr.write(f"ERROR: 删 {args.key!r} 失败 ({type(e).__name__}: {e})\n")
                return 1
            sys.stdout.write(f"OK: {args.key} 已删.\n")
            return 0

        if args.cmd == "list":
            for k in _KNOWN_KEYS:
                status = "SET" if store.has(k) else "MISSING"
                sys.stdout.write(f"  {k}: {status}\n")
            return 0

    except RuntimeError as e:
        # KeyringSecretStore lazy import 失败 (keyring extra 未装) → 友好提示
        sys.stderr.write(f"ERROR: {e}\n")
        return 3

    return 0  # unreachable (subparsers required=True)


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
