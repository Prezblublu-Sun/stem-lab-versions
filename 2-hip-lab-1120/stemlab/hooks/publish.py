"""发布一样产物的六步，和对账。

插件把算好的文件夹放在自己的 work/ 里，说一声“交这一样产物”。下面六步都由核心做，
每一步是一个可以重做的小函数，所以断在哪一步都接得上：

    1 产物名在这个类型的产物表里，种类相符       不过：拒绝，记成问题，文件留在原地      _in_table
    2 按契约核对清单                             不过：拒绝，记成问题，说出哪里不符      _fits_format
    3 移进 rounds/轮号/outputs/产物名/，算每个文件的哈希，刷到盘上                     _move、_hash、register.durable
    4 设成只读                                                                         _read_only
    5 登记。来路是这个实验的这一轮                                                     _register
    6 记一条 output                                                                    _record

先刷盘再登记：断电时，链上不会留下一条指向半截内容的记录。

对账（reconcile）把断在第 3 步之后的接着做完；做两遍和做一遍结果相同。
接着做的那一份还没登记的话，登记之前再按第 1、2 步核一遍：断开之后它还不是只读的，可能被动过，
也可能根本不是这里移进去的。没过就挪去 work/rejected/，记成问题，不登记。
已经登记、还没记 output 的那一份，补记之前核内容的哈希：只读挡得住程序，挡不住人。
对不上就不记 output，记成问题；登记的那一条不改，内容也留在原处（登记指着它），检查里的“登记的内容都在”会报它。
这一轮再交这样产物也不收。同一句问题一轮只记一次，所以对账做几遍都一样。
"""
from __future__ import annotations

from pathlib import Path

from stemlab.contract import Refused, hashing, kinds, layout, origin, states
from stemlab.contract.formats import manifest
from stemlab.experiments import log, view
from stemlab.registry import lookup, register


def publish(experiment: str, number: int, name: str, folder: Path) -> str | None:
    """发布这个实验这一轮的一样产物。返回登记的编号；没过就记成问题，返回 None，文件留在原地。"""
    status = view.view(experiment)
    if not states.can("report", status) or status.rounds[-1].number != number:
        raise Refused(f"{experiment} 现在不在第 {number} 轮里，不能交产物")
    folder = Path(folder)
    row = next((row for row in status.outputs if row["name"] == name), None)
    done = status.rounds[-1].outputs.get(name)
    if done is None and row is not None and layout.output_dir(experiment, number, name).exists():
        # 上次发布断在了第 3 步之后：文件已经移过来了，先把那一份接着做完。它没过再核，就当这次是头一回交
        item_id = _resume(experiment, number, row)
        if item_id is None and layout.output_dir(experiment, number, name).exists():
            # 登记了、内容却对不上：那一份挪不走（登记指着它），这样产物这一轮不再收
            return _reject_once(experiment, number, name, "这一轮登记过它，内容却和登记时的哈希对不上，这次交的也不收")
        done = {"item": item_id, "hash": lookup.get(item_id)["hash"]} if item_id else None
    if done is not None:
        # 插件在两次调用之间不留状态，断过之后会把同一样产物再交一次：内容一样就当已经交过，不算问题
        if not folder.exists() or _same(folder, done["hash"]):
            return done["item"]
        return _reject(experiment, number, name,
                       f"这一轮已经交过它了（{done['item']}），这次交的内容不一样，没有收。一样产物一轮只交一次")
    why = _in_table(experiment, row, name, folder) or _fits_format(status, row, folder)        # 1、2
    if why:
        return _reject(experiment, number, name, why)
    _move(folder, layout.output_dir(experiment, number, name))                                 # 3 的前一半
    return _resume(experiment, number, row, checked=True)                                      # 3 的后一半到 6


def _same(folder: Path, digest: str) -> bool:
    """这次交的文件夹，内容是不是和已经发布的那一份一样。"""
    try:
        return folder.is_dir() and hashing.hash_tree(folder) == digest
    except (OSError, ValueError):
        return False


def _reject(experiment: str, number: int, name: str, why: str) -> None:
    log.append(experiment, {"entry": "problem", "round": number, "error": f"产物 {name} 没有发布：{why}",
                            "task": None, "raw": None})
    return None


def _reject_once(experiment: str, number: int, name: str, why: str) -> None:
    """同 _reject，只是同一句问题这一轮已经记过就不再记：对账、重交做几遍，记录都和做一遍一样。"""
    error = f"产物 {name} 没有发布：{why}"
    rounds = [one for one in view.view(experiment).rounds if one.number == number]
    if rounds and any(problem.get("error") == error for problem in rounds[0].problems):
        return None
    return _reject(experiment, number, name, why)


# ---------------------------------------------------------------- 六步，一步一个函数

def _in_table(experiment: str, row: dict | None, name: str, folder: Path) -> str | None:
    """第 1 步：产物名在这个类型的产物表里，种类相符。过了返回 None，不过返回原因。

    交上来的得是这个实验 work/ 里的一个带清单的文件夹，清单写的种类就是产物表里的那一种。
    """
    if row is None:
        return f"产物表里没有 {name!r}"
    if not folder.is_dir() or layout.work_dir(experiment).resolve() not in folder.resolve().parents:
        return f"要交的文件夹必须在这个实验的 work/ 里：{folder}"
    return _kind(row, folder)


