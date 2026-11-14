"""跨机测试：哈希两边一致；同一个包两边结果一致；SSH 中途断开 worker 不受影响；备份推过去之后在 Linux 上核对能过。"""
from __future__ import annotations

import json
import shlex
import socket
import subprocess
import sys

import pytest

from stemlab.contract import Refused, hashing, layout
from stemlab.contract.formats import package, points
from stemlab.contract.machines import parse_machines
from stemlab.desk.core import actions, backup, check, start
from stemlab.experiments import view
from stemlab.hooks import remote
from stemlab.registry import lookup
from tests import helpers
from tests.contract.test_hashing import FILES, TREE, VALUE
from tests.contract.test_points import GOLDEN, POINT

pytestmark = pytest.mark.cross


@pytest.fixture
def linux(own_lab):
    """真的那台 worker，但作业和备份都放在它 /tmp 下一个这次测试自己的文件夹里，测完删掉。"""
    workers = [m for m in parse_machines(json.loads((helpers.REPO / "machines.json").read_bytes())) if m.role == "worker"]
    if not workers:
        pytest.skip("机器清单里没有 worker")
    real = workers[0]
    try:
        root = remote.ssh(real, "mktemp -d /tmp/stemlab-cross-XXXXXXXX", timeout=30).decode("utf-8").strip()
    except remote.Unreachable as error:
        pytest.skip(f"连不上 {real.name}：{error}")
    assert root.startswith("/tmp/stemlab-cross-")
    connect = {"ssh": real.ssh, "port": real.port, "options": list(real.options)}
    listed = {"format": 1, "machines": [
        {"name": "here", "role": "desk", "host": socket.gethostname(), "slots": 2},
        {"name": "linux", "role": "worker", "host": real.host, "connect": dict(connect, **({"bin": real.bin} if real.bin else {})),
         "python": real.python, "job_root": f"{root}/jobs", "backup_root": f"{root}/backup"}]}
    (own_lab / "machines.json").write_bytes(hashing.canonical(listed) + b"\n")
    try:
        yield remote.worker("linux")
    finally:
        remote.ssh(real, f"rm -rf {shlex.quote(root)}", timeout=300)


def send_folder(machine, local, where: str) -> None:
    sizes = {rel: (local / rel).stat().st_size for rel in hashing.list_tree(local)}
    backup._send(machine, f"mkdir -p {shlex.quote(where)} && tar -xf - -C {shlex.quote(where)}", local, sizes)


def remote_python(machine, script: str, *arguments: str) -> dict:
    """在远端用机器清单里写的那个解释器跑一段脚本（只用标准库和传过去的 stemlab/），返回它打印的 JSON。"""
    code = f"{machine.backup_root}/{backup.CODE}"
    command = (f"cd {shlex.quote(code)} && {shlex.quote(machine.python)} -c {shlex.quote(script)} "
               + " ".join(map(shlex.quote, arguments)))
    return json.loads(remote.ssh(machine, command, timeout=600).decode("utf-8").strip().splitlines()[-1])


# ---- 1 同一个文件夹在两台机器上 hash_tree 相同 ----

HASHES = r"""
import json, sys
from stemlab.contract import hashing
from stemlab.contract.formats import points
value = {"b": 1, "a": [1.0, 2.5, "中文"], "c": None, "d": {"z": True, "y": -0.0}}
point = {"name": "p1", "bone_id": "femur042", "design": {"length": 120, "offset": 37.5},
         "conditions": {"load": "walk", "bw": 700.0}, "reason": "x"}
print(json.dumps({"tree": hashing.hash_tree(sys.argv[1]), "list": hashing.list_tree(sys.argv[1]),
                  "json": hashing.hash_json(value), "point": points.point_hash(point),
                  "file": hashing.hash_file(sys.argv[1] + "/sub/c.bin"), "platform": sys.platform}))
"""


