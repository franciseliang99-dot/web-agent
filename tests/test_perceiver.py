"""perceiver 单测: marks_to_text 纯函数 + Mark dataclass 默认值 + SoM JS 字符串 smoke。

填补 audit gap (perceiver.py 之前 0 单测); W5-B Shadow DOM 穿透的 JS 端逻辑无法离线
unit test (需真 browser + shadow DOM fixture), 用 substring smoke 检测关键代码段不被
未来 refactor 误删。
"""

from __future__ import annotations

from web_agent.perceiver import (
    _SOM_INJECT_JS,
    Mark,
    current_screenshot_format,
    current_screenshot_quality,
    marks_to_text,
)


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


# ---------- V0.33.2: SoM lean mode opt-in (WEB_AGENT_SOM_FIELDS=lean) ----------


def test_marks_to_text_default_full_mode_unchanged(monkeypatch):
    """V0.33.2: 缺省 / 任何非 'lean' 值 → full mode 字节级兼容 V0.33.1 (baseline 不破)."""
    monkeypatch.delenv("WEB_AGENT_SOM_FIELDS", raising=False)
    m = Mark(
        id=1, tag="a", role="link", text="Sign in",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        href="https://example.com/login",
    )
    # full: id + tag + role + text + href 全保 (V0.33.1 行为)
    assert marks_to_text([m]) == "[1] <a role=link> 'Sign in' → https://example.com/login"


def test_marks_to_text_lean_drops_href(monkeypatch):
    """V0.33.2 lean: a[href] → URL 砍掉 (典型 long string ~60 char/mark, 是 token 大头)."""
    monkeypatch.setenv("WEB_AGENT_SOM_FIELDS", "lean")
    m = Mark(
        id=1, tag="a", role="link", text="Sign in",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        href="https://example.com/very/long/login/path?utm=foo",
    )
    out = marks_to_text([m])
    assert "→" not in out, f"lean 应砍 href, got {out!r}"
    assert "example.com" not in out


def test_marks_to_text_lean_drops_role_for_semantic_tags(monkeypatch):
    """V0.33.2 lean: button/a/input 等 tag 自带语义, role 重复字段砍掉."""
    monkeypatch.setenv("WEB_AGENT_SOM_FIELDS", "lean")
    m = Mark(
        id=1, tag="button", role="button", text="Submit",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
    )
    assert marks_to_text([m]) == "[1] <button> 'Submit'"


def test_marks_to_text_lean_keeps_role_for_generic_tags(monkeypatch):
    """V0.33.2 lean: div/span/li 等 generic tag 必须保 role (语义全靠 aria role 撑).

    实际场景: SPA `<div role=tab>Profile</div>` 是 tab 控件, 砍 role 后 LLM 看到 `<div>` 不知是 tab.
    """
    monkeypatch.setenv("WEB_AGENT_SOM_FIELDS", "lean")
    cases = [
        (Mark(id=1, tag="div", role="tab", text="Profile",
              bbox={"x": 0, "y": 0, "w": 1, "h": 1}),
         "[1] <div role=tab> 'Profile'"),
        (Mark(id=2, tag="span", role="button", text="More",
              bbox={"x": 0, "y": 0, "w": 1, "h": 1}),
         "[2] <span role=button> 'More'"),
        (Mark(id=3, tag="li", role="menuitem", text="Settings",
              bbox={"x": 0, "y": 0, "w": 1, "h": 1}),
         "[3] <li role=menuitem> 'Settings'"),
    ]
    for m, expected in cases:
        assert marks_to_text([m]) == expected, f"{m.tag} role={m.role} 应保 role"


def test_marks_to_text_lean_keeps_id_tag_text_frame(monkeypatch):
    """V0.33.2 lean: id / tag / text / frame_path 必留 (LLM click 引 id, frame_path 跨 frame 必须)."""
    monkeypatch.setenv("WEB_AGENT_SOM_FIELDS", "lean")
    m = Mark(
        id=42, tag="button", role="button", text="Pay",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        frame_path="0.2",
    )
    out = marks_to_text([m])
    assert "[42]" in out, "id 必留"
    assert "<button>" in out, "tag 必留"
    assert "'Pay'" in out, "text 必留"
    assert "@0.2" in out, "frame_path 必留 (跨 frame 路由)"


def test_marks_to_text_lean_invalid_value_falls_back_to_full(monkeypatch):
    """V0.33.2: env 任何非 'lean' (含拼错 'leann' / 空 / 'true') → 走 full, 不要静默 lean."""
    for val in ("leann", "true", "1", "yes", "", "FULL"):
        monkeypatch.setenv("WEB_AGENT_SOM_FIELDS", val)
        m = Mark(
            id=1, tag="a", role="link", text="x",
            bbox={"x": 0, "y": 0, "w": 1, "h": 1},
            href="https://x/y",
        )
        out = marks_to_text([m])
        assert "→" in out, f"非 'lean' 值 {val!r} 应 full, got {out!r}"


