"""中性工具 schema 定义 + 各 provider 格式转换 + 共享 SYSTEM_PROMPT + user-text 构造。

业务工具语义（5 个 action）写一份中性 dict（接近 JSON Schema 通用子集），
各 provider client 内部转换为自己的格式：
- Anthropic: name + description + input_schema
- OpenAI: type='function', function={name, description, parameters, strict}
- Gemini (留位): function_declarations
"""

from __future__ import annotations

import json
from typing import Any

from web_agent.perceiver import marks_to_text
from web_agent.trace import Trace
from web_agent.types import Mark

SYSTEM_PROMPT = """你是一个高度拟人的浏览器自动化 agent。每步给你当前页面的标注截图（每个可交互元素都有彩色边框 + 数字 ID）和元素清单，请按以下规则输出下一步操作：

1. 必须通过 tool 调用返回行动，不要回纯文本。
2. 操作前先用 thought 字段说明你的判断（基于截图实际看到的内容，不要臆测）。
3. 优先选择最直接达成 goal 的操作；遇到 cookie 同意框 / 广告弹窗 / 注册引导先关掉。**(V0.70.7 early anchor) 如 goal 含 chrome-level 关键字 (`console` / `JS 执行` / `localStorage` / `cookie` / `DevTools` / `Runtime.evaluate` / `chrome://`) → 当前工具集**不支持** → 第一步就 `done(result="工具集不含 X 能力, 无法完成此 task")` 早退, 不要试任何 keyboard / click 探索. 详见 rule-16.**
4. 任务完成后调用 `done` 工具并把最终答案写在 `result` 字段。
5. 连续 2 步页面无变化（thought 中识别到）→ 尝试不同策略：滚动 / 后退 / 选另一个候选元素。
6. 严禁猜测 mark_id — 只能用截图里实际存在的编号；编号缺失就先 scroll 让页面重新标注。
7. **type 协议 + 多字段表单严格交错** (V0.56 pilot #2 经验): `type` 不带 mark_id, 默认作用于
   **上一步 click 聚焦的元素**. type 的 submit=true 会按回车.
   - 单字段: `click[5] (input) → type "X"` ✅
   - 多字段必须 **click→type 严格交错**, 不要连续 click 多个再 type (焦点会跑到最后一个 click 的, 第一个 type 写错框):
     - ✅ 正例: `click[5] (姓名 input) → type "Alice" → click[7] (邮箱 input) → type "alice@x.com" → click[9] (Submit)`
     - ❌ 反例: `click[5] click[7] type "Alice"` — 焦点在 [7], "Alice" 写错框
   - 长文本 (>50 字符) 走 `paste` (跟 type 同样需先 click 聚焦, 但更快不触发反爬键盘指纹).
8. **编辑现有内容 (contenteditable / textarea / 富文本编辑器) 走完整组合, 不要反复 click 同元素**:
   - 第 1 步: click 编辑器 (1 次, 仅为聚焦)
   - 第 2 步: `keyboard_shortcut` (key="Control+End" 跳末尾 / "Control+a" 选全部 / "End" 行末)
   - 第 3 步: `paste` (长文本 >50 字符) 或 `type` (短文本) 输入内容
   - 第 4 步: `done` 返回结果
   - 严禁 click 同一 mark_id 超过 1 次! click 不会移动光标; keyboard_shortcut 后应直接走 paste/type, 不要再 click。
9. 长文本 (>50 字符) 优先 `paste`, 短文本 `type`。`paste` 前必须先 click 聚焦目标输入框 (paste 跟 type 同样需要 focus, 但比 type 快且不触发反爬键盘指纹)。
10. **多 tab 编排** (V0.21+): 浏览器可能开多个 tab — 用户提示中的 `Tabs (N open, current=X)` header 列出所有 tab。用 `switch_tab(idx=...)` 切换 active tab (索引 == header 里的 [idx])，用 `close_tab(idx=...)` 关 tab。规则：(a) `close_tab` 不能关最后 1 个 tab，也不能关当前 active tab (先 switch 再 close)；(b) 切 tab 后下一步 perceive 才能看到新 tab 的截图，不要假设切完立即生效；(c) 新弹 tab (target=_blank/window.open) 自动出现在 header，不需要主动切除非任务需要在新 tab 操作。
11. **拖动** (V0.23+): 用 `drag(from_mark_id, to_mark_id)` 拖元素 (Trello 拖卡 / Dropbox 上传 zone / 表单 builder 排序)。规则：两个 mark 必须在同一 frame (主或同 iframe, 看 marks 末尾 `@frame_path`), 跨 frame drag 不允许。
12. **文件上传** (V0.23+): 用 `upload(mark_id, paths)` 把本地文件传到 file input 或上传 button。规则：(a) `paths` 必须绝对路径列表 e.g. `['/tmp/photo.jpg']`; (b) mark_id 可以是 `<input type=file>` 或上传 button — agent 自动找隐藏 input 关联; (c) **敏感路径会被 safety 拒绝** — `~/.ssh/`, `~/.aws/`, `.env`, `*.pem`, `id_rsa*`, `credentials*` 等系统/凭证文件不可上传, 触发会 abort task。
13. **键盘导航优先** (V0.24+): 遇到长列表 / 长 modal / 长 SPA 页, **优先用 `keyboard_shortcut` 比 `scroll` 像素级更稳**。常用键：`PageDown`/`PageUp` 翻屏滚动，`Home`/`End` 跳页首/页末（含 textarea/contenteditable 内首末），`Escape` 关 modal/popover/广告/弹窗，`Tab`/`Shift+Tab` 切换焦点（无 SoM mark 时找下一个交互元素的 fallback）。
14. **失败恢复策略** (V0.25+): 看到 trace 里出现以下 obs 信号请**主动换思路**, 不要死磕同一 mark / 同一 action：
    - `ERROR: ...` → 上一步失败 (mark_id 越界 / 跨 frame drag / DOM walk null 等), 优先**换 mark** 或**重新 perceive**, 不要原 args 重发
    - `[reflect] 页面 3 步无变化` → W5-A 软提示, 当前 strategy 大概率撞墙, 换 scroll/后退/换 mark
    - `[backtrack] 已回退到上一页` → V0.25.2 硬纠正, 你刚被 anti_loop 触发过 → 系统已自动 page.go_back, 重读截图找新 mark, **再触发同样卡死会硬 abort**
    - `LLM_FAILED ... transient` → 系统已自动 retry, 不要担心
    - `dialog confirm: ... (auto-dismissed)` / `dialog prompt: ...` → 浏览器弹了 confirm/prompt 已自动 dismiss; 如需 accept, 重新触发并依靠用户 env `WEB_AGENT_DIALOG_POLICY=auto-accept` 全开
15. **直连导航 fallback** (V0.70.1+): mark click 反复无效但已知目标 URL 结构时 → 用 `goto_url(url=...)` 直跳, 绕开 mark 识别失败. 适用场景: site URL 结构稳定 (e.g. /dashboard/x/auth/url-configuration). 不要每步都 goto (会绕开 SoM 学习); URL 必须 `http://` 或 `https://` 开头 (V0.70.3 allowlist), 其余 scheme 全拒.

16. **`keyboard_shortcut` 仅作用页面层 + chrome-level task 立即 done 早退** (V0.70.4 / V0.70.7 加强): `keyboard_shortcut` 走 Playwright `page.keyboard.press`, 发到**当前 page DOM**, **任何 browser chrome / DevTools / address bar 快捷键全部无效**.
    - **(V0.70.7 类别 ban)** 凡是用来开 DevTools / 操作 address bar / 切换/关闭 tab / 刷新页 / 进入 Chrome 设置的快捷键 — `keyboard_shortcut` **一律不开, 不要试任何一个**. 例子 (**不是穷举, 同类**都不该试): `Control+Shift+J` / `F12` / `Control+Shift+I` (DevTools), `Control+T` / `Control+W` (tab), `Control+L` (URL bar), `Control+R` / `F5` (reload), `Command+,` (Chrome 设置).
    - **替代**: tab 操作 → `switch_tab` / `close_tab` (rule-10); URL 改 → `goto_url` (rule-15); reload → `goto_url(<当前 url>)`.
    - ✅ 仅页面层键 (与 rule-13 同): `PageDown` / `PageUp` / `Home` / `End` / `Tab` / `Shift+Tab` / `Escape` / `Control+End` / `Control+a`.
    - **(V0.70.7 goal 关键字 anchor — 强复述 rule-3) goal text 含 `console` / `localStorage` / `cookie` / `DevTools` / `JS 执行` / `Runtime.evaluate` / `chrome://` 等关键字 = task 要求 chrome-level 能力**, 当前工具集**不支持** → **第一步就** `done(result="工具集不含 X 能力, 无法完成此 task")` 早退, **不要等到撞墙再 done**, **不要试**任何 keyboard_shortcut / click 探索.

17. **`no_nav_after_action` 信号 + 连续 2 步强制 done** (V0.70.4 / V0.70.6 加 goto_url / V0.70.7 硬约束): trace 段里 `"no_nav_after_action": true` = 上一 click / keyboard_shortcut / switch_tab / type / `goto_url` (V0.70.6 加) **没让页面 url 变**. 当 task 期望 nav 而 url 不变 (click 死链 / keyboard 无 handler / 失败 submit / 反复 goto 同 URL) 时:
    - ❌ 不要原 args 重发同 mark_id + 同 action type (anti-loop 会硬切, 见 rule-14 `[backtrack]`)
    - ✅ **第 1 次见信号**: 切 action type 或切 mark — click[X] 失败 → 试 `keyboard_shortcut Enter` (若 X 是 submit) / `goto_url` 直连 (已知 URL 结构, rule-15) / click 另一候选 mark.
    - **(V0.70.7 硬约束) 连续 2 步 `no_nav_after_action: true` 同 (mark_id / url / key) → 必须 `done(result="X 反复无效, 无法完成")` 放弃**. **不再尝试第 3 次**. anti-loop 会在第 3 次硬 abort, 你主动 done 比被 abort 更可控.
"""


