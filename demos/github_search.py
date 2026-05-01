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
        f"在 GitHub 顶部搜索框输入「{keyword}」并回车提交。"
        f"搜索结果页打开后，找到 Repositories 类别下星数最高的开源 repo——"
        f"如果默认排序不是按 star，点击 sort 下拉切到「Most stars」。"
        f"点击进入排第一的 repo 详情页。"
        f"从**右侧 About 区域**读取该 repo 的一句话简介（不必从 README 正文找，About sidebar 的描述就是权威），"
        f"同时记下 repo 名称（owner/name 形式）和 star 数（如「12.5k」）。"
        f"**拿到这三个字段后立即用 done 工具返回**，格式为: "
        f"'repo: <owner/name>, stars: <count>, summary: <一句话简介>'。"
        f"不要反复 scroll 验证，已经拿到的答案就是答案。"
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
