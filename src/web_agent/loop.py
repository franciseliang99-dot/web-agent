"""ReAct loop: max_steps + Action Trace + 每步持久化截图/思考/行动。"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from collections import deque
from pathlib import Path

from playwright.async_api import Page

from web_agent.actuator import human_like_click, human_like_type, scroll, think
from web_agent.captcha import detect as captcha_detect
from web_agent.captcha import wait_for_resolution as captcha_wait
from web_agent.llm import Action, LLMClient
from web_agent.notify import notify
from web_agent.perceiver import Mark, perceive
from web_agent.safety import check as safety_check
from web_agent.trace import Step, Trace, end_task, init_db, start_task, write_step


def _find_mark(marks: list[Mark], mark_id: int) -> Mark | None:
    return next((m for m in marks if m.id == mark_id), None)


def _action_signature(action: Action) -> str:
    """归一化 action 用于死循环检测。"""
    return f"{action.type}:{json.dumps(action.args, sort_keys=True, ensure_ascii=False)}"


def _page_fingerprint(url: str, marks: list[Mark]) -> str:
    """归一化页面状态用于「无变化检测」(W5-A 反思). 与 _action_signature 风格一致, 纯函数。

    取前 8 mark + text[:40] 抗尾部动态计数/timestamp mark 抖动; 留 url 区分 SPA 路由切换。
    """
    sig_marks = [(m.id, m.tag, m.text[:40]) for m in marks[:8]]
    return json.dumps(
        {"url": url, "n": len(marks), "marks": sig_marks},
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


def _captcha_enabled() -> bool:
    return os.environ.get("WEB_AGENT_CAPTCHA_DISABLE", "").lower() not in ("true", "1", "yes")


async def _handle_captcha(page: Page, step_i: int, trace: Trace, conn, task_id: str) -> str | None:
    """检测 captcha; 命中 → wait → 解决返回 None (loop 继续) / 超时返回 result 字符串 (loop abort)。

    在 perceive() 之前调: 避 SoM 注入污染 captcha 页 + 省 perceive 开销。
    超时路径写 trace captcha_timeout step + end_task, 镜像 V0.6.0 safety_block。
    """
    if not _captcha_enabled():
        return None
    info = await captcha_detect(page)
    if info is None:
        return None
    timeout_s = float(os.environ.get("WEB_AGENT_CAPTCHA_TIMEOUT_S", "300"))
    poll_s = float(os.environ.get("WEB_AGENT_CAPTCHA_POLL_S", "3"))
    print(
        f"\n[captcha] {info.vendor} 命中 @ {info.url[:80]} — "
        f"请在浏览器手动解决, agent 每 {poll_s}s 重检 (超时 {timeout_s}s)",
        flush=True,
    )
    notify("web-agent captcha", f"{info.vendor} 命中, 请在浏览器手解 ({info.url[:60]})")
    if await captcha_wait(page, timeout_s=timeout_s, poll_s=poll_s):
        print(f"[captcha] {info.vendor} 已清除, loop 继续", flush=True)
        return None
    result = (
        f"CAPTCHA_TIMEOUT at step {step_i}: {info.vendor} 未在 "
        f"{timeout_s}s 内解决 (url={info.url})"
    )
    print(f"\n[captcha] {result}")
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
    page: Page,
    client: LLMClient,
    goal: str,
    max_steps: int = 20,
    max_wallclock_s: float = 300.0,
    db_path: Path = Path("data/trace.db"),
    screenshots_dir: Path = Path("data/screenshots"),
) -> str:
    """跑 ReAct 循环直到 done / max_steps / max_wallclock_s / 死循环 / LLM 失败。返回最终结果文本。

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
    result = "(no result)"
    t_start = time.time()

    try:
        for step_i in range(max_steps):
            elapsed = time.time() - t_start
            if elapsed > max_wallclock_s:
                result = (
                    f"WALLCLOCK_EXCEEDED at step {step_i}: 已 {elapsed:.1f}s 超过 max_wallclock_s={max_wallclock_s}s。"
                    f"常见原因：perceive/网络卡顿、LLM 响应慢、SDK retry 累积。"
                )
                print(f"\n[wallclock] {result}")
                end_task(conn, task_id, result)
                return result

            await think()

            captcha_abort = await _handle_captcha(page, step_i, trace, conn, task_id)
            if captcha_abort is not None:
                return captcha_abort

            marks, screenshot_b64 = await perceive(page)

            # W5-A 自反思: 页面 3 步无变化 → 软提示 (与 V0.5.0 anti-loop 硬 abort 互补)
            fp = _page_fingerprint(getattr(page, "url", "") or "", marks)
            recent_pages.append(fp)
            _maybe_inject_reflect_hint(trace, recent_pages, fp)

            shot_path = screenshots_dir / f"{task_id}-{step_i:02d}.png"
            shot_path.write_bytes(base64.b64decode(screenshot_b64))

            print(f"\n[step {step_i}] perceive: {len(marks)} marks, screenshot {shot_path} | t+{elapsed:.1f}s")

            try:
                action: Action = await client.plan(goal, screenshot_b64, marks, trace)
            except Exception as e:
                # SDK 内置 retry 已耗尽 / network / tool_call=None / 其他 LLM 异常
                result = (
                    f"LLM_FAILED at step {step_i}: {type(e).__name__}: {e}"
                )
                print(f"\n[llm-failed] {result}")
                step = Step(
                    step=step_i, ts=time.time(), thought="(LLM 调用失败)",
                    action_type="error", action_args={"error": str(e)[:200]},
                    observation=result,
                )
                trace.append(step)
                write_step(conn, task_id, step, str(shot_path))
                end_task(conn, task_id, result)
                return result
            print(f"[step {step_i}] action ({client.name}): {action.type} {action.args} | thought: {action.thought[:120]}")

            # safety check：在 actuator 之前 intercept 敏感 action（send/pay/delete/密码字段...）
            if action.type in ("click", "type"):
                check_mark: Mark | None = None
                if action.type == "click":
                    check_mark = _find_mark(marks, action.args.get("mark_id", -1))
                else:  # type
                    check_mark = last_clicked_mark
                decision = safety_check(action, check_mark, marks)
                if not decision.allow:
                    result = f"SAFETY_BLOCK at step {step_i}: {decision.reason}"
                    print(f"\n[safety] {result}")
                    step = Step(
                        step=step_i, ts=time.time(), thought=action.thought,
                        action_type="safety_block",
                        action_args={"original_type": action.type, "rule": decision.rule, **action.args},
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
                print(f"\n[anti-loop] {result}")
                step = Step(
                    step=step_i, ts=time.time(), thought=action.thought,
                    action_type=action.type, action_args=action.args,
                    observation="LOOP_DETECTED — aborted",
                )
                trace.append(step)
                write_step(conn, task_id, step, str(shot_path))
                end_task(conn, task_id, result)
                return result
            recent_actions.append(sig)

            obs = ""
            if action.type == "click":
                m = _find_mark(marks, action.args.get("mark_id", -1))
                if m is None:
                    obs = f"ERROR: mark_id={action.args.get('mark_id')} 不在当前 marks 里"
                else:
                    await human_like_click(page, m)
                    last_clicked_mark = m  # 给下一步 type action 的 safety check 用
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    obs = f"clicked [{m.id}] {m.tag} {m.text!r}"

            elif action.type == "type":
                text = action.args.get("text", "")
                submit = bool(action.args.get("submit", False))
                await human_like_type(page, text)
                if submit:
                    await page.keyboard.press("Enter")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                obs = f"typed {text!r}" + (" + submit" if submit else "")

            elif action.type == "scroll":
                dy = int(action.args.get("dy", 400))
                await scroll(page, dy)
                obs = f"scrolled dy={dy}"

            elif action.type == "extract":
                obs = f"extracted: {action.args.get('answer', '')[:200]}"

            elif action.type == "done":
                result = action.args.get("result", "")
                obs = result
            else:
                obs = f"unknown action type: {action.type}"

            step = Step(
                step=step_i,
                ts=time.time(),
                thought=action.thought,
                action_type=action.type,
                action_args=action.args,
                observation=obs,
            )
            trace.append(step)
            write_step(conn, task_id, step, str(shot_path))

            if action.type == "done":
                end_task(conn, task_id, result)
                print(f"\n[done] {result[:200]}")
                return result

        result = "(max_steps 耗尽未完成)"
        end_task(conn, task_id, result)
        print(f"\n[max_steps] {result}")
        return result
    finally:
        conn.close()
