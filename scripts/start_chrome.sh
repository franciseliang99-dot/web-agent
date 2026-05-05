#!/usr/bin/env bash
# 启动带 9222 调试端口的 Chrome（独立 user-data-dir，不污染日常 profile）。
#
# 三种 mode（CHROME_MODE env）：
#   auto     默认。装了 xvfb 用 xvfb / 有 DISPLAY 用 headed / 都没用 --headless=new
#   xvfb     强制 Xvfb（先 sudo apt install xvfb），符合"非 headless"反爬偏好
#   headless 强制 --headless=new（chrome 内置，零依赖；但 CDP 指纹仍可被 DataDome 识别）
#   headed   强制有界面（本机有 GUI / SSH -X 转发时用）
#
# 其他 env：
#   CHROME_DEBUG_PORT      默认 9222
#   CHROME_USER_DATA_DIR   默认 ~/.config/web-agent-chrome
#
# 用法:
#   bash scripts/start_chrome.sh                          # auto 模式
#   CHROME_MODE=xvfb bash scripts/start_chrome.sh         # 强制 xvfb
#   bash scripts/start_chrome.sh https://wikipedia.org/   # 透传初始 URL
set -euo pipefail

PORT="${CHROME_DEBUG_PORT:-9222}"
USER_DATA="${CHROME_USER_DATA_DIR:-${HOME}/.config/web-agent-chrome}"
MODE="${CHROME_MODE:-auto}"
mkdir -p "${USER_DATA}"

CHROME_BIN=""
for c in google-chrome google-chrome-stable chromium chromium-browser; do
  if command -v "$c" >/dev/null 2>&1; then
    CHROME_BIN="$(command -v "$c")"
    break
  fi
done
if [[ -z "${CHROME_BIN}" ]]; then
  echo "找不到 Chrome / Chromium 可执行文件" >&2
  exit 1
fi

if [[ "$MODE" == "auto" ]]; then
  if command -v xvfb-run >/dev/null 2>&1; then
    MODE=xvfb
  elif [[ -n "${DISPLAY:-}" ]]; then
    MODE=headed
  else
    MODE=headless
  fi
fi

ARGS=(
  --remote-debugging-port="${PORT}"
  --user-data-dir="${USER_DATA}"
  --disable-blink-features=AutomationControlled
  --no-first-run
  --no-default-browser-check
  --disable-features=PrivacySandboxSettings4
  # V0.16.14 GL flags: Xvfb / headless 无 GPU 时启 SwiftShader 软件渲染
  # 不加这 3 个 → sannysoft "WebGL Vendor/Renderer" 直接 FAIL（Canvas has no webgl context）
  # → 反爬站点用 WebGL fingerprint 过滤 bot 时直接命中
  --use-gl=angle
  --use-angle=swiftshader
  --enable-unsafe-swiftshader
)

echo "Chrome:        ${CHROME_BIN}"
echo "User data dir: ${USER_DATA}"
echo "Debug port:    ${PORT}"
echo "Mode:          ${MODE}"
echo "CDP URL:       http://localhost:${PORT}"
echo

case "$MODE" in
  xvfb)
    if ! command -v xvfb-run >/dev/null 2>&1; then
      echo "xvfb-run 未装。装一下：sudo apt install xvfb" >&2
      echo "或用 CHROME_MODE=headless 走 chrome 内置 headless=new（零依赖）" >&2
      exit 1
    fi
    exec xvfb-run -a -s "-screen 0 1920x1080x24" "${CHROME_BIN}" "${ARGS[@]}" "$@"
    ;;
  headless)
    # V0.16.14: 删 --disable-gpu, 让 ARGS 里的 SwiftShader GL flags 接管软件渲染.
    # --headless=new + SwiftShader 是 Chrome 109+ 官方推荐组合, --disable-gpu 已 deprecated.
    exec "${CHROME_BIN}" --headless=new "${ARGS[@]}" "$@"
    ;;
  headed)
    if [[ -z "${DISPLAY:-}" ]]; then
      echo "headed 模式需要 DISPLAY 环境变量（本机 GUI / SSH -X 转发）" >&2
      exit 1
    fi
    exec "${CHROME_BIN}" "${ARGS[@]}" "$@"
    ;;
  *)
    echo "未知 CHROME_MODE=${MODE}（应为 auto / xvfb / headless / headed）" >&2
    exit 2
    ;;
esac
