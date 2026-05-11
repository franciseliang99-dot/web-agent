"""CDP 接管已启动的本地 Chrome（--remote-debugging-port=9222）。"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from collections import deque
from collections.abc import Callable
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Dialog, Download, Page, Playwright

logger = logging.getLogger(__name__)


async def _popup_notice_handler(page: Page) -> None:
    """V0.21.3: ctx.on('page') 回调 — 新 top-level page (popup / window.open) 出现时拟人延迟.

    Playwright `_on_page` 已先 `_pages.append(page)` 后 emit, 所以 ctx.pages 已含新 page;
    此 handler 仅模拟"人类注意到新 tab 弹出"的反应延迟 0.3-0.8s, **不抢焦点** (不调
    bring_to_front, 不改 active_idx) — 模仿 target=_blank 时人眼看到 tab 但继续读当前 tab.

    pyee AsyncIOEventEmitter 自动 ensure_future 把 async handler 调度成独立 task,
    不阻塞主 loop. **不装 page.on('popup')** — Playwright 内部 popup 事件已通过
    ctx.on('page') 接住一次, 双装会让 sleep 跑两遍 (V0.21.3 sanity 实测).
    """
    delay = random.uniform(0.3, 0.8)
    await asyncio.sleep(delay)
    url_preview = (getattr(page, "url", "") or "")[:80]
    logger.info("popup detected (delay=%.2fs): %s", delay, url_preview)


def _attach_popup_listener(ctx: BrowserContext) -> None:
    """V0.21.3: 给 ctx 装 popup listener, 幂等 (重装等于重 emit, 防 cli/jd_extract/list_extract
    都各自 connect 时叠装).

    用 `_web_agent_popup_listener` private flag 标记已装 — Playwright BrowserContext 是
    动态属性容器, 这种 monkey-patch flag 是 Playwright 生态常见模式.
    """
    if getattr(ctx, "_web_agent_popup_listener", False):
        return
    ctx.on("page", _popup_notice_handler)
    ctx._web_agent_popup_listener = True  # type: ignore[attr-defined]


def _max_download_mb() -> int:
    """V0.23.2: env 可调 download size 上限 (默认 100MB), 防 LLM 误下载 GB 级文件填满磁盘."""
    try:
        return int(os.environ.get("WEB_AGENT_MAX_DOWNLOAD_MB", "100"))
    except ValueError:
        return 100


def _resolve_download_path(download_dir: Path, suggested: str) -> Path:
    """V0.23.2: 同名 download 加 _2/_3/... 后缀去重. timestamp 不可读 / _N 后缀人眼可读."""
    target = download_dir / suggested
    if not target.exists():
        return target
    stem, dot, ext = suggested.partition(".")
    suffix = f".{ext}" if dot else ""
    for i in range(2, 1000):
        candidate = download_dir / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    return download_dir / f"{stem}_overflow_{random.randint(1000, 9999)}{suffix}"


async def _save_download_async(download: Download, target_path: Path, max_bytes: int) -> None:
    """V0.23.2: 异步 save_as + size 后置检查 (Playwright Download 无 pre-check size API).

    超限删除文件 + log warning. 失败不抛 (download 是 fire-and-forget, 主 loop 不该被打断).
    """
    try:
        await download.save_as(str(target_path))
        if target_path.exists():
            actual_bytes = target_path.stat().st_size
            if actual_bytes > max_bytes:
                logger.warning(
                    "download %r size %d MB 超 max %d MB, 删除", target_path.name,
                    actual_bytes // (1024 * 1024), max_bytes // (1024 * 1024),
                )
                target_path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("download save_as %r 失败: %r", target_path, e)


def _make_download_handler(ctx: BrowserContext) -> Callable[[Download], None]:
    """V0.23.2: 工厂返 page.on('download') handler, 闭包持有 ctx 拿 task-scoped download_dir.

    handler 同步 append 元信息到 ctx._web_agent_recent_downloads (loop 顶部读), save_as 异步
    fire-and-forget (不 block 主 loop). 元信息 instant 可读, save 完成与否对 obs 文本无影响.
    """
    def handler(download: Download) -> None:
        download_dir = getattr(ctx, "_web_agent_download_dir", None)
        if download_dir is None:
            logger.warning("download 触发但 ctx._web_agent_download_dir 未设, drop %r", download.url[:80])
            return
        suggested = download.suggested_filename or "download.bin"
        target = _resolve_download_path(download_dir, suggested)
        recent = getattr(ctx, "_web_agent_recent_downloads", None)
        if recent is None:
            recent = deque(maxlen=10)
            ctx._web_agent_recent_downloads = recent  # type: ignore[attr-defined]
        # instant 元信息追加, save 异步 fire-and-forget
        recent.append(f"downloaded: {target.name} ({download.url[:80]})")
        max_bytes = _max_download_mb() * 1024 * 1024
        asyncio.create_task(_save_download_async(download, target, max_bytes))
    return handler


def _attach_page_download(page: Page, ctx: BrowserContext) -> None:
    """V0.23.2: 给单个 page 装 page.on('download') handler, 幂等 flag 防同 page 叠装."""
    if getattr(page, "_web_agent_download_listener", False):
        return
    page.on("download", _make_download_handler(ctx))
    page._web_agent_download_listener = True  # type: ignore[attr-defined]


# ---------- V0.24.0: dialog auto-handle ----------

# Playwright dialog.type ∈ {alert, beforeunload, confirm, prompt}
_DIALOG_ACCEPT_TYPES = {"alert", "beforeunload"}  # safe-defaults: accept (alert OK-only, beforeunload 让 LLM nav)
_DIALOG_DISMISS_TYPES = {"confirm", "prompt"}  # safe-defaults: dismiss (failsafe NO + LLM 没法 prompt 输入)


def _dialog_policy() -> str:
    """V0.24.0: env WEB_AGENT_DIALOG_POLICY 解析. safe-defaults (默认) / auto-accept / auto-dismiss."""
    return os.environ.get("WEB_AGENT_DIALOG_POLICY", "safe-defaults").strip().lower()


def _decide_dialog_action(dialog_type: str) -> str:
    """V0.24.0: 按 env policy 决定 dialog accept/dismiss.

    safe-defaults: alert/beforeunload accept; confirm/prompt dismiss.
    auto-accept: 全 accept (任务优先, 风险买/删 — dev 用).
    auto-dismiss: 全 dismiss (paranoid, 任务可能卡).
    """
    policy = _dialog_policy()
    if policy == "auto-accept":
        return "accept"
    if policy == "auto-dismiss":
        return "dismiss"
    # safe-defaults (default)
    if dialog_type in _DIALOG_ACCEPT_TYPES:
        return "accept"
    return "dismiss"


async def _handle_dialog(dialog: Dialog, action: str) -> None:
    """V0.24.0: async accept/dismiss + 异常 catch (dialog 已被处理 / page closed → 不阻塞 listener)."""
    try:
        if action == "accept":
            await dialog.accept()
        else:
            await dialog.dismiss()
    except Exception as e:
        logger.warning("dialog %s 失败 (%r)", action, e)


def _make_dialog_handler(ctx: BrowserContext) -> Callable[[Dialog], None]:
    """V0.24.0: 工厂返 page.on('dialog') sync handler, 闭包持 ctx 拿 _web_agent_recent_dialogs deque.

    handler 必须**同步调度** dialog.accept/dismiss (Playwright 触发后 page hang 直到响应);
    sync 内 asyncio.create_task fire-and-forget. 同步 append 元信息到 deque (loop 顶部读).

    跟 V0.23.2 _make_download_handler 同套路 (sync register + async fire), 不需新装载机制.
    """
    def handler(dialog: Dialog) -> None:
        action = _decide_dialog_action(dialog.type)
        recent = getattr(ctx, "_web_agent_recent_dialogs", None)
        if recent is None:
            recent = deque(maxlen=10)
            ctx._web_agent_recent_dialogs = recent  # type: ignore[attr-defined]
        message = (dialog.message or "")[:120]
        recent.append(f"dialog {dialog.type}: {message!r} (auto-{action}ed)")
        asyncio.create_task(_handle_dialog(dialog, action))
    return handler


def _attach_page_dialog(page: Page, ctx: BrowserContext) -> None:
    """V0.24.0: 给单个 page 装 page.on('dialog') handler, 幂等 flag 防同 page 叠装."""
    if getattr(page, "_web_agent_dialog_listener", False):
        return
    page.on("dialog", _make_dialog_handler(ctx))
    page._web_agent_dialog_listener = True  # type: ignore[attr-defined]


async def _ctx_page_handler_with_listeners(page: Page, ctx: BrowserContext) -> None:
    """V0.23.2 + V0.24.0: ctx.on('page') 复合 handler — 跑 popup 拟人延迟 + 装 download listener
    + 装 dialog listener (V0.24.0 加).

    新弹 popup page 自动获得 download/dialog 监听 (跟初始 ctx.pages 同模式).
    """
    _attach_page_download(page, ctx)
    _attach_page_dialog(page, ctx)
    await _popup_notice_handler(page)


def _attach_download_listeners(ctx: BrowserContext) -> None:
    """V0.23.2 + V0.24.0: 给 ctx 装 download + dialog listener, 跟 popup 同模式幂等 + 跨 entry 一次性.

    Playwright `download` / `dialog` 事件只在 page 级别 (ctx 无), 必须每个 page 装. ctx.on('page')
    新弹 popup 时也再装一次 (V0.21.3 popup handler 升级为复合 handler 同时装 download + dialog).
    initial pages (ctx.pages 已有) 也 walk 装一次.

    download_dir 由 loop 入口写 ctx._web_agent_download_dir attr (task-scoped); listener
    handler 闭包读. mcp_server._RUN_LOCK 串行化 web_agent_run, ctx 同时只 1 task 持有 →
    attr 注入安全 (sanity 推翻 Plan B5 多 task 并发顾虑).
    """
    if getattr(ctx, "_web_agent_download_listener", False):
        return
    # initial pages 立即装 download + dialog
    for p in ctx.pages:
        _attach_page_download(p, ctx)
        _attach_page_dialog(p, ctx)
    # 新弹 page (popup) 装载: ctx.on('page') 升级到复合 handler 同时装 popup notice +
    # download + dialog. 沿用 V0.23.2 命名 _attach_download_listeners 保单一 entrypoint
    # (避免再加 _attach_dialog_listeners 让 connect 多 1 行 — 复合 handler 已涵盖).
    ctx.on("page", lambda p: asyncio.create_task(_ctx_page_handler_with_listeners(p, ctx)))
    ctx._web_agent_download_listener = True  # type: ignore[attr-defined]


async def connect(
    p: Playwright,
    cdp_url: str = "http://127.0.0.1:9222",
) -> tuple[Browser, BrowserContext, Page]:
    """连接已启动的 Chrome 调试端口，返回 (browser, context, page)。

    用户必须先在终端跑 `bash scripts/start_chrome.sh` 启动带 9222 端口的 Chrome。

    注：默认用 127.0.0.1 而非 localhost — 部分 Linux 发行版 IPv6 优先，
    `localhost` 会 resolve 到 ::1，但 chrome `--remote-debugging-port` 只 listen IPv4。
    用户可通过 WEB_AGENT_CDP_URL env 覆盖（cli.py 读）。

    V0.21.3: 装 ctx.on('page') popup listener 抓 target=_blank / window.open() 弹的子 tab.
    listener 装在 connect (跨 cli/jd_extract/list_extract 三个 entry 一次性), 而非 loop
    (loop 不感知 popup 注册逻辑, 解耦更干净).
    """
    browser = await p.chromium.connect_over_cdp(cdp_url)
    if not browser.contexts:
        raise RuntimeError(
            f"已连接 {cdp_url} 但 contexts 为空 — Chrome 可能没开任何窗口。"
        )
    ctx = browser.contexts[0]
    _attach_popup_listener(ctx)
    _attach_download_listeners(ctx)  # V0.23.2: 跟 popup 同模式 (跨 entry 一次性)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return browser, ctx, page


async def apply_stealth(page: Page) -> None:
    """注入 stealth patches，抹除 navigator.webdriver 等自动化痕迹。

    playwright-stealth 2.x 的 API 在不同 minor 版本间有调整，这里做容错：
    如果当前安装版本 API 不匹配，warn 后跳过——主流程不挂。
    """
    try:
        from playwright_stealth import Stealth

        stealth = Stealth()
        if hasattr(stealth, "apply_stealth_async"):
            await stealth.apply_stealth_async(page)
        elif hasattr(stealth, "apply_async"):
            await stealth.apply_async(page)
        else:
            logger.warning("playwright-stealth API 未匹配（既无 apply_stealth_async 也无 apply_async），跳过")
    except ImportError:
        logger.warning("playwright-stealth 未安装，跳过 stealth")
    except Exception as e:
        logger.warning("stealth 注入失败 (%r)，跳过", e)


# V0.30.0 G stealth 加固: page.add_init_script 注入 JS 在 page navigate 前 (每 frame 都跑).
# 不依赖 playwright-stealth lib (apply_stealth 是 lib 调用, 本 JS 是补充加固防 lib 升级断).
# 3 项加固 (subagent V0.30 plan D 决): webdriver hide + WebGL vendor randomize + permissions consistency.
# 不加 audio noise / timezone / chrome.runtime spoof (V0.30 scope 太 wide, 留 V0.31+).
_STEALTH_PLUS_JS = """
// V0.30.0 G stealth+ 加固 (in addition to playwright-stealth lib defaults)

