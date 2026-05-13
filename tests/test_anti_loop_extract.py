"""V0.46.1 真发现 #25 follow-up unit test — ExtractAction sig normalize + 5-window alternation detector.

V0.44.0 trace.db audit catch HN WALLCLOCK task (ac3abe2dd358) 11 step 全 extract action,
anti_loop miss 因 signature 漂移. V0.46.1 双修:
1. _normalize_extract_query: lowercase + strip punctuation + collapse whitespace
2. 5-window deque + count(any sig) ≥ 3 alternation detector

本测覆盖 fix 关键判据:
- normalize 后 V0.44 step 5/7/10 同 sig + step 6/8/9 同 sig (字面相同)
- 5-window detector catch alternation [A,B,A,B,B] (V0.5.0 3-连续相同 miss)
- normalize 不 over-collapse 不同意图 query
- 5-window 不 false-pos 5 不同 sig (合理 progression)
"""

from __future__ import annotations

from collections import Counter, deque

import pytest

from web_agent.loop import _action_signature, _normalize_extract_query
from web_agent.types import ClickAction, ExtractAction


# --- _normalize_extract_query unit ---


def test_normalize_extract_query_lowercases() -> None:
    assert _normalize_extract_query("Hello World") == "hello world"


def test_normalize_extract_query_strips_punctuation() -> None:
    assert _normalize_extract_query('帖子的"points 数"（投票数）') == "帖子的points 数投票数"


def test_normalize_extract_query_collapses_whitespace() -> None:
    assert _normalize_extract_query("a  b\t\nc") == "a b c"


def test_normalize_extract_query_preserves_cjk_and_alphanumeric() -> None:
    """V0.46.1: CJK 字符 + alphanumeric 应保留 (regex [^\\w\\s一-鿿] strips punctuation only)."""
    out = _normalize_extract_query("Three Inverse Laws of AI 标题")
    assert "three" in out and "inverse" in out and "ai" in out and "标题" in out


def test_normalize_extract_query_no_truncate_preserves_unique_intent() -> None:
    """V0.46.1: 不 truncate (避免 over-collapse 不同意图的 query). 长 query 全文比对."""
    q1 = _normalize_extract_query("读取 HN #1 帖子的标题")
    q2 = _normalize_extract_query("读取 HN #2 帖子的标题")
    assert q1 != q2  # 不同 intent (#1 vs #2) 不应 collapse


# --- _action_signature ExtractAction branch ---


def test_extract_signature_drops_answer_collapses_same_query() -> None:
    """V0.46.1: 字面相同 query, 不同 answer → 同 sig (answer LLM noise drop)."""
    a1 = ExtractAction(thought="t1", query="读取 points", answer="我无法读取")
    a2 = ExtractAction(thought="t2", query="读取 points", answer="让我重新查看")
    assert _action_signature(a1) == _action_signature(a2)


def test_extract_signature_normalize_collapses_wording_variants() -> None:
    """V0.46.1: 大小写 + 标点变体 query (相同内容词 + 相同 token 位置) normalize 后 → 同 sig."""
    a1 = ExtractAction(thought="t1", query="读取 Points 数", answer="ans1")
    a2 = ExtractAction(thought="t2", query="读取 points 数.", answer="ans2")  # 仅大小写 + 末尾 .
    assert _action_signature(a1) == _action_signature(a2)


def test_extract_signature_different_intent_different_sig() -> None:
    """V0.46.1: 不同 intent (#1 vs #2) 仍不同 sig."""
    a1 = ExtractAction(thought="t1", query="读取 HN #1", answer="x")
    a2 = ExtractAction(thought="t2", query="读取 HN #2", answer="x")
    assert _action_signature(a1) != _action_signature(a2)


# --- V0.44 trace 真实 11 query alternation 测 ---

# V0.44 真实 trace.db ac3abe2dd358 task step 0-10 query (sqlite3 dump)
_V044_TRACE_11_QUERIES: list[str] = [
    "Hacker News 首页 #1 帖子的标题和 points 数",
    "Hacker News 首页 #1 帖子 \"Three Inverse Laws of AI\" 的 points 数（投票数）",
    "读取 Hacker News 首页第一条帖子左侧的 points 数字文本，位于 upvote 箭头和 downvote 箭头之间",
    "读取 Hacker News 首页第一条帖子 \"Three Inverse Laws of AI\" 的完整信息",
    "读取 Hacker News 首页第一条帖子左侧的 points 数字，该数字位于 upvote 箭头下方",
    "读取 Hacker News 首页第一条帖子 \"Three Inverse Laws of AI\" 左侧的 points 数字，该数字位于 upvote 箭头下方",  # noqa: E501
    "读取 Hacker News 首页第一条帖子 \"Three Inverse Laws of AI\" 左侧的 points 数字文本",
    "读取 Hacker News 首页第一条帖子 \"Three Inverse Laws of AI\" 左侧的 points 数字，该数字位于 upvote 箭头下方",  # noqa: E501
    "读取 Hacker News 首页第一条帖子 \"Three Inverse Laws of AI\" 左侧的 points 数字文本",
    "读取 Hacker News 首页第一条帖子 \"Three Inverse Laws of AI\" 左侧的 points 数字文本",
    "读取 Hacker News 首页第一条帖子 \"Three Inverse Laws of AI\" 左侧的 points 数字，该数字位于 upvote 箭头下方",  # noqa: E501
]


