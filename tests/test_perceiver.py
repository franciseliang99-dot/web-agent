"""perceiver 单测: marks_to_text 纯函数 + Mark dataclass 默认值 + SoM JS 字符串 smoke。

填补 audit gap (perceiver.py 之前 0 单测); W5-B Shadow DOM 穿透的 JS 端逻辑无法离线
unit test (需真 browser + shadow DOM fixture), 用 substring smoke 检测关键代码段不被
未来 refactor 误删。
"""

from __future__ import annotations

from web_agent.perceiver import _SOM_INJECT_JS, Mark, marks_to_text


def _mk(id_: int, tag: str = "button", role: str = "", text: str = "") -> Mark:
    return Mark(
        id=id_, tag=tag, role=role, text=text,
        bbox={"x": 0, "y": 0, "w": 80, "h": 30},
    )


# ---------- marks_to_text 纯函数 ----------

def test_marks_to_text_empty_list():
    assert marks_to_text([]) == ""


def test_marks_to_text_single_no_role_no_text():
    assert marks_to_text([_mk(1)]) == "[1] <button>"


def test_marks_to_text_with_role():
    assert marks_to_text([_mk(1, role="button")]) == "[1] <button role=button>"


def test_marks_to_text_with_text():
    assert marks_to_text([_mk(1, text="Submit")]) == "[1] <button> 'Submit'"


def test_marks_to_text_with_role_and_text():
    out = marks_to_text([_mk(1, role="button", text="Submit")])
    assert out == "[1] <button role=button> 'Submit'"


def test_marks_to_text_multiple_marks_joined_by_newline():
    marks = [_mk(1, text="Search"), _mk(2, tag="a", text="Help")]
    out = marks_to_text(marks)
    assert out == "[1] <button> 'Search'\n[2] <a> 'Help'"


def test_marks_to_text_chinese_text():
    out = marks_to_text([_mk(1, text="发送")])
    assert "发送" in out
    assert out == "[1] <button> '发送'"


# ---------- Mark dataclass 字段 ----------

def test_mark_dataclass_minimum_defaults():
    """V0.6.0 schema: input_type/name/href 默认空字符串 (旧测兼容)。"""
    m = Mark(id=1, tag="a", role="", text="", bbox={"x": 0, "y": 0, "w": 1, "h": 1})
    assert m.input_type == ""
    assert m.name == ""
    assert m.href == ""


def test_mark_dataclass_full_fields():
    m = Mark(
        id=2, tag="input", role="textbox", text="",
        bbox={"x": 10, "y": 20, "w": 100, "h": 30},
        input_type="password", name="pwd", href="",
    )
    assert m.input_type == "password"
    assert m.name == "pwd"
    assert m.href == ""


# ---------- V0.22.0: frame_path 字段 + marks_to_text @path 后缀 ----------


def test_mark_frame_path_default_empty():
    """V0.22.0: 新增 frame_path 默认 "" 兼容旧 fixture (8+ Mark() 调用不带 kwarg)."""
    m = Mark(id=1, tag="button", role="", text="", bbox={"x": 0, "y": 0, "w": 1, "h": 1})
    assert m.frame_path == ""


def test_mark_frame_path_explicit():
    """V0.22.0: iframe 内 mark 用 frame_path 标深度优先索引路径."""
    m = Mark(
        id=5, tag="input", role="", text="",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        frame_path="0.2",
    )
    assert m.frame_path == "0.2"


def test_marks_to_text_empty_frame_path_no_suffix():
    """V0.22.0: 主 frame mark (frame_path="") 不加 @后缀, 保持 V0.21.x 输出兼容."""
    out = marks_to_text([_mk(1, text="Click")])
    assert "@" not in out


def test_marks_to_text_iframe_path_appends_suffix():
    """V0.22.0: iframe 内 mark 末尾加 @<frame_path> 让 LLM 知道路径."""
    m = Mark(
        id=3, tag="button", role="", text="Pay",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        frame_path="0",
    )
    out = marks_to_text([m])
    assert out.endswith(" @0"), f"应以 @0 结尾, got {out!r}"


