"""网页，只绑本机。读的请求是 GET；写的请求只有 POST /api/do 一个，要带一个专门的请求头，全部转给操作台核心。

    python -m stemlab.desk.ui.web [--port 8790] [--open]

--open 是开起来之后顺手在浏览器里打开。要从仓库根目录跑；从别处用根目录下的 desk-web.cmd。

有实验页和 case 页，都在一个页面里（page.html）。这是展示层，可以整个重写。
写的请求头（X-Stemlab-Write: 1）是为了挡住别的网页偷偷替你点：浏览器不会让别处来的页面带上自定义的头。
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from stemlab.contract import Refused, kinds
from stemlab.desk import core
from stemlab.desk.core import actions, query, start
from stemlab.desk.ui import progress
from stemlab.experiments import reader, view
from stemlab.registry import lookup

READ_PATHS = ("/", "/api/experiments", "/api/types", "/api/items", "/api/all")     # 固定的读请求。守边界的测试照着它逐个去取
WRITE_PATHS = ("/api/do",)
WRITE_HEADER = "X-Stemlab-Write"
PAGE = Path(__file__).with_name("page.html")
HOST = "127.0.0.1"


def _experiments() -> list[dict]:
    found = []
    for experiment in reader.all_ids():
        try:
            found.append(view.summary(experiment))
        except (LookupError, ValueError) as error:
            found.append({"id": experiment, "type": "?", "label": "记录读不出来", "note": str(error), "round": 0, "tasks": {},
                          "problems": 0, "tags": [], "bones": [], "state": None, "result": None})
    return found


def _types() -> dict:
    loaded = query.types()
    listed = [{"name": name, "label": kind.label, "where": kind.where,
               "inputs": [{"name": row.name, "kinds": list(row.kinds), "many": row.many, "required": row.required, "label": row.label}
                          for row in kind.inputs],
               "outputs": [{"name": row.name, "kind": row.kind, "label": row.label} for row in kind.outputs]}
              for name, kind in sorted(loaded.kinds.items())]
    return {"types": listed, "errors": dict(loaded.errors),
            "kinds": {name: one.label for name, one in kinds.ITEM_KINDS.items()}}


def _item(item_id: str) -> dict:
    item = lookup.get(item_id)
    content = item["content"] if item["storage"] == kinds.STORE_VALUE else str(lookup.content(item_id))
    return {"item": item, "content": content, "upstream": query.upstream(item_id), "downstream": query.downstream(item_id)}


def _all() -> list[dict]:
    """每个实验的进展和它的每一张图。给“整个导出来看”用，也让守边界的测试把读的路都走一遍。"""
    found = []
    for one in _experiments():
        try:
            shown = progress.progress(one["id"])
        except (LookupError, ValueError):
            continue
        found.append({"progress": shown, "charts": {chart["name"]: progress.chart(one["id"], chart["name"]) for chart in shown["charts"]}})
    return found


def read(path: str, asked: dict):
    """一个读请求的答案。没有这个地址就是 None。"""
    parts = [unquote(part) for part in path.strip("/").split("/")]
    if path == "/api/experiments":
        return _experiments()
    if path == "/api/types":
        return _types()
    if path == "/api/items":
        return lookup.find(asked.get("kind", [None])[0] or None, asked.get("name", [None])[0] or None)
    if path == "/api/all":
        return _all()
    if parts[:2] == ["api", "experiment"] and len(parts) == 3:
        return progress.progress(parts[2])
    if parts[:2] == ["api", "experiment"] and len(parts) == 5 and parts[3] == "chart":
        return progress.chart(parts[2], parts[4])
    if parts[:2] == ["api", "item"] and len(parts) == 3:
        return _item(parts[2])
    if parts[:2] == ["api", "case"] and len(parts) == 3:
        return {"case": lookup.get(parts[2]), "under": query.under_case(parts[2])}
    if parts[:2] == ["api", "bone"] and len(parts) == 3:
        return query.same_bone(parts[2])
    return None


def _called(result) -> dict:
    return {"ran": result.ok, "error": result.error}


# 写的请求：op -> 转给核心的哪个函数。每一个都只是转调
OPS = {
    "new": lambda body: actions.new(body["type"], body.get("note", ""), body.get("tags") or []),
    "clone": lambda body: actions.clone(body["experiment"], body.get("note")),
    "fill": lambda body: actions.fill(body["experiment"], body["input"], body.get("items") or []) and None,
    "note": lambda body: actions.note(body["experiment"], body["text"]) and None,
    "tag": lambda body: actions.tag(body["experiment"], body.get("add") or [], body.get("remove") or []) and None,
    "start": lambda body: _called(start.start(body["experiment"], body.get("rerun") or [])),
    "stop": lambda body: _called(start.stop(body["experiment"])),
    "poll": lambda body: _called(start.poll(body["experiment"])),
}


def do(body) -> tuple[int, dict]:
    """一个写请求：转给核心。返回（状态码，答案）。被拒不是出错：照实把原因交回去。"""
    if not isinstance(body, dict) or body.get("op") not in OPS:
        return 400, {"ok": False, "refused": f"op 只有这几个：{sorted(OPS)}"}
    try:
        return 200, {"ok": True, "result": OPS[body["op"]](body)}
    except Refused as error:
        return 200, {"ok": False, "refused": str(error)}
    except (KeyError, TypeError) as error:              # 要先接：KeyError 也算一种 LookupError
        return 400, {"ok": False, "refused": f"这个请求少了东西或者写得不对：{error}"}
    except LookupError as error:
        return 200, {"ok": False, "refused": f"找不到：{error}"}


def listening(host: str, port: int) -> bool:
    """这个端口上是不是已经有服务在听了。port 是 0（让系统挑一个）就不用看。"""
    if port == 0:
        return False
    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1" if host in ("", "0.0.0.0") else host, port)) == 0


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, kind: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))

    def do_GET(self):
        split = urlsplit(self.path)
        if split.path == "/":
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        try:
            found = read(split.path, parse_qs(split.query))
        except (LookupError, ValueError, Refused) as error:
            self._json(404, {"error": str(error)})
            return
        if found is None:
            self._json(404, {"error": "没有这个地址"})
        else:
            self._json(200, found)

    def do_POST(self):
        if urlsplit(self.path).path not in WRITE_PATHS:
            self._json(404, {"error": "没有这个地址"})
        elif self.headers.get(WRITE_HEADER) != "1":
            self._json(403, {"ok": False, "refused": f"写的请求要带请求头 {WRITE_HEADER}: 1"})
        else:
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
            except ValueError:
                body = None
            self._json(*do(body))

    def _refuse(self):
        self._json(405, {"error": "只收 GET 和 POST /api/do"})

    do_PUT = do_DELETE = do_PATCH = _refuse

    def log_message(self, *args):           # 不往终端刷每一次请求
        pass


def main(argv=None) -> int:
    core.utf8_console()
    parser = argparse.ArgumentParser(prog="python -m stemlab.desk.ui.web", description="操作台的网页：看一个实验的细节和图表，点启动、停止")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--open", action="store_true", help="开起来之后顺手在浏览器里打开")
    args = parser.parse_args(argv)
    if listening(HOST, args.port):                      # 已经开着了：不起第二个（Windows 上两个进程能绑到同一个端口）
        url = f"http://{HOST}:{args.port}/"
        print(f"{args.port} 端口上已经有服务开着了，多半就是操作台的网页：直接打开 {url}", flush=True)
        if args.open:
            webbrowser.open(url)
        return 0
    server = ThreadingHTTPServer((HOST, args.port), Handler)
    url = f"http://{HOST}:{server.server_address[1]}/"
    print(f"操作台的网页开在 {url} ，只有本机打得开，按 Ctrl+C 关掉", flush=True)
    if args.open:
        webbrowser.open(url)                            # 端口这时已经在听了，浏览器来早了也等得到
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
