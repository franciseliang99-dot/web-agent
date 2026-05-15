"""V0.70 no-nav-after-action signal — TDD red.

V0.69 已让 LLM 看 url 变化 (nav_side_effect), 但**沉默 absence** 当 url 不变.
V0.69 dogfood (Supabase): mark 49 click 后 url 没变, LLM Qwen3-VL 没察觉"click 无效"
连点 3 次撞 anti-loop. V0.70 把"沉默 negative"翻成"显式 positive":
- 仅 nav-expecting action (click/keyboard_shortcut/switch_tab/type) + url_before==url_after
  + 两者非空 → for_llm 注入 no_nav_after_action: True
- 非 nav-expecting action (extract/scroll/done) 不触发 (那些本就不该 nav)
"""

from __future__ import annotations

from web_agent.trace import Step


def _make_step(**overrides):
    base = {
        "step": 0,
        "ts": 1234.5,
        "thought": "test",
        "action_type": "click",
        "action_args": {"mark_id": 49},
    }
    base.update(overrides)
    return Step(**base)


def test_click_url_unchanged_emits_no_nav_after_action():
    """click 后 url 没变 (Supabase mark 49 真场景) → for_llm 有 no_nav_after_action: True."""
    s = _make_step(
        action_type="click",
        url_before="https://supabase.com/dashboard/x/auth/url-configuration",
        url_after="https://supabase.com/dashboard/x/auth/url-configuration",
    )
    d = s.for_llm()
    assert d.get("no_nav_after_action") is True
    assert "nav_side_effect" not in d  # url 没变, V0.69 字段不出


def test_extract_url_unchanged_omits_no_nav_after_action():
    """extract 本就不该 nav, url 不变正常, 不触发 no_nav signal (避免 LLM 误解)."""
    s = _make_step(
        action_type="extract",
        action_args={"query": "title", "answer": "Example"},
        url_before="https://example.com/",
        url_after="https://example.com/",
    )
    d = s.for_llm()
    assert "no_nav_after_action" not in d


def test_scroll_url_unchanged_omits_no_nav_after_action():
    """scroll 本就不该 nav, 不触发."""
    s = _make_step(
        action_type="scroll",
        action_args={"dy": 400},
        url_before="https://example.com/",
        url_after="https://example.com/",
    )
    d = s.for_llm()
    assert "no_nav_after_action" not in d


def test_keyboard_shortcut_url_changed_still_uses_nav_side_effect():
    """V0.70 不破 V0.69: keyboard_shortcut url 变了仍走 nav_side_effect 不走 no_nav."""
    s = _make_step(
        action_type="keyboard_shortcut",
        action_args={"key": "Control+a"},
        url_before="https://supabase.com/dashboard/x/auth/url-configuration",
        url_after="https://example.com/",  # Ctrl+A 副作用跳页
    )
    d = s.for_llm()
    assert "nav_side_effect" in d
    assert "no_nav_after_action" not in d  # url 变了, no_nav 不该触发


def test_keyboard_shortcut_url_unchanged_emits_no_nav():
    """keyboard_shortcut url 没变 → no_nav signal (Ctrl+S save 类期望 stay-page; 但也可能是
    Ctrl+Enter submit 无效). LLM 自己判. 信号给到即可."""
    s = _make_step(
        action_type="keyboard_shortcut",
        action_args={"key": "Control+Enter"},
        url_before="https://example.com/form",
        url_after="https://example.com/form",
    )
    d = s.for_llm()
    assert d.get("no_nav_after_action") is True


def test_empty_url_fields_omit_no_nav_after_action():
    """老 trace (url_before/after 都空) → no_nav 不触发 (向后兼容)."""
    s = _make_step(action_type="click")  # 默认空 url
    d = s.for_llm()
    assert "no_nav_after_action" not in d
    assert "nav_side_effect" not in d


def test_one_empty_one_set_omits_no_nav_after_action():
    """边界: 仅一侧 snap (loop 异常 / mock 缺一边) → 既不该 no_nav 也不该 nav_side_effect."""
    s = _make_step(
        action_type="click",
        url_before="https://example.com/",
        url_after="",
    )
    d = s.for_llm()
    assert "no_nav_after_action" not in d
    assert "nav_side_effect" not in d


def test_switch_tab_url_unchanged_emits_no_nav():
    """switch_tab 期望切到不同 page (URL 变); 没变 = 目标 tab 跟当前同 URL = no-op signal."""
    s = _make_step(
        action_type="switch_tab",
        action_args={"idx": 1},
        url_before="https://example.com/",
        url_after="https://example.com/",
    )
    d = s.for_llm()
    assert d.get("no_nav_after_action") is True


def test_type_url_unchanged_emits_no_nav():
    """type 后 url 没变 = type 没触发 submit-nav. 输入框 type 期望 stay-page, 但若 LLM
    submit=true 期望 nav, 没 nav 就是 signal. 不区分 args.submit, 给信号让 LLM 判."""
    s = _make_step(
        action_type="type",
        action_args={"text": "https://vanboard.vercel.app", "submit": True},
        url_before="https://supabase.com/dashboard/x/auth/url-configuration",
        url_after="https://supabase.com/dashboard/x/auth/url-configuration",
    )
    d = s.for_llm()
    assert d.get("no_nav_after_action") is True


def test_goto_url_url_unchanged_emits_no_nav_after_action():
    """V0.70.6: goto_url 后 url 未变 (反复 goto 同 URL) → no_nav_after_action: True.

    V0.70.4 dogfood task 2 (`6b48e8895a0e`, 2026-05-14 18:11) 跑 10 次相同
    `goto_url("http://localhost:3000/")`, url_before==url_after 每步成立, 但因
    `_NAV_EXPECTING_ACTIONS` 漏 goto_url, signal 一次没注入 → SYSTEM_PROMPT rule-17 在
    goto_url-LOOP 场景空话. V0.70.6 加 goto_url 进 set, signal 触发后 LLM 应切策略或 done 早退.
    """
    s = _make_step(
        action_type="goto_url",
        action_args={"url": "http://localhost:3000/"},
        url_before="http://localhost:3000/",
        url_after="http://localhost:3000/",
    )
    d = s.for_llm()
    assert d.get("no_nav_after_action") is True
