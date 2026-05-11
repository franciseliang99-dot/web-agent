"""V0.26.0: eval runner — 跑单 task 生成 metrics, 复用 chromium.launch fixture pattern.

跟 tests/test_loop_drag_upload.py 同 chromium.launch headless + new_context + new_page +
run_react_loop pattern, 但走完整 ReAct loop (含真 LLM 调用 — vcr 录回放或 mock).
"""

from __future__ import annotations

import dataclasses
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
    (eval/pricing.py PRICING 反查) + llm_calls (步数代理).
    V0.28.3: 加 inject_reflections 区分 reflect 2-pass 的 run1 (False) vs run2 (True).
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
    # V0.28.3 W6 收尾: reflect 2-pass 时区分 run1 (False) vs run2 (True)
    inject_reflections: bool = False
    # V0.29.4 W6-C 收尾: chain task 时 = completed_nodes/total_nodes (默 None = 非 chain task)
    chain_node_pass_rate: float | None = None
    # V0.30.1 D real-world: flaky_repeat>1 时区分第 N 次重跑 (默 0 = 单跑或第 1 次), JSON dump 用
    flaky_repeat_idx: int = 0


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
    memory_db_path: Path | None = None,
    inject_reflections: bool = False,
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

    # V0.28.3 W6 收尾: inject_reflections=True 时构造 memories_str 注入 (复用 cli build_inject_string).
    # eval task fixture 多为 data:text/html → extract_domain 返 "" → recall 返 [] → 自然 None
    # (除非 task fixture 是 https:// + memory_db_path 已有同 domain 反思). isolated db 防 Risk #1.
    memories_str: str | None = None
    eval_domain = ""
    if inject_reflections and memory_db_path is not None:
        from web_agent.memory import build_inject_string, extract_domain
        eval_domain = extract_domain(task.fixture_url)
        memories_str = build_inject_string(
            memory_db_path, eval_domain,
            include_memories=False,  # eval 隔离: 只 inject reflections, 不掺 memories
            include_reflections=True,
        )

    # V0.29.4 W6-C 收尾: chain task 走 run_chain 分支 (eval/runner 检测 task.chain_spec).
    # subagent 决: 内部 if 分支复用 run_one (TaskMetric 字段够覆盖, chain_node_pass_rate 默 None).
    chain_node_pass_rate: float | None = None
    try:
        browser = await chromium_launcher.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await browser.new_context(accept_downloads=True)
            page = await ctx.new_page()
            await page.goto(task.fixture_url)
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            if task.chain_spec is not None:
                # V0.29.4: chain task — 复用 ctx 跨 node 接力 (Chrome 当前 tab 不重 goto)
                final_result, chain_node_pass_rate = await _run_chain_branch(
                    task, client, ctx,
                    db_path=db_path, screenshots_dir=screenshots_dir,
                    memories=memories_str, domain=eval_domain, memory_db_path=memory_db_path,
                )
            else:
                final_result = await run_react_loop(
                    ctx=ctx, client=client, goal=task.goal,
                    max_steps=task.max_steps,
                    max_wallclock_s=task.max_wallclock_s,
                    db_path=db_path, screenshots_dir=screenshots_dir,
                    memories=memories_str,
                    domain=eval_domain,
                    memory_db_path=memory_db_path,  # W6-A reflect 写入路径
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
            inject_reflections=inject_reflections,
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
        inject_reflections=inject_reflections,
        chain_node_pass_rate=chain_node_pass_rate,
    )


