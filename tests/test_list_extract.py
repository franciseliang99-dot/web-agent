"""V0.20.6 list_extract module tests — _validate_jds 校验逻辑.

不测 LLM call / Playwright (依赖外部); 这两块靠 e2e 真实跑验证.
parse_jd_result / _check_loop_error 已被 test_jd_extract.py 覆盖, list_extract 复用它.
"""

from __future__ import annotations

import logging

import pytest

from web_agent.list_extract import _validate_jds


def test_validate_jds_strict_dict() -> None:
    """正常 dict + 已绝对 URL → 通过."""
    parsed = {
        "jds": [
            {"title": "JD A", "url": "https://www.upwork.com/jobs/~01a",
             "budget": "$30/hr", "posted_at": "1h"},
        ]
    }
    out = _validate_jds(parsed)
    assert len(out) == 1
    assert out[0]["url"] == "https://www.upwork.com/jobs/~01a"
    assert out[0]["title"] == "JD A"


def test_validate_jds_relative_url_completed() -> None:
    """LLM 给相对路径 (a[href] 是相对的) → 自动补 https://www.upwork.com 前缀."""
    parsed = {"jds": [{"title": "X", "url": "/jobs/~01b", "budget": None, "posted_at": None}]}
    out = _validate_jds(parsed)
    assert out[0]["url"] == "https://www.upwork.com/jobs/~01b"


def test_validate_jds_non_upwork_url_drops(caplog: pytest.LogCaptureFixture) -> None:
    """非 Upwork host (sidebar 推荐外站) drop, Upwork 项保留."""
    parsed = {"jds": [
        {"title": "spam ad", "url": "https://evil.com/x", "budget": None, "posted_at": None},
        {"title": "real JD", "url": "https://www.upwork.com/jobs/~01c",
         "budget": None, "posted_at": None},
    ]}
    with caplog.at_level(logging.WARNING):
        out = _validate_jds(parsed)
    assert len(out) == 1
    assert out[0]["title"] == "real JD"


def test_validate_jds_empty_array_raises() -> None:
    """空 jds array 或缺 jds key → SystemExit."""
    with pytest.raises(SystemExit, match="没有 jds array 或为空"):
        _validate_jds({"jds": []})
    with pytest.raises(SystemExit, match="没有 jds array 或为空"):
        _validate_jds({"thought": "看不到 jds 部分", "other_key": []})


def test_validate_jds_all_dropped_raises() -> None:
    """全部 item 被 drop (非 dict / 非 Upwork URL) → SystemExit."""
    parsed = {"jds": [
        {"url": "https://evil.com/x"},
        "not a dict",
        {"title": "缺 url"},
    ]}
    with pytest.raises(SystemExit, match="全部被 drop"):
        _validate_jds(parsed)
