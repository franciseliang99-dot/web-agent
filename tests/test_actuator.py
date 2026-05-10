"""actuator W2 单测：纯函数 _click_point / _bezier_path / _type_delay。

page-aware 函数（human_like_click / human_like_type / scroll）依赖 Playwright Page，
靠 demo 端到端验证，不写 mock。
"""

from __future__ import annotations

import math
import statistics

from web_agent.actuator import _bezier_path, _click_point, _type_delay
from web_agent.perceiver import Mark


def _mk(x: float, y: float, w: float, h: float) -> Mark:
    return Mark(id=1, tag="button", role="", text="ok", bbox={"x": x, "y": y, "w": w, "h": h})


# --- _click_point ---

def test_click_point_stays_inside_button():
    """正态 + 截断 ±0.45w 保证不出按钮边界。"""
    m = _mk(100, 200, 80, 30)
    for _ in range(300):
        x, y = _click_point(m)
        assert 100 <= x <= 180, f"x={x} 超出按钮 horizontal"
        assert 200 <= y <= 230, f"y={y} 超出按钮 vertical"


def test_click_point_centered_on_average():
    """500 次均值应接近按钮中心（截断正态对称分布）。"""
    m = _mk(0, 0, 100, 100)
    xs, ys = zip(*[_click_point(m) for _ in range(500)])
    assert 48 <= sum(xs) / len(xs) <= 52
    assert 48 <= sum(ys) / len(ys) <= 52


def test_click_point_concentrated_near_center():
    """正态分布让大部分点（>50%）在中心 ±std 内（120x120 button, std=15）。"""
    m = _mk(0, 0, 120, 120)
    xs = [_click_point(m)[0] for _ in range(1000)]
    inside_one_std = sum(1 for x in xs if 45 <= x <= 75)
    assert inside_one_std / 1000 > 0.5, f"只有 {inside_one_std/1000:.1%} 在 ±std 内"


def test_click_point_tiny_button_does_not_crash():
    """1x1 button: std=3 但截断到 ±0.45。"""
    m = _mk(0, 0, 1, 1)
    for _ in range(50):
        x, y = _click_point(m)
        assert 0 <= x <= 1, f"x={x} 超出 1px button"
        assert 0 <= y <= 1, f"y={y} 超出 1px button"


def test_click_point_zero_size_button_does_not_crash():
    """0x0 button: 偏移截断到 0，应永远返回中心。"""
    m = _mk(50, 50, 0, 0)
    for _ in range(20):
        x, y = _click_point(m)
        assert math.isfinite(x) and math.isfinite(y)
        assert abs(x - 50) <= 0.01
        assert abs(y - 50) <= 0.01


def test_click_point_small_button_has_min_std():
    """小按钮 (w=12) std 应 >= 3 (max(3, w/6)=max(3, 2)=3)，让点击有可见离散度。"""
    m = _mk(0, 0, 12, 12)
    xs = [_click_point(m)[0] for _ in range(500)]
    std = statistics.stdev(xs)
    assert std > 1.0, f"小按钮 std={std:.2f} 太集中（应有 >1.0 的离散度）"


# --- _bezier_path ---

def test_bezier_path_step_count():
    points = list(_bezier_path((0.0, 0.0), (100.0, 100.0), steps=20))
    assert len(points) == 20


def test_bezier_path_endpoint_matches():
    """smootherstep 在 t=1 处 == 1，末点必须等于终点。"""
    points = list(_bezier_path((10.0, 20.0), (110.0, 120.0), steps=15))
    last_x, last_y = points[-1]
    assert abs(last_x - 110.0) < 0.5
    assert abs(last_y - 120.0) < 0.5


def test_bezier_path_no_jumps():
    """100px 走 20 步无突跳（smootherstep 中段密集，两端稀疏）。"""
    points = list(_bezier_path((0.0, 0.0), (100.0, 100.0), steps=20))
    for i in range(1, len(points)):
        d = math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
        assert d < 25, f"step {i} 突跳 d={d:.1f}"


def test_bezier_path_zero_distance_corner_case():
    """起点 == 终点不应除零，应返回 N 个相同点。"""
    points = list(_bezier_path((50.0, 50.0), (50.0, 50.0), steps=5))
    assert len(points) == 5
    assert all(p == (50.0, 50.0) for p in points)


