# web-agent observer (Chrome MV3 扩展)

观察 web-agent 已执行 task 的 replay 面板。**read-only / 不执行**——只展示，不操作浏览器。

来源：[ARCHITECTURE.md §1.1](../docs/ARCHITECTURE.md) 否决"扩展执行"路径（MV3 manifest 限制 + 失去拟人 actuator + stealth），本扩展仅做"观察面板"——iframe 嵌入 web-agent-replay 已生成的 HTML 索引页。

## Dev mode 加载（5 步）

```bash
# 1. 在 web-agent 项目根起本机 HTTP 服务（V0.15.10 加的 entry，stdlib only）
cd /home/myclaw/web-agent
uv run web-agent-serve
# 默认 http://127.0.0.1:8000/ → data/replays/
# 看到 "web-agent-serve: ... → /home/myclaw/web-agent/data/replays" 即 OK
```

```bash
# 2. 跑一次 web-agent 让 data/replays/ 有内容（若已跑过可跳过）
# uv run web-agent "..." --url ...
# uv run web-agent-replay --all   # 重渲染所有 task → HTML
```

3. Chrome 打开 `chrome://extensions/`
4. 右上角开「开发者模式」（Developer mode）
5. 点「加载已解压的扩展」（Load unpacked）→ 选 `/home/myclaw/web-agent/extension/` 目录

工具栏多出蓝色 W 图标 → pin 上去 → 点击 popup 弹出 480×640 → iframe 显示 task 索引 + 点 task 链接进 replay 详情页 + 顶部 "↗ Open in tab" 按钮新 tab 打开。

## 故障排查

| 现象 | 原因 | 修复 |
|---|---|---|
| popup 白屏 | `web-agent-serve` 没起 | 终端 `uv run web-agent-serve` |
| iframe 显示"无法访问" | 端口被占 | `web-agent-serve --port 8001`（同时改 `popup.html` line 28 + `manifest.json` host_permissions）|
| 工具栏图标灰 | manifest 错 | `chrome://extensions/` 看「错误」按钮日志 |
| `chrome.tabs.create` 报错 | manifest 缺 `tabs` 权限 | 已在 V0.15.10 manifest.json 给了，重 load unpacked |
| 跨域 / mixed content | iframe 用 https 请求 http | 不会发生（manifest hardcode http://localhost:8000）|

## 文件

```
extension/
  manifest.json   # MV3 配置, permissions=tabs, host=localhost:8000
  popup.html      # 480×640 popup, iframe + Open-in-tab button
  popup.js        # tabs.create 处理 + iframe error log
  icon-128.png    # 蓝底白 W 图标
  README.md       # 本文件
```

## Phase 路线图

- ✅ **Phase 1** (V0.15.10): 扩展骨架 + dev mode 加载 + serve helper
- 🔜 Phase 2: iframe 嵌入 + 默认显示最新 task（不靠 manifest hardcode）
- 🔜 Phase 3: chrome.runtime + storage 同步 task_id
- 🔜 Phase 4: dev → release 打包（zip + Chrome Web Store 流程，留 V0.16.0+）

之后是形态 1（MCP server，串行 Phase 4 后启动）。