async def _run_chain_branch(
    task: EvalTask,
    client: LLMClient,
    ctx: Any,
    *,
    db_path: Path,
    screenshots_dir: Path,
    memories: str | None = None,
    domain: str = "",
    memory_db_path: Path | None = None,
) -> tuple[str, float]:
    """V0.29.4 W6-C: eval chain task 跑 run_chain 分支 helper (run_one 内 dispatch).

    DI run_task_fn 闭包包 run_react_loop, 跨 node 复用 ctx (Chrome 当前 tab 接力, 不重 goto).
    返 (final_result_summary, node_pass_rate). final_result 拼 chain_id + completed + 末 node result
    raw 让 SubstringPredicate 直接命中 (subagent G 决, 不包装层).
    """
    from web_agent.chain import run_chain

    assert task.chain_spec is not None  # caller 已 check

    async def _eval_run_task_fn(*, goal: str, max_wallclock_s: float | None = None, **_: object) -> str:
        # V0.29.4: 跨 node 复用 ctx (无 fresh page.goto), max_wallclock_s 由 chain runner remaining cap
        return await run_react_loop(
            ctx=ctx, client=client, goal=goal,
            max_steps=task.max_steps, max_wallclock_s=max_wallclock_s or task.max_wallclock_s,
            db_path=db_path, screenshots_dir=screenshots_dir,
            memories=memories, domain=domain, memory_db_path=memory_db_path,
        )

    chain_result = await run_chain(
        task.chain_spec, _eval_run_task_fn,
        max_total_wallclock_s=task.max_wallclock_s,  # 整 chain cap = task max_wallclock
    )

    # subagent G: chain summary 拼末 node result raw 让 predicate substring 命中
    n_total = len(chain_result.node_results)
    n_ok = sum(1 for nr in chain_result.node_results if nr.success)
    last_result = chain_result.node_results[-1].result if chain_result.node_results else "(empty chain)"
    summary = f"chain {chain_result.chain_id}: {n_ok}/{n_total} OK; final={last_result}"
    pass_rate = n_ok / n_total if n_total > 0 else 0.0
    return summary, pass_rate


@dataclass(frozen=True, slots=True)
class CorpusReport:
    """V0.26.2: run_corpus 返结构, 含 task × provider grid 全 metric + run 元信息."""

    run_id: str
    started_at: float
    ended_at: float
    metrics: list[TaskMetric]


# V0.30.1 D real-world / V0.30.1 simplify: 11 项 LLM secret + 机器画像 redact 列表 — eval runner +
# tests/conftest.py vcr_config 共享单一来源 (V0.30.1 commit 自承认 helper 复制 conftest, 已抽).
# tests/conftest.py 是测试 fixture, eval/ 是 production code; 单源放 production 侧, conftest import
# 反向 (production 永不 import tests/). 加新 redact header 改本元组即可两侧同步.
_VCR_FILTER_HEADERS: tuple[tuple[str, str], ...] = (
    ("authorization", "REDACTED"),
    ("x-api-key", "REDACTED"),
    ("anthropic-version", "REDACTED"),
    ("openai-organization", "REDACTED"),
    ("user-agent", "REDACTED"),
    ("x-stainless-arch", "REDACTED"),
    ("x-stainless-os", "REDACTED"),
    ("x-stainless-runtime", "REDACTED"),
    ("x-stainless-runtime-version", "REDACTED"),
    ("x-stainless-lang", "REDACTED"),
    ("x-stainless-package-version", "REDACTED"),
)
_VCR_FILTER_QUERY_PARAMETERS: tuple[tuple[str, str], ...] = (
    ("api_key", "REDACTED"),
)


def _get_eval_vcr_config() -> dict[str, Any]:
    """V0.30.1 D real-world: vcr config — filter LLM key 防泄漏 + record_mode once.

    11 项 redact 共享 _VCR_FILTER_HEADERS (tests/conftest.py vcr_config 也 import 此元组单源).
    cassette dir 由 caller 传, runner 用 vcr.use_cassette(path, **config) 包 LLM call 段
    防 chromium WebSocket.

    record_mode "once": 已有 cassette 重放, 否则录制后写盘 (跟 conftest 一致). EVAL_REAL=1
    + EVAL_LIVE_NET=1 真录, 默回放 (cassette 不在则 raise — caller 决定 fallback).
    """
    return {
        "filter_headers": list(_VCR_FILTER_HEADERS),
        "filter_query_parameters": list(_VCR_FILTER_QUERY_PARAMETERS),
        "record_mode": "once",
    }


