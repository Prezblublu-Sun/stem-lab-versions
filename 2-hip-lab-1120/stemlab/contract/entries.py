"""实验记录的条目。一个实验一份只追加的记录，一共十二种条目。

每条都带：格式版本 format、时间 time、条目名 entry，和链填的 seq、prev、this。
开轮之后属于某一轮的七种还带轮号 round。
check_entry 只看一条自己长得对不对；它此刻能不能记，问 states.refuse。

文件末尾还有两条小链的条目：发号（issued.jsonl）和手动挂接（links.jsonl）。
"""
from __future__ import annotations

from stemlab.contract.chain import is_time
from stemlab.contract.hashing import is_hash
from stemlab.contract.kinds import ITEM_KINDS, VALUE
from stemlab.contract.layout import is_experiment_id, is_item_id, is_key, is_label, is_type_name
from stemlab.contract.origin import check_origin
from stemlab.contract.states import CATEGORIES, RESULTS, T_DONE, T_FAILED, TASK_STATES
from stemlab.contract.versions import FORMATS

_TEXT = (str,)
_MAYBE = (str, type(None))
_INT = (int,)
_BOOL = (bool,)
_LIST = (list,)
_DICT = (dict,)

COMMON = {"format": _INT, "time": _TEXT, "entry": _TEXT}        # 每条都带的
CHAIN = {"seq": _INT, "prev": _TEXT, "this": _TEXT}             # 链填的

# 条目 -> (必填项, 可选项)。必填项可以是 null 的也要写出来
ENTRIES = {
    # 新建。把输入表、产物表、结局表抄进来，插件拔掉或改了之后旧实验照样读得懂
    "created": ({"type": _TEXT, "inputs": _LIST, "outputs": _LIST, "outcomes": _LIST,
                 "note": _TEXT, "tags": _LIST}, {"clone_of": _TEXT}),
    # 填一样输入。items 是登记编号的列表；空列表是把这样输入清掉
    "filled": ({"input": _TEXT, "items": _LIST}, {}),
    # 第一次启动：存定每样输入，记下登记链当时的链头
    "frozen": ({"inputs": _DICT, "register_head": _DICT}, {}),
    # 每次启动：轮号、这一轮的来历、要重排的任务
    "round_opened": ({"round": _INT, "provenance": _DICT, "rerun": _LIST}, {}),
    # 叫完插件的启动或停止：哪个动作，成了还是出错
    "called": ({"round": _INT, "action": _TEXT, "ok": _BOOL, "error": _MAYBE}, {}),
    # 任务的状态变了
    "task": ({"round": _INT, "task": _TEXT, "state": _TEXT, "outcome": _MAYBE, "stage": _MAYBE,
              "machine": _MAYBE, "fingerprint": _MAYBE}, {}),
    # 发布了一样产物
    "output": ({"round": _INT, "output": _TEXT, "item": _TEXT, "hash": _TEXT}, {}),
    # 出了问题。同一个报错连着出现只记一次；不再出现时补一条带 count 的，写明连着出现了几次
    "problem": ({"round": _INT, "error": _TEXT, "task": _MAYBE, "raw": _MAYBE}, {"count": _INT}),
    # 插件、远端或带代码的包补来历
    "provenance": ({"round": _INT, "source": _TEXT, "info": _DICT}, {}),
    # 一轮结束：结局和原因
    "round_closed": ({"round": _INT, "result": _TEXT, "reason": _TEXT}, {}),
    # 备注；标签的增减
    "noted": ({"text": _TEXT}, {}),
    "tagged": ({"add": _LIST, "remove": _LIST}, {}),
}

