"""网页操作台的测试，以及操作台、仪表盘、地基连起来的整体测试。

每个测试用一个临时文件夹当 home，服务开在随机端口上，不碰真的 experiments。
"""
import hashlib
import http.client
import json
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from stemlab import console_web
from stemlab.console import Desk
from stemlab.dashboard import serve as serve_dashboard

REPO = Path(__file__).resolve().parent.parent
HEADERS = {"Content-Type": "application/json", console_web.HEADER: "1"}


class Site:
    """开着的网页操作台，加上发请求的几个手。"""

    def __init__(self, home: Path, watch: bool):
        self.home = home
        self.server, self.web = console_web.serve(home, 0, every=0.05, watch=watch)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.web.watch.stop()

    def get(self, path: str):
        return json.loads(urllib.request.urlopen(self.base + path).read().decode("utf-8"))

    def page(self) -> str:
        return urllib.request.urlopen(self.base + "/").read().decode("utf-8")

    def post(self, body: dict, headers: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            self.base + "/api/do", data=json.dumps(body).encode("utf-8"),
            headers=HEADERS if headers is None else headers, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def do(self, **body) -> dict:
        code, data = self.post(body)
        assert code == 200, data
        return data

    def refused(self, **body) -> str:
        code, data = self.post(body)
        assert code == 400, data
        return data["error"]

    def exp(self, exp_id: str) -> dict:
        return self.get(f"/api/exp/{exp_id}")

    def row(self, exp_id: str) -> dict:
        return next(e for e in self.get("/api/state")["experiments"] if e["id"] == exp_id)

    def new_started(self, points, **more) -> str:
        exp_id = self.do(action="new", plugin="demo")["id"]
        self.do(action="set", exp=exp_id, name="点", kind="值", value=json.dumps(points), source="手填")
        for name, value in more.items():
            self.do(action="set", exp=exp_id, name=name, kind="值", value=json.dumps(value), source="手填")
        self.do(action="op", op="启动", exp=exp_id)
        return exp_id

    def run_to_end(self, exp_id: str, limit=10):
        for _ in range(limit):
            if self.exp(exp_id)["status"] != "运行中":
                return
            self.do(action="refresh", exp=exp_id)
        raise AssertionError("没有在预期的次数内结束")


@pytest.fixture
def home(tmp_path):
    shutil.copytree(REPO / "plugins" / "demo", tmp_path / "plugins" / "demo")
    return tmp_path


@pytest.fixture
def site(home):
    """网页操作台，不开值守：任务只在测试叫「看一眼」时往前走。"""
    s = Site(home, watch=False)
    yield s
    s.close()


@pytest.fixture
def live(home):
    """网页操作台，开着值守。"""
    s = Site(home, watch=True)
    yield s
    s.close()


def wait_for(check, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("等不到")


def tree(folder: Path) -> dict:
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


# ---- 网页操作台 ---------------------------------------------------------


def test_page_opens_and_shows_what_each_plugin_reports(site):
    """网页打得开；插件报的四样都在：名字版本类别、要哪几项设置、写了哪些挂点、产出什么。"""
    assert "操作台" in site.page()
    s = site.get("/api/state")
    assert s["experiments"] == [] and s["plugin_errors"] == [] and s["home"] == str(site.home)
    p = s["plugins"][0]
    assert (p["name"], p["version"], p["category"]) == ("demo", "0.1", "示范")
    assert [(x["name"], x["required"]) for x in p["settings"]] == [("点", True), ("出错的点", False)]
    assert p["hooks"] == ["启动", "报任务状态", "停止", "重试"]
    assert [x["name"] for x in p["outputs"]] == ["点清单"]
    assert s["watch"]["on"] is False


def test_new_fill_start_and_see_all_nine_items(site):
    """在网页上新建、填设置、启动、看一眼直到结束；九项都看得到，记的和命令行操作台一样。"""
    made = site.do(action="new", plugin="demo", note="网页上建的", tags=["试", " "])
    exp_id = made["id"]
    assert exp_id == "E0001" and site.exp(exp_id)["can"] == ["启动"]
    assert "点" in site.refused(action="op", op="启动", exp=exp_id)  # 必填的没填

    site.do(action="set", exp=exp_id, name="点", kind="值", value='["a", "b"]', source="手填", when="2026-11-12")
    v = site.exp(exp_id)
    assert v["frozen"] is False and [w["name"] for w in v["wanted"]] == ["点", "出错的点"]
    assert site.do(action="op", op="启动", exp=exp_id)["message"] == f"{exp_id} 已启动。"
    assert site.exp(exp_id)["can"] == ["暂停", "停止"] and site.exp(exp_id)["can_refresh"] is True
    site.run_to_end(exp_id)

    v = site.exp(exp_id)
    assert v["id"] == exp_id and v["status"] == "已结束"
    assert v["plugin"]["name"] == "demo" and len(v["plugin"]["files_sha256"]) == 64
    assert v["note"] == "网页上建的" and v["tags"] == ["试"]
    s = v["settings"]["点"]
    assert s["frozen"] and s["content"]["value"] == ["a", "b"] and len(s["content"]["sha256"]) == 64
    assert s["source"] == {"kind": "其他来源", "from": "手填", "when": "2026-11-12"}
    assert [o["op"] for o in v["operations"]] == ["新建", "启动"]
    assert [h["state"] for h in v["tasks"]["a"]["history"]] == ["排队", "运行", "完成"]
    assert v["outputs"][0]["name"] == "点清单" and v["problems"] == []
    assert v["provenance"]["machine"] and v["can"] == ["重试"]

    row = site.row(exp_id)
    assert row["status"] == "已结束" and row["counts"] == {"完成": 2} and row["outputs"] == ["点清单"]
    assert Desk(site.home).show(exp_id).startswith(f"实验 {exp_id}　状态：已结束")
    assert site.get("/api/check")["checked"] == [{"id": exp_id, "found": []}]


def test_the_four_kinds_of_setting_content(site, tmp_path):
    """设置的四种内容都能在网页上填：一个值、复制文件、只记位置、另一个实验的产出。"""
    first = site.new_started(["a", "b", "c"], 出错的点=["c"])
    site.run_to_end(first)

    points = tmp_path / "我的点.json"
    points.write_text('["p", "q"]', encoding="utf-8")
    by_copy = site.do(action="new", plugin="demo")["id"]
    site.do(action="set", exp=by_copy, name="点", kind="复制", path=str(points), source="自己写的")
    by_ref = site.do(action="new", plugin="demo")["id"]
    site.do(action="set", exp=by_ref, name="点", kind="位置", path=str(points), source="自己写的")
    by_output = site.do(action="new", plugin="demo")["id"]
    site.do(action="set", exp=by_output, name="点", kind="产出", from_exp=first, output="点清单")
    for exp_id in (by_copy, by_ref, by_output):
        site.do(action="op", op="启动", exp=exp_id)

    points.write_text('["改了"]', encoding="utf-8")
    c = site.exp(by_copy)["settings"]["点"]["content"]
    assert c["kind"] == "复制" and c["stored"] == "settings/点/我的点.json"
    stored = site.home / "experiments" / by_copy / c["stored"]
    assert json.loads(stored.read_text(encoding="utf-8")) == ["p", "q"]
    r = site.exp(by_ref)["settings"]["点"]["content"]
    assert r["kind"] == "位置" and r["path"] == str(points) and len(r["sha256"]) == 64
    o = site.exp(by_output)["settings"]["点"]
    assert o["source"] == {"kind": "实验产出", "experiment": first, "output": "点清单"}
    assert o["content"]["sha256"] == site.exp(first)["outputs"][0]["sha256"]
    assert set(site.exp(by_output)["tasks"]) == {"a", "b"}  # c 在上一个实验里失败了，不在产出里

    assert "完整的路径" in site.refused(action="set", exp=site.do(action="new", plugin="demo")["id"],
                                        name="点", kind="复制", path="相对的.json")


def test_pause_resume_stop_retry_notes_and_tags(site):
    """暂停、继续、停止、重试各记一条；不该做的时候被拒绝并说出原因；备注和标签随时能加。"""
    exp_id = site.new_started(["a", "b"])
    site.do(action="refresh", exp=exp_id)
    site.do(action="op", op="暂停", exp=exp_id)
    assert site.exp(exp_id)["status"] == "已暂停" and site.exp(exp_id)["can"] == ["继续", "停止"]
    assert "没有能看的实验" in site.do(action="refresh", exp=exp_id)["message"]
    assert site.exp(exp_id)["tasks"]["a"]["state"] == "运行"
    assert "不能暂停" in site.refused(action="op", op="暂停", exp=exp_id)
    assert "新建一个实验" in site.refused(action="set", exp=exp_id, name="点", kind="值", value="[1]")

    site.do(action="op", op="继续", exp=exp_id)
    site.do(action="op", op="停止", exp=exp_id)
    assert site.exp(exp_id)["status"] == "已停止" and site.exp(exp_id)["tasks"]["a"]["state"] == "停止"
    site.do(action="note", exp=exp_id, text="停了之后写的")
    site.do(action="tag", exp=exp_id, add=["甲", "乙"])
    site.do(action="tag", exp=exp_id, remove=["甲"])
    site.do(action="op", op="重试", exp=exp_id)
    site.run_to_end(exp_id)

    v = site.exp(exp_id)
    assert [o["op"] for o in v["operations"]] == ["新建", "启动", "暂停", "继续", "停止", "重试"]
    assert v["status"] == "已结束" and v["tasks"]["a"]["state"] == "完成"
    assert v["notes"][0]["text"] == "停了之后写的" and v["tags"] == ["乙"]
    assert "没有这个实验" in site.refused(action="op", op="启动", exp="E9999")
    assert "没有这种操作" in site.refused(action="op", op="删除", exp=exp_id)
    assert "不认识的动作" in site.refused(action="乱写")


def test_plugin_pulled_out_then_reread(site):
    """拔掉插件后重新读插件：旧实验照样能看，只是不能操作；别的不受影响。"""
    exp_id = site.new_started(["a"])
    shutil.rmtree(site.home / "plugins" / "demo")
    assert site.get("/api/state")["plugins"] != []  # 还没重新读
    assert "（无）" in site.do(action="reload")["message"]

    assert site.get("/api/state")["plugins"] == []
    v = site.exp(exp_id)
    assert v["plugin_installed"] is False and v["can"] == [] and v["can_refresh"] is False and v["wanted"] == []
    assert v["plugin"]["name"] == "demo" and v["settings"]["点"]["content"]["value"] == ["a"]
    assert "只能看" in site.refused(action="op", op="停止", exp=exp_id)
    assert "没装上" in site.refused(action="new", plugin="demo")
    site.do(action="note", exp=exp_id, text="插件拔了也能写备注")
    assert site.row(exp_id)["status"] == "运行中"


def test_a_plugin_that_fails_shows_as_a_warning_not_a_crash(site):
    """插件启动时出错：网页收到的是「已启动，但插件出了问题」，问题记进记录，服务照常。"""
    folder = site.home / "plugins" / "boom"
    folder.mkdir()
    folder.joinpath("plugin.py").write_text(
        "from stemlab.plugins import Plugin\n"
        "class Boom(Plugin):\n"
        "    name = 'boom'\n    version = '0'\n    category = '会出错的'\n    settings = []\n"
        "    def start(self, ctx):\n        raise RuntimeError('故意的')\n"
        "PLUGIN = Boom()\n", encoding="utf-8")
    folder.with_name("broken").mkdir()
    folder.with_name("broken").joinpath("plugin.py").write_text("这不是 Python (", encoding="utf-8")
    reread = site.do(action="reload")
    assert reread["warn"] is True and "装不上 1 个" in reread["message"]
    assert len(site.get("/api/state")["plugin_errors"]) == 1

    exp_id = site.do(action="new", plugin="boom")["id"]
    done = site.do(action="op", op="启动", exp=exp_id)
    assert done["warn"] is True and "插件出了问题" in done["message"]
    problem = site.exp(exp_id)["problems"][0]
    assert "故意的" in problem["error"] and "Traceback" in problem["raw"]
    assert site.row(exp_id)["problems"] == 1
    other = site.new_started(["a"])
    site.run_to_end(other)
    assert site.exp(other)["status"] == "已结束"


def test_check_finds_a_record_that_was_changed(site):
    """核对记录：完好的说完好，被改过的指出来。"""
    good = site.new_started(["a"])
    bad = site.do(action="new", plugin="demo", note="原来的说明")["id"]
    path = site.home / "experiments" / bad / "record.jsonl"
    path.write_bytes(path.read_bytes().replace("原来的说明".encode("utf-8"), "改过的说明".encode("utf-8")))
    checked = {c["id"]: c["found"] for c in site.get("/api/check")["checked"]}
    assert checked[good] == [] and any("接不上" in line for line in checked[bad])
    assert site.get(f"/api/check?exp={good}")["checked"] == [{"id": good, "found": []}]


# ---- 能改东西，所以要守住门 ---------------------------------------------


def test_only_this_machine_and_only_with_the_header(site):
    """只绑本机；改东西的请求不带专门的请求头、从别的网页来、用别的域名指过来，都不接，什么都没改。"""
    assert site.server.server_address[0] == "127.0.0.1"
    body = {"action": "new", "plugin": "demo"}
    assert site.post(body, headers={"Content-Type": "application/json"})[0] == 403
    assert site.post(body, headers={"Content-Type": "text/plain"})[0] == 403  # 普通表单发得出的那种请求
    assert site.post(body, headers={**HEADERS, "Origin": "http://evil.example"})[0] == 403
    assert site.post(body, headers={**HEADERS, "Origin": site.base})[0] == 200

    def with_host(method, path, host, headers=None, data=None):
        conn = http.client.HTTPConnection("127.0.0.1", site.port, timeout=10)
        conn.putrequest(method, path, skip_host=True)
        conn.putheader("Host", host)
        for k, v in (headers or {}).items():
            conn.putheader(k, v)
        if data is not None:
            conn.putheader("Content-Length", str(len(data)))
        conn.endheaders(data)
        code = conn.getresponse().status
        conn.close()
        return code

    data = json.dumps(body).encode("utf-8")
    assert with_host("GET", "/api/state", "evil.example") == 403
    assert with_host("POST", "/api/do", "evil.example", HEADERS, data) == 403
    assert with_host("GET", "/api/state", f"localhost:{site.port}") == 200
    assert with_host("PUT", "/api/do", f"127.0.0.1:{site.port}", HEADERS, data) == 501
    assert [e["id"] for e in site.get("/api/state")["experiments"]] == ["E0001"]  # 只有带对了的那一次建成了


def test_bad_requests_are_answered_and_the_service_stays_up(site):
    """读不出来的请求、没有的地址、没有的实验：各有回话，服务不倒。"""
    def raw(data: bytes) -> int:
        req = urllib.request.Request(site.base + "/api/do", data=data, headers=HEADERS, method="POST")
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as err:
            return err.code

    assert raw(b"{not json") == 400 and raw(b"[1, 2]") == 400
    for path, code in (("/no-such-page", 404), ("/api/exp/E9999", 400)):
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(site.base + path)
        assert err.value.code == code
    assert "少了一项" in site.refused(action="new")
    assert site.get("/api/state")["experiments"] == []


def test_web_console_does_everything_through_the_desk():
    """网页操作台不绕过操作台：它的代码不直接碰实验记录，也没有换绑定地址的开关；网页不向外面要东西。"""
    source = (REPO / "stemlab" / "console_web.py").read_text(encoding="utf-8")
    imports = " ".join(line for line in source.splitlines() if re.match(r"\s*(from|import)\s", line))
    assert "Experiment" not in imports and "Store" not in imports and "plugins" not in imports
    assert ".append(" not in source and "--host" not in source and "0.0.0.0" not in source
    page = (REPO / "stemlab" / "console.html").read_text(encoding="utf-8")
    assert "http://" not in page and "https://" not in page
    assert f'"{console_web.HEADER}"' in page


# ---- 整体：操作台、值守、仪表盘、地基连起来 ------------------------------


def test_whole_system_console_watch_and_dashboard_together(live):
    """在网页操作台新建并启动实验，值守让任务自己往前走，仪表盘跟着变。

    含：一个任务失败、用上一个实验的产出当设置、仪表盘全程只读、记录核对。
    """
    dash, _ = serve_dashboard(live.home, "127.0.0.1", 0, with_machines=False)
    threading.Thread(target=dash.serve_forever, daemon=True).start()
    board = f"http://127.0.0.1:{dash.server_address[1]}/api/state"

    def on_board() -> dict:
        return json.loads(urllib.request.urlopen(board).read().decode("utf-8"))

    try:
        assert on_board()["total"] == 0 and live.get("/api/state")["watch"]["on"] is True

        # 还没启动的实验：仪表盘归在「还没启动的」，值守不动它
        first = live.do(action="new", plugin="demo", note="第一个", tags=["整体测试"])["id"]
        live.do(action="set", exp=first, name="点", kind="值", value='["a", "b", "c"]', source="手填")
        live.do(action="set", exp=first, name="出错的点", kind="值", value='["c"]', source="手填")
        assert [e["id"] for e in on_board()["not_started"]] == [first]
        time.sleep(0.3)
        assert live.exp(first)["tasks"] == {}

        # 启动之后不叫「看一眼」，值守让它自己走到结束；一个任务失败，别的照常完成
        live.do(action="op", op="启动", exp=first)
        wait_for(lambda: live.exp(first)["status"] == "已结束")
        v = live.exp(first)
        assert {k: t["state"] for k, t in v["tasks"].items()} == {"a": "完成", "b": "完成", "c": "失败"}
        assert [p["task"] for p in v["problems"]] == ["c"]
        b = on_board()
        ended = next(e for e in b["recent"] if e["id"] == first)
        assert ended["counts"] == {"完成": 2, "失败": 1} and ended["tags"] == ["整体测试"]
        assert [(p["id"], p["task"]) for p in b["problems"]] == [(first, "c")]

        # 用上一个实验的产出当设置，另起一个实验；它和第一个之间只经过实验记录
        second = live.do(action="new", plugin="demo", note="接着第一个的产出")["id"]
        live.do(action="set", exp=second, name="点", kind="产出", from_exp=first, output="点清单")
        live.do(action="op", op="启动", exp=second)
        wait_for(lambda: live.exp(second)["status"] == "已结束")
        v2 = live.exp(second)
        assert v2["settings"]["点"]["source"] == {"kind": "实验产出", "experiment": first, "output": "点清单"}
        assert set(v2["tasks"]) == {"a", "b"} and v2["problems"] == []

        # 值守在跑、仪表盘在读：记录完好，仪表盘读多少遍都不改任何文件
        w = live.get("/api/state")["watch"]
        assert w["holding"] is True and w["last_error"] == "" and w["unreadable"] == {}
        assert all(c["found"] == [] for c in live.get("/api/check")["checked"])
        b = on_board()
        assert b["total"] == 2 and b["ended_total"] == 2 and b["running"] == []
        live.web.watch.stop()
        before = tree(live.home)
        for _ in range(3):
            on_board()
        assert tree(live.home) == before
    finally:
        dash.shutdown()
        dash.server_close()


def test_whole_system_pause_stop_retry_under_the_watch(live):
    """值守开着的时候暂停、停止、重试：暂停期间任务不走，重试之后值守接着把它带到结束。"""
    exp_id = live.do(action="new", plugin="demo")["id"]
    live.do(action="set", exp=exp_id, name="点", kind="值", value=json.dumps([f"p{i}" for i in range(6)]))
    live.do(action="op", op="启动", exp=exp_id)
    live.do(action="op", op="暂停", exp=exp_id)
    frozen = live.exp(exp_id)["tasks"]
    time.sleep(0.4)
    assert live.exp(exp_id)["tasks"] == frozen and live.exp(exp_id)["status"] == "已暂停"

    live.do(action="op", op="停止", exp=exp_id)
    states = {t["state"] for t in live.exp(exp_id)["tasks"].values()}
    assert live.exp(exp_id)["status"] == "已停止" and states <= {"停止", "完成"} and "停止" in states
    time.sleep(0.3)
    assert live.exp(exp_id)["status"] == "已停止"

    live.do(action="op", op="重试", exp=exp_id)
    wait_for(lambda: live.exp(exp_id)["status"] == "已结束")
    v = live.exp(exp_id)
    assert [o["op"] for o in v["operations"]] == ["新建", "启动", "暂停", "停止", "重试"]
    assert all(t["state"] == "完成" for t in v["tasks"].values())
    assert live.get(f"/api/check?exp={exp_id}")["checked"][0]["found"] == []


def test_whole_system_command_line_and_web_share_one_home(live):
    """命令行操作台建的实验，网页操作台看得到、值守带得动；反过来也一样。"""
    desk = Desk(live.home)
    by_cli = desk.new("demo", note="命令行建的")
    desk.set(by_cli, "点", value=["a"])
    desk.start(by_cli)
    wait_for(lambda: desk.store.open(by_cli).view()["status"] == "已结束")
    assert live.row(by_cli)["note"] == "命令行建的" and live.row(by_cli)["status"] == "已结束"

    by_web = live.new_started(["x"])
    wait_for(lambda: live.exp(by_web)["status"] == "已结束")
    assert "点清单" in Desk(live.home).show(by_web)
    assert by_cli != by_web and Desk(live.home).check().count("记录完好") == 2
