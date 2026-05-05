"""V0.16.19: 9222 健康检查 + auto-spawn Chrome — 解约束 4 (Chrome 必须先启).

cli.py / mcp_server.py 检测 9222 不可达时, 自动 `subprocess.Popen([bash, scripts/start_chrome.sh],
start_new_session=True, stdio=DEVNULL)`, 等就绪后接管, exit 时不杀 Chrome.

设计原则:
- sync API: subprocess.Popen + urllib 都是 stdlib sync; 调用方 `asyncio.to_thread` 包
- env 开关 `WEB_AGENT_AUTO_SPAWN_CHROME=true` (默认开) / `=false` 回退 V0.16.18 行为 (手启)
- POSIX `start_new_session=True` (setsid): 父 exit 不带走 Chrome — 约束 4 关键
- stdio MCP 模式 stdin/stdout/stderr 必须 DEVNULL: 防 Chrome 启动 log 污染 JSON-RPC 通道
- 30s 仍不可达 → RuntimeError 引导手启 (与 V0.16.18 行为兼容, 不是回退)

依赖方向 (按 CLAUDE.md): adapter (subprocess + urllib stdlib) ← 业务层 (cli/mcp_server) ← 组合根 (cli.main).
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


def check_chrome_alive(cdp_url: str, timeout: float = 2.0) -> bool:
    """检查 9222 端口可达; 不可达返 False (不抛). 与 mcp_server _check_chrome_alive 抛版本互补."""
    probe_url = f"{cdp_url.rstrip('/')}/json/version"
    try:
        with urllib.request.urlopen(probe_url, timeout=timeout):
            return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def spawn_chrome_detached(
    script_path: Path,
    cdp_url: str,
    ready_timeout: float = 30.0,
    poll_interval: float = 0.5,
) -> int:
    """spawn `bash <script_path>` detached (start_new_session=True), 轮询 cdp_url 直至可达.

    Returns: Popen.pid (Chrome 进程 PID, 用户后续可手动 kill).
    Raises: RuntimeError ready_timeout 内 9222 仍不可达.
    """
    if not script_path.exists():
        raise RuntimeError(f"chrome_launcher: script 不存在: {script_path}")

    logger.info("chrome_launcher: spawning %s detached, waiting %ss for %s", script_path, ready_timeout, cdp_url)
    proc = subprocess.Popen(
        ["bash", str(script_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # POSIX setsid: 父 exit 不带走 Chrome
        close_fds=True,
        cwd=str(script_path.parent.parent),  # 项目 root, scripts/ 用相对路径
    )

    deadline = time.monotonic() + ready_timeout
    while time.monotonic() < deadline:
        if check_chrome_alive(cdp_url, timeout=1.0):
            logger.info("chrome_launcher: 9222 ready, pid=%d", proc.pid)
            return proc.pid
        time.sleep(poll_interval)

    raise RuntimeError(
        f"chrome_launcher: spawn 后 {ready_timeout}s 内 {cdp_url} 仍不可达 (pid={proc.pid}). "
        "可能原因: 端口被其他进程占, Chrome binary 找不到, xvfb 未装. "
        "回退到手启: `bash scripts/start_chrome.sh` 然后重跑."
    )


def ensure_chrome_running(cdp_url: str, script_path: Path | None = None) -> None:
    """V0.16.19 顶层 orchestrator: 检查 → 不可达 + AUTO_SPAWN=true → spawn → wait.

    - AUTO_SPAWN=false (env): 不可达直接抛 RuntimeError 引导手启 (V0.16.18 行为, 用户偏好显式控制时用)
    - AUTO_SPAWN=true (默认): 不可达自动 spawn `scripts/start_chrome.sh`
    - 9222 已活: 直接返回 (零成本)
    """
    if check_chrome_alive(cdp_url):
        return

    auto_spawn = os.environ.get("WEB_AGENT_AUTO_SPAWN_CHROME", "true").lower() not in ("false", "0", "no", "off")
    if not auto_spawn:
        raise RuntimeError(
            f"chrome_not_running: {cdp_url} 无响应 + WEB_AGENT_AUTO_SPAWN_CHROME=false. "
            "提示: 先在另一终端跑 `bash scripts/start_chrome.sh` 启 9222 调试端口的 Chrome."
        )

    if script_path is None:
        # 默认从本模块 __file__ 回溯到项目 root/scripts/start_chrome.sh
        script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "start_chrome.sh"

    spawn_chrome_detached(script_path, cdp_url)
