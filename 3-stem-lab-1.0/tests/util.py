"""测试用的小工具：一个临时的数据目录，加一个开在随机端口上的页面服务。"""
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from stemlab import ledger, runs, things, web  # noqa: E402


class Lab:
    def __init__(self):
        self.data = tempfile.mkdtemp(prefix="stemlab-test-")
        self.srv = web.make_server(self.data, 0)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.data, ignore_errors=True)

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.url, r.read().decode("utf-8")

    def post(self, path, form, origin=None):
        req = urllib.request.Request(self.base + path, urllib.parse.urlencode(form).encode("utf-8"),
                                     headers={"Origin": origin or self.base})
        with urllib.request.urlopen(req) as r:
            return r.url, r.read().decode("utf-8")

    def register(self, type_, name, rel):
        return things.register(self.data, type_, name, os.path.join(REPO, rel))[0]

    def method(self, folder):
        return self.register("做法", "", "methods/" + folder)

    def form(self, m, inputs, gates=None, **settings):
        """照做法的默认值拼一份新建页的表单；停顿设成 0，好跑得快。"""
        spec = things.read_method(things.where(self.data, m))
        f = {"method": m["n"], "action": "start", "title": "测试 " + m["name"]}
        for s in spec.get("settings", []):
            if s["kind"] != "开关" or s.get("default"):
                f["set_" + s["key"]] = "1" if s["kind"] == "开关" else s.get("default", "")
        f["set_pause"] = 0
        for k, v in settings.items():
            f["set_" + k] = v
        for k, t in inputs.items():
            f["in_" + k] = t["n"] if t else ""
        for r in spec.get("reports", []):
            op, val = (gates or {}).get(r["key"], ("", ""))
            f["gop_" + r["key"]], f["gval_" + r["key"]] = op, val
        return f

    def start(self, form):
        """在新建页上点“封存并启动”，返回新实验的编号。"""
        url, html = self.post("/new", form)
        found = re.search(r"/exp\?id=(\d+)", url)
        assert found, "没有启动起来：" + re.sub(r"<[^>]+>", " ", html)[:600]
        return int(found.group(1))

    def wait(self, n, timeout=60):
        """等实验不在跑了，返回它的现状。"""
        end = time.time() + timeout
        while time.time() < end:
            info = runs.status(self.data, ledger.state(self.data).exps[n])
            if info["word"] != "在跑":
                return info
            time.sleep(0.2)
        raise AssertionError(f"实验 {n} 等了 {timeout} 秒还没跑完")

    def state(self):
        return ledger.state(self.data)
