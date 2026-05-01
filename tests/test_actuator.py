"""W1 占位测试：验证 _click_point jitter 落在按钮范围内 + 集中在中心。

真正的端到端测试要等 W2 起 mock Page 后再写。
"""

from __future__ import annotations

from web_agent.actuator import _click_point
from web_agent.perceiver import Mark


def _mk(x: float, y: float, w: float, h: float) -> Mark:
    return Mark(id=1, tag="button", role="", text="ok", bbox={"x": x, "y": y, "w": w, "h": h})


def test_click_point_within_jitter_bounds():
    m = _mk(100, 200, 80, 30)
    cx, cy = 140.0, 215.0  # 中心
    for _ in range(100):
        x, y = _click_point(m)
        assert cx - 5 <= x <= cx + 5, f"x={x} 超出 ±5 jitter"
        assert cy - 5 <= y <= cy + 5, f"y={y} 超出 ±5 jitter"


def test_click_point_centered_on_average():
    m = _mk(0, 0, 100, 100)
    xs, ys = zip(*[_click_point(m) for _ in range(500)])
    avg_x = sum(xs) / len(xs)
    avg_y = sum(ys) / len(ys)
    # 中心 (50, 50)，500 次均值应在 ±1.5 内（jitter 是均匀 ±5）
    assert 48 <= avg_x <= 52, f"x 均值偏离中心: {avg_x}"
    assert 48 <= avg_y <= 52, f"y 均值偏离中心: {avg_y}"
