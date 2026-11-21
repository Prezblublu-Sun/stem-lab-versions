"""界面和仪表盘只读：开着它们前后，data/ 下每个文件的哈希不变，也不多出、不少掉一个文件。

这条测试不认识页面上有什么、命令叫什么，所以界面和仪表盘怎么重写都行，只要留着这几样：
    python -m <模块> --port <端口>     开在本机的这个端口上
    <模块>.READ_PATHS                  它收的读的请求（GET）
    收写的请求的页面另有：<模块>.WRITE_PATHS（写的请求，POST）和 <模块>.WRITE_HEADER（写的请求必须带的请求头）；
        写的请求是一个 JSON：{"op": 做什么, ...}，转给核心做成了就答 {"ok": true, ...}。这里只试 op 是 note 的那一种
    python -m stemlab.desk <命令> ...   命令行的入口
    stemlab.desk.ui.cli.READ_COMMANDS   命令行里只看不写的命令；花括号里的词换成手上有的编号
"""
from __future__ import annotations

import importlib
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from stemlab.contract import hashing
from stemlab.desk.core import actions, start
from tests import helpers

# （有 READ_PATHS 的模块，用 python -m 开它时的名字，写的请求它收不收）
PAGES = [
    ("stemlab.board.web", "stemlab.board", False),
    ("stemlab.desk.ui.web", "stemlab.desk.ui.web", True),
]


def everything(root) -> dict:
    """root 下每个文件的哈希。锁文件也算：只读的一方连锁都不该碰。"""
    return {rel: hashing.hash_file(root / rel) for rel in hashing.list_tree(root)}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def ask(port: int, path: str, method: str = "GET", body: bytes = b"{}", headers: dict | None = None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {},
                                     data=None if method == "GET" else body)
    try:
        with urllib.request.urlopen(request, timeout=15) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return None, b""


@pytest.fixture
def busy_data(lab, data, tmp_path):
    """一份什么都有的 data/：做完的、出过问题还在跑的、还没启动的实验，和登记的东西。"""
    done = helpers.experiment()
    start.start(done), start.poll(done)
    troubled = helpers.experiment(value={"poll_raises": 1, "polls": 9})
    start.start(troubled), start.poll(troubled)
    helpers.experiment()
    actions.register("report", "a-report", source=helpers.make_folder(tmp_path / "rep"), note="n")
    actions.register("bone_source", "a-bone", source=helpers.make_folder(tmp_path / "bone", kind="bone_source", bone_id="femur042"),
                     note="n", bone_id="femur042", new_bone=True)
    return data


@pytest.fixture
def opened(busy_data):
    """给出一个函数：开一个页面，返回它的端口。测试结束时把开着的都关掉。"""
    running = []

    def open_page(run: str) -> int:
        port = free_port()
        server = subprocess.Popen([sys.executable, "-m", run, "--port", str(port)], cwd=helpers.REPO,
                                  env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        running.append(server)
        helpers.wait_for(lambda: ask(port, "/")[0] == 200 or server.poll() is not None, seconds=40, step=0.2)
        assert server.poll() is None, f"python -m {run} 没开起来"
        return port

    yield open_page
    for server in running:
        helpers.kill_tree(server)


@pytest.mark.parametrize("module,run,writes", PAGES, ids=[row[1] for row in PAGES])
def test_opening_it_changes_nothing_under_data(busy_data, opened, module, run, writes):
    paths = importlib.import_module(module).READ_PATHS
    assert "/" in paths
    before = everything(busy_data)
    port = opened(run)
    for _ in range(3):                                  # 开着看一会儿：它自己定时刷新的那几遍也算在内
        for path in paths:
            status, body = ask(port, path)
            assert status == 200 and body, f"{run} 的 {path} 读不出来（{status}）"
        time.sleep(0.6)
    assert everything(busy_data) == before, f"开着 {run} 看了一会儿，data/ 下有文件变了"


@pytest.mark.parametrize("module,run,writes", [row for row in PAGES if not row[2]], ids=lambda value: str(value))
def test_a_read_only_page_takes_no_write_requests(busy_data, opened, module, run, writes):
    before = everything(busy_data)
    port = opened(run)
    for path in importlib.import_module(module).READ_PATHS:
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            status, _ = ask(port, path, method)
            assert status in (405, 501), f"{run} 收下了 {method} {path}（{status}）"
    assert everything(busy_data) == before


@pytest.mark.parametrize("module,run,writes", [row for row in PAGES if row[2]], ids=lambda value: str(value))
def test_a_page_that_writes_wants_its_header(busy_data, opened, module, run, writes):
    """收写请求的页面：不带那个专门的请求头，什么都不做；读的地址不收写；带了头，写才转给核心。"""
    page = importlib.import_module(module)
    before = everything(busy_data)
    port = opened(run)
    note = b'{"op": "note", "experiment": "E0001", "text": "written through the page"}'
    for path in page.WRITE_PATHS:
        status, _ = ask(port, path, "POST", note)
        assert status == 403, f"{run} 没带请求头也收下了 POST {path}（{status}）"
        assert ask(port, path, "POST", note, {page.WRITE_HEADER: "0"})[0] == 403
    for path in page.READ_PATHS:
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            status, _ = ask(port, path, method, note, {page.WRITE_HEADER: "1"})
            assert status in (404, 405, 501), f"{run} 在读的地址上收下了 {method} {path}（{status}）"
    assert everything(busy_data) == before, "不带头的、打在读的地址上的，一个字都没写进去"
    status, body = ask(port, page.WRITE_PATHS[0], "POST", note, {page.WRITE_HEADER: "1"})
    assert status == 200 and b'"ok": true' in body
    assert helpers.entries_of("E0001", "noted")[-1]["text"] == "written through the page", "带了头，写的请求转给了核心"


def test_the_command_line_looks_without_writing(busy_data):
    """命令行里只看不写的那些命令：照 READ_COMMANDS 逐条跑，每条都看得成，前后 data/ 下一个字节都没变。"""
    from stemlab.desk.core import query
    from stemlab.desk.ui import cli
    from stemlab.experiments import reader
    from stemlab.registry import lookup

    experiment = reader.all_ids()[0]
    case = next(item for item in lookup.find() if item["id"].startswith("C"))
    charts = query.charts(experiment)
    known = {"experiment": experiment, "item": lookup.find()[0]["id"], "case": case["id"], "bone": case["bone_id"],
             "chart": charts[0]["name"] if charts else None}
    assert cli.READ_COMMANDS, "命令行要说出哪些命令只看不写"
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    before = everything(busy_data)
    ran = 0
    for template in cli.READ_COMMANDS:
        words = [word[1:-1] if word.startswith("{") and word.endswith("}") else None for word in template]
        assert all(word is None or word in known for word in words), f"{template} 里有这条测试不认识的词"
        if any(word is not None and known[word] is None for word in words):
            continue                                    # 这份 data/ 里没有这样东西可看（比如这个类型没有图）
        arguments = [part if word is None else known[word] for part, word in zip(template, words)]
        done = subprocess.run([sys.executable, "-m", "stemlab.desk", *arguments], cwd=helpers.REPO, env=env,
                              capture_output=True, timeout=300)
        said = (done.stdout + done.stderr).decode("utf-8", "replace")
        assert done.returncode == 0 and done.stdout.strip(), f"{arguments} 没看成（退出码 {done.returncode}）：\n{said[-800:]}"
        ran += 1
    assert ran >= len(cli.READ_COMMANDS) - 1, "差不多每条都真的跑了"
    assert everything(busy_data) == before, "跑了一遍只看的命令，data/ 下有文件变了"