// 1. navigator.webdriver hide (双保险, lib 默已含但加固)
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// 2. WebGL vendor + renderer randomize (固定 per-context seed 防同一 ctx 多次查不一致)
(() => {
    const _origGetParameter = WebGLRenderingContext.prototype.getParameter;
    // UNMASKED_VENDOR_WEBGL = 37445; UNMASKED_RENDERER_WEBGL = 37446
    const _vendors = ['Intel Inc.', 'NVIDIA Corporation', 'ATI Technologies Inc.'];
    const _renderers = ['Intel(R) HD Graphics 620', 'NVIDIA GeForce GTX 1060', 'AMD Radeon Pro 555X'];
    const _idx = Math.floor(Math.random() * _vendors.length);
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return _vendors[_idx];
        if (param === 37446) return _renderers[_idx];
        return _origGetParameter.call(this, param);
    };
})();

// 3. navigator.permissions.query 一致性 (Headless Chrome 默 'denied' for notifications)
(() => {
    const _origQuery = navigator.permissions && navigator.permissions.query;
    if (!_origQuery) return;
    navigator.permissions.query = (params) => {
        if (params && params.name === 'notifications') {
            return Promise.resolve({state: Notification.permission, name: 'notifications', onchange: null});
        }
        return _origQuery.call(navigator.permissions, params);
    };
})();
"""


async def apply_stealth_plus(page: Page) -> None:
    """V0.30.0: G stealth 加固 — page.add_init_script 显式注入 webdriver/WebGL/permissions JS.

    跟 apply_stealth (playwright-stealth lib 调用) 复合用: cli.run_task 入口先 apply_stealth (lib
    覆 80%), 再 apply_stealth_plus 加固 3 项关键 (V0.30 plan D 决). 不依赖 lib 防 lib 升级断.

    `page.add_init_script` 在 page navigate 前注入 + 每 frame 都跑 (popup/iframe 自动覆盖).
    Exception 不阻塞主流程 (跟 apply_stealth 同 graceful 模式).
    """
    try:
        await page.add_init_script(_STEALTH_PLUS_JS)
    except Exception as e:
        logger.warning("apply_stealth_plus init script 注入失败 (%r), 跳过", e)
