"""中性 TOOL_SCHEMAS → provider tools 转换的纯函数测试。

不调用真实 LLM（无 key 依赖），只验证 schema 形状符合各 provider 要求。
"""

from __future__ import annotations

from web_agent.llm._schema import TOOL_SCHEMAS, to_anthropic_tools, to_openai_tools

EXPECTED_TOOL_NAMES = {
    "click",
    "type",
    "scroll",
    "extract",
    "done",
    "keyboard_shortcut",
    "paste",
    "switch_tab",
    "close_tab",
    "drag",
    "upload",
    "goto_url",
}


def test_neutral_schemas_have_12_tools_with_thought():
    assert {s["name"] for s in TOOL_SCHEMAS} == EXPECTED_TOOL_NAMES
    for s in TOOL_SCHEMAS:
        assert "thought" in s["properties"], f"{s['name']} 缺 thought 字段"
        assert "thought" in s["required"], f"{s['name']} thought 必须是 required"


def test_to_anthropic_tools_shape():
    tools = to_anthropic_tools()
    assert len(tools) == 12
    for t in tools:
        assert set(t.keys()) == {"name", "description", "input_schema"}
        assert t["input_schema"]["type"] == "object"
        assert "properties" in t["input_schema"]
        assert "required" in t["input_schema"]
    assert {t["name"] for t in tools} == EXPECTED_TOOL_NAMES


def test_to_openai_tools_strict_mode_invariants():
    """OpenAI strict mode 要求：
    1. function.strict = True
    2. parameters.additionalProperties = False
    3. parameters.required 必须包含所有 properties（即便业务上是 optional）
    """
    tools = to_openai_tools(strict=True)
    assert len(tools) == 12
    for t in tools:
        assert t["type"] == "function"
        f = t["function"]
        assert f["strict"] is True
        params = f["parameters"]
        assert params["type"] == "object"
        assert params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"].keys()), (
            f"{f['name']} strict mode 下 required 必须 == properties keys"
        )


def test_to_openai_tools_non_strict_keeps_business_required():
    tools = to_openai_tools(strict=False)
    type_tool = next(t for t in tools if t["function"]["name"] == "type")
    # 业务上 type.submit 是 optional，非 strict 模式应保留
    assert "submit" not in type_tool["function"]["parameters"]["required"]
    assert "additionalProperties" not in type_tool["function"]["parameters"]
    assert "strict" not in type_tool["function"]


def test_tool_descriptions_non_empty():
    """LLM 调用时缺 description 会大幅降低工具选择准确率。"""
    for s in TOOL_SCHEMAS:
        assert s["description"], f"{s['name']} description 为空"
        assert len(s["description"]) >= 5


def test_switch_tab_close_tab_schema_shape():
    """V0.21.0: switch_tab / close_tab 中性 schema 形状校验 (idx integer required)."""
    by_name = {s["name"]: s for s in TOOL_SCHEMAS}
    for tool_name in ("switch_tab", "close_tab"):
        s = by_name[tool_name]
        assert s["properties"]["idx"]["type"] == "integer", f"{tool_name}.idx 必须 integer"
        assert "idx" in s["required"], f"{tool_name} idx 必须 required"
        assert "thought" in s["required"]


def test_drag_schema_shape():
    """V0.23.0: drag 中性 schema (from_mark_id/to_mark_id integer required)."""
    by_name = {s["name"]: s for s in TOOL_SCHEMAS}
    s = by_name["drag"]
    for field in ("from_mark_id", "to_mark_id"):
        assert s["properties"][field]["type"] == "integer", f"drag.{field} 必须 integer"
        assert field in s["required"]


def test_goto_url_schema_shape():
    """V0.70.1: goto_url 中性 schema (url string required, thought required)."""
    by_name = {s["name"]: s for s in TOOL_SCHEMAS}
    s = by_name["goto_url"]
    assert s["properties"]["url"]["type"] == "string"
    assert "url" in s["required"]
    assert "thought" in s["required"]
    # description 应提及 mark click 失败的 fallback 场景
    assert "click" in s["description"] or "失败" in s["description"] or "url" in s["description"].lower()


def test_system_prompt_includes_goto_url_hint():
    """V0.70.1: SYSTEM_PROMPT rule-15 提示 goto_url fallback."""
    from web_agent.llm._schema import SYSTEM_PROMPT
    assert "goto_url" in SYSTEM_PROMPT
    # 提示位置: 跟 rule-14 失败恢复策略相关 (V0.69 dogfood mark 49 click 撞 anti-loop 根因)
    assert "fallback" in SYSTEM_PROMPT.lower() or "直" in SYSTEM_PROMPT or "无效" in SYSTEM_PROMPT


