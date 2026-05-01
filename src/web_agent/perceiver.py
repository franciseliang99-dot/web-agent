"""SoM (Set-of-Mark) JS 注入 + 截图 + DOM 瘦身。"""

from __future__ import annotations

import base64
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
  const sel = 'a, button, input, textarea, select, [role="button"], [role="link"], [role="textbox"], [role="checkbox"], [role="tab"], [contenteditable="true"]';
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


async def perceive(page: Page) -> tuple[list[Mark], str]:
    """注入 SoM 标注、截带标注的视口图、移除标注，返回 (marks, base64_png)。

    注：截图含 SoM 红框 + 数字角标，直接给 LLM 看；返回前已清掉标注 DOM 节点不污染页面。
    """
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
