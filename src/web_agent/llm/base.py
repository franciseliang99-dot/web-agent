"""LLMClient Protocol — 跨 provider 的 plan() 接口（ports 层）。

依赖方向（按用户 CLAUDE.md「解耦优先」）：
    domain (web_agent.types: Mark, Action; trace.Trace) ← ports (本文件) ← 业务层 (loop.py) ← 组合根 (cli.py)

各 provider 的具体 client（anthropic.py / openai.py / ...）实现本 Protocol，
仅在 llm/__init__.py 的 make_client factory 里实例化，外部代码只依赖 LLMClient 类型。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from web_agent.trace import Trace
from web_agent.types import Action, Mark


@runtime_checkable
class LLMClient(Protocol):
    """跨 provider 的 LLM client 抽象。

    实现类需要：
    - 在 __init__ 里持有自己的 SDK 客户端 + model + 任何 provider-specific 配置（cache/strict 等）
    - 暴露 `name` 属性用于日志（"anthropic" / "openai" / "gemini" ...）
    - 暴露 `model` 属性用于日志
    - plan() 接收 goal / 截图 b64 / SoM marks / 历史 trace，返回结构化 Action
    """

    name: str
    model: str

    async def plan(
        self,
        goal: str,
        screenshot_b64: str,
        marks: list[Mark],
        trace: Trace,
        *,
        tabs: list[tuple[int, str]] | None = None,
        current_idx: int = 0,
        cross_origin_hosts: list[str] | None = None,
    ) -> Action: ...
