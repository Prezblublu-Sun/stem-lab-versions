"""数据和一份预测。两种都是一个文件夹：清单、rows.jsonl（一行一个点），场另存在 fields/ 下。

数据（data）的一行，必带的五样键是点的哈希、骨标识、轮号、输入指纹、结局：
    {"point": "<点的哈希>", "bone_id": "femur042", "round": 2, "fingerprint": "<输入指纹>", "outcome": "finished",
     "values": {"stem_length": 30, "load_case": "stair", "rotation": 0.12},
     "fields": {"interface_slip": "fields/p001/interface_slip.npy"}}
一份预测（prediction）的一行：
    {"point": "<点的哈希>", "bone_id": "femur042",
     "values": {"rotation": 0.11}, "lower": {"rotation": 0.08}, "upper": {"rotation": 0.16},
     "fields": {"interface_slip": "fields/p001/interface_slip.npy"}}
fields 可以不写：只预测标量的预测没有它。预测出来的场，值和它的区间存在同一个文件里。

清单另带：
    count     有几行
    columns   数据说明：每列 {"name", "unit", "meaning", "role"}。没有量纲的列，单位写 1
    level     一份预测才带：lower 和 upper 围出的区间名义上盖住真值的比例，比如 0.95

role 说这一列是什么：
    design      设计的一项                         写在点里，不能空；可以是数、词或开关
    condition   条件的一项                         同上
    pre         不做 FE 就拿得到的量（建模时算出的）  数，没有就写 null
    label       FE 算出的标量                      同上
    derived     由场经推导量定义算出的标量           同上
    field       场。数不在行里：行的 fields 里写着它存在 fields/ 下的哪个文件

values 带齐所有不是场的列。放不进去的点没有 FE 结果，那几列写 null，这一行照样在。
一份预测只有 label、derived 和 field 三种列，名字和数据里的相同；标量的不确定度写成每列的一个区间。
同一张表里一个点只有一行：预测和 FEA 的结果按点的哈希对齐。

契约只核清单和各行的形状。场文件里是什么、数对不对，由写它的那个冻结文件负责。
"""
from __future__ import annotations

import math
from pathlib import Path

from stemlab.contract.formats.points import read_points
from stemlab.contract.hashing import is_hash
from stemlab.contract.layout import is_column, is_key, is_label, same_but_case

ROWS_FILE = "rows.jsonl"
FIELDS = "fields/"
ROW_KEYS = ("point", "bone_id", "round", "fingerprint", "outcome")     # 数据的每一行必带的五样
DATA_KEYS = ROW_KEYS + ("values", "fields")
PREDICTION_KEYS = ("point", "bone_id", "values", "lower", "upper")
PREDICTION_OPTIONAL = ("fields",)           # 一份预测的行可以另带的：预测出来的场各存在哪个文件
COLUMN_KEYS = ("name", "unit", "meaning", "role")
ROLES = ("design", "condition", "pre", "label", "derived", "field")
GIVEN_ROLES = ("design", "condition")       # 写在点里的
FE_ROLES = ("label", "derived", "field")    # 做了 FE 才有的。代理的特征里不能有这几种列
PREDICTABLE = ("label", "derived", "field")     # 一份预测里能有的列
_MAX_PROBLEMS = 20


def check_columns(kind: str, manifest: dict) -> list[str]:
    """核对数据说明：每列有名字、单位、含义、role。"""
    columns = manifest.get("columns")
    if not isinstance(columns, list) or not columns:
        return [f"清单要带 columns（数据说明）：一个不空的列表，每列写 {list(COLUMN_KEYS)}"]
    allowed = ROLES if kind == "data" else PREDICTABLE
    problems, seen = [], set()
    for number, column in enumerate(columns, start=1):
        if not isinstance(column, dict) or set(column) != set(COLUMN_KEYS):
            problems.append(f"columns 的第 {number} 列要带且只带这几项：{list(COLUMN_KEYS)}")
            continue
        name = column["name"]
        if not is_column(name):
            problems.append(f"列名要用字母开头，字母、数字和下划线：{name!r}")
            continue
        if name in seen:
            problems.append(f"列名重复：{name}")
        seen.add(name)
        if not isinstance(column["unit"], str) or not column["unit"].strip():
            problems.append(f"列 {name} 没有写单位（没有量纲的写 1）")
        if not isinstance(column["meaning"], str) or not column["meaning"].strip():
            problems.append(f"列 {name} 没有写含义")
        if column["role"] not in allowed:
            problems.append(f"列 {name} 的 role 是 {column['role']!r}，{kind} 里只能是 {list(allowed)}")
    clashes = same_but_case(sorted(seen))
    if clashes:
        problems.append(f"有只差大小写的列名：{clashes}")
    return problems


