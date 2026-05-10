"""V0.20.5 JD extract entrypoint — 半自动: 用户手 navigate, agent 只 perceive 当前 tab.

路径 D (CHANGELOG V0.20.0): 用户从 Upwork 原生 saved-search email alert 手动拿 JD URL,
贴给 web-agent-jd, web-agent extract 9 字段写 data/upwork.db. 评分由 scripts/score_upwork.py
桥到 jobscout-bot eval-jd (rubric 单 SoT).

V0.20.4 实测 (commit c0ce9d9) page.goto(url) 触发 Cloudflare 重激活 challenge, LLM 看到
"正在验证..." 0 marks 全 null. V0.20.5 改半自动: 用户在 9222 Chrome 手浏览到 JD URL (CF 已过),
agent 遍历 ctx.pages 找 URL match 的 page 直接 perceive, **不调 page.goto** (不触发 CF 重激活).

设计原则 (按 CLAUDE.md 解耦):
- 复用 chrome_launcher / browser / loop (ReAct + 五大守护) / llm.make_client
- jd_extract 自身只: rate-limit / SQLite UPSERT / goal 引导 / done.result JSON 解析
  + URL match 找 active tab (V0.20.5 新)
- max_steps=3 限单步 perceive → done; LLM 误用 click/scroll → ReAct anti-loop 兜底
- `--allow-url-mismatch` 紧急绕过 fallback ctx.pages[0] (用户场景: query string 微差)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.async_api import BrowserContext, Page, async_playwright

from web_agent.browser import apply_stealth, connect
from web_agent.chrome_launcher import ensure_chrome_running
from web_agent.llm import make_client
from web_agent.loop import run_react_loop

logger = logging.getLogger(__name__)

DEFAULT_DB = Path("data/upwork.db")
RATE_LIMIT_MIN_INTERVAL_S = 60.0
RATE_LIMIT_SESSION_WINDOW_S = 1800.0
RATE_LIMIT_SESSION_CAP = 30
DESCRIPTION_TRUNC_CHARS = 8000
JD_EXTRACT_MAX_STEPS = 3
JD_EXTRACT_MAX_WALLCLOCK_S = 120.0


_JD_EXTRACT_GOAL = """你是 Upwork JD 字段提取器. 当前页面是 Upwork JD 详情页.

仅 perceive 截图后**直接调 done 工具**, 把以下 9 字段塞进 done.result (单行严格 JSON, UTF-8):

{"thought": "你看到了什么", "title": "JD 标题原文", "description": "JD body 完整内容 (≤8000 字符)", "budget": "$30/hr 或 Fixed-$500", "hourly": true 或 false, "client_country": "...", "client_rating": 4.8, "posted_at": "Posted 2 hours ago", "proposals_count": 15, "connect_cost": 12}

约束:
- title / description 必填, 看不到 raise; 其它字段看不到填 null 不要瞎猜
- 严禁 click / scroll / type / extract — 直接发 done. 整个任务 1 步完成.
- done.result 字段填 JSON 字符串本体 (不要包 markdown code fence, 不要包 prose 描述).
"""


_LOOP_ERROR_PREFIXES = (
    "CAPTCHA_TIMEOUT", "WALLCLOCK_EXCEEDED", "LOOP_DETECTED",
    "(max_steps 耗尽未完成)", "SAFETY_BLOCK", "LLM_FAILED",
)

_MD_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_BRACE_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


# ===== SQLite (与 V0.20.0 一致, 数据契约不变) =====

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS upwork_jds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    scraped_at REAL NOT NULL,
    title TEXT,
    description TEXT,
    budget TEXT,
    hourly INTEGER,
    client_country TEXT,
    client_rating REAL,
    posted_at TEXT,
    proposals_count INTEGER,
    connect_cost INTEGER,
    score INTEGER,
    recommendation TEXT,
    fit_json TEXT,
    raw_thought TEXT
);
CREATE INDEX IF NOT EXISTS idx_scraped_ts ON upwork_jds(scraped_at DESC);
"""

_UPSERT_FIELDS = (
    "url", "scraped_at", "title", "description", "budget", "hourly",
    "client_country", "client_rating", "posted_at", "proposals_count",
    "connect_cost", "raw_thought",
)


