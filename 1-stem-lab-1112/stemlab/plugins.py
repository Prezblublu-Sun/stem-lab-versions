"""挂点：一个插件要报的四样，以及怎么找到插件、怎么叫它。

插件 = 一种实际的操作模块。每个插件自己报：
  1. 名字、版本、类别
  2. 要哪几项设置
  3. 怎么启动、停止、报任务状态
  4. 产出什么

这个文件不认识任何具体的插件。插件之间互不调用；
一个的产出给另一个当设置，只经过实验记录。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from .record import Experiment, RecordError, sha256_path


@dataclass
class Setting:
    name: str
    required: bool = True
    what: str = ""


@dataclass
class Output:
    name: str
    what: str = ""


class Plugin:
    """插件继承它，填上四样。"""

    # 1. 名字、版本、类别。类别是插件自己报的词，只用来分组显示。
    name: str = ""
    version: str = ""
    category: str = ""
    what: str = ""

    # 2. 要哪几项设置
    settings: list[Setting] = []

    # 4. 产出什么
    outputs: list[Output] = []

    # 3. 怎么启动、停止、报任务状态
    def start(self, ctx: "Context") -> None:
        """启动。把任务报出来；可以马上返回，后面由 poll 接着报。"""
        raise NotImplementedError

    def poll(self, ctx: "Context") -> None:
        """看一眼任务走到哪了，有变化就报。全部做完时登记产出并叫 ctx.finish()。"""

    def stop(self, ctx: "Context") -> None:
        """停止。把还没结束的任务停掉并报出来。"""

    def pause(self, ctx: "Context") -> None:
        """暂停。暂停期间操作台不会叫 poll。"""

    def resume(self, ctx: "Context") -> None:
        """继续。"""

    def retry(self, ctx: "Context") -> None:
        """重试。设置不变，把失败的和停掉的任务重新排上。"""
        raise NotImplementedError


class Context:
    """插件拿到的东西。插件只能通过它读设置、往记录里写。"""

    def __init__(self, exp: Experiment):
        self._exp = exp
        self.id = exp.id
        self.outputs_dir = exp.outputs_dir
        self.private_dir = exp.folder / "plugin_state"

    def setting(self, name: str):
        """取一项设置。值就是值，文件就是路径。没填返回 None。"""
        return self._exp.setting_value(name)

    def tasks(self) -> dict:
        """现在每个任务的状态：{任务名: {"state":..., "stage":..., "machine":...}}"""
        return {
            k: {"state": t["state"], "stage": t["stage"], "machine": t["machine"]}
            for k, t in self._exp.view()["tasks"].items()
        }

    def task(self, task: str, state: str, stage: str = "", machine: str = "") -> None:
        self._exp.task(task, state, stage, machine)

    def output(self, name: str, path, what: str = "") -> None:
        self._exp.output(name, Path(path), what)

    def problem(self, error: str, task: str = "", raw: str = "") -> None:
        self._exp.problem(error, task, raw)

    def provenance(self, **items) -> None:
        self._exp.provenance(**items)

    def finish(self) -> None:
        self._exp.append("结束", {})


def describe(plugin: Plugin, folder: Path) -> dict:
    """写进实验记录的那一份：用的是哪个插件、哪一版。"""
    return {
        "name": plugin.name,
        "version": plugin.version,
        "category": plugin.category,
        "files_sha256": sha256_path(folder),
    }


HOOKS = {"start": "启动", "poll": "报任务状态", "stop": "停止", "pause": "暂停", "resume": "继续", "retry": "重试"}


def hooks_filled(plugin: Plugin) -> list[str]:
    """这个插件自己写了哪几个挂点（中文名）。没写的用的是空的默认。"""
    return [word for hook, word in HOOKS.items() if getattr(type(plugin), hook) is not getattr(Plugin, hook)]


def plugin_dirs(home: Path) -> list[Path]:
    dirs = [Path(home) / "plugins"]
    extra = os.environ.get("STEMLAB_PLUGINS", "")
    dirs += [Path(p) for p in extra.split(os.pathsep) if p]
    return dirs


def load_plugins(dirs: list[Path]) -> tuple[dict, list[str]]:
    """找到所有插件。返回 {名字: (插件, 文件夹)} 和装不上的插件的报错。

    一个插件装不上，不影响别的。
    """
    found: dict = {}
    errors: list[str] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for folder in sorted(p for p in d.iterdir() if (p / "plugin.py").is_file()):
            try:
                module_name = f"stemlab_plugin_{folder.name}"
                spec = importlib.util.spec_from_file_location(module_name, folder / "plugin.py")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                plugin = module.PLUGIN
                if not isinstance(plugin, Plugin) or not plugin.name:
                    raise RecordError("plugin.py 里要有一个 PLUGIN，是 Plugin 的子类的实例，并且有名字")
                if plugin.name in found:
                    raise RecordError(f"名字和 {found[plugin.name][1]} 里的插件重了")
                found[plugin.name] = (plugin, folder)
            except Exception as err:  # 出问题是正常的：记下来，接着装别的
                errors.append(f"{folder}：{type(err).__name__}: {err}")
    return found, errors


def call(plugin: Plugin, hook: str, exp: Experiment) -> bool:
    """叫插件的一个挂点。插件出错不往外抛：记成这个实验的一条问题。"""
    try:
        getattr(plugin, hook)(Context(exp))
        return True
    except Exception as err:
        exp.problem(
            error=f"插件 {plugin.name} 的 {hook} 出错：{type(err).__name__}: {err}",
            raw=traceback.format_exc(),
        )
        return False
