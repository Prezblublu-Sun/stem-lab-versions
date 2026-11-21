"""两台机器现在的数：CPU、内存、GPU、磁盘。只读。

本机直接读。远端开一条 ssh 长连接，循环跑在那一头，每隔几秒打印一组数；
这边一关，连接断开，那一头的循环在下一次打印时跟着退出。不在本机起循环去反复连远端。

送到远端的命令只有 REMOTE_READS 里这几条，全是读。连不连远端由 board.json 的 remote 定，
默认不连：这份清单要你先同意，同意了再把它改成 true。

board.json 放在仓库根目录，可以没有。写法见 DEFAULTS。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import psutil

from stemlab.contract import layout, machines

CONFIG = "board.json"
DEFAULTS = {
    "interval": 5,              # 每隔几秒读一次数
    "remote": False,            # 连不连远端。同意了 REMOTE_READS 这份清单再改成 true
    "disks": {},                # 机器名 -> 要看的盘或文件夹。本机不写就看 data/ 和仓库所在的盘；远端不写就看 /
    "alerts": {
        "disk_free_gb": 20,             # 磁盘剩余低于多少 GB
        "memory_percent": 95,           # 内存占用高于百分之多少
        "unreachable_seconds": 60,      # 远端多久没有数算连不上
        "starting_minutes": 10,         # 一个实验启动中超过多少分钟
        "backup_days": 8,               # 上次备份超过多少天（定的是每周一次）
    },
}

# 送到远端的全部命令。都是读
REMOTE_READS = (
    "nproc",
    "head -1 /proc/stat",
    "grep -E '^(MemTotal|MemAvailable):' /proc/meminfo",
    "nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits",
    "nvidia-smi --query-compute-apps=pid --format=csv,noheader",
    "df -Pk {disks}",
)
_GPU_QUERY = ["--query-gpu=index,name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
_REMOTE_PATH = re.compile(r"/[A-Za-z0-9_./-]*")     # 要拼进远端命令里的位置，只许这些字符
_QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
_GB = 1024 ** 3


def _line(value) -> bool:
    """告警线得是一个不小于零的数。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def read_config() -> tuple[dict, str | None]:
    """读 board.json。没有就用默认的；读不出来也用默认的，并说出原因。告警线不认得或者不是数的，那一条用默认的，也说出来。"""
    config = json.loads(json.dumps(DEFAULTS))
    path = layout.repo_root() / CONFIG
    try:
        given = json.loads(path.read_bytes())
        if not isinstance(given, dict):
            raise ValueError("必须是一个 JSON 对象")
    except FileNotFoundError:
        return config, None
    except (OSError, ValueError) as error:
        return config, f"{CONFIG} 读不出来，现在用的是默认设置：{error}"
    wrong = []
    for key, value in given.items():
        if key == "alerts":
            for name, line in (value.items() if isinstance(value, dict) else [("", value)]):
                if name in config["alerts"] and _line(line):
                    config["alerts"][name] = line
                else:
                    wrong.append(f"alerts.{name}" if name else "alerts")
        elif key in config:
            config[key] = value
    if wrong:
        return config, f"{CONFIG} 里这几项不认得、或者不是不小于零的数，用的是默认的线：{'、'.join(wrong)}"
    return config, None


def read_machines() -> tuple[tuple, str | None]:
    """读机器清单。读不出来就是空的，并说出原因。"""
    try:
        return machines.parse_machines(json.loads((layout.repo_root() / "machines.json").read_bytes())), None
    except (OSError, ValueError) as error:
        return (), f"机器清单读不出来：{error}"


def remote_script(interval: float, disks) -> str:
    """在远端跑的那个循环。每一圈打印一组数；打印不出去（连接断了）就退出。"""
    cores, stat, memory, gpu, apps, df = REMOTE_READS
    return (f"while echo @begin; do {cores}; {stat}; {memory}; echo @gpu; {gpu} 2>/dev/null; "
            f"echo @apps; {apps} 2>/dev/null; echo @df; {df.format(disks=' '.join(disks))} 2>/dev/null; "
            f"echo @end; sleep {max(1, int(interval))}; done")


# ---------------------------------------------------------------- 把打印出来的数读成一组

def _gpu(line: str) -> dict | None:
    parts = [part.strip() for part in line.split(",")]
    try:
        return {"index": int(parts[0]), "name": parts[1], "percent": float(parts[2]),
                "memory_used_mb": float(parts[3]), "memory_total_mb": float(parts[4])}
    except (IndexError, ValueError):
        return None


