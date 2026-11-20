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

另转出契约里几样核对的函数，给插件的骨架核每个点给的项、名字引用和柄的模型用（规矩还是只在契约里）：
    check_setting、check_point、check_design、merged、is_declared、find_declaration、per_point_items   设定的声明
    check_stem_model、read_stem_model、stem_names                                                      柄的模型
    bone_names                                                                                          骨模型里能被名字引用的
骨模型第 2 版（第 5 步）加的，规矩和算法都在契约的 formats/bone_model.py：
    read_bone_model       读一份骨模型的清单，读成现在这一版的样子（盘上是第 1 版的照样读）。交给包的、拿去核要求的都是它
    check_bone_wanted     包清单 inputs 里对骨模型的要求，自己写得对不对
    bone_lacking          一份骨模型缺要求里的哪几样
    bone_frame            从标志点算解剖坐标系（算法只有契约里那一份）
    bone_anteversion      照后髁连线量出的前倾角
重建的骨架照方法包走（第 5 步的 5c）加的：run_recon，跑重建方法包，和 run_stem、run_fem 一样是 entry.run 的薄封装。
"""
from stemlab.contract.formats.bone_model import anteversion as bone_anteversion
from stemlab.contract.formats.bone_model import check_wanted as check_bone_wanted
from stemlab.contract.formats.bone_model import frame as bone_frame
from stemlab.contract.formats.bone_model import lacking as bone_lacking
from stemlab.contract.formats.bone_model import names as bone_names
from stemlab.contract.formats.bone_model import read as read_bone_model
from stemlab.contract.formats.declaration import (check_design, check_point, check_setting, is_declared, merged,
                                                  per_point_items)
from stemlab.contract.formats.declaration import find as find_declaration
from stemlab.contract.formats.manifest import (check_format, common_maker, made_by, made_by_split, maker_clash,
                                               mixed_makers)
from stemlab.contract.formats.points import read_points, write_points
from stemlab.contract.formats.stem_model import check as check_stem_model
from stemlab.contract.formats.stem_model import names as stem_names
from stemlab.contract.formats.stem_model import read as read_stem_model
from stemlab.contract.hashing import fingerprint
from stemlab.contract.plugin_api import Chart, Input, Kind, Outcome, Output
from stemlab.contract.states import TASK_STATES
from stemlab.hooks import remote
from stemlab.hooks.entry import derive, look, predict, rerun, run_fem, run_kernel, run_recon, run_stem, run_strategy
from stemlab.hooks.local import alive, kill, spawn

__all__ = [
    "Kind", "Input", "Output", "Outcome", "Chart", "TASK_STATES",
    "read_points", "write_points", "check_format", "fingerprint", "made_by", "made_by_split", "mixed_makers", "maker_clash",
    "common_maker",
    "predict", "derive", "run_strategy", "run_kernel", "run_stem", "run_fem", "run_recon", "look", "rerun",
    "spawn", "alive", "kill", "remote",
    "check_setting", "check_point", "check_design", "merged", "is_declared", "find_declaration", "per_point_items",
    "check_stem_model", "read_stem_model", "stem_names", "bone_names",
    "read_bone_model", "check_bone_wanted", "bone_lacking", "bone_frame", "bone_anteversion",
]
