"""共享 domain types — 纯 dataclass + TypedDict 叶子，被 perceiver / llm / safety / actuator / loop 共享。

依赖方向（按 CLAUDE.md「解耦优先」）：
    domain (本文件) ← ports (llm/base.py) ← 业务层 (perceiver / actuator / safety / loop) ← 组合根 (cli / mcp_server)

本文件不 import 任何 web_agent.* 模块，是依赖图的最叶子节点。

V0.16.11: `Mark.bbox` 升 BBox TypedDict (4 个 float key) — actuator.py:52-57 4 处算子用法被 mypy 守护.
V0.16.12: `Action.args` 暂保 `dict[str, Any]` (而非 ActionArgs union TypedDict) — Action.type 是 str 不是 Literal,
mypy 无法在 `if action.type == "click"` branch 内 narrow union TypedDict 到 ClickArgs;
真要 discriminated union 需把 Action 拆 5 个 dataclass + Literal type 字段, 跨多文件大重构,
留 V0.17 (W6 reflect 阶段) 顺手做. 本版本 ActionArgs 5 个 TypedDict 仅作 schema 文档保留.
LLM 返回 `args` 后, `thought` 已被 args.pop 弹出独立放 `Action.thought`, 故 ActionArgs 不含 thought.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict


class BBox(TypedDict):
    """SoM 元素的相对页面坐标（含 scroll），由 perceiver JS evaluate 注入返回。"""

    x: float
    y: float
    w: float
    h: float


class ClickArgs(TypedDict):
    """click 动作 args — schema/_schema.py:36-43 (required: thought+mark_id; thought 已 pop)。"""

    mark_id: int


class TypeArgs(TypedDict):
    """type 动作 args — schema:44-53 (required: thought+text; submit 可选 default False, OpenAI strict 强制 required)。"""

    text: str
    submit: NotRequired[bool]


class ScrollArgs(TypedDict):
    """scroll 动作 args — schema:54-62 (required: thought+dy)。"""

    dy: int


class ExtractArgs(TypedDict):
    """extract 动作 args — schema:63-72 (required: thought+query+answer)。"""

    query: str
    answer: str


class DoneArgs(TypedDict):
    """done 动作 args — schema:73-81 (required: thought+result)。"""

    result: str


ActionArgs = ClickArgs | TypeArgs | ScrollArgs | ExtractArgs | DoneArgs


@dataclass
class Mark:
    """SoM (Set-of-Mark) 截图上的可点击/可输入元素，由 perceiver 注入 JS 提取。"""

    id: int
    tag: str
    role: str
    text: str
    bbox: BBox  # {x, y, w, h}（相对页面坐标，含 scroll）
    input_type: str = ""  # input.type（password/tel/text/email/...），仅 input 标签有
    name: str = ""  # input.name 或 input.id（用于敏感字段名匹配 amount/cvv/...）
    href: str = ""  # a.href（绝对 URL），仅 a 标签有


@dataclass
class Action:
    """LLM 返回的下一步行动（5 种 type: click / type / scroll / extract / done）。"""

    type: str
    args: dict[str, Any]
    thought: str
