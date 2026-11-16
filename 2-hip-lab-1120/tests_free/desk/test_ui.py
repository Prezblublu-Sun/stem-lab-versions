"""操作台界面：一个实验的进展、网页的读和写、命令行的新命令。用测试插件（tests/plugins/demo）。"""
from __future__ import annotations

import json

from stemlab.desk.core import query, start
from stemlab.desk.ui import cli, progress, web
from tests import helpers


def running_experiment() -> str:
    made = helpers.experiment()
    start.start(made)
    start.poll(made)
    return made


def test_the_progress_of_an_experiment(lab, data):
    made = running_experiment()
    shown = progress.progress(made, now=None)
    assert (shown["id"], shown["type"], shown["frozen"], shown["plugin_missing"]) == (made, "demo.echo", True, False)
    assert shown["label"] and isinstance(shown["can"], dict) and set(shown["can"]) == {"fill", "start", "stop"}
    assert shown["can"]["fill"] is False, "输入存定了就不能再填"
    assert [row["name"] for row in shown["inputs"]] == ["setting", "extra"] and shown["inputs"][0]["items"][0]["kind"] == "setting"
    assert shown["rounds"][-1]["number"] == 1 and shown["rounds"][-1]["result_label"] and shown["rounds"][-1]["seconds"] >= 0
    for task in shown["tasks"]:
        assert {"name", "state", "stage", "machine", "round", "seconds_since", "outcome_label"} <= set(task)
        assert task["seconds_since"] is not None and task["seconds_since"] < 600
    assert shown["charts"] == query.charts(made)
    json.dumps(shown, ensure_ascii=False, default=str)                  # 整个能转成 JSON 交给网页
    said = progress.text(made)
    assert made in said and "demo.echo" in said and "第 1 轮" in said


def test_a_chart_is_fetched_through_the_core_and_its_errors_are_only_shown(lab, data, monkeypatch):
    made = running_experiment()
    name = query.charts(made)[0]["name"]
    good = progress.chart(made, name)
    assert good["name"] == name and good["form"] == "table" and "data" in good and "error" not in good
    assert "error" in progress.chart(made, "no_such_chart")

    def broken(experiment, chart):
        raise RuntimeError("the chart code is broken")

    before = len(helpers.entries_of(made))
    monkeypatch.setattr(query, "chart", broken)
    assert "the chart code is broken" in progress.chart(made, name)["error"]
    assert len(helpers.entries_of(made)) == before, "取图表出错只显示出来，不进记录"


def test_what_the_page_reads(lab, data, tmp_path):
    made = running_experiment()
    waiting = helpers.experiment()
    listed = web.read("/api/experiments", {})
    assert [one["id"] for one in listed] == [made, waiting] and listed[0]["type"] == "demo.echo"
    types = web.read("/api/types", {})
    assert "demo.echo" in [one["name"] for one in types["types"]] and types["kinds"]["bone_model"] == "骨模型"
    assert [row["name"] for row in next(one for one in types["types"] if one["name"] == "demo.echo")["inputs"]] == ["setting", "extra"]
    items = web.read("/api/items", {})
    assert len(items) >= 2 and web.read("/api/items", {"kind": ["kernel"]}) == []
    assert all(one["kind"] == "setting" for one in web.read("/api/items", {"kind": ["setting"]}))
    assert web.read(f"/api/experiment/{made}", {})["id"] == made
    name = query.charts(made)[0]["name"]
    assert "data" in web.read(f"/api/experiment/{made}/chart/{name}", {})
    shown = web.read(f"/api/item/{items[0]['id']}", {})
    assert shown["item"]["id"] == items[0]["id"] and "upstream" in shown and "downstream" in shown
    everything = web.read("/api/all", {})
    assert [one["progress"]["id"] for one in everything] == [made, waiting] and name in everything[0]["charts"]
    assert web.read("/api/nothing", {}) is None and web.read("/api/experiment", {}) is None
    json.dumps([listed, types, items, shown, everything], ensure_ascii=False, default=str)


