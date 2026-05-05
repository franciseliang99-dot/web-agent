#!/usr/bin/env python
"""V0.16.22: re-aggregate W5-C.2 spike jsonl with current loop.py regex.

V0.16.21 spike jsonl 用 V0.16.21 regex 算的 M1/M2/M5, 但 V0.16.21 regex 漏判 LLM 实际表达
("子任务 N" / "Subgoal:" 等, 详见 V0.16.21 数据 spot check). 本脚本不重跑 spike (那需 80
min + LLM 调用), 只用当前 (V0.16.22) regex 重判现有 jsonl thought 字段 + 重出 summary.

第一步备份 V0.16.21 原始 jsonl 到 spike-w5c2-v021-backup/ 保 audit trail (subagent
推荐 α: 失去原始数据 = 失去 V0.16.21 → V0.16.22 改善 delta 复盘能力).

跑法: uv run python scripts/reaggregate_w5c2.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

# scripts/ + src/ 加入 sys.path 让 import 工作
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from web_agent.loop import (  # noqa: E402
    _SPIKE_FAILURE_OBS_MARKERS,
    _SPIKE_M1_RE,
    _SPIKE_M2_RE,
    _SPIKE_M5_RE,
)
from run_w5c2_spike import OUT_DIR, print_summary  # noqa: E402

BACKUP_DIR = OUT_DIR.parent / "spike-w5c2-v021-backup"


def _recompute(record: dict[str, Any]) -> dict[str, Any]:
    """用当前 regex 重判 M1/M2/M5 + is_failure_step, 覆盖原字段."""
    thought = record.get("thought") or ""
    obs = record.get("obs_head") or ""
    is_failure = any(m in obs for m in _SPIKE_FAILURE_OBS_MARKERS)
    record["M1"] = bool(_SPIKE_M1_RE.search(thought))
    record["M2"] = bool(_SPIKE_M2_RE.search(thought))
    record["M5"] = bool(_SPIKE_M5_RE.search(thought)) if is_failure else False
    record["is_failure_step"] = is_failure
    return record


def main() -> int:
    if not OUT_DIR.exists():
        print(f"no spike data at {OUT_DIR}, run scripts/run_w5c2_spike.py first")
        return 1

    # 备份 V0.16.21 原始 jsonl (audit trail) — 仅首次跑时
    if not BACKUP_DIR.exists():
        shutil.copytree(OUT_DIR, BACKUP_DIR)
        print(f"backed up {OUT_DIR} → {BACKUP_DIR}")
    else:
        print(f"backup already exists at {BACKUP_DIR}, skipping (re-run safe)")

    n_files = 0
    n_records = 0
    for jp in sorted(OUT_DIR.glob("*.jsonl")):
        if jp.name == "summary.jsonl":
            continue
        if jp.stat().st_size == 0:
            continue
        rows = [
            json.loads(ln)
            for ln in jp.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        rows = [_recompute(r) for r in rows]
        with jp.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        n_files += 1
        n_records += len(rows)

    print(f"=== Re-aggregated {n_records} records across {n_files} files ===\n")
    print_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
