"""你的动作里不叫插件的那些：登记、挂接、新建、克隆、填输入、备注、标签。

每个动作要么做成，要么被拒（Refused，带着原因，什么都没写下）。
"""
from __future__ import annotations

import getpass
import tempfile
from pathlib import Path

from stemlab.contract import Refused, hashing, kinds, plugin_api, states
from stemlab.contract.formats import manifest, points
from stemlab.desk.core import locks
from stemlab.experiments import log, view
from stemlab.hooks import call
from stemlab.registry import links, lookup
from stemlab.registry import register as registry


WAIT = 30.0     # 别处正在动这个实验时，填输入最多等多少秒


def _status(experiment: str) -> states.Status:
    try:
        return view.view(experiment)
    except (LookupError, ValueError) as error:
        raise Refused(str(error)) from None


def _item(item_id: str) -> dict:
    try:
        return lookup.get(item_id)
    except LookupError as error:
        raise Refused(str(error)) from None


def register(kind: str, name: str, *, note: str, by: str | None = None, value=None, source=None,
             storage: str | None = None, bone_id: str | None = None, new_bone: bool = False,
             defaults: str | None = None) -> dict:
    """登记一样外面拿来的东西。by 不给就记当前的系统用户。

    手写的一批点可以用 defaults 指定一份条件默认（登记的编号）：核心补全条件之后再存。
    """
    by = by or getpass.getuser()
    if defaults is None:
        return registry.register_external(kind, name, note=note, by=by, value=value, source=source,
                                          storage=storage, bone_id=bone_id, new_bone=new_bone)
    if kind != "points" or storage not in (None, kinds.STORE_COPY):
        raise Refused("只有一批点能指定条件默认，而且补全之后只能复制着存")
    if _item(defaults)["kind"] != "setting":
        raise Refused(f"条件默认要是一份设定，{defaults} 是 {_item(defaults)['kind']}")
    try:
        rows = points.fill_defaults(points.read_points(source), lookup.content(defaults))
        with tempfile.TemporaryDirectory() as scratch:
            points.write_points(Path(scratch) / "points", rows)
            return registry.register_external(kind, name, note=f"{note}（条件默认用的是 {defaults}）", by=by,
                                              source=Path(scratch) / "points", bone_id=bone_id, new_bone=new_bone)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise Refused(f"这批点读不进来或补不全：{type(error).__name__}: {error}") from None


def write_manifest(folder, kind: str, bone_id: str | None = None) -> dict:
    """在一个文件夹里就地写一份共用格式的清单。只在你明说要写的时候做：给只记位置的东西登记之前用。"""
    if kind not in kinds.ITEM_KINDS or kinds.ITEM_KINDS[kind].format != "manifest":
        raise Refused(f"{kind} 的清单不是共用的那一种，不能这样生成")
    folder = Path(folder)
    if not folder.is_dir():
        raise Refused(f"不是文件夹：{folder}")
    files = [rel for rel in hashing.list_tree(folder) if rel != manifest.MANIFEST]
    written = manifest.make_manifest(kind, files, **({"bone_id": bone_id} if bone_id else {}))
    problems = manifest.check_manifest(kind, written)
    if problems:
        raise Refused("；".join(problems))
    manifest.write_manifest(folder, written)
    return written


def attach(item_id: str, case_id: str) -> dict:
    """把一样东西手动挂到一个 case 下面。只影响在哪里看得到，不是来路。"""
    return links.attach(item_id, case_id)


def detach(item_id: str, case_id: str) -> dict:
    return links.detach(item_id, case_id)


def new(type_name: str, note: str = "", tags=()) -> str:
    """新建一个实验，返回它的编号。这个类型的输入表、产物表、结局表在这时抄进记录。"""
    kind, _ = call.find(type_name)
    return log.create(type_name, plugin_api.tables(kind), note, tags)


def clone(experiment: str, note: str | None = None) -> str:
    """克隆：新建一个同类型的实验，输入逐样相同。旧实验一条不动。"""
    status = _status(experiment)
    kind, _ = call.find(status.type)
    tables = plugin_api.tables(kind)
    filled = ({name: [info["id"] for info in listed] for name, listed in status.frozen.items()}
              if status.frozen is not None else status.filled)
    filled = {name: ids for name, ids in filled.items() if ids}
    rows = {row["name"]: row for row in tables["inputs"]}
    wrong = [name for name, ids in filled.items() if name not in rows or (len(ids) > 1 and not rows[name]["many"])]
    if wrong:
        raise Refused(f"这个类型的输入表变过了，这几样输入填不回去：{wrong}")
    copy = log.create(status.type, tables, status.note if note is None else note, status.tags, clone_of=experiment)
    for name, ids in filled.items():
        log.append(copy, {"entry": "filled", "input": name, "items": ids})
    return copy


def fill(experiment: str, name: str, items) -> None:
    """填一样输入。items 是登记的编号；给空的就是把这样输入清掉。同一样输入再填，以后一次为准。"""
    items = [items] if isinstance(items, str) else list(items)
    with locks.busy(experiment, "fill", WAIT):          # 和启动不同时动：启动正在核对输入的时候不能换输入
        status = _status(experiment)
        why = states.why_not("fill", status)
        if why:
            raise Refused(why)
        row = next((row for row in status.inputs if row["name"] == name), None)
        if row is None:
            raise Refused(f"这个类型没有叫 {name} 的输入。它的输入是：{[row['name'] for row in status.inputs]}")
        wrong = [f"{item_id} 是 {_item(item_id)['kind']}" for item_id in items
                 if _item(item_id)["kind"] not in row["kinds"]]
        if wrong:
            raise Refused(f"输入 {name} 收的是 {row['kinds']}：" + "，".join(wrong))
        log.append(experiment, {"entry": "filled", "input": name, "items": items})


def fill_new(experiment: str, name: str, kind: str, item_name: str, **how) -> dict:
    """登记一样新东西，并把它填进这个实验的一样输入。how 是给 register 的其余参数。

    先看这样输入现在能不能填、收不收这个种类，再登记，免得白登记一样东西。
    """
    status = _status(experiment)
    why = states.why_not("fill", status)
    row = next((row for row in status.inputs if row["name"] == name), None)
    if why or row is None or kind not in row["kinds"]:
        raise Refused(why or f"输入 {name} 不收 {kind}，或者这个类型没有这样输入")
    item = register(kind, item_name, **how)
    fill(experiment, name, [item["id"]])
    return item


def note(experiment: str, text: str) -> None:
    """给一个实验加一条备注。随时可以。"""
    _status(experiment)
    log.append(experiment, {"entry": "noted", "text": text})


def tag(experiment: str, add=(), remove=()) -> None:
    """增减一个实验的标签。随时可以。"""
    _status(experiment)
    log.append(experiment, {"entry": "tagged", "add": list(add), "remove": list(remove)})
