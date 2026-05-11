"""SoM (Set-of-Mark) JS 注入 + 截图 + DOM 瘦身 + 自动关 cookie/GDPR 弹窗。"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import replace
from typing import cast
from urllib.parse import urlparse

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
    tag.dataset.somId = String(id);  // V0.34.4: renumber 时同步改 attr + textContent 一致
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

_SOM_RENUMBER_JS = """
(opts) => {
  // V0.34.4: 把 DOM data-som-id (元素 + 视觉框 tag) 从局部 id 改到全局 DFS 顺序 id.
  // F1 同层 sibling iframe SoM inject 用 asyncio.gather 并发, 各 frame 内部 id_offset=0
  // 局部 1..N_local, Python 端 DFS 拼后 renumber, 调本 JS 修 DOM 端同步.
  // opts.id_map: {old_id_str: new_id_int} per-frame (主调用方 dict[str(old)] = new).
  // opts.shadow: bool 跟 _SOM_INJECT_JS 同 SHADOW_ON 模式 (穿透 open shadowRoot).
  const idMap = opts && opts.id_map ? opts.id_map : {};
  const SHADOW_ON = !opts || opts.shadow !== false;
  const visited = new WeakSet();
  const stack = [document];
  while (stack.length) {
    const root = stack.pop();
    if (visited.has(root)) continue;
    visited.add(root);
    // 元素层 data-som-id (actuator frame.locator('[data-som-id="N"]') 路径)
    root.querySelectorAll('[data-som-id]').forEach(e => {
      const old = e.getAttribute('data-som-id');
      if (old !== null && idMap[old] !== undefined) {
        const newId = idMap[old];
        e.setAttribute('data-som-id', String(newId));
        // 视觉框 tag 同步 textContent (LLM 看到的数字)
        if (e.dataset.somMark === 'tag') {
          e.textContent = String(newId);
        }
      }
    });
    if (!SHADOW_ON) continue;
    root.querySelectorAll('*').forEach(e => {
      if (e.shadowRoot && e.shadowRoot.mode === 'open' && !visited.has(e.shadowRoot)) {
        stack.push(e.shadowRoot);
      }
    });
  }
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


def _frame_host(frame: Frame) -> str:
    """V0.22.4: 从 frame.url 解析 host (cross-origin iframe LLM 不可见内容时给 LLM 看的 hint).

    跨域 frame.url 仍可读 (来自父 frame attach 时看到的 src). urlparse 失败/netloc 空
    (data:/about:blank/javascript:) → fallback url[:60] 原串; 极端 detach url 属性也 raise →
    fallback "(unknown)".
    """
    try:
        url = getattr(frame, "url", "") or ""
    except Exception:
        return "(unknown)"
    if not url:
        return "(unknown)"
    try:
        netloc = urlparse(url).netloc
        return netloc if netloc else url[:60]
    except Exception:
        return url[:60]


async def _process_child_frame_concurrent(
    child: Frame, child_path: str, shadow_on: bool,
) -> tuple[list[Mark], list[tuple[Frame, str, int]], list[str]]:
    """V0.34.4 F1 helper: 单 child frame 处理 (id_offset=0 局部 id), 返 functional tuple.

    返:
      - local + sub marks (DFS 顺序, 各 frame 内部 id 局部 1..N_local 等 Python 端 renumber)
      - frames_for_renumber: [(frame, frame_path, local_id_count), ...] 让主调用方组 id_map
      - hosts: 跨域 host (DFS 顺序, 主调用方 dict.fromkeys 去重)

    跨域 / detached frame catch 后整子树 skip, 返 ([], [], [host]).
    """
    try:
        # 等 iframe load 防 timing 抢跑; timeout 短 (2s) 防慢站拖整体 perceive.
        await child.wait_for_load_state("domcontentloaded", timeout=2000)
        local_marks = await _inject_som_in_frame(child, child_path, shadow_on, id_offset=0)
    except Exception as e:
        host = _frame_host(child)
        logger.warning(
            "frame %r (path=%s, host=%s) SoM inject failed (cross-origin/detached?), 跳过子树: %r",
            getattr(child, "url", "")[:80], child_path, host, e,
        )
        return [], [], [host]

    # 子层递归 (孙辈也并发 — 各孙辈深度依赖 child inject 完成但孙辈互之间无依赖)
    sub_marks, sub_frames, sub_hosts = await _walk_child_frames_concurrent(
        child, child_path, shadow_on,
    )
    all_marks = local_marks + sub_marks
    # 本 frame 也要 renumber (注入到 frames_for_renumber 头部, DFS 顺序)
    frames_for_renumber = [(child, child_path, len(local_marks))] + sub_frames
    return all_marks, frames_for_renumber, sub_hosts


async def _walk_child_frames_concurrent(
    parent: Frame, parent_path: str, shadow_on: bool,
) -> tuple[list[Mark], list[tuple[Frame, str, int]], list[str]]:
    """V0.34.4 F1: 同层 child sibling 用 asyncio.gather 并发 inject SoM.

    取代 V0.22.1 顺序循环. 各 child 用 `id_offset=0` 局部 1..N_local, Python 端 DFS 拼后
    renumber 全局 (主调用方 perceive). gather 保返回顺序 = input 顺序 (DFS index 一致).
    跨域 frame catch 在 _process_child_frame_concurrent 内, 整子树 skip, return tuple
    不共享 mutable list 消除竞态.

    返 (marks_dfs_order, frames_for_renumber, hosts_dfs).
    """
    children = list(parent.child_frames)
    if not children:
        return [], [], []
    tasks = [
        _process_child_frame_concurrent(
            child,
            f"{parent_path}.{i}" if parent_path else str(i),
            shadow_on,
        )
        for i, child in enumerate(children)
    ]
    sub_results = await asyncio.gather(*tasks)
    all_marks: list[Mark] = []
    all_frames: list[tuple[Frame, str, int]] = []
    all_hosts: list[str] = []
    for child_marks, child_frames, child_hosts in sub_results:
        all_marks.extend(child_marks)
        all_frames.extend(child_frames)
        all_hosts.extend(child_hosts)
    return all_marks, all_frames, all_hosts


async def perceive(page: Page) -> tuple[list[Mark], str, list[str]]:
    """先尝试关弹窗 → 注入 SoM 标注 (主 frame + 同源 iframe) → 截带标注的视口图 → 移除标注。

    auto-dismiss 在 SoM 注入**之前**执行，避免关弹窗后 mark 编号错位 (只在主 frame 跑,
    iframe dismiss 留 V0.22.4).
    截图含 SoM 红框 + 数字角标，直接给 LLM 看；返回前已清掉标注 DOM 节点不污染页面。

    V0.22.1: 同源 iframe 也注入 SoM 让 LLM 看到 reCAPTCHA 风格 widget 内元素;
    跨域 frame.evaluate fail → catch warn 跳整子树.
    主 frame fail 不 catch (fail-fast — silent 空 marks 会让 loop 误判页面无元素死循环).
    id 全局连续: 主 frame 1..N, 第 1 个 iframe N+1..N+M, ... (用 id_offset 注入 JS, 视觉框
    数字 == Python Mark.id 三方一致).

    V0.22.4: 返第 3 元 cross_origin_hosts: list[str] 跨域 iframe 的 host 列表 (DFS 顺序去重),
    loop 传给 build_user_text 渲染 footer 让 LLM 知道反爬 widget 存在不会瞎点.
    """
    dismissed = await maybe_auto_dismiss(page)
    if dismissed:
        logger.info("auto-dismissed %d popup(s): %s", len(dismissed), dismissed)
    # W5-B: WEB_AGENT_SOM_SHADOW=false 退化到 V0.11.x light-DOM only 行为
    shadow_on = os.environ.get("WEB_AGENT_SOM_SHADOW", "true").lower() not in ("false", "0", "no", "off")
    # 主 frame 不 catch (fail-fast 跟 V0.22.0 行为对齐); id_offset=0 局部, 主 frame 必在 DFS 头
    main_marks = await _inject_som_in_frame(page.main_frame, "", shadow_on, id_offset=0)
    # V0.34.4 F1: 同层 child sibling iframe 并发 inject (各 id_offset=0 局部), DFS 顺序拼.
    child_marks, child_frames, hosts = await _walk_child_frames_concurrent(
        page.main_frame, "", shadow_on,
    )
    # Python 端 DFS 顺序 renumber 全局 1..N, 同时组每 frame 的 old→new id_map
    new_marks: list[Mark] = []
    main_id_map: dict[str, int] = {}
    for i, m in enumerate(main_marks):
        new_id = i + 1
        main_id_map[str(m.id)] = new_id
        new_marks.append(replace(m, id=new_id))
    cursor = len(main_marks)
    child_id_maps: dict[str, dict[str, int]] = {}  # frame_path → id_map
    child_marks_offset = 0
    for _frame, fpath, local_count in child_frames:
        id_map: dict[str, int] = {}
        for j in range(local_count):
            old_local = child_marks[child_marks_offset + j].id  # local 1..local_count
            new_id = cursor + j + 1
            id_map[str(old_local)] = new_id
            new_marks.append(replace(child_marks[child_marks_offset + j], id=new_id))
        child_id_maps[fpath] = id_map
        cursor += local_count
        child_marks_offset += local_count
    # 并发跑 RENUMBER_JS 各 frame (主 + child) 修 DOM data-som-id + 视觉框 tag.textContent
    renumber_tasks = [
        page.main_frame.evaluate(_SOM_RENUMBER_JS, {"id_map": main_id_map, "shadow": shadow_on}),
    ]
    for frame, fpath, _count in child_frames:
        renumber_tasks.append(
            frame.evaluate(_SOM_RENUMBER_JS, {"id_map": child_id_maps[fpath], "shadow": shadow_on}),
        )
    # renumber 失败不致命 (DOM 端 stale id, 但 Mark.id 已是新值) — log + 继续
    await asyncio.gather(*renumber_tasks, return_exceptions=True)
    # V0.33.3: env `WEB_AGENT_SCREENSHOT_FORMAT=webp` opt-in (默 png 兼容 V0.33.2 baseline).
    _fmt = current_screenshot_format()
    if _fmt == "webp":
        screenshot_bytes = await page.screenshot(
            type="webp",  # type: ignore[arg-type]
            quality=current_screenshot_quality(),
            full_page=False,
        )
    else:
        screenshot_bytes = await page.screenshot(type="png", full_page=False)
    # V0.34.4: cleanup 主 + 所有 child frame 并发 (各 frame _remove_som 独立)
    cleanup_tasks = [_remove_som_in_frame(page.main_frame)]
    for frame, _fpath, _count in child_frames:
        cleanup_tasks.append(_remove_som_in_frame(frame))
    await asyncio.gather(*cleanup_tasks)
    # 去重保 DFS 顺序 (LLM prompt 缓存命中率看顺序)
    deduped_hosts = list(dict.fromkeys(hosts))
    return new_marks, base64.b64encode(screenshot_bytes).decode(), deduped_hosts


_LEAN_ROLE_KEEP_TAGS = frozenset({"div", "span", "li", "section", "article"})
"""V0.33.2: lean 模式下仅这些通用 tag 保留 role (语义靠 role 撑),
button / input / a 等 tag 已自带语义, role 重复字段砍."""


def current_screenshot_format() -> str:
    """V0.33.3: env `WEB_AGENT_SCREENSHOT_FORMAT` 单源读 (caller: perceive / anthropic / openai / loop).

    返 "png" (默) 或 "webp". 任何非 "webp" 值都视 "png" (跟 V0.33.2 lean 模式 fallback 同模型).

    定位 (V0.33.0 #13 警告诚实降级): WebP **不省 token** — Anthropic 按 image tile 固定计费
    ~1568 tok/image, OpenAI vision detail=high 同按 tile. WebP 真省的是: ① 落盘磁盘 (~70% bytes
    减) ② 网络上传 latency. V0.33.4 baseline 双跑量化验证.
    """
    return "webp" if os.environ.get("WEB_AGENT_SCREENSHOT_FORMAT", "png").strip().lower() == "webp" else "png"


def current_screenshot_quality() -> int:
    """V0.33.3: WebP lossy quality (1-100, 默 75 是 sweet spot — SoM 红边 + 数字仍清).

    PNG 路径忽略此值 (PNG 是 lossless). env `WEB_AGENT_SCREENSHOT_QUALITY` 解析失败 → 75 fallback.
    """
    raw = os.environ.get("WEB_AGENT_SCREENSHOT_QUALITY", "75").strip()
    try:
        q = int(raw)
        return q if 1 <= q <= 100 else 75
    except ValueError:
        return 75


def marks_to_text(marks: list[Mark]) -> str:
    """把 marks 列表序列化成给 LLM 的简洁文本（DOM 瘦身）。

    V0.22.0: 加 `@<frame_path>` 后缀标记 iframe 内元素 (主 frame 不显示).
    LLM 看到 `@0` / `@0.2` 知道该 mark 在嵌套 iframe; actuator V0.22.2 自动按 frame_path 路由.

    V0.33.2: env `WEB_AGENT_SOM_FIELDS=lean` 触发 lean mode (省 ~50% text token, V0.33 E 性能优化系列):
    - 砍 href (a[href] 长字符不入 LLM, list_extract 走独立路径不受影响)
    - 条件砍 role (仅 generic tag div/span/li/section/article 时保, button/a/input 已自带语义)
    - 保 id / tag / text / frame_path (LLM 必须能引 click(mark_id=N) + 跨 frame 语义)
    缺省 / 任何非 "lean" 值 → full mode 字节级兼容 V0.33.1 行为, baseline 不破.
    """
    lean = os.environ.get("WEB_AGENT_SOM_FIELDS", "full").strip().lower() == "lean"
    lines = []
    for m in marks:
        s = f"[{m.id}] <{m.tag}"
        if m.role and (not lean or m.tag in _LEAN_ROLE_KEEP_TAGS):
            s += f" role={m.role}"
        s += ">"
        if m.text:
            s += f" {m.text!r}"
        if m.href and not lean:
            s += f" → {m.href}"  # V0.20.8: a[href] 暴露给 LLM (list extract 必须看到 link target)
        if m.frame_path:
            s += f" @{m.frame_path}"  # V0.22.0: iframe 路径
        lines.append(s)
    return "\n".join(lines)
