"""中性 TOOL_SCHEMAS → provider tools 转换的纯函数测试。

不调用真实 LLM（无 key 依赖），只验证 schema 形状符合各 provider 要求。
"""

from __future__ import annotations

from web_agent.llm._schema import TOOL_SCHEMAS, to_anthropic_tools, to_openai_tools

EXPECTED_TOOL_NAMES = {"click", "type", "scroll", "extract", "done", "keyboard_shortcut", "paste"}


def test_neutral_schemas_have_7_tools_with_thought():
    assert {s["name"] for s in TOOL_SCHEMAS} == EXPECTED_TOOL_NAMES
    for s in TOOL_SCHEMAS:
        assert "thought" in s["properties"], f"{s['name']} 缺 thought 字段"
        assert "thought" in s["required"], f"{s['name']} thought 必须是 required"


def test_to_anthropic_tools_shape():
    tools = to_anthropic_tools()
    assert len(tools) == 7
    for t in tools:
        assert set(t.keys()) == {"name", "description", "input_schema"}
        assert t["input_schema"]["type"] == "object"
        assert "properties" in t["input_schema"]
        assert "required" in t["input_schema"]
    assert {t["name"] for t in tools} == EXPECTED_TOOL_NAMES


def test_to_openai_tools_strict_mode_invariants():
    """OpenAI strict mode 要求：
    1. function.strict = True
    2. parameters.additionalProperties = False
    3. parameters.required 必须包含所有 properties（即便业务上是 optional）
    """
    tools = to_openai_tools(strict=True)
    assert len(tools) == 7
    for t in tools:
        assert t["type"] == "function"
        f = t["function"]
        assert f["strict"] is True
        params = f["parameters"]
        assert params["type"] == "object"
        assert params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"].keys()), (
            f"{f['name']} strict mode 下 required 必须 == properties keys"
        )


def test_to_openai_tools_non_strict_keeps_business_required():
    tools = to_openai_tools(strict=False)
    type_tool = next(t for t in tools if t["function"]["name"] == "type")
    # 业务上 type.submit 是 optional，非 strict 模式应保留
    assert "submit" not in type_tool["function"]["parameters"]["required"]
    assert "additionalProperties" not in type_tool["function"]["parameters"]
    assert "strict" not in type_tool["function"]


def test_tool_descriptions_non_empty():
    """LLM 调用时缺 description 会大幅降低工具选择准确率。"""
    for s in TOOL_SCHEMAS:
        assert s["description"], f"{s['name']} description 为空"
        assert len(s["description"]) >= 5
