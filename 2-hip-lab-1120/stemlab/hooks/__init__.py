"""挂点：插件能用的门面。

插件要的一切都从这里拿，包括派活到 Linux。这个文件只转出，不写逻辑。插件里这样写：

    from stemlab.hooks import Kind, Input, Output, Outcome, Chart
    from stemlab import hooks           # 要用 remote 时：hooks.remote.push(...)

不要 import 挂点的子模块（stemlab.hooks.handle 之类），依赖规则会报出是哪个文件哪一行。

这一块的目标：插件写得再糟，最坏的结果是这个实验多一条问题。
    load.py     找到所有插件；FROZEN 清单怎么读；插件文件夹和冻结文件的哈希
    handle.py   一次调用里插件能做的事
    call.py     唯一叫插件代码的地方
    publish.py  发布一样产物的六步；对账
    entry.py    在子进程里跑一个带代码的包
    local.py    起、查、杀本机的脱离进程
    remote.py   远程执行的四个动作
"""
from stemlab.contract.formats.manifest import check_format, common_maker, made_by, maker_clash, mixed_makers
from stemlab.contract.formats.points import read_points, write_points
from stemlab.contract.hashing import fingerprint
from stemlab.contract.plugin_api import Chart, Input, Kind, Outcome, Output
from stemlab.contract.states import TASK_STATES
from stemlab.hooks import remote
from stemlab.hooks.entry import derive, look, predict, rerun, run_kernel, run_strategy
from stemlab.hooks.local import alive, kill, spawn

__all__ = [
    "Kind", "Input", "Output", "Outcome", "Chart", "TASK_STATES",
    "read_points", "write_points", "check_format", "fingerprint", "made_by", "mixed_makers", "maker_clash", "common_maker",
    "predict", "derive", "run_strategy", "run_kernel", "look", "rerun",
    "spawn", "alive", "kill", "remote",
]
