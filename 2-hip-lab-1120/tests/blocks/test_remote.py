"""远程执行和备份里不用真连远端就能试的部分。真连远端的在 tests/cross/。"""
from __future__ import annotations

import json
import subprocess
import tarfile
import time

import pytest

from stemlab.contract import Refused, layout, plugin_api
from stemlab.contract.machines import Machine
from stemlab.desk.core import backup, start
from stemlab.experiments import view
from stemlab.hooks import handle, remote
from tests import helpers

LINUX = Machine(name="linux", role="worker", host="linuxbox", ssh="user@10.0.0.2", port=2222,
                options=("-o", "BatchMode=yes"), bin="C:/OpenSSH", python="/opt/env/bin/python",
                job_root="/srv/jobs/", backup_root="/srv/backup")


class Done:
    def __init__(self, code=0, out=b"", err=b""):
        self.returncode, self.stdout, self.stderr = code, out, err


@pytest.fixture
def capture(monkeypatch):
    """给出一个函数：一叫它，就把真正起 ssh、scp 的那一处换掉，记下每条命令，照着预先排好的结果回答。

    要等实验启动好之后再叫：启动时问 git 的那几条命令得是真的。
    """
    def begin():
        seen, answers, naps = [], [], []

        def fake(command, **how):
            seen.append(command)
            return answers.pop(0) if answers else Done()

        monkeypatch.setattr(subprocess, "run", fake)
        monkeypatch.setattr(time, "sleep", naps.append)
        return seen, answers, naps

    return begin


@pytest.fixture
def commands(capture):
    return capture()


def given_for(made: str, machines=(LINUX,)):
    status = view.view(made)
    info = plugin_api.RoundInfo(1, (), status.rounds[0].provenance)
    given = handle.Handle(made, info, status.inputs, status.frozen)
    given.machines = tuple(machines)
    return given


# ---- ssh 和 scp 怎么调 ----

def test_ssh_and_scp_commands(commands):
    seen, answers, _ = commands
    answers.append(Done(out=b"hello\n"))
    assert remote.ssh(LINUX, "echo hello") == b"hello\n"
    remote.upload(LINUX, "C:/work/a.tar", "/srv/jobs/a.tar")
    remote.download(LINUX, "/srv/jobs/b.tar", "C:/work/b.tar")
    tool = seen[0][0].replace("\\", "/")
    assert tool == "C:/OpenSSH/ssh" and seen[0][1:] == ["-p", "2222", "-o", "BatchMode=yes", "user@10.0.0.2", "echo hello"]
    assert seen[1][0].replace("\\", "/") == "C:/OpenSSH/scp"
    assert seen[1][1:] == ["-q", "-P", "2222", "-o", "BatchMode=yes", "C:/work/a.tar", "user@10.0.0.2:/srv/jobs/a.tar"]
    assert seen[2][-2:] == ["user@10.0.0.2:/srv/jobs/b.tar", "C:/work/b.tar"]
    plain = Machine(name="x", role="worker", host="h", ssh="u@h", job_root="/j")
    remote.ssh(plain, "true")
    assert seen[3][:3] == ["ssh", "-p", "22"], "没写 bin 就用 PATH 上的"


def test_an_unreachable_machine_is_retried_with_backoff_then_given_up(commands):
    seen, answers, naps = commands
    answers += [Done(255, err=b"ssh: connect to host 10.0.0.2 port 2222: Connection timed out")] * 2 + [Done(out=b"ok")]
    assert remote.ssh(LINUX, "true") == b"ok" and naps == [1.0, 4.0] and len(seen) == 3, "连不上时退避重试"

    seen.clear(), naps.clear()
    answers += [Done(255, err=b"Connection refused")] * 4
    with pytest.raises(remote.Unreachable, match="连不上 linux") as caught:
        remote.ssh(LINUX, "true")
    assert naps == [1.0, 4.0, 15.0] and len(seen) == 4 and "Connection refused" in str(caught.value)
    assert isinstance(caught.value, Refused)


