"""仪表盘：实验的卡片、机器的数怎么读、告警的线。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import psutil
import pytest

from stemlab.board import alerts, experiments, machines, web
from stemlab.contract import layout
from stemlab.desk.core import start
from tests import helpers

REMOTE_BLOCK = """\
12
cpu  1000 0 500 8000 500 0 0 0 0 0
MemTotal:       32000000 kB
MemAvailable:   24000000 kB
@gpu
0, NVIDIA GeForce RTX 5060 Ti, 35, 4096, 16311
@apps
4242
4243
@df
Filesystem     1024-blocks      Used Available Capacity Mounted on
/dev/sda2        479000000 303000000 152000000      67% /
/dev/nvme0n1p3  1000000000 496000000 504000000      50% /mnt/nvme
""".splitlines()


def test_cards_sort_experiments_into_running_recent_and_waiting(lab, data):
    done = helpers.experiment()
    start.start(done), start.poll(done)
    troubled = helpers.experiment(value={"poll_raises": 1, "polls": 9, "tasks": ["a", "b"]})
    start.start(troubled), start.poll(troubled)
    fresh = helpers.experiment()

    listed = experiments.cards()
    assert [one["id"] for one in listed] == [done, troubled, fresh]
    assert [one["id"] for one in experiments.running(listed=listed)] == [troubled]
    assert [one["id"] for one in experiments.recent(listed=listed)] == [done]
    assert [one["id"] for one in experiments.waiting(listed=listed)] == [fresh]
    running = experiments.running()[0]
    assert running["round"] == 1 and running["counts"] == {"queued": 2} and not running["starting"]
    assert [task["name"] for task in running["tasks"]] == ["a", "b"]
    assert experiments.recent()[0]["result"] == "done" and experiments.recent()[0]["result_label"] == "做完"
    found = experiments.problems()
    assert len(found) == 1 and found[0]["experiment"] == troubled and "轮询抛错" in found[0]["error"]


def test_a_record_that_has_not_changed_is_not_read_again(lab, data, monkeypatch):
    made = helpers.experiment()
    experiments.card(made)
    calls = []
    monkeypatch.setattr(experiments.view, "view", lambda experiment: calls.append(experiment))
    assert experiments.card(made)["id"] == made and calls == [], "记录文件没变，用的是上次算好的"


def test_a_broken_record_shows_up_as_broken_and_does_not_hide_the_others(lab, data):
    good, bad = helpers.experiment(), helpers.experiment()
    layout.record_file(bad).write_bytes(b"{not json}\n")
    listed = experiments.cards()
    assert [one["id"] for one in experiments.broken(listed=listed)] == [bad]
    assert [one["id"] for one in experiments.waiting(listed=listed)] == [good]


def test_remote_numbers_are_read_from_one_printed_block():
    first = machines.parse_remote(REMOTE_BLOCK)
    assert first["cores"] == 12 and first["cpu"] is None, "第一组还算不出 CPU 占用：要和上一组比"
    assert first["memory"] == {"total_gb": 30.5, "used_gb": 7.6, "percent": 25.0}
    assert first["gpus"] == [{"index": 0, "name": "NVIDIA GeForce RTX 5060 Ti", "percent": 35.0,
                              "memory_used_mb": 4096.0, "memory_total_mb": 16311.0}]
    assert first["gpu_processes"] == 2
    assert [disk["path"] for disk in first["disks"]] == ["/", "/mnt/nvme"] and first["disks"][0]["free_gb"] == 145.0
    later = [line.replace("cpu  1000 0 500 8000 500", "cpu  1600 0 600 8700 600") for line in REMOTE_BLOCK]
    assert machines.parse_remote(later, first)["cpu"] == 46.7, "两组之间：总共走了 1500，其中 800 是闲着的"


CHATTER = "import time\nwhile True:\n    print('tick', flush=True)\n    time.sleep(0.1)\n"
BASE_PYTHON = getattr(sys, "_base_executable", sys.executable)      # 虚拟环境里的 python.exe 是个转发器，这里要真的那一个
HOLDER = """
import sys, time
from stemlab.board import machines
feed = machines.Feed([sys._base_executable, "-c", sys.argv[1]], lambda block, before: {"ok": True})
while not feed.latest:
    time.sleep(0.05)
