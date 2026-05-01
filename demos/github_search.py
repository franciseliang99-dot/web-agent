"""W2-B demo: 在 GitHub 搜 repo → 按 star 排序 → 进第一个 → 提取 star 数 + 简介。

用法:
  cd /home/myclaw/web-agent
  uv run python demos/github_search.py "web agent"
  # 或换关键词: "claude code", "playwright", "browser-use" ...
"""

from __future__ import annotations

import asyncio
import sys

from web_agent.cli import run_task


async def main() -> None:
    if len(sys.argv) < 2:
        print('用法: uv run python demos/github_search.py "<搜索词>"')
        sys.exit(1)
    keyword = sys.argv[1]
    goal = (
        f"在 GitHub 顶部搜索框输入「{keyword}」并提交搜索（回车）。"
        f"搜索结果页打开后，找到 Repositories 类别下星数最高的开源 repo——"
        f"如果默认排序不是按 star，请点击 sort 下拉切到「Most stars」。"
        f"点击进入排在第一位的 repo 详情页，从 README 区域读取该 repo 的一句话简介（约 30-100 字），"
        f"同时提取页面顶部显示的 star 数（如「12.5k」）。"
        f"最终用 done 工具返回结果，格式为: "
        f"'repo: <owner/name>, stars: <count>, summary: <一句话简介>'"
    )
    result = await run_task(
        goal=goal,
        start_url="https://github.com",
        max_steps=18,
    )
    print("\n=== GitHub 搜索结果 ===")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
