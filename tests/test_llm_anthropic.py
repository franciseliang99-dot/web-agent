"""anthropic.py 单测 (audit gap 收尾): __init__ env/explicit api_key + base_url 路径。

plan() 真 SDK 调用难 mock (vision + tool_use 复杂结构), 已通过 test_llm_schema.py
的 to_anthropic_tools 间接覆盖工具定义层. 此 file 只测 client 构造路径。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from web_agent.llm.anthropic import DEFAULT_MODEL, AnthropicClient


def test_init_missing_api_key_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicClient()


def test_init_uses_env_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-not-real")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    with patch("web_agent.llm.anthropic.AsyncAnthropic") as fake_anthropic:
        client = AnthropicClient()
    assert client.name == "anthropic"
    assert client.model == DEFAULT_MODEL
    fake_anthropic.assert_called_once()
    kwargs = fake_anthropic.call_args.kwargs
    assert kwargs["api_key"] == "sk-ant-test-fake-not-real"
    assert kwargs["max_retries"] == 4
    assert kwargs["timeout"] == 120.0
    assert "base_url" not in kwargs


def test_init_explicit_api_key_overrides_env(monkeypatch):
    """显式传 api_key 应优先于 env。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")

    with patch("web_agent.llm.anthropic.AsyncAnthropic") as fake_anthropic:
        AnthropicClient(api_key="sk-ant-explicit")
    assert fake_anthropic.call_args.kwargs["api_key"] == "sk-ant-explicit"


def test_init_with_base_url_env(monkeypatch):
    """ANTHROPIC_BASE_URL env 应透传到 SDK (OpenRouter / LiteLLM 代理路径)。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")

    with patch("web_agent.llm.anthropic.AsyncAnthropic") as fake_anthropic:
        AnthropicClient()
    kwargs = fake_anthropic.call_args.kwargs
    assert kwargs["base_url"] == "https://openrouter.ai/api"


def test_init_explicit_base_url_overrides_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://env.example/api")

    with patch("web_agent.llm.anthropic.AsyncAnthropic") as fake_anthropic:
        AnthropicClient(base_url="https://explicit.example/api")
    assert fake_anthropic.call_args.kwargs["base_url"] == "https://explicit.example/api"


def test_init_explicit_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch("web_agent.llm.anthropic.AsyncAnthropic"):
        client = AnthropicClient(model="claude-opus-4-7")
    assert client.model == "claude-opus-4-7"


def test_init_loads_tools(monkeypatch):
    """构造后 _tools 应非空 (5 种 action: click/type/scroll/extract/done)。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch("web_agent.llm.anthropic.AsyncAnthropic"):
        client = AnthropicClient()
    assert isinstance(client._tools, list)
    assert len(client._tools) >= 4  # 至少 click/type/scroll/done; extract 也有


async def test_v042_1_plan_adds_cache_control_to_last_tool(monkeypatch):
    """V0.42.1 D: anthropic plan() 调 messages.create 时 tools[-1] 含 cache_control: ephemeral.

    让 tools schema (~1-2K tok 跨 step 不变) 进入 cache 范围 (cache breakpoint 让前面 system +
    tools 都 cache). image / user_text 每 step 变 cache miss, 不加 breakpoint 防 cache_creation
    1.25× cost.
    """
    from unittest.mock import AsyncMock, MagicMock

    from web_agent.llm.anthropic import AnthropicClient
    from web_agent.perceiver import Mark
    from web_agent.trace import Trace
    from web_agent.types import ClickAction

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch("web_agent.llm.anthropic.AsyncAnthropic") as mock_anthropic:
        # Mock SDK 调 messages.create → 返一个 tool_use response
        mock_resp = MagicMock()
        mock_resp.usage = MagicMock(
            input_tokens=1000, output_tokens=50,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        # tool_use block 返 click action
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.name = "click"
        mock_block.input = {"thought": "x", "mark_id": 1}
        mock_resp.content = [mock_block]
        mock_client = mock_anthropic.return_value
        mock_client.messages.create = AsyncMock(return_value=mock_resp)

        client = AnthropicClient(model="claude-opus-4-7")
        marks = [Mark(id=1, tag="button", role="", text="ok",
                       bbox={"x": 0, "y": 0, "w": 80, "h": 30},
                       input_type="", name="", href="")]
        trace = Trace(task_id="t", goal="g")
        action = await client.plan("g", "fake_b64", marks, trace)
        assert isinstance(action, ClickAction)

        # 验 messages.create 被调 + tools[-1] 含 cache_control
        call_kwargs = mock_client.messages.create.call_args.kwargs
        tools = call_kwargs["tools"]
        assert len(tools) >= 4
        last_tool = tools[-1]
        assert last_tool.get("cache_control") == {"type": "ephemeral"}, (
            f"V0.42.1: tools 末位应含 cache_control, got {last_tool}"
        )
        # 其他 tool 不应有 cache_control (cache breakpoint 单点)
        for t in tools[:-1]:
            assert "cache_control" not in t, f"tools[~last] 不应有 cache_control: {t}"


async def test_v042_1_plan_tools_not_mutated_across_calls(monkeypatch):
    """V0.42.1: 跨多次 plan() 调用, client._tools 原 list 不被 mutate (cache_control 加到 copy).

    防 V0.42.1 实现 mutate self._tools 导致后续 plan() tools[-1] 多次套 cache_control 形 stale
    (Anthropic API 拒重复 cache_control 字段).
    """
    from unittest.mock import AsyncMock, MagicMock

    from web_agent.llm.anthropic import AnthropicClient
    from web_agent.perceiver import Mark
    from web_agent.trace import Trace

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch("web_agent.llm.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_resp = MagicMock()
        mock_resp.usage = MagicMock(
            input_tokens=1000, output_tokens=50,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.name = "done"
        mock_block.input = {"thought": "x", "result": "ok"}
        mock_resp.content = [mock_block]
        mock_anthropic.return_value.messages.create = AsyncMock(return_value=mock_resp)

        client = AnthropicClient(model="claude-opus-4-7")
        marks = [Mark(id=1, tag="button", role="", text="ok",
                       bbox={"x": 0, "y": 0, "w": 80, "h": 30},
                       input_type="", name="", href="")]
        trace = Trace(task_id="t", goal="g")
        # 跑 3 次 plan()
        for _ in range(3):
            await client.plan("g", "fake_b64", marks, trace)
        # client._tools 原 list 末位不应被 mutate
        last_tool_original = client._tools[-1]
        assert "cache_control" not in last_tool_original, (
            f"V0.42.1: client._tools 原 list 末位被 mutate, cross-call 累积 cache_control 风险: "
            f"{last_tool_original}"
        )