print(feed._process.pid, flush=True)
time.sleep(600)
"""


def children() -> set[int]:
    return {child.pid for child in psutil.Process().children(recursive=True)
            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE}


def test_a_feed_reads_what_its_process_prints_and_ends_it_when_closed():
    before = children()
    feed = machines.Feed([BASE_PYTHON, "-c", CHATTER], lambda block, old: {"seen": (old or {"seen": 0})["seen"] + 1})
    helpers.wait_for(lambda: feed.latest and feed.latest["seen"] >= 3)
    assert feed.age() < 5 and feed.error is None and children() - before
    feed.close()
    assert children() == before, "关掉之后，它起的进程也没了"


def test_closing_a_feed_right_away_leaves_no_process_behind():
    before = children()
    for _ in range(5):
        machines.Feed([BASE_PYTHON, "-c", CHATTER], lambda block, old: {}).close()     # 赶在进程起来之前就关
    assert children() == before


def test_a_feed_whose_process_cannot_start_says_so_and_keeps_trying():
    feed = machines.Feed(["no-such-program-on-this-machine"], lambda block, old: {})
    try:
        helpers.wait_for(lambda: feed.error)
        assert "起不来" in feed.error and feed.latest is None and feed.age() is None
    finally:
        feed.close()


@pytest.mark.skipif(os.name != "nt", reason="别的系统上子进程往断了的管道里一写就自己退出")
def test_reading_processes_die_with_the_board_even_when_it_is_killed_hard():
    """仪表盘被强行结束：它起的读数进程（ssh 的长连接也是这样起的）由系统跟着结束，不留在后面。"""
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, CHATTER], cwd=helpers.REPO, stdout=subprocess.PIPE,
                              env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"))
    reader = None
    try:
        reader = int(holder.stdout.readline())
        assert psutil.pid_exists(reader)
        for pid in helpers.family(holder) - {reader}:           # 只结束仪表盘那一头，不碰读数进程
            try:
                psutil.Process(pid).kill()
            except psutil.NoSuchProcess:
                pass
        helpers.wait_for(lambda: not psutil.pid_exists(reader), seconds=15)
    finally:
        helpers.kill_tree(holder)
        if reader and psutil.pid_exists(reader):
            psutil.Process(reader).kill()


def test_only_read_commands_go_to_the_remote():
    script = machines.remote_script(5, ["/", "/mnt/nvme"])
    for command in machines.REMOTE_READS[:-1]:
        assert command in script
    assert "df -Pk / /mnt/nvme" in script and "sleep 5" in script
    words = script.replace(";", " ").split()
    assert not {"rm", "mv", "cp", "tee", "kill", "sudo", "chmod", "touch", "mkdir"} & set(words)
    assert ">" not in script.replace("2>/dev/null", ""), "除了丢掉报错，不往任何地方重定向"


def test_the_remote_is_not_contacted_until_the_config_says_so(lab, data):
    assert machines.DEFAULTS["remote"] is False
    monitor = machines.Monitor()
    try:
        assert monitor.feeds == {}
        rows = monitor.read()
        assert [row["here"] for row in rows] == [True] and rows[0]["memory"]["total_gb"] > 0 and rows[0]["disks"]
    finally:
        monitor.close()


def test_config_is_merged_over_the_defaults_and_a_bad_file_is_said_out_loud(own_lab, data):
    (own_lab / machines.CONFIG).write_bytes(json.dumps({"interval": 2, "alerts": {"disk_free_gb": 500}}).encode())
    config, problem = machines.read_config()
    assert problem is None and config["interval"] == 2 and config["remote"] is False
    assert config["alerts"]["disk_free_gb"] == 500 and config["alerts"]["backup_days"] == 8
    (own_lab / machines.CONFIG).write_bytes(b"{half")
    config, problem = machines.read_config()
    assert config == machines.DEFAULTS and "读不出来" in problem

    odd = {"alerts": {"disk_free_gb": "20", "memory_percent": 90, "backup_days": True, "nothing": 1}}
    (own_lab / machines.CONFIG).write_bytes(json.dumps(odd).encode())
    config, problem = machines.read_config()
    assert config["alerts"] == dict(machines.DEFAULTS["alerts"], memory_percent=90), "不是数的线用默认的，写对了的照用"
    assert all(name in problem for name in ("alerts.disk_free_gb", "alerts.backup_days", "alerts.nothing"))
    alerts.alerts(config, [{"name": "here", "here": True, "disks": [{"path": "/", "free_gb": 1.0}]}], [])  # 线都是数：比得了
    (own_lab / machines.CONFIG).write_bytes(json.dumps({"alerts": [20]}).encode())
    config, problem = machines.read_config()
    assert config["alerts"] == machines.DEFAULTS["alerts"] and "alerts" in problem


def test_a_reading_that_cannot_be_understood_does_not_stop_the_feed():
    """读数的线程碰到一组没想到的数：记下原因，接着读，不就此停下。"""
    def parse(block, before):
        if block == ["odd"]:
            raise TypeError("一组怪数")
        return {"line": block[0]}

    feed = machines.Feed([sys.executable, "-c", "import time; print('good', flush=True); time.sleep(0.5); "
                          "print('odd', flush=True); time.sleep(0.5); print('later', flush=True); time.sleep(30)"], parse)
    try:
        helpers.wait_for(lambda: feed.error and "TypeError" in feed.error, seconds=30)
        helpers.wait_for(lambda: feed.latest == {"line": "later"}, seconds=30)
        assert feed.error is None and feed._thread.is_alive(), "怪数之后的那一组照样读进来"
    finally:
        feed.close()


def test_the_page_still_comes_when_the_machine_numbers_fail(lab, data):
    """读机器的数出了岔子：页面照样出，告警里说出原因。"""
    class Broken:
        config, config_problem, machines_problem = json.loads(json.dumps(machines.DEFAULTS)), None, None

        def read(self):
            raise TypeError("读数坏了")

    state = web.state(Broken())
    assert state["machines"] == [] and any("读数坏了" in one["text"] for one in state["alerts"])


def test_the_board_takes_the_port_before_it_starts_reading(monkeypatch):
    """端口占不到就不起读数的进程和远端的连接：先占端口，再起 Monitor。"""
    made = []
    monkeypatch.setattr(web, "listening", lambda host, port: False)
    monkeypatch.setattr(machines, "Monitor", lambda: made.append("monitor"))

    def taken(address, handler):
        raise OSError("端口被占了")

    monkeypatch.setattr(web, "ThreadingHTTPServer", taken)
    with pytest.raises(OSError):
        web.main(["--port", "8791"])
    assert made == []


def test_alert_lines(lab, data):
    config = json.loads(json.dumps(machines.DEFAULTS))
    row = {"name": "linux", "here": False, "watched": True, "age": 300.0, "error": "ssh: timed out",
           "disks": [{"path": "/", "free_gb": 12.0}], "memory": {"percent": 97.0}}
    found = alerts.alerts(config, [row], [], now=time.time())
    assert {"unreachable", "disk", "memory", "backup"} == {one["what"] for one in found}
    assert any("ssh: timed out" in one["text"] for one in found)
    calm = dict(row, age=2.0, error=None, disks=[{"path": "/", "free_gb": 200.0}], memory={"percent": 40.0})
    assert [one["what"] for one in alerts.alerts(config, [calm], [], now=time.time())] == ["backup"], "还没备份过只是提一句"
    assert alerts.alerts(config, [dict(calm, watched=False, age=None)], [])[0]["what"] == "backup", "没开远端读数不算连不上"


def test_running_without_a_watch_and_an_old_backup_are_alerts(lab, data):
    config = json.loads(json.dumps(machines.DEFAULTS))
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    layout.backup_file().write_bytes(json.dumps({"time": "2026-01-01T00:00:00.000Z"}).encode())
    found = {one["what"]: one for one in alerts.alerts(config, [], experiments.cards())}
    assert "没有值守开着" in found["watch"]["text"] and found["backup"]["level"] == "warn"
    assert alerts.seconds("2026-01-01T00:00:00.000Z") == 1767225600.0 and alerts.seconds("yesterday") is None


def test_state_has_everything_the_page_draws(lab, data):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made), start.poll(made)
    monitor = machines.Monitor()
    try:
        state = web.state(monitor)
    finally:
        monitor.close()
    assert set(state) == {"time", "interval", "alerts", "machines", "running", "recent", "problems", "waiting"}
    assert [one["id"] for one in state["running"]] == [made]
    assert state["machines"][0]["running_tasks"] == 1, "示范插件把任务报在 here 这台上"
    json.dumps(state)