def test_v044_alternation_caught_by_5window_detector_by_step_9() -> None:
    """V0.46.1 真测: V0.44 真实 11 query, 5-window detector 应 by step ≤9 trigger.

    V0.5.0 3-连续相同 detector miss alternation. V0.46.1 5-window + count≥3 catch.
    """
    sigs = [
        _action_signature(ExtractAction(thought=f"t{i}", query=q, answer=f"ans{i}"))
        for i, q in enumerate(_V044_TRACE_11_QUERIES)
    ]
    window: deque[str] = deque(maxlen=5)
    triggered_at = None
    for i, sig in enumerate(sigs):
        candidate = (list(window) + [sig])[-5:]
        if len(candidate) >= 5 and Counter(candidate).most_common(1)[0][1] >= 3:
            triggered_at = i
            break
        window.append(sig)
    assert triggered_at is not None, (
        f"V0.46.1 5-window detector 应 trigger V0.44 11 query alternation, 但全 11 step 都没 trigger. "
        f"sigs (truncated 50): {[s[:50] for s in sigs]}"
    )
    assert triggered_at <= 9, f"V0.46.1: 应 by step ≤9 trigger, 实际 step {triggered_at}"


def test_v044_v50_3consecutive_detector_misses_alternation() -> None:
    """V0.5.0 3-连续相同 detector 不 catch V0.44 alternation pattern (因 [A,B,A] 不全同).

    本测保证 V0.5.0 行为不变, V0.46.1 是 additive (新加 alternation detector 不破 V0.5.0).
    """
    sigs = [
        _action_signature(ExtractAction(thought=f"t{i}", query=q, answer=f"ans{i}"))
        for i, q in enumerate(_V044_TRACE_11_QUERIES)
    ]
    recent: deque[str] = deque(maxlen=3)
    triggered_at = None
    for i, sig in enumerate(sigs):
        if len(recent) == 3 and all(s == sig for s in recent):
            triggered_at = i
            break
        recent.append(sig)
    assert triggered_at is None, (
        f"V0.5.0 detector 不应 catch V0.44 alternation, 但 trigger at step {triggered_at}. "
        f"sigs: {[s[:30] for s in sigs]}"
    )


# --- 5-window 不 false-pos 测 ---


def test_5window_does_not_trigger_on_5_unique_sigs() -> None:
    """V0.46.1: 合理 progression 5 个不同 sig 不应 trigger (false-pos guard)."""
    # 5 个不同 mark_id click — 真实"依次 click [1],[2],[3],[4],[5]" 合理 task
    actions = [ClickAction(thought=f"t{i}", mark_id=i) for i in range(1, 6)]
    sigs = [_action_signature(a) for a in actions]
    window: deque[str] = deque(maxlen=5)
    for sig in sigs:
        candidate = (list(window) + [sig])[-5:]
        assert not (
            len(candidate) >= 5 and Counter(candidate).most_common(1)[0][1] >= 3
        ), f"V0.46.1 false-pos: 5 unique sig 不应 trigger, sigs={sigs}"
        window.append(sig)


def test_5window_does_not_trigger_with_only_2_same() -> None:
    """V0.46.1: window 内最多 2 同 sig 不应 trigger (需 ≥ 3 same)."""
    # [A, B, A, C, D] — A=2, B=1, C=1, D=1, max=2 → 不 trigger
    sigs = ["A", "B", "A", "C", "D"]
    window: deque[str] = deque(maxlen=5)
    for sig in sigs:
        candidate = (list(window) + [sig])[-5:]
        triggered = (
            len(candidate) >= 5 and Counter(candidate).most_common(1)[0][1] >= 3
        )
        assert not triggered, f"V0.46.1: A=2 不应 trigger, candidate={candidate}"
        window.append(sig)


# --- V0.55.0 pilot #3: _action_signature 加 url prefix (跨页 ping-pong catch) ---


def test_action_signature_url_prefix_separates_cross_page() -> None:
    """V0.55.0: 同 mark_id (5) 在 page-A 跟 page-B sig 不同 (cross-page 区分)."""
    action = ClickAction(thought="t", mark_id=5)
    sig_a = _action_signature(action, url="https://a.test/page1")
    sig_b = _action_signature(action, url="https://b.test/page2")
    assert sig_a != sig_b, "V0.55.0: 跨页同 action sig 应不同 (url prefix 区分)"
    assert "a.test" in sig_a
    assert "b.test" in sig_b


