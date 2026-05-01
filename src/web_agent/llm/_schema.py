"""中性工具 schema 定义 + 各 provider 格式转换 + 共享 SYSTEM_PROMPT。

业务工具语义（5 个 action）写一份中性 dict（接近 JSON Schema 通用子集），
各 provider client 内部转换为自己的格式：
- Anthropic: name + description + input_schema
- OpenAI: type='function', function={name, description, parameters, strict}
- Gemini (留位): function_declarations
"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """你是一个高度拟人的浏览器自动化 agent。每步给你当前页面的标注截图（每个可交互元素都有彩色边框 + 数字 ID）和元素清单，请按以下规则输出下一步操作：

1. 必须通过 tool 调用返回行动，不要回纯文本。
2. 操作前先用 thought 字段说明你的判断（基于截图实际看到的内容，不要臆测）。
3. 优先选择最直接达成 goal 的操作；遇到 cookie 同意框 / 广告弹窗 / 注册引导先关掉。
4. 任务完成后调用 `done` 工具并把最终答案写在 `result` 字段。
5. 连续 2 步页面无变化（thought 中识别到）→ 尝试不同策略：滚动 / 后退 / 选另一个候选元素。
6. 严禁猜测 mark_id — 只能用截图里实际存在的编号；编号缺失就先 scroll 让页面重新标注。
7. 输入框先 click 再 type。type 的 submit=true 会按回车。
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