def test_what_the_page_writes_goes_to_the_core(lab, data):
    made = helpers.experiment()
    status, said = web.do({"op": "note", "experiment": made, "text": "from the page"})
    assert (status, said) == (200, {"ok": True, "result": None}) and helpers.entries_of(made, "noted")[-1]["text"] == "from the page"
    status, said = web.do({"op": "start", "experiment": made})
    assert status == 200 and said == {"ok": True, "result": {"ran": True, "error": None}}
    status, said = web.do({"op": "fill", "experiment": made, "input": "setting", "items": []})
    assert status == 200 and said["ok"] is False and "fill" in said["refused"], "核心拒了的，原因照实交回去"
    assert web.do({"op": "start", "experiment": "E9999"})[1]["ok"] is False
    status, said = web.do({"op": "poll", "experiment": helpers.experiment()})
    assert status == 200 and said["ok"] and said["result"]["ran"] is None and "没有叫插件" in said["result"]["said"], \
        "对没在跑的实验点“看一遍”：照实说这一遍没叫插件，不出错"
    assert web.do({"op": "format_the_disk"})[0] == 400 and web.do(None)[0] == 400 and web.do({"op": "note"})[0] == 400
    status, said = web.do({"op": "new", "type": "demo.echo", "note": "made through the page"})
    assert status == 200 and said["ok"] and web.read(f"/api/experiment/{said['result']}", {})["note"] == "made through the page"
    assert set(web.OPS) == {"new", "clone", "fill", "note", "tag", "start", "stop", "poll"}, "写的请求只有这几样，都是转给核心"


def test_the_command_line_shows_progress_and_charts(lab, data, capsys):
    made = running_experiment()
    for command in ("progress", "进展"):
        assert cli.main([command, made]) == 0
        assert made in capsys.readouterr().out
    name = query.charts(made)[0]["name"]
    assert cli.main(["chart", made, name]) == 0 and '"data"' in capsys.readouterr().out
    assert cli.main(["图", made, "no_such_chart"]) == 0 and "出错" in capsys.readouterr().out


def test_open_opens_the_browser_once_the_port_is_listening(monkeypatch):
    """--open：端口在听了才叫浏览器，叫的就是这个端口；不给 --open 就不叫。操作台的网页和仪表盘都一样。"""
    import webbrowser
    from http.server import ThreadingHTTPServer

    from stemlab.board import machines
    from stemlab.board import web as board_web

    opened = []

    def stop_serving(self):
        raise KeyboardInterrupt                     # 相当于一开起来就按了 Ctrl+C

    class Quiet:
        def close(self):
            pass

    monkeypatch.setattr(webbrowser, "open", opened.append)
    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", stop_serving)
    monkeypatch.setattr(machines, "Monitor", Quiet)
    for page in (web, board_web):
        assert page.main(["--port", "0"]) == 0 and opened == [], "不给 --open 不开浏览器"
        assert page.main(["--port", "0", "--open"]) == 0
        url = opened.pop()
        assert url.startswith("http://127.0.0.1:") and url.endswith("/") and not url.endswith(":0/"), url
    assert cli.main(["web", "--port", "0", "--open"]) == 0 and len(opened) == 1, "命令行的 web 命令把 --open 传下去"


def test_a_second_start_on_a_busy_port_opens_the_page_that_is_already_there(monkeypatch, capsys):
    """端口上已经有服务在听：不起第二个，说一声；给了 --open 就直接打开现有的页面。"""
    import socket
    import webbrowser
    from http.server import ThreadingHTTPServer

    from stemlab.board import machines
    from stemlab.board import web as board_web

    opened = []

    def must_not_serve(self):
        raise AssertionError("端口上已经有服务了，不该再起一个")

    def must_not_monitor():
        raise AssertionError("端口上已经有服务了，不该去起读机器的进程")

    monkeypatch.setattr(webbrowser, "open", opened.append)
    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", must_not_serve)
    monkeypatch.setattr(machines, "Monitor", must_not_monitor)
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        for page in (web, board_web):
            assert page.listening("127.0.0.1", port) and not page.listening("127.0.0.1", 0)
            assert page.main(["--port", str(port)]) == 0 and opened == []
            assert "已经有服务开着" in capsys.readouterr().out
            assert page.main(["--port", str(port), "--open"]) == 0 and opened.pop() == f"http://127.0.0.1:{port}/"
    assert not web.listening("127.0.0.1", port), "那个端口关掉之后就不算开着了"