def check_rows(kind: str, manifest: dict, rows, files) -> list[str]:
    """核对一张数据或一份预测。files 是清单列的文件。返回哪里不符，点名是第几行；空列表就是对的。"""
    problems = check_columns(kind, manifest)
    if kind == "prediction":
        level = manifest.get("level")
        if isinstance(level, bool) or not isinstance(level, (int, float)) or not 0 < level < 1:
            problems.append("一份预测的清单要带 level：区间名义上盖住真值的比例，在 0 和 1 之间")
    if not rows:
        problems.append("表不能是空的，至少要有一行")
    if manifest.get("count") != len(rows):
        problems.append(f"清单写的是 {manifest.get('count')!r} 行，实际是 {len(rows)} 行")
    if problems:
        return problems

    columns = manifest["columns"]
    scalars = [column["name"] for column in columns if column["role"] != "field"]
    given = {column["name"] for column in columns if column["role"] in GIVEN_ROLES}
    fields = {column["name"] for column in columns if column["role"] == "field"}
    wanted = DATA_KEYS if kind == "data" else PREDICTION_KEYS
    seen: dict[str, int] = {}
    used: set[str] = set()
    for number, row in enumerate(rows, start=1):
        if len(problems) >= _MAX_PROBLEMS:
            return problems + ["……还有更多，先改上面这些"]
        title = f"第 {number} 行"
        missing = [key for key in wanted if key not in row]
        extra = [key for key in row if key not in wanted and (kind == "data" or key not in PREDICTION_OPTIONAL)]
        if missing or extra:
            problems.append(f"{title} 要带且只带这几项：{list(wanted)}"
                            + (f"，缺 {missing}" if missing else "") + (f"，多了 {extra}" if extra else ""))
            continue
        if not is_hash(row["point"]):
            problems.append(f"{title} 的点的哈希不对：{row['point']!r}")
        elif seen.setdefault(row["point"], number) != number:
            problems.append(f"{title} 和第 {seen[row['point']]} 行是同一个点")
        if not is_label(row["bone_id"]):
            problems.append(f"{title} 的骨标识不对：{row['bone_id']!r}")
        if kind == "data":
            if isinstance(row["round"], bool) or not isinstance(row["round"], int) or row["round"] < 1:
                problems.append(f"{title} 的轮号必须是正整数：{row['round']!r}")
            if not is_hash(row["fingerprint"]):
                problems.append(f"{title} 的输入指纹不对：{row['fingerprint']!r}")
            if not is_key(row["outcome"]):
                problems.append(f"{title} 的结局要写结局名：{row['outcome']!r}")
            problems += _check_group(title, "values", row["values"], scalars, given)
            problems += _check_fields(title, row["fields"], fields, files, used)
        else:
            for group in ("values", "lower", "upper"):
                problems += _check_group(title, group, row[group], scalars, ())
            problems += _check_intervals(title, row, scalars)
            if "fields" in row:
                problems += _check_fields(title, row["fields"], fields, files, used)
    problems += [f"fields/ 下有哪一行都没指着的文件：{rel}"
                 for rel in sorted(set(files) - used) if rel.startswith(FIELDS)][:_MAX_PROBLEMS]
    return problems


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_group(title: str, group: str, values, names: list, given) -> list[str]:
    """一行里的一组数：带齐这几列；写在点里的列不能空，别的列是数或 null。"""
    if not isinstance(values, dict):
        return [f"{title} 的 {group} 必须是一个 JSON 对象"]
    problems = []
    missing, extra = [name for name in names if name not in values], [name for name in values if name not in names]
    if missing:
        problems.append(f"{title} 的 {group} 缺 {missing}")
    if extra:
        problems.append(f"{title} 的 {group} 多了 {extra}（场不写在这里，别的列要先写进数据说明）")
    for name in names:
        value = values.get(name)
        if name in given:
            if name in values and not (_is_number(value) or isinstance(value, bool) or (isinstance(value, str) and value)):
                problems.append(f"{title} 的 {name} 是设计或条件，不能空，要写数、词或开关：{value!r}")
        elif value is not None and not _is_number(value):
            problems.append(f"{title} 的 {name} 要写一个有限的数，没有就写 null：{value!r}")
    return problems


def _check_fields(title: str, listed, fields: set, files, used: set) -> list[str]:
    if not isinstance(listed, dict):
        return [f"{title} 的 fields 必须是一个 JSON 对象"]
    problems = []
    for name, rel in listed.items():
        if name not in fields:
            problems.append(f"{title} 的 fields 里的 {name!r} 不是数据说明里的一个场")
        elif not isinstance(rel, str) or not rel.startswith(FIELDS):
            problems.append(f"{title} 的场 {name} 要存在 fields/ 下：{rel!r}")
        elif rel not in files:
            problems.append(f"{title} 的场 {name} 指着的文件清单里没有：{rel}")
        else:
            used.add(rel)
    return problems


def _check_intervals(title: str, row: dict, names: list) -> list[str]:
    """一份预测的每个数都带区间：下界不大于它，上界不小于它；没有数的也没有区间。"""
    problems = []
    for name in names:
        value, lower, upper = (row[group].get(name) if isinstance(row[group], dict) else None
                               for group in ("values", "lower", "upper"))
        if not all(part is None or _is_number(part) for part in (value, lower, upper)):
            continue                                    # 不是数的那一项上面已经点过名
        if value is None:
            if lower is not None or upper is not None:
                problems.append(f"{title} 的 {name} 没有数，却写了区间")
        elif lower is None or upper is None:
            problems.append(f"{title} 的 {name} 有数，没有写全区间")
        elif not lower <= value <= upper:
            problems.append(f"{title} 的 {name} 不在它自己的区间里：{lower!r} ≤ {value!r} ≤ {upper!r} 不成立")
    return problems


def check(kind: str, manifest: dict, folder) -> list[str]:
    """check_format 叫的入口：清单里的文件对，再读出各行来核。"""
    files = manifest["files"]
    if ROWS_FILE not in files:
        return [f"文件夹里要有 {ROWS_FILE}"]
    others = [rel for rel in files if rel != ROWS_FILE]
    stray = [rel for rel in others if not rel.startswith(FIELDS)]
    if stray:
        return [f"除了 {ROWS_FILE}，别的文件都要放在 fields/ 下：{stray[:5]}"]
    try:
        rows = read_points(Path(folder) / ROWS_FILE)
    except ValueError as error:
        return [str(error)]
    return check_rows(kind, manifest, rows, files)
