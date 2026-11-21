"""坏插件运行时犯的事。一个类型犯一样。"""
import json
import os

from stemlab.hooks import Input, Kind, Outcome, Output

SETTING = (Input("setting", ("setting",)),)
OUTCOMES = (Outcome("finished", "ok"),)


def _dump(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _folder(handle, name: str, manifest: dict, files: dict):
    folder = handle.work_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        (folder / rel).write_bytes(content)
    (folder / "manifest.json").write_bytes(_dump(manifest))
    return folder


def passes(handle):
    return None


def queue_one(handle):
    handle.task("only", "queued")


# ---- 检查里往记录写 ----

def check_writes(handle):
    handle.task("sneaky", "queued")             # 被拒：检查是只读的。这个错没接住，检查就算出错


def check_writes_quietly(handle):
    for write in (lambda: handle.task("sneaky", "queued"), lambda: handle.problem("假的问题"),
                  lambda: handle.provenance(solver="x"), handle.finish, lambda: handle.fail("x"),
                  lambda: handle.output("report", handle.work_dir)):
        try:
            write()
        except Exception:  # noqa: BLE001  把被拒吞掉，装作没事
            pass
    return None


# ---- 交一样产物表里没有的产物，或者种类不符 ----

def poll_wrong_output(handle):
    report = {"format": 1, "kind": "report", "files": ["a.txt"]}
    handle.output("nothing", _folder(handle, "undeclared", report, {"a.txt": b"x"}))
    handle.output("report", _folder(handle, "wrong-kind", dict(report, kind="edits"), {"a.txt": b"x"}))
    handle.output("report", _folder(handle, "no-such-file", report, {}))
    handle.output("report", handle.work_dir / "does-not-exist")
    handle.output("report", handle.work_dir.parent)                 # 不在 work/ 里的文件夹
    handle.task("only", "done", outcome="finished")
    handle.finish()


# ---- 交一批条件没写全的点 ----

def poll_incomplete_points(handle):
    rows = [{"name": "p1", "bone_id": "femur042", "design": {"length": 120}, "conditions": {"load": "walk", "bw": 700},
             "reason": "坏插件选的", "hash": "0" * 64},
            {"name": "p2", "bone_id": "femur042", "design": {"length": 121}, "conditions": {"load": "walk"},
             "reason": "坏插件选的", "hash": "0" * 64}]
    manifest = {"format": 1, "kind": "points", "files": ["points.jsonl"], "count": 2,
                "design_keys": ["length"], "condition_keys": ["bw", "load"]}
    handle.output("points", _folder(handle, "points", manifest, {"points.jsonl": b"".join(map(_dump, rows))}))
    handle.task("only", "done", outcome="finished")
    handle.finish()


# ---- 动作里抛错 ----

def poll_raises(handle):
    raise RuntimeError("坏插件：轮询里抛错")


def poll_exits(handle):
    raise SystemExit("坏插件：想把值守带走")


# ---- 启动到一半进程退出 ----

def start_exits(handle):
    handle.task("only", "queued")
    os._exit(3)


def _kind(name: str, **parts) -> Kind:
    defaults = dict(inputs=SETTING, outputs=(Output("report", "report"),), outcomes=OUTCOMES,
                    check=passes, start=queue_one, poll=poll_raises)
    return Kind(name=name, **{**defaults, **parts})


KINDS = [
    _kind("bad.check_writes", check=check_writes),
    _kind("bad.check_writes_quietly", check=check_writes_quietly, poll=poll_wrong_output),
    _kind("bad.wrong_output", poll=poll_wrong_output),
    _kind("bad.incomplete_points", outputs=(Output("points", "points"),), poll=poll_incomplete_points),
    _kind("bad.raises"),
    _kind("bad.exits_in_poll", poll=poll_exits),
    _kind("bad.exits", start=start_exits),
]