# 中性工具 schema（接近 JSON Schema，所有 provider 兼容子集）。
# 注意：OpenAI strict mode 要求所有 properties 都在 required；本表 required 可能少于 properties，
# 各 client 转换时按需扩展（_to_openai_tools 会处理）。
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "click",
        "description": "点击截图中编号为 mark_id 的元素。",
        "properties": {
            "thought": {"type": "string", "description": "为什么点这个元素"},
            "mark_id": {"type": "integer", "description": "元素的 SoM 编号"},
        },
        "required": ["thought", "mark_id"],
    },
    {
        "name": "type",
        "description": "在当前焦点的输入框中逐字键入文本。先用 click 把焦点放到输入框上。",
        "properties": {
            "thought": {"type": "string"},
            "text": {"type": "string", "description": "要键入的文本"},
            "submit": {"type": "boolean", "description": "键入后是否按回车提交"},
        },
        "required": ["thought", "text"],
    },
    {
        "name": "scroll",
        "description": "滚动页面（正数下滚，负数上滚，单位像素）。",
        "properties": {
            "thought": {"type": "string"},
            "dy": {"type": "integer", "description": "正数下滚，负数上滚"},
        },
        "required": ["thought", "dy"],
    },
    {
        "name": "extract",
        "description": "从当前页面读取信息（不操作页面，把读到的内容写到 answer）。",
        "properties": {
            "thought": {"type": "string"},
            "query": {"type": "string", "description": "要提取的内容描述"},
            "answer": {"type": "string", "description": "你从截图中读到的答案"},
        },
        "required": ["thought", "query", "answer"],
    },
    {
        "name": "done",
        "description": "任务完成，把最终结果写到 result 返回给用户。",
        "properties": {
            "thought": {"type": "string"},
            "result": {"type": "string", "description": "最终结果"},
        },
        "required": ["thought", "result"],
    },
    {
        "name": "keyboard_shortcut",
        "description": "按键盘快捷键 (e.g. Control+End 跳到 textarea/contenteditable 末尾; Control+a 选全部; Tab 切换焦点). Playwright key syntax: 修饰符用 '+' 拼接最终键, e.g. 'Control+End' / 'End' / 'Tab' / 'Control+a' / 'PageDown'.",
        "properties": {
            "thought": {"type": "string"},
            "key": {"type": "string", "description": "按键组合, e.g. 'Control+End', 'End', 'Tab', 'Control+a'"},
        },
        "required": ["thought", "key"],
    },
    {
        "name": "paste",
        "description": "把 text 粘贴到当前 focus 的输入框/textarea/contenteditable。比 type 快, 适合长文本 (>50 字符). paste 前必须先 click 把焦点放到目标输入框。",
        "properties": {
            "thought": {"type": "string"},
            "text": {"type": "string", "description": "要粘贴的文本"},
        },
        "required": ["thought", "text"],
    },
    {
        "name": "switch_tab",
        "description": "切换到第 idx 个 tab 作为后续 perceive/click/type 的目标 (idx 来自用户消息 header 里的 [idx])。切完下一步才能看到新 tab 截图，不要假设立即生效。",
        "properties": {
            "thought": {"type": "string"},
            "idx": {"type": "integer", "description": "目标 tab 索引 (header 里的 [idx])"},
        },
        "required": ["thought", "idx"],
    },
    {
        "name": "close_tab",
        "description": "关闭第 idx 个 tab。规则：(a) 不能关最后 1 个 tab；(b) 不能关当前 active tab (先 switch_tab 切走再 close)。违反会被 loop 拒绝。",
        "properties": {
            "thought": {"type": "string"},
            "idx": {"type": "integer", "description": "要关的 tab 索引 (header 里的 [idx])"},
        },
        "required": ["thought", "idx"],
    },
    {
        "name": "drag",
        "description": "从 from_mark_id 元素拖到 to_mark_id 元素 (Trello 拖卡 / Dropbox 上传区 / 表单 builder)。两个 mark 必须在同一 frame (主或同 iframe), 跨 frame drag 不允许。",
        "properties": {
            "thought": {"type": "string"},
            "from_mark_id": {"type": "integer", "description": "拖动起点 mark id"},
            "to_mark_id": {"type": "integer", "description": "拖动终点 mark id"},
        },
        "required": ["thought", "from_mark_id", "to_mark_id"],
    },
    {
        "name": "upload",
        "description": "把本地文件 paths 上传到 mark_id (input[type=file] 或关联的 button). paths 必须是绝对路径列表; agent 自动找隐藏 input。安全: ~/.ssh/, ~/.aws/, .env, *.pem 等敏感路径会被 safety 拒绝。",
        "properties": {
            "thought": {"type": "string"},
            "mark_id": {"type": "integer", "description": "目标 file input 或上传 button 的 mark id"},
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "本地文件绝对路径列表 (e.g. ['/tmp/photo.jpg'])",
            },
        },
        "required": ["thought", "mark_id", "paths"],
    },
    {
        "name": "goto_url",
        "description": "直接导航到 URL (替代失败的 mark click). 已知 site URL 结构时用 (e.g. /dashboard/x/auth/url-configuration). URL 必须 http:// 或 https:// 开头 (V0.70.3 allowlist), 其余 scheme 全拒. 用 wait_until=domcontentloaded 等 DOM ready 再 perceive。",
        "properties": {
            "thought": {"type": "string"},
            "url": {"type": "string", "description": "目标 URL, 必须 http:// 或 https:// 开头"},
        },
        "required": ["thought", "url"],
    },
]


