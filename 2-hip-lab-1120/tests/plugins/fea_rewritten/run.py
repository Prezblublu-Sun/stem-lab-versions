"""plugins/fea/run.py 的另一种写法：接口不变，写法完全不同。

原来的写法把建模、求解、后处理都脱离出去、按槽排队；这一份每看一遍就原地把一个作业的下一步做完，不排队。
给“把自由的部分整个换一份写法”那条验收用：把它抄过去盖掉原来的 run.py，蓝图的前六条照过。
"""
import json
import pathlib
import shutil
import subprocess
import sys

from stemlab import hooks

REWRITTEN = True
ORDER = ["build", "solve", "post", "end"]


def _home(handle, job) -> pathlib.Path:
    return handle.work_dir / "rewritten" / ("%s-%d" % (job["task"], handle.round.number))


def _memo(home: pathlib.Path, **change) -> dict:
    path = home / "memo.json"
    memo = json.loads(path.read_text()) if path.exists() else {"next": "build", "lost": None}
    if change:
        memo.update(change)
        path.write_text(json.dumps(memo))
    return memo


def _said(home: pathlib.Path, part: str):
    path = home / part / "result.json"
    return json.loads(path.read_text()) if path.exists() else None


def _job_file(home: pathlib.Path, part: str, content: dict) -> pathlib.Path:
    where = home / ("for-" + part)
    where.mkdir(exist_ok=True)
    (where / "job.json").write_text(json.dumps(content))
    return where


def begin(handle, jobs):
    for job in jobs:
        home = _home(handle, job)
        shutil.rmtree(home, ignore_errors=True)
        home.mkdir(parents=True)
        _memo(home, next="build")


def advance(handle, jobs):
    desk = [machine.name for machine in handle.machines if machine.role == "desk"][0]
    kernel, setting = handle.input_info("kernel").id, handle.input("export")
    views = {}
    for job in jobs:
        home = _home(handle, job)
        memo = _memo(home)
        doing = memo["next"]
        point = job["point"]
        ask = {"bone_model": str(handle.input("bone")), "bone_id": point["bone_id"], "settings": setting, "job": str(home / "solve"),
               "point": {"name": point["name"], "design": point["design"], "conditions": point["conditions"]}}
        try:
            if doing == "build":
                built = hooks.run_kernel(kernel, _job_file(home, "build", dict(ask, mode="build")), home / "build")
                memo = _memo(home, next="solve" if built.get("status") == "built" else "end")
            elif doing == "solve":
                command = [sys.executable if part == "{python}" else part for part in _said(home, "build")["solve"]["command"]]
                (home / "solve").mkdir(exist_ok=True)
                subprocess.run(command, cwd=home / "solve", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                memo = _memo(home, next="post")
            elif doing == "post":
                hooks.run_kernel(kernel, _job_file(home, "post", dict(ask, mode="post")), home / "post")
                memo = _memo(home, next="end")
        except Exception as error:  # noqa: BLE001
            memo = _memo(home, next="end", lost="crashed" if _said(home, doing) is None else str(error))
        ended = doing == "end" or (memo["next"] == "end" and doing == "build")
        result = None
        if ended:
            result = {"build": _said(home, "build"), "post": _said(home, "post"), "lost": memo["lost"],
                      "dirs": {part: str(home / part) for part in ("build", "solve", "post") if (home / part).is_dir()}}
        views[job["task"]] = {"stage": doing if doing != "end" else "post", "machine": desk, "result": result}
    return views


def halt(handle, jobs):
    pass


def release(handle, job):
    shutil.rmtree(_home(handle, job), ignore_errors=True)
