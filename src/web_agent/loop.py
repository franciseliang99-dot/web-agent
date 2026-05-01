"""ReAct loop: max_steps + Action Trace + 每步持久化截图/思考/行动。"""

from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path

from anthropic import AsyncAnthropic
from playwright.async_api import Page

from web_agent.actuator import human_like_click, human_like_type, scroll, think
from web_agent.perceiver import Mark, perceive
from web_agent.planner import Action, plan
from web_agent.trace import Step, Trace, end_task, init_db, start_task, write_step


def _find_mark(marks: list[Mark], mark_id: int) -> Mark | None:
    for m in marks:
        if m.id == mark_id:
            return m
    return None


async def run_react_loop(
    page: Page,
    client: AsyncAnthropic,
    model: str,
    goal: str,
    max_steps: int = 20,
    db_path: Path = Path("data/trace.db"),
    screenshots_dir: Path = Path("data/screenshots"),
) -> str:
    """跑 ReAct 循环直到 done 或 max_steps。返回最终结果文本。"""
    task_id = uuid.uuid4().hex[:12]
    conn = init_db(db_path)
    start_task(conn, task_id, goal)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    trace = Trace(task_id=task_id, goal=goal)
    result = "(no result)"

    try:
        for step_i in range(max_steps):
            await think()
            marks, screenshot_b64 = await perceive(page)

            shot_path = screenshots_dir / f"{task_id}-{step_i:02d}.png"
            shot_path.write_bytes(base64.b64decode(screenshot_b64))

            print(f"\n[step {step_i}] perceive: {len(marks)} marks, screenshot {shot_path}")

            action: Action = await plan(client, model, goal, screenshot_b64, marks, trace)
            print(f"[step {step_i}] action: {action.type} {action.args} | thought: {action.thought[:120]}")

            obs = ""
            if action.type == "click":
                m = _find_mark(marks, action.args.get("mark_id", -1))
                if m is None:
                    obs = f"ERROR: mark_id={action.args.get('mark_id')} 不在当前 marks 里"
                else:
                    await human_like_click(page, m)
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
                step = Step(
                    step=step_i,
                    ts=time.time(),
                    thought=action.thought,
                    action_type=action.type,
                    action_args=action.args,
                    observation=result,
                )
                trace.append(step)
                write_step(conn, task_id, step, str(shot_path))
                end_task(conn, task_id, result)
                print(f"\n[done] {result[:200]}")
                return result
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

        result = "(max_steps 耗尽未完成)"
        end_task(conn, task_id, result)
        print(f"\n[max_steps] {result}")
        return result
    finally:
        conn.close()
