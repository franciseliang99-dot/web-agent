"""V0.47.1: 防护识别 — autonomous scope 第一层 (L1/L2 静态/动态识别).

互补 captcha.py (页面侧 JS probe 4 vendor) — 本模块 = network 侧 response listener 抓 main-frame
headers/cookies/status. 不切武器 (V0.48+ maintainer 红线), 仅 observe + 分类.

依赖方向 (按 CLAUDE.md 解耦):
domain (ProtectionSignal/ProtectionLevel) ← protection.py (本, 纯函数) ← browser.py (装 listener)
                                                                     ← memory.py (V0.47.2 持久化)
                                                                     ← cli/loop (V0.47.3 inject)

V0.47.1 scope: ProtectionSignal + classify 纯函数 + listener factory. 不动 memory.py / loop.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Response

logger = logging.getLogger(__name__)


ProtectionLevel = Literal["low", "medium", "high", "unknown"]


@dataclass(frozen=True, slots=True)
class ProtectionSignal:
    """V0.47.1: 单次 main-frame response 防护信号 (network 侧).

    Args:
        server: response 'server' header (e.g. 'cloudflare', 'AkamaiGHost').
        status: HTTP status code.
        cookies: set-cookie 中 name (lowercase) — cf_clearance / datadome / __cfduid 等. 值不存.
        cf_ray: cf-ray header (CF 通用).
        captcha_vendor: captcha.py JS probe 命中的 vendor (空表无).
    """

    server: str = ""
    status: int = 0
    cookies: frozenset[str] = frozenset()
    cf_ray: str = ""
    captcha_vendor: str = ""


# 高防 WAF/CDN server header 关键词 (substring match, lowercase)
_HIGH_PROTECTION_SERVERS: frozenset[str] = frozenset({
    "cloudflare",   # CF (含 turnstile)
    "akamaighost",  # Akamai
    "akamai",       # Akamai variants
    "datadome",     # DataDome
    "incapsula",    # Imperva Incapsula
})

# 高防 challenge-passed cookie 名 (lowercase prefix)
_HIGH_PROTECTION_COOKIES: frozenset[str] = frozenset({
    "cf_clearance",   # CF challenge passed
    "datadome",       # DataDome
    "__cfduid",       # CF legacy uid
    "incap_ses",      # Imperva Incapsula session
    "visid_incap",    # Imperva visitor id
    "akamai_bot",     # Akamai bot manager
    "ak_bmsc",        # Akamai bot manager cookie
})


def classify(signal: ProtectionSignal) -> ProtectionLevel:
    """V0.47.1: 根据 ProtectionSignal 分类防护等级 (CLAUDE.md 模型 vs 代码边界 — 字段已能回答).

    分类规则 (按优先级):
    - **high**: status 403/503 OR captcha_vendor 命中 OR cookie 含 challenge-passed prefix
    - **medium**: status 429 频率限制 OR server 高防关键词 (但无 challenge cookie 或 captcha vendor)
    - **low**: status 200/3xx + server 不在高防 set + 无防护 cookie + 无 captcha vendor
    - **unknown**: 数据不足 (status=0 + 无 server + 无 cookies + 无 captcha vendor)
    """
    if (
        signal.status == 0
        and not signal.server
        and not signal.cookies
        and not signal.captcha_vendor
    ):
        return "unknown"

    if signal.status in (403, 503):
        return "high"
    if signal.captcha_vendor:
        return "high"
    if any(c.startswith(prefix) for c in signal.cookies for prefix in _HIGH_PROTECTION_COOKIES):
        return "high"

    if signal.status == 429:
        return "medium"
    server_low = signal.server.lower()
    if any(s in server_low for s in _HIGH_PROTECTION_SERVERS):
        return "medium"

    return "low"


def attach_protection_listener(ctx: "BrowserContext") -> None:
    """V0.47.1: 给 ctx 装 main-frame response listener, 累积 ProtectionSignal 到
    `ctx._web_agent_protection_signals` (list, 跟 popup/download monkey-patch flag 同模式).

    幂等: 重装 silent. main-frame document response 过滤 (跳 iframe / image / css / js noise).
    handler 异常 silent swallow (跟 captcha/memory record 同档, 不阻塞主路径).
    """
    if getattr(ctx, "_web_agent_protection_listener", False):
        return

    if not getattr(ctx, "_web_agent_protection_signals", None):
        ctx._web_agent_protection_signals = []  # type: ignore[attr-defined]

    async def handler(response: "Response") -> None:
        try:
            if response.request.resource_type != "document":
                return
            if response.frame.parent_frame is not None:
                return  # iframe 内 document 跳

            headers = response.headers  # sync property, lowercase keys dict
            server = headers.get("server", "")
            cf_ray = headers.get("cf-ray", "")
            set_cookie_str = headers.get("set-cookie", "")

            cookies: set[str] = set()
            for chunk in set_cookie_str.split("\n"):
                name_eq, _, _ = chunk.strip().partition("=")
                if name_eq:
                    cookies.add(name_eq.strip().lower())

            signal = ProtectionSignal(
                server=server,
                status=response.status,
                cookies=frozenset(cookies),
                cf_ray=cf_ray,
            )
            ctx._web_agent_protection_signals.append(signal)  # type: ignore[attr-defined]
        except Exception as e:
            logger.debug("protection listener 失败 (non-fatal): %r", e)

    ctx.on("response", handler)
    ctx._web_agent_protection_listener = True  # type: ignore[attr-defined]


__all__ = [
    "ProtectionLevel",
    "ProtectionSignal",
    "attach_protection_listener",
    "classify",
]
