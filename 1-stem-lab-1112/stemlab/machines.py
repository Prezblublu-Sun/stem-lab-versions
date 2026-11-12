"""机器信息：CPU、内存、GPU、磁盘。只读。

机器的清单写在 home 下的 machines.json 里，这个文件不认识任何具体的机器。
没有 machines.json 时只看本机。

远端机器只开一条 ssh 长连接，循环跑在远端，本机不反复起进程。
远端跑的命令只读：nproc、/proc/stat、/proc/meminfo、nvidia-smi 查询、df。
"""
from __future__ import annotations

import io
import json
import os
import shlex
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

INTERVAL = 5  # 秒
GPU_QUERY = "--query-gpu=index,utilization.gpu,memory.used,memory.total,name"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def remote_script(disks: list[str], interval: int = INTERVAL) -> str:
    """在那一头循环跑的脚本。每隔几秒打印一组：B 开头，E 结尾。"""
    df = ""
    if disks:
        paths = " ".join(shlex.quote(d) for d in disks)
        df = f"df -Pk {paths} 2>/dev/null | awk 'NR>1{{print \"D\",$6,$2,$3}}'\n"
    return (
        "while true; do\n"
        "echo B\n"
        'echo "N $(nproc)"\n'
        'echo "C $(head -1 /proc/stat)"\n'
        "awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} END{print \"M\",t,a}' /proc/meminfo\n"
        f"nvidia-smi {GPU_QUERY} --format=csv,noheader,nounits 2>/dev/null | sed 's/^/G /'\n"
        f"{df}"
        "echo E\n"
        f"sleep {interval}\n"
        "done\n"
    )


def cpu_percent(prev: list[int] | None, cur: list[int]) -> float | None:
    """由 /proc/stat 第一行前后两次的数算占用。第一次没有上一次，返回 None。"""
    if not prev:
        return None
    idle = (cur[3] + cur[4]) - (prev[3] + prev[4])
    total = sum(cur[:8]) - sum(prev[:8])
    if total <= 0:
        return None
    return round(100.0 * (1 - idle / total), 1)


def parse_gpu(text: str) -> dict | None:
    """nvidia-smi 的一行：index, 占用, 已用显存, 总显存, 名字。"""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 5:
        return None

    def num(s):
        try:
            return float(s)
        except ValueError:
            return None

    return {
        "index": parts[0],
        "util": num(parts[1]),
        "mem_used_mb": num(parts[2]),
        "mem_total_mb": num(parts[3]),
        "name": ",".join(parts[4:]).strip(),
    }


def _gb(kb: float) -> float:
    return round(kb / 1024 / 1024, 1)


def _pct(used: float, total: float) -> float | None:
    return round(100.0 * used / total, 1) if total else None


class BlockParser:
    """把那一头打印的行拼成一次采样。"""

    def __init__(self):
        self.prev_cpu: list[int] | None = None
        self.block: dict | None = None

    def feed(self, line: str) -> dict | None:
        tag, _, rest = line.strip().partition(" ")
        if tag == "B":
            self.block = {"gpus": [], "disks": []}
        elif self.block is None:
            return None
        elif tag == "N":
            self.block["cores"] = int(rest)
        elif tag == "C":
            cur = [int(x) for x in rest.split()[1:]]
            self.block["cpu"] = cpu_percent(self.prev_cpu, cur)
            self.prev_cpu = cur
        elif tag == "M":
            total, avail = (float(x) for x in rest.split())
            used = total - avail
            self.block["mem"] = {"total_gb": _gb(total), "used_gb": _gb(used), "percent": _pct(used, total)}
        elif tag == "G":
            gpu = parse_gpu(rest)
            if gpu:
                self.block["gpus"].append(gpu)
        elif tag == "D":
            path, total, used = rest.rsplit(" ", 2)
            self.block["disks"].append(
                {"path": path, "total_gb": _gb(float(total)), "used_gb": _gb(float(used)), "percent": _pct(float(used), float(total))}
            )
        elif tag == "E":
            done, self.block = self.block, None
            return done
        return None


