"""V0.21.0: action_from_tool_call 工厂测试 (此前无 test_types.py).

7 旧 type 顺带 sanity (factory 单条 dispatch + thought pop 行为) + 2 新 type (switch_tab/close_tab) +
未知 name raise. 不依赖 LLM/Playwright, 纯函数测试.
"""

from __future__ import annotations

import pytest

from web_agent.types import (
    ClickAction,
    CloseTabAction,
    DoneAction,
    ExtractAction,
    KeyboardShortcutAction,
    PasteAction,
    ScrollAction,
    SwitchTabAction,
    TypeAction,
    action_from_tool_call,
)


def test_click_factory():
    a = action_from_tool_call("click", {"thought": "点搜索按钮", "mark_id": 7})
    assert isinstance(a, ClickAction)
    assert a.thought == "点搜索按钮"
    assert a.mark_id == 7
    assert a.type == "click"


def test_type_factory_with_submit_default_false():
    a = action_from_tool_call("type", {"thought": "输入查询", "text": "hello"})
    assert isinstance(a, TypeAction)
    assert a.text == "hello"
    assert a.submit is False


def test_type_factory_with_submit_true():
    a = action_from_tool_call("type", {"thought": "回车提交", "text": "q", "submit": True})
    assert isinstance(a, TypeAction)
    assert a.submit is True


def test_scroll_factory():
    a = action_from_tool_call("scroll", {"thought": "下滚", "dy": 500})
    assert isinstance(a, ScrollAction)
    assert a.dy == 500


def test_extract_factory():
    a = action_from_tool_call(
        "extract",
        {"thought": "读价格", "query": "price", "answer": "$9.99"},
    )
    assert isinstance(a, ExtractAction)
    assert a.query == "price"
    assert a.answer == "$9.99"


def test_done_factory():
    a = action_from_tool_call("done", {"thought": "完成", "result": "ok"})
    assert isinstance(a, DoneAction)
    assert a.result == "ok"


def test_keyboard_shortcut_factory():
    a = action_from_tool_call("keyboard_shortcut", {"thought": "跳末尾", "key": "Control+End"})
    assert isinstance(a, KeyboardShortcutAction)
    assert a.key == "Control+End"


def test_paste_factory():
    a = action_from_tool_call("paste", {"thought": "粘贴长文", "text": "x" * 100})
    assert isinstance(a, PasteAction)
    assert len(a.text) == 100


def test_switch_tab_factory():
    """V0.21.0: switch_tab 工厂."""
    a = action_from_tool_call("switch_tab", {"thought": "切到 GitHub tab", "idx": 2})
    assert isinstance(a, SwitchTabAction)
    assert a.thought == "切到 GitHub tab"
    assert a.idx == 2
    assert a.type == "switch_tab"


def test_switch_tab_idx_coerce_int():
    """V0.21.0: idx 容错 — LLM 偶尔输 string '1' 也接 (int(...) cast)."""
    a = action_from_tool_call("switch_tab", {"thought": "切", "idx": "1"})
    assert isinstance(a, SwitchTabAction)
    assert a.idx == 1


def test_close_tab_factory():
    """V0.21.0: close_tab 工厂."""
    a = action_from_tool_call("close_tab", {"thought": "关掉空白 tab", "idx": 3})
    assert isinstance(a, CloseTabAction)
    assert a.thought == "关掉空白 tab"
    assert a.idx == 3
    assert a.type == "close_tab"


def test_close_tab_idx_coerce_int():
    a = action_from_tool_call("close_tab", {"thought": "关", "idx": "0"})
    assert isinstance(a, CloseTabAction)
    assert a.idx == 0


def test_unknown_tool_name_raises():
    with pytest.raises(RuntimeError, match="unknown tool name"):
        action_from_tool_call("frobnicate", {"thought": "?"})


def test_thought_default_empty_when_missing():
    """raw 不含 thought key 时 factory 用空字符串 (不应抛 KeyError)."""
    a = action_from_tool_call("click", {"mark_id": 1})
    assert isinstance(a, ClickAction)
    assert a.thought == ""


def test_actions_are_frozen():
    """frozen=True dataclass 拒 mutate (防 deque 短期记忆里被改)."""
    a = action_from_tool_call("switch_tab", {"thought": "x", "idx": 0})
    with pytest.raises(AttributeError):
        a.idx = 99  # type: ignore[misc]
