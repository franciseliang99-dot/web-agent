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
from eval.pricing import cost_usd
from eval.types import EvalTask


@dataclass(frozen=True, slots=True)
class TaskMetric:
    """V0.26.0+V0.26.2: 单 task 单 provider 单 run 的 metric.

    V0.26.2: 加 input/output_tokens (累自 client.last_usage 跨 step) + cost_usd
    (eval/pricing.py PRICING 反查) + llm_calls (step 数代理, 1 step ≈ 1 plan 调用).
    """

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
    # V0.26.2 token cost
    input_tokens: int = 0
    output_tokens: int = 0
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0


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
    """V0.26.0+V0.26.2: 跑单 task 单 client 单 run, 返 TaskMetric (含 token cost).

    chromium_launcher 是 Playwright `p.chromium` (caller 在 async with async_playwright() 内
    传入). 不在 runner 内 async with 是为让 caller 跨 task 复用 playwright 实例 (省 launch 开销)
    且避免 runner 强依赖 async_playwright 顶层 import.

    db_path / screenshots_dir 跟 cli.py 同 default 但 caller 应该传 task-isolated 路径
    (eval/data/<run_id>/) 防 baseline run 之间 trace 互相覆盖.

    V0.26.2: 跑前 reset client.last_usage = None (mutable state cross-task 残留风险);
    跑后从 trace 拿 step 数 + 假设每 step 1 plan call → step × last_usage 估总 token.
    精确累加需要在 loop 每 step 后读 last_usage 累加 (V0.26.2 简化: 末次 last_usage × step 数).
    """
    run_id = uuid.uuid4().hex[:8]
    t_start = time.time()
    web_agent_task_id = ""
    final_result = ""
    # V0.26.2: reset last_usage 防上次 task 残留
    if hasattr(client, "last_usage"):
        try:
            client.last_usage = None
        except Exception:
            pass

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
    # V0.26.2: token cost 估算 — last_usage 是末次 call 用量, × step 数估总用量 (假设
    # cache hit 后 N step 用量近似). V0.26.3 cassette 路径会从 cassette 累加精确值取代估算.
    last_usage = getattr(client, "last_usage", None)
    if last_usage is not None and len(trace_steps) > 0:
        in_tok = last_usage.input_tokens * len(trace_steps)
        out_tok = last_usage.output_tokens * len(trace_steps)
        in_cost, out_cost = cost_usd(client.model, in_tok, out_tok)
    else:
        in_tok = out_tok = 0
        in_cost = out_cost = 0.0
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
        input_tokens=in_tok,
        output_tokens=out_tok,
        input_cost_usd=in_cost,
        output_cost_usd=out_cost,
    )


@dataclass(frozen=True, slots=True)
class CorpusReport:
    """V0.26.2: run_corpus 返结构, 含 task × provider grid 全 metric + run 元信息."""

    run_id: str
    started_at: float
    ended_at: float
    metrics: list[TaskMetric]


async def run_corpus(
    tasks: list[EvalTask],
    clients: list[LLMClient],
    predicates: dict[str, Predicate],
    *,
    db_path: Path,
    screenshots_dir: Path,
    chromium_launcher: Any,
) -> CorpusReport:
    """V0.26.2: 跑 task × provider grid (串行 N task × M provider, fresh chromium per cell).

    sanity B: cross-provider 也 fresh launch (cookie/storage 隔离 > 内存; 18 cells 串行 ~3 min).
    """
    run_id = uuid.uuid4().hex[:12]
    started_at = time.time()
    metrics: list[TaskMetric] = []
    for task in tasks:
        pred = predicates.get(task.task_id)
        if pred is None:
            continue  # 缺 predicate 的 task 跳过 (lint_corpus_tokens 会拦)
        for client in clients:
            m = await run_one(
                task, client, pred,
                db_path=db_path, screenshots_dir=screenshots_dir,
                chromium_launcher=chromium_launcher,
            )
            metrics.append(m)
    return CorpusReport(
        run_id=run_id, started_at=started_at, ended_at=time.time(), metrics=metrics,
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
    """V0.26.0+V0.26.2: TaskMetric → JSON-safe dict (pass_ 字段写回 'pass' key + V0.26.2 token cost)."""
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
        # V0.26.2 token cost
        "input_tokens": m.input_tokens,
        "output_tokens": m.output_tokens,
        "input_cost_usd": round(m.input_cost_usd, 6),
        "output_cost_usd": round(m.output_cost_usd, 6),
    }