def to_anthropic_tools(
    schemas: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """中性 schema → Anthropic tools 格式（input_schema 包装）。"""
    schemas = schemas if schemas is not None else TOOL_SCHEMAS
    return [
        {
            "name": s["name"],
            "description": s["description"],
            "input_schema": {
                "type": "object",
                "properties": s["properties"],
                "required": s["required"],
            },
        }
        for s in schemas
    ]


def to_openai_tools(
    schemas: list[dict[str, Any]] | None = None,
    strict: bool = True,
) -> list[dict[str, Any]]:
    """中性 schema → OpenAI tools 格式（function.parameters + 可选 strict 模式）。

    strict=True 时（默认）：
    - 所有 properties 必须在 required 列表中（OpenAI strict mode 要求）；
      原本 optional 的字段（如 type.submit）会被强制放进 required，
      LLM 必须显式给值（boolean default 由 LLM 自决，常见就是写 false）
    - parameters 必须含 additionalProperties: false
    - function 顶层必须含 strict: true
    """
    schemas = schemas if schemas is not None else TOOL_SCHEMAS
    tools = []
    for s in schemas:
        required = list(s["properties"].keys()) if strict else s["required"]
        params: dict[str, Any] = {
            "type": "object",
            "properties": s["properties"],
            "required": required,
        }
        if strict:
            params["additionalProperties"] = False
        tool: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": params,
            },
        }
        if strict:
            tool["function"]["strict"] = True
        tools.append(tool)
    return tools


