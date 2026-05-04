// V0.15.10 Z Phase 1: popup 行为 - 仅 "Open in tab" 按钮 + iframe 故障兜底
//
// 故意不动 iframe.src 由 manifest hardcode http://localhost:8000/index.html.
// 用户启 web-agent-serve 服务后 iframe 自动连; 没启服务 iframe 会显示连接错误,
// content_security_policy 不让 popup 直接访问跨域所以无 fallback UI 显示.

const REPLAY_URL = "http://localhost:8000/index.html";

document.getElementById("open-tab").addEventListener("click", () => {
  chrome.tabs.create({ url: REPLAY_URL });
});

// iframe load 失败检测 (轻量, 不替换内容)
const frame = document.getElementById("replay-frame");
frame.addEventListener("error", () => {
  console.warn("[web-agent observer] iframe 加载失败 — 检查是否启 web-agent-serve");
});
