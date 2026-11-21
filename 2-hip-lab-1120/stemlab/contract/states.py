"""状态：实验的四种状态、轮的结局、任务的状态、结局的类别，和状态表。

规则只有这一份：
    fold      由记录重放出现状，不另存
    can       一个操作此刻能不能做（why_not 给原因）
    refuse    一条条目此刻能不能记
三个问的都是下面同一张表。别的块不许出现对状态名的判断。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 实验的状态。实验的状态就是它最后一轮的状态
NEW, STARTING, RUNNING, ENDED = "new", "starting", "running", "ended"
STATES = (NEW, STARTING, RUNNING, ENDED)
NONE = "none"       # 还没有记录，只在新建之前出现

# 轮的结局。做完不等于每个任务都成功
DONE, FAILED, STOPPED, START_FAILED = "done", "failed", "stopped", "start_failed"
RESULTS = (DONE, FAILED, STOPPED, START_FAILED)

# 任务的状态
T_QUEUED, T_RUNNING, T_DONE, T_FAILED, T_STOPPED = "queued", "running", "done", "failed", "stopped"
TASK_STATES = (T_QUEUED, T_RUNNING, T_DONE, T_FAILED, T_STOPPED)

# 结局的类别 -> 带这类结局的任务是什么状态
#   ok          算出来了。再启动时不重排，进数据
#   conclusion  结论：这个点就是这个结果，再算也一样。不重排，进数据并带结局名
#   retryable   可重试：和点无关的偶发问题。再启动时自动重排，不进数据
#   unclear     待查：说不清，先当失败。你点名才重排，不进数据
OK, CONCLUSION, RETRYABLE, UNCLEAR = "ok", "conclusion", "retryable", "unclear"
CATEGORIES = {OK: T_DONE, CONCLUSION: T_DONE, RETRYABLE: T_FAILED, UNCLEAR: T_FAILED}

# 只用于显示
LABELS = {
    NONE: "还没新建", NEW: "未启动", STARTING: "启动中", RUNNING: "运行中", ENDED: "已结束",
    DONE: "做完", FAILED: "失败", STOPPED: "停止", START_FAILED: "启动失败",
}


# ---------------------------------------------------------------- 状态表

@dataclass(frozen=True)
class Rule:
    write: str                  # 条目的写法，见 variant
    op: str                     # 它属于哪个操作
    states: tuple[str, ...]     # 什么状态时能记
    cond: str | None            # 另加的条件，对应 _CONDITIONS 里的名字
    then: str | None            # 记完的状态；None 是不变


_LIVE = (STARTING, RUNNING)

# 表里没有的组合一律拒绝
TABLE = (
    #    写法                          操作            什么状态时能记    另加的条件       记完的状态
    Rule("created",                   "create",       (NONE,),         None,           NEW),
    Rule("filled",                    "fill",         (NEW,),          "fill",         None),
    Rule("frozen",                    "start",        (NEW,),          "freeze",       None),
    Rule("round_opened",              "start",        (NEW, ENDED),    "open",         STARTING),
    Rule("called:start:ok",           "start_ok",     (STARTING,),     "first_call",   RUNNING),
    Rule("called:start:error",        "start_error",  (STARTING,),     "first_call",   None),
    Rule("round_closed:start_failed", "start_error",  (STARTING,),     "start_erred",  ENDED),
    Rule("called:stop:ok",            "stop",         (RUNNING,),      "in_round",     None),
    Rule("round_closed:stopped",      "stop",         (RUNNING,),      "stop_called",  ENDED),
    Rule("round_closed:done",         "finish",       (RUNNING,),      "in_round",     ENDED),
    Rule("round_closed:failed",       "fail",         (RUNNING,),      "in_round",     ENDED),
    Rule("task",                      "report",       _LIVE,           "task",         None),     # 结束了的不退回、不改，见 _task_ok
    Rule("output",                    "report",       _LIVE,           "output",       None),
    Rule("problem",                   "report",       _LIVE,           "in_round",     None),
    Rule("provenance",                "report",       _LIVE,           "in_round",     None),
    Rule("noted",                     "note",         STATES,          None,           None),
    Rule("tagged",                    "tag",          STATES,          None,           None),
)

# 不往这个实验的记录里写的两个操作：轮询只叫插件；克隆写的是另一个实验
SILENT = {"poll": (RUNNING,), "clone": STATES}

_RULES = {rule.write: rule for rule in TABLE}
OPERATIONS = tuple(dict.fromkeys([rule.op for rule in TABLE] + list(SILENT)))


def variant(entry: dict) -> str:
    """一条条目的写法。called 和 round_closed 按内容再细分，别的就是条目名。"""
    name = entry.get("entry")
    if name == "called":
        return f"called:{entry.get('action')}:{'ok' if entry.get('ok') is True else 'error'}"
    if name == "round_closed":
        return f"round_closed:{entry.get('result')}"
    return str(name)


# ---------------------------------------------------------------- 现状

@dataclass
class Task:
    name: str
    state: str
    outcome: str | None
    stage: str | None
    machine: str | None
    fingerprint: str | None
    round: int                  # 这个状态是哪一轮报的
    time: str


@dataclass
class Round:
    number: int
    opened: str
    provenance: dict            # 这一轮的来历
    rerun: list                 # 这一轮要重排的任务
    calls: list = field(default_factory=list)       # 叫插件启动、停止的结果：action、ok、error、time
    tasks: dict = field(default_factory=dict)       # 这一轮报过的任务，各取最后一次
    outputs: dict = field(default_factory=dict)     # 产物名 -> {"item", "hash"}
    problems: list = field(default_factory=list)    # error、task、raw、count、time
    extra: list = field(default_factory=list)       # 后补的来历：source、info、time
    result: str | None = None
    reason: str | None = None
    closed: str | None = None


@dataclass
class Status:
    state: str = NONE
    type: str = ""
    inputs: list = field(default_factory=list)      # 输入表、产物表、结局表：新建时从类型抄下的
    outputs: list = field(default_factory=list)
    outcomes: list = field(default_factory=list)
    note: str = ""
    tags: list = field(default_factory=list)
    notes: list = field(default_factory=list)       # text、time
    clone_of: str | None = None
    created: str | None = None
    filled: dict = field(default_factory=dict)      # 输入名 -> 登记编号的列表，以后一次填的为准
    frozen: dict | None = None                      # 存定的输入：输入名 -> 每样的编号、种类、版本、哈希、来路
    register_head: dict | None = None               # 存定时登记链的链头
    rounds: list = field(default_factory=list)
    tasks: dict = field(default_factory=dict)       # 每个任务跨轮取最后一次
    count: int = 0                                  # 重放了几条


def recorded_code(current: Round) -> str:
    """这一轮的记录说现在该跑的是哪一份插件代码：开轮时记的那份，或者中途最后一次记下的变化。

    2026-11-16 起一轮里不换代码，新的轮不再记中途的变化；以前的轮里记过的，照样认。
    """
    changes = [extra["info"]["plugin_hash"] for extra in current.extra if extra["source"] == "code"]
    return changes[-1] if changes else current.provenance["plugin_hash"]


def fold(entries) -> Status:
    """由记录重放出现状。同一串条目重放几遍结果都相同。"""
    status = Status()
    for entry in entries:
        advance(status, entry)
    return status


def advance(status: Status, entry: dict) -> None:
    """把一条条目算进现状里。fold 就是从空的现状起一条一条地算。"""
    rule = _RULES.get(variant(entry))
    if rule is None:
        raise ValueError(f"状态表里没有这种写法：{variant(entry)}")
    _APPLY[entry["entry"]](status, entry)
    if rule.then is not None:
        status.state = rule.then
    status.count += 1


def _current(status: Status, entry: dict) -> Round:
    if not status.rounds:
        raise ValueError(f"还没开轮就出现了 {entry['entry']}")
    return status.rounds[-1]


def _created(status, entry):
    status.type, status.note, status.created = entry["type"], entry["note"], entry["time"]
    status.inputs, status.outputs, status.outcomes = entry["inputs"], entry["outputs"], entry["outcomes"]
    status.tags, status.clone_of = list(entry["tags"]), entry.get("clone_of")


def _filled(status, entry):
    if entry["items"]:
        status.filled[entry["input"]] = list(entry["items"])
    else:
        status.filled.pop(entry["input"], None)


def _frozen(status, entry):
    status.frozen, status.register_head = entry["inputs"], entry["register_head"]


def _round_opened(status, entry):
    status.rounds.append(Round(entry["round"], entry["time"], entry["provenance"], list(entry["rerun"])))


def _called(status, entry):
    call = {"action": entry["action"], "ok": entry["ok"], "error": entry["error"], "time": entry["time"]}
    _current(status, entry).calls.append(call)


def _task(status, entry):
    task = Task(entry["task"], entry["state"], entry["outcome"], entry["stage"], entry["machine"],
                entry["fingerprint"], entry["round"], entry["time"])
    _current(status, entry).tasks[task.name] = task
    status.tasks[task.name] = task


def _output(status, entry):
    _current(status, entry).outputs[entry["output"]] = {"item": entry["item"], "hash": entry["hash"]}


def _problem(status, entry):
    problems = _current(status, entry).problems
    if "count" in entry and problems and problems[-1]["error"] == entry["error"]:
        problems[-1]["count"] = entry["count"]      # 同一个报错连着出现只记一次，恢复时补上次数
        return
    problems.append({"error": entry["error"], "task": entry["task"], "raw": entry["raw"],
                     "count": entry.get("count", 1), "time": entry["time"]})


def _provenance(status, entry):
    extra = {"source": entry["source"], "info": entry["info"], "time": entry["time"]}
    _current(status, entry).extra.append(extra)


def _round_closed(status, entry):
    current = _current(status, entry)
    current.result, current.reason, current.closed = entry["result"], entry["reason"], entry["time"]


def _noted(status, entry):
    status.notes.append({"text": entry["text"], "time": entry["time"]})


def _tagged(status, entry):
    for tag in entry["add"]:
        if tag not in status.tags:
            status.tags.append(tag)
    status.tags = [tag for tag in status.tags if tag not in entry["remove"]]


_APPLY = {
    "created": _created, "filled": _filled, "frozen": _frozen, "round_opened": _round_opened,
    "called": _called, "task": _task, "output": _output, "problem": _problem,
    "provenance": _provenance, "round_closed": _round_closed, "noted": _noted, "tagged": _tagged,
}


# ---------------------------------------------------------------- 能不能

def rerunnable(status: Status, outcomes, named=()) -> list[str]:
    """再启动时可以重排的任务。

    没做完的（排队、运行、停止）和失败而结局属于可重试的自动重排；
    失败而结局属于待查的，点了名才重排。算出来了的和结论不重排。
    """
    category = {row["name"]: row["category"] for row in outcomes}
    picked = []
    for name, task in status.tasks.items():
        if task.state in (T_QUEUED, T_RUNNING, T_STOPPED):
            picked.append(name)
        elif task.state == T_FAILED:
            kind = category.get(task.outcome)
            if kind == RETRYABLE or (kind == UNCLEAR and name in named):
                picked.append(name)
    return picked


def why_not(op: str, status: Status, actions=(), named=()) -> str | None:
    """一个操作此刻为什么不能做。能做返回 None。

    actions 是这个类型写了的动作；named 是启动时你点名要重排的任务。
    """
    if op not in OPERATIONS:
        raise ValueError(f"没有这个操作：{op}")
    states = SILENT.get(op) or tuple(s for rule in TABLE if rule.op == op for s in rule.states)
    if status.state not in states:
        return f"现在是“{LABELS[status.state]}”，不能做 {op}"
    if op == "fill" and status.frozen is not None:
        return "输入已经存定，不能再填"
    if op == "stop" and "stop" not in actions:
        return "这个类型没有写停止，它自己会结束"
    if op == "start" and status.state == ENDED:
        if status.rounds[-1].result == DONE and not rerunnable(status, status.outcomes, named):
            return "上一轮已经做完，也没有可以重排的任务"
    return None


def can(op: str, status: Status, actions=(), named=()) -> bool:
    """一个操作此刻能不能做。"""
    return why_not(op, status, actions, named) is None


def refuse(status: Status, entry: dict) -> str | None:
    """一条条目此刻为什么不能记。能记返回 None。条目自己长得对不对，先问 entries.check_entry。"""
    name = variant(entry)
    rule = _RULES.get(name)
    if rule is None:
        return f"状态表里没有这种写法：{name}"
    if status.state not in rule.states:
        return f"现在是“{LABELS[status.state]}”，不能记 {name}"
    return _CONDITIONS[rule.cond](status, entry) if rule.cond else None


def _row(table, name):
    return next((row for row in table if row["name"] == name), None)


def _in_round(status, entry):
    if not status.rounds or entry["round"] != status.rounds[-1].number:
        now = status.rounds[-1].number if status.rounds else "还没开"
        return f"轮号不对：现在是第 {now} 轮，条目写的是第 {entry['round']} 轮"
    return None


def _fill(status, entry):
    if status.frozen is not None:
        return "输入已经存定，不能再填"
    row = _row(status.inputs, entry["input"])
    if row is None:
        return f"这个类型没有叫 {entry['input']} 的输入"
    if not row["many"] and len(entry["items"]) > 1:
        return f"输入 {entry['input']} 只收一份"
    return None


def _freeze(status, entry):
    if status.frozen is not None:
        return "输入已经存定过了"
    if set(entry["inputs"]) != {row["name"] for row in status.inputs}:
        return "存定的输入和输入表对不上"
    for name, listed in entry["inputs"].items():
        if [info["id"] for info in listed] != status.filled.get(name, []):
            return f"存定的 {name} 和现在填的不一样：核对之后它又被填过，重新启动一次"
    return None


def _open(status, entry):
    if entry["round"] != len(status.rounds) + 1:
        return f"轮号必须接着上一轮：该是第 {len(status.rounds) + 1} 轮"
    if status.frozen is None:
        return "还没存定输入"
    if status.rounds and status.rounds[-1].result == DONE and not entry["rerun"]:
        return "上一轮已经做完，也没有可以重排的任务"
    done = [name for name in entry["rerun"] if name in status.tasks and status.tasks[name].state == T_DONE]
    if done:
        return f"这几个任务已经做完，不重排：{done}。做完的不再做一遍；要重算，就新建一个实验（比如克隆这一个）"
    return None


def _first_call(status, entry):
    why = _in_round(status, entry)
    if why:
        return why
    return "这一轮的启动已经记过结果了" if status.rounds[-1].calls else None


def _start_erred(status, entry):
    why = _in_round(status, entry)
    if why:
        return why
    calls = status.rounds[-1].calls
    erred = bool(calls) and calls[-1]["action"] == "start" and not calls[-1]["ok"]
    return None if erred else "要先记下启动出错，才能记启动失败"


def _stop_called(status, entry):
    why = _in_round(status, entry)
    if why:
        return why
    calls = status.rounds[-1].calls
    stopped = bool(calls) and calls[-1]["action"] == "stop" and calls[-1]["ok"]
    return None if stopped else "插件停成了才能记停止"


_ENDS = (T_DONE, T_FAILED, T_STOPPED)
# 一个任务在一轮里结束之后，除了状态和结局，这几样也定了：同样的话再报一次可以，改不了。
# 结束之后还能变的只有阶段（stage），它只给人看
_SETTLED = (("fingerprint", "输入指纹"), ("machine", "机器"))


def _task_ok(status, entry):
    why = _in_round(status, entry)
    if why:
        return why
    current, name = status.rounds[-1], entry["task"]
    mine, earlier = current.tasks.get(name), status.tasks.get(name)
    if mine is None and earlier is not None and name not in current.rerun:
        return f"任务 {name} 在第 {earlier.round} 轮报过，这一轮没有排它重来：要重来，启动时把它排进重排"
    if mine is not None and mine.state in _ENDS:
        if (entry["state"], entry["outcome"]) != (mine.state, mine.outcome):
            return (f"任务 {name} 这一轮已经是“{mine.state}”（{mine.outcome or '没有结局'}），"
                    f"不能再改成“{entry['state']}”：同一轮里结束了的任务不退回，要重来就走新的一轮")
        changed = [label for key, label in _SETTLED if entry[key] != getattr(mine, key)]
        if changed:
            return (f"任务 {name} 这一轮已经是“{mine.state}”（{mine.outcome or '没有结局'}），它的{'、'.join(changed)}不能再改："
                    f"同一轮里结束了的任务不退回、不改，要重来就走新的一轮")
    if entry["outcome"] is None:
        return None
    row = _row(status.outcomes, entry["outcome"])
    if row is None:
        return f"结局表里没有 {entry['outcome']}"
    if CATEGORIES[row["category"]] != entry["state"]:
        return f"结局 {row['name']} 属于 {row['category']}，任务状态应该是 {CATEGORIES[row['category']]}"
    return None


def _output_ok(status, entry):
    why = _in_round(status, entry)
    if why:
        return why
    if _row(status.outputs, entry["output"]) is None:
        return f"产物表里没有 {entry['output']}"
    if entry["output"] in status.rounds[-1].outputs:
        return f"这一轮已经交过 {entry['output']}"
    return None


_CONDITIONS = {
    "fill": _fill, "freeze": _freeze, "open": _open, "in_round": _in_round, "first_call": _first_call,
    "start_erred": _start_erred, "stop_called": _stop_called, "task": _task_ok, "output": _output_ok,
}
