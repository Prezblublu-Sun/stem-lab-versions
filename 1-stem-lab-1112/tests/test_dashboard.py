"""仪表盘和机器信息的测试。用临时文件夹，不连任何真的远端机器。"""
import hashlib
import json
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from stemlab.console import Desk
from stemlab.dashboard import Board, serve
from stemlab.machines import BlockParser, Machine, cpu_percent, load_config, parse_gpu, remote_script

REPO = Path(__file__).resolve().parent.parent

FAKE_REMOTE = r'''
import sys, time
sys.stdin.read()
for cpu in ("cpu  100 0 100 800 0 0 0 0 0 0", "cpu  150 0 150 900 0 0 0 0 0 0"):
    print("B"); print("N 12"); print("C " + cpu); print("M 32000000 24000000")
    print("G 0, 40, 2048, 16384, Some GPU"); print("D /data 1048576000 524288000"); print("E")
    sys.stdout.flush(); time.sleep(0.3)
time.sleep(60)
'''


@pytest.fixture
def home(tmp_path):
    shutil.copytree(REPO / "plugins" / "demo", tmp_path / "plugins" / "demo")
    return tmp_path


def tree(folder: Path) -> dict:
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def wait_for(check, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("等不到")


def some_experiments(home):
    """一个在跑、一个结束且有失败、一个停了、一个没启动。"""
    desk = Desk(home)
    running = desk.new("demo", note="在跑的", tags=["甲"])
    desk.set(running, "点", value=["a", "b"])
    desk.start(running)
    desk.refresh(running)

    ended = desk.new("demo", note="结束的")
    desk.set(ended, "点", value=["a", "b"])
    desk.set(ended, "出错的点", value=["b"])
    desk.start(ended)
    desk.refresh(ended)
    desk.refresh(ended)

    stopped = desk.new("demo", note="停了的")
    desk.set(stopped, "点", value=["a"])
    desk.start(stopped)
    desk.stop(stopped)

    idle = desk.new("demo", note="没启动的")
    return desk, running, ended, stopped, idle


def test_board_groups_experiments_by_what_is_happening(home):
    """在跑的、刚结束的、出问题的、没启动的，各归各的。"""
    _, running, ended, stopped, idle = some_experiments(home)
    s = Board(home).state()
    assert [e["id"] for e in s["running"]] == [running]
    assert {e["id"] for e in s["recent"]} == {ended, stopped}
    assert [e["id"] for e in s["not_started"]] == [idle]
    assert s["total"] == 4 and s["ended_total"] == 2

    r = s["running"][0]
    assert r["counts"] == {"运行": 2} and r["category"] == "示范" and r["tags"] == ["甲"]
    assert {t["name"]: t["state"] for t in r["tasks"]} == {"a": "运行", "b": "运行"}
    assert all(t["machine"] and t["since"] for t in r["tasks"])

    e = next(x for x in s["recent"] if x["id"] == ended)
    assert e["counts"] == {"完成": 1, "失败": 1}
    assert [(p["id"], p["task"]) for p in s["problems"]] == [(ended, "b")]


def test_dashboard_changes_nothing_on_disk(home):
    """仪表盘只读：算现状、开网页、取数据之后，文件夹里一个字节都没变。"""
    some_experiments(home)
    before = tree(home)
    server, _ = serve(home, "127.0.0.1", 0, with_machines=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        page = urllib.request.urlopen(base + "/").read().decode("utf-8")
        data = json.loads(urllib.request.urlopen(base + "/api/state").read().decode("utf-8"))
        assert "仪表盘" in page and len(data["running"]) == 1
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + "/no-such-page")
        assert err.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(urllib.request.Request(base + "/api/state", data=b"{}", method="POST"))
        assert err.value.code == 501
    finally:
        server.shutdown()
        server.server_close()
    assert tree(home) == before


def test_dashboard_does_not_reach_plugins_or_the_console():
    """仪表盘的代码不引用挂点和操作台，所以它叫不到任何插件。"""
    source = (REPO / "stemlab" / "dashboard.py").read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if re.match(r"\s*(from|import)\s", line)]
    assert not any("plugins" in line or "console" in line for line in imports)
    page = (REPO / "stemlab" / "dashboard.html").read_text(encoding="utf-8")
    assert "http://" not in page and "https://" not in page  # 网页不向外面要任何东西


def test_board_only_rereads_records_that_changed(home):
    """低消耗：记录没变就不重读；哪个变了只重读哪个。"""
    desk, running, *_ = some_experiments(home)
    board = Board(home)
    board.state()
    first = board.reads
    assert first == 4
    board.state()
    assert board.reads == first
    desk.note(running, "加一条备注")
    board.state()
    assert board.reads == first + 1