def test_upload_schema_shape():
    """V0.23.0: upload schema paths 是 array of string + required."""
    by_name = {s["name"]: s for s in TOOL_SCHEMAS}
    s = by_name["upload"]
    assert s["properties"]["mark_id"]["type"] == "integer"
    assert s["properties"]["paths"]["type"] == "array"
    assert s["properties"]["paths"]["items"]["type"] == "string"
    for field in ("thought", "mark_id", "paths"):
        assert field in s["required"], f"upload {field} 必须 required"


def test_system_prompt_includes_keyboard_navigation_clauses():
    """V0.24.2: SYSTEM_PROMPT 第 13 条键盘导航 (PageDown/Escape/Tab) 让 LLM 知道用 keyboard_shortcut.

    V0.19.0 keyboard_shortcut 已是通用工具但 SYSTEM_PROMPT 第 8 条只举编辑器场景 (Control+End/a),
    LLM 不会自己想到用 PageDown 滚长列表 / Escape 关 modal. V0.24.2 显式列候选清单提示 LLM.
    """
    from web_agent.llm._schema import SYSTEM_PROMPT
    # 关键键盘候选: 滚动 / 跳首末 / 关 modal / 切焦点
    for keyword in ("PageDown", "PageUp", "Home", "End", "Escape", "Tab"):
        assert keyword in SYSTEM_PROMPT, f"V0.24.2: SYSTEM_PROMPT 应含 {keyword!r} 键盘导航候选"
    # 关闭 modal 的语义提示
    assert "modal" in SYSTEM_PROMPT or "popover" in SYSTEM_PROMPT


def test_system_prompt_includes_failure_recovery_clauses():
    """V0.25.3: SYSTEM_PROMPT 第 14 条失败恢复策略 — LLM 看到 ERROR/reflect/backtrack 主动换思路.

    V0.25 系列 (smart retry + backtracking) 落档后 LLM 会看到新 obs 信号 (transient retry /
    [backtrack] 已回退 / 既有 [reflect]). 第 14 条显式说明每种信号的应对策略, 防 LLM 不知
    [backtrack] 后该换思路.
    """
    from web_agent.llm._schema import SYSTEM_PROMPT
    # 失败信号关键词
    for keyword in ("ERROR", "[reflect]", "[backtrack]", "LLM_FAILED", "transient"):
        assert keyword in SYSTEM_PROMPT, f"V0.25.3: SYSTEM_PROMPT 应含 {keyword!r} 失败信号"
    # 应对策略动词
    assert "换思路" in SYSTEM_PROMPT or "换策略" in SYSTEM_PROMPT


def test_system_prompt_includes_keyboard_chrome_level_warning():
    """V0.70.4 rule-16: keyboard_shortcut 仅作用页面层, 不开浏览器 chrome / DevTools.

    根因 (vanboard dogfood 4 task / trace.db audit): LLM 在 "用 console JS" task 上
    hallucinate `keyboard_shortcut("Control+Shift+J")` 反复按试图开 DevTools (Playwright
    `page.keyboard.press` 把键发到 page DOM, 不发到 Chrome chrome → 根本不会开 DevTools),
    撞 anti-loop. rule-16 显式警示让 LLM 早退而非死磕.
    """
    from web_agent.llm._schema import SYSTEM_PROMPT
    # 反例关键字 (LLM 应识别这些都不该用 keyboard_shortcut)
    for keyword in ("Control+Shift+J", "F12", "DevTools", "chrome"):
        assert keyword in SYSTEM_PROMPT, (
            f"V0.70.4 rule-16: SYSTEM_PROMPT 应含反例 {keyword!r}"
        )
    # chrome-level 能力不支持时 LLM 该 done 早退的指引
    assert "done" in SYSTEM_PROMPT and (
        "早退" in SYSTEM_PROMPT or "无法完成" in SYSTEM_PROMPT
    ), "V0.70.4 rule-16: 应指引 LLM 当 chrome-level task 时 done 早退"


def test_system_prompt_includes_no_nav_after_action_protocol():
    """V0.70.4 rule-17: `no_nav_after_action: true` 信号的处置 protocol.

    V0.70 注入 no_nav_after_action 字段进 trace JSON 但 SYSTEM_PROMPT 没解释含义.
    Qwen3-VL 真测看到 self-documenting key 仍重复同 mark + 撞 anti-loop. rule-17 显式说明
    "看到此字段 = 切 action type / 切 mark / done 早退", 让 LLM 不必"自己推断"含义.
    """
    from web_agent.llm._schema import SYSTEM_PROMPT
    assert "no_nav_after_action" in SYSTEM_PROMPT, (
        "V0.70.4 rule-17: SYSTEM_PROMPT 应明示 no_nav_after_action 字段含义"
    )
    # 处置指引: 切 action / 切 mark / 不要重发
    for keyword in ("切 action", "切 mark", "重发"):
        assert keyword in SYSTEM_PROMPT, (
            f"V0.70.4 rule-17: SYSTEM_PROMPT 应含 {keyword!r}"
        )


