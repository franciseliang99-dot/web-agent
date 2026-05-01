"""Anthropic Claude vision call + prompt caching + tool-use 结构化 action。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from anthropic import AsyncAnthropic

from web_agent.perceiver import Mark, marks_to_text
from web_agent.trace import Trace

SYSTEM_PROMPT = """你是一个高度拟人的浏览器自动化 agent。每步给你当前页面的标注截图（每个可交互元素都有彩色边框 + 数字 ID）和元素清单，请按以下规则输出下一步操作：

1. 必须通过 tool 调用返回行动，不要回纯文本。
2. 操作前先用 thought 字段说明你的判断（基于截图实际看到的内容，不要臆测）。
3. 优先选择最直接达成 goal 的操作；遇到 cookie 同意框 / 广告弹窗 / 注册引导先关掉。
4. 任务完成后调用 `done` 工具并把最终答案写在 `result` 字段。
5. 连续 2 步页面无变化（thought 中识别到）→ 尝试不同策略：滚动 / 后退 / 选另一个候选元素。
6. 严禁猜测 mark_id — 只能用截图里实际存在的编号；编号缺失就先 scroll 让页面重新标注。
7. 输入框先 click 再 type。type 的 submit=true 会按回车。
"""

TOOLS = [
    {
        "name": "click",
        "description": "点击截图中编号为 mark_id 的元素。",
        "input_schema": {
            "type": "object",
            "properties": {
                "thought": {"type": "string", "description": "为什么点这个元素"},
                "mark_id": {"type": "integer", "description": "元素的 SoM 编号"},
            },
            "required": ["thought", "mark_id"],
        },
    },
    {
        "name": "type",
        "description": "在当前焦点的输入框中逐字键入文本。先用 click 把焦点放到输入框上。",
        "input_schema": {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "text": {"type": "string", "description": "要键入的文本"},
                "submit": {
                    "type": "boolean",
                    "description": "键入后是否按回车提交",
                    "default": False,
                },
            },
            "required": ["thought", "text"],
        },
    },
    {
        "name": "scroll",
        "description": "滚动页面（正数下滚，负数上滚，单位像素）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "dy": {"type": "integer", "description": "正数下滚，负数上滚"},
            },
            "required": ["thought", "dy"],
        },
    },
    {
        "name": "extract",
        "description": "从当前页面读取信息（不操作页面，把读到的内容写到 answer）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "query": {"type": "string", "description": "要提取的内容描述"},
                "answer": {"type": "string", "description": "你从截图中读到的答案"},
            },
            "required": ["thought", "query", "answer"],
        },
    },
    {
        "name": "done",
        "description": "任务完成，把最终结果写到 result 返回给用户。",
        "input_schema": {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "result": {"type": "string", "description": "最终结果"},
            },
            "required": ["thought", "result"],
        },
    },
]


@dataclass
class Action:
    type: str  # click / type / scroll / extract / done
    args: dict
    thought: str


def make_client() -> AsyncAnthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 未设置 — 请填 .env 或 export 环境变量")
    return AsyncAnthropic(api_key=api_key)


async def plan(
    client: AsyncAnthropic,
    model: str,
    goal: str,
    screenshot_b64: str,
    marks: list[Mark],
    trace: Trace,
) -> Action:
    """调用 Claude vision，返回结构化 Action。"""
    history_text = (
        json.dumps(trace.for_llm(), ensure_ascii=False, indent=2)
        if trace.steps
        else "(空)"
    )
    user_content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": screenshot_b64,
            },
        },
        {
            "type": "text",
            "text": (
                f"# 任务目标\n{goal}\n\n"
                f"# 历史 Action Trace\n{history_text}\n\n"
                f"# 当前可交互元素清单（编号对应截图边框）\n{marks_to_text(marks)}\n\n"
                f"请通过 tool 返回下一步操作。"
            ),
        },
    ]

    resp = await client.messages.create(
        model=model,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=TOOLS,
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": user_content}],
    )

    for block in resp.content:
        if block.type == "tool_use":
            args = dict(block.input)
            thought = args.pop("thought", "")
            return Action(type=block.name, args=args, thought=thought)

    raise RuntimeError(f"Claude 没返回 tool_use: {resp.content!r}")
