"""V0.15.8 W5-E real LLM smoke 共享工具 (anthropic + openai/kimi + openai/gpt 复用).

三段抽象:
- `TINY_GRAY_PNG_B64`: 16×16 灰 PNG, Claude vision <8×8 拒, 16×16 安全下限
- `smoke_skip_marker(env_var, cassette_subdir, label)`: pytest.mark.skipif 守卫工厂
- `assert_smoke_action(action, Action_cls)`: smoke = pipeline alive 共用断言

不放 conftest.py 的原因 (subagent 审核): conftest 全局加载, 这些 helper 仅 smoke
test 用, 放 conftest 让 219 非 smoke test collection 阶段也 import 浪费.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# 16×16 RGB (128,128,128) 灰 PNG, base64=112 字节 - Claude/OpenAI/Kimi 各 vision 模型
# 实测最小可接受图片下限. 1×1 透明会被 Claude 拒 "image too small to process".
TINY_GRAY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAGUlEQVR4nGNsaGhgIAUwkaR6VMOoh"
    "iGlAQDJTAGgLgFHggAAAABJRU5ErkJggg=="
)

_CASSETTE_ROOT = Path(__file__).parent / "cassettes"


def smoke_skip_marker(
    env_var: str,
    cassette_subdir: str,
    label: str,
    *,
    blocker_env: tuple[str, str] | None = None,
):
    """生成 smoke test 的 skipif 守卫: 既无 cassette 也无 key 时整文件 skip.

    使用 (顶部 module 级):
        pytestmark = smoke_skip_marker("OPENAI_API_KEY", "test_smoke_openai_kimi_real",
                                        "Kimi 国内版 .cn")

    cassette 已录存在 → 跳过 key 检查 (replay 不需要 key).
    cassette 没录但有 key → 不 skip, --record-mode=once 真发请求录制.
    都没 → skip 整文件不阻塞主 219 tests.

    blocker_env: (env_name, required_substring) 可选守卫 — 当用户 .env 让某 env var
    被设置但其值与本 smoke 目标端点冲突 (e.g. GPT smoke 看 OPENAI_API_KEY 存在但用户
    OPENAI_BASE_URL 指向 moonshot.cn), 视为 "没 key for 本端点" 触发 skip 防错路由
    record. 实例: GPT smoke 传 ("OPENAI_BASE_URL", "openai.com") — 当 OPENAI_BASE_URL
    设了但不含 "openai.com" 时, 把 has_key 视为 False 触发 skip.
    """
    cassette_dir = _CASSETTE_ROOT / cassette_subdir
    has_cassette = cassette_dir.exists() and any(cassette_dir.glob("*.yaml"))
    has_key = bool(os.environ.get(env_var))
    if has_key and blocker_env is not None:
        blocker_name, required_substring = blocker_env
        blocker_value = os.environ.get(blocker_name, "")
        if blocker_value and required_substring not in blocker_value:
            # blocker_env 设了但端点不匹配 → 视为没 key (会被错路由)
            has_key = False
    return pytest.mark.skipif(
        not has_cassette and not has_key,
        reason=f"real {label} smoke skeleton: 既无 cassette 也无 {env_var} (或 "
        f"被 {blocker_env[0] if blocker_env else 'env'} 路由到非目标端点) — "
        f"首次录制请 unset {blocker_env[0] if blocker_env else ''} + "
        f"export {env_var} 后跑 --record-mode=once",
    )


def ensure_dummy_key(env_var: str, dummy_value: str) -> None:
    """无 key 但 cassette 已录时, 注入 dummy 让 *Client.__init__ 通过.

    vcr 拦下出站请求不会真用 dummy. 仅 smoke replay 阶段用.
    """
    if not os.environ.get(env_var):
        os.environ[env_var] = dummy_value


def assert_smoke_action(action, Action_cls) -> None:
    """smoke = pipeline alive 共用断言, 不验行为正确.

    断言: 返 Action dataclass / action.type ∈ 5 合法 / args dict / thought str.
    """
    assert isinstance(action, Action_cls), \
        f"plan() 应返 Action dataclass, got {type(action)!r}"
    assert action.type in {"click", "type", "scroll", "extract", "done"}, \
        f"action.type 必须是 5 合法值之一, got {action.type!r}"
    assert isinstance(action.args, dict)
    assert isinstance(action.thought, str)