def test_v0707_rule_16_category_ban_and_goal_keyword_anchor():
    """V0.70.7 rule-16 加强: 类别 ban 措辞 + goal 关键字 anchor.

    V0.70.6 dogfood task 2 实证: LLM 仅 literal 理解 ban Ctrl+Shift+J, emit F12 (rule-16 反例 list 内)
    撞 anti-loop. V0.70.7 prompt 改 "凡是 chrome-level 快捷键一律不开" (类别 ban) + "goal 含
    chrome-level 关键字 → 第一步 done 早退" (rule-3 early anchor + rule-16 强复述).
    """
    from web_agent.llm._schema import SYSTEM_PROMPT
    # 类别 ban 措辞 (不再是 specific key list ban)
    assert "类别 ban" in SYSTEM_PROMPT or "凡是" in SYSTEM_PROMPT, (
        "V0.70.7 rule-16: 应有类别 ban 措辞防 LLM 字面理解 ban specific key"
    )
    assert "一律不开" in SYSTEM_PROMPT or "同类" in SYSTEM_PROMPT, (
        "V0.70.7 rule-16: 应明示同类全 ban (不是穷举反例)"
    )
    # goal 关键字 anchor (rule-3 早段 + rule-16 强复述)
    for keyword in ("console", "localStorage", "Runtime.evaluate"):
        assert keyword in SYSTEM_PROMPT, (
            f"V0.70.7 anchor: SYSTEM_PROMPT 应含 chrome-level 关键字示例 {keyword!r}"
        )
    # 第一步就 done 早退指引 (rule-3 + rule-16 加强)
    assert "第一步" in SYSTEM_PROMPT, (
        "V0.70.7 anchor: 应明示 chrome-level task 第一步就 done 早退, 不要试"
    )


def test_v0707_rule_17_consecutive_forced_done():
    """V0.70.7 rule-17 硬约束: 连续 2 步 no_nav signal 必须 done(放弃), 不再尝试第 3 次.

    V0.70.6 dogfood: LLM 看 no_nav signal 4 次仍连续 goto_url 撞 anti-loop. rule-17 软措辞
    ('✅ 连续 2 步 → done 早退') LLM 不 anchor. V0.70.7 改硬约束 ('必须 done 放弃' + 'anti-loop
    第 3 次硬 abort' 加恐吓).
    """
    from web_agent.llm._schema import SYSTEM_PROMPT
    # 硬约束措辞
    assert "必须" in SYSTEM_PROMPT and "放弃" in SYSTEM_PROMPT, (
        "V0.70.7 rule-17: 应改硬约束措辞 (必须 done 放弃, 不再尝试)"
    )
    # V0.70.6 goto_url 加入信号 nav-expecting actions list
    assert "goto_url" in SYSTEM_PROMPT, (
        "V0.70.6 加 goto_url 进 _NAV_EXPECTING_ACTIONS, rule-17 应反映"
    )
    # anti-loop 第 3 次硬 abort 加恐吓 (LLM 主动 done 比被 abort 可控)
    assert "第 3 次" in SYSTEM_PROMPT or "硬 abort" in SYSTEM_PROMPT, (
        "V0.70.7 rule-17: 应明示 anti-loop 第 3 次硬 abort, LLM 主动 done 更可控"
    )


def test_system_prompt_includes_multi_field_type_protocol():
    """V0.56.0 pilot #2: SYSTEM_PROMPT 第 7 条多字段 type 协议 example-driven 重写.

    Pilot 真测 #2 weak — "LLM 不熟 type 默认到 focused 协议". 原第 7 条单行裸文本协议已写但
    LLM 多字段表单仍连续 click→type 错序. V0.56.0 expand 到含正反例 example block.
    """
    from web_agent.llm._schema import SYSTEM_PROMPT
    # 严格交错 关键词 (LLM 看到此明示 click→type 严格交错)
    for keyword in ("严格交错", "click[5]", "click[7]", "焦点", "反例"):
        assert keyword in SYSTEM_PROMPT, f"V0.56.0: SYSTEM_PROMPT 应含 {keyword!r} 多字段 example"
    # 正反例 mark (LLM 视觉 cue)
    assert "✅" in SYSTEM_PROMPT
    assert "❌" in SYSTEM_PROMPT


# ---------- V0.21.2 build_user_text tabs header 渲染 ----------


