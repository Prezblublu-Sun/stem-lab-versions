"""实验：封存、跑、停、继续、收尾，以及从账本和几个小文件读出现状。

一个实验在账本里是这样几条：
  seal   封存：哪一类、标题、选用的每样东西（名字、第几版、指纹）、做法（第几版、指纹）、
         全部设置的值、门槛、系统自己的指纹、照哪个实验开的。封存以后没有任何入口能改它。
  start  每启动（或继续）一次加一条。
  end    每结束一次加一条：完成 / 失败 / 停了。完成的带着报的数、判定和产出的指纹。
现状 = 这几条 + 进度文件的最后一行 + 心跳。不另存一份状态。

每个实验一个目录 data/runs/e0005/：
  task.json       核心写给做法的：选用的东西在哪、设置的值、输出放哪
  progress.jsonl  做法一行一行追加的进度
  result.json     做法跑完写的结果
  log.txt         做法的标准输出和错误输出
  heartbeat.json  看护进程每隔几秒写一次
  out/            做法放产出的地方
"""
import json
import os
import shlex
import signal
import subprocess
import sys
import time

from . import fingerprint, ledger, things
from .things import Problem

SYSTEM = os.path.dirname(os.path.abspath(__file__))   # stemlab/ 文件夹：系统自己
BEAT_EVERY = 2    # 心跳间隔，秒
BEAT_LOST = 15    # 这么久没有心跳就算中断，秒
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
OPS = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b,
       "<": lambda a, b: a < b, ">": lambda a, b: a > b}


def run_dir(data, n):
    return os.path.join(data, "runs", f"e{n:04d}")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ---------- 门槛和判定 ----------

def judge(gates, reports):
    """照封存时写下的门槛判定。没写门槛就是“未设门槛”，永远不是合格。"""
    if not gates:
        return {"result": "未设门槛", "checks": []}
    checks = []
    for g in gates:
        actual = reports.get(g["metric"])
        ok = isinstance(actual, (int, float)) and OPS[g["op"]](actual, g["value"])
        checks.append({**g, "actual": actual, "ok": ok})
    return {"result": "合格" if all(c["ok"] for c in checks) else "不合格", "checks": checks}


# ---------- 封存 ----------

def _ref(t):
    return {"n": t["n"], "type": t["type"], "name": t["name"], "version": t["version"],
            "fingerprint": t["fingerprint"]}


def seal(data, category, title, method, inputs, settings, gates, from_exp=None):
    """封存一个实验，返回封存的那一条。method 和 inputs 里给的是账本里登记的那一条。"""
    return ledger.append(data, {
        "kind": "seal", "category": category, "title": title,
        "method": _ref(method),
        "inputs": {k: (_ref(t) if t else None) for k, t in inputs.items()},
        "settings": settings, "gates": gates,
        "system": fingerprint.of(SYSTEM)[0],
        "from": from_exp,
    })


def changed_uses(data, st, method, inputs):
    """核对要用的东西和登记时一不一样。返回 [(键, 登记的那一条, 哪里不一样)]，空的就是都没变。"""
    out = []
    for key, t in [("做法", method)] + list(inputs.items()):
        why = things.check(data, t) if t else None
        if why:
            out.append((key, t, why))
    return out


# ---------- 启动、停、继续 ----------

def start(data, n, verify=True):
    """启动（或继续）实验 n：核对用的东西没变，写 task.json，起看护进程。"""
    st = ledger.state(data)
    x = st.exps[n]
    s = x["seal"]
    method = st.things[s["method"]["n"]]
    inputs = {k: (st.things[r["n"]] if r else None) for k, r in s["inputs"].items()}
    if verify:
        bad = changed_uses(data, st, method, inputs)
        if bad:
            raise Problem("这个实验用的东西和封存时不一样了，不能启动：" + "；".join(
                f"{t['type']}「{t['name']}」第{t['version']}版：{why}" for _, t, why in bad)
                + "。可以“照这个再开一个”，选上新登记的一版。")
    run = run_dir(data, n)
    os.makedirs(os.path.join(run, "out"), exist_ok=True)
    _write_json(os.path.join(run, "task.json"), {
        "experiment": f"e{n:04d}", "run": run, "out": os.path.join(run, "out"),
        "progress": os.path.join(run, "progress.jsonl"), "result": os.path.join(run, "result.json"),
        "inputs": {k: (things.where(data, t) if t else None) for k, t in inputs.items()},
        "settings": s["settings"],
    })
    attempt = 1 + sum(1 for e in x["events"] if e["kind"] == "start")
    ledger.append(data, {"kind": "start", "exp": n, "attempt": attempt})
    args = [sys.executable, "-m", "stemlab", "--data", data, "--watch", str(n)]
    try:
        with open(os.path.join(run, "log.txt"), "ab") as log:
            _spawn(args, os.path.dirname(SYSTEM), log)
    except OSError as err:
        ledger.append(data, {"kind": "end", "exp": n, "status": "失败", "code": None,
                             "why": f"看护进程起不来：{err}"})


_watchers = []   # 起过的看护进程；已经结束的，下次起新的时顺手收掉


