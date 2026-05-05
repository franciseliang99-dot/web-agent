"""拟人 actuator (W2: 3 阶贝塞尔 + 正态键入 + typo+backspace 纠错 + 多段惯性滚动 + 正态点击偏移)。

核心设计（含 Plan subagent 反馈优化的参数）：
- 鼠标轨迹用 3 阶贝塞尔（P0/P3 端点 + P1/P2 在 1/3 和 2/3 处垂直 N(0, jitter*dist) 偏移、clamp ±80px）
- ease 用 smootherstep (6t⁵-15t⁴+10t³)，加加速度连续、minimum-jerk 廉价近似
- 鼠标"上次位置"用 WeakKeyDictionary[Page, (x,y)]，支持 W3 multi-tab 不串扰
- 键入间隔截断正态 N(120, 40) ms ∈ [40, 300]
- ~2% 概率打错相邻 QWERTY 键 + 真人 reaction time 200-400ms 后 backspace（仅 ASCII 字母 + 中速以上才触发）
- 滚动按 sin 包络分 4-7 段，每段间停顿 50-120ms（避免段连发被反爬识别）
- 点击坐标 std=max(3, min(w/6, 15))、截断 90% 内区（参考反爬研究 click heatmap 离散度）
"""

from __future__ import annotations

import asyncio
import math
import random
from collections import deque
from collections.abc import Iterable
from weakref import WeakKeyDictionary

from playwright.async_api import Page

from web_agent.types import Mark

# 上次鼠标视口坐标（per-page，避免 W3 multi-tab 串扰）。Page 关闭后自动 GC。
_last_mouse_pos: WeakKeyDictionary[Page, tuple[float, float]] = WeakKeyDictionary()

# QWERTY 邻居键（用于 typo 模拟，仅 ASCII 字母）
_QWERTY_NEIGHBORS: dict[str, str] = {
    "q": "wa", "w": "qeas", "e": "wrds", "r": "etfd", "t": "ryfg",
    "y": "tugh", "u": "yihj", "i": "uojk", "o": "ipkl", "p": "ol",
    "a": "qwsz", "s": "awedzx", "d": "serfcx", "f": "drtgvc", "g": "ftyhbv",
    "h": "gyujnb", "j": "huiknm", "k": "jiolm", "l": "kop",
    "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb", "b": "vghn",
    "n": "bhjm", "m": "njk",
}


async def think(min_s: float = 0.8, max_s: float = 2.5) -> None:
    """模拟人类思考延迟（每步 action 前调用一次）。"""
    await asyncio.sleep(random.uniform(min_s, max_s))


def _click_point(mark: Mark) -> tuple[float, float]:
    """按钮中心 + 截断正态偏移。

    std = max(3, min(w/6, 15))：小按钮加底（不到 3px 偏移视觉太集中），大按钮加顶（>15 不真实）。
    截断到按钮 90% 内区（80% 太保守，真人偶尔会点近边缘）。
    返回页面绝对坐标（含 scroll）；视口坐标转换在 human_like_click 里做。
    """
    cx = mark.bbox["x"] + mark.bbox["w"] / 2
    cy = mark.bbox["y"] + mark.bbox["h"] / 2
    sx = max(3.0, min(mark.bbox["w"] / 6, 15.0))
    sy = max(3.0, min(mark.bbox["h"] / 6, 15.0))
    max_dx = mark.bbox["w"] * 0.45
    max_dy = mark.bbox["h"] * 0.45
    dx = max(-max_dx, min(max_dx, random.gauss(0, sx)))
    dy = max(-max_dy, min(max_dy, random.gauss(0, sy)))
    return cx + dx, cy + dy


def _bezier_path(
    start: tuple[float, float],
    end: tuple[float, float],
    steps: int = 25,
    jitter: float = 0.08,
) -> Iterable[tuple[float, float]]:
    """3 阶贝塞尔从 start 到 end，控制点垂直方向 N(0, jitter*dist) 偏移、clamp ±80px。
    smootherstep ease (6t⁵-15t⁴+10t³)，加加速度连续。生成 steps 个 (x, y) 点。

    jitter=0.08 出处：反爬研究推荐 perpendicular offset 5-10% 距离，0.15 在长距离会画 120px 弧像醉汉。
    clamp ±80 防短距离 gauss 尾部样本画大弧。
    """
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    dist = math.hypot(dx, dy)
    if dist < 1e-3:
        for _ in range(steps):
            yield ex, ey
        return
    perp_x = -dy / dist
    perp_y = dx / dist
    off1 = max(-80.0, min(80.0, random.gauss(0, jitter * dist)))
    off2 = max(-80.0, min(80.0, random.gauss(0, jitter * dist)))
    p1x = sx + dx / 3 + perp_x * off1
    p1y = sy + dy / 3 + perp_y * off1
    p2x = sx + 2 * dx / 3 + perp_x * off2
    p2y = sy + 2 * dy / 3 + perp_y * off2
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * t * (t * (t * 6 - 15) + 10)  # smootherstep
        u = 1 - t
        x = u**3 * sx + 3 * u**2 * t * p1x + 3 * u * t**2 * p2x + t**3 * ex
        y = u**3 * sy + 3 * u**2 * t * p1y + 3 * u * t**2 * p2y + t**3 * ey
        yield x, y