def test_hashes_are_the_same_on_both_machines(linux, tmp_path):
    local = helpers.write_files(tmp_path / "sample", FILES)
    backup._send_code(linux, linux.backup_root)
    send_folder(linux, local, f"{linux.backup_root}/sample")
    there = remote_python(linux, HASHES, f"{linux.backup_root}/sample")
    assert there["platform"] == "linux" and sys.platform == "win32", "这条测试比的是 Windows 和 Linux"
    assert there["tree"] == hashing.hash_tree(local) == TREE
    assert there["list"] == hashing.list_tree(local)
    assert there["json"] == hashing.hash_json(VALUE)
    assert there["point"] == points.point_hash(POINT) == GOLDEN
    assert there["file"] == hashing.hash_file(local / "sub" / "c.bin")


# ---- 2 同一个包两边的结果在容差内相同（预测器到阶段 5 才有，这里先用示范的包）----

def test_a_package_gives_the_same_result_on_both_machines(linux, tmp_path):
    local = helpers.make_package(tmp_path / "pack", scale=1 / 3)
    source = helpers.write_files(tmp_path / "in", {"x.json": b'{"x": 0.1}'})
    (tmp_path / "out").mkdir()
    here = subprocess.run([sys.executable, "code/main.py", str(source), str(tmp_path / "out")], cwd=local, check=True)
    assert here.returncode == 0
    mine = json.loads((tmp_path / "out" / "result.json").read_bytes())

    root = linux.backup_root
    send_folder(linux, local, f"{root}/pack")
    send_folder(linux, source, f"{root}/in")
    out = remote.ssh(linux, f"cd {root}/pack && mkdir -p {root}/out"
                            f" && {shlex.quote(linux.python)} code/main.py {root}/in {root}/out"
                            f" && cat {root}/out/result.json && echo && sha256sum code/main.py")
    lines = out.decode("utf-8").strip().splitlines()
    theirs = json.loads(lines[0])
    assert package.differences(mine, theirs, {"rel": 1e-12, "abs": 0}) == [], "两边的结果在容差内相同"
    assert lines[1].split()[0] == hashing.hash_file(local / "code" / "main.py"), "传过去的代码一个字节不差"


# ---- 3 远程执行走一遍；SSH 中途断开：worker 不受影响，status 能接上 ----

def poll_until_ended(made: str, seconds: float = 90.0) -> None:
    def step():
        start.poll(made)
        return view.view(made).rounds[-1].result is not None

    helpers.wait_for(step, seconds=seconds, step=0.5)


