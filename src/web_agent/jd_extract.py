"""V0.20.0 JD extract entrypoint — 从单个 Upwork JD URL 抽 9 字段写 SQLite.

路径 D (CHANGELOG V0.20.0): 用户从 Upwork 原生 saved-search email alert 手动拿 JD URL,
贴给 web-agent-jd, 走 deterministic perceive + 单次 Anthropic SDK tool_use, 写 data/upwork.db.
评分由 scripts/score_upwork.py 桥到 jobscout-bot eval-jd (rubric 单 SoT).

设计原则 (按 CLAUDE.md 解耦):
- 本文件是独立组合根 (mirror cli.py), 不依赖 ReAct loop / memory / planner.
- 复用 chrome_launcher / browser / perceiver / captcha (无状态业务层 / adapter).
- 真人节律守护 (≤1/min, ≤30/30min) 放本层, SQLite 自身做状态存储, 跨 shell 重启状态连续.
- LLM extract 直调 Anthropic SDK (不复用 AnthropicClient.plan: 它的 SYSTEM_PROMPT 与 7 ReAct tools
  是 ReAct-specific, JD extract 是不同语义).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import (
    MessageParam,
    TextBlockParam,
    ToolChoiceToolParam,
    ToolParam,
)
from dotenv import load_dotenv
from playwright.async_api import Page, async_playwright

from web_agent.browser import apply_stealth, connect
from web_agent.captcha import detect as captcha_detect
from web_agent.chrome_launcher import ensure_chrome_running
from web_agent.notify import notify
from web_agent.perceiver import perceive

logger = logging.getLogger(__name__)

DEFAULT_DB = Path("data/upwork.db")
DEFAULT_MODEL = "claude-sonnet-4-6"
RATE_LIMIT_MIN_INTERVAL_S = 60.0
RATE_LIMIT_SESSION_WINDOW_S = 1800.0
RATE_LIMIT_SESSION_CAP = 30
DESCRIPTION_TRUNC_CHARS = 8000


# ===== JD extract tool schema (单工具 single tool_use, 不复用 _schema.TOOL_SCHEMAS) =====

_JD_FIELDS_TOOL: dict[str, Any] = {
    "name": "report_jd",
    "description": "从 Upwork JD 页面截图提取字段为 JSON. 看不到的字段 omit (不要瞎猜).",
    "input_schema": {
        "type": "object",
        "properties": {
            "thought": {"type": "string", "description": "你看到了什么 / 哪些字段缺失"},
            "title": {"type": "string", "description": "JD 标题原文"},
            "description": {"type": "string", "description": "JD body 完整内容"},
            "budget": {"type": "string", "description": "预算原文 e.g. 'Fixed-price $500' 或 '$30-50/hr'"},
            "hourly": {"type": "boolean", "description": "true=hourly, false=fixed-price"},
            "client_country": {"type": "string"},
            "client_rating": {"type": "number", "description": "客户评分 0-5 浮点"},
            "posted_at": {"type": "string", "description": "发布时间原文 e.g. 'Posted 2 hours ago'"},
            "proposals_count": {"type": "integer", "description": "已提交 proposals 数"},
            "connect_cost": {"type": "integer", "description": "投递所需 connects 数"},
        },
        "required": ["thought", "title", "description"],
    },
}

_JD_EXTRACT_SYSTEM = """你是 Upwork JD 字段提取器. 给你一张 Upwork JD 页面截图, 必须调用 `report_jd` 工具填字段.
title / description 必填; 其它字段截图里看不到就 omit, 严禁瞎猜或编造.
description 应包含 JD body 完整内容 (会被截到 8000 字符)."""


# ===== SQLite =====

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
    """INSERT ... ON CONFLICT(url) DO UPDATE. 重贴同 URL 刷 scraped_at + 字段, 保 id 与已写 score."""
    placeholders = ",".join("?" * len(_UPSERT_FIELDS))
    cols = ",".join(_UPSERT_FIELDS)
    update_set = ",".join(f"{f}=excluded.{f}" for f in _UPSERT_FIELDS if f != "url")
    sql = (
        f"INSERT INTO upwork_jds ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(url) DO UPDATE SET {update_set}"
    )
    conn.execute(sql, tuple(row.get(f) for f in _UPSERT_FIELDS))
    conn.commit()


# ===== captcha guard (deterministic 路径专用; 不写 trace.db, jd_extract 不用 trace 系统) =====

async def wait_captcha_resolution(
    page: Page, timeout_s: float = 300.0, poll_s: float = 3.0
) -> bool:
    """检测 → notify → poll 等用户手解. timeout False / 解决或无 captcha True."""
    info = await captcha_detect(page)
    if info is None:
        return True
    logger.info("%s 命中 @ %s — 请在浏览器手动解决, 每 %ss 重检 (超时 %ss)",
                info.vendor, info.url[:80], poll_s, timeout_s)
    notify("web-agent-jd captcha", f"{info.vendor} 命中, 请手解 ({info.url[:60]})")
    t_start = time.monotonic()
    while time.monotonic() - t_start < timeout_s:
        if await captcha_detect(page) is None:
            logger.info("%s 已清除", info.vendor)
            return True
        await asyncio.sleep(poll_s)
    logger.warning("captcha %ss 未解, 中止", timeout_s)
    return False


# ===== LLM extract (直调 SDK, 单 tool_use) =====

async def llm_extract_jd(
    client: AsyncAnthropic, model: str, screenshot_b64: str
) -> dict[str, Any]:
    """调一次 Anthropic vision + tool_use, 返回 report_jd input dict."""
    user_content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64},
        },
        {"type": "text", "text": "看 Upwork JD 截图, 调 report_jd 填字段. 看不到的 omit."},
    ]
    system: list[TextBlockParam] = [
        {"type": "text", "text": _JD_EXTRACT_SYSTEM, "cache_control": {"type": "ephemeral"}}
    ]
    tool_choice: ToolChoiceToolParam = {"type": "tool", "name": "report_jd"}
    resp = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        tools=cast(list[ToolParam], [_JD_FIELDS_TOOL]),
        tool_choice=tool_choice,
        messages=cast(list[MessageParam], [{"role": "user", "content": user_content}]),
    )
    for block in resp.content:
        if block.type == "tool_use":
            return cast(dict[str, Any], dict(block.input))
    raise RuntimeError(f"LLM 没返回 tool_use: {resp.content!r}")


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
    model: str = DEFAULT_MODEL,
    captcha_timeout_s: float = 300.0,
    ignore_rate_limit: bool = False,
) -> dict[str, Any]:
    """主流程: rate-limit → spawn Chrome → connect → goto → captcha guard → perceive → LLM → upsert."""
    load_dotenv()
    cdp_url = cdp_url or os.environ.get("WEB_AGENT_CDP_URL", "http://127.0.0.1:9222")

    conn = init_upwork_db(db_path)
    if not ignore_rate_limit:
        check_rate_limit(conn)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY 未设置 — 请填 .env 或 export 环境变量")
    sdk_kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 4, "timeout": 120.0}
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if base_url:
        sdk_kwargs["base_url"] = base_url
    client = AsyncAnthropic(**sdk_kwargs)

    await asyncio.to_thread(ensure_chrome_running, cdp_url)

    async with async_playwright() as p:
        _, _, page = await connect(p, cdp_url=cdp_url)
        await apply_stealth(page)
        logger.info("navigating to %s", url)
        await page.goto(url, wait_until="domcontentloaded")

        if not await wait_captcha_resolution(page, timeout_s=captcha_timeout_s):
            raise SystemExit(f"captcha 未在 {captcha_timeout_s}s 内解决, 中止")

        marks, screenshot_b64 = await perceive(page)
        logger.info("perceived %d marks; calling LLM", len(marks))

        fields = await llm_extract_jd(client, model, screenshot_b64)
        logger.info("LLM extract: title=%r budget=%r posted=%r",
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
        description="V0.20.0 路径 D: 从单个 Upwork JD URL 抽 9 字段写 SQLite",
    )
    parser.add_argument("url", help="Upwork JD URL")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite path (默认 {DEFAULT_DB})")
    parser.add_argument("--cdp-url", default=None, help="覆盖 WEB_AGENT_CDP_URL")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--captcha-timeout-s", type=float, default=300.0)
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
