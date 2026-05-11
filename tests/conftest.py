"""共享 pytest fixture / vcr 配置 (V0.15.3 W5-E real LLM smoke 骨架, V0.15.7 加 .env autoload)。

vcr_config 锁默认 cassette filter, 避免每个 vcr 标注 case 重复参数。
重点是过滤一切可能含 secret 或机器画像的 header。

V0.15.7: 加 dotenv autoload 让 smoke skip 守卫 (`os.environ.get("OPENAI_API_KEY")` /
ANTHROPIC_API_KEY) 在 pytest collection 时能读到 .env 里的 key. override=False 让
shell 已 export 的优先 (CI scenario), 不被 .env 覆盖.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=False)


@pytest.fixture(scope="module")
def vcr_config():
    """pytest-recording 默认 fixture: 所有 @pytest.mark.vcr case 的 baseline 配置。

    filter_headers 用元组形式 (name, replacement) 保留 header 但脱敏, 便于 cassette diff;
    单字符串形式 (e.g. "authorization") 会整 header 删, replay 时若 SDK 必须读会出错。

    V0.30.1 simplify: 11 项 redact 共享 eval/runner._VCR_FILTER_HEADERS (单源, 加新 header 改 1 处).
    """
    from eval.runner import _VCR_FILTER_HEADERS, _VCR_FILTER_QUERY_PARAMETERS

    return {
        "filter_headers": list(_VCR_FILTER_HEADERS),
        "filter_query_parameters": list(_VCR_FILTER_QUERY_PARAMETERS),
        # 默认 once: 已有 cassette 重放, 否则录制后写盘. CLI --record-mode=none 可强 replay-only
        "record_mode": "once",
    }
