"""操作台（网页）。

和命令行操作台是同一个操作台，换成在网页上点。它做的每件事都经过 Desk，自己不碰记录。
定时值守也开在这里。

它和仪表盘是两个服务：仪表盘只读，这里能改东西。所以
  - 只开在本机（127.0.0.1），没有换地址的开关；
  - 改东西的请求必须带一个专门的请求头，别的网页发不出这样的请求。

运行：python -m stemlab.console_web [--home 文件夹] [--port 8792] [--every 15]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

if __package__ in (None, ""):  # 直接当脚本跑时，把仓库根加进来
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stemlab.console import OP_HOOK, Desk, parse_value
from stemlab.record import RecordError, now
from stemlab.watch import Watch

CODE_DIR = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).resolve().parent / "console.html"
HOST = "127.0.0.1"
HEADER = "X-Stemlab-Desk"  # 改东西的请求要带的请求头
MAX_BODY = 1 << 20


class WebDesk:
    """网页背后的那个操作台，加上值守。"""

    def __init__(self, home: Path, every: float = 15.0):
        self.home = Path(home)
        self.desk = Desk(self.home)
        self.watch = Watch(lambda: self.desk, every=every)

    def reload(self) -> None:
        """重新读一遍插件文件夹。"""
        self.desk = Desk(self.home)

    def state(self) -> dict:
        desk = self.desk
        return {
            "time": now(),
            "home": str(self.home),
            "plugins": desk.plugin_info(),
            "plugin_errors": list(desk.plugin_errors),
            "experiments": desk.rows(),
            "watch": self.watch.status(),
        }

    def do(self, body: dict) -> dict:
        """做一件事。做不了抛 RecordError。"""
        desk = self.desk
        action = body.get("action")

        def need(key: str) -> str:
            value = body.get(key)
            if not isinstance(value, str) or not value.strip():
                raise RecordError(f"少了一项：{key}")
            return value.strip()

        if action == "new":
            tags = [str(t).strip() for t in body.get("tags") or [] if str(t).strip()]
            exp_id = desk.new(need("plugin"), note=str(body.get("note") or "").strip(), tags=tags)
            return {"message": f"新建了 {exp_id}。", "id": exp_id}

        if action == "set":
            exp_id, name, kind = need("exp"), need("name"), body.get("kind")
            given: dict = {}
            if kind == "值":
                given["value"] = parse_value(need("value"))
            elif kind in ("复制", "位置"):
                path = need("path")
                if not Path(path).is_absolute():
                    raise RecordError("文件的位置要写完整的路径。")
                given["file" if kind == "复制" else "ref"] = path
            elif kind == "产出":
                given["from_exp"], given["output"] = need("from_exp"), need("output")
            else:
                raise RecordError("内容要选一种：一个值、复制文件、只记位置，或另一个实验的产出。")
            desk.set(
                exp_id, name, source=str(body.get("source") or "").strip(),
                when=str(body.get("when") or "").strip(), **given,
            )
            return {"message": f"{exp_id} 的设置「{name}」已填。"}

        if action == "op":
            exp_id, op = need("exp"), body.get("op")
            if op not in OP_HOOK:
                raise RecordError(f"没有这种操作：{op}")
            ok = getattr(desk, OP_HOOK[op])(exp_id)
            if ok:
                return {"message": f"{exp_id} 已{op}。"}
            return {"message": f"{exp_id} 已{op}，但插件出了问题，已记进记录。", "warn": True}

        if action == "refresh":
            exp_id = body.get("exp") or None
            seen = desk.refresh(exp_id)
            return {"message": "看过：" + ("、".join(seen) if seen else "没有能看的实验（不在运行中，或别处正在动它）")}

        if action == "note":
            exp_id = need("exp")
            desk.note(exp_id, need("text"))
            return {"message": f"{exp_id} 的备注已记。"}

        if action == "tag":
            exp_id = need("exp")
            add = [str(t).strip() for t in body.get("add") or [] if str(t).strip()]
            remove = [str(t).strip() for t in body.get("remove") or [] if str(t).strip()]
            if not add and not remove:
                raise RecordError("没有写要加或要去掉的标签。")
            desk.tag(exp_id, add=add, remove=remove)
            return {"message": f"{exp_id} 的标签已改。"}

        if action == "reload":
            self.reload()
            names = "、".join(self.desk.plugins) or "（无）"
            bad = len(self.desk.plugin_errors)
            return {"message": f"重新读了插件。装着的有：{names}" + (f"；装不上 {bad} 个" if bad else ""), "warn": bool(bad)}

        raise RecordError(f"不认识的动作：{action}")


def make_handler(web: WebDesk):
    class Handler(BaseHTTPRequestHandler):
        def _own_hosts(self) -> set:
            port = self.server.server_address[1]
            return {f"127.0.0.1:{port}", f"localhost:{port}"}

        def _host_ok(self) -> bool:
            # 只认用本机地址打开的请求；用别的域名指过来的（DNS 重绑定）不接
            return self.headers.get("Host", "") in self._own_hosts()

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "只能用本机地址打开。"})
            url = urlsplit(self.path)
            path = unquote(url.path)
            try:
                if path in ("/", "/index.html"):
                    return self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
                if path == "/api/state":
                    return self._json(200, web.state())
                if path.startswith("/api/exp/"):
                    return self._json(200, web.desk.detail(path[len("/api/exp/"):]))
                if path == "/api/check":
                    exp_id = (parse_qs(url.query).get("exp") or [None])[0]
                    return self._json(200, {"time": now(), "checked": web.desk.check_all(exp_id)})
                return self._json(404, {"error": "没有这个地址"})
            except RecordError as err:
                return self._json(400, {"error": str(err)})
            except Exception as err:  # 读的时候出问题：说出来，服务不倒
                return self._json(500, {"error": f"{type(err).__name__}: {err}", "raw": traceback.format_exc()})

        def do_POST(self):
            if not self._host_ok():
                return self._json(403, {"error": "只能用本机地址打开。"})
            if self.headers.get(HEADER) != "1":
                return self._json(403, {"error": f"改东西的请求要带请求头 {HEADER}。"})
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{h}" for h in self._own_hosts()}:
                return self._json(403, {"error": "不接别的网页发来的请求。"})
            if urlsplit(self.path).path != "/api/do":
                return self._json(404, {"error": "没有这个地址"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= MAX_BODY:
                    return self._json(400, {"error": "请求的内容是空的，或者太大。"})
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("不是一个对象")
            except (ValueError, UnicodeDecodeError) as err:
                return self._json(400, {"error": f"请求的内容读不出来：{err}"})
            try:
                return self._json(200, {"ok": True, **web.do(body)})
            except RecordError as err:
                return self._json(400, {"error": f"没有做：{err}"})
            except Exception as err:  # 出问题是正常的：说出来，服务不倒
                return self._json(500, {"error": f"出了问题：{type(err).__name__}: {err}", "raw": traceback.format_exc()})

        def _json(self, code: int, data: dict):
            self._send(code, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode("utf-8"))

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


def serve(home: Path, port: int, every: float = 15.0, watch: bool = True) -> tuple[ThreadingHTTPServer, WebDesk]:
    """开服务。只绑本机。watch 为假时不开值守（测试用）。"""
    web = WebDesk(home, every=every)
    server = ThreadingHTTPServer((HOST, port), make_handler(web))
    if watch:
        web.watch.start()
    return server, web


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stemlab.console_web", description="操作台（网页）：操作实验，并把操作记下来。带定时值守。")
    ap.add_argument("--home", help="放 experiments 和 plugins 的文件夹。默认是环境变量 STEMLAB_HOME，再默认是代码所在的文件夹。")
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--every", type=float, default=15, help="值守隔几秒看一次，默认 15")
    ap.add_argument("--no-watch", action="store_true", help="不开值守")
    args = ap.parse_args(argv)
    home = Path(args.home or os.environ.get("STEMLAB_HOME") or CODE_DIR)
    server, web = serve(home, args.port, every=args.every, watch=not args.no_watch)
    print(f"操作台开在 http://{HOST}:{args.port}/ ，用的是 {home} 。按 Ctrl+C 关掉。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        web.watch.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