def test_build_user_text_no_tabs_skips_header():
    """V0.21.2: 不传 tabs (老 caller / jd_extract 等) → header 不渲染, 向后兼容."""
    from web_agent.llm._schema import build_user_text
    from web_agent.trace import Trace
    text = build_user_text("做事", marks=[], trace=Trace(task_id="t", goal="做事"))
    assert "# 当前 Tabs" not in text


def test_build_user_text_single_tab_renders_header():
    """V0.21.2: 单 tab 也渲染 header (LLM 知道 tab 概念存在)."""
    from web_agent.llm._schema import build_user_text
    from web_agent.trace import Trace
    text = build_user_text(
        "做事", marks=[], trace=Trace(task_id="t", goal="做事"),
        tabs=[(0, "Inbox - Gmail")], current_idx=0,
    )
    assert "# 当前 Tabs (1 open, current=0)" in text
    assert '[0] "Inbox - Gmail"' in text


def test_build_user_text_multi_tab_marks_current():
    """V0.21.2: 多 tab + current_idx=1 → header 标 current=1, 列出全部 tab idx+title."""
    from web_agent.llm._schema import build_user_text
    from web_agent.trace import Trace
    text = build_user_text(
        "做事", marks=[], trace=Trace(task_id="t", goal="做事"),
        tabs=[(0, "Inbox"), (1, "GitHub"), (2, "SO")], current_idx=1,
    )
    assert "current=1)" in text
    for snippet in ('[0] "Inbox"', '[1] "GitHub"', '[2] "SO"'):
        assert snippet in text


def test_build_user_text_truncates_long_title():
    """V0.21.2: title >60 字符截断 (防 SEO 堆词污染上下文)."""
    from web_agent.llm._schema import build_user_text
    from web_agent.trace import Trace
    long_title = "A" * 200
    text = build_user_text(
        "做事", marks=[], trace=Trace(task_id="t", goal="做事"),
        tabs=[(0, long_title)], current_idx=0,
    )
    # 截 60 字符
    assert "A" * 60 in text
    assert "A" * 61 not in text


def test_build_user_text_tabs_header_position_before_marks():
    """V0.21.2: header 出现在 marks 之前 (LLM 先看 tabs 状态再读 marks 动作面板)."""
    from web_agent.llm._schema import build_user_text
    from web_agent.trace import Trace
    text = build_user_text(
        "做事", marks=[], trace=Trace(task_id="t", goal="做事"),
        tabs=[(0, "X")], current_idx=0,
    )
    tabs_pos = text.index("# 当前 Tabs")
    marks_pos = text.index("# 当前可交互元素清单")
    assert tabs_pos < marks_pos, "tabs header 应在 marks 之前"


# ---------- V0.22.4 cross_origin_hosts footer ----------


def test_build_user_text_no_cross_origin_hosts_skips_footer():
    """V0.22.4: 不传 / 空 list → footer 不渲染 (向后兼容)."""
    from web_agent.llm._schema import build_user_text
    from web_agent.trace import Trace
    text = build_user_text("做事", marks=[], trace=Trace(task_id="t", goal="做事"))
    assert "跨域 iframe" not in text
    text2 = build_user_text(
        "做事", marks=[], trace=Trace(task_id="t", goal="做事"),
        cross_origin_hosts=[],
    )
    assert "跨域 iframe" not in text2


def test_build_user_text_renders_cross_origin_hosts_with_count_and_warning():
    """V0.22.4: 多 host → 渲染含数量 + host list + 不要 click 警告."""
    from web_agent.llm._schema import build_user_text
    from web_agent.trace import Trace
    text = build_user_text(
        "做事", marks=[], trace=Trace(task_id="t", goal="做事"),
        cross_origin_hosts=["stripe.com", "www.google.com"],
    )
    assert "2 个" in text
    assert "stripe.com" in text
    assert "www.google.com" in text
    assert "不要尝试 click" in text, "文案必须明示不可点防 LLM 幻觉 mark_id"


def test_build_user_text_cross_origin_footer_after_marks():
    """V0.22.4: footer 在 marks 之后 (跟 tabs header 在前对称: header=context, footer=marks 注脚)."""
    from web_agent.llm._schema import build_user_text
    from web_agent.trace import Trace
    text = build_user_text(
        "做事", marks=[], trace=Trace(task_id="t", goal="做事"),
        cross_origin_hosts=["x.example"],
    )
    marks_pos = text.index("# 当前可交互元素清单")
    footer_pos = text.index("# 跨域 iframe")
    assert marks_pos < footer_pos, "cross-origin footer 应在 marks 之后 (注脚而非 context)"
    # 同时确认在 "请通过 tool 返回" 之前 (不是被推到末尾)
    end_pos = text.index("请通过 tool 返回")
    assert footer_pos < end_pos
