"""账本：data/ledger.jsonl，一行一条 JSON，只往后加。这里没有改和删。

每一条带两个指纹：
  prev  上一条的指纹；
  hash  这一条自己的指纹（除 hash 以外的全部内容，连同 prev，一起算 SHA-256）。
哪一行被改过，它自己的 hash 就对不上；哪一行被删掉、换掉或插进来，下一行的 prev 就对不上。
账本旁边还有一个 ledger.head，记着最后一条的编号和指纹：末尾被砍掉、或整个换成旧的，和它一比就知道。
往里加之前先和头比；对不上，就先在账本里加一条 gap 记下这件事，再照常加。这样痕迹一直留在账本里。

页面服务和各个实验的看护进程都会往里加，所以加之前先拿文件锁。
"""
import hashlib
import json
import os
import threading
import time

FILE = "ledger.jsonl"
HEAD = "ledger.head"
_threads = threading.Lock()   # 同一个进程里的几个线程先在这里排队
_cache = {}                   # 账本没变就不重读：{路径: ((大小, 修改时间), 条目)}
_trouble = {}                 # 账本没变就不重新核对：{路径: ((大小, 修改时间), 对不上的地方)}


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _canon(entry):
    return json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(_canon(body).encode("utf-8")).hexdigest()


# 文件锁：锁住一个 .lock 文件的第一个字节。握着它的进程死了，系统自己会放开。
# 账本用它排队往里加；每个实验的看护进程从头到尾握着一把，页面看锁有没有人握着就知道它还活着没有。
if os.name == "nt":
    import msvcrt

    def _try(f):
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try(f):
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)


def grab(path, wait):
    """试着拿住一把文件锁，最多等 wait 秒。拿到返回打开着的锁文件（进程结束就放开），拿不到返回 None。"""
    f = open(path, "a+b")
    end = time.time() + wait
    while not _try(f):
        if time.time() >= end:
            f.close()
            return None
        time.sleep(0.05)
    return f


def held(path):
    """这把锁现在有没有人握着。"""
    if not os.path.isdir(os.path.dirname(path)):
        return False
    f = grab(path, 0)
    if f is None:
        return True
    _unlock(f)
    f.close()
    return False


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


def _head(data):
    """账本旁边的头：最后一条的编号和指纹。没有返回 None，读不懂返回 {}。"""
    try:
        with open(os.path.join(data, HEAD), encoding="utf-8") as f:
            head = json.load(f)
    except FileNotFoundError:
        return None
    except ValueError:
        return {}
    return head if isinstance(head, dict) else {}


def _gap(head, last):
    """账本最后一条（没有就是 None）和头对不上的地方，用一句话说；对得上返回空。"""
    n, h = (last or {}).get("n", 0), (last or {}).get("hash")
    if head is None:
        return "账本旁边的头不见了" if last else ""
    if not isinstance(head.get("n"), int):
        return "账本旁边的头读不懂：被改过"
    if n < head["n"]:
        return f"账本末尾少了 {head['n'] - n} 条：被砍掉过，或被换成了旧的"
    if n == head["n"] and h != head.get("hash"):
        return "账本最后一条和头里记的指纹不一样：被换过"
    return ""


def _add(data, last, body):
    """真正写一条：接在 last 后面，写进账本，再把头改成这一条。"""
    last = last or {"n": 0, "hash": ""}
    entry = {"n": last["n"] + 1, "time": now(), **body, "prev": last["hash"]}
    entry["hash"] = _digest(entry)
    with open(os.path.join(data, FILE), "a", encoding="utf-8", newline="\n") as f:
        f.write(_canon(entry) + "\n")
        f.flush()
        os.fsync(f.fileno())
    with open(os.path.join(data, HEAD), "w", encoding="utf-8") as f:
        json.dump({"n": entry["n"], "hash": entry["hash"]}, f)
    return entry


def append(data, make):
    """往账本后面加一条，返回加上去的那一条。

    make 可以直接是一条（dict），也可以是一个函数：拿到现有的全部条目，返回要加的那一条，
    返回 None 就不加。“第几版”这种要看着前面才定得下来的数，就这样在锁里算，不会撞号。
    账本和头对不上时不挡（挡了看护进程就收不了尾），先加一条 gap 把这件事记下来。
    """
    os.makedirs(data, exist_ok=True)
    with _threads, grab(os.path.join(data, FILE) + ".lock", float("inf")) as lk:
        try:
            entries = read(data)
            body = make(entries) if callable(make) else make
            if body is None:
                return None
            last, head = (entries[-1] if entries else None), _head(data)
            why = _gap(head, last)
            if why:
                last = _add(data, last, {"kind": "gap", "why": why, "head": head,
                                         "last": {"n": last["n"], "hash": last["hash"]} if last else None})
            return _add(data, last, body)
        finally:
            _unlock(lk)


def verify(data):
    """从头核对账本。返回 (一共几行, [(第几行, 那一条, 哪里不对)])；列表是空的就是现在都对得上。
    除了逐行核对链，还和旁边的头比：末尾被砍掉、整个换成旧的、头不见了，都算现在对不上。
    已经记进账本的 gap（以前出过的事）不算在这里，核对页另外列。"""
    path = os.path.join(data, FILE)
    if not os.path.exists(path):
        return 0, []
    with _threads, grab(path + ".lock", float("inf")) as lk:   # 和往里加的错开，账本和头是同一刻的
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            head = _head(data)
        finally:
            _unlock(lk)
    bad, prev, last = [], "", None
    for i, line in enumerate(lines, 1):
        try:
            entry = json.loads(line)
        except ValueError:
            bad.append((i, None, "读不懂，不是一条完整的记录"))
            prev = None
            continue
        if entry.get("hash") != _digest(entry):
            bad.append((i, entry, "内容和它自己的指纹对不上：这一行被改过"))
        elif prev is not None and entry.get("prev") != prev:
            bad.append((i, entry, "接不上上一行：它前面有一行被删掉、换掉或插进来过"))
        prev, last = entry.get("hash"), entry
    why = _gap(head, last)
    if why:
        bad.append((None, None, why))
    return len(lines), bad


def trouble(data):
    """账本现在有没有对不上的地方（每一页顶上都要说）。只在账本变了以后重算一次。"""
    path = os.path.join(data, FILE)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return []
    key = (st.st_size, st.st_mtime_ns)
    hit = _trouble.get(path)
    if not hit or hit[0] != key:
        hit = _trouble[path] = (key, verify(data)[1])
    return hit[1]


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
