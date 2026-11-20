"""页面服务：只听 127.0.0.1。看页面用 GET；会往账本里写的一律用 POST，并且核对 Origin——
不然随便哪个网页都能让这台机器登记并运行一个做法。"""
import json
import math
import os
import tomllib
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from . import ledger, pages, runs, things
from .things import METHOD, Problem

TEXT = "text/plain; charset=utf-8"
CATALOG = os.path.join(os.path.dirname(runs.SYSTEM), "examples", "catalog.toml")   # 自带模板和示例材料的清单
IMAGES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


class Handler(BaseHTTPRequestHandler):
    data = ""   # 数据目录和端口，起服务时填上
    port = 0

    def log_message(self, *args):   # 不往控制台刷每一个请求
        pass

    def send(self, body, code=200, ctype="text/html; charset=utf-8", headers=()):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def go(self, url):
        self.send_response(303)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def ours(self, host):
        return host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def safely(self, fn):
        try:
            fn()
        except Exception:
            self.send(pages.page("出错了", "<p>程序出了毛病，不是你填错了。下面这段是给写程序的人看的：</p>"
                                 f"<pre>{pages.e(traceback.format_exc())}</pre>"), 500)

    def do_GET(self):
        if not self.ours(self.headers.get("Host", "")):
            return self.send("只接本机 127.0.0.1 上的访问。", 403, TEXT)
        url = urlsplit(self.path)
        self.safely(lambda: self.get(url.path, {k: v[-1] for k, v in parse_qs(url.query).items()}))

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if not (self.ours(self.headers.get("Host", "")) and origin.startswith("http://")
                and self.ours(origin[len("http://"):])):
            return self.send("只接本机这个页面自己发来的操作。", 403, TEXT)
        length = _int(self.headers.get("Content-Length")) or 0
        if length > 5 * 2 ** 20:
            return self.send("提交的内容太大了。", 413, TEXT)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        form = {k: v[-1] for k, v in parse_qs(body, keep_blank_values=True).items()}
        self.safely(lambda: self.post(urlsplit(self.path).path, form))

    # ---------- 看 ----------

    def get(self, path, q):
        d, n = self.data, _int(q.get("id"))
        if path == "/":
            return self.send(pages.dashboard(d))
        if path == "/live":
            return self.send(pages.dashboard_live(d))
        if path == "/new":
            v, notes = new_values(d, q)
            return self.send(pages.new_form(d, v, notes=notes))
        if path == "/exps":
            return self.send(pages.exps_list(d, q.get("cat", "")))
        if path == "/exp":
            return self.send(pages.experiment(d, n))
        if path == "/exp_live" and n in ledger.state(d).exps:
            return self.send(pages.experiment_live(d, n))
        if path == "/things":
            return self.send(pages.things_page(d))
        if path == "/check":
            return self.send(pages.check_page(d, q.get("go") == "1"))
        if path == "/file":
            return self.file(n, q.get("path", ""))
        self.send(pages.page("没有这一页", '<p><a href="/">回仪表盘</a></p>'), 404)

    def file(self, n, rel):
        """只许读实验目录里的文件。"""
        run = runs.run_dir(self.data, n or 0)
        full = os.path.realpath(os.path.join(run, rel))
        if n is None or not runs.inside(run, rel) or not os.path.isfile(full):
            return self.send("只能看实验目录里的文件；这个不在里面，或者不存在。", 404, TEXT)
        size = os.path.getsize(full)
        if size > 20 * 2 ** 20:
            return self.send(f"这个文件有 {size // 2 ** 20} MB，太大，不在页面上打开。它在：{full}", 200, TEXT)
        with open(full, "rb") as f:
            raw = f.read()
        image = IMAGES.get(os.path.splitext(full)[1].lower())
        if image:   # 做法画的图：给对的类型；SVG 是别人写的，不许它跑脚本
            return self.send(raw, 200, image, [("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; sandbox"),
                                               ("X-Content-Type-Options", "nosniff")])
        for enc in ("utf-8", "gbk"):
            try:
                return self.send(raw.decode(enc), 200, TEXT)
            except UnicodeDecodeError:
                pass
        self.send(raw, 200, "application/octet-stream",
                  [("Content-Disposition", f"attachment; filename*=UTF-8''{quote(os.path.basename(full))}")])

    # ---------- 写 ----------

    def post(self, path, form):
        d = self.data
        if path == "/new":
            return self.post_new(form)
        if path == "/register":
            try:
                _, told = things.register(d, form.get("type", ""), form.get("name", ""), form.get("path", ""),
                                          form.get("note", ""))
            except Problem as err:
                return self.send(pages.things_page(d, form, errors=[str(err)]))
            return self.send(pages.things_page(d, notes=[told]))
        if path == "/register_all":
            return self.send(pages.things_page(d, **register_catalog(d)))
        n = _int(form.get("id"))
        x = ledger.state(d).exps.get(n)
        if not x:
            return self.send(pages.page("找不到这个实验", '<p><a href="/exps">回到实验列表</a></p>'), 404)
        now = runs.status(d, x)["word"]
        if path == "/stop":
            if now != "在跑":
                return self.send(pages.experiment(d, n, errors=[f"它现在是“{now}”，不在跑，不用停。"]))
            try:
                runs.stop(d, n)
            except Problem as err:
                return self.send(pages.experiment(d, n, errors=[str(err)]))
            return self.go(f"/exp?id={n}")
        if path == "/continue":
            if now not in ("中断", "失败", "停了", "没启动"):
                return self.send(pages.experiment(d, n, errors=[f"它现在是“{now}”，不用继续。"]))
            try:
                runs.start(d, n)
            except Problem as err:
                return self.send(pages.experiment(d, n, errors=[str(err)]))
            return self.go(f"/exp?id={n}")
        self.send(pages.page("没有这一页", '<p><a href="/">回仪表盘</a></p>'), 404)

    def post_new(self, form):
        """新建页上的三个按钮：照外来的设置填表、把变了的东西登记成新的一版、封存并启动。"""
        d = self.data
        st = ledger.state(d)
        m = st.things.get(_int(form.get("method")))
        if not m or m["type"] != METHOD:
            return self.go("/new")
        try:
            spec = things.read_method(things.where(d, m))
        except Problem:   # 新建页会把读不出来的原因说清楚
            return self.go(f"/new?method={m['n']}")
        v = {"method": m["n"], "from": _int(form.get("from")), "title": form.get("title", "").strip(),
             "inputs": {i["key"]: _int(form.get("in_" + i["key"])) for i in spec.get("inputs", [])},
             "settings": {s["key"]: form.get("set_" + s["key"], "") for s in spec.get("settings", [])},
             "gates": {r["key"]: (form.get("gop_" + r["key"], ""), form.get("gval_" + r["key"], "").strip())
                       for r in spec.get("reports", [])},
             "fill_json": form.get("fill_json", ""), "fill_path": form.get("fill_path", "")}
        action = form.get("action", "start")
        if action == "fill":
            errors, notes = fill(v, spec)
            return self.send(pages.new_form(d, v, errors, notes))
        if action.startswith("rereg:"):   # 照原处的文件再登记一次：恢复留底，或成为新的一版，并选上
            key = action[len("rereg:"):]
            old = m if key == "做法" else st.things.get(v["inputs"].get(key))
            if old is None:
                return self.send(pages.new_form(d, v, ["没登记上：这一项现在没选东西。"]))
            made_by = (old.get("source") or {}).get("experiment")
            note = (f"这是 e{made_by:04d} 的产出跑完以后被人改过的样子，不是它原来的产出" if made_by
                    else f"照{things.label(old)}的原处重新登记")
            try:
                t, told = things.register(d, old["type"], old["name"], old["path"] or things.where(d, old), note)
            except Problem as err:
                return self.send(pages.new_form(d, v, [f"没登记上：{err}"]))
            if t["n"] == old["n"]:
                told += "选的还是它。"
            else:
                told += ("" if made_by else f"原处的文件已经改过，{things.label(old)}的留底恢复不了。") + \
                        f"选择已经换成{things.label(t)}。"
            if key == "做法":
                v["method"] = t["n"]
            else:
                v["inputs"][key] = t["n"]
            return self.send(pages.new_form(d, v, notes=[told]))
        errors, inputs, settings, gates = [], {}, {}, []
        for i in spec.get("inputs", []):
            t = st.things.get(v["inputs"][i["key"]])
            if t is None and not i.get("optional"):
                errors.append(f'「{i.get("label") or i["key"]}」还没选')
            inputs[i["key"]] = t
        for s in spec.get("settings", []):
            try:
                settings[s["key"]] = things.parse_value(s, v["settings"][s["key"]])
            except Problem as err:
                errors.append(str(err))
        for r in spec.get("reports", []):
            op, val = v["gates"][r["key"]]
            if op in runs.OPS:
                try:
                    value = float(val)
                    if not math.isfinite(value):
                        raise ValueError
                    gates.append({"metric": r["key"], "op": op, "value": value})
                except ValueError:
                    errors.append(f'门槛「{r.get("name") or r["key"]}」要填一个实实在在的数，现在是 {val!r}')
        if errors:
            return self.send(pages.new_form(d, v, errors))
        changed = runs.changed_uses(d, st, m, inputs)
        if changed:
            return self.send(pages.new_form(d, v, ["有东西和登记时不一样了，不能启动。看下面红色的几行。"],
                                            changed=changed))
        title = v["title"] or f'{m["name"]} {ledger.now()[5:16]}'
        x = runs.seal(d, m["category"], title, m, inputs, settings, gates, v["from"])
        try:
            runs.start(d, x["n"], verify=False)
        except Problem as err:   # 封存了但没启动起来：落到实验页上说清楚
            return self.send(pages.experiment(d, x["n"], errors=[str(err)]))
        self.go(f"/exp?id={x['n']}")


