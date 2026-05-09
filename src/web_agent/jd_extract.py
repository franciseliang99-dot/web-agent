"""V0.20.4 JD extract entrypoint — 复用 cli.py 的 run_react_loop 让 LLM 走 done(JSON) 路径.

路径 D (CHANGELOG V0.20.0): 用户从 Upwork 原生 saved-search email alert 手动拿 JD URL,
贴给 web-agent-jd, web-agent extract 9 字段写 data/upwork.db. 评分由 scripts/score_upwork.py
桥到 jobscout-bot eval-jd (rubric 单 SoT).

V0.20.4 撕开 V0.20.0 设计原则 "不依赖 ReAct loop" — multi-provider 需求 (Kimi-k2.6 走 Moonshot
OpenAI compat, 不支持 anthropic SDK 直调 + tool_choice specific name) 强制 jd_extract 复用
run_react_loop. LLM 看 SoM 截图后, 用 done.result 字段塞 JSON 字符串, jd_extract 三层 fallback
解析后写库.

设计原则 (按 CLAUDE.md 解耦):
- 复用 chrome_launcher / browser / loop (ReAct 主循环 + 五大守护: captcha / safety / anti-loop /
  wallclock / LLM-failed) / llm.make_client (provider 自动按 model 名前缀推断)
- jd_extract 自身只: rate-limit / SQLite UPSERT / goal 引导 / done.result JSON 解析
- max_steps=3 限单步 perceive → done; LLM 误用 click/scroll → ReAct anti-loop 兜底
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

from dotenv import load_dotenv
from playwright.async_api import async_playwright

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


# run_react_loop 失败 sentinel 字符串 (loop.py 的 6 种 abort 路径). 命中即 jd extract abort.
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


# ===== JSON 解析 (V0.20.4 新, 三层 fallback) =====

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
    """三层 fallback 解析 LLM done.result: 严格 JSON → ```json md block → 裸 {} block. 失败 SystemExit.

    Public function (无下划线) 因为 tests/test_jd_extract.py 复用它做 unit test.
    """
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
) -> dict[str, Any]:
    """主流程: rate-limit → spawn Chrome → connect → goto → run_react_loop → parse JSON → upsert."""
    load_dotenv()
    cdp_url = cdp_url or os.environ.get("WEB_AGENT_CDP_URL", "http://127.0.0.1:9222")
    if captcha_timeout_s is not None:
        os.environ["WEB_AGENT_CAPTCHA_TIMEOUT_S"] = str(captcha_timeout_s)

    conn = init_upwork_db(db_path)
    if not ignore_rate_limit:
        check_rate_limit(conn)

    await asyncio.to_thread(ensure_chrome_running, cdp_url)

    async with async_playwright() as p:
        _, _, page = await connect(p, cdp_url=cdp_url)
        await apply_stealth(page)
        logger.info("navigating to %s", url)
        await page.goto(url, wait_until="domcontentloaded")

        client = make_client(model=model)
        logger.info("LLM provider=%s model=%s", client.name, client.model)

        result_str = await run_react_loop(
            page=page,
            client=client,
            goal=_JD_EXTRACT_GOAL,
            max_steps=JD_EXTRACT_MAX_STEPS,
            max_wallclock_s=JD_EXTRACT_MAX_WALLCLOCK_S,
            db_path=Path("data/trace.db"),
            screenshots_dir=Path("data/screenshots"),
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
        description="V0.20.4 路径 D: 单 Upwork JD URL 抽 9 字段写 SQLite (复用 ReAct loop, multi-provider)",
    )
    parser.add_argument("url", help="Upwork JD URL")
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
    args = parser.parse_args()

    if args.ignore_rate_limit:
        logger.warning("--ignore-rate-limit ON, 真人节律守护已禁用 (Upwork 反爬风险升)")

    row = asyncio.run(
        extract_url(
            url=args.url,
            db_path=Path(args.db),
            cdp_url=args.cdp_url,
            model=args.model,
            captcha_timeout_s=args.captcha_timeout_s,
            ignore_rate_limit=args.ignore_rate_limit,
        )
    )
    print(json.dumps(row, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
