"""V0.15.3 W5-E real LLM smoke skeleton — 真 Anthropic SDK 调用 + cassette 回放。

设计意图: 验证 plan() pipeline 端到端走通 (SDK 构造 / system + tool schema 序列化
/ tool_use 解析 / Action dataclass 返回), 而非验证行为正确性 — 真 LLM 在空 mark 列表
+ 16×16 灰图下回什么不可断言, 只断言 "返回了合法 Action" 即够 (smoke 含义)。

运行模式 3 选 1:
1. **首次录制 (用户接手, 1 次)**: 提供 ANTHROPIC_API_KEY, 跑
   `pytest tests/test_smoke_anthropic_real.py --record-mode=once`
   → cassette 落到 `tests/cassettes/test_smoke_anthropic_real/...yaml`,
   提交进 commit (header 已 filter 无 key 泄漏)。

2. **后续 replay (CI/任何人, 无 key)**: 默认 `pytest tests/...` 直接读 cassette,
   不发任何 HTTP 请求, 无 key 也过。

3. **当前骨架状态 (V0.15.3, 无 cassette 无 key)**: 模块顶部 _SHOULD_SKIP 检查,
   skip 整个文件, 不阻塞主 219 tests pass。

成本估算 (录一次): claude-sonnet-4-6 vision, ~1100 input + ~150 output ≈ $0.006。
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path

import pytest

# ---- skip-when-no-cassette-no-key: 骨架阶段保 220 tests 全绿 ----
_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "test_smoke_anthropic_real"
_HAS_CASSETTE = _CASSETTE_DIR.exists() and any(_CASSETTE_DIR.glob("*.yaml"))
_HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
_SHOULD_SKIP = not _HAS_CASSETTE and not _HAS_KEY

pytestmark = pytest.mark.skipif(
    _SHOULD_SKIP,
    reason="real LLM smoke skeleton: 既无 cassette 也无 ANTHROPIC_API_KEY — "
    "首次录制请 export ANTHROPIC_API_KEY 后跑 --record-mode=once",
)


# 16×16 灰 PNG (RGB 128/128/128) — Claude vision 实测 <8×8 会拒 (image too small);
# 16×16 是安全下限, base64 仅 112 字节, cassette 友好。
_GRAY_16X16_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAGUlEQVR4nGNsaGhgIAUwkaR6VMOoh"
    "iGlAQDJTAGgLgFHggAAAABJRU5ErkJggg=="
)


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_anthropic_plan_smoke_pipeline_alive():
    """smoke = pipeline alive, NOT behavior correctness.

    真调一次 Anthropic plan(), 断言:
    - 返回 Action 实例 (dataclass, 不是 tuple)
    - action.type ∈ 5 合法值
    - action.args 是 dict
    - action.thought 是 str (可能空, V0.10.0 已知 LLM 有时漏 thought 字段)
    """
    from web_agent.llm.anthropic import AnthropicClient
    from web_agent.llm.base import Action
    from web_agent.trace import Trace

    # 无 key 但有 cassette 时, AnthropicClient.__init__ 会抛 RuntimeError.
    # 给一个 dummy key 让构造通过, replay 阶段 vcr 拦下出站请求, 不会真用此 key.
    if not _HAS_KEY:
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-cassette-replay-not-real"

    client = AnthropicClient()
    trace = Trace(task_id="smoke-real", goal="搜苹果价格", steps=deque())
    action = await client.plan(
        goal="搜苹果价格",
        screenshot_b64=_GRAY_16X16_PNG_B64,
        marks=[],  # 空 SoM marks: smoke 验 pipeline, 不验 LLM 是否选具体 mark_id
        trace=trace,
    )

    assert isinstance(action, Action), f"plan() 应返 Action dataclass, got {type(action)!r}"
    assert action.type in {"click", "type", "scroll", "extract", "done"}, \
        f"action.type 必须是 5 合法值之一, got {action.type!r}"
    assert isinstance(action.args, dict)
    assert isinstance(action.thought, str)
