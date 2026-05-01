"""W1 demo: 在中文 Wikipedia 搜词条 + 提取首段。

用法:
  终端 A: bash scripts/start_chrome.sh
  终端 B: uv run python demos/wikipedia_search.py "量子纠缠"
"""

from __future__ import annotations

import asyncio
import sys

from web_agent.cli import run_task


async def main() -> None:
    if len(sys.argv) < 2:
        print('用法: uv run python demos/wikipedia_search.py "<搜索词>"')
        sys.exit(1)
    keyword = sys.argv[1]
    goal = (
        f"在维基百科中文版（zh.wikipedia.org）搜索「{keyword}」词条，"
        f"打开词条页面后从主体内容中读取该词条的简介首段（约 100-300 字）。"
        f"读到后用 done 工具返回这段简介文本作为 result。"
    )
    result = await run_task(
        goal=goal,
        start_url="https://zh.wikipedia.org/",
        max_steps=12,
    )
    print("\n=== Wikipedia 简介 ===")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
