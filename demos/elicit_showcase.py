"""V0.18.4 demo: SafetyApprovalCallback 程序化定制 (CLI 模式 elicit 替身).

V0.18.0 把 safety hardcoded "拦截即 abort" 改为可注入 callback (`SafetyApprovalCallback`).
MCP server 模式自动注入 `ctx.elicit()`; CLI 模式默认 cb=None 维持 abort.
本 demo 展示 CLI 模式下用户手写 cb (终端 input 替代 elicit) 的 reference 实现.

⚠ **运行前提**:
   - Chrome 9222 已起 (`bash scripts/start_chrome.sh` & 或 V0.16.19 auto-spawn)
   - 不需登录任何站点 (用本地 file:// fixture)

⚠ **行为** (走 zero-side-effect fixture):
   1. agent click input + type 'hello' (前 2 步无 safety 拦截)
   2. agent 决定 click 'Publish' 按钮 → safety 拦 (rule=send-or-pay)
   3. cb 被调, 终端 input() 询问 y/n
   4. 选 y → 真 click button (button onclick 改 div text), agent done
   5. 选 n → SAFETY_BLOCK abort, trace 写 safety_block step

用法:
   bash scripts/start_chrome.sh             # 终端 A (已起则跳)
   uv run python demos/elicit_showcase.py   # 终端 B
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from web_agent.cli import run_task

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[%(name)s] %(message)s")

_FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "dogfood_publish.html"


async def cli_safety_approval_cb(rule: str, reason: str) -> bool:
    """CLI 模式 elicit 替身: 终端 input 询问 y/n.

    asyncio.to_thread 必需: input() 同步阻塞会卡住 event loop, 包 to_thread 释放.
    """
    print(f"\n⚠ safety 拦截: rule={rule}", file=sys.stderr)
    print(f"  reason: {reason}", file=sys.stderr)
    response = await asyncio.to_thread(input, "approve? (y/N): ")
    return response.strip().lower() in ("y", "yes")


async def main() -> None:
    if not _FIXTURE.exists():
        print(f"\n⚠ fixture 不存在: {_FIXTURE}", file=sys.stderr)
        sys.exit(2)

    goal = (
        "在当前页面的 input (id=msg, placeholder='Type here') 里输入 'hello',"
        "然后点击页面上文本为 'Publish' 的按钮."
    )
    result = await run_task(
        goal=goal,
        start_url=f"file://{_FIXTURE}",
        max_steps=10,
        safety_approval_cb=cli_safety_approval_cb,
    )
    print("\n=== Elicit Showcase Result ===")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
