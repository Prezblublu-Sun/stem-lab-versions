"""只读的网页。只收读的请求：GET / 是页面，GET /api/state 是全部的数；别的方法一律不收。

    python -m stemlab.board [--port 8791] [--host 127.0.0.1] [--open]

--open 是开起来之后顺手在浏览器里打开。要从仓库根目录跑；从别处用根目录下的 board.cmd。

默认只在本机打得开。它不叫任何插件，不往任何地方写；记录没变就不重读。
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from stemlab.board import alerts, experiments, machines
from stemlab.contract import states

READ_PATHS = ("/", "/api/state")        # 这个网页收的全部请求。守边界的测试照着它逐个去取
PAGE = Path(__file__).with_name("page.html")


def state(monitor) -> dict:
    """页面要的全部的数。"""
    notes = [monitor.config_problem, monitor.machines_problem]
    try:
        listed = experiments.cards()
    except (OSError, ValueError, LookupError) as error:
        listed, notes = [], notes + [f"发号的那条链读不出来：{error}"]
    rows = monitor.read()
    busy = Counter((task["machine"], task["state"]) for one in listed if one.get("live") for task in one["tasks"])
    for row in rows:
        row["running_tasks"] = busy[(row["name"], states.T_RUNNING)]
    return {
        "time": time.time(),
        "interval": monitor.config["interval"],
        "alerts": alerts.alerts(monitor.config, rows, listed, notes=notes),
        "machines": rows,
        "running": experiments.running(listed=listed),
        "recent": experiments.recent(listed=listed),
        "problems": experiments.problems(listed=listed),
        "waiting": experiments.waiting(listed=listed),
    }


def listening(host: str, port: int) -> bool:
    """这个端口上是不是已经有服务在听了。port 是 0（让系统挑一个）就不用看。"""
    if port == 0:
        return False
    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1" if host in ("", "0.0.0.0") else host, port)) == 0


def handler(monitor):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                body, kind = PAGE.read_bytes(), "text/html; charset=utf-8"
            elif path == "/api/state":
                body, kind = json.dumps(state(monitor), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _refuse(self):
            self.send_error(405, "read only: this page takes GET requests only")

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuse

        def log_message(self, *args):       # 不往终端刷每一次请求
            pass

    return Handler


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m stemlab.board", description="仪表盘：全部实验的只读总览")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--host", default="127.0.0.1", help="默认只在本机打得开")
    parser.add_argument("--open", action="store_true", help="开起来之后顺手在浏览器里打开")
    args = parser.parse_args(argv)
    if listening(args.host, args.port):                 # 已经开着了：不起第二个（Windows 上两个进程能绑到同一个端口）
        url = f"http://{args.host}:{args.port}/"
        print(f"{args.port} 端口上已经有服务开着了，多半就是仪表盘：直接打开 {url}", flush=True)
        if args.open:
            webbrowser.open(url)
        return 0
    monitor = machines.Monitor()
    server = ThreadingHTTPServer((args.host, args.port), handler(monitor))
    url = f"http://{args.host}:{server.server_address[1]}/"
    print(f"仪表盘开在 {url} ，按 Ctrl+C 关掉", flush=True)
    if args.open:
        webbrowser.open(url)                            # 端口这时已经在听了，浏览器来早了也等得到
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        monitor.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
