"""验证码接管 (W4-2): 检测页面 captcha widget, 让用户在浏览器手解, 自动恢复 loop.

蓝本 + README 明示: 不接 2Captcha 自动绕 (越线), 走「暂停 → 用户解 → 恢复循环」UX。

支持 4 vendor:
- cloudflare-turnstile: iframe[src*="challenges.cloudflare.com"], .cf-turnstile
- recaptcha (v2 visible): iframe[src*="google.com/recaptcha"], .g-recaptcha
- hcaptcha: iframe[src*="hcaptcha.com"], .h-captcha
- google-verify: body 文本 "verify you're not a robot" / "I'm not a robot" / "我不是机器人"

visibility 过滤掉 0×0 隐形 reCAPTCHA v3 (常驻 SaaS 站, 永远存在则无意义)。

依赖方向 (按 CLAUDE.md 解耦): domain (Page) → captcha.py (本文件, 纯检测) ← loop.py (业务调用)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from playwright.async_api import Page

# 优先级 cloudflare > recaptcha > hcaptcha > google-verify;
# visibility 过滤 (offsetWidth/Height + bbox 在视口) 排除隐形 v3 占位
_DETECT_JS = """
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1 && r.bottom > 0 && r.top < window.innerHeight;
  };
  const probe = (sel, vendor) => {
    for (const el of document.querySelectorAll(sel)) {
      if (visible(el)) return {hit: true, vendor, url: el.src || location.href};
    }
    return null;
  };
  const cf = probe('iframe[src*="challenges.cloudflare.com"], .cf-turnstile, [class*="cf-challenge"]', "cloudflare-turnstile");
  if (cf) return cf;
  const rc = probe('iframe[src*="google.com/recaptcha"], .g-recaptcha', "recaptcha");
  if (rc) return rc;
  const hc = probe('iframe[src*="hcaptcha.com"], .h-captcha', "hcaptcha");
  if (hc) return hc;
  const body = ((document.body && document.body.innerText) || '').slice(0, 2000).toLowerCase();
  if (body.includes("verify you're not a robot")
      || body.includes("i'm not a robot")
      || body.includes("我不是机器人")) {
    return {hit: true, vendor: "google-verify", url: location.href};
  }
  return {hit: false};
}
"""


@dataclass
class CaptchaInfo:
    vendor: str
    url: str


async def detect(page: Page) -> CaptchaInfo | None:
    """检测页面 captcha; 命中返回 CaptchaInfo, 无则 None。

    捕获所有异常 → None: page 在 navigate 中或 fake page 缺 evaluate 不该崩 loop。
    """
    try:
        info = await page.evaluate(_DETECT_JS)
    except Exception:
        return None
    if not info or not info.get("hit"):
        return None
    return CaptchaInfo(
        vendor=info.get("vendor", "unknown"),
        url=info.get("url", ""),
    )


async def wait_for_resolution(
    page: Page, timeout_s: float = 300.0, poll_s: float = 3.0
) -> bool:
    """轮询 detect() 直到 captcha 清除 / 超时。清除返回 True, 超时 False。

    - 用 asyncio.sleep 不阻塞 event loop
    - 每次 detect 命中异常返回 None → 视作清除 (与 detect() 语义一致)
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if await detect(page) is None:
            return True
        await asyncio.sleep(poll_s)
    return False
