"""V0.26.1: corpus 共享 fixture HTML + URL 工厂.

复用 V0.21-V0.25 slow smoke 的 data:text/html pattern. 抽出共享 module 防 6 task 文件
散乱重复 + 让所有 task token 统一定义 (后人加 task 用 helper 防漏).

每 task **token-specific 强制** (V0.26 plan B7): SubstringPredicate.substring 必须含
独特 token (≥ 8 字符 + 不在通用词集), 防 agent done(result="完成") 假阳性.
test_eval_corpus_lint 验所有 task token 符合这个约束.
"""

from __future__ import annotations

import urllib.parse


def html_to_data_url(html: str) -> str:
    """V0.26.1: HTML 字符串 → data:text/html URL (urllib.parse.quote 转 percent-encoding)."""
    return "data:text/html," + urllib.parse.quote(html)


# --- token 定义 (V0.26 plan B7 强制 task-specific 防假阳性) ---

# 每 token 独特, ≥ 8 字符, 不在 SYSTEM_PROMPT / 通用词集 (成功/完成/done 等)
TOKEN_MULTITAB_POPUP_H1 = "popup-h1-token-7d3a"
TOKEN_IFRAME_CLICKED = "iframe-clicked-marker-b91f"
TOKEN_DRAG_DROP_ACK = "drop-zone-accepted-c4e2"
TOKEN_UPLOAD_FILENAME = "upload-filename-ack-a8b1.txt"
TOKEN_DOWNLOAD_FILENAME = "v026-corpus-report-9f2e.pdf"
TOKEN_DIALOG_CONFIRM_MSG = "dialog-message-token-e5d7"
TOKEN_KEYBOARD_NAV_BOTTOM = "bottom-of-modal-found-d2c8"
TOKEN_FAILURE_RECOVERY_VALID = "valid-mark-clicked-b7f4"
TOKEN_CROSS_FEATURE_DONE = "cross-feature-iframe-popup-1ec5"


# --- HTML fragment ---

# 1. multi-tab popup: 主 page 含 target=_blank link, popup H1 含独特 token
_MULTITAB_HTML = (
    "<html><body>"
    "<h1>main-page-banner</h1>"
    f"<a target=_blank href=\"{html_to_data_url(f'<html><body><h1>{TOKEN_MULTITAB_POPUP_H1}</h1></body></html>')}\">open new tab</a>"
    "</body></html>"
)
URL_MULTITAB_POPUP = html_to_data_url(_MULTITAB_HTML)

# 2. iframe-click: srcdoc iframe 内含 button, click 后 parent.window.__iframe_done 写 token
_IFRAME_HTML = (
    "<html><body>"
    "<h1>iframe-click-task</h1>"
    "<iframe srcdoc=\""
    "<html><body>"
    "<button onclick='window.parent.__iframe_done=1; "
    "document.body.innerHTML += \\\"<div id=ack>" + TOKEN_IFRAME_CLICKED + "</div>\\\"'>"
    "click me</button>"
    "</body></html>"
    "\"></iframe>"
    "</body></html>"
)
URL_IFRAME_CLICK = html_to_data_url(_IFRAME_HTML)

# 3. drag-drop: src + dst zone, drop 后 dst innerHTML 写 token
_DRAG_HTML = (
    "<html><body>"
    "<div id=src draggable=true style='width:80px;height:40px;background:#cfc;"
    "position:absolute;left:50px;top:50px'"
    " ondragstart=\"event.dataTransfer.setData('text/plain','x')\">SRC</div>"
    "<div id=dst style='width:120px;height:80px;background:#ccf;"
    "position:absolute;left:300px;top:200px'"
    " ondragover=\"event.preventDefault()\""
    " ondrop=\"event.preventDefault(); this.innerText='" + TOKEN_DRAG_DROP_ACK + "'\""
    ">DROP HERE</div>"
    "</body></html>"
)
URL_DRAG_DROP = html_to_data_url(_DRAG_HTML)

# 4. upload: input[type=file] + onchange 显示文件名 + ack token
_UPLOAD_HTML = (
    "<html><body>"
    "<input type=file id=u onchange=\"document.getElementById('ack').innerText="
    "'received: ' + this.files[0].name + ' " + TOKEN_UPLOAD_FILENAME + "'\">"
    "<div id=ack>(no file yet)</div>"
    "</body></html>"
)
URL_UPLOAD = html_to_data_url(_UPLOAD_HTML)

# 5. download: <a download> click 触发, filename 含独特 token
_DOWNLOAD_HTML = (
    "<html><body>"
    f"<a id=dl href=\"data:text/plain,download-content\" download=\"{TOKEN_DOWNLOAD_FILENAME}\">"
    "Download report</a>"
    "</body></html>"
)
URL_DOWNLOAD = html_to_data_url(_DOWNLOAD_HTML)

# 6. dialog confirm: button onclick confirm() 触发 + dialog 消息含独特 token
_DIALOG_CONFIRM_HTML = (
    "<html><body>"
    f"<button onclick=\"confirm('{TOKEN_DIALOG_CONFIRM_MSG}?')\">trigger dialog</button>"
    "</body></html>"
)
URL_DIALOG_CONFIRM = html_to_data_url(_DIALOG_CONFIRM_HTML)

# 7. keyboard-nav: 长 modal scroll 容器, 底部 button 含独特 token
_KEYBOARD_NAV_HTML = (
    "<html><body>"
    "<div style='height:200px;overflow:auto;border:1px solid #ccc'>"
    "<div style='height:2000px'>scroll content padding</div>"
    f"<button onclick=\"document.body.innerHTML='<h1>{TOKEN_KEYBOARD_NAV_BOTTOM}</h1>'\">"
    "bottom button</button>"
    "</div>"
    "</body></html>"
)
URL_KEYBOARD_NAV = html_to_data_url(_KEYBOARD_NAV_HTML)

# 8. failure-recovery: 多 button + 一个标记"VALID" 一个标记"DECOY"; LLM 选 VALID 时显 token
_FAILURE_RECOVERY_HTML = (
    "<html><body>"
    "<button>DECOY 1</button>"
    "<button>DECOY 2</button>"
    f"<button onclick=\"document.body.innerHTML='<h1>{TOKEN_FAILURE_RECOVERY_VALID}</h1>'\">"
    "VALID button</button>"
    "</body></html>"
)
URL_FAILURE_RECOVERY = html_to_data_url(_FAILURE_RECOVERY_HTML)

# 9. cross-feature: popup 内含 iframe, popup click iframe button → 注入 token
_CROSS_FEATURE_INNER_HTML = (
    "<html><body>"
    "<h1>popup-with-iframe</h1>"
    "<iframe srcdoc=\""
    "<html><body>"
    "<button onclick='window.parent.document.body.innerHTML += "
    "\\\"<h1>" + TOKEN_CROSS_FEATURE_DONE + "</h1>\\\"'>iframe button</button>"
    "</body></html>"
    "\"></iframe>"
    "</body></html>"
)
_CROSS_FEATURE_HTML = (
    "<html><body>"
    "<h1>main-page-cross-feature</h1>"
    f"<a target=_blank href=\"{html_to_data_url(_CROSS_FEATURE_INNER_HTML)}\">open</a>"
    "</body></html>"
)
URL_CROSS_FEATURE = html_to_data_url(_CROSS_FEATURE_HTML)
