"""V0.16.20 W5-C.2 logging spike: instrumentation 验证 (regex + jsonl write).

不跑 LLM/Chrome — 直接构造 Trace 喂给 _dump_spike_metrics, 检查输出文件 schema 与指标判定.
"""

from __future__ import annotations

import json

from web_agent.loop import (
    _dump_spike_metrics,
    _SPIKE_M1_RE,
    _SPIKE_M2_RE,
    _SPIKE_M5_RE,
)
from web_agent.trace import Step, Trace


# ===== regex 单元判定 =====


def test_M1_chinese_subgoal_marker_hits():
    """中文 subgoal 标记词 (子目标 / 步骤 N / 第 N 步 / 序号前缀) 命中."""
    cases = [
        "目前在子目标 2",
        "执行步骤 3 的搜索动作",
        "已完成第 1 步, 进入第 2 步",
        "1. 搜索 2. 筛选 3. 点击",
        "① 输入 ② 提交",
    ]
    for thought in cases:
        assert _SPIKE_M1_RE.search(thought), f"M1 should match: {thought!r}"


def test_M1_english_subgoal_marker_hits():
    """英文 subgoal 标记词 (first / then / next / finally / step N) 命中."""
    cases = [
        "First I will search the box",
        "Then I click the link",
        "Next, scroll down",
        "Step 2: extract data",
        "Finally, return result",
    ]
    for thought in cases:
        assert _SPIKE_M1_RE.search(thought), f"M1 should match: {thought!r}"


def test_M1_no_marker_no_match():
    """纯执行描述 (无 subgoal 标记) 不命中."""
    cases = [
        "I clicked the button.",
        "Found the search input on the top",
        "页面已加载完成",
        "extract title text",
    ]
    for thought in cases:
        assert not _SPIKE_M1_RE.search(thought), f"M1 should NOT match: {thought!r}"


def test_M2_plan_referenced_chinese():
    """中文 plan 引用 (目前/当前在第 N 步, 按计划) 命中."""
    cases = [
        "目前在第 2 步",
        "当前在步骤 3 的执行阶段",
        "现在在 subgoal 2",
        "按计划应该先点击搜索框",
        "根据上面拆出的 4 个 subgoal, 先做第一个",
    ]
    for thought in cases:
        assert _SPIKE_M2_RE.search(thought), f"M2 should match: {thought!r}"


def test_M2_plan_referenced_english():
    """英文 plan 引用 (currently on/at subgoal, according to the plan, as planned) 命中."""
    cases = [
        "Currently on subgoal 3",
        "Currently at step 2 of the plan",
        "According to the plan, click submit next",
        "Continuing as planned, scroll to load more",
    ]
    for thought in cases:
        assert _SPIKE_M2_RE.search(thought), f"M2 should match: {thought!r}"


def test_M5_revision_on_failure_hits():
    """换/改/重新 + 策略/方法/思路/方案/路径 / try another / switch strategy 命中."""
    cases = [
        "换一种策略, 尝试 scroll 看下",
        "改用另一个方法定位元素",
        "重新规划路径",
        "Try a different approach",
        "Switch strategy: scroll instead of click",
    ]
    for thought in cases:
        assert _SPIKE_M5_RE.search(thought), f"M5 should match: {thought!r}"


# ===== _dump_spike_metrics 写文件行为 =====


def _make_trace(task_id: str = "test123", goal: str = "test goal", steps_data=None) -> Trace:
    trace = Trace(task_id=task_id, goal=goal)
    for s in steps_data or []:
        trace.append(Step(**s))
    return trace