# 每一轮必记的来历（本机）。由核心记，不靠插件自己报
ROUND_PROVENANCE = {
    "commit": _TEXT,            # 核心的提交号
    "clean": _BOOL,             # 契约和核心是否干净
    "frozen": _TEXT,            # FROZEN 清单的哈希
    "plugin": _TEXT,            # 这个类型属于哪个插件
    "plugin_hash": _TEXT,       # 插件文件夹的哈希
    "plugin_frozen": _TEXT,     # 这个插件冻结文件的哈希，输入指纹用它
    "plugin_dirty": _BOOL,      # 插件有没有没提交的改动；有的话差异存在这一轮的 plugin.diff
    "contract": _INT,           # 契约版本
    "python": _TEXT,            # Python 版本
    "lock": _TEXT,              # 锁文件的哈希
    "host": _TEXT,              # 主机名
}

# 后补的来历：谁补的 -> 必带哪几项
PROVENANCE_SOURCES = {
    "remote": ("host", "python", "libs", "cuda", "driver", "gpu"),     # 在远端跑的轮，取回时由核心记
    "package": ("id", "hash"),                                          # 用到带代码的包时由核心记
    # 这一轮中途插件自由的代码变了，由核心记：新的文件夹哈希、当时的提交号、有没有没提交的改动。
    # 有的话，差异存在这一轮的 plugin-<哈希的前 12 位>.diff
    "code": ("plugin_hash", "commit", "plugin_dirty"),
    "plugin": (),                                                       # 插件自己补的，比如求解器版本
}

_FROZEN_INFO = ("id", "kind", "name", "version", "hash", "origin", "bone_id")


def _is(value, kinds) -> bool:
    if isinstance(value, bool):
        return bool in kinds
    return isinstance(value, kinds)


def _shape(title: str, obj: dict, required: dict, optional: dict) -> list[str]:
    problems = [f"{title} 缺 {key}" for key in required if key not in obj]
    known = {**required, **optional}
    problems += [f"{title} 多了 {key}" for key in obj if key not in known]
    problems += [f"{title} 的 {key} 类型不对：{obj[key]!r}"
                 for key, kinds in known.items() if key in obj and not _is(obj[key], kinds)]
    return problems


def is_tag(text) -> bool:
    """标签：一到四十个字符，不带空白。可以用中文。"""
    return isinstance(text, str) and 0 < len(text) <= 40 and not any(ch.isspace() for ch in text)


def check_entry(entry) -> list[str]:
    """核对一条条目自己长得对不对。返回哪里不符；空列表就是对的。"""
    if not isinstance(entry, dict):
        return ["一条必须是一个 JSON 对象"]
    name = entry.get("entry")
    if name not in ENTRIES:
        return [f"十二种条目里没有 {name!r}"]
    required, optional = ENTRIES[name]
    problems = _shape(name, entry, {**COMMON, **required}, {**optional, **CHAIN})
    if problems:
        return problems
    if entry["format"] != FORMATS["record"]:
        problems.append(f"{name} 的格式版本是 {entry['format']}，现在是 {FORMATS['record']}")
    if not is_time(entry["time"]):
        problems.append(f"{name} 的 time 不是规定的写法：{entry['time']!r}")
    if "round" in entry and entry["round"] < 1:
        problems.append(f"{name} 的轮号必须从 1 起：{entry['round']}")
    return problems + _DEEP[name](entry)


# ---------------------------------------------------------------- 各种条目里面的规矩

def check_tables(inputs, outputs, outcomes) -> list[str]:
    """核对一个类型的输入表、产物表、结局表。"""
    problems = _rows("输入表", inputs, {"name": _TEXT, "kinds": _LIST, "many": _BOOL, "required": _BOOL, "label": _TEXT})
    problems += _rows("产物表", outputs, {"name": _TEXT, "kind": _TEXT, "label": _TEXT})
    problems += _rows("结局表", outcomes, {"name": _TEXT, "category": _TEXT, "label": _TEXT})
    if problems:
        return problems
    for row in inputs:
        if not row["kinds"] or any(kind not in ITEM_KINDS for kind in row["kinds"]):
            problems.append(f"输入 {row['name']} 收的种类不对：{row['kinds']}")
    for row in outputs:
        if row["kind"] not in ITEM_KINDS:
            problems.append(f"产物 {row['name']} 的种类不对：{row['kind']!r}")
        elif ITEM_KINDS[row["kind"]].form == VALUE:
            problems.append(f"产物 {row['name']} 不能是一个值，产物都是文件夹")
    for row in outcomes:
        if row["category"] not in CATEGORIES:
            problems.append(f"结局 {row['name']} 的类别不对：{row['category']!r}")
    if not outcomes:
        problems.append("结局表不能是空的")
    return problems


