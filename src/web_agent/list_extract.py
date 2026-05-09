"""V0.20.6 List extract entrypoint — 半自动 read-only: 用户手 navigate 到 Upwork list 页,
agent perceive 一次抽出 N 个 JD 概览 (title/url/budget/posted_at) 给用户手选.

路径 D 延伸 (CHANGELOG V0.20.0/5): V0.20.5 跑通 3 条单 JD 后用户希望 list 页一次看多条.
V0.20.6 0 联跳 / 0 写 db / 单 LLM call, 不触发 CF / 不违 ToS scraping.

设计原则:
- 复用 chrome_launcher / browser / loop / llm.make_client / jd_extract._url_match /
  jd_extract._find_jd_page / jd_extract.parse_jd_result (半自动 + 三层 JSON fallback + sentinel).
- list_extract 自身只: LIST_EXTRACT_GOAL prompt / _validate_jds (类型 + URL host 校验) / stdout dump.
- max_steps=1 限单步 perceive → done(JSON); LLM 误用 click/scroll → ReAct anti-loop 兜底.
- 不写 db (list 抓 read-only audit, 单 JD 路径已 cover db 写入); 不动 jd_extract / score_upwork.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from web_agent.browser import apply_stealth, connect
from web_agent.chrome_launcher import ensure_chrome_running
from web_agent.jd_extract import _find_jd_page, parse_jd_result
from web_agent.llm import make_client
from web_agent.loop import run_react_loop

logger = logging.getLogger(__name__)

LIST_EXTRACT_MAX_STEPS = 1
LIST_EXTRACT_MAX_WALLCLOCK_S = 60.0
LIST_MAX_JDS = 30
UPWORK_HOST_PREFIX = "https://www.upwork.com"

# list URL pattern 白名单 — 不命中 warn 但继续 (用户可能在新版 path 上, 不强 block)
_LIST_URL_PATTERNS = ("/nx/find-work/", "/nx/search/jobs", "/search/jobs/", "/ab/find-work/")


_LIST_EXTRACT_GOAL = """你是 Upwork JD list 页字段提取器. 当前页面是 Upwork 找工 list 页.

仅 perceive 截图后**直接调 done 工具**, 把顶层 JSON 塞 done.result (UTF-8, 不要 markdown fence):
{"thought": "你看到了什么", "jds": [{"title": "...", "url": "...", "budget": "...", "posted_at": "..."}, ...]}

