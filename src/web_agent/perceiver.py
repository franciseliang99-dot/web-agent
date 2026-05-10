"""SoM (Set-of-Mark) JS 注入 + 截图 + DOM 瘦身 + 自动关 cookie/GDPR 弹窗。"""

from __future__ import annotations

import base64
import logging
import os
from typing import cast

from playwright.async_api import Frame, Page

from web_agent.types import BBox, Mark  # V0.16.9 上提到 web_agent.types — re-export 保持旧 import 路径

logger = logging.getLogger(__name__)


_SOM_INJECT_JS = """
(opts) => {
  const sel = 'a, button, input, textarea, select, [role="button"], [role="link"], [role="textbox"], [role="checkbox"], [role="tab"], [role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"], [role="option"], [role="combobox"], [role="switch"], [role="radio"], [contenteditable="true"]';
  // W5-B Shadow DOM 穿透: stack-based open shadowRoot walker
  // light DOM first → 各 open shadowRoot, WeakSet visited 防自引用; closed mode 跳过 (W3C 设计 JS 不可达)
  const SHADOW_ON = !opts || opts.shadow !== false;
  // V0.22.1: id_offset 让 iframe 内 SoM id 跟 Python Mark.id 全局一致 (无 drift).
  // 视觉框 tag.textContent + 返回 dict.id 都 ref 同一 id 变量, 三方自动一致.
  const ID_OFFSET = (opts && opts.id_offset) || 0;
  const collected = [];
  const visited = new WeakSet();
  const stack = [document];
  while (stack.length) {
    const root = stack.pop();
    if (visited.has(root)) continue;
    visited.add(root);
    root.querySelectorAll(sel).forEach(e => collected.push(e));
    if (!SHADOW_ON) continue;
    root.querySelectorAll('*').forEach(e => {
      if (e.shadowRoot && e.shadowRoot.mode === 'open' && !visited.has(e.shadowRoot)) {
        stack.push(e.shadowRoot);
      }
    });
  }
  const els = collected.filter(e => {
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
  // V0.22.2: 清旧 data-som-id (上次 perceive 残留) 防 actuator 走错 id;
  // 跨 open shadowRoot walker (跟主收集 selector 同模式).
  {
    const visited = new WeakSet();
    const stack = [document];
    while (stack.length) {
      const root = stack.pop();
      if (visited.has(root)) continue;
      visited.add(root);
      root.querySelectorAll('[data-som-id]').forEach(e => e.removeAttribute('data-som-id'));
      if (!SHADOW_ON) continue;
      root.querySelectorAll('*').forEach(e => {
        if (e.shadowRoot && e.shadowRoot.mode === 'open' && !visited.has(e.shadowRoot)) {
          stack.push(e.shadowRoot);
        }
      });
    }
  }
  const colors = ['#FF3B30', '#34C759', '#007AFF', '#AF52DE', '#FF9500', '#5AC8FA'];
  return els.map((el, i) => {
    const r = el.getBoundingClientRect();
    const id = i + 1 + ID_OFFSET;  // V0.22.1: iframe 路径下 offset>0
    // V0.22.2: 给元素挂 data-som-id 让 actuator iframe 路径走 frame.locator(`[data-som-id="N"]`)
    el.setAttribute('data-som-id', String(id));
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
    const tagName = el.tagName.toLowerCase();
    return {
      id,
      tag: tagName,
      role: el.getAttribute('role') || '',
      text: text.trim().slice(0, 80),
      bbox: {
        x: r.left + window.scrollX,
        y: r.top + window.scrollY,
        w: r.width,
        h: r.height,
      },
      input_type: tagName === 'input' ? (el.type || '') : '',
      name: el.name || el.id || '',
      href: tagName === 'a' ? (el.href || '') : '',
    };
  });
}
"""

