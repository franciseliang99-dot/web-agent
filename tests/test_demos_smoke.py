"""Demo smoke tests：每个 demo 文件能 import + main 是 async coroutine factory。

不跑 main()（会真启 chrome + 调 LLM 烧 token）。零成本检测 demo 静默腐烂——
比如某天 `run_task` 签名变了或 `from web_agent.cli import run_task` 路径改了，
demo 不跑没人发现，直到下次手动跑才挂。

实现用 `importlib.util.spec_from_file_location` 从文件路径直接 load，
避免改 pytest pythonpath 配置（demos/ 不在 src layout 内）。
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

DEMOS_DIR = Path(__file__).parent.parent / "demos"


@pytest.mark.parametrize(
    "demo_file",
    [
        "wikipedia_search.py",
        "github_search.py",
        "gmail_summary.py",
    ],
)
def test_demo_imports_and_has_main_coroutine(demo_file: str) -> None:
    path = DEMOS_DIR / demo_file
    assert path.exists(), f"demo file 不存在: {path}"

    spec = importlib.util.spec_from_file_location(demo_file[:-3], path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 触发 import 副作用（含 from web_agent.* 等）

    assert hasattr(mod, "main"), f"{demo_file} 缺 main 函数"
    assert asyncio.iscoroutinefunction(mod.main), (
        f"{demo_file}.main 不是 async coroutine factory"
    )
