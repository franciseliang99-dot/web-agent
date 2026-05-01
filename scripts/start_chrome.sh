#!/usr/bin/env bash
# 启动带 9222 调试端口的 Chrome（独立 user-data-dir，不污染日常 profile）。
#
# 用法:
#   bash scripts/start_chrome.sh                    # 空白起点
#   bash scripts/start_chrome.sh https://wikipedia.org/   # 带初始 URL
#
# 关闭这个 Chrome 不影响你日常 Chrome 的 profile / cookie / 标签页。
# 第一次启动后可手动登录常用站点（Gmail / GitHub），登录态会存进 user-data-dir
# 持久化复用，下次 agent 跑就有登录态了。
set -euo pipefail

USER_DATA="${HOME}/.config/web-agent-chrome"
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

echo "Chrome:        ${CHROME_BIN}"
echo "User data dir: ${USER_DATA}"
echo "Debug port:    9222"
echo "CDP URL:       http://localhost:9222"
echo ""

exec "${CHROME_BIN}" \
  --remote-debugging-port=9222 \
  --user-data-dir="${USER_DATA}" \
  --no-first-run \
  --no-default-browser-check \
  --disable-features=PrivacySandboxSettings4 \
  "$@"
