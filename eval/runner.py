"""V0.26.0: eval runner — 跑单 task 生成 metrics, 复用 chromium.launch fixture pattern.

跟 tests/test_loop_drag_upload.py 同 chromium.launch headless + new_context + new_page +
run_react_loop pattern, 但走完整 ReAct loop (含真 LLM 调用 — vcr 录回放或 mock).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web_agent.llm import LLMClient
from web_agent.loop import run_react_loop

from eval.predicates import Predicate, PredicateResult
from eval.types import EvalTask


@dataclass(frozen=True, slots=True)
class TaskMetric:
    """V0.26.0: 单 task 单 provider 单 run 的 metric. V0.26.2 加 token cost / failure_bucket 扩展."""

    task_id: str
    provider: str
    run_id: str
    pass_: bool  # V0.26.2 metrics JSON 写 "pass" 字段, Python 关键字冲突所以加 _ 后缀
    failure_bucket: str
    steps: int
    wallclock_s: float
    web_agent_task_id: str  # trace.db 里的 task_id (12 字符 hex), 让 replay 面板能 drill down
    final_result: str
    predicate_result: PredicateResult


# V0.26.0: failure_bucket 复用 memory.py FAILURE_MARKERS + 加 4 类 eval 专属
# (PREDICATE_FAIL: 跑完但 predicate 拒; EVAL_TIMEOUT: predicate 跑超时; EVAL_INFRA_ERROR:
# chromium launch 挂 / cassette 损坏; OK: predicate 过)
_LOOP_FAILURE_MARKERS = (
    "WALLCLOCK_EXCEEDED", "SAFETY_BLOCK", "CAPTCHA_TIMEOUT",
    "LOOP_DETECTED", "LLM_FAILED", "(max_steps 耗尽未完成)",
)


def _classify_failure_bucket(predicate: PredicateResult, final_result: str) -> str:
    """V0.26.0: 把 final_result + predicate 结果归类到 10 个 failure bucket 之一."""
    if predicate.matched:
        return "OK"
    # 上游 loop sentinel 命中
    for marker in _LOOP_FAILURE_MARKERS:
        if marker in final_result:
            # 标准化 sentinel 名作 bucket (e.g. "LLM_FAILED" → "LLM_FAILED")
            return marker.split(" ")[0].split(":")[0]
    # 跑完但 predicate 拒
    return "PREDICATE_FAIL"


async def run_one(
    task: EvalTask,
    client: LLMClient,
    predicate: Predicate,
    *,
    db_path: Path,
    screenshots_dir: Path,
    chromium_launcher: Any,  # Playwright Chromium browser_type, 让 caller 决定 launch 时机
) -> TaskMetric:
    """V0.26.0: 跑单 task 单 client 单 run, 返 TaskMetric.

    chromium_launcher 是 Playwright `p.chromium` (caller 在 async with async_playwright() 内
    传入). 不在 runner 内 async with 是为让 caller 跨 task 复用 playwright 实例 (省 launch 开销)
    且避免 runner 强依赖 async_playwright 顶层 import.

    db_path / screenshots_dir 跟 cli.py 同 default 但 caller 应该传 task-isolated 路径
    (eval/data/<run_id>/) 防 baseline run 之间 trace 互相覆盖.
    """
    run_id = uuid.uuid4().hex[:8]
    t_start = time.time()
    web_agent_task_id = ""
    final_result = ""

    try:
        browser = await chromium_launcher.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await browser.new_context(accept_downloads=True)
            page = await ctx.new_page()
            await page.goto(task.fixture_url)
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            final_result = await run_react_loop(
                ctx=ctx, client=client, goal=task.goal,
                max_steps=task.max_steps,
                max_wallclock_s=task.max_wallclock_s,
                db_path=db_path, screenshots_dir=screenshots_dir,
            )
            # 从 trace.db 拿 web_agent_task_id (run_react_loop 内 uuid 生成的, 不返出来)
            web_agent_task_id = _last_task_id(db_path)
        finally:
            await browser.close()
    except Exception as e:
        return TaskMetric(
            task_id=task.task_id, provider=client.name, run_id=run_id,
            pass_=False, failure_bucket="EVAL_INFRA_ERROR",
            steps=0, wallclock_s=time.time() - t_start,
            web_agent_task_id="", final_result=f"INFRA: {type(e).__name__}: {e}",
            predicate_result=PredicateResult(matched=False, reason=str(e)[:200], name="N/A"),
        )

    trace_steps = _read_trace_steps(db_path, web_agent_task_id)
    pred_result = predicate.evaluate(final_result, trace_steps)
    return TaskMetric(
        task_id=task.task_id,
        provider=client.name,
        run_id=run_id,
        pass_=pred_result.matched,
        failure_bucket=_classify_failure_bucket(pred_result, final_result),
        steps=len(trace_steps),
        wallclock_s=time.time() - t_start,
        web_agent_task_id=web_agent_task_id,
        final_result=final_result[:500],
        predicate_result=pred_result,
    )


def _last_task_id(db_path: Path) -> str:
    """V0.26.0: 拿 trace.db 最后写入的 task_id (run_react_loop 不返出来, 从 db 拿)."""
    if not db_path.exists():
        return ""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT task_id FROM tasks ORDER BY started DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return ""
    finally:
        conn.close()
    return row[0] if row else ""


def _read_trace_steps(db_path: Path, web_agent_task_id: str) -> list[dict[str, Any]]:
    """V0.26.0: 拿指定 task_id 的 trace.steps list[dict] 让 predicate evaluate 时可看 step 历史."""
    if not db_path.exists() or not web_agent_task_id:
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT step, action_type, action_args, observation FROM steps "
            "WHERE task_id=? ORDER BY step",
            (web_agent_task_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return [
        {"step": r[0], "action_type": r[1], "action_args": json.loads(r[2]) if r[2] else {},
         "observation": r[3] or ""}
        for r in rows
    ]


def metric_to_dict(m: TaskMetric) -> dict[str, Any]:
    """V0.26.0: TaskMetric → JSON-safe dict (pass_ 字段写回 'pass' key)."""
    return {
        "task_id": m.task_id,
        "provider": m.provider,
        "run_id": m.run_id,
        "pass": m.pass_,
        "failure_bucket": m.failure_bucket,
        "steps": m.steps,
        "wallclock_s": round(m.wallclock_s, 2),
        "web_agent_task_id": m.web_agent_task_id,
        "final_result": m.final_result,
        "predicate_result": {
            "matched": m.predicate_result.matched,
            "reason": m.predicate_result.reason,
            "name": m.predicate_result.name,
        },
    }
