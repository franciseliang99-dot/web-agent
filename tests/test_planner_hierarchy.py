"""W5-C 分层规划单测: should_decompose 启发式 + subgoal hint 拼接。"""

from __future__ import annotations

import pytest

from web_agent.planner_hierarchy import (
    build_subgoal_hint_text,
    merge_into_memories,
    should_decompose,
)


# ---------- should_decompose ----------

def test_short_simple_goal_skipped(monkeypatch):
    monkeypatch.delenv("WEB_AGENT_SUBGOAL_DISABLE", raising=False)
    assert should_decompose("搜苹果价格") is False
    assert should_decompose("订机票") is False
    assert should_decompose("") is False


def test_long_goal_triggers(monkeypatch):
    """≥200 字符任务命中长度阈值。"""
    monkeypatch.delenv("WEB_AGENT_SUBGOAL_DISABLE", raising=False)
    long_goal = "x" * 250
    assert should_decompose(long_goal) is True


def test_numbered_goal_triggers(monkeypatch):
    """带 ≥2 个 1. / 2. 序号即触发, 即使总长短。"""
    monkeypatch.delenv("WEB_AGENT_SUBGOAL_DISABLE", raising=False)
    assert should_decompose("1. 搜苹果\n2. 加购\n3. 结账") is True
    assert should_decompose("1) 登录\n2) 搜索") is True


def test_circled_numbered_triggers(monkeypatch):
    """① ② 中文圆圈数字也触发。"""
    monkeypatch.delenv("WEB_AGENT_SUBGOAL_DISABLE", raising=False)
    assert should_decompose("① 登录 Gmail\n② 撰写邮件\n③ 发送") is True


def test_dash_bullet_triggers(monkeypatch):
    """- bullet 列表也触发 (≥2 项)。"""
    monkeypatch.delenv("WEB_AGENT_SUBGOAL_DISABLE", raising=False)
    assert should_decompose("- 步骤 A\n- 步骤 B\n- 步骤 C") is True


def test_single_numbered_short_goal_not_triggered(monkeypatch):
    """仅 1 个序号且短任务不触发。"""
    monkeypatch.delenv("WEB_AGENT_SUBGOAL_DISABLE", raising=False)
    assert should_decompose("1. 搜苹果") is False


@pytest.mark.parametrize("disable_value", ["true", "True", "1", "yes"])
def test_env_disable_overrides_all(monkeypatch, disable_value):
    """WEB_AGENT_SUBGOAL_DISABLE 任何 truthy 值都关闭 (即使长任务)。"""
    monkeypatch.setenv("WEB_AGENT_SUBGOAL_DISABLE", disable_value)
    assert should_decompose("x" * 500) is False
    assert should_decompose("1. a\n2. b\n3. c") is False


# ---------- build_subgoal_hint_text + merge_into_memories ----------

def test_build_subgoal_hint_contains_keyword():
    hint = build_subgoal_hint_text()
    assert "subgoal" in hint.lower()
    assert "thought" in hint
    assert "3-6" in hint  # 推荐 subgoal 数量


def test_merge_into_memories_appends_with_separator():
    out = merge_into_memories("过去在 x.com 跑过 2 次", "subgoal hint")
    assert "过去在 x.com 跑过 2 次" in out
    assert "subgoal hint" in out
    assert "\n\n" in out  # 分隔符


def test_merge_into_memories_empty_existing():
    out = merge_into_memories(None, "subgoal hint")
    assert out == "subgoal hint"
    out2 = merge_into_memories("", "subgoal hint")
    assert out2 == "subgoal hint"


def test_merge_into_memories_empty_subgoal():
    out = merge_into_memories("memories text", "")
    assert out == "memories text"