_SOM_REMOVE_JS = """
() => {
  // 移除 SoM 视觉框 div (截图后调, 让 LLM 看到有框的截图但页面回归干净视觉)
  // V0.22.2: data-som-id **故意留**给 actuator 后续 frame.locator 用; 下次 perceive 入口
  // 在 _SOM_INJECT_JS 内自动清旧 data-som-id 再注入新, 不污染跨步骤 selector.
  // agent 退出关 Chrome 时 data-som-id 随 page 一并消失, 不污染用户长留 session.
  document.querySelectorAll('[data-som-mark]').forEach(e => e.remove());
}
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
        return cast(list[str], dismissed)
    except Exception as e:
        logger.warning("auto-dismiss failed: %r", e)
        return []


def _raw_to_marks(raw: list[dict[str, object]], frame_path: str) -> list[Mark]:
    """V0.22.1: JS evaluate 返回的 raw dict 列表 → Mark[] 加 frame_path."""
    return [
        Mark(
            id=cast(int, m["id"]), tag=cast(str, m["tag"]), role=cast(str, m["role"]),
            text=cast(str, m["text"]),
            bbox=cast(BBox, m["bbox"]),  # SoM JS 保证 x/y/w/h float
            input_type=cast(str, m.get("input_type", "")),
            name=cast(str, m.get("name", "")),
            href=cast(str, m.get("href", "")),
            frame_path=frame_path,
        )
        for m in raw
    ]


async def _inject_som_in_frame(
    frame: Frame, frame_path: str, shadow_on: bool, id_offset: int,
) -> list[Mark]:
    """V0.22.1: 单 frame 注入 SoM 并返 marks (frame_path + id_offset 已绑).

    主 frame 调用方不 catch (fail-fast 跟 V0.22.0 行为对齐); 子 frame 调用方裹 try.
    """
    raw = await frame.evaluate(_SOM_INJECT_JS, {"shadow": shadow_on, "id_offset": id_offset})
    return _raw_to_marks(cast(list[dict[str, object]], raw), frame_path)


async def _remove_som_in_frame(frame: Frame) -> None:
    """V0.22.1: 每 frame 都跑 _SOM_REMOVE_JS 防残留污染下次 perceive."""
    try:
        await frame.evaluate(_SOM_REMOVE_JS)
    except Exception as e:
        logger.warning("frame %r remove SoM failed (non-fatal): %r", frame.url[:80], e)


async def _walk_child_frames(
    parent: Frame, parent_path: str, shadow_on: bool, marks: list[Mark],
) -> None:
    """V0.22.1: DFS 递归注入 child frame SoM, 累加到 marks. 跨域/detached frame 跳过子树.

    每层用 `len(marks)` 作 id_offset → 全局 id 连续无冲突. frame_path 编码深度优先索引,
    主 frame 父调用 path="", 第 1 个 child path="0", child 的第 2 个 child path="0.1".
    """
    for i, child in enumerate(parent.child_frames):
        child_path = f"{parent_path}.{i}" if parent_path else str(i)
        try:
            # 等 iframe load 防 timing 抢跑; timeout 短 (2s) 防慢站拖整体 perceive.
            await child.wait_for_load_state("domcontentloaded", timeout=2000)
            child_marks = await _inject_som_in_frame(
                child, child_path, shadow_on, id_offset=len(marks),
            )
        except Exception as e:
            logger.warning(
                "frame %r (path=%s) SoM inject failed (cross-origin/detached?), 跳过子树: %r",
                child.url[:80], child_path, e,
            )
            continue  # 跨域父跳了子也访问不到, 整子树 skip
        marks.extend(child_marks)
        await _walk_child_frames(child, child_path, shadow_on, marks)
        await _remove_som_in_frame(child)


async def perceive(page: Page) -> tuple[list[Mark], str]:
    """先尝试关弹窗 → 注入 SoM 标注 (主 frame + 同源 iframe) → 截带标注的视口图 → 移除标注。

    auto-dismiss 在 SoM 注入**之前**执行，避免关弹窗后 mark 编号错位 (只在主 frame 跑,
    iframe dismiss 留 V0.22.4).
    截图含 SoM 红框 + 数字角标，直接给 LLM 看；返回前已清掉标注 DOM 节点不污染页面。

    V0.22.1: 同源 iframe 也注入 SoM 让 LLM 看到 reCAPTCHA 风格 widget 内元素;
    跨域 frame.evaluate fail → catch warn 跳整子树 (留 V0.22.3 加 a11y fallback);
    主 frame fail 不 catch (fail-fast — silent 空 marks 会让 loop 误判页面无元素死循环).
    id 全局连续: 主 frame 1..N, 第 1 个 iframe N+1..N+M, ... (用 id_offset 注入 JS, 视觉框
    数字 == Python Mark.id 三方一致).
    """
    dismissed = await maybe_auto_dismiss(page)
    if dismissed:
        logger.info("auto-dismissed %d popup(s): %s", len(dismissed), dismissed)
    # W5-B: WEB_AGENT_SOM_SHADOW=false 退化到 V0.11.x light-DOM only 行为
    shadow_on = os.environ.get("WEB_AGENT_SOM_SHADOW", "true").lower() not in ("false", "0", "no", "off")
    # 主 frame 不 catch (fail-fast 跟 V0.22.0 行为对齐)
    marks = await _inject_som_in_frame(page.main_frame, "", shadow_on, id_offset=0)
    # 同源 iframe DFS
    await _walk_child_frames(page.main_frame, "", shadow_on, marks)
    screenshot_bytes = await page.screenshot(type="png", full_page=False)
    # cleanup 主 frame 的 SoM (iframe 已在 _walk_child_frames 内 cleanup 完)
    await _remove_som_in_frame(page.main_frame)
    return marks, base64.b64encode(screenshot_bytes).decode()


def marks_to_text(marks: list[Mark]) -> str:
    """把 marks 列表序列化成给 LLM 的简洁文本（DOM 瘦身）。

    V0.22.0: 加 `@<frame_path>` 后缀标记 iframe 内元素 (主 frame 不显示).
    LLM 看到 `@0` / `@0.2` 知道该 mark 在嵌套 iframe; actuator V0.22.2 自动按 frame_path 路由.
    """
    lines = []
    for m in marks:
        s = f"[{m.id}] <{m.tag}"
        if m.role:
            s += f" role={m.role}"
        s += ">"
        if m.text:
            s += f" {m.text!r}"
        if m.href:
            s += f" → {m.href}"  # V0.20.8: a[href] 暴露给 LLM (list extract 必须看到 link target)
        if m.frame_path:
            s += f" @{m.frame_path}"  # V0.22.0: iframe 路径
        lines.append(s)
    return "\n".join(lines)
