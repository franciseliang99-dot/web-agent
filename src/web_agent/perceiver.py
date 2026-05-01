"""SoM (Set-of-Mark) JS 注入 + 截图 + DOM 瘦身 + 自动关 cookie/GDPR 弹窗。"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from playwright.async_api import Page


@dataclass
class Mark:
    id: int
    tag: str
    role: str
    text: str
    bbox: dict  # {x, y, w, h}（相对页面坐标，含 scroll）


_SOM_INJECT_JS = """
() => {
  const sel = 'a, button, input, textarea, select, [role="button"], [role="link"], [role="textbox"], [role="checkbox"], [role="tab"], [role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"], [role="option"], [role="combobox"], [role="switch"], [role="radio"], [contenteditable="true"]';
  const all = Array.from(document.querySelectorAll(sel));
  const els = all.filter(e => {
    const r = e.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) return false;
    if (r.bottom < 0 || r.top > window.innerHeight) return false;
    if (r.right < 0 || r.left > window.innerWidth) return false;
    const style = window.getComputedStyle(e);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    if (parseFloat(style.opacity) < 0.05) return false;
    return true;
  });
  document.querySelectorAll('[data-som-mark]').forEach(e => e.remove());
  const colors = ['#FF3B30', '#34C759', '#007AFF', '#AF52DE', '#FF9500', '#5AC8FA'];
  return els.map((el, i) => {
    const r = el.getBoundingClientRect();
    const id = i + 1;
    const color = colors[i % colors.length];
    const box = document.createElement('div');
    box.dataset.somMark = 'box';
    Object.assign(box.style, {
      position: 'fixed', left: r.left + 'px', top: r.top + 'px',
      width: r.width + 'px', height: r.height + 'px',
      border: '2px solid ' + color, pointerEvents: 'none', zIndex: '2147483646',
      boxSizing: 'border-box', borderRadius: '2px',
    });
    const tag = document.createElement('div');
    tag.dataset.somMark = 'tag';
    tag.textContent = id;
    Object.assign(tag.style, {
      position: 'fixed', left: r.left + 'px', top: Math.max(0, r.top - 18) + 'px',
      background: color, color: 'white',
      font: 'bold 12px monospace', padding: '0 4px',
      pointerEvents: 'none', zIndex: '2147483647', borderRadius: '2px',
    });
    document.body.appendChild(box);
    document.body.appendChild(tag);
    const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '') + '';
    return {
      id,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      text: text.trim().slice(0, 80),
      bbox: {
        x: r.left + window.scrollX,
        y: r.top + window.scrollY,
        w: r.width,
        h: r.height,
      },
    };
  });
}
"""

_SOM_REMOVE_JS = """
() => { document.querySelectorAll('[data-som-mark]').forEach(e => e.remove()); }
"""


# 自动关常见 cookie/GDPR/notification 弹窗。在 SoM 注入之前跑一次。
# 容器筛选：必须含 cookie/consent/gdpr/notif/policy 关键词；按钮文本严格 anchored regex；
# 黑名单：含 password/sign in/login/pay/支付 直接 skip（保护 OAuth/付款 dialog）
_AUTO_DISMISS_JS = """
() => {
  const ACCEPT = /^(accept|accept all|accept cookies|got it|i agree|i accept|ok|okay|allow all|allow|continue|close|dismiss|同意|全部接受|接受|知道了|我知道了|确定|允许|继续|关闭|关闭弹窗)$/i;
  const SKIP = /(password|sign[\\s-]?in|log[\\s-]?in|登录|登入|登陆|pay|payment|confirm|checkout|支付|付款|结算|order|确认订单|delete|删除)/i;
  const containers = document.querySelectorAll(
    '[role="dialog"], [aria-modal="true"], ' +
    '[class*="cookie" i], [class*="consent" i], ' +
    '[id*="cookie" i], [id*="consent" i], ' +
    '[class*="gdpr" i], [class*="banner" i], ' +
    '[class*="notif" i]'
  );
  const dismissed = [];
  for (const c of containers) {
    const containerText = (c.innerText || '').slice(0, 500);
    if (SKIP.test(containerText)) continue;
    const ctxLower = (c.className + ' ' + (c.id || '') + ' ' + containerText).toLowerCase();
    if (!/cookie|consent|gdpr|notif|policy|banner/i.test(ctxLower)) continue;
    const buttons = c.querySelectorAll('button, [role="button"], a');
    for (const b of buttons) {
      const txt = (b.innerText || b.getAttribute('aria-label') || '').trim();
      if (ACCEPT.test(txt) && !SKIP.test(txt)) {
        b.click();
        dismissed.push(txt.slice(0, 40));
        break;
      }
    }
  }
  return dismissed;
}
"""


async def maybe_auto_dismiss(page: Page) -> list[str]:
    """如果 WEB_AGENT_AUTO_DISMISS != false，扫描 cookie/GDPR/notification 弹窗并 click 接受按钮。

    严格白名单（容器必须含 cookie/consent/gdpr/notif/policy/banner 关键词）+
    黑名单文本（password/sign in/pay 直接 skip）保护 OAuth / 付款类 modal。
    返回被 dismiss 的按钮文本列表（用于日志）。
    """
    if os.environ.get("WEB_AGENT_AUTO_DISMISS", "true").lower() in ("false", "0", "no", "off"):
        return []
    try:
        dismissed = await page.evaluate(_AUTO_DISMISS_JS)
        if dismissed:
            await page.wait_for_timeout(300)  # 等弹窗关闭动画
        return dismissed
    except Exception as e:
        print(f"[perceive] auto-dismiss failed: {e!r}")
        return []


async def perceive(page: Page) -> tuple[list[Mark], str]:
    """先尝试关弹窗 → 注入 SoM 标注 → 截带标注的视口图 → 移除标注，返回 (marks, base64_png)。

    auto-dismiss 在 SoM 注入**之前**执行，避免关弹窗后 mark 编号错位。
    截图含 SoM 红框 + 数字角标，直接给 LLM 看；返回前已清掉标注 DOM 节点不污染页面。
    """
    dismissed = await maybe_auto_dismiss(page)
    if dismissed:
        print(f"[perceive] auto-dismissed {len(dismissed)} popup(s): {dismissed}")
    raw = await page.evaluate(_SOM_INJECT_JS)
    marks = [
        Mark(id=m["id"], tag=m["tag"], role=m["role"], text=m["text"], bbox=m["bbox"])
        for m in raw
    ]
    screenshot_bytes = await page.screenshot(type="png", full_page=False)
    await page.evaluate(_SOM_REMOVE_JS)
    return marks, base64.b64encode(screenshot_bytes).decode()


def marks_to_text(marks: list[Mark]) -> str:
    """把 marks 列表序列化成给 LLM 的简洁文本（DOM 瘦身）。"""
    lines = []
    for m in marks:
        s = f"[{m.id}] <{m.tag}"
        if m.role:
            s += f" role={m.role}"
        s += ">"
        if m.text:
            s += f" {m.text!r}"
        lines.append(s)
    return "\n".join(lines)
