"""LLMClient Protocol — 跨 provider 的 plan() 接口（ports 层）。

依赖方向（按用户 CLAUDE.md「解耦优先」）：
    domain (web_agent.types: Mark, Action; trace.Trace) ← ports (本文件) ← 业务层 (loop.py) ← 组合根 (cli.py)

各 provider 的具体 client（anthropic.py / openai.py / ...）实现本 Protocol，
仅在 llm/__init__.py 的 make_client factory 里实例化，外部代码只依赖 LLMClient 类型。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from web_agent.trace import Trace
from web_agent.types import Action, Mark, Usage


@runtime_checkable
class LLMClient(Protocol):
    """跨 provider 的 LLM client 抽象。

    实现类需要：
    - 在 __init__ 里持有自己的 SDK 客户端 + model + 任何 provider-specific 配置（cache/strict 等）
    - 暴露 `name` 属性用于日志（"anthropic" / "openai" / "gemini" ...）
    - 暴露 `model` 属性用于日志
    - plan() 接收 goal / 截图 b64 / SoM marks / 历史 trace，返回结构化 Action
    - V0.26.2: 暴露 `last_usage: Usage | None` 属性记录上次 plan() token 用量, 默认 None
      让现有 FakeLLMClient (V0.21.2 加 **kwargs) 零改动兼容. eval/runner 累加用.
    """

    name: str
    model: str
    last_usage: Usage | None

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

    async def reflect(self, prompt: str) -> str:
        """V0.28.1: W6-A 失败反思 — 单次 raw text completion (无 tools / 无 image / 无 cache).

        给 reflect.build_reflect_prompt 输出的纯文本 prompt, 返 LLM raw text response.
        caller (loop._maybe_reflect_on_failure) 用 reflect.parse_reflection 解析返值成
        Reflection dataclass + record_reflection 持久化.

        跟 plan() 正交:
        - plan(): ReAct loop 内 SoM marks + screenshot + trace + tools (Action 输出)
        - reflect(): 失败 task 后 trace 文本反思 + 无 tools (raw str 输出)

        token 不更 self.last_usage (eval/runner 只累加 plan() 成本, reflect 是 task 级 overhead;
        V0.28.3 eval --reflect flag 时再加 last_reflect_usage 单独累加, YAGNI).
        """
        ...
