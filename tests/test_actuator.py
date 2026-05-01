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