def test_bezier_path_smootherstep_starts_slow():
    """smootherstep ease：前 30% 步数走的距离应 < 25% 总距离（开始慢）。"""
    points = list(_bezier_path((0.0, 0.0), (100.0, 0.0), steps=20, jitter=0.0))
    quarter_idx = 6  # 30% of 20
    quarter_x = points[quarter_idx][0]
    assert quarter_x < 30, f"前 30% 走了 {quarter_x:.1f}/100，应 < 30"


def test_bezier_path_x_monotonic_with_zero_jitter():
    """jitter=0 时 x 应严格单调递增（直线）。"""
    points = list(_bezier_path((0.0, 0.0), (100.0, 0.0), steps=20, jitter=0.0))
    for i in range(1, len(points)):
        assert points[i][0] >= points[i - 1][0] - 0.001, (
            f"step {i} x 倒退: {points[i-1][0]:.3f} -> {points[i][0]:.3f}"
        )


# --- _type_delay ---

def test_type_delay_within_truncated_range():
    delays = [_type_delay() for _ in range(500)]
    assert all(0.04 <= d <= 0.30 for d in delays), f"截断违反: min={min(delays)} max={max(delays)}"


def test_type_delay_mean_near_120ms():
    """N(0.12, 0.04) 截断到 [0.04, 0.30] 后均值应仍接近 0.12。"""
    delays = [_type_delay() for _ in range(2000)]
    mean = statistics.mean(delays)
    assert 0.10 <= mean <= 0.14, f"均值偏离 0.12: {mean:.3f}"


# --- V0.22.2 iframe 路径分流 (mock frame.locator) ---


def _mk_iframe_mark(id_: int, frame_path: str = "0") -> Mark:
    return Mark(
        id=id_, tag="button", role="", text="iframe-btn",
        bbox={"x": 0, "y": 0, "w": 50, "h": 20},
        frame_path=frame_path,
    )


async def test_human_like_click_iframe_path_uses_locator():
    """V0.22.2: frame 非 None → 走 frame.locator(...).click() (无贝塞尔), 不调 page.mouse."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import human_like_click
    locator = MagicMock()
    locator.click = AsyncMock()
    frame = MagicMock()
    frame.locator = MagicMock(return_value=locator)
    page = MagicMock()
    page.mouse = MagicMock()  # 不该被调
    page.mouse.move = AsyncMock()
    page.mouse.down = AsyncMock()
    mark = _mk_iframe_mark(7)
    await human_like_click(page, mark, frame=frame)
    frame.locator.assert_called_once_with('[data-som-id="7"]')
    locator.click.assert_awaited_once()
    page.mouse.move.assert_not_called()
    page.mouse.down.assert_not_called()


async def test_human_like_type_iframe_path_uses_press_sequentially():
    """V0.22.2: type frame+mark → frame.locator(...).press_sequentially (Locator.type deprecated)."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import human_like_type
    locator = MagicMock()
    locator.press_sequentially = AsyncMock()
    frame = MagicMock()
    frame.locator = MagicMock(return_value=locator)
    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()  # 不该被调
    mark = _mk_iframe_mark(3)
    await human_like_type(page, "hi", frame=frame, mark=mark)
    frame.locator.assert_called_once_with('[data-som-id="3"]')
    locator.press_sequentially.assert_awaited_once_with("hi", delay=120)
    page.keyboard.type.assert_not_called()


async def test_human_like_keyboard_shortcut_iframe_path_uses_locator_press():
    """V0.22.2: keyboard_shortcut frame+mark → frame.locator(...).press(key) (focus 后按)."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import human_like_keyboard_shortcut
    locator = MagicMock()
    locator.press = AsyncMock()
    frame = MagicMock()
    frame.locator = MagicMock(return_value=locator)
    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()  # 不该被调
    mark = _mk_iframe_mark(5)
    await human_like_keyboard_shortcut(page, "Control+End", frame=frame, mark=mark)
    locator.press.assert_awaited_once_with("Control+End")
    page.keyboard.press.assert_not_called()


async def test_human_like_keyboard_shortcut_iframe_no_mark_falls_back_to_page():
    """V0.22.2: frame 给了但无 mark (LLM 单按 Tab 全局) → 仍走 page.keyboard.press."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import human_like_keyboard_shortcut
    frame = MagicMock()
    frame.locator = MagicMock()
    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    await human_like_keyboard_shortcut(page, "Tab", frame=frame, mark=None)
    page.keyboard.press.assert_awaited_once_with("Tab")
    frame.locator.assert_not_called()


