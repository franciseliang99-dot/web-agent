"""拟人 actuator：W1 占位实现（直线鼠标 + 简单键入抖动 + 思考延迟）。

W2 升级路径（写在这里给未来的我看）：
- `_click_point`: ±5 均匀 jitter → 正态分布 N(0, w/8) 截断在按钮内
- `human_like_click` 鼠标轨迹: 直线 → 3 阶贝塞尔曲线 + 微颤
- `human_like_type` 间隔: uniform(80,200) → 正态 + 5% 概率打错 + backspace 修正
- `scroll`: 单次 wheel → 多次小 wheel + 中途 pause 模拟惯性
"""

from __future__ import annotations

import asyncio
import random

from playwright.async_api import Page

from web_agent.perceiver import Mark


async def think(min_s: float = 0.8, max_s: float = 2.5) -> None:
    """模拟人类思考延迟（每步 action 前调用一次）。"""
    await asyncio.sleep(random.uniform(min_s, max_s))


def _click_point(mark: Mark) -> tuple[float, float]:
    """W1: 中心点 + ±5px 均匀 jitter。W2 改正态分布。

    注意：bbox.x/y 是页面绝对坐标（含 scroll），mouse API 接受的是视口坐标。
    本函数只负责算"按钮内的目标点"，不做坐标系转换；scroll 处理在调用方。
    """
    cx = mark.bbox["x"] + mark.bbox["w"] / 2
    cy = mark.bbox["y"] + mark.bbox["h"] / 2
    return cx + random.uniform(-5, 5), cy + random.uniform(-5, 5)


async def human_like_click(page: Page, mark: Mark) -> None:
    """点击元素：移动 → 短暂停顿 → 按下 → 短暂停顿 → 抬起。

    W1 占位：直线移动 15-25 步。元素的 bbox 是页面绝对坐标，
    mouse 接受视口坐标，所以减掉当前 scroll offset。
    """
    page_x, page_y = _click_point(mark)
    scroll = await page.evaluate("() => ({x: window.scrollX, y: window.scrollY})")
    vx = page_x - scroll["x"]
    vy = page_y - scroll["y"]
    await page.mouse.move(vx, vy, steps=random.randint(15, 25))
    await asyncio.sleep(random.uniform(0.05, 0.15))
    await page.mouse.down()
    await asyncio.sleep(random.uniform(0.04, 0.12))
    await page.mouse.up()


async def human_like_type(page: Page, text: str) -> None:
    """逐字键入，间隔 80-200ms 均匀抖动。W2 改正态 + 偶尔 typo。"""
    for ch in text:
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(0.08, 0.20))


async def scroll(page: Page, dy: int = 400) -> None:
    """滚动一定距离（W1 简单实现，W2 加多段惯性）。"""
    await page.mouse.wheel(0, dy)
    await asyncio.sleep(random.uniform(0.3, 0.8))