def test_marks_to_text_iframe_path_after_href():
    """V0.22.0: 输出顺序 text → href → @frame_path (href 先 frame_path 后)."""
    m = Mark(
        id=4, tag="a", role="", text="link",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        href="https://x.test/y", frame_path="0.1",
    )
    out = marks_to_text([m])
    assert "→ https://x.test/y" in out
    assert out.endswith(" @0.1")
    assert out.index("→") < out.index("@")


# ---------- V0.22.1: perceive() iframe DFS + id_offset + 跨域 catch ----------


def _mk_raw(start: int, n: int, tag: str = "button") -> list[dict]:
    """模拟 SoM JS evaluate 返回的 raw dict 列表 (含 id 已加 offset)."""
    return [
        {
            "id": start + i, "tag": tag, "role": "", "text": f"el-{start + i}",
            "bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
            "input_type": "", "name": "", "href": "",
        }
        for i in range(n)
    ]


def _mk_frame(child_frames=None, evaluate_returns=None, evaluate_raises=None, url: str = ""):
    """构 fake Frame: evaluate 按调用顺序返预设, child_frames 列表."""
    from unittest.mock import AsyncMock
    frame = AsyncMock()
    frame.url = url
    frame.child_frames = child_frames or []
    if evaluate_raises is not None:
        frame.evaluate.side_effect = evaluate_raises
    elif evaluate_returns is not None:
        frame.evaluate.side_effect = evaluate_returns
    frame.wait_for_load_state = AsyncMock()
    return frame


async def test_perceive_main_frame_only_no_iframes():
    """V0.22.1: 无 iframe → 行为等价 V0.22.0 (主 frame 1 次注入, 全 frame_path='')."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import perceive
    main_frame = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 2), None])
    page = MagicMock()
    page.main_frame = main_frame
    page.evaluate = AsyncMock(return_value=[])  # auto-dismiss
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    marks, _ = await perceive(page)
    assert len(marks) == 2
    assert all(m.frame_path == "" for m in marks)
    assert [m.id for m in marks] == [1, 2]


async def test_perceive_iframe_dfs_id_offset_continuous():
    """V0.22.1: 主 frame 2 marks + iframe 3 marks → id 全局连续 1-5, frame_path='' / '0'.

    关键: iframe.evaluate 被调用时 opts 含 id_offset=2 (主 frame 已用 id 1-2).
    """
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import _SOM_INJECT_JS, perceive
    iframe = _mk_frame(
        child_frames=[],
        evaluate_returns=[_mk_raw(3, 3, tag="input"), None],  # id 3,4,5 (offset=2 → JS 内 +2)
        url="about:srcdoc",
    )
    main_frame = _mk_frame(
        child_frames=[iframe],
        evaluate_returns=[_mk_raw(1, 2), None],
    )
    page = MagicMock()
    page.main_frame = main_frame
    page.evaluate = AsyncMock(return_value=[])
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    marks, _ = await perceive(page)
    assert [m.id for m in marks] == [1, 2, 3, 4, 5]
    assert [m.frame_path for m in marks] == ["", "", "0", "0", "0"]
    # iframe.evaluate 第 1 调用 (SoM inject) opts 含 id_offset=2
    inject_call = iframe.evaluate.call_args_list[0]
    assert inject_call.args[0] == _SOM_INJECT_JS
    assert inject_call.args[1]["id_offset"] == 2


async def test_perceive_cross_origin_iframe_skipped_main_continues():
    """V0.22.1: child frame.evaluate 抛 (跨域 / detached) → warn skip 子树, 主 marks 不丢."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import perceive
    cross_origin = _mk_frame(
        child_frames=[],
        evaluate_raises=RuntimeError("Frame is cross-origin"),
        url="https://other.example/widget",
    )
    main_frame = _mk_frame(
        child_frames=[cross_origin],
        evaluate_returns=[_mk_raw(1, 2), None],
    )
    page = MagicMock()
    page.main_frame = main_frame
    page.evaluate = AsyncMock(return_value=[])
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    marks, _ = await perceive(page)
    # 主 2 marks 仍在; 跨域 0 marks; 不抛
    assert len(marks) == 2
    assert all(m.frame_path == "" for m in marks)