async def run_corpus(
    tasks: list[EvalTask],
    clients: list[LLMClient],
    predicates: dict[str, Predicate],
    *,
    db_path: Path,
    screenshots_dir: Path,
    chromium_launcher: Any,
    reflect: bool = False,
    memory_db_path: Path | None = None,
) -> CorpusReport:
    """V0.26.2: 跑 task × provider grid (串行 N task × M provider, fresh chromium per cell).

    V0.28.3 W6 收尾: reflect=True → 每 task 跑 2 次 (subagent B 决, task-by-task 配对):
    - run1 inject_reflections=False (baseline)
    - run2 inject_reflections=True (W6-A 反思 inject 后)
    每 task 跑前清 reflections 表 (Risk #1 修: 跨 task 共 domain 污染 防止) + isolated
    memory_db_path (caller 传 output_dir / "eval_memory.db" 防写脏主用户 db).

    cost: reflect=True 烧 token 翻倍 (每 task 2 次 LLM call), opt-in.
    """
    run_id = uuid.uuid4().hex[:12]
    started_at = time.time()
    metrics: list[TaskMetric] = []
    for task in tasks:
        # V0.30.1 D real-world: flaky_repeat × reflect 互斥早 assert (subagent D 决, 配对算法
        # 假设单配对, V0.30.4 收尾再决合并语义)
        if reflect and task.flaky_repeat > 1:
            raise RuntimeError(
                f"V0.30.1: task {task.task_id!r} flaky_repeat={task.flaky_repeat} 跟 reflect=True "
                "互斥 (V0.28.3 by_pair 算法假设单配对). V0.30.4 收尾再决合并语义."
            )
        # V0.30.1: chain task 禁 flaky_repeat>1 (chain 内 node-level retry 已存外层冗余)
        if task.chain_spec is not None and task.flaky_repeat > 1:
            raise RuntimeError(
                f"V0.30.1: chain task {task.task_id!r} flaky_repeat={task.flaky_repeat} 禁用 "
                "(chain 内 node-level retry 已存)."
            )
        pred = predicates.get(task.task_id)
        if pred is None:
            continue  # 缺 predicate 的 task 跳过 (lint_corpus_tokens 会拦)
        for client in clients:
            if reflect and memory_db_path is not None:
                # V0.28.3 W6 2-pass: 每 task 清 reflections 表防跨 task 污染 (Risk #1)
                from web_agent.memory import clear_reflections
                clear_reflections(memory_db_path)
                # run1: baseline 不 inject (W6-A 触发会写表给 run2)
                m1 = await run_one(
                    task, client, pred,
                    db_path=db_path, screenshots_dir=screenshots_dir,
                    chromium_launcher=chromium_launcher,
                    memory_db_path=memory_db_path,
                    inject_reflections=False,
                )
                metrics.append(m1)
                # run2: inject reflections (run1 写的反思 — 同 task 配对, 不跨 task)
                m2 = await run_one(
                    task, client, pred,
                    db_path=db_path, screenshots_dir=screenshots_dir,
                    chromium_launcher=chromium_launcher,
                    memory_db_path=memory_db_path,
                    inject_reflections=True,
                )
                metrics.append(m2)
            else:
                # V0.30.1 D real-world: flaky_repeat 内 loop, metric 各 run_id 独立 + flaky_repeat_idx 区分
                for repeat_idx in range(task.flaky_repeat):
                    m = await run_one(
                        task, client, pred,
                        db_path=db_path, screenshots_dir=screenshots_dir,
                        chromium_launcher=chromium_launcher,
                    )
                    if task.flaky_repeat > 1:
                        m = dataclasses.replace(m, flaky_repeat_idx=repeat_idx)
                    metrics.append(m)
    return CorpusReport(
        run_id=run_id, started_at=started_at, ended_at=time.time(), metrics=metrics,
    )


def _last_task_id(db_path: Path) -> str:
    """V0.26.0+V0.26.4: 拿 trace.db 最后写入的 task_id.

    V0.26.4 实测发现 V0.26.0 用错列名 `started` (实际 `started_at`) → SQL OperationalError
    → except 兜底返 "" → web_agent_task_id 为空 → _read_trace_steps 也返空 → metrics
    steps=0 input_tokens=0 全为 0. 修正用 started_at.
    """
    if not db_path.exists():
        return ""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT task_id FROM tasks ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
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
        # V0.28.3 W6 收尾: reflect 2-pass 区分 run1 vs run2
        "inject_reflections": m.inject_reflections,
        # V0.29.4 W6-C 收尾: chain task 时 = completed_nodes/total_nodes, 非 chain → null
        "chain_node_pass_rate": m.chain_node_pass_rate,
        # V0.30.1 D real-world: flaky_repeat>1 时区分第 N 次重跑, 默 0
        "flaky_repeat_idx": m.flaky_repeat_idx,
    }
