"""data/ 的布局和编号的写法。

这里只做路径和字符串的运算，不碰盘。别的块要找 data/ 下的任何东西都问这里，
所以“东西放在哪”只有这一份。

    data/
      registry/
        register.jsonl  register.lock
        links.jsonl
        store/C0001/ ...             storage=copy 的内容
      experiments/
        issued.jsonl  issued.lock    给实验发号
        E0001/
          record.jsonl  record.lock
          busy.lock                  动这个实验时拿的锁
          rounds/1/outputs/data/ ... 发布后的产物，只读
          rounds/1/plugin.diff       这一轮插件没提交的改动
          work/                      插件自己的地方，几轮共用
      watch.lock
      backup.json                    上次备份时各条链的链头

四个环境变量可以改默认位置（测试、在 Linux 上核对备份时用）：
    STEMLAB_REPO     仓库根目录。默认是 stemlab 包的上一级
    STEMLAB_DATA     data/ 的位置。默认是仓库根目录下的 data
    STEMLAB_PLUGINS  插件所在的包名。默认是 plugins
    STEMLAB_CACHE    这台机器自己的缓存。默认是仓库根目录下的 .cache
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# 编号。骨这一层的（case）以 C 开头，其余登记的东西以 R 开头，实验以 E 开头
ITEM_ID = re.compile(r"[CR][0-9]{4,}")
EXPERIMENT_ID = re.compile(r"E[0-9]{4,}")

# 落盘的名字和 JSON 的键一律用 ASCII
KEY = re.compile(r"[a-z][a-z0-9_]{0,39}")                 # 输入名、产物名、结局名、图表名
COLUMN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")         # 数据的列名、点的设计项和条件项：物理量的名字常带大写（L、E_MPa）
TYPE_NAME = re.compile(r"[a-z][a-z0-9_]{0,19}\.[a-z][a-z0-9_]{0,19}")   # 类型名：插件.类型
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")    # 登记的名字、骨标识、任务名、标签


def repo_root() -> Path:
    """仓库根目录。"""
    env = os.environ.get("STEMLAB_REPO")
    return Path(env) if env else Path(os.path.abspath(__file__)).parents[2]


def data_root() -> Path:
    """data/ 的位置。"""
    env = os.environ.get("STEMLAB_DATA")
    return Path(env) if env else repo_root() / "data"


def plugins_package() -> str:
    """插件所在的包名。核心靠扫描这个包的文件夹找到插件。"""
    return os.environ.get("STEMLAB_PLUGINS") or "plugins"


def lock_file() -> Path:
    """环境的锁文件。两台机器各一个环境，由这同一份装出来；它的哈希记进每一轮的来历。"""
    return repo_root() / "uv.lock"


def cache_root() -> Path:
    """这台机器自己的缓存，不是账的一部分，丢了只是重算。默认在仓库根目录下的 .cache；STEMLAB_CACHE 可以改。

    现在只放一样：哪个带代码的包在这台机器上过了自检。它不能放进 data/：data/ 会备份到另一台机器上。
    """
    env = os.environ.get("STEMLAB_CACHE")
    return Path(env) if env else repo_root() / ".cache"


# ---- 编号 ----

def item_id(seq: int, case: bool) -> str:
    """登记的编号，由这一条在登记链上的序号得出，所以不重用。"""
    return f"{'C' if case else 'R'}{seq:04d}"


def experiment_id(seq: int) -> str:
    """实验的编号，由发号链上的序号得出。"""
    return f"E{seq:04d}"


def is_item_id(text) -> bool:
    return isinstance(text, str) and ITEM_ID.fullmatch(text) is not None


def is_experiment_id(text) -> bool:
    return isinstance(text, str) and EXPERIMENT_ID.fullmatch(text) is not None


def id_seq(some_id: str) -> int:
    """编号里的序号。"""
    if not (is_item_id(some_id) or is_experiment_id(some_id)):
        raise ValueError(f"不是一个编号：{some_id!r}")
    return int(some_id[1:])


def is_key(text) -> bool:
    return isinstance(text, str) and KEY.fullmatch(text) is not None


def is_column(text) -> bool:
    """数据的列名、点的设计项和条件项的名字：字母开头，字母、数字、下划线，大小写都行。"""
    return isinstance(text, str) and COLUMN.fullmatch(text) is not None


def same_but_case(names) -> list[str]:
    """只差大小写的名字（L 和 l）。放在同一张表里迟早认错，所以不许。返回撞上的那几个。"""
    seen: dict[str, str] = {}
    clashes = []
    for name in names:
        other = seen.setdefault(name.lower(), name)
        if other != name:
            clashes.append(name)
    return clashes


def is_label(text) -> bool:
    return isinstance(text, str) and LABEL.fullmatch(text) is not None


def is_type_name(text) -> bool:
    return isinstance(text, str) and TYPE_NAME.fullmatch(text) is not None


# ---- 登记 ----

def register_file() -> Path:
    return data_root() / "registry" / "register.jsonl"


def register_lock() -> Path:
    return data_root() / "registry" / "register.lock"


def links_file() -> Path:
    return data_root() / "registry" / "links.jsonl"


def store_root() -> Path:
    return data_root() / "registry" / "store"


def store_dir(some_item_id: str) -> Path:
    """storage=copy 的外来东西存在哪。"""
    if not is_item_id(some_item_id):
        raise ValueError(f"不是登记的编号：{some_item_id!r}")
    return store_root() / some_item_id


# ---- 实验 ----

def issued_file() -> Path:
    return data_root() / "experiments" / "issued.jsonl"


def issued_lock() -> Path:
    return data_root() / "experiments" / "issued.lock"


def experiment_dir(experiment: str) -> Path:
    if not is_experiment_id(experiment):
        raise ValueError(f"不是实验的编号：{experiment!r}")
    return data_root() / "experiments" / experiment


def record_file(experiment: str) -> Path:
    return experiment_dir(experiment) / "record.jsonl"


def record_lock(experiment: str) -> Path:
    return experiment_dir(experiment) / "record.lock"


def busy_lock(experiment: str) -> Path:
    return experiment_dir(experiment) / "busy.lock"


def work_dir(experiment: str) -> Path:
    """插件自己的地方，几轮共用。"""
    return experiment_dir(experiment) / "work"


def round_dir(experiment: str, number: int) -> Path:
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError(f"不是一个轮号：{number!r}")
    return experiment_dir(experiment) / "rounds" / str(number)


def outputs_dir(experiment: str, number: int) -> Path:
    return round_dir(experiment, number) / "outputs"


def output_dir(experiment: str, number: int, name: str) -> Path:
    """发布后的一样产物放在哪。"""
    if not is_key(name):
        raise ValueError(f"不是一个产物名：{name!r}")
    return outputs_dir(experiment, number) / name


def plugin_diff(experiment: str, number: int, changed_to: str | None = None) -> Path:
    """这一轮插件没提交的改动存在哪。

    开轮时的那一份叫 plugin.diff。这一轮中途插件的代码又变了，变成哈希是 changed_to 的那一份，
    它的差异另存一个文件，名字里带哈希的前 12 位。
    """
    name = "plugin.diff" if changed_to is None else f"plugin-{changed_to[:12]}.diff"
    return round_dir(experiment, number) / name


# ---- data/ 根下的两个文件 ----

def watch_lock() -> Path:
    return data_root() / "watch.lock"


def backup_file() -> Path:
    return data_root() / "backup.json"


# ---- data/ 里的位置怎么写进记录 ----

def inside(path) -> str:
    """把 data/ 里的一个位置写成相对的、正斜杠的字符串。登记里 copy 的 content 记的是它。"""
    return Path(path).relative_to(data_root()).as_posix()


def locate(content: str) -> Path:
    """inside 的反过来。"""
    if not isinstance(content, str) or content.startswith("/") or ":" in content or ".." in content.split("/"):
        raise ValueError(f"不是 data/ 里的相对位置：{content!r}")
    return data_root() / content
