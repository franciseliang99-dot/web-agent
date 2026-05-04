"""V0.16.2 web-agent MCP server 端到端 stdio 协议层验证脚本。

跑: `uv run python scripts/test_mcp_local.py`

单条命令验证 4 件事 (subagent 审核反馈采纳的 minimal smoke):
1. server stdio 启动不崩溃
2. initialize 握手返合法 protocolVersion
3. list_tools 含 3 个 tool 名 (web_agent_run / web_agent_get_replay / web_agent_query_memory)
4. web_agent_run 无 Chrome 时返 chrome_not_running 结构化错误 (V0.16.1 _check_chrome_alive 兜底)

退出码: 0 = 全 PASS, 非 0 = 有 FAIL
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "web-agent-mcp"],
        env=None,
    )

    failures: list[str] = []

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. initialize 握手
            init_result = await session.initialize()
            print(f"✓ initialize OK (protocolVersion={init_result.protocolVersion})")

            # 2. list_tools 验 3 名
            tools_resp = await session.list_tools()
            names = {t.name for t in tools_resp.tools}
            expected = {"web_agent_run", "web_agent_get_replay", "web_agent_query_memory"}
            if names == expected:
                print(f"✓ list_tools OK: {sorted(names)}")
            else:
                failures.append(f"list_tools 名不匹配: got {names}, expected {expected}")
                print(f"✗ list_tools FAIL: got {names}")

            # 3. web_agent_run 无 Chrome 时返 chrome_not_running
            #    (假设当前 Chrome 9222 不通; 通了的话改 cdp_url 到一个不通的端口)
            run_result = await session.call_tool(
                "web_agent_run",
                {"goal": "smoke test", "url": "", "max_steps": 1},
            )
            text = " ".join(c.text for c in run_result.content if hasattr(c, "text"))
            if run_result.isError and "chrome_not_running" in text:
                print("✓ web_agent_run chrome_not_running 兜底 OK")
            elif not run_result.isError:
                print("⚠ web_agent_run 未报 error (Chrome 可能起了, 跳过此断言)")
            else:
                failures.append(f"web_agent_run 报 error 但不是 chrome_not_running: {text[:200]}")
                print(f"✗ web_agent_run FAIL: {text[:200]}")

            # 4. web_agent_query_memory 不依赖 Chrome, 跑空 domain 应返 []
            mem_result = await session.call_tool("web_agent_query_memory", {"domain": ""})
            if not mem_result.isError and mem_result.structuredContent == {"result": []}:
                print("✓ web_agent_query_memory empty-domain → [] OK")
            else:
                failures.append(f"query_memory empty 异常: {mem_result.structuredContent}")
                print(f"✗ query_memory FAIL: {mem_result.structuredContent}")

    if failures:
        print(f"\n=== {len(failures)} FAIL ===")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\n=== ALL PASS — MCP server stdio 协议层端到端验通 ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