def test_marks_to_text_lean_case_insensitive(monkeypatch):
    """V0.33.2: 'LEAN' / 'Lean' / 大小写混合都视 lean (跟 V0.30 _normalize_provider 同 strip().lower() pattern)."""
    for val in ("lean", "LEAN", "Lean", "  lean  "):
        monkeypatch.setenv("WEB_AGENT_SOM_FIELDS", val)
        m = Mark(
            id=1, tag="a", role="link", text="x",
            bbox={"x": 0, "y": 0, "w": 1, "h": 1},
            href="https://x/y",
        )
        out = marks_to_text([m])
        assert "→" not in out, f"{val!r} 应 lean, got {out!r}"


# ---------- V0.33.3: screenshot WebP opt-in (WEB_AGENT_SCREENSHOT_FORMAT=webp) ----------


def test_screenshot_format_default_png(monkeypatch):
    """V0.33.3: 缺省 → png (兼容 V0.33.2 baseline 字节级)."""
    monkeypatch.delenv("WEB_AGENT_SCREENSHOT_FORMAT", raising=False)
    assert current_screenshot_format() == "png"


def test_screenshot_format_webp_explicit(monkeypatch):
    """V0.33.3: env=webp → "webp" (case-insensitive + strip)."""
    for val in ("webp", "WEBP", "WebP", "  webp  "):
        monkeypatch.setenv("WEB_AGENT_SCREENSHOT_FORMAT", val)
        assert current_screenshot_format() == "webp", f"{val!r} 应 webp"


def test_screenshot_format_invalid_falls_back_to_png(monkeypatch):
    """V0.33.3: 非 'webp' 值 (jpeg/avif/拼错/空) 全 fallback png — 不静默 webp."""
    for val in ("jpeg", "jpg", "avif", "wepb", "true", "1", ""):
        monkeypatch.setenv("WEB_AGENT_SCREENSHOT_FORMAT", val)
        assert current_screenshot_format() == "png", f"{val!r} 应 fallback png"


def test_screenshot_quality_default_75(monkeypatch):
    """V0.33.3: 默 75 (WebP sweet spot — SoM 数字仍清, byte 减 ~70%)."""
    monkeypatch.delenv("WEB_AGENT_SCREENSHOT_QUALITY", raising=False)
    assert current_screenshot_quality() == 75


def test_screenshot_quality_valid_range(monkeypatch):
    """V0.33.3: 1-100 valid."""
    for val in ("1", "50", "75", "100"):
        monkeypatch.setenv("WEB_AGENT_SCREENSHOT_QUALITY", val)
        assert current_screenshot_quality() == int(val)


def test_screenshot_quality_out_of_range_falls_back(monkeypatch):
    """V0.33.3: <1 或 >100 → 75 fallback (silent clamp 比 raise 更友好, env 配置错不该挂掉 task)."""
    for val in ("0", "-1", "101", "9999"):
        monkeypatch.setenv("WEB_AGENT_SCREENSHOT_QUALITY", val)
        assert current_screenshot_quality() == 75, f"{val!r} 应 fallback 75"


def test_screenshot_quality_non_int_falls_back(monkeypatch):
    """V0.33.3: 非整数 (浮点 / 字符串) → 75 fallback."""
    for val in ("75.5", "high", "", "abc"):
        monkeypatch.setenv("WEB_AGENT_SCREENSHOT_QUALITY", val)
        assert current_screenshot_quality() == 75


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


def _mk_page(main_frame):
    """V0.65.0: 构 fake Page. CDP raw 替 page.screenshot, mock new_cdp_session 链.

    fake CDP session: send 返 base64 ("iVBORw0KGgo=" 是 8-byte PNG signature 编码), detach
    保 try/finally close 路径不抛.
    """
    from unittest.mock import AsyncMock, MagicMock
    page = MagicMock()
    page.main_frame = main_frame
    page.evaluate = AsyncMock(return_value=[])  # auto-dismiss empty
    cdp = AsyncMock()
    cdp.send = AsyncMock(return_value={"data": "iVBORw0KGgo="})
    cdp.detach = AsyncMock()
    page.context.new_cdp_session = AsyncMock(return_value=cdp)
    return page