def parse_remote(lines, before: dict | None = None) -> dict:
    """远端打印的一组数（@begin 和 @end 之间的各行）。before 是上一组，用来算 CPU 占用。"""
    found = {"gpus": [], "gpu_processes": 0, "disks": [], "cpu": None, "cores": None, "memory": None}
    part, total, available = "top", None, None
    for line in lines:
        line = line.strip()
        if line.startswith("@"):
            part = line[1:]
        elif part == "top":
            fields = line.split()
            if line.isdigit():
                found["cores"] = int(line)
            elif fields and fields[0] == "cpu":
                counts = [int(value) for value in fields[1:9]]
                found["ticks"] = {"total": sum(counts), "idle": counts[3] + counts[4]}
            elif fields and fields[0] == "MemTotal:":
                total = int(fields[1]) * 1024
            elif fields and fields[0] == "MemAvailable:":
                available = int(fields[1]) * 1024
        elif part == "gpu":
            if _gpu(line):
                found["gpus"].append(_gpu(line))
        elif part == "apps":
            found["gpu_processes"] += bool(line)
        elif part == "df":
            fields = line.split()
            if len(fields) >= 6 and fields[1].isdigit():
                size, free = int(fields[1]) * 1024, int(fields[3]) * 1024
                found["disks"].append({"path": fields[5], "total_gb": round(size / _GB, 1), "free_gb": round(free / _GB, 1),
                                       "percent": round(100 * (1 - free / size), 1) if size else None})
    if total and available is not None:
        found["memory"] = {"total_gb": round(total / _GB, 1), "used_gb": round((total - available) / _GB, 1),
                           "percent": round(100 * (1 - available / total), 1)}
    ticks, old = found.get("ticks"), (before or {}).get("ticks")
    if ticks and old and ticks["total"] > old["total"]:
        found["cpu"] = round(100 * (1 - (ticks["idle"] - old["idle"]) / (ticks["total"] - old["total"])), 1)
    return found


def local_numbers(disks) -> dict:
    """本机现在的数。"""
    memory = psutil.virtual_memory()
    found = {"cores": psutil.cpu_count(), "cpu": psutil.cpu_percent(None),
             "memory": {"total_gb": round(memory.total / _GB, 1), "used_gb": round((memory.total - memory.available) / _GB, 1),
                        "percent": round(memory.percent, 1)},
             "disks": [], "gpus": [], "gpu_processes": None}
    for path in disks:
        try:
            usage = psutil.disk_usage(path)
        except OSError:
            continue
        found["disks"].append({"path": str(path), "total_gb": round(usage.total / _GB, 1),
                               "free_gb": round(usage.free / _GB, 1), "percent": round(usage.percent, 1)})
    return found


# ---------------------------------------------------------------- 一直开着的读数进程

class _Leash:
    """把子进程拴在本进程上：本进程一没（哪怕是被强行结束的），拴着的子进程由系统跟着结束。

    不这样做的话，仪表盘被强行关掉之后，ssh 的长连接和它那一头的循环会留下来，越积越多。
    Windows 上用作业对象。别的系统上，子进程往断了的管道里一写就自己退出，不用管。
    """

    def __init__(self):
        self.job = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        job = self.kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000        # 作业对象的句柄一关（本进程没了），里面的进程全部结束
        if job and self.kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.job = job                                      # 句柄一直留着不关：它跟着本进程一起没

    def hold(self, process: subprocess.Popen) -> None:
        if self.job is None:
            return
        handle = self.kernel.OpenProcess(0x0101, False, process.pid)   # 结束它、把它放进作业对象，要这两样权限
        if handle:
            self.kernel.AssignProcessToJobObject(self.job, handle)
            self.kernel.CloseHandle(handle)


_LEASH = None


def _leash() -> _Leash:
    global _LEASH
    if _LEASH is None:
        _LEASH = _Leash()
    return _LEASH


