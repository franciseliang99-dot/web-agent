"""共享 domain types — 纯 dataclass 叶子，被 perceiver / llm / safety / actuator / loop 共享。

依赖方向（按 CLAUDE.md「解耦优先」）：
    domain (本文件) ← ports (llm/base.py) ← 业务层 (perceiver / actuator / safety / loop) ← 组合根 (cli / mcp_server)

本文件不 import 任何 web_agent.* 模块，是依赖图的最叶子节点。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Mark:
    """SoM (Set-of-Mark) 截图上的可点击/可输入元素，由 perceiver 注入 JS 提取。"""

    id: int
    tag: str
    role: str
    text: str
    bbox: dict  # {x, y, w, h}（相对页面坐标，含 scroll）
    input_type: str = ""  # input.type（password/tel/text/email/...），仅 input 标签有
    name: str = ""  # input.name 或 input.id（用于敏感字段名匹配 amount/cvv/...）
    href: str = ""  # a.href（绝对 URL），仅 a 标签有


@dataclass
class Action:
    """LLM 返回的下一步行动（5 种 type: click / type / scroll / extract / done）。"""

    type: str
    args: dict
    thought: str