async def test_perceive_main_frame_only_no_iframes():
    """V0.22.1: 无 iframe → 行为等价 V0.22.0 (主 frame 1 次注入, 全 frame_path='')."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import perceive
    main_frame = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 2), None])
    page = _mk_page(main_frame)
    marks, _, _ = await perceive(page)
    assert len(marks) == 2
    assert all(m.frame_path == "" for m in marks)
    assert [m.id for m in marks] == [1, 2]


async def test_perceive_iframe_dfs_id_offset_continuous():
    """V0.34.4: 主 frame 2 marks + iframe 3 marks (local id 1..3) → Python renumber 全局 1..5.

    V0.22.1 用 id_offset 在 JS 内加 → V0.34.4 改各 frame inject id_offset=0 局部 id,
    Python 端 DFS 顺序拼后 renumber, 各 frame 跑 RENUMBER_JS 修 DOM data-som-id 一致.
    """
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import _SOM_INJECT_JS, _SOM_RENUMBER_JS, perceive
    iframe = _mk_frame(
        child_frames=[],
        # V0.34.4: child id_offset=0 → JS 返 local id 1..3 (mock 直接给 local)
        evaluate_returns=[_mk_raw(1, 3, tag="input"), None, None],  # INJECT, RENUMBER, REMOVE
        url="about:srcdoc",
    )
    main_frame = _mk_frame(
        child_frames=[iframe],
        evaluate_returns=[_mk_raw(1, 2), None, None],  # INJECT, RENUMBER, REMOVE
    )
    page = _mk_page(main_frame)
    marks, _, _ = await perceive(page)
    # Python renumber 后全局 id 1..5 DFS 顺序 (主 1..2 + child local 1..3 → renumber 3..5)
    assert [m.id for m in marks] == [1, 2, 3, 4, 5]
    assert [m.frame_path for m in marks] == ["", "", "0", "0", "0"]
    # V0.34.4 iframe inject 用 id_offset=0 (各 frame 局部 id, 不是 V0.22.1 global offset)
    inject_call = iframe.evaluate.call_args_list[0]
    assert inject_call.args[0] == _SOM_INJECT_JS
    assert inject_call.args[1]["id_offset"] == 0
    # V0.34.4 第 2 调用 RENUMBER_JS, id_map dict[str, int] (JS object key 必须 str)
    renumber_call = iframe.evaluate.call_args_list[1]
    assert renumber_call.args[0] == _SOM_RENUMBER_JS
    assert renumber_call.args[1]["id_map"] == {"1": 3, "2": 4, "3": 5}


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
    page = _mk_page(main_frame)
    marks, _, _ = await perceive(page)
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
    page = _mk_page(main_frame)
    import pytest
    with pytest.raises(RuntimeError, match="main frame crashed"):
        _ = await perceive(page)


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


async def test_perceive_returns_three_tuple_with_cross_origin_hosts():
    """V0.22.4: perceive() 返 (marks, screenshot, cross_origin_hosts) 三-tuple. 无跨域时空 list."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import perceive
    main_frame = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 1), None])
    page = _mk_page(main_frame)
    result = await perceive(page)
    assert len(result) == 3, f"V0.22.4: perceive 必须返三-tuple; got len={len(result)}"
    marks, _, hosts = result
    assert hosts == [], f"无跨域时 hosts 应空; got {hosts}"


async def test_perceive_collects_cross_origin_host_from_url():
    """V0.22.4: child frame.evaluate raise + url 含 host → cross_origin_hosts 含 netloc."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import perceive
    cross_origin = _mk_frame(
        child_frames=[],
        evaluate_raises=RuntimeError("Frame is cross-origin"),
        url="https://www.google.com/recaptcha/api2/anchor?k=abc",
    )
    main_frame = _mk_frame(
        child_frames=[cross_origin],
        evaluate_returns=[_mk_raw(1, 1), None],
    )
    page = _mk_page(main_frame)
    _, _, hosts = await perceive(page)
    assert hosts == ["www.google.com"], f"应收集 netloc; got {hosts}"


async def test_perceive_dedupes_repeated_cross_origin_hosts_dfs_order():
    """V0.22.4: 同 host 多 iframe (e.g. 多 reCAPTCHA) → dict.fromkeys 保 DFS 顺序去重."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import perceive
    a1 = _mk_frame(child_frames=[], evaluate_raises=RuntimeError("x"), url="https://a.example/1")
    b = _mk_frame(child_frames=[], evaluate_raises=RuntimeError("x"), url="https://b.example/")
    a2 = _mk_frame(child_frames=[], evaluate_raises=RuntimeError("x"), url="https://a.example/2")
    main_frame = _mk_frame(
        child_frames=[a1, b, a2],
        evaluate_returns=[_mk_raw(1, 1), None],
    )
    page = _mk_page(main_frame)
    _, _, hosts = await perceive(page)
    assert hosts == ["a.example", "b.example"], (
        f"DFS 顺序去重: a 先于 b, a 第二次 skip; got {hosts}"
    )


async def test_perceive_cross_origin_url_fallback_to_url_when_no_netloc():
    """V0.22.4: about:blank / data: 无 netloc → fallback url[:60]."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.perceiver import perceive
    weird = _mk_frame(
        child_frames=[],
        evaluate_raises=RuntimeError("blocked"),
        url="data:text/html,<html></html>",
    )
    main_frame = _mk_frame(
        child_frames=[weird],
        evaluate_returns=[_mk_raw(1, 1), None],
    )
    page = _mk_page(main_frame)
    _, _, hosts = await perceive(page)
    assert hosts and hosts[0].startswith("data:"), (
        f"无 netloc 应 fallback url 原串; got {hosts}"
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
    page = _mk_page(main_frame)
    marks, _, _ = await perceive(page)
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