def new_values(data, q):
    """从网址参数（选了哪一类、哪个做法、照哪个实验开）得到新建页一开始的值。"""
    v = {"cat": q.get("cat", ""), "method": _int(q.get("method")), "inputs": {}, "settings": {}, "gates": None}
    src = ledger.state(data).exps.get(_int(q.get("from")))
    if not src:
        return v, []
    s = src["seal"]
    v.update(method=s["method"]["n"], **{"from": s["n"]},
             inputs={k: (r["n"] if r else None) for k, r in s["inputs"].items()}, settings=dict(s["settings"]),
             gates={g["metric"]: (g["op"], pages.fmt(g["value"])) for g in s["gates"]})
    return v, [f'照 {pages.eid(s["n"])}「{s["title"]}」填好了：同一个做法、同样的东西、同样的设置和门槛。'
               f'改你想改的再启动；{pages.eid(s["n"])} 原样留着。']


def fill(v, spec):
    """照一份外来的设置填表。认得的填进去，认不得的列出来，不悄悄丢。返回 (出错的话, 提示的话)。"""
    text, path = v["fill_json"].strip(), v["fill_path"].strip().strip('"')
    try:
        if path:
            with open(path, "rb") as f:
                raw = f.read().decode("utf-8-sig")
            obj = tomllib.loads(raw) if path.lower().endswith(".toml") else json.loads(raw)
        else:
            obj = json.loads(text)
    except (OSError, ValueError) as err:
        return [f"读不出这份设置：{err}"], []
    if isinstance(obj, dict) and isinstance(obj.get("settings"), dict):
        obj = obj["settings"]   # task.json 和封存记录都把设置放在 settings 里，也认
    if not isinstance(obj, dict):
        return ["这份设置应该是 {\"键\": 值, …} 的样子。"], []
    known = {}
    for s in spec.get("settings", []):
        known[s["key"]] = s
        known.setdefault(s.get("name"), s)
    filled, unknown, errors = [], [], []
    for k, val in obj.items():
        s = known.get(k)
        if not s:
            unknown.append(str(k))
            continue
        v["settings"][s["key"]] = val
        filled.append(s.get("name") or s["key"])
        try:
            things.parse_value(s, val)
        except Problem as err:
            errors.append(str(err))
    if unknown:
        errors.insert(0, f"这 {len(unknown)} 项认不得（这个做法没有这些设置），没有填：{'、'.join(unknown)}")
    return errors, [f"照这份设置填了 {len(filled)} 项：{'、'.join(filled)}。" if filled
                    else "这份设置里没有一项是这个做法认得的。"]


def register_catalog(data):
    """把自带清单（examples/catalog.toml）里还没登记的全部登记进来；登记过、内容没变的不会多出来。"""
    try:
        with open(CATALOG, "rb") as f:
            items = tomllib.load(f).get("item", [])
    except (OSError, ValueError) as err:
        return {"errors": [f"自带清单 {CATALOG} 读不出来：{err}"]}
    told, errors = [], []
    for it in items:
        try:
            told.append(things.register(data, it.get("type", ""), it.get("name", ""),
                                        os.path.join(os.path.dirname(CATALOG), it.get("path", "")), it.get("note", ""))[1])
        except Problem as err:
            errors.append(f"自带清单里的 {it.get('path')}：{err}")
    new = [t for t in told if t.startswith("登记好了")]
    same = len(told) - len(new)
    return {"errors": errors, "notes": new + ([f"{same} 样早就登记过、内容没变，没有多出来。"] if same else [])}


def make_server(data, port):
    handler = type("Bound", (Handler,), {"data": data})
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    srv.daemon_threads = True
    handler.port = srv.server_address[1]
    return srv
