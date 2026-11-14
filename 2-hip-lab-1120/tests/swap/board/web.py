"""只读的网页——另一种写法：两个地址，都是 JSON。别的方法一律不收。

    python -m stemlab.board [--port 8791]
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from stemlab.board import alerts, experiments, machines

READ_PATHS = ("/", "/numbers.json")


def numbers() -> dict:
    listed = experiments.all_of_them()
    return {"experiments": listed, "warnings": alerts.warnings(listed), "machines": machines.names()}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] not in READ_PATHS:
            self.send_error(404)
            return
        body = json.dumps(numbers(), ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _no(self):
        self.send_error(405, "read only")

    do_POST = do_PUT = do_DELETE = do_PATCH = _no

    def log_message(self, *args):
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stemlab.board")
    parser.add_argument("--port", type=int, default=8791)
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
