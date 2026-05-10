"""中性工具 schema 定义 + 各 provider 格式转换 + 共享 SYSTEM_PROMPT + user-text 构造。

业务工具语义（5 个 action）写一份中性 dict（接近 JSON Schema 通用子集），
各 provider client 内部转换为自己的格式：
- Anthropic: name + description + input_schema
- OpenAI: type='function', function={name, description, parameters, strict}
- Gemini (留位): function_declarations
"""

from __future__ import annotations

import json
from typing import Any

from web_agent.perceiver import marks_to_text
from web_agent.trace import Trace
from web_agent.types import Mark

SYSTEM_PROMPT = """你是一个高度拟人的浏览器自动化 agent。每步给你当前页面的标注截图（每个可交互元素都有彩色边框 + 数字 ID）和元素清单，请按以下规则输出下一步操作：

1. 必须通过 tool 调用返回行动，不要回纯文本。
2. 操作前先用 thought 字段说明你的判断（基于截图实际看到的内容，不要臆测）。
3. 优先选择最直接达成 goal 的操作；遇到 cookie 同意框 / 广告弹窗 / 注册引导先关掉。
4. 任务完成后调用 `done` 工具并把最终答案写在 `result` 字段。
5. 连续 2 步页面无变化（thought 中识别到）→ 尝试不同策略：滚动 / 后退 / 选另一个候选元素。
6. 严禁猜测 mark_id — 只能用截图里实际存在的编号；编号缺失就先 scroll 让页面重新标注。
7. 输入框先 click 再 type。type 的 submit=true 会按回车。
8. **编辑现有内容 (contenteditable / textarea / 富文本编辑器) 走完整组合, 不要反复 click 同元素**:
   - 第 1 步: click 编辑器 (1 次, 仅为聚焦)
   - 第 2 步: `keyboard_shortcut` (key="Control+End" 跳末尾 / "Control+a" 选全部 / "End" 行末)
   - 第 3 步: `paste` (长文本 >50 字符) 或 `type` (短文本) 输入内容
   - 第 4 步: `done` 返回结果
   - 严禁 click 同一 mark_id 超过 1 次! click 不会移动光标; keyboard_shortcut 后应直接走 paste/type, 不要再 click。
9. 长文本 (>50 字符) 优先 `paste`, 短文本 `type`。`paste` 前必须先 click 聚焦目标输入框 (paste 跟 type 同样需要 focus, 但比 type 快且不触发反爬键盘指纹)。
10. **多 tab 编排** (V0.21+): 浏览器可能开多个 tab — 用户提示中的 `Tabs (N open, current=X)` header 列出所有 tab。用 `switch_tab(idx=...)` 切换 active tab (索引 == header 里的 [idx])，用 `close_tab(idx=...)` 关 tab。规则：(a) `close_tab` 不能关最后 1 个 tab，也不能关当前 active tab (先 switch 再 close)；(b) 切 tab 后下一步 perceive 才能看到新 tab 的截图，不要假设切完立即生效；(c) 新弹 tab (target=_blank/window.open) 自动出现在 header，不需要主动切除非任务需要在新 tab 操作。
"""