每个 jd item 4 字段:
- title: list 卡片标题原文
- url: a[href] 实际 attribute 完整路径 (相对路径补全 https://www.upwork.com 前缀);
  **严禁瞎编 ~01abc 编号**, 看不清宁可 raise 也不要造假
- budget: $30/hr / Fixed-$500 / Est.budget; 看不到 null
- posted_at: "Posted 2 hours ago" 原文; 看不到 null

约束:
- jds array 至少 1 条, 看到 0 条说明 CF 拦或 list 空; 直接 raise
- 严禁 click/scroll/type/extract — 1 步完成
- 上限抽 30 条; list 超过 30 只抽前 30
"""


def _validate_jds(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """从 parse_jd_result 输出取 jds array, 校验类型 + URL host 补全. 失败 SystemExit.

    - jds 必须是 list 且非空; 否则 SystemExit
    - 每条 item 必须 dict + 含 url; 不符 drop + warn
    - url 相对路径 (`/jobs/~01a`) 补 UPWORK_HOST_PREFIX; 非 Upwork host drop + warn
    - 全部 drop → SystemExit
    """
    jds = parsed.get("jds")
    if not isinstance(jds, list) or not jds:
        raise SystemExit(f"LLM done.result 没有 jds array 或为空: {str(parsed)[:200]}")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(jds):
        if not isinstance(item, dict):
            logger.warning("jds[%d] 不是 dict, drop: %r", i, item)
            continue
        url = item.get("url", "")
        if not isinstance(url, str) or not url:
            logger.warning("jds[%d] 缺 url, drop: %r", i, item)
            continue
        if url.startswith("/"):
            url = UPWORK_HOST_PREFIX + url
        if not url.startswith(UPWORK_HOST_PREFIX):
            logger.warning("jds[%d] URL 非 Upwork host (%s), drop", i, url[:60])
            continue
        item["url"] = url
        out.append(item)
    if not out:
        raise SystemExit(f"jds 全部被 drop (类型错或非 Upwork URL), 原始: {str(jds)[:200]}")
    return out


async def extract_list_url(
    url: str,
    cdp_url: str | None = None,
    model: str | None = None,
    captcha_timeout_s: float | None = None,
    allow_url_mismatch: bool = False,
) -> list[dict[str, Any]]:
    """半自动主流程: connect 9222 → 找 URL match list page → run_react_loop(max_steps=1) → parse + validate."""
    load_dotenv()
    cdp_url = cdp_url or os.environ.get("WEB_AGENT_CDP_URL", "http://127.0.0.1:9222")
    if captcha_timeout_s is not None:
        os.environ["WEB_AGENT_CAPTCHA_TIMEOUT_S"] = str(captcha_timeout_s)

    await asyncio.to_thread(ensure_chrome_running, cdp_url)

    async with async_playwright() as p:
        _, ctx, fallback_page = await connect(p, cdp_url=cdp_url)

        list_page = _find_jd_page(ctx, url)
        if list_page is None:
            if not allow_url_mismatch:
                tabs = [pg.url[:80] for pg in ctx.pages]
                raise SystemExit(
                    f"V0.20.6 半自动模式: 当前 9222 Chrome 没找到 URL 在 {url} 的 tab.\n"
                    f"  当前 {len(ctx.pages)} 个 tab: {tabs}\n"
                    f"操作: 在 Chrome 手动打开该 list URL, 等 Cloudflare 过完, 再重跑.\n"
                    f"或加 --allow-url-mismatch 用 ctx.pages[0]."
                )
            logger.warning("--allow-url-mismatch ON, fallback ctx.pages[0].url=%r", fallback_page.url)
            list_page = fallback_page

        if not any(pat in list_page.url for pat in _LIST_URL_PATTERNS):
            logger.warning(
                "URL %r 看似不是 Upwork list 页 (期望含 %r), LLM 可能抽 0 条",
                list_page.url[:80], _LIST_URL_PATTERNS,
            )

        await apply_stealth(list_page)
        logger.info("using existing 9222 list tab: %s", list_page.url[:120])

        client = make_client(model=model)
        logger.info("LLM provider=%s model=%s", client.name, client.model)

        result_str = await run_react_loop(
            page=list_page,
            client=client,
            goal=_LIST_EXTRACT_GOAL,
            max_steps=LIST_EXTRACT_MAX_STEPS,
            max_wallclock_s=LIST_EXTRACT_MAX_WALLCLOCK_S,
            db_path=Path("data/trace.db"),
            screenshots_dir=Path("data/screenshots"),
        )

    parsed = parse_jd_result(result_str)
    jds = _validate_jds(parsed)
    if len(jds) > LIST_MAX_JDS:
        logger.info("LLM 抽 %d 条, 截到 %d", len(jds), LIST_MAX_JDS)
        jds = jds[:LIST_MAX_JDS]
    return jds


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="[%(name)s] %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="web-agent-list-jds",
        description="V0.20.6 路径 D 半自动: 抽 Upwork list 页 N 个 JD 概览给用户手选 (read-only, 不联跳)",
    )
    parser.add_argument("url", help="Upwork list URL (best-matches/most-recent/search; 用户先手 navigate)")
    parser.add_argument("--cdp-url", default=None, help="覆盖 WEB_AGENT_CDP_URL")
    parser.add_argument("--model", default=None,
                        help="覆盖 WEB_AGENT_MODEL (e.g. claude-sonnet-4-6 / kimi-k2.6)")
    parser.add_argument("--captcha-timeout-s", type=float, default=None,
                        help="覆盖 WEB_AGENT_CAPTCHA_TIMEOUT_S (默认 300)")
    parser.add_argument(
        "--allow-url-mismatch",
        action="store_true",
        help="找不到 URL match tab 时 fallback ctx.pages[0] (默认 OFF)",
    )
    args = parser.parse_args()

    if args.allow_url_mismatch:
        logger.warning("--allow-url-mismatch ON, 跳过 URL verify")

    jds = asyncio.run(
        extract_list_url(
            url=args.url, cdp_url=args.cdp_url, model=args.model,
            captcha_timeout_s=args.captcha_timeout_s,
            allow_url_mismatch=args.allow_url_mismatch,
        )
    )
    print(json.dumps(jds, ensure_ascii=False, indent=2))
    logger.info("抽出 %d 条 JD, 复制 url 跑 web-agent-jd <url>", len(jds))


if __name__ == "__main__":
    main()
