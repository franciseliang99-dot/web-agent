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
    DragAction,
    ExtractAction,
    GotoUrlAction,
    KeyboardShortcutAction,
    PasteAction,
    ScrollAction,
    SwitchTabAction,
    TypeAction,
    UploadAction,
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


def test_goto_url_factory():
    """V0.70.1: goto_url 工厂 — 直连 URL 替代失败 mark click."""
    a = action_from_tool_call("goto_url", {"thought": "mark 49 反复点击无效, 直跳 url-configuration", "url": "https://supabase.com/dashboard/x/auth/url-configuration"})
    assert isinstance(a, GotoUrlAction)
    assert a.thought == "mark 49 反复点击无效, 直跳 url-configuration"
    assert a.url == "https://supabase.com/dashboard/x/auth/url-configuration"
    assert a.type == "goto_url"


def test_goto_url_factory_url_required():
    """V0.70.1: 缺 url 应抛 KeyError (raw["url"] 无 default)."""
    with pytest.raises(KeyError):
        action_from_tool_call("goto_url", {"thought": "缺 url"})


def test_goto_url_action_frozen():
    """V0.70.1: GotoUrlAction frozen — 不可 mutate."""
    a = action_from_tool_call("goto_url", {"thought": "x", "url": "https://example.com/"})
    with pytest.raises(AttributeError):
        a.url = "https://malicious.com/"  # type: ignore[misc]


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


# ---------- V0.23.0: drag / upload factory ----------


def test_drag_factory():
    """V0.23.0: drag 工厂 from/to mark_id."""
    a = action_from_tool_call("drag", {
        "thought": "拖卡到 done 列",
        "from_mark_id": 5,
        "to_mark_id": 12,
    })
    assert isinstance(a, DragAction)
    assert a.from_mark_id == 5
    assert a.to_mark_id == 12
    assert a.type == "drag"


def test_drag_factory_idx_coerce_int():
    """V0.23.0: from/to 容错 LLM 偶尔输 string."""
    a = action_from_tool_call("drag", {
        "thought": "x", "from_mark_id": "3", "to_mark_id": "7",
    })
    assert isinstance(a, DragAction)
    assert a.from_mark_id == 3
    assert a.to_mark_id == 7


def test_upload_factory_paths_list_to_tuple():
    """V0.23.0: upload paths LLM 给 list → factory 转 tuple (frozen dataclass requires hashable)."""
    a = action_from_tool_call("upload", {
        "thought": "传 PDF",
        "mark_id": 8,
        "paths": ["/tmp/foo.pdf", "/tmp/bar.pdf"],
    })
    assert isinstance(a, UploadAction)
    assert a.mark_id == 8
    assert a.paths == ("/tmp/foo.pdf", "/tmp/bar.pdf")
    assert isinstance(a.paths, tuple), "paths 必须是 tuple (frozen+slots dataclass hashable)"


def test_upload_factory_empty_paths_handled():
    """V0.23.0: paths 缺失 / 空 list → 空 tuple (不 raise; 由 actuator/loop ERROR obs 兜底)."""
    a = action_from_tool_call("upload", {"thought": "x", "mark_id": 1, "paths": []})
    assert isinstance(a, UploadAction)
    assert a.paths == ()


def test_upload_factory_paths_string_coerce():
    """V0.23.0: paths 元素 LLM 给 int/Path 等 → str() cast."""
    a = action_from_tool_call("upload", {
        "thought": "x", "mark_id": 1, "paths": ["/tmp/a.txt", 123],
    })
    assert isinstance(a, UploadAction)
    assert a.paths == ("/tmp/a.txt", "123")


def test_drag_action_frozen():
    """V0.23.0: DragAction frozen+slots — 拒 mutate."""
    a = DragAction(thought="x", from_mark_id=1, to_mark_id=2)
    with pytest.raises(AttributeError):
        a.from_mark_id = 99  # type: ignore[misc]
