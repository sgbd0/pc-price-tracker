#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机网页看板服务（只读）。

- GET /            网页看板(web/index.html)
- GET /api/data    实时汇总的看板数据(JSON)
- 其余路径         web/ 目录下的静态文件

默认监听 127.0.0.1:8787，只读、无任何写入接口；
公网访问由 cloudflared 隧道转发到本端口（见 tunnel.bat）。
"""
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracker

WEB_DIR = os.path.join(tracker.BASE, "web")


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/data":
            try:
                data = tracker.build_web_data()
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                body = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, fmt, *args):
        pass


def main(args=None):
    cfg = tracker.load_config()
    web_cfg = cfg.setdefault("web", {"port": 8787, "bind": "127.0.0.1"})
    tracker.save_config(cfg)
    port = getattr(args, "port", None) or web_cfg.get("port", 8787)
    bind = getattr(args, "bind", None) or web_cfg.get("bind", "127.0.0.1")
    # 禁止端口复用叠加：旧实例还活着时新实例直接报错退出，避免多进程串数据
    ThreadingHTTPServer.allow_reuse_address = False
    ThreadingHTTPServer.daemon_threads = True
    httpd = ThreadingHTTPServer((bind, port), DashboardHandler)
    print(f"看板已启动: http://{'127.0.0.1' if bind == '0.0.0.0' else bind}:{port}", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
