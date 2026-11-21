"""种类。登记的东西有哪几种，按形态分四组（见 _ROWS）；这里也定了登记的一条记录长什么样。

蓝图定的是十六种。2026-11-16 照《核心、插件和包》第二节，带代码的包加了四种：柄空间、有限元、重建方法、代理模型。
原来的内核（kernel）留着，作参照包。

注意两个容易混的词：种类（kind）说的是登记的东西，类型（type）说的是实验。
"""
from __future__ import annotations

from dataclasses import dataclass

from stemlab.contract.chain import is_time
from stemlab.contract.hashing import is_hash
from stemlab.contract.layout import id_seq, is_item_id, is_label
from stemlab.contract.origin import PRODUCT, check_origin

# 形态
FOLDER, TABLE, PACKAGE, VALUE = "folder", "table", "package", "value"

# 存法：value 一个值；copy 内容在 data/ 里，归系统管，只读；ref 只记位置
STORE_VALUE, STORE_COPY, STORE_REF = "value", "copy", "ref"


@dataclass(frozen=True)
class ItemKind:
    name: str       # 代码里的名字
    label: str      # 中文名，只用于显示
    form: str       # 形态
    case: bool      # 是不是 case（骨这一层）
    format: str     # 用哪个格式，见 versions.FORMATS


_ROWS = (
    # 代码名          中文名          形态      case    格式
    ("bone_source", "骨源",         FOLDER,   True,   "manifest"),
    ("bone_model",  "骨模型",       FOLDER,   True,   "bone_model"),
    ("bone_draft",  "候选骨模型",   FOLDER,   False,  "bone_model"),
    ("edits",       "人工修改",     FOLDER,   False,  "manifest"),
    ("archive",     "归档清单",     FOLDER,   False,  "manifest"),
    ("report",      "报告",         FOLDER,   False,  "manifest"),
    ("points",      "一批点",       TABLE,    False,  "points"),
    ("pool",        "候选池",       TABLE,    False,  "points"),
    ("data",        "数据",         TABLE,    False,  "data"),
    ("prediction",  "一份预测",     TABLE,    False,  "data"),
    ("kernel",      "内核",         PACKAGE,  False,  "package"),      # 原来的内核，留作参照包
    ("strategy",    "策略",         PACKAGE,  False,  "package"),
    ("derive_def",  "推导量定义",   PACKAGE,  False,  "package"),
    ("predictor",   "预测器",       PACKAGE,  False,  "package"),
    ("stem_space",  "柄空间",       PACKAGE,  False,  "package"),      # 柄的形状和放置：设计项、模板化、交出柄的模型
    ("fem",         "有限元",       PACKAGE,  False,  "package"),      # 照 Abaqus 的设定建模、求解、后处理
    ("recon_method", "重建方法",    PACKAGE,  False,  "package"),      # CT 流程、CAD 导入、STL 导入
    ("surrogate_model", "代理模型", PACKAGE,  False,  "package"),      # 一种模型族怎么训练
    ("objective",   "目标和约束",   VALUE,    False,  "value"),
    ("setting",     "设定",         VALUE,    False,  "value"),
)
ITEM_KINDS: dict[str, ItemKind] = {row[0]: ItemKind(*row) for row in _ROWS}


def storages(kind: str) -> tuple[str, ...]:
    """这个种类能用哪几种存法。值只能存成值；别的都是文件夹，复制一份或只记位置。"""
    return (STORE_VALUE,) if ITEM_KINDS[kind].form == VALUE else (STORE_COPY, STORE_REF)


# 登记的一条记录的字段。seq、prev、this 由链来填
ITEM_FIELDS = ("format", "time", "id", "kind", "name", "version", "storage", "content", "hash", "origin", "bone_id")


def check_item(record) -> list[str]:
    """核对登记的一条记录。返回哪里不符；空列表就是对的。"""
    if not isinstance(record, dict):
        return ["登记的一条必须是一个 JSON 对象"]
    wanted = ITEM_FIELDS + ("seq", "prev", "this")
    problems = [f"缺 {key}" for key in ITEM_FIELDS if key not in record]
    problems += [f"多了 {key}" for key in record if key not in wanted]
    if problems:
        return problems

    kind = ITEM_KINDS.get(record["kind"]) if isinstance(record["kind"], str) else None
    if kind is None:
        return [f"登记的种类里没有 {record['kind']!r}"]
    if not is_time(record["time"]):
        problems.append(f"time 不是规定的写法：{record['time']!r}")
    if not is_item_id(record["id"]) or record["id"].startswith("C") != kind.case:
        problems.append(f"编号不对：case 以 C 开头，其余以 R 开头，这里是 {record['id']!r}")
    elif "seq" in record and id_seq(record["id"]) != record["seq"]:
        problems.append(f"编号 {record['id']} 和它在链上的序号 {record['seq']} 对不上")
    if not is_label(record["name"]):
        problems.append(f"名字要用 ASCII 的字母、数字和 . _ -，这里是 {record['name']!r}")
    version = record["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        problems.append(f"version 必须是正整数：{version!r}")
    if not is_hash(record["hash"]):
        problems.append("hash 必须是完整的 SHA-256")

    storage = record["storage"]
    if storage not in storages(kind.name):
        problems.append(f"{kind.name} 不能存成 {storage!r}，只能是 {storages(kind.name)}")
    elif storage == STORE_VALUE and not isinstance(record["content"], dict):
        problems.append("存成值的东西，content 必须是一个 JSON 对象")
    elif storage != STORE_VALUE and (not isinstance(record["content"], str) or not record["content"]):
        problems.append("文件夹形态的东西，content 必须写它的位置")

    origin_problems = check_origin(record["origin"])
    problems += origin_problems
    if not origin_problems and record["origin"]["from"] == PRODUCT and storage != STORE_COPY:
        problems.append("产物一定在 data/ 里，存法只能是 copy")

    bone_id = record["bone_id"]
    if kind.case and not is_label(bone_id):
        problems.append(f"case 必须带骨标识，这里是 {bone_id!r}")
    elif bone_id is not None and not is_label(bone_id):
        problems.append(f"骨标识要用 ASCII 的字母、数字和 . _ -，这里是 {bone_id!r}")
    return problems
