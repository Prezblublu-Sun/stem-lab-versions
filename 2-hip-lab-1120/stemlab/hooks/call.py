"""唯一叫插件代码的地方。

    call(类型, 动作, 实验)     叫启动、轮询、停止。出错不往外抛，记成这个实验的问题
    call_check(...)            叫检查。只读；不过就给原因，什么都不记
    call_chart(...)            取一张图的数据。只读；出错往外抛，由界面显示，不进记录

插件写得再糟，最坏的结果是这个实验多一条问题。同一个报错连着出现只记一次，不再出现时补记连着出现了几次。
叫插件代码的时候不拿链的锁：handle 的每次写都是拿了就放。

真正跑的代码必须就是这一轮记下的那一份：冻结文件变了不跑；这个进程里装着的不是记下的那一份也不跑
（报 load.Stale，由调用方重新起进程）。
"""
from __future__ import annotations

import copy
import traceback
from dataclasses import dataclass

from stemlab.contract import Refused, plugin_api, states
from stemlab.experiments import log, view
from stemlab.hooks import entry, handle, load


@dataclass
class Result:
    ok: bool                            # 动作有没有出错
    error: str | None = None            # 报错：类型和消息
    said: tuple | None = None           # 插件说的（结局, 原因）：做完，或者做不下去
    value: object = None                # 动作的返回值


# （实验, 轮）-> (正连着出现的报错, 次数)。只在这个进程里记，不落盘
_STREAK: dict[tuple[str, int], tuple[str, int]] = {}


def find(type_name: str) -> tuple[plugin_api.Kind, str]:
    """这个类型的 Kind，和它属于哪个插件。插件装不上就被拒，说出原因。"""
    loaded = load.load()
    if type_name in loaded.kinds:
        return loaded.kinds[type_name], loaded.owners[type_name]
    plugin = type_name.split(".")[0]
    raise Refused(f"类型 {type_name} 现在用不了：" + loaded.errors.get(plugin, f"没有找到插件 {plugin}，或者它没有报这个类型"))


def call(type_name: str, action: str, experiment: str) -> Result:
    """叫一次启动、轮询或停止。调用方要先拿着这个实验的 busy。"""
    status = view.view(experiment)
    current = status.rounds[-1]
    try:
        kind, plugin = find(type_name)
        function = getattr(kind, action)
        if not callable(function):
            raise Refused(f"类型 {type_name} 没有写 {action}")
        if load.frozen_hash(plugin) != current.provenance["plugin_frozen"]:
            raise Refused("插件的冻结文件和这一轮开始时不一样了，这一轮不能接着跑：把冻结文件改回去，或者另开一个实验")
        if load.imported(plugin) != states.recorded_code(current):
            raise load.Stale("这个进程里装着的插件代码，不是这一轮记下的那一份。重新起这个进程再来")
        info = plugin_api.RoundInfo(current.number, tuple(current.rerun), copy.deepcopy(current.provenance), current.opened)
        given = handle.Handle(experiment, info, status.inputs, status.frozen)
    except load.Stale:
        raise
    except (Refused, ValueError) as error:          # ValueError：机器清单读不出来之类
        return _failed(experiment, current.number, str(error))
    try:
        value = entry.call_with(given, function)
    except (Exception, SystemExit) as error:  # noqa: BLE001  插件抛什么都接住
        return _failed(experiment, current.number, f"{type(error).__name__}: {error}", traceback.format_exc())
    finally:
        given.close()
    _recovered(experiment, current.number)
    return Result(True, said=given.said, value=value)


def _failed(experiment: str, number: int, error: str, raw: str | None = None) -> Result:
    error = error.strip() or "出错了，但没有说是什么"
    streak = _STREAK.get((experiment, number))
    if streak and streak[0] == error:
        _STREAK[experiment, number] = (error, streak[1] + 1)        # 同一个报错连着出现：不再记，只数次数
    else:
        _recovered(experiment, number)                              # 换了一个报错：上一个连着出现的次数先补上
        log.append(experiment, {"entry": "problem", "round": number, "error": error, "task": None, "raw": raw})
        _STREAK[experiment, number] = (error, 1)
    return Result(False, error)


def _recovered(experiment: str, number: int) -> None:
    streak = _STREAK.pop((experiment, number), None)
    if streak and streak[1] > 1:
        log.append(experiment, {"entry": "problem", "round": number, "error": streak[0], "task": None,
                                "raw": None, "count": streak[1]})


def call_check(type_name: str, experiment: str, table: list, frozen: dict, info: plugin_api.RoundInfo) -> str | None:
    """叫插件的检查（启动的第 5 步）。过了返回 None，不过返回原因。

    这时 frozen 和 round_opened 都还没记，所以输入和轮的信息由调用方把手上算好的那一份给进来。
    """
    try:
        kind, _ = find(type_name)
        given = handle.ReadOnly(experiment, info, table, frozen)
    except (Refused, ValueError) as error:
        return str(error)
    try:
        verdict = kind.check(given)
    except (Exception, SystemExit) as error:  # noqa: BLE001
        return f"检查出错：{type(error).__name__}: {error}"
    finally:
        given.close()
    if verdict is None:
        return None
    return verdict if isinstance(verdict, str) and verdict.strip() else "检查没过，但没有说原因（check 该返回 None 或原因）"


def call_chart(type_name: str, experiment: str, name: str):
    """取一张图的数据。出错往外抛，由界面显示；不进记录。"""
    kind, _ = find(type_name)
    if name not in [chart.name for chart in kind.charts]:
        raise Refused(f"类型 {type_name} 没有叫 {name} 的图")
    status = view.view(experiment)
    last = status.rounds[-1] if status.rounds else None
    info = plugin_api.RoundInfo(last.number if last else 0, tuple(last.rerun) if last else (),
                                copy.deepcopy(last.provenance) if last else {}, last.opened if last else None)
    given = handle.ReadOnly(experiment, info, status.inputs, status.frozen or {})
    try:
        return kind.chart(given, name)
    finally:
        given.close()
