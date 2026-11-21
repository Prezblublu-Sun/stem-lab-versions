"""插件：把归档里已有的 FE 作业导出成数据。

吃一批作业号和归档所在的文件夹，每个作业一个任务。
产出标签、界面场、整体场三样，加一份说明。只读归档，不重算 FE，不连别的机器。

导出本身在一个后台进程里做（worker.py）。这个文件只做三件事：
把设置整理成一份计划、起停那个后台进程、把它的进度报进实验记录。
某个作业的归档读不了，记成问题，别的作业照常做。
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from stemlab.plugins import Output, Plugin, Setting

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"stemlab_plugin_fea_archive_export_{name}", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = _load("fae_columns")  # 只取版本号和三样量的名字；不带 numpy，操作台不用装它

JOB_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")
MAX_SPAWN = 3  # 后台进程中途退出时，最多一共起几次
STOP_WAIT = 30.0  # 叫停之后等后台进程自己退出的秒数


class SettingError(Exception):
    """设置用不了。消息是给人看的。"""


# ---------------------------------------------------------------- 进程

def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # Windows 上不能用 os.kill(pid, 0) 探活，那会把进程杀掉
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def pid_kill(pid: int) -> None:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
        if handle:
            ctypes.windll.kernel32.TerminateProcess(handle, 1)
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        import signal

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def spawn_worker(state_dir: Path) -> int:
    """起后台进程。不开窗口；操作台关掉它也接着做。返回进程号。"""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, str(HERE / "worker.py"), str(state_dir)]
    with open(state_dir / "worker.log", "ab") as log:
        common = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env, cwd=str(HERE), close_fds=True)
        if os.name == "nt":
            no_window, new_group, breakaway = 0x08000000, 0x00000200, 0x01000000
            try:
                proc = subprocess.Popen(cmd, creationflags=no_window | new_group | breakaway, **common)
            except OSError:  # 这个进程所在的作业对象不让脱离：那就不脱离
                proc = subprocess.Popen(cmd, creationflags=no_window | new_group, **common)
        else:
            proc = subprocess.Popen(cmd, start_new_session=True, **common)
    (state_dir / "worker.json").write_text(json.dumps({"pid": proc.pid, "started": time.time()}), encoding="utf-8")
    return proc.pid


def worker_pid(state_dir: Path) -> int:
    try:
        return int(json.loads((state_dir / "worker.json").read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError):
        return 0


def log_tail(state_dir: Path, size: int = 3000) -> str:
    out = []
    for name in ("worker_crash.txt", "worker.log"):
        try:
            out.append(f"--- {name}\n" + (state_dir / name).read_text(encoding="utf-8", errors="replace")[-size:])
        except OSError:
            pass
    return "\n".join(out)


# ---------------------------------------------------------------- 设置 → 计划

def read_jobs(value, archive: Path) -> list[str]:
    """「作业」这项设置的几种写法，都整理成作业号的列表。"""
    if isinstance(value, Path):
        text = value.read_text(encoding="utf-8-sig")
        try:
            value = json.loads(text)
        except ValueError:
            value = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if isinstance(value, str):
        if value.strip() == "全部":
            names = {p.name[: -len(".tar.xz")] for p in archive.glob("*.tar.xz")}
            names |= {p.name[: -len(".manifest.json")] for p in archive.glob("*.manifest.json")}
            value = sorted(names)
        else:
            value = [v for v in re.split(r"[\s,，、;；]+", value) if v]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SettingError("「作业」要是一个作业号的列表、一个清单文件，或者写「全部」")
    jobs = list(dict.fromkeys(v.strip() for v in value if v.strip()))
    bad = [j for j in jobs if not JOB_NAME.match(j)]
    if bad:
        raise SettingError(f"这些不像作业号：{bad[:5]}")
    if not jobs:
        raise SettingError("「作业」里一个作业号都没有")
    return jobs


def read_quantities(value) -> list[str]:
    if value is None:
        return list(C.QUANTITIES)
    if isinstance(value, str):
        value = [v for v in re.split(r"[\s,，、;；]+", value) if v]
    if not isinstance(value, list) or not value:
        raise SettingError(f"「导出哪些量」要从这几样里选：{'、'.join(C.QUANTITIES)}")
    unknown = [v for v in value if v not in C.QUANTITIES]
    if unknown:
        raise SettingError(f"「导出哪些量」里有不认识的：{unknown}。能选的是：{'、'.join(C.QUANTITIES)}")
    return [q for q in C.QUANTITIES if q in value]


class FeaArchiveExport(Plugin):
    name = "fea-archive-export"
    version = C.VERSION
    category = "FEA"
    what = "把归档里已有的 FE 作业导出成数据：标签、界面场、整体场。只读归档，不重算"

    settings = [
        Setting("归档", required=True,
                what="放作业归档的文件夹，里面是 <作业号>.tar.xz 和 <作业号>.manifest.json。填「只记位置」：只记位置和哈希，不复制"),
        Setting("作业", required=True,
                what="一批作业号：一个列表，或一个清单文件（一行一个，或 JSON 列表），或写「全部」（归档文件夹里所有的作业）"),
        Setting("导出哪些量", required=False,
                what=f"从 {'、'.join(C.QUANTITIES)} 里选，写成列表。不填就是三样全导出"),
    ]
    outputs = [
        Output("标签", what="标签.csv：一个作业一行，带每个作业的结局；标签说明.json：每列的来历；原始json：归档里各 json 的原文"),
        Output("界面场", what="每个有摩擦模型的作业一个 npz：界面节点对在每一步的相对位移、间隙、接触量、接触力，加界面三角形"),
        Output("整体场", what="每个作业一个 npz：网格，加每一步的位移、反力、应力、应变、应变能。归档里有什么就是什么"),
        Output("说明", what="两种场的格式；每个作业有什么、缺什么；归档里本来就没有的量"),
    ]

    # ---- 启动 -----------------------------------------------------------

    def start(self, ctx):
        try:
            archive = ctx.setting("归档")
            archive = Path(archive) if isinstance(archive, (str, Path)) else None
            if archive is None or not archive.is_dir():
                raise SettingError(f"「归档」要是一个文件夹：{ctx.setting('归档')}")
            jobs = read_jobs(ctx.setting("作业"), archive)
            quantities = read_quantities(ctx.setting("导出哪些量"))
        except (SettingError, OSError) as err:
            ctx.problem(f"设置用不了，没有启动任何任务：{err}")
            ctx.finish()
            return
        sd = ctx.private_dir
        sd.mkdir(parents=True, exist_ok=True)
        plan = {"archive": str(archive), "jobs": jobs, "quantities": quantities, "outputs": str(ctx.outputs_dir),
                "plugin_version": self.version}
        (sd / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        ctx.provenance(归档导出={"版本": self.version, "归档": str(archive), "作业数": len(jobs), "导出的量": quantities,
                              "后台进程用的python": sys.executable})
        for job in jobs:
            ctx.task(job, "排队")
        self._spawn(ctx, first=True)

    def _spawn(self, ctx, first: bool = False) -> None:
        sd = ctx.private_dir
        count_file = sd / "spawns.txt"
        count = 0 if first else self._spawns(sd)
        count_file.write_text(str(count + 1), encoding="ascii")
        spawn_worker(sd)

    @staticmethod
    def _spawns(sd: Path) -> int:
        try:
            return int((sd / "spawns.txt").read_text(encoding="ascii"))
        except (OSError, ValueError):
            return 0

    # ---- 报任务状态 ------------------------------------------------------

    def _consume(self, ctx) -> None:
        """把后台进程新写的进度报进实验记录。"""
        sd = ctx.private_dir
        path, mark = sd / "progress.jsonl", sd / "progress.offset"
        if not path.exists():
            return
        try:
            offset = int(mark.read_text(encoding="ascii"))
        except (OSError, ValueError):
            offset = 0
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
        end = data.rfind(b"\n") + 1  # 只认写完整的行
        if end == 0:
            return
        latest: dict[str, dict] = {}
        ended: list[dict] = []
        for raw in data[:end].split(b"\n"):
            if not raw.strip():
                continue
            line = json.loads(raw.decode("utf-8"))
            if line["state"] == "运行":
                latest[line["job"]] = line
            else:
                latest.pop(line["job"], None)
                ended.append(line)
        for line in ended:
            ctx.task(line["job"], line["state"], stage=line.get("stage", ""))
            if line.get("error"):
                ctx.problem(line["error"], task=line["job"], raw=line.get("raw", ""))
            if line.get("notes"):
                ctx.problem("导出时记下的：" + "；".join(line["notes"]), task=line["job"])
        now = ctx.tasks()
        for job, line in latest.items():
            have = now.get(job, {})
            if have.get("state") != "运行" or have.get("stage") != line.get("stage", ""):
                ctx.task(job, "运行", stage=line.get("stage", ""))
        mark.write_text(str(offset + end), encoding="ascii")

    def _register(self, ctx) -> None:
        """登记产出。"""
        sd = ctx.private_dir
        try:
            counts = json.loads((sd / "done.json").read_text(encoding="utf-8")).get("counts", {})
        except (OSError, ValueError):
            counts = {}
        said = f"完成 {counts.get('完成', '?')} 个作业，失败 {counts.get('失败', '?')} 个"
        for out in self.outputs:
            folder = ctx.outputs_dir / out.name
            if not folder.is_dir():
                continue
            files = [p for p in folder.rglob("*") if p.is_file()]
            if not files:
                continue
            n = len([p for p in files if p.suffix == ".npz"])
            what = f"{n} 个作业的{out.name}" if out.name in ("界面场", "整体场") else said
            ctx.output(out.name, folder, what=what)

    def poll(self, ctx):
        sd = ctx.private_dir
        if not (sd / "plan.json").exists():
            return
        done = (sd / "done.json").exists()
        self._consume(ctx)
        if not done and not pid_alive(worker_pid(sd)):
            time.sleep(0.3)  # 它可能是刚做完退出的
            done = (sd / "done.json").exists()
            self._consume(ctx)
            if not done:
                self._worker_gone(ctx)
                return
        if done:
            self._register(ctx)
            ctx.finish()

    def _worker_gone(self, ctx) -> None:
        """后台进程不在了，活还没做完。"""
        sd = ctx.private_dir
        count = self._spawns(sd)
        if count < MAX_SPAWN:
            ctx.problem(f"后台进程中途不在了，重新起一个（第 {count + 1} 次起）", raw=log_tail(sd))
            self._spawn(ctx)
            return
        ctx.problem(f"后台进程起了 {count} 次都中途退出，不再起了。没做完的任务记成失败，可以重试", raw=log_tail(sd))
        for job, t in ctx.tasks().items():
            if t["state"] in ("排队", "运行"):
                ctx.task(job, "失败", stage=t["stage"])
        ctx.finish()

    # ---- 停止、暂停、继续、重试 --------------------------------------------

    def stop(self, ctx):
        sd = ctx.private_dir
        if not (sd / "plan.json").exists():
            return
        (sd / "STOP").write_text(str(time.time()), encoding="ascii")
        pid = worker_pid(sd)
        deadline = time.time() + STOP_WAIT
        while pid_alive(pid) and time.time() < deadline:
            time.sleep(0.1)
        if pid_alive(pid):
            pid_kill(pid)
            deadline = time.time() + 10
            while pid_alive(pid) and time.time() < deadline:
                time.sleep(0.1)
        if pid_alive(pid):
            ctx.problem(f"后台进程（进程号 {pid}）叫不停，也结束不掉，要手动处理")
        self._consume(ctx)
        for job, t in ctx.tasks().items():
            if t["state"] in ("排队", "运行"):
                ctx.task(job, "停止", stage=t["stage"])

    def pause(self, ctx):
        """暂停：手上这个作业做完后等着，不开始下一个。"""
        sd = ctx.private_dir
        if (sd / "plan.json").exists():
            (sd / "PAUSE").write_text(str(time.time()), encoding="ascii")

    def resume(self, ctx):
        sd = ctx.private_dir
        if not (sd / "plan.json").exists():
            return
        (sd / "PAUSE").unlink(missing_ok=True)
        if not pid_alive(worker_pid(sd)) and not (sd / "done.json").exists():
            self._spawn(ctx, first=True)

    def retry(self, ctx):
        """重试：设置不变，把失败的和停掉的任务重新排上。做完的不重做。"""
        sd = ctx.private_dir
        if not (sd / "plan.json").exists():
            ctx.problem("这个实验没有启动成过（设置用不了），没有能重试的任务。要改设置就新建一个实验")
            ctx.finish()
            return
        pid = worker_pid(sd)
        if pid_alive(pid):
            pid_kill(pid)
        for name in ("STOP", "PAUSE", "done.json"):
            (sd / name).unlink(missing_ok=True)
        try:
            state = json.loads((sd / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        for job, t in ctx.tasks().items():
            if t["state"] in ("失败", "停止"):
                state.pop(job, None)
                ctx.task(job, "排队")
        (sd / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        self._spawn(ctx, first=True)


PLUGIN = FeaArchiveExport()