def test_a_round_on_the_worker_survives_a_dropped_connection(linux, data):
    made = helpers.experiment("demo.remote", value={"machine": "linux", "seconds": 6, "numbers": [1, 2, 3, 4]})
    assert start.start(made).ok
    status = view.view(made)
    job = f"{linux.job_root}/{made}/r1"
    assert status.tasks["job"].machine == "linux" and status.state == "running"

    # 开一条长连接，然后把它掐断：这就是“SSH 中途断开”
    dropped = subprocess.Popen([remote._tool(linux, "ssh"), "-p", str(linux.port), *linux.options, linux.ssh, "sleep 120"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    first = helpers.wait_for(lambda: remote.ssh(linux, f"cat {job}/status.json 2>/dev/null").strip(), seconds=30)
    helpers.kill_tree(dropped)
    assert json.loads(first)["stage"] == "adding"

    poll_until_ended(made)
    status = view.view(made)
    assert status.rounds[0].result == "done" and status.rounds[0].problems == []
    assert (status.tasks["job"].state, status.tasks["job"].outcome) == ("done", "finished")
    summary = json.loads((lookup.content(lookup.by_origin(made, 1)[0]["id"]) / "summary.json").read_bytes())
    assert summary == {"sum": 10, "host": linux.host}, "活是在 worker 上干的，结果取回来了"

    noted = [extra["info"] for extra in status.rounds[0].extra if extra["source"] == "remote"]
    assert len(noted) == 1 and set(noted[0]) == {"host", "python", "libs", "cuda", "driver", "gpu"}
    assert noted[0]["host"] == linux.host and noted[0]["libs"] == {"demo": "1.0"}, "远端的环境记进了这一轮的来历"

    listing = remote.ssh(linux, f"ls {job} && sha256sum {job}/code/tests/plugins/demo/plugin.py").decode("utf-8").split()
    assert {"code", "inputs", "outputs", "status.json", "log.txt", "pid"} <= set(listing)
    local_plugin = layout.repo_root() / "tests" / "plugins" / "demo" / "plugin.py"
    assert hashing.hash_file(local_plugin) in listing, "远端跑的就是这一轮上传的那一份代码"
    assert remote.ssh(linux, f"ls {linux.job_root}/{made}").decode().split() == ["r1"], "一轮一个作业文件夹"


def test_stop_ends_the_worker(linux, data):
    made = helpers.experiment("demo.remote", value={"machine": "linux", "seconds": 300})
    assert start.start(made).ok
    job = f"{linux.job_root}/{made}/r1"
    helpers.wait_for(lambda: remote.ssh(linux, f"cat {job}/status.json 2>/dev/null").strip(), seconds=30)
    alive = f"test -d /proc/$(cat {job}/pid) && echo alive || echo gone"
    assert remote.ssh(linux, alive).strip() == b"alive", "worker 在跑"
    assert start.stop(made).ok
    helpers.wait_for(lambda: remote.ssh(linux, alive).strip() == b"gone", seconds=30)
    stopped = json.loads(remote.ssh(linux, f"cat {job}/status.json"))
    assert stopped["result"] is None, "它是被结束的，不是自己做完的"
    status = view.view(made)
    assert status.rounds[0].result == "stopped" and status.tasks["job"].state == "stopped"
    assert start.start(made).ok and view.view(made).rounds[1].rerun == ["job"], "再启动就是新的一轮、新的作业文件夹"
    assert sorted(remote.ssh(linux, f"ls {linux.job_root}/{made}").decode().split()) == ["r1", "r2"]
    start.stop(made)


def test_starting_the_worker_twice_does_not_make_two(linux, data):
    """连接断了重试、或者重复叫，这个作业的 worker 都只有一个。"""
    from stemlab.contract import plugin_api
    from stemlab.hooks import handle

    made = helpers.experiment("demo.remote", value={"machine": "linux", "seconds": 300})
    assert start.start(made).ok
    job = f"{linux.job_root}/{made}/r1"
    status = view.view(made)
    given = handle.Handle(made, plugin_api.RoundInfo(1, (), status.rounds[0].provenance), status.inputs, status.frozen)
    count = f"pgrep -f '[d]emo.worker {job}' | wc -l"
    try:
        helpers.wait_for(lambda: remote.ssh(linux, count).strip() == b"1", seconds=30)
        first = remote.ssh(linux, f"cat {job}/pid").strip()
        remote.start(given, "linux", "tests.plugins.demo.worker", "300")
        remote.start(given, "linux", "tests.plugins.demo.worker", "300")
        assert remote.ssh(linux, count).strip() == b"1" and remote.ssh(linux, f"cat {job}/pid").strip() == first
    finally:
        assert start.stop(made).ok
    helpers.wait_for(lambda: remote.ssh(linux, count).strip() == b"0", seconds=30)
    remote.stop(given, "linux")                         # 已经不在了：再停一次什么都不做
    given.close()


def test_an_unknown_worker_is_a_problem_not_a_crash(linux, data):
    made = helpers.experiment("demo.remote", value={"machine": "nowhere"})
    result = start.start(made)
    assert not result.ok and "没有叫 nowhere 的 worker" in result.error
    assert view.view(made).rounds[0].result == "start_failed"


# ---- 4 备份推过去之后，在 Linux 上跑核对能过 ----

def test_backup_is_incremental_and_is_verified_on_linux(linux, data, tmp_path):
    actions.register("bone_source", "femur042-ct", source=helpers.write_files(tmp_path / "ct", {"Series 1/IM 0001.dcm": b"slice"}),
                     note="CT", bone_id="femur042", new_bone=True)
    first_run = helpers.experiment(value={"tasks": ["a", "b"]})
    start.start(first_run), start.poll(first_run)

    first = backup.backup("linux", contents=True)
    assert first["sent"] == first["files"] > 5 and first["machine"] == "linux"
    assert json.loads(layout.backup_file().read_bytes()) == first and check.check_backup() == []
    there = remote.ssh(linux, f"cd {linux.backup_root}/data && find . -type f | wc -l").strip()
    assert int(there) == first["files"], "账上的每个文件都到了"
    stored = remote.ssh(linux, f"sha256sum '{linux.backup_root}/data/registry/store/C0001/Series 1/IM 0001.dcm'")
    assert stored.split()[0].decode() == hashing.hash_bytes(b"slice")

    again = backup.backup("linux")
    assert again["sent"] == 0 and again["files"] == first["files"], "什么都没变，就什么都不用传"

    second_run = helpers.experiment(value={"tasks": ["c"]})
    start.start(second_run), start.poll(second_run)
    third = backup.backup("linux", contents=True)
    assert 0 < third["sent"] < third["files"], "只传新增的和变长了的"
    assert third["heads"]["records"][second_run]["seq"] > 0 and check.check_backup() == []

    # 远端那一份被动过：下次备份在远端核对时发现，backup.json 不更新
    record = f"{linux.backup_root}/data/experiments/{first_run}/record.jsonl"
    remote.ssh(linux, f"sed -i 's/\"round\":1/\"round\":7/' {record}")
    before = layout.backup_file().read_bytes()
    with pytest.raises(Refused, match="在远端核对没过"):
        backup.backup("linux")
    assert layout.backup_file().read_bytes() == before


def remote_sha(machine, rel: str) -> str:
    return remote.ssh(machine, f"sha256sum {shlex.quote(f'{machine.backup_root}/data/{rel}')}").split()[0].decode()


def test_a_damaged_local_copy_never_replaces_the_good_backup(linux, data, tmp_path):
    """备份只往远端添东西。本机的账坏了、丢了尾巴，或者不该变的文件变了：不备份，远端那一份一个字节不动。"""
    made = helpers.experiment(value={"tasks": ["a"]})
    start.start(made), start.poll(made)
    for n in range(3):
        helpers.setting(f"later-{n}")
    good = backup.backup("linux", contents=True)
    register, product = "registry/register.jsonl", f"experiments/{made}/rounds/1/outputs/report/summary.json"
    kept = {rel: remote_sha(linux, rel) for rel in (register, product)}
    recorded = layout.backup_file().read_bytes()

    path = layout.register_file()
    whole = path.read_bytes()
    path.write_bytes(b"".join(line + b"\n" for line in whole.split(b"\n")[:-3]))        # 链丢了最后两条
    with pytest.raises(Refused, match="不是上次备份那一份的延长"):
        backup.backup("linux")
    path.write_bytes(whole)

    local_product = layout.data_root() / product
    original = local_product.read_bytes()
    import os
    os.chmod(local_product, 0o600)
    local_product.write_bytes(original + b"edited after it was published\n")           # 只读的产物被改了
    with pytest.raises(Refused, match="没有覆盖远端"):
        backup.backup("linux")
    local_product.write_bytes(original)

    assert {rel: remote_sha(linux, rel) for rel in kept} == kept, "远端那一份一个字节没动"
    assert layout.backup_file().read_bytes() == recorded
    helpers.setting("after-the-scare")
    again = backup.backup("linux", contents=True)
    assert again["sent"] == 1 and again["heads"]["register"]["seq"] == good["heads"]["register"]["seq"] + 1, \
        "修好之后照常：只传变长了的那条链"
