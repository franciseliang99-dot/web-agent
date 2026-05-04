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
