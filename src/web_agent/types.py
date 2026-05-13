"""共享 domain types — 纯 dataclass + TypedDict 叶子，被 perceiver / llm / safety / actuator / loop 共享。

依赖方向（按 CLAUDE.md「解耦优先」）：
    domain (本文件) ← ports (llm/base.py) ← 业务层 (perceiver / actuator / safety / loop) ← 组合根 (cli / mcp_server)

本文件不 import 任何 web_agent.* 模块，是依赖图的最叶子节点。

V0.16.11: `Mark.bbox` 升 BBox TypedDict (4 个 float key) — actuator.py:52-57 4 处算子用法被 mypy 守护.
V0.17.0: Action 拆 5 dataclass discriminated union (`ClickAction` / `TypeAction` / `ScrollAction` /
  `ExtractAction` / `DoneAction`), 每个含 `type: Literal[...]` 字段. 用 `match action: case
  ClickAction(...)` 让 mypy 自动 narrow, 删 V0.16.12 留下的 2 处 `cast(dict[str, Any], ...)`.
  V0.16.11 的 `ActionArgs` union TypedDict 删除 (不再需要). LLM provider parse 后调
  `action_from_tool_call(name, raw)` factory dispatch 到对应 dataclass.
V0.19.0: Action union 扩 KeyboardShortcutAction (key) + PasteAction (text) 共 7 dataclass.
  V0.16.31 + V0.18.5 spike-2 复刻 contenteditable 末尾追加 fail mode (anti-loop on click 试光标定位)
  根因 = actuator 缺 keyboard chord + paste action. V0.19.0 actuator 加 page.keyboard.press chord
  syntax + execCommand insertText 主路径.
V0.21.0: Action union 扩 SwitchTabAction (idx) + CloseTabAction (idx) 共 9 dataclass.
  零行为变化 — 仅 types/schema 加，loop 派发在 V0.21.1 接入。idx 是 perceive-step 时的
  ctx.pages snapshot 索引（V0.21.1 loop 顶部 snapshot 防 popup 偏移）。
V0.23.0: Action union 扩 DragAction (from/to mark_id) + UploadAction (mark_id + paths) 共 11 dataclass.
  零行为变化 — V0.23.1 actuator + V0.23.2 loop dispatch 接入. paths 用 tuple (frozen
  dataclass requires hashable; LLM 给 list 由 factory 转 tuple).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict


class BBox(TypedDict):
    """SoM 元素的相对页面坐标（含 scroll），由 perceiver JS evaluate 注入返回。"""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True, slots=True)
class Usage:
    """V0.26.2 + V0.42.0: LLM API 单次调用 token 用量 (跨 provider 中性 schema).

    anthropic resp.usage.input_tokens/output_tokens vs openai resp.usage.prompt_tokens/
    completion_tokens — 两 SDK 字段名不同, Usage 中性化让 eval/metrics 跨 provider 累加.

    V0.42.0 加 cache 字段 (default=0 保 V0.33.1 FakeLLMClientWithUsage 兼容):
    - cache_creation_input_tokens: Anthropic prompt cache 首次写入 (1.25× input cost)
    - cache_read_input_tokens: Anthropic + OpenAI/Kimi 缓存命中 (0.1× input cost)

    跟 V0.33.0 token_baseline + V0.42.0 D 主题 cache hit-rate audit 配合.
    eval 用 (web_agent 主路径不强依赖, last_usage 属性默认 None 不破坏 fake client).
    """

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


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
    frame_path: str = ""  # V0.22.0: iframe 深度优先索引路径 e.g. "0" / "0.2"; 主 frame 为空


# ===== V0.17.0: Action discriminated union (5 dataclass + Literal type) =====
# V0.19.0: 扩 KeyboardShortcutAction + PasteAction (共 7 个).
# 每个 dataclass 有 `type: Literal[...]` 字段 (放最后, dataclass 要求 default 字段在后),
# `thought: str` 是公共字段 (每个 dataclass 重写而非继承 — explicit-better-than-implicit + frozen 子类坑).
# `frozen=True` 防意外 mutate (Action 在短期记忆 deque 里被多次 ref); `slots=True` 省内存.


@dataclass(frozen=True, slots=True)
class ClickAction:
    """click 动作 — schema/_schema.py:36-43 (required: thought+mark_id)."""

    thought: str
    mark_id: int
    type: Literal["click"] = "click"


@dataclass(frozen=True, slots=True)
class TypeAction:
    """type 动作 — schema:44-53 (required: thought+text+submit; submit OpenAI strict 强制 required)."""

    thought: str
    text: str
    submit: bool = False
    type: Literal["type"] = "type"


@dataclass(frozen=True, slots=True)
class ScrollAction:
    """scroll 动作 — schema:54-62 (required: thought+dy)."""

    thought: str
    dy: int
    type: Literal["scroll"] = "scroll"


@dataclass(frozen=True, slots=True)
class ExtractAction:
    """extract 动作 — schema:63-72 (required: thought+query+answer)."""

    thought: str
    query: str
    answer: str
    type: Literal["extract"] = "extract"


@dataclass(frozen=True, slots=True)
class DoneAction:
    """done 动作 — schema:73-81 (required: thought+result)."""

    thought: str
    result: str
    type: Literal["done"] = "done"


@dataclass(frozen=True, slots=True)
class KeyboardShortcutAction:
    """V0.19.0: 按键盘快捷键 (e.g. Control+End 跳到 textarea/contenteditable 末尾, Tab 切焦点).

    Playwright key syntax: 修饰符 + '+' + 主键 (e.g. 'Control+End', 'Control+a', 'End', 'PageDown').
    actuator 接 LLM 偶尔写 'Ctrl+...' 时 normalize 到 'Control+...' (Playwright canonical).
    """

    thought: str
    key: str
    type: Literal["keyboard_shortcut"] = "keyboard_shortcut"


@dataclass(frozen=True, slots=True)
class PasteAction:
    """V0.19.0: 把文本粘贴到当前 focus 的 input/textarea/contenteditable.

    比 type 快且不触发反爬键盘指纹. 主路径 document.execCommand('insertText') 避 clipboard 权限,
    备路径 navigator.clipboard.writeText + Ctrl+V (CDP-connected mode 不能 grant_permissions).
    paste 前必须先 click 把焦点放到目标输入框.
    """

    thought: str
    text: str
    type: Literal["paste"] = "paste"


@dataclass(frozen=True, slots=True)
class SwitchTabAction:
    """V0.21.0: 切换到 ctx.pages[idx] 作为后续 perceive/actuate 的 active tab.

    idx 是 perceive 时 LLM 看到的 step-snapshot 索引 (V0.21.1 loop 顶部 snapshot list(ctx.pages)
    防 popup 偏移). 派发后 loop 会 ctx.pages[idx].bring_to_front() + 重置 last_clicked_mark.
    """

    thought: str
    idx: int
    type: Literal["switch_tab"] = "switch_tab"


@dataclass(frozen=True, slots=True)
class CloseTabAction:
    """V0.21.0: 关闭 ctx.pages[idx]. 2 道 safety guard 在 loop 派发时校验.

    Guard: (a) len(ctx.pages)==1 拒 (不能关最后 1 个 tab 否则 loop 孤儿);
    (b) idx == active_idx 拒 (强迫 LLM 先 switch_tab 再 close, 避免 active 蒸发竞态).
    """

    thought: str
    idx: int
    type: Literal["close_tab"] = "close_tab"


@dataclass(frozen=True, slots=True)
class DragAction:
    """V0.23.0: 从 from_mark_id 拖到 to_mark_id (Trello 拖卡, Dropbox 上传 zone, 表单 builder 等).

    actuator V0.23.1 走单段贝塞尔 from→to + mouse.down→bezier moves→mouse.up. iframe 路径
    走 frame.locator(...).drag_to(other_locator) (跟 V0.22.2 click iframe 同 trade-off 失贝塞尔).
    跨 frame drag 不允许 (loop V0.23.2 dispatch 校验 from.frame_path == to.frame_path).
    """

    thought: str
    from_mark_id: int
    to_mark_id: int
    type: Literal["drag"] = "drag"


@dataclass(frozen=True, slots=True)
class UploadAction:
    """V0.23.0: 把本地文件 paths 上传到 mark_id (input[type=file] 或关联 button).

    paths 是绝对路径 tuple (frozen dataclass requires hashable; LLM 给 list 由 factory 转).
    actuator V0.23.1 自适应:
    - mark.tag=='input' and input_type=='file' → 直接 set_input_files
    - 否则 (mark 是 button) → DOM walk 找关联 input[type=file] (label[for] / aria-controls /
      同祖先 querySelector)
    safety V0.23.2 拦敏感路径黑名单 (~/.ssh/, ~/.aws/, .env, *.pem, id_rsa* etc).
    """

    thought: str
    mark_id: int
    paths: tuple[str, ...]
    type: Literal["upload"] = "upload"


@dataclass(frozen=True, slots=True)
class GotoUrlAction:
    """V0.70.1: 直接 page.goto(url) — mark click 反复无效后的 escape hatch.

    使用场景: V0.69 dogfood Supabase Dashboard mark 49 click 撞 anti-loop, LLM 已知
    site URL 结构 (e.g. /dashboard/x/auth/url-configuration) → goto_url 直跳绕开 mark 识别.
    safety V0.70.1: 拒 javascript:/data:/file: scheme (XSS / 本地文件读).
    actuator (loop.py match-case): try page.goto(url, wait_until="domcontentloaded") except → ERROR obs.
    """

    thought: str
    url: str
    type: Literal["goto_url"] = "goto_url"


Action = (
    ClickAction
    | TypeAction
    | ScrollAction
    | ExtractAction
    | DoneAction
    | KeyboardShortcutAction
    | PasteAction
    | SwitchTabAction
    | CloseTabAction
    | DragAction
    | UploadAction
    | GotoUrlAction
)


def action_from_tool_call(name: str, raw: dict[str, Any]) -> Action:
    """V0.17.0: LLM provider parse 用. `raw` 是 tool_use input dict (含 thought+args).

    `thought` 必须在调用前已 pop 出, 或 raw 含 thought 由本函数 pop. 11 type 之一不匹配抛 RuntimeError.
    V0.21.0: 加 switch_tab / close_tab 2 arm.
    V0.23.0: 加 drag / upload 2 arm. upload paths LLM 给 list → tuple cast (frozen hashable).
    """
    thought = raw.pop("thought", "") if "thought" in raw else ""
    match name:
        case "click":
            return ClickAction(thought=thought, mark_id=int(raw["mark_id"]))
        case "type":
            return TypeAction(thought=thought, text=str(raw["text"]), submit=bool(raw.get("submit", False)))
        case "scroll":
            return ScrollAction(thought=thought, dy=int(raw["dy"]))
        case "extract":
            return ExtractAction(thought=thought, query=str(raw["query"]), answer=str(raw["answer"]))
        case "done":
            return DoneAction(thought=thought, result=str(raw["result"]))
        case "keyboard_shortcut":
            return KeyboardShortcutAction(thought=thought, key=str(raw["key"]))
        case "paste":
            return PasteAction(thought=thought, text=str(raw["text"]))
        case "switch_tab":
            return SwitchTabAction(thought=thought, idx=int(raw["idx"]))
        case "close_tab":
            return CloseTabAction(thought=thought, idx=int(raw["idx"]))
        case "drag":
            return DragAction(
                thought=thought,
                from_mark_id=int(raw["from_mark_id"]),
                to_mark_id=int(raw["to_mark_id"]),
            )
        case "upload":
            paths_raw = raw.get("paths") or []
            return UploadAction(
                thought=thought,
                mark_id=int(raw["mark_id"]),
                paths=tuple(str(p) for p in paths_raw),
            )
        case "goto_url":
            return GotoUrlAction(thought=thought, url=str(raw["url"]))
        case _:
            raise RuntimeError(f"action_from_tool_call: unknown tool name {name!r}")


# ===== ActionArgs 兼容 stub (TypedDict 保留 schema 文档, 但不再用于 union) =====
# V0.17.0 删除 ActionArgs union, 但留 5 个 TypedDict 是因为 `_schema.py` 里某些参考 schema 文档
# 仍引用这些 type. 实际 LLM tool schema 是 hand-written JSON, 这 5 个 TypedDict 仅作 IDE 提示作用.
# V0.19.0 加 KeyboardShortcutArgs + PasteArgs 同模式.


class ClickArgs(TypedDict):
    mark_id: int


class TypeArgs(TypedDict):
    text: str
    submit: NotRequired[bool]


class ScrollArgs(TypedDict):
    dy: int


class ExtractArgs(TypedDict):
    query: str
    answer: str


class DoneArgs(TypedDict):
    result: str


class KeyboardShortcutArgs(TypedDict):
    key: str


class PasteArgs(TypedDict):
    text: str
