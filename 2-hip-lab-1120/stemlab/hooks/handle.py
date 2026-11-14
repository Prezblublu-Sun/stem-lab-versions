"""一次调用里插件能做的事。接口的约定见 contract/plugin_api.py 里的 Handle。

Handle 能读能写；ReadOnly 是检查和图表拿到的那一份，写的那几个一叫就被拒。
handle 只在一次调用里有效：调用返回之后再用它，一样被拒。
"""
from __future__ import annotations

import copy
from pathlib import Path

from stemlab.contract import Refused, kinds, layout, plugin_api, states
from stemlab.experiments import log, view
from stemlab.hooks import publish, remote
from stemlab.registry import lookup, verify


def _registered(item_id: str) -> str | None:
    """这样东西是什么时候登记的。登记里找不到它（链丢了尾巴）就是 None：由核对去报，不在这里拦。"""
    try:
        return lookup.get(item_id)["time"]
    except LookupError:
        return None


class ReadOnly:
    """只读的那一份。"""

    def __init__(self, experiment: str, round_info: plugin_api.RoundInfo, table: list, frozen: dict):
        self.experiment = experiment
        self.round = round_info
        self.work_dir: Path = layout.work_dir(experiment)
        self.machines = remote.read_machines()
        self.said: tuple[str, str] | None = None        # 插件说做完或做不下去。这次调用返回之后才生效
        self._table = {row["name"]: row for row in table}                       # 输入表
        # 给插件的是抄出来的一份：它拿去改了，也改不到核心读记录时留在内存里的那一份
        self._inputs = {name: [plugin_api.InputInfo(**copy.deepcopy(info), time=_registered(info["id"])) for info in listed]
                        for name, listed in frozen.items()}
        self._verified: set[str] = set()
        self._open = True

    def close(self) -> None:
        self._open = False

    def _use(self) -> None:
        if not self._open:
            raise Refused("这次调用已经结束，handle 不能再用")

    def _allow_write(self) -> None:
        self._use()
        raise Refused("这次调用是只读的，不能往记录里写")

    def _append(self, body: dict) -> None:
        self._allow_write()
        log.append(self.experiment, dict(body, round=self.round.number))

    def _row(self, name: str) -> dict:
        self._use()
        if name not in self._table:
            raise Refused(f"这个类型没有叫 {name} 的输入")
        return self._table[name]

    def _content(self, info: plugin_api.InputInfo):
        if lookup.get(info.id)["storage"] == kinds.STORE_REF:
            return self.verified(info)              # 只记位置的先再核一次哈希；对不上就不交出内容
        return lookup.content(info.id)

    # ---- 给挂点里别的文件用的，不在插件的接口里 ----

    def find_input(self, item_id: str) -> plugin_api.InputInfo | None:
        """这个实验存定的输入里，编号是 item_id 的那一样。没有就是 None。"""
        return next((info for listed in self._inputs.values() for info in listed if info.id == item_id), None)

    def verified(self, info: plugin_api.InputInfo):
        """一样输入的内容，交出去之前核一次哈希。一次调用里同一样只核一次。"""
        if info.id not in self._verified:
            verify.verify_item(info.id)
            self._verified.add(info.id)
        return lookup.content(info.id)

    # ---- 读 ----

    def input(self, name: str):
        row = self._row(name)
        contents = [self._content(info) for info in self._inputs.get(name, [])]
        return contents if row["many"] else (contents[0] if contents else None)

    def input_info(self, name: str):
        row = self._row(name)
        listed = list(self._inputs.get(name, []))
        return listed if row["many"] else (listed[0] if listed else None)

    def tasks(self) -> dict:
        self._use()
        return view.view(self.experiment).tasks

    # ---- 写 ----

    def task(self, task: str, state: str, outcome: str | None = None, stage: str | None = None,
             machine: str | None = None, fingerprint: str | None = None) -> None:
        self._append({"entry": "task", "task": task, "state": state, "outcome": outcome, "stage": stage,
                      "machine": machine, "fingerprint": fingerprint})

    def output(self, name: str, folder) -> str | None:
        self._allow_write()
        return publish.publish(self.experiment, self.round.number, name, Path(folder))

    def problem(self, error: str, task: str | None = None, raw: str | None = None) -> None:
        self._append({"entry": "problem", "error": str(error), "task": task, "raw": raw})

    def provenance(self, **info) -> None:
        self._append({"entry": "provenance", "source": "plugin", "info": info})

    def finish(self) -> None:
        self._allow_write()
        self.said = (states.DONE, "")

    def fail(self, reason: str) -> None:
        self._allow_write()
        self.said = (states.FAILED, str(reason))


class Handle(ReadOnly):
    """能读能写的那一份。启动、轮询、停止拿到的是它。"""

    def __init__(self, experiment: str, round_info: plugin_api.RoundInfo, table: list, frozen: dict):
        super().__init__(experiment, round_info, table, frozen)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def _allow_write(self) -> None:
        self._use()