def _render_tabs_header(tabs: list[tuple[int, str]], current_idx: int) -> str:
    """V0.21.2: 渲染 multi-tab header. 单 tab (len==1) 也渲染让 LLM 知道 tab 概念存在.

    格式: `Tabs (N open, current=X): [0] "title-A" [1] "title-B"`
    title 截 60 字符防超长 page title (e.g. SEO 堆词); 加引号区分相邻 idx.
    """
    if not tabs:
        return ""
    body = " ".join(f'[{idx}] "{title[:60]}"' for idx, title in tabs)
    return f"# 当前 Tabs ({len(tabs)} open, current={current_idx})\n{body}\n\n"


def _render_cross_origin_footer(hosts: list[str]) -> str:
    """V0.22.4: 渲染跨域 iframe footer (放 marks 之后让 LLM 知道反爬 widget 存在).

    格式: `# 跨域 iframe (LLM 不可见内容, 不要尝试 click): N 个 - host1, host2`
    文案明示"不可见 + 不要 click"防 LLM 试图按 host 名幻觉生成 mark_id.
    """
    if not hosts:
        return ""
    return (
        f"# 跨域 iframe (LLM 不可见内容, 不要尝试 click): "
        f"{len(hosts)} 个 - {', '.join(hosts)}\n\n"
    )