def test_board_survives_a_half_written_record(home):
    """正好读到写了一半的一行：不崩，别的实验照常显示。"""
    _, running, ended, *_ = some_experiments(home)
    board = Board(home)
    board.state()
    path = home / "experiments" / running / "record.jsonl"
    with open(path, "ab") as f:
        f.write(b'{"seq": 99, "ti')
    s = board.state()
    assert [e["id"] for e in s["running"]] == [running]
    assert ended in {e["id"] for e in s["recent"]}


def test_cpu_percent_from_two_readings():
    a = [100, 0, 100, 800, 0, 0, 0, 0, 0, 0]
    b = [150, 0, 150, 900, 0, 0, 0, 0, 0, 0]
    assert cpu_percent(None, a) is None
    assert cpu_percent(a, b) == 50.0


def test_block_parser_builds_one_sample_per_block():
    p = BlockParser()
    lines = ["B", "N 12", "C cpu  100 0 100 800 0 0 0 0 0 0", "M 32000000 24000000",
             "G 0, 40, 2048, 16384, Some GPU", "D /data 1048576000 524288000", "E"]
    first = [p.feed(x) for x in lines][-1]
    assert first["cores"] == 12 and first["cpu"] is None
    assert first["mem"] == {"total_gb": 30.5, "used_gb": 7.6, "percent": 25.0}
    assert first["gpus"] == [{"index": "0", "util": 40.0, "mem_used_mb": 2048.0, "mem_total_mb": 16384.0, "name": "Some GPU"}]
    assert first["disks"] == [{"path": "/data", "total_gb": 1000.0, "used_gb": 500.0, "percent": 50.0}]
    lines[2] = "C cpu  150 0 150 900 0 0 0 0 0 0"
    assert [p.feed(x) for x in lines][-1]["cpu"] == 50.0
    assert p.feed("乱七八糟的一行") is None
    assert parse_gpu("不是 GPU 的行") is None


def test_remote_script_only_reads():
    """送到远端跑的脚本只读：没有往文件里写的重定向，也没有会改东西的命令。"""
    script = remote_script(["/", "/home/some one"])
    redirects = re.findall(r"\S*>\S*", script)
    assert set(redirects) <= {"2>/dev/null", "'NR>1{print"}  # 后一个是 awk 里的比较，不是重定向
    for word in ("rm ", "mv ", "cp ", "tee", "touch", "mkdir", "kill", "sudo", "chmod", "dd ", "systemctl"):
        assert word not in script
    assert "'/home/some one'" in script
    assert "\r" not in script


def test_machine_list_defaults_to_this_machine_only(tmp_path):
    conf = load_config(tmp_path)
    assert len(conf) == 1 and conf[0]["kind"] == "本机"


def test_machine_stream_gives_samples_and_its_process_ends_on_stop(tmp_path):
    """一条长连接读采样；停掉之后那个进程确实退出了。"""
    fake = tmp_path / "fake_remote.py"
    fake.write_text(FAKE_REMOTE, encoding="utf-8")
    m = Machine({"name": "假的远端", "kind": "ssh", "ssh": [sys.executable, str(fake)], "disks": ["/data"]}, interval=1)
    m.start()
    try:
        snap = wait_for(lambda: (s := m.snapshot())["ok"] and s.get("cpu") is not None and s)
        assert snap["name"] == "假的远端" and snap["cpu"] == 50.0 and snap["cores"] == 12
        assert snap["mem"]["percent"] == 25.0 and snap["gpus"][0]["util"] == 40.0
        assert snap["disks"][0]["percent"] == 50.0 and snap["time"]
        child = m.children[0]
    finally:
        m.stop()
    assert child.wait(timeout=10) is not None


def test_machine_that_cannot_connect_shows_the_reason(tmp_path):
    """连不上的机器：显示连不上和原因，不影响别的。"""
    m = Machine({"name": "连不上的", "kind": "ssh", "ssh": [sys.executable, "-c", "import sys; print('拒绝连接'); sys.exit(255)", "--"]}, interval=1)
    m.start()
    try:
        snap = wait_for(lambda: (s := m.snapshot())["error"] != "还没有采到" and s)
        assert snap["ok"] is False and "255" in snap["error"] and "拒绝连接" in snap["error"]
    finally:
        m.stop()


def test_this_machine_reports_cpu_and_memory():
    """本机：读得到 CPU 和内存；停掉之后没有留下子进程。"""
    m = Machine({"kind": "本机"}, interval=1)
    m.start()
    try:
        snap = wait_for(lambda: (s := m.snapshot())["ok"] and s)
        assert 0 <= snap["cpu"] <= 100 and snap["cores"] >= 1
        assert snap["mem"]["total_gb"] > 0 and 0 < snap["mem"]["percent"] < 100
        children = list(m.children)
    finally:
        m.stop()
    for child in children:
        assert child.wait(timeout=10) is not None