class Machine(threading.Thread):
    """一台机器。后台一直采，snapshot() 给出最近一次。"""

    def __init__(self, conf: dict, interval: int = INTERVAL):
        super().__init__(daemon=True)
        self.conf = conf
        self.name_ = conf.get("name") or socket.gethostname()
        self.kind = conf.get("kind", "本机")
        self.disks = list(conf.get("disks", []))
        self.interval = interval
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.children: list[subprocess.Popen] = []
        self.state = {"ok": False, "error": "还没有采到", "sampled": None}

    # ---- 对外 ---------------------------------------------------------

    def snapshot(self) -> dict:
        with self.lock:
            s = dict(self.state)
        sampled = s.pop("sampled")
        s["name"] = self.name_
        s["kind"] = self.kind
        s["time"] = datetime.fromtimestamp(sampled).astimezone().isoformat(timespec="seconds") if sampled else None
        s["age_s"] = round(time.time() - sampled, 1) if sampled else None
        if sampled and time.time() - sampled > 4 * self.interval and s["ok"]:
            s["ok"], s["error"] = False, "有一阵没有新数据了"
        return s

    def stop(self) -> None:
        self.stop_event.set()
        for child in list(self.children):
            try:
                child.terminate()
            except OSError:
                pass

    # ---- 内部 ---------------------------------------------------------

    def _good(self, sample: dict) -> None:
        with self.lock:
            self.state = {**sample, "ok": True, "error": "", "sampled": time.time()}

    def _bad(self, error: str) -> None:
        with self.lock:
            self.state = {**self.state, "ok": False, "error": error}

    def run(self) -> None:
        wait = 30
        while not self.stop_event.is_set():
            try:
                if self.kind == "ssh":
                    self._stream(list(self.conf["ssh"]) + ["sh", "-s"])
                elif os.name == "nt":
                    self._local_windows()
                else:
                    self._stream(["sh", "-s"])
                wait = 30
            except Exception as err:  # 出问题是正常的：显示出来，过一会儿再连
                self._bad(f"{type(err).__name__}: {err}")
            if self.stop_event.wait(wait):
                break
            wait = min(wait * 2, 300)

    def _spawn(self, cmd: list[str], stdin=None) -> subprocess.Popen:
        # 管道用字节：文本方式在 Windows 上会把换行写成 \r\n，那一头的 sh 读不了
        child = subprocess.Popen(
            cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW
        )
        child.lines = io.TextIOWrapper(child.stdout, encoding="utf-8", errors="replace")
        self.children.append(child)
        return child

    def _stream(self, cmd: list[str]) -> None:
        """起一个长驻的进程，把脚本从标准输入送过去，然后一直读它打印的行。"""
        child = self._spawn(cmd, stdin=subprocess.PIPE)
        try:
            child.stdin.write(remote_script(self.disks, self.interval).encode("utf-8"))
            child.stdin.close()
            parser, noise = BlockParser(), ""
            for line in child.lines:
                if self.stop_event.is_set():
                    break
                try:
                    sample = parser.feed(line)
                except (ValueError, IndexError):
                    sample, noise = None, line.strip()
                if sample is not None:
                    self._good(sample)
                elif line.strip() and line[:2] not in ("B\n", "N ", "C ", "M ", "G ", "D ", "E\n"):
                    noise = line.strip()
            code = child.wait()
            if not self.stop_event.is_set():
                raise RuntimeError(f"连接断了（退出码 {code}）{'：' + noise if noise else ''}")
        finally:
            if child.poll() is None:
                child.terminate()
            self.children.remove(child)

    def _local_windows(self) -> None:
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        kernel32 = ctypes.windll.kernel32

        def times():
            idle, kern, user = FILETIME(), FILETIME(), FILETIME()
            kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
            val = lambda ft: (ft.hi << 32) | ft.lo
            return val(idle), val(kern) + val(user)

        gpus: dict[str, dict] = {}
        gpu_child = None
        if shutil.which("nvidia-smi"):
            gpu_child = self._spawn(
                ["nvidia-smi", GPU_QUERY, "--format=csv,noheader,nounits", "-l", str(self.interval)]
            )

            def read_gpu():
                for line in gpu_child.lines:
                    gpu = parse_gpu(line)
                    if gpu:
                        gpus[gpu["index"]] = gpu

            threading.Thread(target=read_gpu, daemon=True).start()

        try:
            prev = times()
            while not self.stop_event.wait(self.interval):
                cur = times()
                d_idle, d_total = cur[0] - prev[0], cur[1] - prev[1]
                prev = cur
                mem = MEMORYSTATUSEX()
                mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
                total_kb = mem.ullTotalPhys / 1024
                used_kb = (mem.ullTotalPhys - mem.ullAvailPhys) / 1024
                disks = []
                for path in self.disks:
                    try:
                        u = shutil.disk_usage(path)
                        disks.append({"path": path, "total_gb": _gb(u.total / 1024), "used_gb": _gb(u.used / 1024), "percent": _pct(u.used, u.total)})
                    except OSError as err:
                        disks.append({"path": path, "error": str(err)})
                self._good({
                    "cores": os.cpu_count(),
                    "cpu": round(100.0 * (1 - d_idle / d_total), 1) if d_total > 0 else None,
                    "mem": {"total_gb": _gb(total_kb), "used_gb": _gb(used_kb), "percent": _pct(used_kb, total_kb)},
                    "gpus": [gpus[k] for k in sorted(gpus)],
                    "disks": disks,
                })
        finally:
            if gpu_child is not None:
                if gpu_child.poll() is None:
                    gpu_child.terminate()
                self.children.remove(gpu_child)


def load_config(home: Path) -> list[dict]:
    path = Path(home) / "machines.json"
    if not path.exists():
        return [{"name": socket.gethostname(), "kind": "本机"}]
    return json.loads(path.read_text(encoding="utf-8"))


class MachineWatch:
    def __init__(self, home: Path, interval: int = INTERVAL):
        self.machines = [Machine(conf, interval) for conf in load_config(home)]

    def start(self) -> None:
        for m in self.machines:
            m.start()

    def stop(self) -> None:
        for m in self.machines:
            m.stop()

    def snapshot(self) -> list[dict]:
        return [m.snapshot() for m in self.machines]
