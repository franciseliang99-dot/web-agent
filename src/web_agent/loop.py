"""ReAct loop: max_steps + Action Trace + 每步持久化截图/思考/行动。"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from collections import Counter, deque
from pathlib import Path
from typing import Any, Awaitable, Callable

from playwright.async_api import BrowserContext, Frame, Page

from web_agent.actuator import (
    human_like_click,
    human_like_drag,
    human_like_keyboard_shortcut,
    human_like_paste,
    human_like_type,
    scroll,
    think,
    upload_file,
)
from web_agent.captcha import detect as captcha_detect
from web_agent.llm import LLMClient
from web_agent.memory import record_reflection
from web_agent.notify import notify
from web_agent.perceiver import perceive
from web_agent.safety import check as safety_check
from web_agent.trace import Step, Trace, end_task, init_db, start_task, write_step
from web_agent.types import (
    Action,
    ClickAction,
    CloseTabAction,
    DoneAction,
    DragAction,
    ExtractAction,
    KeyboardShortcutAction,
    Mark,
    PasteAction,
    ScrollAction,
    SwitchTabAction,
    TypeAction,
    UploadAction,
)

# V0.18.0 elicitation callback: 业务层接收 (rule, reason) → True 放行 / False 拦.
# 组合根 (mcp_server.py) 注入 ctx.elicit 包装; CLI 模式 None → 维持 env-based 现状.
SafetyApprovalCallback = Callable[[str, str], Awaitable[bool]]

# V0.16.1 progress callback: (step_i, max_steps, message=None) → 注 mcp ctx.report_progress
# 形参可选, 不传则 loop 行为 100% 同 V0.16.0; 传则主循环每步 + captcha poll 心跳触发
ProgressCallback = Callable[[int, int, str | None], Awaitable[None]]


def _action_args_only(action: Action) -> dict[str, Any]:
    """V0.17.0: 序列化 dataclass action 到 dict, 剔 type/thought (trace 兼容旧 schema).

    用于 trace.Step.action_args + safety_block step + LOOP_DETECTED step + log + signature.
    """
    return {
        f.name: getattr(action, f.name)
        for f in dataclasses.fields(action)
        if f.name not in ("type", "thought")
    }


logger = logging.getLogger(__name__)


def _find_mark(marks: list[Mark], mark_id: int) -> Mark | None:
    return next((m for m in marks if m.id == mark_id), None)


def _normalize_extract_query(query: str) -> str:
    """V0.46.1 真发现 #25 follow-up: normalize ExtractAction query for anti_loop sig.

    LLM 反复试 extract 时 query wording 微调 (大小写/空格/标点变体) — 让 sig 合并语义相同的
    wording 变体. lowercase + strip punctuation + collapse whitespace. 不 truncate 避免
    over-collapse 不同意图的 query.
    """
    s = query.lower()
    s = re.sub(r"[^\w\s一-鿿]", "", s)  # 保 alphanumeric + CJK + whitespace
    return re.sub(r"\s+", " ", s).strip()


def _action_signature(action: Action) -> str:
    """归一化 action 用于死循环检测. V0.17.0: dataclass action 用 _action_args_only 取字段.

    V0.46.1 真发现 #25 follow-up: ExtractAction 特殊处理 — 删 answer (LLM 生成 noise) +
    normalize query (lowercase / punctuation / whitespace). 修 V0.44 HN WALLCLOCK task
    11 step extract loop anti_loop miss.
    """
    if isinstance(action, ExtractAction):
        return f"extract:{_normalize_extract_query(action.query)}"
    return f"{action.type}:{json.dumps(_action_args_only(action), sort_keys=True, ensure_ascii=False)}"


def _page_fingerprint(url: str, marks: list[Mark], active_idx: int = 0) -> str:
    """归一化页面状态用于「无变化检测」(W5-A 反思). 与 _action_signature 风格一致, 纯函数。

    取前 8 mark + text[:40] 抗尾部动态计数/timestamp mark 抖动; 留 url 区分 SPA 路由切换。
    V0.21.1: 加 active_idx — 多 tab 场景下 switch_tab→back 看似 url+marks 不变但语义变了,
    把 active_idx 进 fingerprint 防 W5-A reflect hint 误触发 + LOOP_DETECTED 误判.
    单 tab 场景 active_idx 恒 0, 行为不变 (向后兼容默认 0).
    V0.22.0: sig_marks 加 frame_path[:10] 防 iframe navigate 后看似 marks 不变但 iframe
    内容已变触发误判 (e.g. 父页面不变但 iframe src 切了).
    """
    sig_marks = [(m.id, m.tag, m.text[:40], m.frame_path[:10]) for m in marks[:8]]
    return json.dumps(
        {"url": url, "n": len(marks), "marks": sig_marks, "tab": active_idx},
        sort_keys=True, ensure_ascii=False,
    )


_REFLECT_HINT = (
    "[reflect] 页面 3 步无变化 (url+marks 同). 建议: "
    "① scroll 看视口外内容 ② 后退/换 selector "
    "③ 检查 SoM 是否漏标目标元素 ④ 当前 strategy 大概率撞墙, 换思路."
)


def _maybe_inject_reflect_hint(trace: Trace, recent_pages: deque[str], fp: str) -> None:
    """W5-A: 页面 3 步无变化 → 把 hint 追加到上一步 observation, mutate in-memory Trace。

    LLM 下一次 plan() 通过 Trace.for_llm() 自然看到 (软提示而非硬 abort, 与 V0.5.0
    anti-loop 同 action 3 次硬 abort 互补)。in-place mutate, 调用方负责先 push fp。
    幂等: "[reflect]" 已在 obs 则跳过, 防同一 step 被双重 append。
    """
    if not (
        len(recent_pages) == 3
        and all(p == fp for p in recent_pages)
        and trace.steps
        and "[reflect]" not in trace.steps[-1].observation
    ):
        return
    trace.steps[-1].observation = (
        trace.steps[-1].observation + "\n" + _REFLECT_HINT
    ).strip()


# V0.16.20 W5-C.2 logging spike: 量化 LLM 是否在 thought 拆 subgoal (ARCHITECTURE §1.5 触发条件 ③).
# 仅在 env WEB_AGENT_SPIKE_W5C2=1 时激活, noop overhead 极小.
_SPIKE_M1_RE = re.compile(
    r"子目标|步骤\s*\d|"
    r"第\s*[一二三四五六七八九十0-9]+\s*步|"  # V0.16.21: 中文/阿拉伯序数 (第一步/第2步)
    r"子任务\s*[一二三四五六七八九十0-9]+|"  # V0.16.22: LLM 复述 prompt "子任务 N" 字样 (label 18/20)
    r"\bsubgoal\b|"  # V0.16.22: 英文裸词 (Subgoal:) — label 15 模板回应
    r"(?:^|[^\w])(?:1\.|2\.|3\.|①|②|③|④|⑤)|"
    r"\b(?:first|then|next|finally|step\s*\d)\b",
    re.IGNORECASE,
)
_SPIKE_M2_RE = re.compile(
    r"(?:目前|当前|现在)(?:在|进行到|进入到?)\s*"  # V0.16.21: 进行到/进入也算 plan reference
    r"(?:第\s*[一二三四五六七八九十0-9]+|"  # V0.16.21: 中文序数
    r"子任务\s*[一二三四五六七八九十0-9]+|"  # V0.16.22: 当前在子任务 N
    r"subgoal|步骤)|"
    r"子任务\s*[一二三四五六七八九十0-9]+\s*[:：]|"  # V0.16.22b: 裸 "子任务 N:" 持续标号 (subagent 实证 label 20 用 8 次)
    r"\bSubgoal\s*[:：]|"  # V0.16.22b: 英文 "Subgoal:" 模板回应 (label 15)
    r"按计划|根据(?:上面|前面)拆|"
    r"已完成子任务\s*[一二三四五六七八九十0-9]+|"  # V0.16.22: 已完成子任务 1, 进行子任务 2
    r"\bcurrently\s+(?:on|at|working\s+on)\s+(?:subgoal|step|subtask)|"  # V0.16.22: working on
    r"\baccording\s+to\s+(?:the\s+)?plan|\bas\s+planned",
    re.IGNORECASE,
)
_SPIKE_M5_RE = re.compile(
    r"(?:换|改|重新|另一).{0,4}?(?:策略|方法|思路|方案|路径|途径|搜索|尝试)|"
    r"\b(?:try\s+(?:a\s+)?(?:another|different)|switch\s+(?:strategy|approach)|"
    r"alternative\s+approach|reconsider)\b",
    re.IGNORECASE,
)
_SPIKE_FAILURE_OBS_MARKERS = (
    "ERROR", "SAFETY_BLOCK", "LOOP_DETECTED", "CAPTCHA", "WALLCLOCK", "LLM_FAILED",
)


def _dump_spike_metrics(task_id: str, goal: str, trace: Trace) -> None:
    """task 结束 task 后一次性 dump 每个 step 的 5 指标到 jsonl (W5-C.2 spike).

    env WEB_AGENT_SPIKE_W5C2 != "1" → noop. 输出 ~/.cache/web-agent/spike-w5c2/{task_label}-{task_id}.jsonl.
    M1/M2/M5 单步级 regex; M3/M4 留 summary 阶段聚合 (scripts/run_w5c2_spike.py).
    silent swallow 失败: spike 不该阻塞主路径 (与 memory.record_task 同档).
    """
    if os.environ.get("WEB_AGENT_SPIKE_W5C2", "") != "1":
        return
    try:
        out_dir = Path.home() / ".cache" / "web-agent" / "spike-w5c2"
        out_dir.mkdir(parents=True, exist_ok=True)
        label = os.environ.get("WEB_AGENT_SPIKE_TASK_LABEL", "") or "unknown"
        path = out_dir / f"{label}-{task_id}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for step in trace.steps:
                if step.step < 0:  # W5-D.2 synthetic memory_recall step
                    continue
                thought = step.thought or ""
                obs = step.observation or ""
                is_failure_step = any(m in obs for m in _SPIKE_FAILURE_OBS_MARKERS)
                record = {
                    "task_id": task_id,
                    "task_label": label,
                    "step": step.step,
                    "ts": step.ts,
                    "goal": goal[:300],
                    "thought": thought[:600],
                    "action_type": step.action_type,
                    "obs_head": obs[:200],
                    "M1": bool(_SPIKE_M1_RE.search(thought)),
                    "M2": bool(_SPIKE_M2_RE.search(thought)),
                    "M5": bool(_SPIKE_M5_RE.search(thought)) if is_failure_step else False,
                    "is_failure_step": is_failure_step,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _captcha_enabled() -> bool:
    return os.environ.get("WEB_AGENT_CAPTCHA_DISABLE", "").lower() not in ("true", "1", "yes")


# V0.25.0: transient/fatal 分类器. SDK 内置 max_retries=4 耗尽后我们再加一层 step 级 retry.
# isinstance + status_code 双重兜底 — 跨第三方代理 (OpenRouter/LiteLLM) 包装层用 HTTP 语义.
_TRANSIENT_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}


def _classify_failure(e: Exception) -> str:
    """V0.25.0: 给 LLM_FAILED 异常分类 transient / fatal.

    transient: 网络/timeout/RateLimit/InternalServer — 同 step 重试有意义
    fatal: Auth/BadRequest/Permission/RuntimeError(Kimi 配置问题) — 重试无意义立即 abort

    isinstance 优先 (anthropic + openai 两 SDK 类层级一致), status_code 兜底 (跨第三方代理).
    """
    # SDK 类型 isinstance 检查 (避免硬 import openai 因为是 optional dep)
    name = type(e).__name__
    if name in {
        "APIConnectionError", "APITimeoutError", "ConnectionError",
        "RateLimitError", "InternalServerError",
        "ServiceUnavailableError", "APIError",
    }:
        return "transient"
    # HTTP status 兜底 (第三方代理透传)
    status = getattr(e, "status_code", None)
    if status in _TRANSIENT_HTTP_STATUSES:
        return "transient"
    # 默认 fatal (含 RuntimeError / AuthenticationError / BadRequestError / PermissionDeniedError)
    return "fatal"


def _transient_retry_max() -> int:
    """V0.25.0: env WEB_AGENT_TRANSIENT_RETRY_MAX 默认 3, 0 禁用 (回退 V0.24.2 行为)."""
    try:
        return max(0, int(os.environ.get("WEB_AGENT_TRANSIENT_RETRY_MAX", "3")))
    except ValueError:
        return 3


def _frame_for_followup(page: Page, last_clicked_mark: Mark | None) -> Frame | None:
    """V0.22.3: type/paste/keyboard_shortcut 复用 last_clicked_mark.frame_path 路由 iframe.

    抽出 3 处重复三元 `_resolve_frame(page, last_clicked_mark.frame_path) if last_clicked_mark else None`.
    收益: ① 读者扫 match arm 看名字直接懂"复用 click 状态" ② V0.23 加新 follow-up action
    时只 1 处调用 ③ 防 V0.23 加 namespace 时漏改某 arm 的 last_clicked_mark 引用.
    """
    if last_clicked_mark is None:
        return None
    return _resolve_frame(page, last_clicked_mark.frame_path)


# V0.24.1 抽 helper 时设计: V0.25+ 加新 deque 类型只动此元组. V0.25.1 兑现承诺加第 3 项.
_PRE_STEP_DRAIN_ATTRS = (
    "_web_agent_recent_downloads",   # V0.23.2: download listener save 完元信息
    "_web_agent_recent_dialogs",      # V0.24.0: dialog auto-handle 元信息
    "_web_agent_recent_failure_hints",  # V0.25.1: backtracking / 失败模式 hint (V0.25.2 写入)
)


def _drain_pre_step_observations(ctx: BrowserContext, trace: Trace) -> None:
    """V0.24.1: 统一 browser listener 跨 step 元信息追加到上一步 trace.steps[-1].observation.

    遍历 _PRE_STEP_DRAIN_ATTRS (download / dialog / V0.25+ 加新类型只动常量), 对每个
    ctx attr deque 执行: 同形 (str 列表 + maxlen=10) → join → mutate trace.steps[-1] +
    clear (注入幂等). 抽出兑现 V0.23.2 simplify subagent TODO 第 (2) 条 "loop pre-step
    mutation 第 3 处出现时抽 helper".

    W5-A reflect hint **不进 helper** — 它依赖 (recent_pages, fp) 跟 ctx attr 不同源,
    强行抽会引入耦合. 进 helper 的是 ctx 上 deque attr 同形结构.
    """
    if not trace.steps:
        return
    for attr_name in _PRE_STEP_DRAIN_ATTRS:
        deque_obj = getattr(ctx, attr_name, None)
        if not deque_obj:
            continue
        obs_text = "\n".join(deque_obj)
        trace.steps[-1].observation = (
            trace.steps[-1].observation + "\n" + obs_text
        ).strip()
        deque_obj.clear()


def _resolve_frame(page: Page, frame_path: str) -> Frame | None:
    """V0.22.2: 解析 mark.frame_path → Playwright Frame (主 frame 返 None 走 page 路径).

    "0" → page.main_frame.child_frames[0]
    "0.1" → main.child_frames[0].child_frames[1]
    失败 (IndexError 越界 / ValueError 非数字 / detached) → 返 None, 调用方观察 None
    走主 frame 路径 (退化为 click 主 page 失败 → ERROR obs 安全兜底).

    分歧: 解析失败用 None 兜底 vs 抛 / 返 sentinel — 选 None 兜底因 actuator 已经天然
    支持 frame=None 主路径, 错误传染最小; loop dispatch 在 _resolve_frame 返 None 但
    mark.frame_path != "" 时 log warning 让用户看 trace 时知道路由失败 (但 obs 仍尝试主路径).
    """
    if not frame_path:
        return None
    try:
        f: Frame = page.main_frame
        for idx_str in frame_path.split("."):
            f = f.child_frames[int(idx_str)]
        if f.is_detached():
            logger.warning("frame_path=%r resolve 后已 detached", frame_path)
            return None
        return f
    except (IndexError, ValueError, RuntimeError) as e:
        logger.warning("frame_path=%r resolve 失败 (%r), 回退主 frame", frame_path, e)
        return None


async def _gather_tab_titles(pages: list[Page]) -> list[tuple[int, str]]:
    """V0.21.2: 取每个 page.title() 失败 fallback URL path. 串行 — N≤5 ms 级开销可忽略.

    title() 返空字符串 (about:blank / 加载中) → 也走 URL fallback 让 LLM 至少看 host/path.
    任何 exception (page closed / 网络断) → fallback URL 字符串. 不 raise 防 loop 中断.
    """
    out: list[tuple[int, str]] = []
    for i, p in enumerate(pages):
        title = ""
        try:
            title = (await p.title()) or ""
        except Exception:
            pass
        if not title:
            url = getattr(p, "url", "") or ""
            title = url.split("?")[0][-60:] if url else "(untitled)"
        out.append((i, title))
    return out


async def _handle_captcha(
    page: Page,
    step_i: int,
    trace: Trace,
    conn: sqlite3.Connection,
    task_id: str,
    max_steps: int = 0,
    progress_cb: ProgressCallback | None = None,
) -> str | None:
    """检测 captcha; 命中 → wait → 解决返回 None (loop 继续) / 超时返回 result 字符串 (loop abort)。

    在 perceive() 之前调: 避 SoM 注入污染 captcha 页 + 省 perceive 开销。
    超时路径写 trace captcha_timeout step + end_task, 镜像 V0.6.0 safety_block。
    progress_cb 每 poll_s (默认 3s) 触发心跳, 防 Claude Desktop 60s no-traffic timeout.
    """
    if not _captcha_enabled():
        return None
    info = await captcha_detect(page)
    if info is None:
        return None
    timeout_s = float(os.environ.get("WEB_AGENT_CAPTCHA_TIMEOUT_S", "300"))
    poll_s = float(os.environ.get("WEB_AGENT_CAPTCHA_POLL_S", "3"))
    logger.info(
        "%s 命中 @ %s — 请在浏览器手动解决, agent 每 %ss 重检 (超时 %ss)",
        info.vendor, info.url[:80], poll_s, timeout_s,
    )
    notify("web-agent captcha", f"{info.vendor} 命中, 请在浏览器手解 ({info.url[:60]})")

    # 内联 poll: 不复用 captcha.wait_for_resolution, 因为这里需要 progress_cb 心跳
    # (captcha module 保持单职, 心跳是 loop 关心的事 — 它持有 progress_cb).
    t_start = time.monotonic()
    while time.monotonic() - t_start < timeout_s:
        if progress_cb is not None:
            elapsed = time.monotonic() - t_start
            await progress_cb(
                step_i,
                max_steps,
                f"awaiting {info.vendor} ({elapsed:.0f}/{timeout_s:.0f}s)",
            )
        if await captcha_detect(page) is None:
            logger.info("%s 已清除, loop 继续", info.vendor)
            return None
        await asyncio.sleep(poll_s)

    result = (
        f"CAPTCHA_TIMEOUT at step {step_i}: {info.vendor} 未在 "
        f"{timeout_s}s 内解决 (url={info.url})"
    )
    logger.warning("captcha %s", result)
    notify("web-agent captcha 超时", f"{info.vendor} {timeout_s}s 未解, loop 已中止")
    step = Step(
        step=step_i, ts=time.time(), thought="(captcha 超时)",
        action_type="captcha_timeout",
        action_args={"vendor": info.vendor, "url": info.url, "timeout_s": timeout_s},
        observation=result,
    )
    trace.append(step)
    write_step(conn, task_id, step, "")
    end_task(conn, task_id, result)
    return result


async def _maybe_reflect_on_failure(
    client: LLMClient,
    goal: str,
    trace: Trace,
    final_result: str,
    task_id: str,
    domain: str,
    memory_db_path: Path,
) -> None:
    """V0.28.1: W6-A 失败反思 helper — final_result 触发 should_reflect 时调 client.reflect +
    record_reflection 持久化. LLM raise / parse fail 都 graceful (logger.warning), 不阻塞 task return.

    跟 W5-A `_maybe_inject_reflect_hint` (intra-step deterministic) 边界分明: 本 helper 是
    inter-task LLM-driven, 仅 task 终结时调一次, 写 reflections 表 (V0.28.2 cli inject 给下次启动看).
    """
    from web_agent.reflect import build_reflect_prompt, parse_reflection, should_reflect

    if not should_reflect(final_result):
        return
    try:
        prompt = build_reflect_prompt(goal, trace.for_llm(), final_result)
        response = await client.reflect(prompt)
        reflection = parse_reflection(response)
        record_reflection(
            db_path=memory_db_path,
            task_id=task_id,
            domain=domain,
            goal=goal,
            final_result=final_result,
            root_cause=reflection.root_cause,
            hint=reflection.hint,
        )
        logger.info("W6-A reflect 已写入: task_id=%s domain=%r hint=%r",
                    task_id, domain, reflection.hint[:80])
    except Exception as e:
        logger.warning("W6-A reflect failed (non-fatal): %r", e)


async def run_react_loop(
    ctx: BrowserContext,
    client: LLMClient,
    goal: str,
    max_steps: int = 20,
    max_wallclock_s: float = 300.0,
    db_path: Path = Path("data/trace.db"),
    screenshots_dir: Path = Path("data/screenshots"),
    memories: str | None = None,
    progress_cb: ProgressCallback | None = None,
    safety_approval_cb: SafetyApprovalCallback | None = None,
    initial_active_idx: int = 0,
    domain: str = "",
    memory_db_path: Path | None = None,
) -> str:
    """跑 ReAct 循环直到 done / max_steps / max_wallclock_s / 死循环 / LLM 失败。返回最终结果文本。

    V0.21.1: 签名 page → ctx, 内部维护 active_idx 索引到 ctx.pages[active_idx]; 每 step 顶部
    snapshot list(ctx.pages) 防 popup 中 step 偏移. SwitchTabAction/CloseTabAction 派发改 active_idx
    + bring_to_front + 重置 last_clicked_mark.

    `initial_active_idx`: jd_extract / list_extract 半自动模式找到特定 URL match tab 后传入其
    在 ctx.pages 中的索引 (Playwright bring_to_front 不改 pages 顺序). 默认 0 对应 cli.py
    走 ctx.pages[0] 的 V0.20 等价行为.

    异常处理：
    - LLM API 失败（SDK 内置 max_retries=4 后仍挂）→ catch + 写 trace + graceful return
    - wallclock 超时 → 同上，避免卡 perceive/network 比 max_steps 更早 abort
    - 死循环（连续 3 次同 action）→ 同上
    """
    task_id = uuid.uuid4().hex[:12]
    # V0.28.1 W6-A: reflect 写入 memory.db (跟 W5-D record_task 同 db, schema 不同表).
    # caller (cli/eval/mcp) 不传 memory_db_path 时 fallback 默 data/memory.db.
    _resolved_mem_db: Path = memory_db_path or Path("data/memory.db")
    conn = init_db(db_path)
    start_task(conn, task_id, goal)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # V0.23.2: download_dir task-scoped + ctx attr 注入 (browser.py download listener 闭包读).
    # mcp_server._RUN_LOCK 串行化 web_agent_run, ctx 同时只 1 task 持有 → attr 注入安全
    # (sanity 推翻 Plan B5 多 task 并发顾虑). mkdir 在 perceive 第一步前完成防 listener save_as
    # 写到不存在目录抛异常被 silent swallow.
    download_dir = Path("data/downloads") / task_id
    download_dir.mkdir(parents=True, exist_ok=True)
    ctx._web_agent_download_dir = download_dir  # type: ignore[attr-defined]
    if not getattr(ctx, "_web_agent_recent_downloads", None):
        ctx._web_agent_recent_downloads = deque(maxlen=10)  # type: ignore[attr-defined]
    # V0.24.0: dialog deque 同 download deque 同模式 (browser.py _make_dialog_handler 闭包读)
    if not getattr(ctx, "_web_agent_recent_dialogs", None):
        ctx._web_agent_recent_dialogs = deque(maxlen=10)  # type: ignore[attr-defined]
    # V0.25.1: failure_hints deque — V0.25.2 backtracking 写入 "已回退到 X" 让 LLM 看到换思路
    if not getattr(ctx, "_web_agent_recent_failure_hints", None):
        ctx._web_agent_recent_failure_hints = deque(maxlen=10)  # type: ignore[attr-defined]

    trace = Trace(task_id=task_id, goal=goal)
    recent_actions: deque[str] = deque(maxlen=3)
    # V0.46.1 真发现 #25 follow-up reframe: 加 5-window 加 alternation detector. V0.46.0 plan
    # 推仅 normalize query (B), V0.46.1 真测 V0.44 HN 11 query 发现是 alternation pattern
    # (step 5/7/10 同 sig + step 6/8/9 同 sig 交替), normalize 后 deque [A,B,A] 仍不全同 →
    # V0.5.0 3 连续相同 detector miss. 复合 detector: V0.5.0 3 连续 + V0.46.1 5-window count≥3.
    recent_action_window: deque[str] = deque(maxlen=5)
    recent_pages: deque[str] = deque(maxlen=3)  # W5-A 反思: 页面 fingerprint 跟踪
    last_clicked_mark: Mark | None = None  # type action 的 safety check 需要上次 click 的元素
    active_idx: int = initial_active_idx  # V0.21.1: 当前 active tab 索引
    result = "(no result)"
    t_start = time.time()
    # V0.42.2 D: token budget guard (跟 V0.24.2 max_wallclock_s 同守护模式).
    # env WEB_AGENT_TOKEN_BUDGET_USD 累计 cost > 阈值 → TOKEN_BUDGET_EXCEEDED graceful abort.
    # 默 0 disable (跟 V0.30.1 D opt-in pattern 同, 主流 cli 不强制 budget).
    # 简化 pricing: Anthropic Sonnet 4 上界估 (~$0.003/1K input + $0.015/1K output, 不算 cache 折扣).
    _budget_env = os.environ.get("WEB_AGENT_TOKEN_BUDGET_USD", "0").strip()
    try:
        token_budget_usd = float(_budget_env) if _budget_env else 0.0
    except ValueError:
        token_budget_usd = 0.0
    cumulative_cost_usd = 0.0

    # W5-D.2 长期记忆 inject: 主循环前 prepend 一个 synthetic step,
    # LLM 通过 Trace.for_llm() 看到跨 session 历史. 不写 sqlite (与 W5-A reflect hint 同档:
    # in-memory soft hint, 不污染 trace.db 的"实际执行"事件流).
    if memories:
        trace.append(Step(
            step=-1, ts=time.time(),
            thought="(W5-D.2 长期记忆召回)",
            action_type="memory_recall",
            action_args={},
            observation=memories[:2000],
        ))

    try:
        for step_i in range(max_steps):
            elicited_approval_rule: str | None = None  # V0.18.0: 每步重置, safety elicit accept 时设
            elapsed = time.time() - t_start
            if progress_cb is not None:
                await progress_cb(step_i, max_steps, f"step {step_i + 1}/{max_steps}")
            if elapsed > max_wallclock_s:
                result = (
                    f"WALLCLOCK_EXCEEDED at step {step_i}: 已 {elapsed:.1f}s 超过 max_wallclock_s={max_wallclock_s}s。"
                    f"常见原因：perceive/网络卡顿、LLM 响应慢、SDK retry 累积。"
                )
                logger.warning("wallclock %s", result)
                end_task(conn, task_id, result)
                # V0.44.2 W6-A: WALLCLOCK 路径触发 reflect (#25 真发现: 实际 plan 缺陷类
                # LLM extract loop, V0.28 subagent A "外因不 reflect" 假设双端推翻).
                await _maybe_reflect_on_failure(
                    client, goal, trace, result, task_id, domain, _resolved_mem_db,
                )
                return result
            # V0.42.2 D: token budget guard 在 step 顶 check, 累计 cost > 阈值 graceful abort.
            # budget=0 disable 不 check (默, 跟 V0.30.1 D opt-in 同).
            if token_budget_usd > 0 and cumulative_cost_usd > token_budget_usd:
                result = (
                    f"TOKEN_BUDGET_EXCEEDED at step {step_i}: 累计 ${cumulative_cost_usd:.4f} 超过 "
                    f"WEB_AGENT_TOKEN_BUDGET_USD=${token_budget_usd:.4f}. "
                    f"常见原因: runaway loop / 长 task / pageload 反复 retry. "
                    f"调高 budget 或拆 task 重跑."
                )
                logger.warning("token-budget %s", result)
                end_task(conn, task_id, result)
                return result

            await think()

            # V0.21.1: 每 step 顶部 snapshot ctx.pages 防 step 内 popup 偏移索引;
            # active_idx 越界 (上一步 close_tab 后或 popup 关闭) clamp 到合法范围.
            step_pages: list[Page] = list(ctx.pages)
            if not step_pages:
                result = f"NO_PAGES at step {step_i}: ctx.pages 空, browser context 已无 page"
                logger.warning("no-pages %s", result)
                end_task(conn, task_id, result)
                return result
            if active_idx >= len(step_pages):
                active_idx = len(step_pages) - 1
            page = step_pages[active_idx]

            # V0.24.1: download/dialog 跨 step 元信息追加到上一步 obs (helper 统一 drain).
            _drain_pre_step_observations(ctx, trace)

            captcha_abort = await _handle_captcha(
                page, step_i, trace, conn, task_id,
                max_steps=max_steps, progress_cb=progress_cb,
            )
            if captcha_abort is not None:
                return captcha_abort

            marks, screenshot_b64, cross_origin_hosts = await perceive(page)

            # W5-A 自反思: 页面 3 步无变化 → 软提示 (与 V0.5.0 anti-loop 硬 abort 互补)
            # V0.21.1: fingerprint 加 active_idx 防 switch-back 看似无变化触发误报
            fp = _page_fingerprint(getattr(page, "url", "") or "", marks, active_idx)
            recent_pages.append(fp)
            _maybe_inject_reflect_hint(trace, recent_pages, fp)

            # V0.33.3: 落盘后缀跟 perceiver 截图格式一致 (.webp 模式 ~70% 磁盘省).
            # V0.36.1: per-task subdir 让 cleanup 粒度对齐 task (data/screenshots/<task_id>/<NN>.{ext}
            # 取代 V0.36 之前 flat data/screenshots/<task_id>-<NN>.{ext}). 老 task replay.py BC fallback.
            from web_agent.perceiver import current_screenshot_format
            task_shots_dir = screenshots_dir / task_id
            task_shots_dir.mkdir(parents=True, exist_ok=True)
            shot_path = task_shots_dir / f"{step_i:02d}.{current_screenshot_format()}"
            shot_path.write_bytes(base64.b64decode(screenshot_b64))

            logger.info("step %d perceive: %d marks, screenshot %s | t+%.1fs", step_i, len(marks), shot_path, elapsed)

            # V0.21.2: 算 tabs 列表传给 LLM 让它看到 multi-tab 状态. 单 tab 也传 (LLM 知道
            # tab 概念存在). 失败 fallback URL — 不 raise 防 loop 中断.
            tabs = await _gather_tab_titles(step_pages)
            # V0.25.0: transient retry — SDK max_retries 之上再加 step 级重试. fatal 维持 V0.24.2
            # abort. WEB_AGENT_TRANSIENT_RETRY_MAX=0 禁用 retry 回退 V0.24.2 行为.
            retry_max = _transient_retry_max()
            transient_retries = 0
            action: Action | None = None
            last_error: Exception | None = None
            # V0.33.1 + V0.42.0: 捕 plan() 后 last_usage 给 Step 用 (per-step 真累加 + cache 字段)
            step_input_tokens = 0
            step_output_tokens = 0
            step_cache_creation_tokens = 0
            step_cache_read_tokens = 0
            for attempt in range(retry_max + 1):  # 第 0 次是首发, 1..retry_max 是 retry
                try:
                    action = await client.plan(
                        goal, screenshot_b64, marks, trace,
                        tabs=tabs, current_idx=active_idx,
                        cross_origin_hosts=cross_origin_hosts,
                    )
                    # V0.33.1: capture 本次 plan call 的 token usage (含 retry — 第 N 次成功的为准).
                    # last_usage None 时 (mock client / 老 client 不支持) 保持 0.
                    _usage = getattr(client, "last_usage", None)
                    if _usage is not None:
                        step_input_tokens = getattr(_usage, "input_tokens", 0)
                        step_output_tokens = getattr(_usage, "output_tokens", 0)
                        # V0.42.0 D: cache 字段 (default 0 兼容老 FakeLLMClientWithUsage)
                        step_cache_creation_tokens = getattr(_usage, "cache_creation_input_tokens", 0)
                        step_cache_read_tokens = getattr(_usage, "cache_read_input_tokens", 0)
                        # V0.42.2 D: 累加 step cost (Anthropic Sonnet 4 上界估算, 不算 cache 折扣 — 保守安全).
                        # $0.003/1K input + $0.015/1K output. budget 触发优先于真实 cost 计算精度.
                        cumulative_cost_usd += (
                            step_input_tokens * 0.003 / 1000.0
                            + step_output_tokens * 0.015 / 1000.0
                        )
                    break  # 成功跳出 retry loop
                except Exception as e:
                    last_error = e
                    classification = _classify_failure(e)
                    if classification == "transient" and attempt < retry_max:
                        transient_retries = attempt + 1
                        logger.info(
                            "step %d transient %s (attempt %d/%d): %s — retry",
                            step_i, type(e).__name__, transient_retries, retry_max, e,
                        )
                        continue  # transient + 还有 budget → 同 step 重 perceive+plan
                    # fatal 或 budget 耗尽 → abort
                    result = (
                        f"LLM_FAILED at step {step_i}: {type(e).__name__}: {e}"
                    )
                    logger.warning(
                        "llm-failed %s (classification=%s transient_retries=%d)",
                        result, classification, transient_retries,
                    )
                    step = Step(
                        step=step_i, ts=time.time(), thought="(LLM 调用失败)",
                        action_type="error",
                        action_args={
                            "error": str(e)[:200],
                            "classification": classification,
                            "transient_retries": transient_retries,
                        },
                        observation=result,
                    )
                    trace.append(step)
                    write_step(conn, task_id, step, str(shot_path))
                    end_task(conn, task_id, result)
                    return result
            # mypy: 若 break 出循环 action 必非 None; 若全 transient 走完 retry 走 abort 已 return.
            # 此 assert 防御未来重构破坏不变量.
            assert action is not None, f"V0.25.0 retry loop bug: action=None last_error={last_error!r}"
            logger.info("step %d action (%s): %s %s | thought: %s", step_i, client.name, action.type, _action_args_only(action), action.thought[:120])

            # safety check：在 actuator 之前 intercept 敏感 action（send/pay/delete/密码字段...）
            # V0.17.0: isinstance 替 action.type 字符串比, mypy 自动 narrow ClickAction.mark_id
            # V0.23.2: UploadAction 也走 safety check (paths 黑名单), elicit 流程一致
            if isinstance(action, (ClickAction, TypeAction, PasteAction, UploadAction)):
                check_mark: Mark | None = None
                if isinstance(action, ClickAction):
                    check_mark = _find_mark(marks, action.mark_id)
                elif isinstance(action, UploadAction):
                    # V0.23.2: UploadAction safety 看 paths 不看 mark; mark 仅传给 obs 用,
                    # safety.check 内 isinstance(UploadAction) 分支不读 mark 直接走 paths 黑名单.
                    check_mark = _find_mark(marks, action.mark_id)
                else:  # TypeAction or PasteAction (V0.19.0: paste 同 type 用 last_clicked_mark)
                    check_mark = last_clicked_mark
                decision = safety_check(action, check_mark, marks)
                if not decision.allow:
                    # V0.18.0: 若注入 elicitation callback (e.g. MCP server 模式), 询问用户是否放行.
                    # accept → 在主 dispatch step 的 action_args 加 elicited_approval_rule 标记 + 继续;
                    # decline/cancel/异常 → 维持原 SAFETY_BLOCK abort 路径 (安全 default).
                    elicited = False
                    if safety_approval_cb is not None:
                        try:
                            elicited = await safety_approval_cb(decision.rule, decision.reason)
                        except Exception as e:
                            logger.warning("safety_approval_cb failed (%r) → 视作 decline", e)
                    if elicited:
                        elicited_approval_rule = decision.rule
                        logger.info("safety ALLOWED rule=%r elicited approve → 继续", decision.rule)
                    else:
                        result = f"SAFETY_BLOCK at step {step_i}: {decision.reason}"
                        logger.info("safety %s", result)
                        step = Step(
                            step=step_i, ts=time.time(), thought=action.thought,
                            action_type="safety_block",
                            action_args={"original_type": action.type, "rule": decision.rule, **_action_args_only(action)},
                            observation=result,
                        )
                        trace.append(step)
                        write_step(conn, task_id, step, str(shot_path))
                        end_task(conn, task_id, result)
                        return result

            # 死循环检测：
            # - V0.5.0: 连续 3 次完全相同 action（type + args）→ V0.25.2 backtrack 或 abort
            # - V0.46.1 真发现 #25 follow-up: 5-window 内任意 sig 出现 ≥ 3 次 → alternation abort
            #   (V0.5.0 catch 不到 [A,B,A,B,B] 交替, V0.46.1 reframe 加 5-window count detector)
            sig = _action_signature(action)
            # V0.5.0 detector 优先 (早 step 触发)
            if len(recent_actions) == 3 and all(s == sig for s in recent_actions):
                # V0.25.2: 第 1 次 trigger → page.go_back + reset 状态 + 注入 hint + retry once
                # 第 2 次 trigger (backtrack 后又卡) → abort 维持 V0.5.0 兼容防 infinite loop
                already_backtracked = getattr(ctx, "_web_agent_anti_loop_backtracked", False)
                if not already_backtracked:
                    try:
                        await page.go_back()
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception as e:
                        logger.warning("V0.25.2 backtrack page.go_back 失败 (%r), 走原 abort 路径", e)
                    else:
                        # 成功 backtrack: reset 防 W5-A reflect 误判 + reset last_clicked +
                        # clear recent_actions 让重 loop 检测从头算 + 注 hint 让 LLM 看到
                        ctx._web_agent_anti_loop_backtracked = True  # type: ignore[attr-defined]
                        recent_actions.clear()
                        recent_action_window.clear()  # V0.46.1: 同 recent_actions reset 防 5-window detector 立即 re-trigger
                        recent_pages.clear()
                        last_clicked_mark = None
                        hint = (
                            f"[backtrack] 已回退到上一页 (上次连续 3 次同 action {sig[:80]} 卡住). "
                            f"换思路: 重新读截图找新 mark / scroll / 用 keyboard_shortcut. "
                            f"再触发同样卡死会硬 abort 不再回退."
                        )
                        recent_dl = getattr(ctx, "_web_agent_recent_failure_hints", None)
                        if recent_dl is None:
                            recent_dl = deque(maxlen=10)
                            ctx._web_agent_recent_failure_hints = recent_dl  # type: ignore[attr-defined]
                        recent_dl.append(hint)
                        # 写 backtrack step trace + 跳过本 action 派发, 进下一 step 重 perceive
                        bt_step = Step(
                            step=step_i, ts=time.time(), thought=action.thought,
                            action_type="backtrack",
                            action_args={"sig": sig[:200], "trigger": "anti_loop"},
                            observation=f"backtracked: {hint[:200]}",
                        )
                        trace.append(bt_step)
                        write_step(conn, task_id, bt_step, str(shot_path))
                        continue  # 跳到下一 step 重 perceive (新 fp 自然变, W5-A 不误 fire)
                # 已 backtrack 过 / go_back 失败 → 走原 abort 路径 (V0.5.0 兼容)
                result = (
                    f"LOOP_DETECTED 在 step {step_i}：连续 3+ 次同一 action {sig[:200]}。"
                    f"agent 卡死, 已强制中止。常见原因：SoM 没标到目标元素 / "
                    f"页面状态未按 LLM 预期变化 / system prompt 没说服 LLM 换策略。"
                    + (" (V0.25.2 backtrack 后第 2 次 trigger, 不再回退)" if already_backtracked else "")
                )
                logger.warning("anti-loop %s", result)
                step = Step(
                    step=step_i, ts=time.time(), thought=action.thought,
                    action_type=action.type, action_args=_action_args_only(action),
                    observation="LOOP_DETECTED — aborted",
                )
                trace.append(step)
                write_step(conn, task_id, step, str(shot_path))
                end_task(conn, task_id, result)
                # V0.28.1 W6-A: LOOP_DETECTED 路径触发 reflect (subagent A 决: plan 缺陷类失败)
                await _maybe_reflect_on_failure(
                    client, goal, trace, result, task_id, domain, _resolved_mem_db,
                )
                return result
            recent_actions.append(sig)

            # V0.46.1 真发现 #25 follow-up: 5-window alternation detector — V0.5.0 不 catch
            # 的交替 pattern [A,B,A,B,B] 等. V0.44 HN WALLCLOCK 真实 trace 是 step 5/7/10 同 sig
            # + step 6/8/9 同 sig 交替, V0.5.0 3-连续相同 miss. window 内任 sig 出现 ≥ 3 次 abort.
            candidate_window = (list(recent_action_window) + [sig])[-5:]
            if len(candidate_window) >= 5 and Counter(candidate_window).most_common(1)[0][1] >= 3:
                result = (
                    f"LOOP_DETECTED 在 step {step_i}: 5-step window 内有 sig 出现 ≥ 3 次"
                    f" (V0.46.1 alternation detector). 反复 action 交替 (V0.5.0 3-连续相同 miss). "
                    f"agent 已强制中止. window 内 sig (truncated 80 char each): "
                    f"{[s[:80] for s in candidate_window]}"
                )
                logger.warning("anti-loop alternation %s", result[:200])
                alt_step = Step(
                    step=step_i, ts=time.time(), thought=action.thought,
                    action_type=action.type, action_args=_action_args_only(action),
                    observation="LOOP_DETECTED — alternation aborted",
                )
                trace.append(alt_step)
                write_step(conn, task_id, alt_step, str(shot_path))
                end_task(conn, task_id, result)
                # V0.28.1 W6-A: LOOP_DETECTED 路径触发 reflect (跟 V0.5.0 同模式)
                await _maybe_reflect_on_failure(
                    client, goal, trace, result, task_id, domain, _resolved_mem_db,
                )
                return result
            recent_action_window.append(sig)

            # V0.17.0: match-case dispatch on dataclass discriminated union (mypy narrow 自动)
            obs = ""
            match action:
                case ClickAction(mark_id=mid):
                    m = _find_mark(marks, mid)
                    if m is None:
                        obs = f"ERROR: mark_id={mid} 不在当前 marks 里"
                    else:
                        # V0.22.2: 解析 frame_path; 主 frame mark.frame_path="" → frame=None
                        # 走旧贝塞尔, iframe → frame.locator
                        target_frame = _resolve_frame(page, m.frame_path)
                        await human_like_click(page, m, frame=target_frame)
                        last_clicked_mark = m  # 给下一步 type action 的 safety check 用 (含 frame_path)
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=5000)
                        except Exception:
                            pass
                        frame_suffix = f" @{m.frame_path}" if m.frame_path else ""
                        obs = f"clicked [{m.id}] {m.tag} {m.text!r}{frame_suffix}"
                case TypeAction(text=text, submit=submit):
                    # V0.22.3: _frame_for_followup helper 抽 3 处重复三元
                    type_frame = _frame_for_followup(page, last_clicked_mark)
                    await human_like_type(page, text, frame=type_frame, mark=last_clicked_mark)
                    if submit:
                        await page.keyboard.press("Enter")
                        try:
                            await page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                    obs = f"typed {text!r}" + (" + submit" if submit else "")
                case ScrollAction(dy=dy):
                    # V0.22.2: scroll 不实现 iframe 路径 (LLM 用例罕见 YAGNI)
                    await scroll(page, dy)
                    obs = f"scrolled dy={dy}"
                case ExtractAction(answer=answer):
                    obs = f"extracted: {answer[:200]}"
                case DoneAction(result=res):
                    result = res
                    obs = res
                case KeyboardShortcutAction(key=key):
                    ks_frame = _frame_for_followup(page, last_clicked_mark)
                    await human_like_keyboard_shortcut(page, key, frame=ks_frame, mark=last_clicked_mark)
                    obs = f"keyboard_shortcut {key!r}"
                case PasteAction(text=text):
                    paste_frame = _frame_for_followup(page, last_clicked_mark)
                    await human_like_paste(page, text, frame=paste_frame, mark=last_clicked_mark)
                    obs = f"pasted {text!r}"
                case SwitchTabAction(idx=tab_idx):
                    # V0.21.1: 用 step_pages snapshot 解析 (防 step 内 popup 偏移);
                    # 越界 → ERROR obs, active_idx 不变, 不重置 last_clicked_mark.
                    if tab_idx < 0 or tab_idx >= len(step_pages):
                        obs = (
                            f"ERROR: switch_tab idx={tab_idx} 越界 "
                            f"(当前 {len(step_pages)} tab, 合法 0..{len(step_pages) - 1})"
                        )
                    else:
                        active_idx = tab_idx
                        await step_pages[tab_idx].bring_to_front()
                        last_clicked_mark = None  # 切 tab 旧 mark 失效, 防 type safety 误判
                        obs = f"switched to tab [{tab_idx}] {step_pages[tab_idx].url[:80]}"
                case DragAction(from_mark_id=fid, to_mark_id=tid):
                    # V0.23.2: 找 from/to 2 mark; 校验同 frame_path; resolve frame; 派发 actuator.
                    from_m = _find_mark(marks, fid)
                    to_m = _find_mark(marks, tid)
                    if from_m is None or to_m is None:
                        missing = [str(i) for i, m in [(fid, from_m), (tid, to_m)] if m is None]
                        obs = f"ERROR: drag mark_id={','.join(missing)} 不在当前 marks 里"
                    elif from_m.frame_path != to_m.frame_path:
                        obs = (
                            f"ERROR: drag 跨 frame 不允许 — from @{from_m.frame_path!r} "
                            f"to @{to_m.frame_path!r}; 主流 builder/Trello 都在同 frame 内拖"
                        )
                    else:
                        drag_frame = _resolve_frame(page, from_m.frame_path)
                        await human_like_drag(page, from_m, to_m, frame=drag_frame)
                        last_clicked_mark = None  # drag 不该污染后续 type focus
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=5000)
                        except Exception:
                            pass
                        frame_suffix = f" @{from_m.frame_path}" if from_m.frame_path else ""
                        obs = (
                            f"dragged [{from_m.id}] {from_m.tag} {from_m.text!r} → "
                            f"[{to_m.id}] {to_m.tag} {to_m.text!r}{frame_suffix}"
                        )
                case UploadAction(mark_id=uid, paths=upload_paths):
                    # V0.23.2: 找 mark; resolve frame; safety 已在 dispatch 前 (上面 isinstance 分支)
                    # 检过 paths 黑名单 — 此处只校 mark 存在 + actuator 调用.
                    upload_m = _find_mark(marks, uid)
                    if upload_m is None:
                        obs = f"ERROR: upload mark_id={uid} 不在当前 marks 里"
                    else:
                        upload_frame = _resolve_frame(page, upload_m.frame_path)
                        try:
                            await upload_file(page, upload_m, upload_paths, frame=upload_frame)
                            last_clicked_mark = None  # upload 不污染后续 type focus
                            obs = (
                                f"uploaded {len(upload_paths)} file(s) to [{upload_m.id}] "
                                f"{upload_m.tag} {upload_m.text!r}"
                            )
                        except RuntimeError as e:
                            # actuator DOM walk 失败 (button 找不到关联 input) → 兜底 ERROR obs
                            obs = f"ERROR: upload {e}"
                case CloseTabAction(idx=tab_idx):
                    # V0.21.1: 2 道 guard — len==1 拒 + idx==active_idx 拒 (强迫先 switch 再 close).
                    if tab_idx < 0 or tab_idx >= len(step_pages):
                        obs = f"ERROR: close_tab idx={tab_idx} 越界 (当前 {len(step_pages)} tab)"
                    elif len(step_pages) == 1:
                        obs = "ERROR: close_tab 拒 — 不能关最后 1 个 tab"
                    elif tab_idx == active_idx:
                        obs = (
                            f"ERROR: close_tab 拒 — 不能关当前 active tab "
                            f"(idx={tab_idx}), 请先 switch_tab 切走再 close"
                        )
                    else:
                        await step_pages[tab_idx].close()
                        # idx < active_idx → active_idx 减 1; idx > active_idx → active_idx 不变
                        if tab_idx < active_idx:
                            active_idx -= 1
                        last_clicked_mark = None  # 即便没切 active, 关 tab 后保险重置
                        obs = f"closed tab [{tab_idx}], active_idx now={active_idx}"

            action_args = _action_args_only(action)
            if elicited_approval_rule is not None:
                action_args["elicited_approval_rule"] = elicited_approval_rule  # V0.18.0
            step = Step(
                step=step_i,
                ts=time.time(),
                thought=action.thought,
                action_type=action.type,
                action_args=action_args,
                observation=obs,
                # V0.33.1: per-step token 真累加 (修 V0.26.2 silent bug #14 — last_usage × N 高估).
                input_tokens=step_input_tokens,
                output_tokens=step_output_tokens,
                # V0.42.0 D: cache hit-rate audit per-step
                cache_creation_input_tokens=step_cache_creation_tokens,
                cache_read_input_tokens=step_cache_read_tokens,
            )
            trace.append(step)
            write_step(conn, task_id, step, str(shot_path))

            if isinstance(action, DoneAction):
                end_task(conn, task_id, result)
                logger.info("done %s", result[:200])
                return result

        result = "(max_steps 耗尽未完成)"
        end_task(conn, task_id, result)
        logger.warning("max_steps %s", result)
        # V0.28.1 W6-A: max_steps 路径触发 reflect (subagent A 决: plan 缺陷类失败)
        await _maybe_reflect_on_failure(
            client, goal, trace, result, task_id, domain, _resolved_mem_db,
        )
        return result
    finally:
        conn.close()
        _dump_spike_metrics(task_id, goal, trace)
