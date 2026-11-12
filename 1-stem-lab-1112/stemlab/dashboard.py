"""仪表盘：只读。

读实验记录和机器信息，给一个本机网页，显示实时的任务现状。
它不叫任何插件，不往任何地方写。网页没人看的时候，它只有机器信息在采。

运行：python -m stemlab.dashboard [--home 文件夹] [--port 8791]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __package__ in (None, ""):  # 直接当脚本跑时，把仓库根加进来
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stemlab.machines import MachineWatch
from stemlab.record import (
    FINISHED,
    NOT_STARTED,
    PAUSED,
    RECORD_FILE,
    RUNNING,
    STOPPED,
    TASK_STATES,
    Experiment,
    Store,
)

CODE_DIR = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).resolve().parent / "dashboard.html"
RECENT = 10
PROBLEMS = 20


class Board:
    """把所有实验的记录整理成仪表盘要显示的现状。只读。"""

    def __init__(self, home: Path, watch: MachineWatch | None = None):
        self.home = Path(home)
        self.store = Store(self.home)
        self.watch = watch
        self.cache: dict[str, tuple] = {}
        self.reads = 0  # 实际读了几次记录文件，测试用

    def summary(self, exp_id: str) -> dict:
        """一个实验的摘要。记录文件没变就用上次算好的。"""
        path = self.store.root / exp_id / RECORD_FILE
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = self.cache.get(exp_id)
        if cached and cached[0] == key:
            return cached[1]
        try:
            self.reads += 1
            v = Experiment(self.store, exp_id).view()
        except ValueError:  # 正好读到写了一半的一行：先用上次的
            if cached:
                return cached[1]
            return {"id": exp_id, "status": "读不出来", "unreadable": True}
        states = [t["state"] for t in v["tasks"].values()]
        started = next((o["time"] for o in v["operations"] if o["op"] == "启动"), "")
        s = {
            "id": exp_id,
            "status": v["status"],
            "plugin": f"{v['plugin'].get('name', '')} {v['plugin'].get('version', '')}".strip(),
            "category": v["plugin"].get("category", ""),
            "note": v["note"],
            "tags": v["tags"],
            "created": v["created"],
            "started": started,
            "updated": v["updated"],
            "counts": {state: states.count(state) for state in TASK_STATES if state in states},
            "tasks": [
                {
                    "name": name,
                    "state": t["state"],
                    "stage": t["stage"],
                    "machine": t["machine"],
                    "since": t["history"][-1]["time"],
                }
                for name, t in v["tasks"].items()
            ],
            "problems": [
                {"time": p["time"], "task": p["task"], "error": p["error"]} for p in v["problems"]
            ],
        }
        self.cache[exp_id] = (key, s)
        return s

    def state(self) -> dict:
        all_ = []
        for exp_id in self.store.ids():
            try:
                all_.append(self.summary(exp_id))
            except OSError:  # 文件夹正好被拿走
                continue
        good = [s for s in all_ if not s.get("unreadable")]
        running = [s for s in good if s["status"] in (RUNNING, PAUSED)]
        ended = [s for s in good if s["status"] in (FINISHED, STOPPED)]
        problems = [
            {**p, "id": s["id"]} for s in good for p in s["problems"]
        ]
        return {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "home": str(self.home),
            "total": len(all_),
            "running": sorted(running, key=lambda s: s["started"]),
            "not_started": [s for s in good if s["status"] == NOT_STARTED],
            "recent": sorted(ended, key=lambda s: s["updated"], reverse=True)[:RECENT],
            "ended_total": len(ended),
            "problems": sorted(problems, key=lambda p: p["time"], reverse=True)[:PROBLEMS],
            "problems_total": len(problems),
            "unreadable": [s["id"] for s in all_ if s.get("unreadable")],
            "machines": self.watch.snapshot() if self.watch else [],
        }


def make_handler(board: Board):
    class Handler(BaseHTTPRequestHandler):
        """只有 GET。别的方法一律不接。"""

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
            elif path == "/api/state":
                body = json.dumps(board.state(), ensure_ascii=False).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", body)
            else:
                self._send(404, "text/plain; charset=utf-8", "没有这个地址".encode("utf-8"))

        def _send(self, code: int, ctype: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # 不往控制台刷访问记录
            pass

    return Handler


def serve(home: Path, host: str, port: int, with_machines: bool = True) -> tuple[ThreadingHTTPServer, MachineWatch | None]:
    watch = MachineWatch(home) if with_machines else None
    if watch:
        watch.start()
    server = ThreadingHTTPServer((host, port), make_handler(Board(home, watch)))
    return server, watch


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stemlab.dashboard", description="仪表盘：只读的任务现状网页。")
    ap.add_argument("--home", help="放 experiments 的文件夹。默认是环境变量 STEMLAB_HOME，再默认是代码所在的文件夹。")
    ap.add_argument("--host", default="127.0.0.1", help="默认只在本机能打开")
    ap.add_argument("--port", type=int, default=8791)
    args = ap.parse_args(argv)
    home = Path(args.home or os.environ.get("STEMLAB_HOME") or CODE_DIR)
    server, watch = serve(home, args.host, args.port)
    print(f"仪表盘开在 http://{args.host}:{args.port}/ ，读的是 {home} 。按 Ctrl+C 关掉。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if watch:
            watch.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
