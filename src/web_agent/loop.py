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
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable

from playwright.async_api import BrowserContext, Frame, Page

from web_agent.actuator import (
    human_like_click,
    human_like_keyboard_shortcut,
    human_like_paste,
    human_like_type,
    scroll,
    think,
)
from web_agent.captcha import detect as captcha_detect
from web_agent.llm import LLMClient
from web_agent.notify import notify
from web_agent.perceiver import perceive
from web_agent.safety import check as safety_check
from web_agent.trace import Step, Trace, end_task, init_db, start_task, write_step
from web_agent.types import (
    Action,
    ClickAction,
    CloseTabAction,
    DoneAction,
    ExtractAction,
    KeyboardShortcutAction,
    Mark,
    PasteAction,
    ScrollAction,
    SwitchTabAction,
    TypeAction,
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


def _action_signature(action: Action) -> str:
    """归一化 action 用于死循环检测。V0.17.0: dataclass action 用 _action_args_only 取字段."""
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


def _frame_for_followup(page: Page, last_clicked_mark: Mark | None) -> Frame | None:
    """V0.22.3: type/paste/keyboard_shortcut 复用 last_clicked_mark.frame_path 路由 iframe.

    抽出 3 处重复三元 `_resolve_frame(page, last_clicked_mark.frame_path) if last_clicked_mark else None`.
    收益: ① 读者扫 match arm 看名字直接懂"复用 click 状态" ② V0.23 加新 follow-up action
    时只 1 处调用 ③ 防 V0.23 加 namespace 时漏改某 arm 的 last_clicked_mark 引用.
    """
    if last_clicked_mark is None:
        return None
    return _resolve_frame(page, last_clicked_mark.frame_path)


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
    conn = init_db(db_path)
    start_task(conn, task_id, goal)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    trace = Trace(task_id=task_id, goal=goal)
    recent_actions: deque[str] = deque(maxlen=3)
    recent_pages: deque[str] = deque(maxlen=3)  # W5-A 反思: 页面 fingerprint 跟踪
    last_clicked_mark: Mark | None = None  # type action 的 safety check 需要上次 click 的元素
    active_idx: int = initial_active_idx  # V0.21.1: 当前 active tab 索引
    result = "(no result)"
    t_start = time.time()

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

            shot_path = screenshots_dir / f"{task_id}-{step_i:02d}.png"
            shot_path.write_bytes(base64.b64decode(screenshot_b64))

            logger.info("step %d perceive: %d marks, screenshot %s | t+%.1fs", step_i, len(marks), shot_path, elapsed)

            # V0.21.2: 算 tabs 列表传给 LLM 让它看到 multi-tab 状态. 单 tab 也传 (LLM 知道
            # tab 概念存在). 失败 fallback URL — 不 raise 防 loop 中断.
            tabs = await _gather_tab_titles(step_pages)
            try:
                action: Action = await client.plan(
                    goal, screenshot_b64, marks, trace,
                    tabs=tabs, current_idx=active_idx,
                    cross_origin_hosts=cross_origin_hosts,
                )
            except Exception as e:
                # SDK 内置 retry 已耗尽 / network / tool_call=None / 其他 LLM 异常
                result = (
                    f"LLM_FAILED at step {step_i}: {type(e).__name__}: {e}"
                )
                logger.warning("llm-failed %s", result)
                step = Step(
                    step=step_i, ts=time.time(), thought="(LLM 调用失败)",
                    action_type="error", action_args={"error": str(e)[:200]},
                    observation=result,
                )
                trace.append(step)
                write_step(conn, task_id, step, str(shot_path))
                end_task(conn, task_id, result)
                return result
            logger.info("step %d action (%s): %s %s | thought: %s", step_i, client.name, action.type, _action_args_only(action), action.thought[:120])

            # safety check：在 actuator 之前 intercept 敏感 action（send/pay/delete/密码字段...）
            # V0.17.0: isinstance 替 action.type 字符串比, mypy 自动 narrow ClickAction.mark_id
            if isinstance(action, (ClickAction, TypeAction, PasteAction)):
                check_mark: Mark | None = None
                if isinstance(action, ClickAction):
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

            # 死循环检测：连续 3 次完全相同 action（type + args）→ abort
            sig = _action_signature(action)
            if len(recent_actions) == 3 and all(s == sig for s in recent_actions):
                result = (
                    f"LOOP_DETECTED 在 step {step_i}：连续 3+ 次同一 action {sig[:200]}。"
                    f"agent 卡死, 已强制中止。常见原因：SoM 没标到目标元素 / "
                    f"页面状态未按 LLM 预期变化 / system prompt 没说服 LLM 换策略。"
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
                return result
            recent_actions.append(sig)

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
        return result
    finally:
        conn.close()
        _dump_spike_metrics(task_id, goal, trace)