def test_dump_disabled_by_default_no_file(tmp_path, monkeypatch):
    """env WEB_AGENT_SPIKE_W5C2 未设 → noop, 不写任何文件."""
    monkeypatch.delenv("WEB_AGENT_SPIKE_W5C2", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    trace = _make_trace(steps_data=[
        {"step": 0, "ts": 1.0, "thought": "first I will search", "action_type": "click",
         "action_args": {}, "observation": "clicked"},
    ])
    _dump_spike_metrics("abc", "goal", trace)
    out_dir = tmp_path / ".cache" / "web-agent" / "spike-w5c2"
    assert not out_dir.exists() or not list(out_dir.glob("*.jsonl"))


def test_dump_enabled_writes_jsonl(tmp_path, monkeypatch):
    """env=1 → 写 jsonl, schema 字段齐全, M1/M2/M5/is_failure_step 判定正确."""
    monkeypatch.setenv("WEB_AGENT_SPIKE_W5C2", "1")
    monkeypatch.setenv("WEB_AGENT_SPIKE_TASK_LABEL", "07")
    monkeypatch.setenv("HOME", str(tmp_path))
    trace = _make_trace(steps_data=[
        {"step": 0, "ts": 1.0, "thought": "First I search the box, then I click", "action_type": "click",
         "action_args": {"mark_id": 3}, "observation": "clicked [3] input 'search'"},
        {"step": 1, "ts": 2.0, "thought": "Currently at subgoal 2, extracting result", "action_type": "extract",
         "action_args": {"answer": "1969"}, "observation": "extracted: 1969"},
        {"step": 2, "ts": 3.0, "thought": "换一种策略, 重新搜索", "action_type": "click",
         "action_args": {"mark_id": 5}, "observation": "ERROR: mark_id=5 不在当前 marks 里"},
    ])
    _dump_spike_metrics("xyz789", "find Linus birth year", trace)

    out_dir = tmp_path / ".cache" / "web-agent" / "spike-w5c2"
    files = list(out_dir.glob("07-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3

    rows = [json.loads(ln) for ln in lines]
    assert rows[0]["task_id"] == "xyz789"
    assert rows[0]["task_label"] == "07"
    assert rows[0]["step"] == 0
    assert rows[0]["action_type"] == "click"
    assert rows[0]["M1"] is True   # "First I" + "then I"
    assert rows[0]["is_failure_step"] is False

    assert rows[1]["M2"] is True   # "Currently at subgoal"
    assert rows[1]["is_failure_step"] is False

    assert rows[2]["is_failure_step"] is True   # observation 含 ERROR
    assert rows[2]["M5"] is True   # "换一种策略"


def test_dump_skips_synthetic_memory_step(tmp_path, monkeypatch):
    """W5-D.2 step=-1 (memory_recall synthetic) 跳过, 不进 jsonl."""
    monkeypatch.setenv("WEB_AGENT_SPIKE_W5C2", "1")
    monkeypatch.setenv("WEB_AGENT_SPIKE_TASK_LABEL", "01")
    monkeypatch.setenv("HOME", str(tmp_path))
    trace = _make_trace(steps_data=[
        {"step": -1, "ts": 0.5, "thought": "(W5-D.2 长期记忆召回)", "action_type": "memory_recall",
         "action_args": {}, "observation": "past memories ..."},
        {"step": 0, "ts": 1.0, "thought": "real first step", "action_type": "click",
         "action_args": {}, "observation": "clicked"},
    ])
    _dump_spike_metrics("aaa111", "goal", trace)

    files = list((tmp_path / ".cache" / "web-agent" / "spike-w5c2").glob("01-*.jsonl"))
    rows = [json.loads(ln) for ln in files[0].read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["step"] == 0


def test_dump_silent_swallow_on_io_error(tmp_path, monkeypatch):
    """路径不可写不抛异常 (spike 不该阻塞主路径)."""
    monkeypatch.setenv("WEB_AGENT_SPIKE_W5C2", "1")
    # 把 HOME 指向只读路径触发 mkdir 失败
    bad = tmp_path / "readonly"
    bad.mkdir()
    bad.chmod(0o444)
    monkeypatch.setenv("HOME", str(bad))
    trace = _make_trace(steps_data=[
        {"step": 0, "ts": 1.0, "thought": "x", "action_type": "click",
         "action_args": {}, "observation": "ok"},
    ])
    # 不应抛
    _dump_spike_metrics("id", "goal", trace)
    bad.chmod(0o755)  # cleanup
