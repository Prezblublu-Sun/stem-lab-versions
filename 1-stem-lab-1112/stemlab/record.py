"""地基：实验记录。

一个实验一个文件夹。里面的 record.jsonl 只追加，是这个实验唯一的事实。
操作台和仪表盘显示的内容都由它算出来（见 view）。

这个文件不认识任何具体的操作模块。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import time
from datetime import datetime
from pathlib import Path

RECORD_FILE = "record.jsonl"
IDS_FILE = "ids.log"

# 实验的状态，由操作和结束事件算出来
NOT_STARTED = "未启动"
RUNNING = "运行中"
PAUSED = "已暂停"
STOPPED = "已停止"
FINISHED = "已结束"

# 操作的名字
OPS = ("新建", "启动", "暂停", "继续", "停止", "重试")

# 任务的状态。插件只能报这五种；自己的阶段名写在 stage 里。
TASK_STATES = ("排队", "运行", "完成", "失败", "停止")
TASK_ENDED = ("完成", "失败", "停止")


class RecordError(Exception):
    """操作被拒绝时抛出。消息是给人看的。"""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    """文件的哈希；文件夹则是其中每个文件的相对路径和内容合起来的哈希。"""
    path = Path(path)
    if path.is_file():
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    if path.is_dir():
        h = hashlib.sha256()
        for sub in sorted(p for p in path.rglob("*") if p.is_file()):
            if "__pycache__" in sub.parts:
                continue
            h.update(sub.relative_to(path).as_posix().encode("utf-8"))
            h.update(b"\0")
            h.update(sha256_path(sub).encode("ascii"))
            h.update(b"\n")
        return h.hexdigest()
    raise RecordError(f"找不到：{path}")


def pid_alive(pid: int) -> bool:
    """这个进程还在不在。"""
    if pid <= 0:
        return False
    if os.name == "nt":  # Windows 上不能用 os.kill(pid, 0)，那会把进程杀掉
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


class Busy(RecordError):
    """等不到锁。"""


class _Lock:
    """一个锁文件，同一时刻只让一个进程（或线程）进去。

    里面写着拿锁的进程号。那个进程不在了，锁就当作没人要。
    """

    def __init__(self, folder: Path, name: str = ".lock", wait: float = 30):
        self.path = folder / name
        self.wait = wait

    def _stale(self) -> bool:
        try:
            text = self.path.read_text(encoding="ascii").strip()
            if text:
                return not pid_alive(int(text))
            return time.time() - self.path.stat().st_mtime > 120
        except (OSError, ValueError):
            return False

    def holder(self) -> int | None:
        """现在拿着锁的进程号。没人拿着返回 None。"""
        try:
            return int(self.path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None

    def __enter__(self):
        deadline = time.time() + self.wait
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                return self
            except FileExistsError:
                if self._stale():
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                if time.time() >= deadline:
                    raise Busy(f"等了 {self.wait:g} 秒还拿不到锁：{self.path}")
                time.sleep(0.05)
            except PermissionError:  # Windows 上别人正在删这个文件
                if time.time() >= deadline:
                    raise Busy(f"等了 {self.wait:g} 秒还拿不到锁：{self.path}")
                time.sleep(0.05)

    def __exit__(self, *exc):
        # Windows 上别处正好在读这个文件（看拿锁的进程还在不在）时删不掉。
        # 这时不能算了：锁留下来，这个进程又还活着，别处就永远等不到。等它读完再删。
        for _ in range(2000):
            try:
                os.unlink(self.path)
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(0.005)


class Store:
    """放所有实验的地方。"""

    def __init__(self, home: Path):
        self.home = Path(home)
        self.root = self.home / "experiments"

    def new_id(self) -> str:
        """给一个新编号。不重复；用过的编号即使文件夹被删也不再用。"""
        self.root.mkdir(parents=True, exist_ok=True)
        with _Lock(self.root):
            ids_file = self.root / IDS_FILE
            used = ids_file.read_text(encoding="utf-8").split() if ids_file.exists() else []
            n = len(used) + 1
            while True:
                exp_id = f"E{n:04d}"
                if exp_id not in used and not (self.root / exp_id).exists():
                    break
                n += 1
            (self.root / exp_id).mkdir()
            with open(ids_file, "a", encoding="utf-8") as f:
                f.write(exp_id + "\n")
        return exp_id

    def watch_lock(self) -> _Lock:
        """定时值守拿的锁。一个 home 同一时刻只有一处在值守。拿不到马上抛 Busy。"""
        return _Lock(self.root, ".watch", wait=0)

    def ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / RECORD_FILE).exists())

    def open(self, exp_id: str) -> "Experiment":
        exp = Experiment(self, exp_id)
        if not exp.record_path.exists():
            raise RecordError(f"没有这个实验：{exp_id}")
        return exp

    def create(self, plugin: dict, note: str = "", tags: list[str] | None = None) -> "Experiment":
        """新建一个实验。plugin 是插件报上来的名字、版本、类别、文件哈希。"""
        exp = Experiment(self, self.new_id())
        exp.append("新建实验", {"plugin": plugin, "note": note, "tags": list(tags or [])})
        exp.append("操作", {"op": "新建"})
        return exp


class Experiment:
    def __init__(self, store: Store, exp_id: str):
        self.store = store
        self.id = exp_id
        self.folder = store.root / exp_id
        self.record_path = self.folder / RECORD_FILE
        self.settings_dir = self.folder / "settings"
        self.outputs_dir = self.folder / "outputs"

    def busy(self, wait: float = 60) -> _Lock:
        """操作这个实验、叫它的插件时拿的锁。同一个实验一次只让一处动它。

        用法：with exp.busy(): ...  等不到就抛 Busy。
        """
        return _Lock(self.folder, ".busy", wait)

    # ---- 只追加的记录 -------------------------------------------------

    def events(self) -> list[dict]:
        with open(self.record_path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def append(self, type_: str, data: dict) -> dict:
        """追加一条。每条带序号和上一条的哈希，所以改过或删过能查出来。"""
        self.folder.mkdir(parents=True, exist_ok=True)
        with _Lock(self.folder):
            seq, prev = 0, ""
            if self.record_path.exists():
                with open(self.record_path, "rb") as f:
                    lines = [ln for ln in f.read().split(b"\n") if ln.strip()]
                if lines:
                    seq = json.loads(lines[-1])["seq"]
                    prev = sha256_bytes(lines[-1])
            event = {"seq": seq + 1, "time": now(), "type": type_, "data": data, "prev": prev}
            line = json.dumps(event, ensure_ascii=False, sort_keys=True)
            with open(self.record_path, "ab") as f:
                f.write(line.encode("utf-8") + b"\n")
        return event

    def check(self) -> list[str]:
        """核对记录有没有被改过。返回发现的问题，空表示完好。"""
        found = []
        with open(self.record_path, "rb") as f:
            lines = [ln for ln in f.read().split(b"\n") if ln.strip()]
        prev = ""
        for i, line in enumerate(lines, start=1):
            try:
                event = json.loads(line)
            except ValueError:
                found.append(f"第 {i} 行读不出来")
                prev = sha256_bytes(line)
                continue
            if event.get("seq") != i:
                found.append(f"第 {i} 行的序号是 {event.get('seq')}")
            if event.get("prev") != prev:
                found.append(f"第 {i} 行和上一行接不上，上一行被改过或被删过")
            prev = sha256_bytes(line)
        return found

    # ---- 由记录算出来的现状 -------------------------------------------

    def view(self) -> dict:
        """把记录整理成九项，加来历和状态。"""
        v = {
            "id": self.id,
            "plugin": {},
            "note": "",
            "notes": [],
            "tags": [],
            "settings": {},
            "frozen": False,
            "operations": [],
            "tasks": {},
            "outputs": [],
            "problems": [],
            "provenance": {},
            "status": NOT_STARTED,
            "created": "",
            "updated": "",
        }
        for e in self.events():
            t, d, when = e["type"], e["data"], e["time"]
            v["updated"] = when
            if t == "新建实验":
                v["plugin"] = d["plugin"]
                v["note"] = d["note"]
                v["tags"] = list(d["tags"])
                v["created"] = when
            elif t == "备注":
                v["notes"].append({"time": when, "text": d["text"]})
            elif t == "标签":
                for tag in d.get("add", []):
                    if tag not in v["tags"]:
                        v["tags"].append(tag)
                for tag in d.get("remove", []):
                    if tag in v["tags"]:
                        v["tags"].remove(tag)
            elif t == "填设置":
                v["settings"][d["name"]] = {**d, "time": when, "frozen": False}
            elif t == "存定设置":
                v["frozen"] = True
                for item in d["settings"]:
                    v["settings"][item["name"]] = {**item, "time": when, "frozen": True}
            elif t == "操作":
                v["operations"].append({"time": when, "op": d["op"]})
                v["status"] = {
                    "新建": NOT_STARTED,
                    "启动": RUNNING,
                    "暂停": PAUSED,
                    "继续": RUNNING,
                    "停止": STOPPED,
                    "重试": RUNNING,
                }[d["op"]]
            elif t == "任务":
                task = v["tasks"].setdefault(d["task"], {"history": []})
                task.update(state=d["state"], stage=d.get("stage", ""), machine=d.get("machine", ""))
                task["history"].append(
                    {"time": when, "state": d["state"], "stage": d.get("stage", ""), "machine": d.get("machine", "")}
                )
            elif t == "产出":
                v["outputs"].append({**d, "time": when})
            elif t == "问题":
                v["problems"].append({**d, "time": when})
            elif t == "来历":
                v["provenance"].update(d)
            elif t == "结束":
                v["status"] = FINISHED
        return v

    # ---- 设置 ---------------------------------------------------------

    def set_setting(self, name: str, content: dict, source: dict) -> None:
        """启动前填一项设置。再填同一项就是改，两次都留在记录里。启动后不能改。"""
        if self.view()["frozen"]:
            raise RecordError(f"{self.id} 已经启动，设置不能改。要改就新建一个实验。")
        self.append("填设置", {"name": name, "content": content, "source": source})

    def freeze_settings(self) -> list[dict]:
        """启动时把每项设置实际用的那一份存定：原文复制进来，算哈希。"""
        settings = self.view()["settings"]
        # 先全部查一遍，有一项不行就什么都不存，免得存一半
        for name, s in settings.items():
            kind = s["content"]["kind"]
            if kind not in ("值", "复制", "位置"):
                raise RecordError(f"设置「{name}」的内容种类不认识：{kind}")
            if kind != "值" and not Path(s["content"]["path"]).exists():
                raise RecordError(f"设置「{name}」的文件找不到：{s['content']['path']}")
        frozen = []
        for name, s in settings.items():
            content = dict(s["content"])
            kind = content["kind"]
            if kind == "值":
                text = json.dumps(content["value"], ensure_ascii=False, sort_keys=True)
                content["sha256"] = sha256_bytes(text.encode("utf-8"))
            elif kind == "复制":
                src = Path(content["path"])
                dst = self.settings_dir / name / src.name
                if dst.parent.exists():  # 上一次启动没成功留下的
                    shutil.rmtree(dst.parent)
                dst.parent.mkdir(parents=True)
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                content["stored"] = dst.relative_to(self.folder).as_posix()
                content["sha256"] = sha256_path(dst)
            elif kind == "位置":
                src = Path(content["path"])
                actual = sha256_path(src)
                expected = content.get("expected_sha256")
                if expected and expected != actual:
                    raise RecordError(
                        f"设置「{name}」指的文件和产出它的实验记下的哈希对不上：{src}"
                    )
                content["sha256"] = actual
            frozen.append({"name": name, "content": content, "source": s["source"]})
        self.append("存定设置", {"settings": frozen})
        return frozen

    def setting_value(self, name: str):
        """给插件用：取一项存定了的设置。值就返回值，文件就返回路径。"""
        s = self.view()["settings"].get(name)
        if s is None:
            return None
        content = s["content"]
        if content["kind"] == "值":
            return content["value"]
        if content["kind"] == "复制":
            return self.folder / content["stored"]
        return Path(content["path"])

    # ---- 插件往记录里写的四种东西 --------------------------------------

    def task(self, task: str, state: str, stage: str = "", machine: str = "") -> None:
        if state not in TASK_STATES:
            raise RecordError(f"任务状态只能是 {'、'.join(TASK_STATES)}，收到的是：{state}")
        self.append(
            "任务",
            {"task": str(task), "state": state, "stage": stage, "machine": machine or socket.gethostname()},
        )

    def output(self, name: str, path: Path, what: str = "") -> None:
        path = Path(path)
        try:
            where = path.resolve().relative_to(self.folder.resolve()).as_posix()
            inside = True
        except ValueError:
            where, inside = str(path), False
        self.append(
            "产出",
            {"name": name, "what": what, "path": where, "inside": inside, "sha256": sha256_path(path)},
        )

    def problem(self, error: str, task: str = "", raw: str = "") -> None:
        self.append("问题", {"task": str(task), "error": error, "raw": raw})

    def provenance(self, **items) -> None:
        self.append("来历", items)

    def output_path(self, name: str) -> tuple[Path, str]:
        """找这个实验的一项产出，返回它的位置和记下的哈希。"""
        for o in reversed(self.view()["outputs"]):
            if o["name"] == name:
                path = self.folder / o["path"] if o["inside"] else Path(o["path"])
                return path, o["sha256"]
        raise RecordError(f"{self.id} 没有叫「{name}」的产出")