def init_upwork_db(db_path: Path) -> sqlite3.Connection:
    """打开/创建 upwork.db, 建表 + 索引. 幂等."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_INIT_SQL)
    conn.commit()
    return conn


def check_rate_limit(conn: sqlite3.Connection, now: float | None = None) -> None:
    """≤1/min 上次 < 60s 拒; 30min 内 ≥30 个拒. 抛 SystemExit (退出码 != 0)."""
    now = now if now is not None else time.time()
    last_ts: float | None = conn.execute("SELECT MAX(scraped_at) FROM upwork_jds").fetchone()[0]
    if last_ts is not None and now - last_ts < RATE_LIMIT_MIN_INTERVAL_S:
        delta = now - last_ts
        raise SystemExit(
            f"rate-limit: 上次 extract {delta:.0f}s 前, 等满 {RATE_LIMIT_MIN_INTERVAL_S:.0f}s "
            "(--ignore-rate-limit 紧急绕过)"
        )
    session_count: int = conn.execute(
        "SELECT COUNT(*) FROM upwork_jds WHERE scraped_at > ?",
        (now - RATE_LIMIT_SESSION_WINDOW_S,),
    ).fetchone()[0]
    if session_count >= RATE_LIMIT_SESSION_CAP:
        raise SystemExit(
            f"session-cap: 30min 内已 extract {session_count} 个 (cap={RATE_LIMIT_SESSION_CAP}), "
            "建议收工 (--ignore-rate-limit 紧急绕过)"
        )


def upsert_jd(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """INSERT ... ON CONFLICT(url) DO UPDATE. 重贴同 URL 刷字段, 保 id 与已写 score."""
    placeholders = ",".join("?" * len(_UPSERT_FIELDS))
    cols = ",".join(_UPSERT_FIELDS)
    update_set = ",".join(f"{f}=excluded.{f}" for f in _UPSERT_FIELDS if f != "url")
    sql = (
        f"INSERT INTO upwork_jds ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(url) DO UPDATE SET {update_set}"
    )
    conn.execute(sql, tuple(row.get(f) for f in _UPSERT_FIELDS))
    conn.commit()


# ===== JSON 解析 (V0.20.4, 三层 fallback) =====

def _ensure_dict(obj: Any) -> dict[str, Any]:
    """json.loads 可能返非 dict (list / scalar). 不是 dict 就 SystemExit."""
    if not isinstance(obj, dict):
        raise SystemExit(f"LLM done.result JSON 顶层不是 object: type={type(obj).__name__}")
    return obj


def _check_loop_error(result: str) -> None:
    """识别 run_react_loop 6 种 sentinel 错误字符串, 命中 → SystemExit."""
    head = result[:80]
    for prefix in _LOOP_ERROR_PREFIXES:
        if prefix in head:
            raise SystemExit(f"jd extract aborted: {result[:200]}")


def parse_jd_result(result: str) -> dict[str, Any]:
    """三层 fallback 解析 LLM done.result: 严格 JSON → ```json md block → 裸 {} block. 失败 SystemExit."""
    _check_loop_error(result)

    text = result.strip()

    try:
        return _ensure_dict(json.loads(text))
    except json.JSONDecodeError:
        pass

    md_match = _MD_CODE_BLOCK_RE.search(text)
    if md_match:
        try:
            return _ensure_dict(json.loads(md_match.group(1)))
        except json.JSONDecodeError:
            pass

    bare_match = _BARE_BRACE_RE.search(text)
    if bare_match:
        try:
            return _ensure_dict(json.loads(bare_match.group(0)))
        except json.JSONDecodeError:
            pass

    raise SystemExit(f"LLM done.result 不是 JSON: {result[:300]!r}")


# ===== URL match + 找 active tab (V0.20.5 新, 半自动模式) =====

def _url_match(want: str, have: str) -> bool:
    """V0.20.5: normalize URL 比 host + path, 忽略 scheme casing / query / fragment / trailing slash.

    Upwork JD URL path 已唯一标识 JD (`~01abc...`), query 仅含 tracking (?pageTitle=, &utm_*=);
    exact match 撞 query 必败, substring 撞同 host sidebar 推荐链接风险.
    """
    try:
        w, h = urlparse(want), urlparse(have)
    except Exception:
        return False
    return (
        w.netloc.lower() == h.netloc.lower()
        and w.path.rstrip("/") == h.path.rstrip("/")
    )


def _find_jd_page(ctx: BrowserContext, url: str) -> Page | None:
    """V0.20.5: 遍历 ctx.pages 找第一个 URL match 的 page. 找不到返 None."""
    return next((p for p in ctx.pages if _url_match(url, p.url)), None)


# ===== 主流程 =====

def _bool_to_int(v: Any) -> int | None:
    """SQLite 不直接存 bool, hourly 序列化: True→1 / False→0 / None→NULL."""
    if v is True:
        return 1
    if v is False:
        return 0
    return None


async def extract_url(
    url: str,
    db_path: Path = DEFAULT_DB,
    cdp_url: str | None = None,
    model: str | None = None,
    captcha_timeout_s: float | None = None,
    ignore_rate_limit: bool = False,
    allow_url_mismatch: bool = False,
) -> dict[str, Any]:
    """V0.20.5 半自动主流程: rate-limit → connect 9222 → 找 URL match page → run_react_loop → parse → upsert.

    用户必须先在 9222 Chrome 手 navigate 到 url (CF 验证已过, 页面正常显示 JD). agent 不调 page.goto
    (V0.20.4 实测 navigation 触发 CF 重激活 challenge). --allow-url-mismatch 紧急绕过用 ctx.pages[0]
    强抽 (用户场景: query string 微差).
    """
    load_dotenv()
    cdp_url = cdp_url or os.environ.get("WEB_AGENT_CDP_URL", "http://127.0.0.1:9222")
    if captcha_timeout_s is not None:
        os.environ["WEB_AGENT_CAPTCHA_TIMEOUT_S"] = str(captcha_timeout_s)

    conn = init_upwork_db(db_path)
    if not ignore_rate_limit:
        check_rate_limit(conn)

    await asyncio.to_thread(ensure_chrome_running, cdp_url)

    async with async_playwright() as p:
        _, ctx, fallback_page = await connect(p, cdp_url=cdp_url)

        jd_page = _find_jd_page(ctx, url)
        if jd_page is None:
            if not allow_url_mismatch:
                tabs = [pg.url[:80] for pg in ctx.pages]
                raise SystemExit(
                    f"V0.20.5 半自动模式: 当前 9222 Chrome 没找到 URL 在 {url} 的 tab.\n"
                    f"  当前 {len(ctx.pages)} 个 tab: {tabs}\n"
                    f"操作: 在 Chrome 手动打开该 URL, 等 Cloudflare 过完 (页面正常显示 JD 内容), "
                    f"再重跑 web-agent-jd. 或加 --allow-url-mismatch 用当前 active tab "
                    f"(pages[0]) 强抽."
                )
            logger.warning("--allow-url-mismatch ON, fallback ctx.pages[0].url=%r", fallback_page.url)
            jd_page = fallback_page

        await apply_stealth(jd_page)
        logger.info("using existing 9222 tab: %s", jd_page.url[:120])

        client = make_client(model=model)
        logger.info("LLM provider=%s model=%s", client.name, client.model)

        # V0.21.1: loop 改读 ctx; 传 jd_page 在 ctx.pages 的 idx 作为 initial_active_idx
        # (Playwright ctx.pages 顺序不被 bring_to_front 改变, 必须显式传 idx).
        jd_idx = ctx.pages.index(jd_page)
        result_str = await run_react_loop(
            ctx=ctx,
            client=client,
            goal=_JD_EXTRACT_GOAL,
            max_steps=JD_EXTRACT_MAX_STEPS,
            max_wallclock_s=JD_EXTRACT_MAX_WALLCLOCK_S,
            db_path=Path("data/trace.db"),
            screenshots_dir=Path("data/screenshots"),
            initial_active_idx=jd_idx,
        )

    fields = parse_jd_result(result_str)
    logger.info("parsed JD: title=%r budget=%r posted=%r",
                fields.get("title"), fields.get("budget"), fields.get("posted_at"))

    desc_raw = fields.get("description") or ""
    row: dict[str, Any] = {
        "url": url,
        "scraped_at": time.time(),
        "title": fields.get("title"),
        "description": desc_raw[:DESCRIPTION_TRUNC_CHARS] or None,
        "budget": fields.get("budget"),
        "hourly": _bool_to_int(fields.get("hourly")),
        "client_country": fields.get("client_country"),
        "client_rating": fields.get("client_rating"),
        "posted_at": fields.get("posted_at"),
        "proposals_count": fields.get("proposals_count"),
        "connect_cost": fields.get("connect_cost"),
        "raw_thought": fields.get("thought"),
    }
    upsert_jd(conn, row)
    conn.close()
    return row


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="[%(name)s] %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="web-agent-jd",
        description="V0.20.5 路径 D 半自动: 用户手 navigate 到 Upwork JD, agent 只 perceive 当前 tab",
    )
    parser.add_argument("url", help="Upwork JD URL (用户必须先在 9222 Chrome 手 navigate 到该 URL)")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite path (默认 {DEFAULT_DB})")
    parser.add_argument("--cdp-url", default=None, help="覆盖 WEB_AGENT_CDP_URL")
    parser.add_argument("--model", default=None,
                        help="覆盖 WEB_AGENT_MODEL (e.g. claude-sonnet-4-6 / kimi-k2.6 / gpt-5)")
    parser.add_argument("--captcha-timeout-s", type=float, default=None,
                        help="覆盖 WEB_AGENT_CAPTCHA_TIMEOUT_S (默认 300)")
    parser.add_argument(
        "--ignore-rate-limit",
        action="store_true",
        help="紧急绕过 rate limit (默认 OFF, stderr 打 warn)",
    )
    parser.add_argument(
        "--allow-url-mismatch",
        action="store_true",
        help="V0.20.5 紧急绕过: 找不到 URL match 的 tab 时 fallback ctx.pages[0] (默认 OFF)",
    )
    args = parser.parse_args()

    if args.ignore_rate_limit:
        logger.warning("--ignore-rate-limit ON, 真人节律守护已禁用 (Upwork 反爬风险升)")
    if args.allow_url_mismatch:
        logger.warning("--allow-url-mismatch ON, 跳过 URL verify (字段可能从错的 tab 抽)")

    row = asyncio.run(
        extract_url(
            url=args.url,
            db_path=Path(args.db),
            cdp_url=args.cdp_url,
            model=args.model,
            captcha_timeout_s=args.captcha_timeout_s,
            ignore_rate_limit=args.ignore_rate_limit,
            allow_url_mismatch=args.allow_url_mismatch,
        )
    )
    print(json.dumps(row, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
