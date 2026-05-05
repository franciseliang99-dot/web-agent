"""V0.16.1+ MCP server: 暴露 web-agent 为 MCP server (Claude Desktop / 任意 MCP client 调).

3 tools (有副作用 / 主动调用):
- `web_agent_run(goal, url, max_steps)`: 跑一个 task, 返 result string
- `web_agent_get_replay(task_id)`: 渲染 replay HTML, 返 {task_id, html_path, step_count, result}
- `web_agent_query_memory(domain, limit)`: 长期记忆 by domain, 返 list[dict]

2 resources (V0.16.6 加, 只读视图 / 客户端订阅):
- `webagent://replay/{task_id}`: 渲染好的 replay HTML 文本 (text/html mime)
- `webagent://memory/{domain}`: 长期记忆 entries JSON (application/json mime)

设计:
- FastMCP decorator 风格 (官方推荐)
- Module-level `_RUN_LOCK` 串行化并发 task (Chrome CDP 单 tab 抢, 测试 monkeypatch 可重置)
- per-tool-call Chrome 9222 健康检查 (urllib stdlib, 仅 web_agent_run 需)
- progress notification 通过 ctx.report_progress(progress, total, message) DI 到 loop 不破坏解耦
- exception → 返 structured tool error / resource error (FastMCP 自动序列化)
- Resources vs tools: replay/memory 本质 read-only 订阅, resource 语义比 tool 更准

CLI:
  uv run web-agent-mcp                 # stdio mode (Claude Desktop 默认)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from web_agent.cli import run_task as cli_run_task
from web_agent.memory import (
    DEFAULT_DB as _MEM_DB,
    extract_domain,
    recall_by_domain,
)
from web_agent.replay import render_to_file as replay_render_to_file

logger = logging.getLogger(__name__)

# 同时只跑一个 web_agent_run task: Chrome CDP 单 tab, 并发抢会撞 SoM 注入 / actuator 鼠标 race.
# 第二个并发 call 会 await 此 lock 等待第一个完成 (不 fail-fast 直接 reject 让 client 自然排队).
_RUN_LOCK = asyncio.Lock()

mcp = FastMCP("web-agent")


def _check_chrome_alive(cdp_url: str, timeout: float = 2.0) -> None:
    """检查 9222 端口可达, 不可达 raise RuntimeError. 仅 web_agent_run 需调.

    阻塞 urllib 调用; async 调用方应包 asyncio.to_thread 释放事件循环.
    """
    probe_url = f"{cdp_url.rstrip('/')}/json/version"
    try:
        with urllib.request.urlopen(probe_url, timeout=timeout):
            return
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(
            f"chrome_not_running: {cdp_url} 无响应 ({e!r}). "
            "提示: 先在另一终端跑 `bash scripts/start_chrome.sh` 启 9222 调试端口的 Chrome."
        )


@mcp.tool()
async def web_agent_run(
    goal: str,
    url: str = "",
    max_steps: int = 20,
    ctx: Context[Any, Any] | None = None,
) -> str:
    """跑一个 web-agent task: 用 ReAct loop 在 Chrome 里完成 goal.

    Args:
        goal: 自然语言任务描述 (e.g. "在维基百科搜量子纠缠并提取首段")
        url: 起始 URL, 空则从 Chrome 当前 tab 开始
        max_steps: 最大步数 (默认 20, ReAct loop 上限)

    Returns: 最终结果文本 (如 "result: ...", 或 SAFETY_BLOCK / WALLCLOCK_EXCEEDED 等错误).

    Raises:
        RuntimeError: Chrome 9222 不可达 (用户没起 Chrome).
    """
    cdp_url = os.environ.get("WEB_AGENT_CDP_URL", "http://127.0.0.1:9222")
    await asyncio.to_thread(_check_chrome_alive, cdp_url)

    # ctx.report_progress(progress, total, message) bound method 直接 1:1 对齐 ProgressCallback
    progress_cb = ctx.report_progress if ctx is not None else None
    async with _RUN_LOCK:
        return await cli_run_task(
            goal=goal,
            start_url=url or None,
            max_steps=max_steps,
            progress_cb=progress_cb,
        )


def _render_replay(task_id: str) -> dict[str, Any]:
    """渲染 replay 共享实现: tool/resource 都走它. SystemExit 转 RuntimeError 防 server 退出.

    replay.load_task 用 sys.exit() 报错 (CLI 行为); FastMCP 不 catch BaseException,
    必须转为 Exception 让 SDK 序列化为 tool/resource error 而不让 server 进程退出.
    """
    try:
        return replay_render_to_file(task_id or None)
    except SystemExit as e:
        raise RuntimeError(f"replay 失败: {e}") from e


def _query_memory(domain: str, limit: int) -> list[dict[str, Any]]:
    """查询长期记忆共享实现: tool/resource 都走它. 空 domain → []; URL 形式自动 normalize."""
    if not domain:
        return []
    if domain.startswith("http://") or domain.startswith("https://"):
        domain = extract_domain(domain)
    mem_db = Path(os.environ.get("WEB_AGENT_MEMORY_DB", str(_MEM_DB)))
    entries = recall_by_domain(mem_db, domain, limit=limit)
    return [
        {"ts": e.ts, "domain": e.domain, "goal": e.goal, "result": e.result, "success": e.success}
        for e in entries
    ]


@mcp.tool()
async def web_agent_get_replay(task_id: str) -> dict[str, Any]:
    """渲染指定 task 的 replay HTML, 返结构化路径.

    Args:
        task_id: trace.db 里的 task_id (12 字符 hex). 空字符串表"最新一次".

    Returns: {"task_id", "html_path" (绝对路径), "step_count", "result"}.

    Raises:
        RuntimeError: db 不存在 / task_id 不存在 (replay.load_task SystemExit 转译).
    """
    return _render_replay(task_id)


@mcp.resource(
    "webagent://replay/{task_id}",
    name="web-agent replay HTML",
    description="渲染好的 ReAct trace replay HTML (含截图 + 思考 + 行动时间线). 只读.",
    mime_type="text/html",
)
async def replay_resource(task_id: str) -> str:
    """V0.16.6 read-only resource: 客户端订阅指定 task_id 的 replay HTML 文本.

    与 `web_agent_get_replay` tool 的差异: tool 返结构化 dict (含 path/step_count),
    resource 直接返 HTML 文本 (client 可 inline render). 同源数据无副作用.
    """
    info = _render_replay(task_id)
    return Path(info["html_path"]).read_text(encoding="utf-8")


@mcp.resource(
    "webagent://memory/{domain}",
    name="web-agent 长期记忆",
    description="按 domain 拉历史 task outcome (ts/goal/result/success), 默认 5 条.",
    mime_type="application/json",
)
async def memory_resource(domain: str) -> list[dict[str, Any]]:
    """V0.16.6 read-only resource: 客户端订阅指定 domain 的历史 task entries (JSON list).

    与 `web_agent_query_memory` tool 的差异: tool 接 limit 参数 + 主动调用语义,
    resource URI 模板更适合 LLM 当上下文订阅 (e.g. 调 web_agent_run 前自动拉同 domain 历史).
    """
    return _query_memory(domain, limit=5)


@mcp.tool()
async def web_agent_query_memory(domain: str, limit: int = 5) -> list[dict[str, Any]]:
    """查询长期记忆: 按 domain 拉历史 task outcome.

    Args:
        domain: 域名 (e.g. "github.com") 或 URL ("https://github.com/x"), 后者自动 extract domain.
        limit: 返条数上限 (默认 5).

    Returns: list[dict] 每条 {ts, domain, goal, result, success}, 按 ts DESC 排序.
    """
    return _query_memory(domain, limit=limit)


def main() -> None:
    """stdio mode entry: 走 JSON-RPC over stdio (Claude Desktop 默认 transport).

    必须在 mcp.run() 前 basicConfig logging 走 stderr, 防业务模块 logger 输出污染 stdout.
    """
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="[%(name)s] %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
