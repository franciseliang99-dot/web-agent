"""V0.15.8 W5-E real LLM smoke 共享工具 (anthropic + openai/kimi + openai/gpt 复用).

放 tests/_smoke_helpers.py 而非 conftest.py: conftest 全局加载, 这些 helper 仅
3 个 smoke file 用, 放 conftest 让其余 219 tests collection 阶段也 import 浪费.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from web_agent.types import ClickAction, DoneAction, ExtractAction, ScrollAction, TypeAction

# 16×16 RGB (128,128,128) 灰 PNG, base64=112 字节 - Claude/OpenAI/Kimi 各 vision 模型
# 实测最小可接受图片下限. 1×1 透明会被 Claude 拒 "image too small to process".
TINY_GRAY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAGUlEQVR4nGNsaGhgIAUwkaR6VMOoh"
    "iGlAQDJTAGgLgFHggAAAABJRU5ErkJggg=="
)

_VALID_ACTION_TYPES = {"click", "type", "scroll", "extract", "done"}
_CASSETTE_ROOT = Path(__file__).parent / "cassettes"


def smoke_skip_marker(
    env_var: str,
    cassette_subdir: str,
    label: str,
    *,
    blocker_env: tuple[str, str] | None = None,
):
    """生成 smoke skipif 守卫: 既无 cassette 也无 key 时整文件 skip.

    `blocker_env=(env_name, required_substring)`: 当 env_name 已设置但值不含
    required_substring (e.g. OPENAI_BASE_URL=moonshot.cn 但 GPT smoke 要 openai.com),
    把 has_key 视为 False 触发 skip, 防请求被错路由录到错 cassette.
    """
    cassette_dir = _CASSETTE_ROOT / cassette_subdir
    has_cassette = cassette_dir.exists() and any(cassette_dir.glob("*.yaml"))
    has_key = bool(os.environ.get(env_var))
    blocker_name = blocker_env[0] if blocker_env else None
    if has_key and blocker_env is not None:
        blocker_value = os.environ.get(blocker_name, "")
        if blocker_value and blocker_env[1] not in blocker_value:
            has_key = False
    blocker_hint = (
        f" (或 {blocker_name} 路由到非目标端点, 首次录制需 unset {blocker_name})"
        if blocker_name
        else ""
    )
    return pytest.mark.skipif(
        not has_cassette and not has_key,
        reason=f"real {label} smoke skeleton: 既无 cassette 也无 {env_var}{blocker_hint} — "
        f"首次录制 export {env_var} 后跑 --record-mode=once",
    )


def assert_smoke_action(action) -> None:
    """smoke = pipeline alive 共用断言, 不验行为正确性. V0.17.0: 5 dataclass tuple isinstance."""
    _ACTION_TYPES = (ClickAction, TypeAction, ScrollAction, ExtractAction, DoneAction)
    assert isinstance(action, _ACTION_TYPES), \
        f"plan() 应返 5 Action dataclass 之一, got {type(action)!r}"
    assert action.type in _VALID_ACTION_TYPES, \
        f"action.type 必须是 5 合法值之一, got {action.type!r}"
    assert isinstance(action.thought, str)