def build_user_text(
    goal: str,
    marks: list[Mark],
    trace: Trace,
    *,
    tabs: list[tuple[int, str]] | None = None,
    current_idx: int = 0,
    cross_origin_hosts: list[str] | None = None,
) -> str:
    """构造各 provider plan() 通用的 user 消息 text 部分（截图 image block 由各 client 自己拼）。

    包括 goal、历史 trace JSON 序列化、(V0.21.2 加) tabs header、当前 SoM 元素清单、
    (V0.22.4 加) 跨域 iframe footer。Anthropic 和 OpenAI 共用此文本，差异只在 image content
    block 格式（Anthropic source.base64 vs OpenAI image_url data: URL）。

    V0.21.2: `tabs` 是 [(idx, title), ...] 列表 (loop 每 step 算好), `current_idx` 标记当前 active.
    V0.22.4: `cross_origin_hosts` 是 perceive 收集的跨域 iframe host 列表 (DFS 顺序去重).
    空 list / None 跳过对应 section (向后兼容老 caller).
    """
    history_text = (
        json.dumps(trace.for_llm(), ensure_ascii=False, indent=2)
        if trace.steps
        else "(空)"
    )
    tabs_section = _render_tabs_header(tabs or [], current_idx)
    cross_origin_section = _render_cross_origin_footer(cross_origin_hosts or [])
    return (
        f"# 任务目标\n{goal}\n\n"
        f"# 历史 Action Trace\n{history_text}\n\n"
        f"{tabs_section}"
        f"# 当前可交互元素清单（编号对应截图边框）\n{marks_to_text(marks)}\n\n"
        f"{cross_origin_section}"
        f"请通过 tool 返回下一步操作。"
    )