class Feed:
    """一个一直开着的进程，一组一组地往外打印数。读它的是守护线程；进程没了，隔一会儿重起。

    begin 和 end 是一组数的头尾标记；不给就是一行一组。用完要 close：它起的进程跟着结束。
    """

    def __init__(self, command, parse, begin: str | None = None, end: str | None = None):
        self.command, self.parse, self.begin, self.end = list(command), parse, begin, end
        self.latest, self.at, self.error = None, None, None
        self._stop, self._process = threading.Event(), None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        wait = 5.0
        while not self._stop.is_set():
            said = []
            try:
                self._process = subprocess.Popen(self.command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                 stderr=subprocess.STDOUT, **_QUIET)
                _leash().hold(self._process)
                if self._stop.is_set():                         # close 赶在进程起来之前叫了
                    self._process.kill()
                block = None if self.begin else []
                for raw in self._process.stdout:
                    if self._stop.is_set():
                        break
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if self.begin is None:
                        self._take([line])
                    elif line == self.begin:
                        block = []
                    elif line == self.end and block is not None:
                        self._take(block)
                        block, wait = None, 5.0
                    elif block is not None:
                        block.append(line)
                    elif line.strip():
                        said = (said + [line.strip()])[-3:]     # 一组数之外的话：多半是连不上的原因
                code = self._process.wait()
                self.error = f"读数的连接断了（退出码 {code}）" + (f"：{' / '.join(said)}" if said else "")
            except OSError as error:
                self.error = f"读数的进程起不来：{error}"
            if self._stop.wait(wait):
                return
            wait = min(wait * 3, 60.0)

    def _take(self, block) -> None:
        try:
            self.latest, self.at, self.error = self.parse(block, self.latest), time.time(), None
        except (ValueError, IndexError, KeyError, ZeroDivisionError):
            pass                                                # 这一组读不懂就等下一组
        except Exception as error:  # noqa: BLE001  读数的线程不能因为一组没想到的数就停下，停了就再也没有数
            self.error = f"有一组数读不懂：{type(error).__name__}: {error}"

    def age(self) -> float | None:
        return None if self.at is None else time.time() - self.at

    def close(self) -> None:
        """停下来，并等它起的进程真的结束。"""
        self._stop.set()
        process = self._process
        if process is not None and process.poll() is None:
            process.kill()
        self._thread.join(timeout=10)                           # 线程里那一头看到停的记号，会把刚起来的进程也结束掉
        process = self._process
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            process.stdout.close()


def _local_gpus(block, before) -> dict:
    gpus = dict((before or {}).get("by_index", {}))
    for line in block:
        found = _gpu(line)
        if found:
            gpus[found["index"]] = found
    return {"by_index": gpus}


class Monitor:
    """开着的时候，随时答得出每台机器现在的数。用完要 close：远端的那条连接跟着断开。"""

    def __init__(self):
        self.config, self.config_problem = read_config()
        self.machines, self.machines_problem = read_machines()
        interval = self.config["interval"] if isinstance(self.config["interval"], (int, float)) else 5
        here = socket.gethostname().lower()
        names = [machine.name for machine in self.machines if machine.host.lower() == here]
        self.here = names[0] if names else next((m.name for m in self.machines if m.role == machines.DESK), None)
        self.feeds: dict[str, Feed] = {}
        self.local_gpu = None
        psutil.cpu_percent(None)                                # 第一次叫只是开始计数
        if shutil.which("nvidia-smi"):
            self.local_gpu = Feed(["nvidia-smi", *_GPU_QUERY, "-l", str(max(1, int(interval)))], _local_gpus)
        for machine in self.machines:
            if machine.name != self.here and machine.ssh and self.config["remote"] is True:
                disks = [path for path in self._disks(machine) if _REMOTE_PATH.fullmatch(str(path))] or ["/"]
                ssh = str(Path(machine.bin) / "ssh") if machine.bin else "ssh"
                command = [ssh, "-p", str(machine.port), *machine.options, machine.ssh, remote_script(interval, disks)]
                self.feeds[machine.name] = Feed(command, parse_remote, "@begin", "@end")

    def _disks(self, machine) -> list:
        listed = self.config["disks"].get(machine.name) if isinstance(self.config["disks"], dict) else None
        if isinstance(listed, list) and listed:
            return listed
        if machine.name != self.here:
            return ["/"]
        return list(dict.fromkeys(Path(path).anchor or str(path) for path in (layout.data_root(), layout.repo_root())))

    def read(self) -> list[dict]:
        """每台机器一行。远端没开读数的，只有清单里的那几项。"""
        rows = []
        for machine in self.machines:
            row = {"name": machine.name, "role": machine.role, "host": machine.host, "slots": machine.slots,
                   "here": machine.name == self.here, "watched": True, "age": 0.0, "error": None}
            if row["here"]:
                row.update(local_numbers(self._disks(machine)))
                if self.local_gpu is not None and self.local_gpu.latest:
                    row["gpus"] = [self.local_gpu.latest["by_index"][index] for index in sorted(self.local_gpu.latest["by_index"])]
            elif machine.name in self.feeds:
                feed = self.feeds[machine.name]
                row.update({key: value for key, value in (feed.latest or {}).items() if key != "ticks"})
                row.update(age=feed.age(), error=feed.error)
            else:
                row.update(watched=False, age=None)
            rows.append(row)
        return rows

    def close(self) -> None:
        for feed in [*self.feeds.values(), *([self.local_gpu] if self.local_gpu else [])]:
            feed.close()
