"""账本：data/ledger.jsonl，一行一条 JSON，只往后加。这里没有改和删。

每一条带两个指纹：
  prev  上一条的指纹；
  hash  这一条自己的指纹（除 hash 以外的全部内容，连同 prev，一起算 SHA-256）。
哪一行被改过，它自己的 hash 就对不上；哪一行被删掉、换掉或插进来，下一行的 prev 就对不上。

页面服务和各个实验的看护进程都会往里加，所以加之前先拿文件锁。
"""
import hashlib
import json
import os
import threading
import time

FILE = "ledger.jsonl"
_threads = threading.Lock()   # 同一个进程里的几个线程先在这里排队
_cache = {}                   # 账本没变就不重读：{路径: ((大小, 修改时间), 条目)}


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _canon(entry):
    return json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(_canon(body).encode("utf-8")).hexdigest()


# 文件锁：锁住 ledger.jsonl.lock 的第一个字节。进程死了，系统自己会放开。
if os.name == "nt":
    import msvcrt

    def _lock(f):
        while True:
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.05)

    def _unlock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(f):
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)


def read(data):
    """读出全部条目。读不懂的行跳过（“核对”页会把它指出来）。"""
    path = os.path.join(data, FILE)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return []
    key = (st.st_size, st.st_mtime_ns)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except ValueError:
                pass
    _cache[path] = (key, entries)
    return entries


def append(data, make):
    """往账本后面加一条，返回加上去的那一条。

    make 可以直接是一条（dict），也可以是一个函数：拿到现有的全部条目，返回要加的那一条，
    返回 None 就不加。“第几版”这种要看着前面才定得下来的数，就这样在锁里算，不会撞号。
    """
    os.makedirs(data, exist_ok=True)
    path = os.path.join(data, FILE)
    with _threads, open(path + ".lock", "a+b") as lk:
        _lock(lk)
        try:
            entries = read(data)
            body = make(entries) if callable(make) else make
            if body is None:
                return None
            last = entries[-1] if entries else {"n": 0, "hash": ""}
            entry = {"n": last["n"] + 1, "time": now(), **body, "prev": last["hash"]}
            entry["hash"] = _digest(entry)
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(_canon(entry) + "\n")
                f.flush()
                os.fsync(f.fileno())
            return entry
        finally:
            _unlock(lk)


def verify(data):
    """从头核对账本的链。返回 (对不对, 一句话)。"""
    path = os.path.join(data, FILE)
    if not os.path.exists(path):
        return True, "账本还是空的"
    prev, count = "", 0
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            try:
                entry = json.loads(line)
            except ValueError:
                return False, f"第 {i} 行读不懂，不是一条完整的记录"
            if entry.get("hash") != _digest(entry):
                return False, f"第 {i} 行的内容和它自己的指纹对不上：这一行被改过"
            if entry.get("prev") != prev:
                return False, f"第 {i} 行接不上上一行：它前面有一行被删掉、换掉或插进来过"
            prev, count = entry["hash"], i
    return True, f"链是完整的，一共 {count} 条"


class State:
    """账本叠出来的现状。不另存，每次都从账本算。"""

    def __init__(self, entries):
        self.things = {}   # 登记的东西：编号 -> 登记的那一条
        self.names = {}    # (类型, 名字) -> 各版的登记，旧的在前
        self.exps = {}     # 实验：编号 -> {"seal": 封存的那一条, "events": [启动、结束……], "outputs": [产出]}
        for e in entries:
            kind = e.get("kind")
            if kind == "register":
                self.things[e["n"]] = e
                self.names.setdefault((e["type"], e["name"]), []).append(e)
                made_by = (e.get("source") or {}).get("experiment")
                if made_by in self.exps:
                    self.exps[made_by]["outputs"].append(e)
            elif kind == "seal":
                self.exps[e["n"]] = {"seal": e, "events": [], "outputs": []}
            elif kind in ("start", "end") and e.get("exp") in self.exps:
                self.exps[e["exp"]]["events"].append(e)


def state(data):
    return State(read(data))
