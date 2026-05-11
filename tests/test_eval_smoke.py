"""V0.26.3: web-agent-eval CLI smoke + opt-in env 双保险测.

不真跑 chromium / 真 LLM (RUN_EVAL=0 默认). 验:
- CLI 不设 RUN_EVAL=1 → exit 1 + stderr 提示
- CLI --lint-only 不需 RUN_EVAL=1 (lint 0 token 0 chromium)
- _check_real_eval_or_cassette: cassette 不存在 + EVAL_REAL=0 → exit 1 提示

真跑 eval 端到端留 V0.26.4 baseline 录 cassette 后跑 (本 commit cassette dir 空 .gitkeep).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from eval.cli import (
    _check_opt_in_env,
    _check_real_eval_or_cassette,
    _parse_providers,
    _select_tasks,
    main,
)


# --- _parse_providers ---


def test_parse_providers_default_anthropic():
    """V0.26.3: 空 raw → ["anthropic"] 默认 (单 provider 防 OpenAI key 缺失 fail)."""
    assert _parse_providers("") == ["anthropic"]


def test_parse_providers_comma_split():
    assert _parse_providers("anthropic,openai") == ["anthropic", "openai"]


def test_parse_providers_strips_whitespace():
    assert _parse_providers(" anthropic , openai , kimi ") == ["anthropic", "openai", "kimi"]


def test_parse_providers_skip_empty():
    assert _parse_providers("anthropic,,openai") == ["anthropic", "openai"]


# --- _select_tasks (corpus filter) ---


def test_select_tasks_all_returns_full_corpus():
    """V0.30.4: --corpus all → 全 15 task (V0.26.1 10 + V0.29 2 chain + V0.30.2 1 wiki + V0.30.4 2 (wiki+github))."""
    tasks = _select_tasks("all")
    assert len(tasks) == 15


def test_select_tasks_axis_filter():
    """V0.26.3: --corpus iframe → 仅 iframe 类 task."""
    tasks = _select_tasks("iframe")
    assert len(tasks) >= 1
    assert all(t.capability_axis == "iframe" for t in tasks)


def test_select_tasks_unknown_axis_returns_empty():
    """V0.26.3: 未知 axis → 空 list (CLI 检测后 exit 1 + 提示)."""
    tasks = _select_tasks("nonexistent-axis")
    assert tasks == []


# --- opt-in env check ---


def test_check_opt_in_env_exits_when_not_set(monkeypatch, capsys):
    """V0.26.3: WEB_AGENT_RUN_EVAL 不设 → SystemExit(1) + stderr 提示防意外烧 token."""
    monkeypatch.delenv("WEB_AGENT_RUN_EVAL", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        _check_opt_in_env()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "WEB_AGENT_RUN_EVAL=1" in captured.err
    assert "防意外烧 token" in captured.err


def test_check_opt_in_env_passes_when_set(monkeypatch):
    """V0.26.3: WEB_AGENT_RUN_EVAL=1 设了 → 无异常."""
    monkeypatch.setenv("WEB_AGENT_RUN_EVAL", "1")
    _check_opt_in_env()  # 不抛即过


# --- _check_real_eval_or_cassette ---


def test_check_real_eval_returns_true_when_eval_real_set(monkeypatch, tmp_path):
    """V0.26.3: EVAL_REAL=1 → 返 True (走真 LLM, cassette dir 不查)."""
    monkeypatch.setenv("WEB_AGENT_EVAL_REAL", "1")
    assert _check_real_eval_or_cassette(tmp_path / "nonexistent") is True


def test_check_cassette_mode_when_cassettes_exist(monkeypatch, tmp_path):
    """V0.26.3: EVAL_REAL=0 + cassette dir 有 .yaml → 返 False (cassette 模式)."""
    monkeypatch.delenv("WEB_AGENT_EVAL_REAL", raising=False)
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()
    (cassette_dir / "v0260-baseline.yaml").write_text("interactions: []")
    assert _check_real_eval_or_cassette(cassette_dir) is False


def test_check_no_cassette_no_real_eval_exits(monkeypatch, capsys, tmp_path):
    """V0.26.3: EVAL_REAL=0 + cassette dir 空 → exit 1 + 提示用户开 EVAL_REAL=1."""
    monkeypatch.delenv("WEB_AGENT_EVAL_REAL", raising=False)
    cassette_dir = tmp_path / "empty-cassettes"
    cassette_dir.mkdir()
    with pytest.raises(SystemExit) as exc_info:
        _check_real_eval_or_cassette(cassette_dir)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "WEB_AGENT_EVAL_REAL=1" in captured.err
    assert "ANTHROPIC_API_KEY" in captured.err


# --- main entry: --lint-only 不需 RUN_EVAL=1 ---


def test_main_lint_only_passes_without_run_eval_env(monkeypatch, capsys):
    """V0.26.3: --lint-only 模式 (不调真 LLM/chromium) 不需 RUN_EVAL=1, 跑 V0.26.1 lint."""
    monkeypatch.delenv("WEB_AGENT_RUN_EVAL", raising=False)
    with patch("sys.argv", ["web-agent-eval", "--lint-only"]):
        main()  # 不抛 SystemExit (lint OK 时静默 return)
    captured = capsys.readouterr()
    assert "LINT OK" in captured.out


def test_main_lint_only_fails_with_corrupt_corpus(monkeypatch):
    """V0.26.3: --lint-only 检测到 violations → SystemExit(1)."""
    monkeypatch.delenv("WEB_AGENT_RUN_EVAL", raising=False)
    fake_violations = ["fake-task: substring 'ok' 长度 < 8"]
    with patch("eval.corpus.lint_corpus_tokens", return_value=fake_violations):
        with patch("sys.argv", ["web-agent-eval", "--lint-only"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
    assert exc_info.value.code == 1


def test_main_run_eval_without_env_exits(monkeypatch):
    """V0.26.3: 不带 --lint-only 模式必须 RUN_EVAL=1, 否则 exit 1."""
    monkeypatch.delenv("WEB_AGENT_RUN_EVAL", raising=False)
    with patch("sys.argv", ["web-agent-eval", "--corpus", "all"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1


# --- argparse 默认值 ---


def test_argparse_defaults():
    """V0.26.3: --providers anthropic / --runs 1 / --output data/eval/ / --corpus all 默认."""
    parser = argparse.ArgumentParser(prog="web-agent-eval")
    parser.add_argument("--corpus", default="all")
    parser.add_argument("--providers", default="anthropic")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output", default="data/eval/")
    args = parser.parse_args([])
    assert args.corpus == "all"
    assert args.providers == "anthropic"
    assert args.runs == 1
    assert args.output == "data/eval/"


# --- workflow file sanity ---


def test_eval_nightly_workflow_default_disabled():
    """V0.26.3: GitHub Actions workflow stub 必须默认 if:false 防意外烧 token."""
    workflow_path = Path(__file__).parent.parent / ".github" / "workflows" / "eval-nightly.yml"
    assert workflow_path.exists(), f"V0.26.3 workflow stub 必须存在: {workflow_path}"
    content = workflow_path.read_text()
    assert "if: false" in content, "默认必须 if:false 防意外烧 token"
    assert "WEB_AGENT_RUN_EVAL" in content
    assert "ANTHROPIC_API_KEY" in content  # secret 配置 example


# ---------- V0.30.5 收尾: --corpus real-world axis filter 验 ----------


def test_select_tasks_real_world_axis_returns_3_real_net_tasks():
    """V0.30.5: --corpus real-world → 3 V0.30.2-4 task (Quantum + Apple_Inc + GitHub octocat).

    requires_real_net=True 全部 — _select_tasks 是纯函数 (不调 LIVE_NET filter), 测 axis 选对.
    """
    tasks = _select_tasks("real-world")
    assert len(tasks) == 3
    assert all(t.capability_axis == "real-world" for t in tasks)
    assert all(t.requires_real_net for t in tasks)
    task_ids = {t.task_id for t in tasks}
    assert "v030-wikipedia-quantum-entanglement" in task_ids
    assert "v030-wikipedia-apple-inc" in task_ids
    assert "v030-github-octocat-hello-world" in task_ids


def test_argparse_help_mentions_real_world_axis(capsys):
    """V0.30.5: --corpus help 文案含 'real-world' axis 例 (V0.30.5 cli help update 验)."""
    import contextlib
    import sys
    from eval.cli import main

    sys.argv = ["web-agent-eval", "--help"]
    with contextlib.suppress(SystemExit):
        main()
    captured = capsys.readouterr()
    # argparse --help → stdout
    assert "real-world" in captured.out, (
        f"V0.30.5 cli help 应含 'real-world' axis 例, captured: {captured.out[:500]}"
    )
