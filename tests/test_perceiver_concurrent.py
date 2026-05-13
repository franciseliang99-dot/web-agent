"""V0.34.4 F1 单元测: iframe DFS asyncio.gather 同层 sibling 并发 + RENUMBER_JS 修 DOM.

覆盖 V0.34.4 新行为, 不重测 V0.22.1 顺序 walker (那些在 test_perceiver.py).
- 主 frame only (无 child): RENUMBER_JS 仍调 1 次 (id_map identity)
- 单 child linear: id renumber DFS 顺序 + RENUMBER call args 正确
- 3 sibling fan-out: gather 保 DFS 顺序 + id 全局连续
- 1 child raise (跨域): hosts 含 host, 子树整 skip, 主+其他 marks 不丢
- 嵌套 fan-out 树: 主 + 2 sibling × (1 + 2 grand-child) → DFS 顺序 13 id
- RENUMBER_JS 入参格式: id_map dict[str, int] (JS object key 必须 str)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from web_agent.perceiver import _SOM_INJECT_JS, _SOM_RENUMBER_JS, perceive


def _mk_raw(start: int, n: int, tag: str = "button") -> list[dict]:
    """模拟 SoM JS evaluate 返回的 raw dict 列表 (V0.34.4 各 frame local id)."""
    return [
        {
            "id": start + i, "tag": tag, "role": "", "text": f"el-{start + i}",
            "bbox": {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0},
            "input_type": "", "name": "", "href": "",
        }
        for i in range(n)
    ]


def _mk_frame(
    child_frames: list | None = None,
    evaluate_returns: list | None = None,
    evaluate_raises: Exception | None = None,
    url: str = "",
) -> AsyncMock:
    """构 fake Frame: evaluate 按调用顺序返预设 (INJECT/RENUMBER/REMOVE), child_frames 列表."""
    frame = AsyncMock()
    frame.url = url
    frame.child_frames = child_frames or []
    if evaluate_raises is not None:
        frame.evaluate.side_effect = evaluate_raises
    elif evaluate_returns is not None:
        frame.evaluate.side_effect = evaluate_returns
    frame.wait_for_load_state = AsyncMock()
    return frame


def _mk_page(main_frame: AsyncMock) -> MagicMock:
    """V0.65.0: 构 fake Page. CDP raw 替 page.screenshot, mock new_cdp_session 链."""
    page = MagicMock()
    page.main_frame = main_frame
    page.evaluate = AsyncMock(return_value=[])  # auto-dismiss empty
    cdp = AsyncMock()
    cdp.send = AsyncMock(return_value={"data": "iVBORw0KGgo="})
    cdp.detach = AsyncMock()
    page.context.new_cdp_session = AsyncMock(return_value=cdp)
    return page


async def test_perceive_main_only_renumber_identity_map() -> None:
    """V0.34.4 主 frame only: RENUMBER_JS 仍调 1 次, id_map 是 identity {'1':1, '2':2}."""
    main = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 2), None, None])
    marks, _, hosts = await perceive(_mk_page(main))

    assert [m.id for m in marks] == [1, 2]
    assert hosts == []
    # 主 frame.evaluate 3 调用: INJECT, RENUMBER, REMOVE
    assert main.evaluate.call_count == 3
    inject_call = main.evaluate.call_args_list[0]
    assert inject_call.args[0] == _SOM_INJECT_JS
    assert inject_call.args[1]["id_offset"] == 0
    renumber_call = main.evaluate.call_args_list[1]
    assert renumber_call.args[0] == _SOM_RENUMBER_JS
    assert renumber_call.args[1]["id_map"] == {"1": 1, "2": 2}  # identity


async def test_perceive_three_sibling_fanout_renumber_dfs_order() -> None:
    """V0.34.4 fan-out: 主 1 mark + 3 sibling 各 2 mark → 全局 id 1..7 DFS 顺序.

    各 sibling 内部 local id 1..2 → renumber 后 sib0 → 2,3; sib1 → 4,5; sib2 → 6,7.
    """
    sib0 = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 2), None, None], url="about:srcdoc")
    sib1 = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 2), None, None], url="about:srcdoc")
    sib2 = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 2), None, None], url="about:srcdoc")
    main = _mk_frame(
        child_frames=[sib0, sib1, sib2],
        evaluate_returns=[_mk_raw(1, 1), None, None],
    )

    marks, _, _ = await perceive(_mk_page(main))

    # DFS 顺序: 主 1 + sib0(2,3) + sib1(4,5) + sib2(6,7) = 7 marks
    assert [m.id for m in marks] == [1, 2, 3, 4, 5, 6, 7]
    assert [m.frame_path for m in marks] == ["", "0", "0", "1", "1", "2", "2"]

    # 各 sibling RENUMBER id_map 正确
    assert sib0.evaluate.call_args_list[1].args[1]["id_map"] == {"1": 2, "2": 3}
    assert sib1.evaluate.call_args_list[1].args[1]["id_map"] == {"1": 4, "2": 5}
    assert sib2.evaluate.call_args_list[1].args[1]["id_map"] == {"1": 6, "2": 7}


async def test_perceive_one_sibling_raises_skipped_subtree() -> None:
    """V0.34.4: 3 sibling 中第 2 个 raise (跨域) → 子树整跳, 其他 sibling marks 不丢, host 列入."""
    sib0 = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 1), None, None], url="about:srcdoc")
    cross = _mk_frame(
        child_frames=[],
        evaluate_raises=RuntimeError("Frame is cross-origin"),
        url="https://attacker.example/widget",
    )
    sib2 = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 1), None, None], url="about:srcdoc")
    main = _mk_frame(
        child_frames=[sib0, cross, sib2],
        evaluate_returns=[_mk_raw(1, 1), None, None],
    )

    marks, _, hosts = await perceive(_mk_page(main))

    # 主 1 + sib0 1 + (cross skip) + sib2 1 = 3 marks, id 全局连续 1..3
    assert [m.id for m in marks] == [1, 2, 3]
    assert [m.frame_path for m in marks] == ["", "0", "2"]
    # 跨域 host 收集 (V0.22.4 contract)
    assert "attacker.example" in hosts


async def test_perceive_nested_fanout_tree_renumber_dfs() -> None:
    """V0.34.4: 2 层 fan-out 树: 主 1 + 2 sibling × (1 mark + 2 grand-child × 1 mark) = 主 + sib(1+2) × 2 = 1 + 6 = 7.

    DFS: 主 → sib0(local) → sib0.gc0 → sib0.gc1 → sib1(local) → sib1.gc0 → sib1.gc1.
    """
    sib0_gc0 = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 1), None, None], url="about:srcdoc")
    sib0_gc1 = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 1), None, None], url="about:srcdoc")
    sib0 = _mk_frame(
        child_frames=[sib0_gc0, sib0_gc1],
        evaluate_returns=[_mk_raw(1, 1), None, None],
        url="about:srcdoc",
    )
    sib1_gc0 = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 1), None, None], url="about:srcdoc")
    sib1_gc1 = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 1), None, None], url="about:srcdoc")
    sib1 = _mk_frame(
        child_frames=[sib1_gc0, sib1_gc1],
        evaluate_returns=[_mk_raw(1, 1), None, None],
        url="about:srcdoc",
    )
    main = _mk_frame(
        child_frames=[sib0, sib1],
        evaluate_returns=[_mk_raw(1, 1), None, None],
    )

    marks, _, _ = await perceive(_mk_page(main))

    # DFS 7 marks, 全局 id 1..7
    assert [m.id for m in marks] == [1, 2, 3, 4, 5, 6, 7]
    # frame_path DFS 顺序
    assert [m.frame_path for m in marks] == ["", "0", "0.0", "0.1", "1", "1.0", "1.1"]


async def test_perceive_renumber_js_id_map_keys_are_str() -> None:
    """V0.34.4 RENUMBER_JS 入参 id_map dict key 必须 str (JS object key 自动 str).

    Python end 端用 dict[str, int] 不是 dict[int, int], 避免 JS 端类型推断错.
    """
    sib = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 1), None, None], url="about:srcdoc")
    main = _mk_frame(child_frames=[sib], evaluate_returns=[_mk_raw(1, 1), None, None])

    await perceive(_mk_page(main))

    # 主 + sibling 各 RENUMBER 调用 id_map keys 都是 str
    main_renumber = main.evaluate.call_args_list[1]
    assert all(isinstance(k, str) for k in main_renumber.args[1]["id_map"])
    sib_renumber = sib.evaluate.call_args_list[1]
    assert all(isinstance(k, str) for k in sib_renumber.args[1]["id_map"])


async def test_perceive_renumber_js_includes_shadow_param() -> None:
    """V0.34.4 RENUMBER_JS 入参含 'shadow' bool (跟 INJECT 同 SHADOW_ON 模式, 穿透 open shadowRoot)."""
    main = _mk_frame(child_frames=[], evaluate_returns=[_mk_raw(1, 1), None, None])

    await perceive(_mk_page(main))

    renumber_call = main.evaluate.call_args_list[1]
    assert "shadow" in renumber_call.args[1]
    # 默 WEB_AGENT_SOM_SHADOW=true → shadow_on=True
    assert renumber_call.args[1]["shadow"] is True
