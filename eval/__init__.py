"""V0.26 eval golden corpus — 用户场景"完全无人值守"硬前置数据底座.

V0.21-V0.25 沉淀 9 个新能力 (multi-tab/iframe/drag/upload/download/dialog/retry/backtrack/
keyboard-nav) 仅有代码路径单元测 + 真 chromium slow smoke, 完全没数据回答 "LLM 真用上了吗".
V0.26 corpus 用 data:text/html fixture 跑端到端任务测 LLM 行为, baseline 数据驱动决定
V0.27 凭证 vault + V0.28 无人值守模式开权限边界.

依赖方向: domain (web_agent.types) ← runtime (web_agent.loop/cli) ← eval (本目录, 测 LLM 行为).
跟 tests/ 不同: tests/ 测代码路径 (mock LLM); eval/ 测 LLM 真实表现 (vcr 录回放或真 LLM).
"""

__version__ = "0.26.5"