def test_a_command_that_fails_on_the_remote_is_not_retried(commands):
    seen, answers, naps = commands
    answers.append(Done(2, err=b"tar: outputs: Cannot open: No such file or directory"))
    with pytest.raises(Refused, match="退出码 2") as caught:
        remote.ssh(LINUX, "tar -cf x outputs")
    assert not isinstance(caught.value, remote.Unreachable) and naps == [] and len(seen) == 1
    assert "No such file" in str(caught.value)


def test_a_command_that_never_answers_counts_as_unreachable(monkeypatch):
    def hang(command, **how):
        raise subprocess.TimeoutExpired(command, how["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    with pytest.raises(remote.Unreachable, match="没有回应"):
        remote.ssh(LINUX, "sleep 999", timeout=1)


def test_worker_lookup():
    desk = Machine(name="win", role="desk", host="w")
    assert remote.worker("linux", (desk, LINUX)) is LINUX
    for name in ("win", "nothing"):
        with pytest.raises(Refused, match="没有叫"):
            remote.worker(name, (desk, LINUX))


# ---- 操作台这一边的四个动作 ----

def test_snapshot_holds_the_core_and_this_plugin_only(lab, data):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    given = given_for(made)
    with tarfile.open(remote.snapshot(given)) as tar:
        names = tar.getnames()
    assert "stemlab/contract/chain.py" in names and "stemlab/hooks/remote.py" in names
    assert "tests/__init__.py" in names and "tests/plugins/__init__.py" in names, "插件所在的包一路上的 __init__.py"
    assert "tests/plugins/demo/plugin.py" in names and "tests/plugins/demo/worker.py" in names
    assert not any(name.startswith("tests/plugins/bad") or "__pycache__" in name for name in names), "别的插件不带"
    assert not any(name.startswith(("tests/blocks", "data", ".git")) for name in names)


def test_snapshot_is_refused_when_the_plugin_changed_after_the_round_opened(own_lab, data):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    free = own_lab / "tests" / "plugins" / "demo" / "free.py"
    free.write_bytes(free.read_bytes() + b"# changed after the round opened\n")
    with pytest.raises(Refused, match="不是这一轮记下的那一份"):
        remote.snapshot(given_for(made))


def test_push_start_status_pull_and_stop_send_the_right_scripts(lab, data, capture):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    given = given_for(made)
    seen, answers, _ = capture()
    job = f"/srv/jobs/{made}/r1"
    assert remote.job_dir(given, LINUX) == job

    numbers = helpers.write_files(given.work_dir / "in", {"numbers.json": b"{}"})
    assert remote.push(given, "linux", {"numbers.json": numbers / "numbers.json", "folder": numbers}) == job
    scripts = [command[-1] for command in seen]
    assert scripts[0] == f"mkdir -p {job}"
    assert seen[1][-1] == f"user@10.0.0.2:{job}/snapshot.tar" and seen[2][-1] == f"user@10.0.0.2:{job}/inputs.tar"
    assert "tar -xf snapshot.tar -C code" in scripts[3] and "tar -xf inputs.tar -C inputs" in scripts[3]
    assert "mkdir -p code inputs outputs" in scripts[3] and scripts[3].startswith(f"cd {job} && rm -rf code inputs outputs")
    with pytest.raises(Refused, match="名字"):
        remote.push(given, "linux", {"bad name": numbers})

    seen.clear()
    remote.start(given, "linux", "tests.plugins.demo.worker", "3", "it's quoted")
    script = seen[0][-1]
    assert script.startswith(f"cd {job}/code && if ") and "setsid nohup /opt/env/bin/python -m tests.plugins.demo.worker" in script
    assert f"{job} 3 'it'\"'\"'s quoted'" in script, "参数是引起来的"
    assert f">> {job}/log.txt 2>&1 < /dev/null & echo $! > {job}/pid); fi" in script
    alive = f'p=$(cat {job}/pid 2>/dev/null) && grep -qa -- {job} "/proc/$p/cmdline" 2>/dev/null'
    assert f"if {alive}; then true; else (" in script, "这个作业的 worker 已经在跑，就不再起第二个"

    seen.clear()
    answers.append(Done(out=b"\n1000.5\n"))
    assert remote.status(given, "linux") is None, "worker 还没写过状态文件"
    answers.append(Done(out=b'{"stage":"adding","heartbeat":990.0,"result":null,"env":{"host":"linuxbox"}}\n\n1000.5\n'))
    found = remote.status(given, "linux")
    assert (found["stage"], found["result"], found["age"]) == ("adding", None, 10.5), "心跳过了多久按远端的钟算"
    assert f"cat {job}/status.json" in seen[0][-1] and "date -u +%s.%N" in seen[0][-1]

    seen.clear()
    remote.stop(given, "linux")
    script = seen[0][-1]
    assert script.startswith(f'if {alive}; then kill -TERM -- "-$p" 2>/dev/null;'), \
        "先认出 pid 文件里的进程确实是这个作业的 worker，再结束它那一组"
    assert script.index("kill -TERM") < script.index(f"{alive} || exit 0") < script.index('kill -KILL -- "-$p"') \
        < script.rindex(f"if {alive}; then echo") < script.rindex("exit 3"), "先让它自己收尾，等一阵还在才强杀，强杀之后再查一遍"
    assert script.isascii(), "发到远端的脚本只用 ASCII"

    seen.clear()
    answers.append(Done(3, err=b"pid 4242 still running after TERM and KILL"))
    with pytest.raises(Refused, match="没停住") as caught:
        remote.stop(given, "linux")
    assert "4242" in str(caught.value) and not isinstance(caught.value, remote.Unreachable), "停不住就报错，核心不记“停止”"


def test_commands_that_must_not_run_twice_are_tried_only_once(lab, data, capture):
    """解开上传的包、打包产物这两步，连接断的时候在远端可能还在做：不重试，免得两遍撞在一起。"""
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    given = given_for(made)
    seen, answers, naps = capture()
    answers += [Done(), Done(), Done(), Done(255, err=b"Connection reset")]          # 建文件夹、传两个包、解开时断了
    with pytest.raises(remote.Unreachable):
        remote.push(given, "linux", {})
    assert len(seen) == 4 and naps == [], "解开那一步只试了一次"
    assert "tar -xf snapshot.tar" in seen[3][-1]

    seen.clear()
    answers += [Done(255, err=b"Connection reset")]
    with pytest.raises(remote.Unreachable):
        remote.pull(given, "linux")
    assert len(seen) == 1 and naps == [] and "tar -cf outputs.tar" in seen[0][-1]

    seen.clear()
    answers += [Done(255, err=b"Connection timed out"), Done()]
    remote.start(given, "linux", "some.worker")
    assert len(seen) == 2 and naps == [1.0], "起 worker 可以重试：它已经在跑就不会再起一个"


def test_pull_only_takes_a_plain_name_for_where_to_put_things(lab, data, tmp_path, capture):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    given = given_for(made)
    precious = helpers.write_files(tmp_path / "precious-r1", {"keep.txt": b"must survive"})
    seen, _, _ = capture()
    for name in (str(tmp_path / "precious"), "../../somewhere", "a/b", "", "with space"):
        with pytest.raises(Refused, match="不能是路径"):
            remote.pull(given, "linux", name=name)
    assert seen == [] and (precious / "keep.txt").read_bytes() == b"must survive", "什么都没删，一条命令都没发"


def test_pull_unpacks_into_work_and_notes_the_remote_environment_once(lab, data, tmp_path, monkeypatch):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    given = given_for(made)
    produced = helpers.write_files(tmp_path / "outputs", {"sum.json": b'{"sum": 10}', "deep/more.bin": b"\x00\x01"})
    bundle = tmp_path / "outputs.tar"
    with tarfile.open(bundle, "w") as tar:
        tar.add(produced, arcname=".")
    env = {"host": "linuxbox", "python": "3.12.3", "libs": {"torch": "2.9"}, "cuda": "12.8", "driver": "580", "gpu": "RTX"}
    state = json.dumps({"stage": "done", "heartbeat": 100.0, "result": "finished", "env": env}).encode() + b"\n\n101.0\n"
    seen = []

    def fake(command, **how):
        seen.append(command)
        if "scp" in command[0]:                         # 取回：把准备好的包放到它要的地方
            (tmp_path / "copied").write_bytes(bundle.read_bytes())
            __import__("shutil").copy(bundle, command[-1])
        return Done(out=state if "status.json" in command[-1] else b"")

    monkeypatch.setattr(subprocess, "run", fake)
    pulled = remote.pull(given, "linux", name="trained")
    assert pulled == given.work_dir / "trained-r1" and (pulled / "sum.json").read_bytes() == b'{"sum": 10}'
    assert (pulled / "deep" / "more.bin").read_bytes() == b"\x00\x01"
    assert not (given.work_dir / "trained-r1.tar").exists(), "取回来的包解开之后就删掉"
    assert seen[0][-1].endswith("tar -cf outputs.tar -C outputs .") and seen[1][-2] == f"user@10.0.0.2:/srv/jobs/{made}/r1/outputs.tar"

    noted = [extra for extra in view.view(made).rounds[0].extra if extra["source"] == "remote"]
    assert len(noted) == 1 and noted[0]["info"] == env, "远端的环境由核心记进这一轮的来历"
    (pulled / "stale.txt").write_bytes(b"left from the first pull")
    remote.pull(given, "linux", name="trained")
    assert not (pulled / "stale.txt").exists(), "再取一次，上一次取回来的先清掉"
    assert len([e for e in view.view(made).rounds[0].extra if e["source"] == "remote"]) == 1, "来历只记一次"


def test_remote_actions_need_a_writable_handle_and_a_known_worker(lab, data, capture):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    seen, _, _ = capture()
    status = view.view(made)
    read_only = handle.ReadOnly(made, plugin_api.RoundInfo(1, (), status.rounds[0].provenance), status.inputs, status.frozen)
    read_only.machines = (LINUX,)
    for action in (lambda: remote.push(read_only, "linux", {}), lambda: remote.start(read_only, "linux", "m"),
                   lambda: remote.pull(read_only, "linux"), lambda: remote.stop(read_only, "linux")):
        with pytest.raises(Refused, match="只读"):
            action()
    with pytest.raises(Refused, match="没有叫 nowhere 的 worker"):
        remote.status(given_for(made), "nowhere")
    assert seen == [], "一条命令都没发出去"


# ---- worker 那一边 ----

def test_report_writes_the_status_file_whole(tmp_path):
    remote.report(tmp_path, "training", libs={"torch": "2.9"})
    first = json.loads((tmp_path / "status.json").read_bytes())
    assert first["stage"] == "training" and first["result"] is None and first["env"]["libs"] == {"torch": "2.9"}
    assert set(first["env"]) == {"host", "python", "libs", "cuda", "driver", "gpu"}, "远端的来历要的六项都在"
    time.sleep(0.05)
    remote.report(tmp_path, "done", libs={"torch": "2.9"}, result="finished", epochs=3)
    second = json.loads((tmp_path / "status.json").read_bytes())
    assert second["heartbeat"] > first["heartbeat"] and second["result"] == "finished" and second["epochs"] == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == ["status.json"], "先写到旁边再换过去，不留半截"


# ---- 备份：传什么、不传什么 ----

def test_backup_covers_the_books_and_nothing_else(lab, data, tmp_path):
    from stemlab.desk.core import actions

    actions.register("report", "a-report", source=helpers.make_folder(tmp_path / "rep"), note="n")
    made = helpers.experiment()
    start.start(made), start.poll(made)
    locked = helpers.make_folder(tmp_path / "with-lock", files={"uv.lock": b"version = 1\n", "notes/busy.lock": b"x"})
    actions.register("report", "has-a-lock-file", source=locked, note="登记的内容里有叫 .lock 的文件")
    helpers.write_files(layout.store_root() / ".incoming-abc", {"half.txt": b"x"})
    helpers.write_files(layout.store_root() / ".orphan-R0009-abcd1234", {"old.txt": b"x"})
    (data / "go").write_bytes(b"")
    (data / "backup.json").write_bytes(b"{}")
    found = backup.files()
    assert {"registry/register.jsonl", "experiments/issued.jsonl", f"experiments/{made}/record.jsonl",
            "registry/store/R0001/summary.json", "registry/store/R0001/manifest.json",
            f"experiments/{made}/rounds/1/outputs/report/summary.json"} <= set(found)
    assert "registry/store/R0004/uv.lock" in found and "registry/store/R0004/notes/busy.lock" in found, \
        "登记的内容里叫 .lock 的文件是账的一部分，照样备份"
    own = {"registry/register.lock", "experiments/issued.lock", f"experiments/{made}/record.lock",
           f"experiments/{made}/busy.lock"}
    assert own <= {rel for rel in helpers.hashing.list_tree(data)} and not own & set(found), "系统自己的几把锁不备份"
    assert not any("/work/" in rel or ".incoming-" in rel or ".orphan-" in rel for rel in found), "work/ 和登记到一半的不备份"
    assert "go" not in found and "backup.json" not in found
    assert found["registry/register.jsonl"] == layout.register_file().stat().st_size

    heads = backup.heads()
    assert heads["register"]["seq"] == 4 and heads["issued"]["seq"] == 1 and heads["links"] == {"seq": 0, "this": "0" * 64}
    assert heads["records"][made]["seq"] == len(helpers.entries_of(made))
    assert [rel for rel in found if backup.is_chain(rel)] == sorted(
        [f"experiments/{made}/record.jsonl", "experiments/issued.jsonl", "registry/register.jsonl"]), "哪些是链"
    assert not backup.is_chain("registry/store/R0001/record.jsonl") and backup.is_chain("registry/links.jsonl")


def backup_machine(repo) -> None:
    listed = {"format": 1, "machines": [
        {"name": "here", "role": "desk", "host": "here"},
        {"name": "linux", "role": "worker", "host": "linuxbox", "connect": {"ssh": "user@10.0.0.2"},
         "job_root": "/srv/jobs", "backup_root": "/srv/backup"}]}
    (repo / "machines.json").write_bytes(json.dumps(listed).encode("utf-8"))


def test_backup_never_overwrites_a_good_backup_with_damaged_books(own_lab, data, tmp_path, capture):
    """本机的账坏了，或者不是上次备份的延长：不备份，一条命令都不往远端发。"""
    backup_machine(own_lab)
    made = helpers.experiment()
    start.start(made), start.poll(made)
    for n in range(3):
        helpers.setting(f"later-{n}")
    layout.backup_file().write_bytes(helpers.hashing.canonical(
        {"format": 1, "time": "2026-01-01T00:00:00.000Z", "machine": "linux", "heads": backup.heads()}) + b"\n")
    recorded = layout.backup_file().read_bytes()
    seen, _, _ = capture()

    register = layout.register_file()
    whole = register.read_bytes()
    register.write_bytes(b"".join(line + b"\n" for line in whole.split(b"\n")[:-3]))     # 链丢了最后两条
    with pytest.raises(Refused, match="不是上次备份那一份的延长") as caught:
        backup.backup("linux")
    assert "远端的那一份没有动" in str(caught.value)
    register.write_bytes(whole.replace(b'"by":"tester"', b'"by":"nobody"', 1))            # 链中间被改过
    with pytest.raises(Refused, match="被改过"):
        backup.backup("linux")
    assert seen == [] and layout.backup_file().read_bytes() == recorded, "没有往远端发任何东西，backup.json 也没动"


def test_backup_refuses_when_the_remote_copy_and_the_local_books_disagree(own_lab, data, capture):
    """远端已经有的文件，只许链变长：别的文件大小变了、链变短了、链的开头对不上，都不覆盖。"""
    backup_machine(own_lab)
    made = helpers.experiment()
    start.start(made), start.poll(made)
    local = backup.files()
    product = f"experiments/{made}/rounds/1/outputs/report/summary.json"
    chain_file = "registry/register.jsonl"

    def listing(change: dict) -> bytes:
        sizes = {**local, **change}
        return "".join(f"{size} {rel}\n" for rel, size in sizes.items()).encode("utf-8")

    def attempt(change: dict, more=()) -> list:
        seen, answers, _ = capture()
        answers += [Done(out=listing(change)), *more]
        with pytest.raises(Refused) as caught:
            backup.backup("linux")
        return [str(caught.value), seen]

    message, seen = attempt({product: local[product] + 5})
    assert product in message and "没有覆盖远端" in message and len(seen) == 1, "产物的大小变了：只列了一下远端有什么，就停了"
    message, seen = attempt({chain_file: local[chain_file] + 100})
    assert chain_file in message and len(seen) == 1, "远端的链比本机的还长：本机的链丢过尾巴"
    shorter = local[chain_file] - 10
    message, seen = attempt({chain_file: shorter}, more=[Done(out=("0" * 64 + f"  {chain_file}\n").encode())])
    assert "不是本机这一份的开头" in message and len(seen) == 2 and "sha256sum" in seen[1][-1]
    assert not layout.backup_file().exists()


def test_a_backup_cut_short_says_what_the_other_side_said(tmp_path, monkeypatch):
    """对面先走了（比如盘满了）：说清楚是送的时候断的，并把对面留下的话带上，不只是一句管道断了。"""
    class Closed:
        def write(self, data):
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self):
            pass

        def close(self):
            pass

    class Gone:
        ended = []

        def __init__(self, command, stdin=None, stdout=None, stderr=None, **how):
            stderr.write("tar: data/x: Cannot write: No space left on device\n".encode("utf-8"))
            stderr.flush()
            self.stdin = Closed()

        def kill(self):
            self.ended.append("kill")

        def wait(self, timeout=None):
            self.ended.append("wait")
            return 2

    helpers.write_files(tmp_path, {"registry/register.jsonl": b"{}\n" * 2000})
    monkeypatch.setattr(subprocess, "Popen", Gone)
    with pytest.raises(remote.Unreachable) as caught:
        backup._send(LINUX, "tar -xf - -C /srv/backup/data", tmp_path, {"registry/register.jsonl": 6000})
    assert "送备份的时候断了" in str(caught.value) and "No space left on device" in str(caught.value)
    assert Gone.ended == ["kill", "wait"], "那一头的进程收掉了，不留着"


def test_backup_needs_a_machine_with_a_backup_root(own_lab, data, capture):
    with pytest.raises(Refused, match="没有叫 linux 的 worker"):
        backup.backup("linux")
    listed = {"format": 1, "machines": [
        {"name": "here", "role": "desk", "host": "here"},
        {"name": "linux", "role": "worker", "host": "linuxbox", "connect": {"ssh": "user@10.0.0.2"}, "job_root": "/srv/jobs"}]}
    (own_lab / "machines.json").write_bytes(json.dumps(listed).encode("utf-8"))
    seen, _, _ = capture()
    with pytest.raises(Refused, match="没有写 backup_root"):
        backup.backup("linux")
    assert seen == [] and not layout.backup_file().exists(), "一条命令都没发出去，也没有记下备份"


def test_every_backup_checks_on_the_other_side_the_contents_it_sent(lab, data, tmp_path):
    """远端核对：这次传了内容的那几样，每次备份都核内容的哈希，不只看大小；别的内容带 contents 时才核。
    这里照远端的做法在本机跑那段核对脚本：sent.json 放在它运行的地方，STEMLAB_DATA 指向这份账。"""
    import os
    import stat
    import sys

    from stemlab.registry import lookup

    made = helpers.experiment()
    start.start(made), start.poll(made)
    item = lookup.by_origin(made, 1)[0]
    product = f"experiments/{made}/rounds/1/outputs/report/summary.json"
    assert backup.sent_items([product, "registry/register.jsonl"]) == [item["id"]]
    assert backup.sent_items(["registry/register.jsonl", f"experiments/{made}/record.jsonl"]) == []

    target = data / product
    size = target.stat().st_size
    os.chmod(target, stat.S_IWRITE)
    target.write_bytes(b"x" * size)                     # 大小没变，内容变了：只看大小查不出
    where = tmp_path / "remote"
    where.mkdir()

    def checked(sent, *more) -> list:
        (where / backup.SENT).write_text(json.dumps(sent), encoding="utf-8")
        done = subprocess.run([sys.executable, "-c", backup._VERIFY, json.dumps(backup.heads()), *more], cwd=where,
                              env=dict(os.environ, PYTHONPATH=str(lab), PYTHONUTF8="1"), capture_output=True, timeout=120)
        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
        return json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])

    assert checked([]) == [], "这次没传它的内容：链都接得上，它不核"
    assert any(item["id"] in text for text in checked([item["id"]])), "这次传了它的内容：核哈希，查得出"
    assert any(item["id"] in text for text in checked([], "contents")), "带 contents：全都核"