def _spawn(args, cwd, log):
    """起一个和页面服务脱钩的进程：页面服务关掉它照跑；Windows 上不弹窗口。"""
    _watchers[:] = [p for p in _watchers if p.poll() is None]
    kw = dict(cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    if os.name != "nt":
        _watchers.append(subprocess.Popen(args, start_new_session=True, **kw))
        return
    flags = NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    try:   # 能脱离父进程所在的“作业”就脱离，免得被它一起关掉
        _watchers.append(subprocess.Popen(args, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw))
    except OSError:
        _watchers.append(subprocess.Popen(args, creationflags=flags, **kw))


def stop(data, n):
    """停下实验 n：杀掉看护进程和它下面整棵进程树，再替它在账本里记一笔“停了”。"""
    beat = _read_json(os.path.join(run_dir(data, n), "heartbeat.json")) or {}
    for pid in (beat.get("pid"), beat.get("child")):
        if not pid:
            continue
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=NO_WINDOW)
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass

    def make(entries):   # 只有最后一条还是“启动”时才记；看护进程刚好自己收了尾就不重复记
        ev = [e for e in entries if e.get("exp") == n and e.get("kind") in ("start", "end")]
        if ev and ev[-1]["kind"] == "start":
            return {"kind": "end", "exp": n, "status": "停了", "code": None, "why": "在页面上点了停"}
    ledger.append(data, make)


# ---------- 看护进程 ----------

def watch(data, n):
    """看护进程的全部工作：跑做法的命令，留心跳，跑完收尾。"""
    st = ledger.state(data)
    s = st.exps[n]["seal"]
    mdir = things.method_dir(data, st.things[s["method"]["n"]])
    run = run_dir(data, n)
    cmd = things.read_method(mdir)["command"]
    for key, value in (("{python}", sys.executable), ("{method}", mdir), ("{run}", run)):
        cmd = cmd.replace(key, f'"{value}"')
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    with open(os.path.join(run, "log.txt"), "ab") as log:
        log.write(f"\n---- {ledger.now()} 启动：{cmd}\n".encode("utf-8"))
        log.flush()
        try:
            child = subprocess.Popen(cmd if os.name == "nt" else shlex.split(cmd), cwd=run, env=env,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        except OSError as err:
            log.write(f"命令起不来：{err}\n".encode("utf-8"))
            return finish(data, n, None, f"命令起不来：{err}")
        while True:
            _write_json(os.path.join(run, "heartbeat.json"),
                        {"pid": os.getpid(), "child": child.pid, "time": ledger.now()})
            try:
                code = child.wait(timeout=BEAT_EVERY)
                break
            except subprocess.TimeoutExpired:
                pass
    finish(data, n, code)


def finish(data, n, code, why=""):
    """收尾：读 result.json，登记产出，照封存的门槛判定，往账本加一条结束记录。"""
    run = run_dir(data, n)
    result = _read_json(os.path.join(run, "result.json"))
    if code != 0 or not isinstance(result, dict):
        why = why or (f"退出码是 {code}，不是 0" if code != 0 else "做法退出了，但没有写 result.json")
        return ledger.append(data, {"kind": "end", "exp": n, "status": "失败", "code": code, "why": why})
    gates = ledger.state(data).exps[n]["seal"]["gates"]
    reports = result.get("reports") or {}
    outputs, problems = [], []
    for o in result.get("outputs") or []:
        try:
            t = things.register(data, o["type"], o["name"], os.path.join(run, o["path"]),
                                o.get("note", ""), source={"experiment": n})
            outputs.append(t["n"])
        except (Problem, KeyError, TypeError) as err:
            problems.append(f"产出登记不上：{o!r}：{err}")
    fp, files = fingerprint.of(run)
    return ledger.append(data, {
        "kind": "end", "exp": n, "status": "完成", "code": 0, "reports": reports,
        "verdict": judge(gates, reports), "outputs": outputs, "table": result.get("table"),
        "problems": problems, "fingerprint": fp, "files": files})


# ---------- 现状 ----------

def _seconds(stamp):
    return time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))


def _age(path):
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return None


def status(data, x):
    """一个实验现在怎样：没启动 / 在跑 / 中断 / 完成 / 失败 / 停了。"""
    events = x["events"]
    last = events[-1] if events else None
    info = {"attempts": sum(1 for e in events if e["kind"] == "start"), "end": None}
    if last is None:
        info["word"] = "没启动"
    elif last["kind"] == "end":
        info["word"], info["end"] = last["status"], last
    else:
        beat = _age(os.path.join(run_dir(data, x["seal"]["n"]), "heartbeat.json"))
        fresh = (beat is not None and beat < BEAT_LOST) or time.time() - _seconds(last["time"]) < BEAT_LOST
        info["word"] = "在跑" if fresh else "中断"
    return info


def _tail_bytes(path, size):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - size))
            raw = f.read()
    except OSError:
        return b""
    if len(raw) == size and b"\n" in raw:   # 从中间切开的第一行不完整，丢掉
        raw = raw[raw.index(b"\n") + 1:]
    return raw


def progress(data, n):
    """进度文件的最后一行，和多久没动静（进度和日志里较新的那个）。"""
    run = run_dir(data, n)
    last = None
    for line in reversed(_tail_bytes(os.path.join(run, "progress.jsonl"), 4096).splitlines()):
        try:
            last = json.loads(line.decode("utf-8"))
            break
        except ValueError:
            continue
    ages = [a for a in (_age(os.path.join(run, "progress.jsonl")), _age(os.path.join(run, "log.txt")))
            if a is not None]
    return (last if isinstance(last, dict) else None), (min(ages) if ages else None)


def tail(path, lines=20):
    """日志末尾几行。先当 UTF-8 读，读不通再当 GBK（中文 Windows 上别的程序常用），实在不行就替换掉。"""
    raw = _tail_bytes(path, 16384)
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])