async def test_human_like_paste_iframe_path_uses_frame_evaluate():
    """V0.22.2: paste frame 非 None → frame.evaluate execCommand (跟主 frame 同款)."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import human_like_paste
    frame = MagicMock()
    frame.evaluate = AsyncMock(return_value=True)
    page = MagicMock()
    page.evaluate = AsyncMock()  # 不该被调
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    await human_like_paste(page, "long text", frame=frame, mark=_mk_iframe_mark(1))
    frame.evaluate.assert_awaited_once()
    args = frame.evaluate.call_args
    assert "execCommand" in args.args[0]
    assert args.args[1] == "long text"
    page.evaluate.assert_not_called()


async def test_human_like_click_main_frame_unchanged_when_frame_none():
    """V0.22.2: frame=None → 主 frame 路径 100% 兼容 V0.22.1 (跑 page.mouse 贝塞尔)."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import human_like_click
    page = MagicMock()
    page.evaluate = AsyncMock(return_value={"x": 0, "y": 0})
    page.viewport_size = {"width": 1280, "height": 800}
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.down = AsyncMock()
    page.mouse.up = AsyncMock()
    mark = Mark(id=1, tag="button", role="", text="ok", bbox={"x": 100, "y": 100, "w": 50, "h": 30})
    await human_like_click(page, mark)  # frame 默认 None
    assert page.mouse.move.await_count >= 15  # 贝塞尔轨迹至少 15 步
    page.mouse.down.assert_awaited_once()
    page.mouse.up.assert_awaited_once()


# --- V0.23.1 human_like_drag + upload_file ---


def _mk_xy(id_: int, x: float, y: float) -> Mark:
    return Mark(
        id=id_, tag="div", role="", text=f"el-{id_}",
        bbox={"x": x, "y": y, "w": 30, "h": 30},
    )


async def test_human_like_drag_main_frame_full_sequence():
    """V0.23.1: 主 frame drag = approach moves → mouse.down → drag moves → mouse.up.

    验证 down() 在所有 move 中间; down 之前的 move 是 approach (≥15 步), 之后是拖动 (≥20 步).
    """
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import human_like_drag
    call_order: list[str] = []
    page = MagicMock()
    page.evaluate = AsyncMock(return_value={"x": 0, "y": 0})
    page.viewport_size = {"width": 1280, "height": 800}
    page.mouse = MagicMock()

    async def rec_move(x, y):
        call_order.append("move")

    async def rec_down():
        call_order.append("down")

    async def rec_up():
        call_order.append("up")

    page.mouse.move = AsyncMock(side_effect=rec_move)
    page.mouse.down = AsyncMock(side_effect=rec_down)
    page.mouse.up = AsyncMock(side_effect=rec_up)

    from_m = _mk_xy(1, 100, 100)
    to_m = _mk_xy(2, 600, 400)
    await human_like_drag(page, from_m, to_m)

    assert "down" in call_order, "必须有 mouse.down"
    assert "up" in call_order, "必须有 mouse.up"
    down_idx = call_order.index("down")
    up_idx = call_order.index("up")
    assert down_idx < up_idx, "down 必须在 up 之前"
    pre_moves = call_order[:down_idx].count("move")
    drag_moves = call_order[down_idx + 1:up_idx].count("move")
    assert pre_moves >= 15, f"approach moves 至少 15 步 (V0.23.1 spec); got {pre_moves}"
    assert drag_moves >= 20, f"drag moves 至少 20 步 (V0.23.1 spec); got {drag_moves}"
    page.mouse.down.assert_awaited_once()
    page.mouse.up.assert_awaited_once()


