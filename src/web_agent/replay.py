"""Replay 日志面板 (W4-1): 把 trace.db 的 task+steps 渲染成单文件 HTML 时间线。

零新依赖 — stdlib (sqlite3 + html + json + argparse + datetime + pathlib)。
HTML 引用截图走相对路径 ../screenshots/<task_id>-<NN>.png (从 data/replays/ 视角)。

CLI:
  uv run web-agent-replay              # 渲染最新一次 task
  uv run web-agent-replay <task_id>    # 渲染指定 task
  uv run web-agent-replay --db data/trace.db --out data/replays
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path("data/trace.db")
DEFAULT_OUT = Path("data/replays")
SCREENSHOT_DIR_REL = "../screenshots"  # 相对 data/replays/ 的路径

_STEP_CLASS = {
    "safety_block": "step--safety",
    "error": "step--error",
    "done": "step--done",
    "loop_detected": "step--loop",
}


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        sys.exit(f"replay: db 不存在: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_task(task_id: str | None, db_path: Path = DEFAULT_DB) -> dict:
    """加载指定 task (None = 最新)。返回含 steps 列表的 dict。

    Raises:
        SystemExit: db 不存在 / 无 task / 指定 id 不存在。
    """
    conn = _connect(db_path)
    try:
        if task_id is None:
            row = conn.execute(
                "SELECT * FROM tasks ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                sys.exit("replay: tasks 表为空")
            task_id = row["task_id"]
        else:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                sys.exit(f"replay: task_id={task_id!r} 不存在")

        step_rows = conn.execute(
            "SELECT * FROM steps WHERE task_id = ? ORDER BY step", (task_id,)
        ).fetchall()
    finally:
        conn.close()

    steps = []
    for s in step_rows:
        try:
            args = json.loads(s["action_args"]) if s["action_args"] else {}
        except json.JSONDecodeError:
            args = {"_raw": s["action_args"]}  # fallback 不破整页
        steps.append({
            "step": s["step"],
            "ts": s["ts"],
            "thought": s["thought"] or "",
            "action_type": s["action_type"] or "",
            "action_args": args,
            "screenshot_path": s["screenshot_path"] or "",
            "observation": s["observation"] or "",
        })
    return {
        "task_id": row["task_id"],
        "goal": row["goal"] or "",
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "result": row["result"] or "",
        "steps": steps,
    }


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _shot_src(task_id: str, step: int) -> str:
    return f"{SCREENSHOT_DIR_REL}/{task_id}-{step:02d}.png"


_CSS = """
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         max-width: 960px; margin: 2em auto; padding: 0 1em; color: #222; }
  h1 { font-size: 1.4em; line-height: 1.4; }
  .task-meta { background: #f5f5f5; padding: 0.8em 1em; border-radius: 4px;
               font-size: 0.9em; line-height: 1.6; }
  .task-meta code { background: #fff; padding: 1px 5px; border-radius: 2px; }
  .step { border-left: 4px solid #ccc; padding: 0.8em 1em; margin: 1em 0;
          background: #fafafa; border-radius: 0 4px 4px 0; }
  .step--safety { border-left-color: #d32f2f; background: #fff3f3; }
  .step--error  { border-left-color: #f9a825; background: #fffbe6; }
  .step--done   { border-left-color: #2e7d32; background: #f0fff0; }
  .step--loop   { border-left-color: #ef6c00; background: #fff7eb; }
  .step h3 { margin: 0 0 0.4em 0; font-size: 1em; }
  .action-type { display: inline-block; padding: 1px 8px; border-radius: 3px;
                 background: #333; color: #fff; font-family: monospace; font-size: 0.85em; }
  .ts { color: #888; font-size: 0.85em; font-weight: normal; }
  .thought { color: #555; font-style: italic; margin: 0.4em 0; }
  pre.action { font-family: monospace; font-size: 0.85em; background: #fff;
               padding: 0.5em 0.8em; border: 1px solid #e0e0e0; border-radius: 3px;
               overflow-x: auto; margin: 0.4em 0; white-space: pre-wrap; word-break: break-all; }
  .observation { color: #444; font-size: 0.9em; margin: 0.4em 0; }
  .observation:before { content: "→ "; color: #888; }
  details.shot { margin-top: 0.6em; }
  details.shot summary { cursor: pointer; color: #1976d2; font-size: 0.9em; }
  details.shot img { display: block; max-width: 100%; margin-top: 0.5em;
                     border: 1px solid #ddd; border-radius: 2px; }
"""


def _render_step(task_id: str, step: dict) -> str:
    sclass = _STEP_CLASS.get(step["action_type"], "")
    args_pretty = json.dumps(step["action_args"], ensure_ascii=False, indent=2)
    return (
        f'<section class="step {sclass}" id="step-{step["step"]:02d}">\n'
        f'  <h3>#{step["step"]:02d} '
        f'<span class="action-type">{html.escape(step["action_type"])}</span> '
        f'<span class="ts">{_fmt_ts(step["ts"])}</span></h3>\n'
        f'  <div class="thought">{html.escape(step["thought"])}</div>\n'
        f'  <pre class="action">{html.escape(args_pretty)}</pre>\n'
        f'  <details class="shot"><summary>screenshot</summary>'
        f'<img src="{html.escape(_shot_src(task_id, step["step"]))}" '
        f'alt="step {step["step"]:02d} (missing)" loading="lazy"></details>\n'
        f'  <div class="observation">{html.escape(step["observation"])}</div>\n'
        f'</section>\n'
    )


def render_html(task: dict) -> str:
    """把 load_task() 的 dict 渲染成完整单文件 HTML。"""
    steps_html = "".join(_render_step(task["task_id"], s) for s in task["steps"])
    return (
        f'<!DOCTYPE html>\n'
        f'<html lang="zh-CN"><head><meta charset="utf-8">\n'
        f'<title>web-agent replay — {html.escape(task["task_id"])}</title>\n'
        f'<style>{_CSS}</style></head>\n'
        f'<body>\n'
        f'<h1>{html.escape(task["goal"])}</h1>\n'
        f'<div class="task-meta">\n'
        f'  task_id: <code>{html.escape(task["task_id"])}</code><br>\n'
        f'  started: {_fmt_ts(task["started_at"])} → ended: {_fmt_ts(task["ended_at"])}<br>\n'
        f'  steps: {len(task["steps"])}<br>\n'
        f'  result: <strong>{html.escape(task["result"])}</strong>\n'
        f'</div>\n'
        f'{steps_html}'
        f'</body></html>\n'
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="web-agent-replay",
                                description="渲染 trace.db 单次 task 为 HTML 时间线")
    p.add_argument("task_id", nargs="?", help="task_id (省略 = 最新一次)")
    p.add_argument("--db", default=str(DEFAULT_DB), help="trace.db 路径 (默认 data/trace.db)")
    p.add_argument("--out", default=str(DEFAULT_OUT),
                   help="输出目录 (默认 data/replays/, 文件名 <task_id>.html)")
    args = p.parse_args(argv)

    task = load_task(args.task_id, db_path=Path(args.db))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{task['task_id']}.html"
    out_path.write_text(render_html(task), encoding="utf-8")
    print(f"wrote {out_path} ({len(task['steps'])} steps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