def _kind(row: dict, folder: Path) -> str | None:
    """第 1 步的后一半：文件夹带清单，清单写的种类就是产物表里的那一种。"""
    try:
        listed = manifest.read_manifest(folder)
    except ValueError as error:
        return str(error)
    if listed.get("kind") != row["kind"]:
        return f"种类不符：产物表里它是 {row['kind']}，清单写的是 {listed.get('kind')!r}"
    return None


def _fits_format(status: states.Status, row: dict, folder: Path) -> str | None:
    """第 2 步：按契约核对清单。过了返回 None，不过返回原因，说出哪里不符。

    登记时会拒的（骨标识不是从输入继承来的、case 没带骨标识）也在这里先看，免得文件移过去了却登记不上。
    """
    problems = manifest.check_format(row["kind"], folder)
    if problems:
        return f"不符合 {row['kind']} 的格式：" + "；".join(problems)
    bone = manifest.read_manifest(folder).get("bone_id")
    inherited = {info["bone_id"] for infos in status.frozen.values() for info in infos}
    if bone is not None and bone not in inherited:
        return f"骨标识 {bone!r} 不是从这个实验的输入继承来的"
    if bone is None and kinds.ITEM_KINDS[row["kind"]].case:
        return f"{row['kind']} 必须带骨标识，清单里没有"
    return None


def _move(folder: Path, target: Path) -> None:
    """第 3 步的前一半：移进 rounds/轮号/outputs/产物名/。改名带退避重试：文件正被别处读着的时候改不了名。"""
    register.rename(folder, target)


def _hash(target: Path) -> str:
    """第 3 步的后一半：算每个文件的哈希。文件已经在 outputs/ 里了，重算一遍结果相同。"""
    return hashing.hash_tree(target)


def _read_only(target: Path) -> None:
    """第 4 步：设成只读。已经是只读的再设一遍无妨。"""
    register.read_only(target)


def _registered(experiment: str, number: int, name: str) -> dict | None:
    """这样产物登记过没有。登记过就是那一条。"""
    return next((item for item in lookup.by_origin(experiment, number) if item["origin"]["output"] == name), None)


def _register(experiment: str, number: int, row: dict, target: Path, tree: str) -> dict:
    """第 5 步：登记。来路是这个实验的这一轮。"""
    return register.register_output(row["kind"], f"{experiment}.{row['name']}", layout.inside(target), tree,
                                    origin.product(experiment, number, row["name"]), manifest.read_manifest(target).get("bone_id"))


def _record(experiment: str, number: int, name: str, item: dict) -> str:
    """第 6 步：记一条 output。返回登记的编号。"""
    log.append(experiment, {"entry": "output", "round": number, "output": name, "item": item["id"], "hash": item["hash"]})
    return item["id"]


def _rejected(experiment: str, number: int, name: str) -> Path:
    """再核没过的那一份挪去的地方：work/rejected/产物名-r轮号，已经有了就往后加 -2、-3。"""
    base = layout.work_dir(experiment) / "rejected"
    base.mkdir(parents=True, exist_ok=True)
    target, count = base / f"{name}-r{number}", 1
    while target.exists():
        count += 1
        target = base / f"{name}-r{number}-{count}"
    return target


def _resume(experiment: str, number: int, row: dict, checked: bool = False) -> str | None:
    """文件已经在 outputs/ 里了：从第 3 步的后一半做到第 6 步。做到哪一步断的，就从哪一步接着做。

    还没登记的，登记之前再按第 1、2 步核一遍；刚核过、刚移过来的（checked）不用。
    没过：挪去 work/rejected/，记成问题，返回 None。
    登记了、还没记 output 的，补记之前核内容的哈希。对不上：不记 output，记成问题（一轮一次），返回 None。
    """
    name = row["name"]
    target = layout.output_dir(experiment, number, name)
    item = _registered(experiment, number, name)
    if item is None:                                    # 还没登记：断在了第 5 步之前
        why = None if checked else (_kind(row, target) or _fits_format(view.view(experiment), row, target))   # 1、2 再核一遍
        if why:
            moved = _rejected(experiment, number, name)
            _move(target, moved)
            return _reject(experiment, number, name, f"接着做发布之前再核了一遍，没过：{why}。挪去了 {layout.inside(moved)}")
        tree = _hash(target)                            # 3
        register.durable(target)                        # 3 的最后：刷到盘上，再登记
        _read_only(target)                              # 4
        item = _register(experiment, number, row, target, tree)                                # 5
    elif not _same(target, item["hash"]):               # 断在了第 5、6 步之间，断开的时候内容被动过
        return _reject_once(experiment, number, name,
                            f"登记了（{item['id']}），内容却和登记时的哈希对不上了，没有记 output。"
                            f"登记的那一条不改，内容留在 {layout.inside(target)}")
    return _record(experiment, number, name, item)                                             # 6


def reconcile(experiment: str) -> list[str]:
    """对账：这一轮里移过来了却没登记、或登记了却没记 output 的产物，接着做完。返回这次补做成了哪几样。"""
    status = view.view(experiment)
    if not states.can("report", status):
        return []
    current = status.rounds[-1]
    folder = layout.outputs_dir(experiment, current.number)
    present = sorted(path.name for path in folder.iterdir() if path.is_dir()) if folder.is_dir() else []
    done = []
    for row in status.outputs:
        if row["name"] in present and row["name"] not in current.outputs and _resume(experiment, current.number, row):
            done.append(row["name"])
    return done