# 中性工具 schema（接近 JSON Schema，所有 provider 兼容子集）。
# 注意：OpenAI strict mode 要求所有 properties 都在 required；本表 required 可能少于 properties，
# 各 client 转换时按需扩展（_to_openai_tools 会处理）。
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "click",
        "description": "点击截图中编号为 mark_id 的元素。",
        "properties": {
            "thought": {"type": "string", "description": "为什么点这个元素"},
            "mark_id": {"type": "integer", "description": "元素的 SoM 编号"},
        },
        "required": ["thought", "mark_id"],
    },
    {
        "name": "type",
        "description": "在当前焦点的输入框中逐字键入文本。先用 click 把焦点放到输入框上。",
        "properties": {
            "thought": {"type": "string"},
            "text": {"type": "string", "description": "要键入的文本"},
            "submit": {"type": "boolean", "description": "键入后是否按回车提交"},
        },
        "required": ["thought", "text"],
    },
    {
        "name": "scroll",
        "description": "滚动页面（正数下滚，负数上滚，单位像素）。",
        "properties": {
            "thought": {"type": "string"},
            "dy": {"type": "integer", "description": "正数下滚，负数上滚"},
        },
        "required": ["thought", "dy"],
    },
    {
        "name": "extract",
        "description": "从当前页面读取信息（不操作页面，把读到的内容写到 answer）。",
        "properties": {
            "thought": {"type": "string"},
            "query": {"type": "string", "description": "要提取的内容描述"},
            "answer": {"type": "string", "description": "你从截图中读到的答案"},
        },
        "required": ["thought", "query", "answer"],
    },
    {
        "name": "done",
        "description": "任务完成，把最终结果写到 result 返回给用户。",
        "properties": {
            "thought": {"type": "string"},
            "result": {"type": "string", "description": "最终结果"},
        },
        "required": ["thought", "result"],
    },
    {
        "name": "keyboard_shortcut",
        "description": "按键盘快捷键 (e.g. Control+End 跳到 textarea/contenteditable 末尾; Control+a 选全部; Tab 切换焦点). Playwright key syntax: 修饰符用 '+' 拼接最终键, e.g. 'Control+End' / 'End' / 'Tab' / 'Control+a' / 'PageDown'.",
        "properties": {
            "thought": {"type": "string"},
            "key": {"type": "string", "description": "按键组合, e.g. 'Control+End', 'End', 'Tab', 'Control+a'"},
        },
        "required": ["thought", "key"],
    },
    {
        "name": "paste",
        "description": "把 text 粘贴到当前 focus 的输入框/textarea/contenteditable。比 type 快, 适合长文本 (>50 字符). paste 前必须先 click 把焦点放到目标输入框。",
        "properties": {
            "thought": {"type": "string"},
            "text": {"type": "string", "description": "要粘贴的文本"},
        },
        "required": ["thought", "text"],
    },
    {
        "name": "switch_tab",
        "description": "切换到第 idx 个 tab 作为后续 perceive/click/type 的目标 (idx 来自用户消息 header 里的 [idx])。切完下一步才能看到新 tab 截图，不要假设立即生效。",
        "properties": {
            "thought": {"type": "string"},
            "idx": {"type": "integer", "description": "目标 tab 索引 (header 里的 [idx])"},
        },
        "required": ["thought", "idx"],
    },
    {
        "name": "close_tab",
        "description": "关闭第 idx 个 tab。规则：(a) 不能关最后 1 个 tab；(b) 不能关当前 active tab (先 switch_tab 切走再 close)。违反会被 loop 拒绝。",
        "properties": {
            "thought": {"type": "string"},
            "idx": {"type": "integer", "description": "要关的 tab 索引 (header 里的 [idx])"},
        },
        "required": ["thought", "idx"],
    },
]


def to_anthropic_tools(
    schemas: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """中性 schema → Anthropic tools 格式（input_schema 包装）。"""
    schemas = schemas if schemas is not None else TOOL_SCHEMAS
    return [
        {
            "name": s["name"],
            "description": s["description"],
            "input_schema": {
                "type": "object",
                "properties": s["properties"],
                "required": s["required"],
            },
        }
        for s in schemas
    ]


def to_openai_tools(
    schemas: list[dict[str, Any]] | None = None,
    strict: bool = True,
) -> list[dict[str, Any]]:
    """中性 schema → OpenAI tools 格式（function.parameters + 可选 strict 模式）。

    strict=True 时（默认）：
    - 所有 properties 必须在 required 列表中（OpenAI strict mode 要求）；
      原本 optional 的字段（如 type.submit）会被强制放进 required，
      LLM 必须显式给值（boolean default 由 LLM 自决，常见就是写 false）
    - parameters 必须含 additionalProperties: false
    - function 顶层必须含 strict: true
    """
    schemas = schemas if schemas is not None else TOOL_SCHEMAS
    tools = []
    for s in schemas:
        required = list(s["properties"].keys()) if strict else s["required"]
        params: dict[str, Any] = {
            "type": "object",
            "properties": s["properties"],
            "required": required,
        }
        if strict:
            params["additionalProperties"] = False
        tool: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": params,
            },
        }
        if strict:
            tool["function"]["strict"] = True
        tools.append(tool)
    return tools


def build_user_text(goal: str, marks: list[Mark], trace: Trace) -> str:
    """构造各 provider plan() 通用的 user 消息 text 部分（截图 image block 由各 client 自己拼）。

    包括 goal、历史 trace JSON 序列化、当前 SoM 元素清单。Anthropic 和 OpenAI 共用此文本，
    差异只在 image content block 格式（Anthropic source.base64 vs OpenAI image_url data: URL）。
    """
    history_text = (
        json.dumps(trace.for_llm(), ensure_ascii=False, indent=2)
        if trace.steps
        else "(空)"
    )
    return (
        f"# 任务目标\n{goal}\n\n"
        f"# 历史 Action Trace\n{history_text}\n\n"
        f"# 当前可交互元素清单（编号对应截图边框）\n{marks_to_text(marks)}\n\n"
        f"请通过 tool 返回下一步操作。"
    )
