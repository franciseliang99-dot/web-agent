"""共享 pytest fixture / vcr 配置 (V0.15.3 W5-E real LLM smoke 骨架)。

vcr_config 锁默认 cassette filter, 避免每个 vcr 标注 case 重复参数。
重点是过滤一切可能含 secret 或机器画像的 header。
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def vcr_config():
    """pytest-recording 默认 fixture: 所有 @pytest.mark.vcr case 的 baseline 配置。

    filter_headers 用元组形式 (name, replacement) 保留 header 但脱敏, 便于 cassette diff;
    单字符串形式 (e.g. "authorization") 会整 header 删, replay 时若 SDK 必须读会出错。
    """
    return {
        "filter_headers": [
            ("authorization", "REDACTED"),
            ("x-api-key", "REDACTED"),
            ("anthropic-version", "REDACTED"),
            ("openai-organization", "REDACTED"),
            ("user-agent", "REDACTED"),
            ("x-stainless-arch", "REDACTED"),
            ("x-stainless-os", "REDACTED"),
            ("x-stainless-runtime", "REDACTED"),
            ("x-stainless-runtime-version", "REDACTED"),
            ("x-stainless-lang", "REDACTED"),
            ("x-stainless-package-version", "REDACTED"),
        ],
        "filter_query_parameters": [("api_key", "REDACTED")],
        # 默认 once: 已有 cassette 重放, 否则录制后写盘. CLI --record-mode=none 可强 replay-only
        "record_mode": "once",
    }
