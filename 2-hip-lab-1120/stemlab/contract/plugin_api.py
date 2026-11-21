"""插件接口：一个类型报什么、四个动作的约定、一次调用里能做什么。

插件在自己的 plugin.py 里写 KINDS = [Kind(...), ...]，每个 Kind 是一种实验类型。
插件只交候选：算出文件交给核心，核对、算哈希、给编号、登记都由核心做。

四个动作（都必须很快返回；长时间的活放到脱离出去的本机进程或远端，下一次 poll 再去看）：
    check(handle)   启动的第 5 步。只读。过了返回 None，不过返回原因
    start(handle)   每一轮开头。把这一轮要跑的任务派出去就返回，不等它们跑完
    poll(handle)    值守每看一遍叫一次。报任务、交产物、报问题；都完了就说做完或做不下去。可以重复叫
    stop(handle)    你点停止。把在跑的停掉，已经算好的可以照常交。可以重复叫。可以不写
另有不算动作的 chart(handle, 图表名)：给界面一张图的数据，只读，出错只显示在页面上。

一个类型可以声明自己的设定（settings）：现在就是运行设定，只管怎么跑（求解槽、超时、归档放在哪），不影响算出来的数。
写法和包里的声明一样（formats/declaration.py）；照它写的设定，declaration 里的 of 写类型名，核心启动时照它核。
运行设定每个点都一样：声明里的项都不能是每个点给的。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from stemlab.contract.entries import check_tables
from stemlab.contract.formats.declaration import check_declaration
from stemlab.contract.layout import is_key, is_type_name

ACTIONS = ("check", "start", "poll", "stop")
REQUIRED_ACTIONS = ("check", "start", "poll")
CHART_FORMS = ("line", "scatter", "bar", "table", "image")      # 折线、散点、柱、表、图片
WHERE = ("desk", "worker")                                      # 在哪跑：操作台那台，或远端的 worker


@dataclass(frozen=True)
class Input:
    """输入表的一行。"""
    name: str
    kinds: tuple[str, ...]      # 收哪几种
    many: bool = False          # 收一份还是多份
    required: bool = True
    label: str = ""             # 中文名，只用于显示


@dataclass(frozen=True)
class Output:
    """产物表的一行。"""
    name: str
    kind: str
    label: str = ""


@dataclass(frozen=True)
class Outcome:
    """结局表的一行。category 是 ok、conclusion、retryable、unclear 之一。"""
    name: str
    category: str
    label: str = ""


@dataclass(frozen=True)
class Chart:
    """这个类型能给的一张图。画由界面统一画，插件只给数据。"""
    name: str
    form: str
    label: str = ""


@dataclass(frozen=True)
class Kind:
    """一种实验类型。输入表、产物表、结局表都是写死的；要不同的输入或产物，就是另一种类型。"""
    name: str                                       # 类型名，写成“插件.类型”
    inputs: tuple[Input, ...]
    outputs: tuple[Output, ...]
    outcomes: tuple[Outcome, ...]
    check: Callable[["Handle"], str | None]
    start: Callable[["Handle"], None]
    poll: Callable[["Handle"], None]
    stop: Callable[["Handle"], None] | None = None
    charts: tuple[Chart, ...] = ()
    chart: Callable[["Handle", str], Any] | None = None
    where: str = "desk"
    label: str = ""
    settings: tuple[dict, ...] = ()                 # 这种实验自己声明的设定（运行设定），写法见 formats/declaration.py


def declared(kind: Kind, name: str) -> dict | None:
    """这个类型声明的、叫这个名字的那份设定的声明。没有就是 None。"""
    found = [one for one in kind.settings if isinstance(one, dict) and one.get("name") == name]
    return found[0] if len(found) == 1 else None


def tables(kind: Kind) -> dict:
    """一个类型的三张表，写成抄进 created 的形状。"""
    return {
        "inputs": [{"name": row.name, "kinds": list(row.kinds), "many": row.many,
                    "required": row.required, "label": row.label} for row in kind.inputs],
        "outputs": [{"name": row.name, "kind": row.kind, "label": row.label} for row in kind.outputs],
        "outcomes": [{"name": row.name, "category": row.category, "label": row.label} for row in kind.outcomes],
    }


def actions(kind: Kind) -> tuple[str, ...]:
    """这个类型写了哪几个动作。"""
    return tuple(name for name in ACTIONS if callable(getattr(kind, name, None)))


def check_kind(kind) -> list[str]:
    """核对一个类型报的东西。返回哪里不符；空列表就是对的。"""
    if not isinstance(kind, Kind):
        return [f"KINDS 里的每一项必须是 Kind：{type(kind).__name__}"]
    if not is_type_name(kind.name):
        return [f"类型名要写成“插件.类型”：{kind.name!r}"]
    title = f"类型 {kind.name}"
    try:
        problems = [f"{title}：{text}" for text in check_tables(**tables(kind))]
    except (AttributeError, TypeError):
        return [f"{title}：三张表要分别用 Input、Output、Outcome 写"]
    problems += [f"{title}：没有写 {name}" for name in REQUIRED_ACTIONS if name not in actions(kind)]
    if kind.stop is not None and not callable(kind.stop):
        problems.append(f"{title}：stop 不是一个函数")
    if kind.where not in WHERE:
        problems.append(f"{title}：where 只有 {list(WHERE)}：{kind.where!r}")
    names = [chart.name for chart in kind.charts if isinstance(chart, Chart)]
    if len(names) != len(kind.charts) or len(set(names)) != len(names) or not all(map(is_key, names)):
        problems.append(f"{title}：图表要用 Chart 写，名字不重复")
    elif any(chart.form not in CHART_FORMS for chart in kind.charts):
        problems.append(f"{title}：图的种类只有 {list(CHART_FORMS)}")
    if kind.charts and not callable(kind.chart):
        problems.append(f"{title}：报了图表就要写 chart")
    return problems + _settings_problems(kind, title)


def _settings_problems(kind: Kind, title: str) -> list[str]:
    """这个类型声明的设定：每份合声明的规矩，不重名，项都不是每个点给的。"""
    if not isinstance(kind.settings, tuple) or not all(isinstance(one, dict) for one in kind.settings):
        return [f"{title}：settings 要是声明的元组，每份一个 JSON 对象"]
    problems = [f"{title}：{text}" for one in kind.settings for text in check_declaration(one)]
    names = [one.get("name") for one in kind.settings]
    if len(set(map(str, names))) != len(names):
        problems.append(f"{title}：声明的设定有重名的：{names}")
    for one in kind.settings:
        loose = [item.get("name") for item in one.get("items") or [] if isinstance(item, dict) and item.get("per_point") is not False]
        if loose:
            problems.append(f"{title}：声明的设定 {one.get('name')!r} 只管怎么跑，每个点都一样，这几项不能是每个点给的：{loose}")
    return problems


# ---------------------------------------------------------------- handle

@dataclass(frozen=True)
class InputInfo:
    """一样输入的登记信息。"""
    id: str
    kind: str
    name: str
    version: int
    hash: str
    origin: dict
    bone_id: str | None
    time: str | None = None     # 它是什么时候登记的。判据这类“要在看到结果之前写定”的输入，拿它和这一轮开的时间比


@dataclass(frozen=True)
class RoundInfo:
    """这是第几轮、要重排哪些任务、这一轮的来历。

    rerun 只说以前报过的任务里这一轮要重排哪几个。它是空的不等于“这是第一轮”：
    比如上一轮启动失败、一个任务都没来得及报，这一轮的 rerun 也是空的。
    所以 start 里该派哪些任务这样定：rerun 里的，加上 handle.tasks() 里还没有的。
    """
    number: int
    rerun: tuple[str, ...]      # 以前报过、这一轮要重排的任务
    provenance: dict            # 见 entries.ROUND_PROVENANCE；输入指纹要的 plugin_frozen 在这里
    opened: str | None = None   # 这一轮是什么时候开的。检查的时候轮还没开，是 None


class Handle(Protocol):
    """一次调用里插件能做的事。只在这一次调用里有效：脱离出去的进程和远端的 worker 都拿不到它。

    check 和 chart 拿到的是只读的那一份，写的那几个一叫就报错。
    """

    experiment: str                 # 实验的编号
    round: RoundInfo
    work_dir: Path                  # 插件自己的文件夹，几轮共用
    machines: tuple                 # 机器清单，见 machines.Machine

    # ---- 读 ----
    def input(self, name: str) -> Any:
        """一样输入的内容：值就是那个值，文件夹就是它的位置。只记位置的先再核一次哈希。

        收多份的输入返回列表；没填的可选输入返回 None（收多份的返回空列表）。
        """

    def input_info(self, name: str) -> Any:
        """一样输入的 InputInfo。收多份的返回列表。"""

    def tasks(self) -> dict:
        """各任务现在的状态：任务名 -> states.Task。"""

    # ---- 写 ----
    def task(self, task: str, state: str, outcome: str | None = None, stage: str | None = None,
             machine: str | None = None, fingerprint: str | None = None) -> None:
        """报一个任务的状态。完成和失败要带结局名。"""

    def output(self, name: str, folder) -> str | None:
        """交一样候选的产物。文件夹要在 work_dir 里。

        过了核对就被移走并登记，返回登记的编号；没过留在原地并记成问题，返回 None。
        """

    def problem(self, error: str, task: str | None = None, raw: str | None = None) -> None:
        """报一个问题。"""

    def provenance(self, **info) -> None:
        """补来历，比如求解器版本。"""

    def finish(self) -> None:
        """说这一轮做完了。这次调用返回之后才生效。"""

    def fail(self, reason: str) -> None:
        """说这一轮做不下去了。这次调用返回之后才生效。"""
