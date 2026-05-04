"""V0.15.10 (Z Phase 1 of 4): 本机 HTTP server 服务 data/replays/, 给 Chrome 扩展 iframe 嵌入。

stdlib only (`http.server`), 无 dep. 默认端口 8000, 默认目录 data/replays/.
扩展 popup iframe 指 http://localhost:8000/, file:// 跨 scheme 在 MV3 下几乎必崩,
本机 HTTP 服务是最简方案 (subagent 审核反馈).

使用:
    web-agent-serve              # 默认 data/replays/ + 8000
    web-agent-serve --port 9000
    web-agent-serve --dir custom/path
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
from pathlib import Path

DEFAULT_DIR = "data/replays"
DEFAULT_PORT = 8000


def main() -> None:
    parser = argparse.ArgumentParser(
        description="本机 HTTP server 服务 web-agent replays HTML, 给 Chrome 扩展 iframe 嵌入"
    )
    parser.add_argument("--dir", default=DEFAULT_DIR, help=f"服务目录 (默认 {DEFAULT_DIR})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口 (默认 {DEFAULT_PORT})")
    parser.add_argument("--bind", default="127.0.0.1", help="绑定地址 (默认 127.0.0.1, 仅本机)")
    args = parser.parse_args()

    serve_dir = Path(args.dir).resolve()
    if not serve_dir.exists():
        raise SystemExit(f"目录不存在: {serve_dir}")

    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(serve_dir), **kw
    )
    with socketserver.TCPServer((args.bind, args.port), handler) as httpd:
        print(f"web-agent-serve: http://{args.bind}:{args.port}/ → {serve_dir}")
        print("Ctrl+C 退出")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve] 退出")


if __name__ == "__main__":
    main()