async def test_human_like_drag_iframe_uses_drag_to_locator():
    """V0.23.1: iframe drag → frame.locator(from).drag_to(frame.locator(to))."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import human_like_drag
    from_loc = MagicMock()
    from_loc.drag_to = AsyncMock()
    to_loc = MagicMock()
    frame = MagicMock()
    frame.locator = MagicMock(side_effect=[from_loc, to_loc])
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.down = AsyncMock()
    from_m = Mark(id=3, tag="div", role="", text="", bbox={"x": 0, "y": 0, "w": 1, "h": 1}, frame_path="0")
    to_m = Mark(id=5, tag="div", role="", text="", bbox={"x": 0, "y": 0, "w": 1, "h": 1}, frame_path="0")
    await human_like_drag(page, from_m, to_m, frame=frame)
    assert frame.locator.call_count == 2
    frame.locator.assert_any_call('[data-som-id="3"]')
    frame.locator.assert_any_call('[data-som-id="5"]')
    from_loc.drag_to.assert_awaited_once_with(to_loc)
    page.mouse.move.assert_not_called()  # iframe 路径不走主页面 mouse


async def test_upload_file_input_mark_direct_set_input_files():
    """V0.23.1: mark 是 input[type=file] → 直接 page.locator(...).set_input_files."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import upload_file
    locator = MagicMock()
    locator.set_input_files = AsyncMock()
    page = MagicMock()
    page.locator = MagicMock(return_value=locator)
    page.evaluate = AsyncMock()  # 不该被调
    mark = Mark(
        id=7, tag="input", role="", text="",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        input_type="file",
    )
    await upload_file(page, mark, ("/tmp/a.txt", "/tmp/b.txt"))
    page.locator.assert_called_once_with('[data-som-id="7"]')
    locator.set_input_files.assert_awaited_once_with(["/tmp/a.txt", "/tmp/b.txt"])
    page.evaluate.assert_not_called()  # input 路径不走 DOM walk


async def test_upload_file_button_mark_dom_walk_path():
    """V0.23.1: mark 是 button (非 input/file) → JS DOM walk 找隐藏 input + sentinel locator."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import upload_file
    sentinel_locator = MagicMock()
    sentinel_locator.set_input_files = AsyncMock()
    page = MagicMock()
    page.locator = MagicMock(return_value=sentinel_locator)
    page.evaluate = AsyncMock(return_value="__upload_input_8")
    mark = Mark(
        id=8, tag="button", role="", text="Upload",
        bbox={"x": 0, "y": 0, "w": 80, "h": 30},
    )
    await upload_file(page, mark, ("/tmp/x.png",))
    page.evaluate.assert_awaited_once()
    args = page.evaluate.call_args
    assert "data-upload-target" in args.args[0], "DOM walk JS 必须含 data-upload-target sentinel 注入"
    assert args.args[1] == 8, "JS 接 mark.id 作 somId 参数"
    page.locator.assert_called_once_with('[data-upload-target="__upload_input_8"]')
    sentinel_locator.set_input_files.assert_awaited_once_with(["/tmp/x.png"])


async def test_upload_file_button_dom_walk_returns_null_raises():
    """V0.23.1: DOM walk 找不到 input → RuntimeError (loop dispatch V0.23.2 兜底 ERROR obs)."""
    from unittest.mock import AsyncMock, MagicMock
    import pytest
    from web_agent.actuator import upload_file
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=None)
    mark = Mark(id=9, tag="button", role="", text="x", bbox={"x": 0, "y": 0, "w": 1, "h": 1})
    with pytest.raises(RuntimeError, match="未找到.*关联的 input"):
        await upload_file(page, mark, ("/tmp/a.txt",))


async def test_upload_file_iframe_path_uses_frame_locator():
    """V0.23.1: iframe 内 file input → frame.locator(...).set_input_files (跟主 frame 同 API)."""
    from unittest.mock import AsyncMock, MagicMock
    from web_agent.actuator import upload_file
    locator = MagicMock()
    locator.set_input_files = AsyncMock()
    frame = MagicMock()
    frame.locator = MagicMock(return_value=locator)
    page = MagicMock()
    page.locator = MagicMock()  # 不该被调
    mark = Mark(
        id=4, tag="input", role="", text="",
        bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        input_type="file", frame_path="0",
    )
    await upload_file(page, mark, ("/tmp/y.txt",), frame=frame)
    frame.locator.assert_called_once_with('[data-som-id="4"]')
    locator.set_input_files.assert_awaited_once_with(["/tmp/y.txt"])
    page.locator.assert_not_called()