async def human_like_click(page: Page, mark: Mark) -> None:
    """3 阶贝塞尔轨迹移动到按钮 → 短暂悬停 → 按下 → 短停 → 抬起。

    起点取该 page 上次鼠标位置；首次取视口中心附近随机点。
    """
    page_x, page_y = _click_point(mark)
    scroll = await page.evaluate("() => ({x: window.scrollX, y: window.scrollY})")
    target_vx = page_x - scroll["x"]
    target_vy = page_y - scroll["y"]

    last = _last_mouse_pos.get(page)
    if last is None:
        viewport = page.viewport_size or {"width": 1280, "height": 800}
        start_vx = random.uniform(viewport["width"] * 0.3, viewport["width"] * 0.7)
        start_vy = random.uniform(viewport["height"] * 0.3, viewport["height"] * 0.7)
    else:
        start_vx, start_vy = last

    dist = math.hypot(target_vx - start_vx, target_vy - start_vy)
    steps = max(15, min(40, int(dist / 20) + random.randint(5, 10)))
    delay_per_step = random.uniform(0.005, 0.015)
    for x, y in _bezier_path((start_vx, start_vy), (target_vx, target_vy), steps=steps):
        await page.mouse.move(x, y)
        await asyncio.sleep(delay_per_step)
    _last_mouse_pos[page] = (target_vx, target_vy)

    await asyncio.sleep(random.uniform(0.05, 0.15))
    await page.mouse.down()
    await asyncio.sleep(random.uniform(0.04, 0.12))
    await page.mouse.up()


def _is_qwerty_letter(ch: str) -> bool:
    return ch.isascii() and ch.isalpha()


def _type_delay() -> float:
    """截断正态 N(120, 40) ms 限到 [40, 300]。"""
    return max(0.04, min(0.30, random.gauss(0.12, 0.04)))


async def human_like_type(page: Page, text: str, typo_rate: float = 0.02) -> None:
    """逐字键入：截断正态间隔 + ~2% 概率打错相邻 QWERTY 键 + reaction time 200-400ms + backspace 修正。

    typo 触发条件：① ASCII 字母（中文 IME 单字符 typo 不真实）② 概率命中 ③ 中速以上
    （最近 3 字平均间隔 < 150ms，慢打字不会频繁错）。typo_rate 默认 2%（参考 Salthouse 1986 + IKI 数据集）。
    """
    recent_delays: deque[float] = deque(maxlen=3)
    for ch in text:
        delay = _type_delay()
        fast_enough = (
            len(recent_delays) < 3
            or sum(recent_delays) / len(recent_delays) < 0.15
        )
        if _is_qwerty_letter(ch) and fast_enough and random.random() < typo_rate:
            wrong = random.choice(_QWERTY_NEIGHBORS[ch.lower()])
            if ch.isupper():
                wrong = wrong.upper()
            await page.keyboard.type(wrong)
            await asyncio.sleep(_type_delay())
            await asyncio.sleep(random.uniform(0.20, 0.40))  # 真人察觉错字的 reaction time
            await page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.05, 0.15))
        await page.keyboard.type(ch)
        await asyncio.sleep(delay)
        recent_delays.append(delay)


async def scroll(page: Page, dy: int = 400) -> None:
    """多段 wheel + sin 包络（中间快两端慢，模拟惯性）；段间停顿避免连发被反爬识别。"""
    n = random.randint(4, 7)
    weights = [math.sin((i + 0.5) / n * math.pi) for i in range(n)]
    total = sum(weights) or 1.0
    accum = 0
    for i, w in enumerate(weights):
        seg = int(dy * w / total)
        if i == n - 1:
            seg = dy - accum  # 末段补差防舍入丢失
        accum += seg
        await page.mouse.wheel(0, seg)
        await asyncio.sleep(random.uniform(0.05, 0.12))  # 段间停顿，不要连发
    await asyncio.sleep(random.uniform(0.3, 0.8))  # 滚完看新内容
