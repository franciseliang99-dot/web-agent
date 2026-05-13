"""V0.58.1: 代理层 env 接入 helper (V0.48.2 #26 催生).

V0.48.2 真发现 #26 IP-level baseline 拦 (akamai 跨 visit 直接 403). 解决路径 = 代理层换出口 IP.

Env schema: `WEB_AGENT_PROXY = http://user:pw@host:port / socks5://host:port / 空`. 2 launch
path 共用 (scripts/start_chrome.sh 直读, Python direct launch 调 `parse_proxy_env()` 拆结构化).

依赖方向 (CLAUDE.md 解耦): stdlib only (`os`, `urllib.parse`), 0 第三方. 不依赖 web_agent.*
(allow util 在 cli/eval/test 任处复用, 不引循环).

Secret 处理 (CLAUDE.md secrets): env-only, 解析后 caller log 仅 host:port. 本模块不 print 任何
auth (caller 决定 log 时 mask).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    """V0.58.1: 解析后 proxy 配置 (Playwright launch kwargs 兼容 dict 形式).

    Args:
        server: 'http://host:port' / 'socks5://host:port' (scheme + netloc, 无 auth).
        username: basic auth user (空字符串 == 无 auth).
        password: basic auth pass (空字符串 == 无 auth).
        raw: 原始 env 值 (debug 用; caller 不应 log raw).
    """

    server: str
    username: str
    password: str
    raw: str

    def to_playwright_kwargs(self) -> dict[str, str]:
        """V0.58.1: 转 Playwright `browser.new_context(proxy={...})` / `chromium.launch(proxy={...})` kwargs.

        Playwright 接受 `server` 必填 + `username`/`password` 可选. 空 auth 时不传 username/password
        (Playwright sig 不报 error 但 explicit 不传更干净).
        """
        kwargs: dict[str, str] = {"server": self.server}
        if self.username:
            kwargs["username"] = self.username
        if self.password:
            kwargs["password"] = self.password
        return kwargs

    def masked(self) -> str:
        """V0.58.1: log-safe 形式 — `scheme://<auth>@host:port` 仅 mask auth, host/port 留可调试."""
        if self.username:
            return f"{self.server.split('://', 1)[0]}://<auth>@{self.server.split('://', 1)[1]}"
        return self.server


def parse_proxy_env(env_value: str | None = None) -> ProxyConfig | None:
    """V0.58.1: 解析 `WEB_AGENT_PROXY` env URL → ProxyConfig. 空 / unset / 无效 → None.

    Args:
        env_value: 显式传 (test 用); None → 读 `os.environ["WEB_AGENT_PROXY"]`.

    Returns:
        ProxyConfig 或 None (env 空 / 不可解析 → None, caller skip proxy 接入).

    解析规则:
    - 空 / `unset` → None (autonomous 默关)
    - 缺 scheme → None (防意外 host:port without http:// 被错误解析)
    - 有效 URL → ProxyConfig(server=scheme://host:port, username/password from URL netloc)
    """
    if env_value is None:
        env_value = os.environ.get("WEB_AGENT_PROXY", "").strip()
    else:
        env_value = env_value.strip()
    if not env_value:
        return None
    parsed = urlparse(env_value)
    if not parsed.scheme or not parsed.hostname:
        return None  # 缺 scheme / hostname → 不可用
    port_suffix = f":{parsed.port}" if parsed.port else ""
    server = f"{parsed.scheme}://{parsed.hostname}{port_suffix}"
    return ProxyConfig(
        server=server,
        username=parsed.username or "",
        password=parsed.password or "",
        raw=env_value,
    )


__all__ = ["ProxyConfig", "parse_proxy_env"]