def test_action_signature_default_empty_url_backward_compat() -> None:
    """V0.55.0: url="" (default) 保 V0.46.1 既有行为 (sig 不含 @url# prefix)."""
    action = ClickAction(thought="t", mark_id=5)
    sig_default = _action_signature(action)
    sig_empty = _action_signature(action, url="")
    assert sig_default == sig_empty
    assert not sig_default.startswith("@")  # 无 @url# prefix


def test_action_signature_url_truncated_80_char() -> None:
    """V0.55.0: long URL prefix 截 80 char 防 query string noise + 仍区分 path."""
    action = ClickAction(thought="t", mark_id=1)
    long_url_a = "https://example.com/path/a?query=" + "x" * 200
    long_url_b = "https://example.com/path/b?query=" + "x" * 200
    sig_a = _action_signature(action, url=long_url_a)
    sig_b = _action_signature(action, url=long_url_b)
    # 前 80 char 含 path 区分 (path/a vs path/b 在 33-40 char 位)
    assert sig_a != sig_b


def test_v055_cross_page_ping_pong_caught_by_5window() -> None:
    """V0.55.0: 跨页 ping-pong [A_click:5, B_click:5, A_click:5, B_click:5, A_click:5] →
    5-window count(any sig) ≥ 3 catch. V0.46.1 detector 经 V0.55 url prefix 后能 catch cross-page.
    """
    action_5 = ClickAction(thought="t", mark_id=5)
    url_a = "https://a.test/"
    url_b = "https://b.test/"
    sigs = [
        _action_signature(action_5, url_a),  # step 0: A
        _action_signature(action_5, url_b),  # step 1: B
        _action_signature(action_5, url_a),  # step 2: A
        _action_signature(action_5, url_b),  # step 3: B
        _action_signature(action_5, url_a),  # step 4: A → window=[A,B,A,B,A] A=3 catch
    ]
    window: deque[str] = deque(maxlen=5)
    triggered_at = None
    for i, sig in enumerate(sigs):
        candidate = (list(window) + [sig])[-5:]
        if len(candidate) >= 5 and Counter(candidate).most_common(1)[0][1] >= 3:
            triggered_at = i
            break
        window.append(sig)
    assert triggered_at == 4, (
        f"V0.55.0: 跨页 ping-pong 应 by step 4 trigger (A 出现 3 次), 实际 step {triggered_at}"
    )


def test_v055_cross_page_no_ping_pong_no_trigger() -> None:
    """V0.55.0: 合理跨页 navigation (各 url 唯一访) 不 trigger (false-pos guard)."""
    action_5 = ClickAction(thought="t", mark_id=5)
    sigs = [
        _action_signature(action_5, f"https://page{i}.test/")
        for i in range(5)
    ]
    window: deque[str] = deque(maxlen=5)
    for sig in sigs:
        candidate = (list(window) + [sig])[-5:]
        triggered = (
            len(candidate) >= 5 and Counter(candidate).most_common(1)[0][1] >= 3
        )
        assert not triggered, f"V0.55.0: 5 唯一 url 不应 trigger, sigs={sigs}"
        window.append(sig)


# --- V0.46.1 5-window pattern matrix (continued from above) ---


@pytest.mark.parametrize("pattern,should_trigger,expected_step", [
    (["A", "B", "A", "B", "A"], True, 4),       # A=3, B=2 at step 4 (alternation)
    # 注: 3-连续相同 [A,A,A,...] 由 V0.5.0 detector at step 2 catch (本测仅覆盖 V0.46.1 5-window,
    # V0.5.0 单测在 tests/test_loop_anti_loop.py). 此处 5-window detector at step 4 trigger.
    (["A", "A", "A", "B", "C"], True, 4),       # 5-window A=3 at step 4 (V0.5.0 真实生产 step 2 catch)
    (["A", "B", "C", "A", "B"], False, None),   # all ≤ 2 same
    (["A", "B", "C", "D", "E"], False, None),   # all unique
    (["A", "B", "A", "C", "A"], True, 4),       # A=3 at step 4
])
def test_5window_alternation_pattern_matrix(
    pattern: list[str], should_trigger: bool, expected_step: int | None,
) -> None:
    """V0.46.1: 5-window alternation detector 各 pattern 真值表."""
    window: deque[str] = deque(maxlen=5)
    triggered_at = None
    for i, sig in enumerate(pattern):
        candidate = (list(window) + [sig])[-5:]
        if len(candidate) >= 5 and Counter(candidate).most_common(1)[0][1] >= 3:
            triggered_at = i
            break
        window.append(sig)
    if should_trigger:
        assert triggered_at == expected_step, (
            f"V0.46.1 pattern {pattern}: 应 trigger at step {expected_step}, "
            f"实际 step {triggered_at}"
        )
    else:
        assert triggered_at is None, (
            f"V0.46.1 pattern {pattern}: 不应 trigger 但 step {triggered_at} trigger"
        )