def _rows(title: str, rows: list, spec: dict) -> list[str]:
    problems, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            problems.append(f"{title}里有一行不是 JSON 对象")
            continue
        found = _shape(f"{title}的一行", row, spec, {})
        if not found and not is_key(row["name"]):
            found = [f"{title}里的名字要用小写字母、数字和下划线：{row['name']!r}"]
        if not found and row["name"] in seen:
            found = [f"{title}里 {row['name']} 重复了"]
        problems += found
        seen.add(row.get("name"))
    return problems


def _created(entry):
    problems = [] if is_type_name(entry["type"]) else [f"类型名要写成“插件.类型”：{entry['type']!r}"]
    problems += check_tables(entry["inputs"], entry["outputs"], entry["outcomes"])
    problems += [f"标签不对：{tag!r}" for tag in entry["tags"] if not is_tag(tag)]
    if "clone_of" in entry and not is_experiment_id(entry["clone_of"]):
        problems.append(f"clone_of 不是实验的编号：{entry['clone_of']!r}")
    return problems


def _filled(entry):
    problems = [] if is_key(entry["input"]) else [f"不是一个输入名：{entry['input']!r}"]
    problems += [f"不是登记的编号：{item!r}" for item in entry["items"] if not is_item_id(item)]
    if len(set(map(str, entry["items"]))) != len(entry["items"]):
        problems.append("同一样东西填了两次")
    return problems


def _frozen(entry):
    problems = []
    for name, infos in entry["inputs"].items():
        if not is_key(name) or not isinstance(infos, list):
            problems.append(f"存定的输入 {name!r} 必须是一个列表")
            continue
        for info in infos:
            if not isinstance(info, dict) or set(info) != set(_FROZEN_INFO):
                problems.append(f"存定的输入 {name} 里每样要带且只带这几项：{list(_FROZEN_INFO)}")
            elif not (is_item_id(info["id"]) and info["kind"] in ITEM_KINDS and is_hash(info["hash"])
                      and not check_origin(info["origin"])):
                problems.append(f"存定的输入 {name} 里有一样的编号、种类、哈希或来路不对：{info.get('id')!r}")
    head = entry["register_head"]
    if set(head) != {"seq", "this"} or not _is(head.get("seq"), _INT) or not is_hash(head.get("this")):
        problems.append("register_head 要带登记链当时的 seq 和 this")
    return problems


def _round_opened(entry):
    problems = _shape("这一轮的来历", entry["provenance"], ROUND_PROVENANCE, {})
    problems += [f"要重排的任务名不对：{task!r}" for task in entry["rerun"] if not is_label(task)]
    if len(set(map(str, entry["rerun"]))) != len(entry["rerun"]):
        problems.append("要重排的任务里有重复的")
    return problems


def _called(entry):
    problems = [] if entry["action"] in ("start", "stop") else [f"called 只记启动和停止：{entry['action']!r}"]
    if entry["ok"] and entry["error"] is not None:
        problems.append("成了就不该带报错")
    if not entry["ok"] and not entry["error"]:
        problems.append("出错了要写报错")
    return problems


def _task(entry):
    problems = [] if is_label(entry["task"]) else [f"任务名不对：{entry['task']!r}"]
    if entry["state"] not in TASK_STATES:
        return problems + [f"任务的状态只有 {list(TASK_STATES)}：{entry['state']!r}"]
    ended = entry["state"] in (T_DONE, T_FAILED)
    if ended and not is_key(entry["outcome"]):
        problems.append("完成和失败都要带一个结局名")
    if not ended and entry["outcome"] is not None:
        problems.append(f"{entry['state']} 的任务还没有结局")
    if entry["fingerprint"] is not None and not is_hash(entry["fingerprint"]):
        problems.append("输入指纹必须是完整的哈希")
    return problems