async def test_perceive_main_frame_evaluate_failure_propagates():
    """V0.22.1: 主 frame fail = 致命 (silent 空 marks 会让 loop 死循环), 不 catch 透抛."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import perceive
    main_frame = _mk_frame(
        child_frames=[],
        evaluate_raises=RuntimeError("main frame crashed"),
    )
    page = MagicMock()
    page.main_frame = main_frame
    page.evaluate = AsyncMock(return_value=[])
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    import pytest
    with pytest.raises(RuntimeError, match="main frame crashed"):
        await perceive(page)


def test_som_inject_js_sets_data_som_id_attribute():
    """V0.22.2: SoM inject JS 给元素挂 data-som-id 让 actuator 走 frame.locator 选."""
    from web_agent.perceiver import _SOM_INJECT_JS
    assert "setAttribute('data-som-id'" in _SOM_INJECT_JS, (
        "V0.22.2: 注入时必须挂 data-som-id (actuator iframe 路径靠它选)"
    )


def test_som_inject_js_cleans_old_data_som_id_at_entry():
    """V0.22.2 真 chromium 实测: data-som-id cleanup 必须在 inject 入口而不在 REMOVE.

    原 sanity D 推荐 REMOVE 清 data-som-id, 但实测发现 perceive() 末尾 REMOVE 后 actuator
    用 frame.locator([data-som-id]) 找不到元素 (Locator.click timeout). 改在 inject 入口清旧
    + 末尾 REMOVE 不清 → agent 跑期间 data-som-id 持续可用, agent 退出关 Chrome 自动清.
    """
    from web_agent.perceiver import _SOM_INJECT_JS, _SOM_REMOVE_JS
    # inject 入口必须清旧 data-som-id (含 shadow walker)
    assert "removeAttribute('data-som-id')" in _SOM_INJECT_JS, (
        "V0.22.2: inject 入口必须清旧 data-som-id (上次残留)"
    )
    # REMOVE 故意不清 data-som-id (留给 actuator); 注释里可能含 "data-som-id" 字样,
    # 用更精确的 removeAttribute('data-som-id') 反查防误判
    assert "removeAttribute('data-som-id')" not in _SOM_REMOVE_JS, (
        "V0.22.2 实测修正: REMOVE 不能 removeAttribute(data-som-id) 否则 actuator 找不到元素"
    )


async def test_perceive_nested_iframe_path_encoding():
    """V0.22.1: 主 → iframe[0] → iframe[1] 的嵌套 → frame_path 编码 '0.1'."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import perceive
    inner = _mk_frame(
        child_frames=[],
        evaluate_returns=[_mk_raw(3, 1), None],
    )
    middle = _mk_frame(
        # middle frame 自己 0 marks + 含 child[0]=skipped + child[1]=inner
        child_frames=[
            _mk_frame(  # child[0] 跨域跳过
                child_frames=[],
                evaluate_raises=RuntimeError("cross-origin"),
            ),
            inner,
        ],
        evaluate_returns=[_mk_raw(2, 1), None],
    )
    main_frame = _mk_frame(
        child_frames=[middle],
        evaluate_returns=[_mk_raw(1, 1), None],
    )
    page = MagicMock()
    page.main_frame = main_frame
    page.evaluate = AsyncMock(return_value=[])
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    marks, _ = await perceive(page)
    assert [m.frame_path for m in marks] == ["", "0", "0.1"]
    assert [m.id for m in marks] == [1, 2, 3]


# ---------- _SOM_INJECT_JS smoke (W5-B 穿透代码段不被误删) ----------

def test_som_inject_js_has_shadow_root_walker():
    """关键词 shadowRoot + open + visited 共现 → 穿透代码段在位。"""
    js = _SOM_INJECT_JS
    assert "shadowRoot" in js, "缺 shadowRoot walker"
    assert "open" in js, "缺 open mode 检查 (closed shadow 不应被穿透)"
    assert "visited" in js, "缺 visited 防自引用 dedup"


def test_som_inject_js_accepts_opts_arg():
    """JS 函数签名应接收 opts 参数 (env opt-out 路径)。"""
    js = _SOM_INJECT_JS
    assert "(opts)" in js
    assert "opts.shadow" in js


def test_som_inject_js_keeps_visibility_filter():
    """穿透不应破坏现有 visibility 过滤 (W5-B refactor 不改 V0.11.1 行为)。"""
    js = _SOM_INJECT_JS
    assert "getBoundingClientRect" in js
    assert "visibility" in js
    assert "display" in js
