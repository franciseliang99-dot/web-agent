#!/usr/bin/env python3
"""V0.20.0 桋桥: upwork.db 未评分 row → jobscout-bot cli:eval-jd → UPDATE 回写.

CLAUDE.md "Sync rule": jobscout-bot fit-rubric.ts 是 SoT, 本桥不重写 rubric, 跨 repo
单点 maintain. 副作用: 每跑一行在 jobscout-bot/data/outbox/ 多一份 markdown 卡 (jobscout-bot
设计如此, audit trail).

Usage:
    python scripts/score_upwork.py --limit 5
    python scripts/score_upwork.py --db data/upwork.db --jobscout-bot ~/jobscout-bot
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_JOBSCOUT_BOT = Path.home() / "jobscout-bot"
DEFAULT_DB = Path("data/upwork.db")
EVAL_JD_TIMEOUT_S = 120
INTER_ROW_DELAY_S = 2

_STDOUT_OUTBOX_RE = re.compile(r"^\s*✓\s+outbox card:\s+(\S+)", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def render_frontmatter(row: dict[str, Any]) -> str:
    """upwork.db row → jobscout-bot FRONTMATTER_TEMPLATE 格式 (manual-eval.ts:23)."""
    lines = [
        f"Title: {row.get('title') or 'Unknown Upwork JD'}",
        f"Org: Upwork client ({row.get('client_country') or 'unknown country'})",
        "Location: Remote · Worldwide async",
    ]
    if row.get("url"):
        lines.append(f"URL: {row['url']}")
    if row.get("budget"):
        lines.append(f"Salary: {row['budget']}")
    if row.get("posted_at"):
        lines.append(f"PostedDate: {row['posted_at']}")
    lines.append("---")
    lines.append(row.get("description") or "(JD body 为空 — 请在 Upwork 页面手动确认)")
    return "\n".join(lines)


def parse_outbox_frontmatter(card_path: Path) -> dict[str, str]:
    """读 outbox markdown card, 手解 YAML frontmatter (无 yaml 依赖, frontmatter 是简单 key:value 行)."""
    text = card_path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise RuntimeError(f"outbox card 缺 frontmatter: {card_path}")
    fm: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm


def run_eval_jd(frontmatter: str, jobscout_bot: Path) -> dict[str, Any]:
    """pipe frontmatter 给 pnpm cli:eval-jd -, 拿到 outbox card path → parse → 返回 score/rec/fit_json."""
    proc = subprocess.run(
        ["pnpm", "--dir", str(jobscout_bot), "cli:eval-jd", "-"],
        input=frontmatter,
        capture_output=True,
        text=True,
        timeout=EVAL_JD_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"eval-jd 退出 {proc.returncode}\n"
            f"stderr:\n{proc.stderr[:500]}\nstdout:\n{proc.stdout[:500]}"
        )
    outbox_match = _STDOUT_OUTBOX_RE.search(proc.stdout)
    if not outbox_match:
        raise RuntimeError(f"eval-jd stdout 没找到 ✓ outbox card 行:\n{proc.stdout[:500]}")
    outbox_path = jobscout_bot / outbox_match.group(1)

    fm = parse_outbox_frontmatter(outbox_path)
    try:
        score = int(fm.get("fit_score", "0"))
    except ValueError:
        score = 0
    rec = fm.get("fit_recommendation", "manual-review")
    return {
        "score": score,
        "recommendation": rec,
        "outbox_path": str(outbox_path),
        "fit_json": json.dumps(fm, ensure_ascii=False),
    }


def score_unscored(db_path: Path, jobscout_bot: Path, limit: int) -> int:
    """SELECT score IS NULL → run_eval_jd → UPDATE. 单行失败 continue 不阻塞其它行. 返回成功数."""
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "SELECT url, title, description, budget, client_country, posted_at "
        "FROM upwork_jds WHERE score IS NULL ORDER BY scraped_at DESC LIMIT ?",
        (limit,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    if not rows:
        logger.info("no unscored rows in %s", db_path)
        conn.close()
        return 0

    logger.info("scoring %d row(s) via %s", len(rows), jobscout_bot)
    n_ok = 0
    for i, row in enumerate(rows):
        title_log = (row.get("title") or row["url"])[:60]
        logger.info("[%d/%d] → %s", i + 1, len(rows), title_log)
        try:
            result = run_eval_jd(render_frontmatter(row), jobscout_bot)
        except Exception as e:
            logger.warning("  eval-jd failed: %r", e)
            continue
        conn.execute(
            "UPDATE upwork_jds SET score=?, recommendation=?, fit_json=? WHERE url=?",
            (result["score"], result["recommendation"], result["fit_json"], row["url"]),
        )
        conn.commit()
        logger.info(
            "  score=%d (%s) outbox=%s",
            result["score"], result["recommendation"], result["outbox_path"],
        )
        n_ok += 1
        if i < len(rows) - 1:
            time.sleep(INTER_ROW_DELAY_S)
    conn.close()
    return n_ok


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="[%(name)s] %(message)s"
    )
    parser = argparse.ArgumentParser(
        prog="score_upwork",
        description="V0.20.0 bridge: upwork.db unscored row → jobscout-bot eval-jd → write back",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite path (默认 {DEFAULT_DB})")
    parser.add_argument(
        "--jobscout-bot",
        default=str(DEFAULT_JOBSCOUT_BOT),
        help=f"jobscout-bot repo path (默认 {DEFAULT_JOBSCOUT_BOT})",
    )
    parser.add_argument("--limit", type=int, default=5, help="单次处理上限 (默认 5)")
    args = parser.parse_args()

    n = score_unscored(Path(args.db), Path(args.jobscout_bot), limit=args.limit)
    print(f"scored {n} row(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
