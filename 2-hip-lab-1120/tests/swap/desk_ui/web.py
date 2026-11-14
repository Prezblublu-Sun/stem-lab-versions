"""网页——另一种写法：一页纯文字。只绑本机；写的请求只有一个地址，要带请求头，转给操作台核心。

    python -m stemlab.desk.ui.web [--port 8790]
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from stemlab.contract import Refused
from stemlab.desk.core import actions
from stemlab.desk.ui import views

READ_PATHS = ("/", "/experiments.json")
WRITE_PATHS = ("/act",)
WRITE_HEADER = "X-Other-Desk-Write"
ACTS = {"note": lambda body: actions.note(body["experiment"], body["text"])}


class Handler(BaseHTTPRequestHandler):
    def _answer(self, status: int, body: bytes, kind: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            lines = [f"{one['id']}  {one.get('type', '')}  {one.get('label', '')}" for one in views.experiments()]
            self._answer(200, ("another desk page\n" + "\n".join(lines)).encode("utf-8"), "text/plain; charset=utf-8")
        elif path == "/experiments.json":
            self._answer(200, json.dumps(views.experiments(), ensure_ascii=False, default=str).encode("utf-8"))
        else:
            self._answer(404, b'{"missing": true}')

    def do_POST(self):
        if self.path.split("?", 1)[0] not in WRITE_PATHS:
            self._answer(405, b'{"refused": "not a place to write"}')
            return
        if self.headers.get(WRITE_HEADER) != "1":
            self._answer(403, b'{"refused": "a write needs its header"}')
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
            ACTS[body["op"]](body)
        except Refused as error:
            self._answer(200, json.dumps({"ok": False, "refused": str(error)}, ensure_ascii=False).encode("utf-8"))
        except (KeyError, TypeError, ValueError, LookupError) as error:
            self._answer(400, json.dumps({"ok": False, "refused": str(error)}, ensure_ascii=False).encode("utf-8"))
        else:
            self._answer(200, json.dumps({"ok": True}).encode("utf-8"))

    def _no(self):
        self._answer(405, b'{"refused": "GET, or POST to the one write address"}')

    do_PUT = do_DELETE = do_PATCH = _no

    def log_message(self, *args):
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stemlab.desk.ui.web")
    parser.add_argument("--port", type=int, default=8790)
    server = ThreadingHTTPServer(("127.0.0.1", parser.parse_args(argv).port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