def _output(entry):
    problems = [] if is_key(entry["output"]) else [f"不是一个产物名：{entry['output']!r}"]
    if not is_item_id(entry["item"]):
        problems.append(f"不是登记的编号：{entry['item']!r}")
    if not is_hash(entry["hash"]):
        problems.append("hash 必须是完整的 SHA-256")
    return problems


def _problem(entry):
    problems = [] if entry["error"].strip() else ["报错不能是空的"]
    if entry["task"] is not None and not is_label(entry["task"]):
        problems.append(f"任务名不对：{entry['task']!r}")
    if "count" in entry and entry["count"] < 2:
        problems.append("count 记的是连着出现的次数，至少是 2")
    return problems


def _provenance(entry):
    wanted = PROVENANCE_SOURCES.get(entry["source"])
    if wanted is None:
        return [f"补来历的只有 {list(PROVENANCE_SOURCES)}：{entry['source']!r}"]
    problems = [f"{entry['source']} 补的来历缺 {key}" for key in wanted if key not in entry["info"]]
    return problems if entry["info"] else problems + ["补的来历不能是空的"]


def _round_closed(entry):
    return [] if entry["result"] in RESULTS else [f"轮的结局只有 {list(RESULTS)}：{entry['result']!r}"]


def _noted(entry):
    return [] if entry["text"].strip() else ["备注不能是空的"]


def _tagged(entry):
    problems = [f"标签不对：{tag!r}" for tag in entry["add"] + entry["remove"] if not is_tag(tag)]
    return problems if entry["add"] or entry["remove"] else problems + ["没有要增减的标签"]


_DEEP = {
    "created": _created, "filled": _filled, "frozen": _frozen, "round_opened": _round_opened,
    "called": _called, "task": _task, "output": _output, "problem": _problem,
    "provenance": _provenance, "round_closed": _round_closed, "noted": _noted, "tagged": _tagged,
}


# ---------------------------------------------------------------- 另外两条小链

def check_issued(entry) -> list[str]:
    """发号链的一条：给哪个类型的实验发了哪个号。编号用过不再用。"""
    if not isinstance(entry, dict):
        return ["一条必须是一个 JSON 对象"]
    problems = _shape("issued", entry, {"format": _INT, "time": _TEXT, "id": _TEXT, "type": _TEXT}, CHAIN)
    if problems:
        return problems
    if not is_experiment_id(entry["id"]) or ("seq" in entry and int(entry["id"][1:]) != entry["seq"]):
        problems.append(f"实验的编号和它在发号链上的序号对不上：{entry['id']!r}")
    if not is_type_name(entry["type"]):
        problems.append(f"类型名要写成“插件.类型”：{entry['type']!r}")
    if not is_time(entry["time"]):
        problems.append(f"time 不是规定的写法：{entry['time']!r}")
    return problems


def check_link(entry) -> list[str]:
    """手动挂接的一条：把一样东西挂到某个 case 下面，或者摘下来。只影响在哪里看得到，不是来路。"""
    if not isinstance(entry, dict):
        return ["一条必须是一个 JSON 对象"]
    problems = _shape("links", entry, {"format": _INT, "time": _TEXT, "op": _TEXT, "item": _TEXT, "case": _TEXT}, CHAIN)
    if problems:
        return problems
    if entry["op"] not in ("attach", "detach"):
        problems.append(f"op 只有 attach 和 detach：{entry['op']!r}")
    if not is_item_id(entry["item"]):
        problems.append(f"不是登记的编号：{entry['item']!r}")
    if not is_item_id(entry["case"]) or not entry["case"].startswith("C"):
        problems.append(f"不是一个 case 的编号：{entry['case']!r}")
    if not is_time(entry["time"]):
        problems.append(f"time 不是规定的写法：{entry['time']!r}")
    return problems
