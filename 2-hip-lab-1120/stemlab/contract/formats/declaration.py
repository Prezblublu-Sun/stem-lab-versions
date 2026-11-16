"""设定的声明，和照声明登记的设定：格式，和核验的规矩。规矩只在这一处（《设定的声明和包的清单》第二、三节）。

一份声明是一个 JSON 对象：
    name       这份声明叫什么：fea、placement、derive、recon、hyper、strategy、run……（小写字母、数字、下划线）
    groups     分组的顺序，页面照它排：[组名, …]，组名是不空的文字，不重复
    items      项的列表，一项见下面
    relations  两项之间的大小关系，可以没有：[{"less": 项名, "than": 项名}]。两项都得是数或都得是整数，单位相同

一项：
    name         机器认的名字：字母开头，字母、数字、下划线。一份声明里不重名，只差大小写也不行
    label        给人看的名字
    meaning      一两句话：这个量是什么，影响什么
    group        在哪一组，得在 groups 里
    type         见 TYPES
    unit         number、vector3 必有，从 UNITS 里选；别的类型不写。跑的时候不换算
    range        number、integer 必有：{"min", "max"}，可再写 "min_open"、"max_open": true，不含那一头
    choices      choice、choices 必有：[{"value": 文字, "label": 文字}]，value 不重复
    when         只在什么时候有，可以没有：{别的项名: [取值, …]}。那一项得是几选一或是否，而且每个点都一样
    per_point    每个点能不能变：true 或 false
    required     必不必填：true 或 false。可选的项设定里不写就是“没有”，不会被补成默认
    test         测试轮的取值，必须合这一项的规矩；可选的项可以写 null
    test_source  测试轮取值的来路：不空的文字，比如“Abaqus 手册”“文献 …”“原项目 M1 的做法”
    abaqus       对应 Abaqus 的关键字和参数，只给人看，可以没有
    pattern      text 才有，可以没有：正则，整串要匹配上
    unit_length  vector3 才有，可以没有：true 是要求长度为一，用来写方向
    columns      table 必有：每一列又是一项，只写 name、label、meaning、type、required，和这个类型要的那几样；不能再是表
    kind         item 必有：指向哪一种登记的东西，kinds.ITEM_KINDS 里的名字
    refers       ref 必有：能指向哪几类有名字的东西，[“bone.region”, …]，从 REFERABLE 里选

一份设定（登记的值）：
    declaration  照哪份声明：{"of": 包的编号或实验类型, "name": 声明名, "hash": 声明的哈希}
    use          formal（正式）或 test（测试）
    values       每一项的取值。每个点能变的项可以写 {"per_point": true}：由一批点逐个给
    sources      每一项的来路：{项名: 文字}
    note         说明，可以没有

名字引用的值写成 {"ref": "bone.region.cortical"}：哪一份输入、哪一类、叫什么。

核验设定的规矩（RULES）。不合的说出是哪一项、哪一条：
    1 照的那份声明对得上：就是这个实验填的那个包（或实验类型）的那份，哈希也对
    2 声明里没有的项不许出现
    3 必填的项都在；“只在什么时候有”的项，条件不满足时不许出现，满足时照必不必填
    4 类型、范围、可选的值都对；单位就是声明的单位，跑的时候不换算
    5 两项之间的大小关系成立
    6 写了“每个点给”的项，这一批点的每个点上都有，照同一份声明核
    7 用途对得上：测试的设定不用在正式的轮上，反过来也不行
    8 名字引用的名字，在实际的输入里有
    9 正式的设定，每个写了的项都写了来路
第 1、7、8 条要知道这个实验填了什么、输入里有什么，由调用的一方给（of、use、names）；不给就不核那一条。
"""
from __future__ import annotations

import math
import re

from stemlab.contract.hashing import hash_json
from stemlab.contract.kinds import ITEM_KINDS
from stemlab.contract.layout import is_column, is_item_id, is_key, is_label, same_but_case

TYPES = ("number", "integer", "bool", "choice", "choices", "text", "vector3", "table", "item", "ref")
NUMERIC = ("number", "integer")

# 单位表：ASCII 写法，和现有的包一致。要加单位，就要改契约
UNITS = {
    "mm": "长度", "um": "长度（微动、间隙这类小量）",
    "mm2": "面积", "mm3": "体积",
    "N": "力", "N*mm": "力矩",
    "MPa": "应力、模量", "1/MPa": "柔度", "N/mm": "刚度",
    "1/mm": "比表面积、曲率",
    "kg": "质量", "g/cm3": "密度",
    "deg": "角度", "s": "时间", "HU": "CT 值",
    "1": "无量纲、比例（比例写小数，不写百分数）",
}

# 名字引用能指向的东西：哪一份输入，哪一类
REFERABLE = {"bone": ("block", "joint", "region", "surface", "landmark"),
             "stem": ("region", "faces", "feature", "axis")}

USES = ("formal", "test")
PER_POINT = {"per_point": True}

RULES = {1: "照的声明对得上", 2: "没有声明外的项", 3: "该有的项都在", 4: "类型、范围、可选的值对",
         5: "大小关系成立", 6: "每个点给的项每个点都有", 7: "用途对得上", 8: "名字引用的名字存在",
         9: "正式的设定每项写了来路"}

_ITEM_KEYS = {"name", "label", "meaning", "group", "type", "unit", "range", "choices", "when", "per_point",
              "required", "test", "test_source", "abaqus", "pattern", "unit_length", "columns", "kind", "refers"}
_ITEM_MUST = ("name", "label", "meaning", "group", "type", "per_point", "required", "test", "test_source")
_COLUMN_KEYS = {"name", "label", "meaning", "type", "required", "unit", "range", "choices", "pattern", "unit_length",
                "kind", "refers"}
_BY_TYPE = {"number": {"unit", "range"}, "integer": {"range"}, "choice": {"choices"}, "choices": {"choices"},
            "vector3": {"unit"}, "table": {"columns"}, "item": {"kind"}, "ref": {"refers"}}
_OPTIONAL_BY_TYPE = {"text": {"pattern"}, "vector3": {"unit_length"}}


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _said(item: dict) -> str:
    """说给人听的一项：名字，和它的叫法。"""
    label = item.get("label")
    return f"{item.get('name')!r}（{label}）" if _text(label) else repr(item.get("name"))


def _broke(item: dict, what: str, rule: int) -> str:
    return f"{_said(item)}：{what}（规则 {rule}：{RULES[rule]}）"


def is_per_point(value) -> bool:
    """这个取值是不是“每个点给”。"""
    return isinstance(value, dict) and value == PER_POINT


def declaration_hash(declaration: dict) -> str:
    """一份声明的哈希。设定里记它：声明改了，旧的设定就对不上了。"""
    return hash_json(declaration)


# ---------------------------------------------------------------- 一个取值合不合这一项

def check_value(item: dict, value, names: dict | None = None) -> str | None:
    """这个取值合不合这一项的类型、范围、可选的值（第 4 条）；名字引用的名字在不在（第 8 条，给了 names 才核）。

    合就返回 None，不合返回原因（已经说了是哪一项、哪一条）。names 是 {"bone.region": {名字, …}, …}。
    """
    kind = item.get("type")
    if kind in NUMERIC:
        if kind == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            return _broke(item, f"要一个整数，这里是 {value!r}", 4)
        if not _number(value):
            return _broke(item, f"要一个数，这里是 {value!r}", 4)
        return _out_of_range(item, value)
    if kind == "bool":
        return None if isinstance(value, bool) else _broke(item, f"要 true 或 false，这里是 {value!r}", 4)
    if kind == "choice":
        allowed = [choice["value"] for choice in item["choices"]]
        return None if value in allowed else _broke(item, f"要从 {allowed} 里选一个，这里是 {value!r}", 4)
    if kind == "choices":
        allowed = [choice["value"] for choice in item["choices"]]
        if not isinstance(value, list) or any(one not in allowed for one in value) or len(set(map(str, value))) != len(value):
            return _broke(item, f"要从 {allowed} 里选几个，不重复，这里是 {value!r}", 4)
        return None
    if kind == "text":
        if not isinstance(value, str):
            return _broke(item, f"要一段文字，这里是 {value!r}", 4)
        if item.get("pattern") and re.fullmatch(item["pattern"], value) is None:
            return _broke(item, f"文字要合 {item['pattern']!r} 这个写法，这里是 {value!r}", 4)
        return None
    if kind == "vector3":
        if not isinstance(value, list) or len(value) != 3 or not all(map(_number, value)):
            return _broke(item, f"要三个数 [x, y, z]，这里是 {value!r}", 4)
        if item.get("unit_length") and abs(math.sqrt(sum(part * part for part in value)) - 1.0) > 1e-6:
            return _broke(item, f"是一个方向，长度要是一，这里是 {value!r}", 4)
        return None
    if kind == "table":
        return _table(item, value, names)
    if kind == "item":
        return None if is_item_id(value) else _broke(item, f"要一个登记的编号，这里是 {value!r}", 4)
    if kind == "ref":
        return _ref(item, value, names)
    return _broke(item, f"类型 {kind!r} 不认得", 4)


def _out_of_range(item: dict, value) -> str | None:
    bounds = item["range"]
    low, high = bounds["min"], bounds["max"]
    below = value < low or (bounds.get("min_open") and value == low)
    above = value > high or (bounds.get("max_open") and value == high)
    if below or above:
        left, right = ("(" if bounds.get("min_open") else "["), (")" if bounds.get("max_open") else "]")
        return _broke(item, f"要在 {left}{low}, {high}{right} 里，这里是 {value!r}", 4)
    return None


def _table(item: dict, value, names) -> str | None:
    if not isinstance(value, list):
        return _broke(item, f"要一张表（若干行），这里是 {value!r}", 4)
    columns = {column["name"]: column for column in item["columns"]}
    for number, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            return _broke(item, f"第 {number} 行要是一个 JSON 对象", 4)
        extra = sorted(set(row) - set(columns))
        if extra:
            return _broke(item, f"第 {number} 行多了 {extra}", 4)
        for name, column in columns.items():
            if row.get(name) is None:
                if column["required"]:
                    return _broke(item, f"第 {number} 行缺 {name!r}", 4)
                continue
            why = check_value(column, row[name], names)
            if why:
                return _broke(item, f"第 {number} 行的 {why}", 4)
    return None


def _ref(item: dict, value, names) -> str | None:
    target = value.get("ref") if isinstance(value, dict) and set(value) == {"ref"} else None
    parts = target.split(".") if isinstance(target, str) else []
    if len(parts) != 3 or not is_label(parts[2]):
        return _broke(item, f'名字引用要写成 {{"ref": "输入.类别.名字"}}，这里是 {value!r}', 4)
    where = f"{parts[0]}.{parts[1]}"
    if where not in item["refers"]:
        return _broke(item, f"只能指向 {item['refers']}，这里指向 {where}", 4)
    if names is not None and parts[2] not in names.get(where, ()):
        return _broke(item, f"输入里没有 {target}", 8)
    return None


# ---------------------------------------------------------------- 一份声明合不合规矩

def check_declaration(declaration) -> list[str]:
    """核对一份声明。返回哪里不符，说出是哪一项；空列表就是对的。测试轮的取值也照规矩核，拼出的测试轮设定要过核验。"""
    if not isinstance(declaration, dict):
        return ["声明必须是一个 JSON 对象"]
    problems = [f"声明缺 {key}" for key in ("name", "groups", "items") if key not in declaration]
    problems += [f"声明多了 {key}" for key in declaration if key not in ("name", "groups", "items", "relations")]
    if problems:
        return problems
    title = f"声明 {declaration['name']!r}"
    if not is_key(declaration["name"]):
        problems.append(f"{title}：名字要用小写字母、数字和下划线")
    groups = declaration["groups"]
    if not isinstance(groups, list) or not all(map(_text, groups)) or len(set(groups)) != len(groups):
        return problems + [f"{title}：groups 要是不重复的组名列表"]
    items = declaration["items"]
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        return problems + [f"{title}：items 要是项的列表，每项一个 JSON 对象"]
    names = [item.get("name") for item in items]
    if not all(map(is_column, names)):
        return problems + [f"{title}：项的名字要字母开头，字母、数字、下划线：{names}"]
    if len(set(names)) != len(names) or same_but_case(names):
        problems.append(f"{title}：项的名字有重复的，或者只差大小写：{sorted(set(n for n in names if names.count(n) > 1)) or same_but_case(names)}")
    by_name = {item["name"]: item for item in items}
    # 分三遍：每一项自己的样子；都对了，再看“只在什么时候有”和测试轮的取值（要读别的项）；再看大小关系
    for number, item in enumerate(items, start=1):
        problems += [f"{title} 的第 {number} 项 {text}" for text in _item_problems(item, groups, by_name)]
    if problems:
        return problems
    for number, item in enumerate(items, start=1):
        problems += [f"{title} 的第 {number} 项 {text}" for text in _item_values(item, by_name)]
    if problems:
        return problems
    problems += [f"{title}：{text}" for text in _relation_problems(declaration.get("relations", []), by_name)]
    if not problems:
        problems += [f"{title}：拼出来的测试轮设定不过核验：{text}"
                     for text in check_setting(test_setting(declaration, "test"), declaration)]
    return problems


def _item_values(item: dict, by_name: dict) -> list[str]:
    """一项里要读别的项才核得了的：“只在什么时候有”；还有测试轮的取值。"""
    problems = _when_problems(item, by_name) if "when" in item else []
    if item["test"] is None:
        if item["required"]:
            problems.append(f"{_said(item)}：必填的项，测试轮也要有取值")
    elif is_per_point(item["test"]):
        problems.append(f"{_said(item)}：测试轮的取值要写一个值，不能写“每个点给”")
    else:
        why = check_value(item, item["test"])
        if why:
            problems.append(f"测试轮的取值不合规矩：{why}")
    return problems


def _item_problems(item: dict, groups: list, by_name: dict, column: bool = False) -> list[str]:
    allowed = _COLUMN_KEYS if column else _ITEM_KEYS
    must = ("name", "label", "meaning", "type", "required") if column else _ITEM_MUST
    problems = [f"{_said(item)}：缺 {key}" for key in must if key not in item]
    problems += [f"{_said(item)}：多了 {key}" for key in item if key not in allowed]
    if problems:
        return problems
    kind = item["type"]
    if kind not in TYPES or (column and kind == "table"):
        return [f"{_said(item)}：类型要是 {[t for t in TYPES if not (column and t == 'table')]} 之一，这里是 {kind!r}"]
    needed = _BY_TYPE.get(kind, set())
    optional = _OPTIONAL_BY_TYPE.get(kind, set())
    typed = {"unit", "range", "choices", "pattern", "unit_length", "columns", "kind", "refers"}
    problems += [f"{_said(item)}：{kind} 要写 {key}" for key in sorted(needed) if key not in item]
    problems += [f"{_said(item)}：{kind} 不写 {key}" for key in sorted(typed - needed - optional) if key in item]
    if not (_text(item["label"]) and _text(item["meaning"])):
        problems.append(f"{_said(item)}：label 和 meaning 要写清楚")
    if not isinstance(item["required"], bool):
        problems.append(f"{_said(item)}：required 要是 true 或 false")
    if not column:
        if item["group"] not in groups:
            problems.append(f"{_said(item)}：组 {item['group']!r} 不在 groups 里")
        if not isinstance(item["per_point"], bool):
            problems.append(f"{_said(item)}：per_point 要是 true 或 false")
        if not _text(item["test_source"]):
            problems.append(f"{_said(item)}：测试轮取值的来路要写")
        if "abaqus" in item and not _text(item["abaqus"]):
            problems.append(f"{_said(item)}：abaqus 写了就要是不空的文字")
    if problems:
        return problems
    return problems + _typed_problems(item, kind, groups, by_name)


def _typed_problems(item: dict, kind: str, groups: list, by_name: dict) -> list[str]:
    problems = []
    if "unit" in item and item["unit"] not in UNITS:
        problems.append(f"{_said(item)}：单位要从单位表里选：{list(UNITS)}，这里是 {item['unit']!r}")
    if kind in NUMERIC:
        bounds = item["range"]
        if not isinstance(bounds, dict) or not {"min", "max"} <= set(bounds) or set(bounds) - {"min", "max", "min_open", "max_open"}:
            problems.append(f'{_said(item)}：range 要写成 {{"min", "max"}}，可再写 min_open、max_open')
        elif not (_number(bounds["min"]) and _number(bounds["max"]) and bounds["min"] <= bounds["max"]):
            problems.append(f"{_said(item)}：range 的 min、max 要是数，min 不大于 max")
        elif kind == "integer" and not all(float(bounds[k]).is_integer() for k in ("min", "max")):
            problems.append(f"{_said(item)}：整数的 range 两头要是整数")
        elif any(not isinstance(bounds.get(k, False), bool) for k in ("min_open", "max_open")):
            problems.append(f"{_said(item)}：min_open、max_open 要是 true 或 false")
    if kind in ("choice", "choices"):
        choices = item["choices"]
        if (not isinstance(choices, list) or not choices
                or not all(isinstance(c, dict) and set(c) == {"value", "label"} and _text(c["value"]) and _text(c["label"]) for c in choices)):
            problems.append(f'{_said(item)}：choices 要是 [{{"value", "label"}}] 的列表，都是不空的文字')
        elif len({c["value"] for c in choices}) != len(choices):
            problems.append(f"{_said(item)}：choices 的 value 有重复的")
    if "pattern" in item:
        try:
            re.compile(item["pattern"])
        except (re.error, TypeError):
            problems.append(f"{_said(item)}：pattern 不是一个正则：{item['pattern']!r}")
    if "unit_length" in item and not isinstance(item["unit_length"], bool):
        problems.append(f"{_said(item)}：unit_length 要是 true 或 false")
    if kind == "table":
        columns = item["columns"]
        if not isinstance(columns, list) or not columns or not all(isinstance(c, dict) for c in columns):
            problems.append(f"{_said(item)}：columns 要是列的列表，每列一个 JSON 对象")
        else:
            names = [c.get("name") for c in columns]
            if not all(map(is_column, names)) or len(set(names)) != len(names) or same_but_case(names):
                problems.append(f"{_said(item)}：列的名字要字母开头、不重复：{names}")
            for column in columns:
                problems += [f"{_said(item)} 的列 {text}" for text in _item_problems(column, groups, by_name, column=True)]
    if kind == "item" and item["kind"] not in ITEM_KINDS:
        problems.append(f"{_said(item)}：kind 要是登记的一种东西：{list(ITEM_KINDS)}，这里是 {item['kind']!r}")
    if kind == "ref":
        known = [f"{where}.{what}" for where, whats in REFERABLE.items() for what in whats]
        if not isinstance(item["refers"], list) or not item["refers"] or any(one not in known for one in item["refers"]):
            problems.append(f"{_said(item)}：refers 要从 {known} 里选，这里是 {item['refers']!r}")
    return problems


def _when_problems(item: dict, by_name: dict) -> list[str]:
    when = item["when"]
    if not isinstance(when, dict) or not when:
        return [f"{_said(item)}：when 要写成 {{别的项名: [取值, …]}}"]
    problems = []
    for name, values in when.items():
        other = by_name.get(name)
        if other is None or other is item:
            problems.append(f"{_said(item)}：when 指向的 {name!r} 不是这份声明里别的一项")
            continue
        if other["type"] not in ("choice", "bool") or other["per_point"]:
            problems.append(f"{_said(item)}：when 只能看一项每个点都一样的几选一或是否，{name!r} 不是")
            continue
        allowed = [c["value"] for c in other["choices"]] if other["type"] == "choice" else [True, False]
        if not isinstance(values, list) or not values or any(value not in allowed for value in values):
            problems.append(f"{_said(item)}：when 里 {name!r} 的取值要从 {allowed} 里选，这里是 {values!r}")
    return problems


def _relation_problems(relations, by_name: dict) -> list[str]:
    if not isinstance(relations, list):
        return ["relations 要是一个列表"]
    problems = []
    for relation in relations:
        if not isinstance(relation, dict) or set(relation) != {"less", "than"}:
            problems.append(f'大小关系要写成 {{"less": 项名, "than": 项名}}：{relation!r}')
            continue
        less, than = by_name.get(relation["less"]), by_name.get(relation["than"])
        if less is None or than is None or less is than:
            problems.append(f"大小关系里的两项要是这份声明里不同的两项：{relation!r}")
        elif not (less["type"] == than["type"] and less["type"] in NUMERIC and less.get("unit") == than.get("unit")):
            problems.append(f"大小关系里的两项要都是数或都是整数，单位相同：{relation!r}")
    return problems


# ---------------------------------------------------------------- 一份设定合不合它的声明

def _present(item: dict, values: dict, by_name: dict) -> bool:
    """这一项在这份设定里该不该有：没写 when 的都该有；写了的，看它指向的那几项的取值。"""
    return all(values.get(name) in allowed for name, allowed in item.get("when", {}).items() if name in by_name)


def check_setting(setting, declaration: dict, *, of=None, use: str | None = None, names: dict | None = None) -> list[str]:
    """核一份设定（第 1 到第 5、第 7 到第 9 条）。返回哪里不符，说出是哪一项、哪一条；空列表就是对的。

    declaration 要是合规矩的声明（check_declaration 过了的）。of 是这个实验填的那个包的编号或实验类型，
    use 是这一轮的用途，names 是实际输入里有的名字：不给就不核第 1 条的 of、第 7 条、第 8 条。
    每个点给的项（第 6 条）由 check_point 逐个点核。
    """
    if not isinstance(setting, dict):
        return ["设定必须是一个 JSON 对象"]
    problems = [f"设定缺 {key}" for key in ("declaration", "use", "values", "sources") if key not in setting]
    problems += [f"设定多了 {key}" for key in setting if key not in ("declaration", "use", "values", "sources", "note")]
    if problems:
        return problems
    wanted = {"name": declaration["name"], "hash": declaration_hash(declaration)}
    said = setting["declaration"]
    if not isinstance(said, dict) or set(said) != {"of", "name", "hash"} or any(said.get(k) != v for k, v in wanted.items()):
        problems.append(f"设定说它照的是 {said!r}，这份声明是 {wanted['name']!r}、哈希 {wanted['hash'][:12]}…"
                        f"（规则 1：{RULES[1]}）")
    elif of is not None and said["of"] != of:
        problems.append(f"设定照的是 {said['of']!r} 的声明，这个实验填的是 {of!r}（规则 1：{RULES[1]}）")
    if setting["use"] not in USES:
        problems.append(f"用途要是 {list(USES)} 之一，这里是 {setting['use']!r}")
    elif use is not None and setting["use"] != use:
        problems.append(f"这份设定是{'测试' if setting['use'] == 'test' else '正式'}用的，这一轮是"
                        f"{'测试' if use == 'test' else '正式'}的（规则 7：{RULES[7]}）")
    values, sources = setting["values"], setting["sources"]
    if not isinstance(values, dict) or not isinstance(sources, dict):
        return problems + ["values 和 sources 都要是 JSON 对象"]
    by_name = {item["name"]: item for item in declaration["items"]}
    problems += [f"{name!r}：声明里没有这一项（规则 2：{RULES[2]}）" for name in values if name not in by_name]
    problems += [f"{name!r} 的来路：声明里没有这一项（规则 2：{RULES[2]}）" for name in sources if name not in by_name]
    # 先核写了的取值。取值不对的那几项，不再拿来定别的项该不该有、也不拿来比大小：只报根上那一处
    bad = set()
    for name, given in values.items():
        item = by_name.get(name)
        if item is None or given is None:
            continue
        if is_per_point(given):
            why = None if item["per_point"] else _broke(item, "每个点不能变，不能写“每个点给”", 4)
        else:
            why = check_value(item, given, names)
        if why:
            problems.append(why)
            bad.add(name)
    for item in declaration["items"]:
        name, given = item["name"], values.get(item["name"])
        if any(other in bad for other in item.get("when", {})):
            continue                                    # 它看的那一项取值不对：该不该有定不下来，先改那一项
        if not _present(item, values, by_name):
            if given is not None:
                problems.append(_broke(item, f"只在 {item['when']} 时才有，这份设定里不该写它", 3))
            continue
        if given is None:
            if item["required"]:
                problems.append(_broke(item, "必填，没有写", 3))
            continue
        if setting["use"] == "formal" and not _text(sources.get(name)):
            problems.append(_broke(item, "正式的设定要写它的来路", 9))
    problems += _relations_broken(declaration, {k: v for k, v in values.items() if k not in bad})
    return problems


def _relations_broken(declaration: dict, values: dict) -> list[str]:
    """两项之间的大小关系（第 5 条）。哪一头没写、取值不对，或者是“每个点给”，就不比，留给改好之后、或者逐个点核。"""
    by_name = {item["name"]: item for item in declaration["items"]}
    problems = []
    for relation in declaration.get("relations", []):
        less, than = values.get(relation["less"]), values.get(relation["than"])
        if _number(less) and _number(than) and not less < than:
            problems.append(_broke(by_name[relation["less"]], f"要小于 {relation['than']!r}（{than}），这里是 {less}", 5))
    return problems


def per_point_items(setting: dict) -> list[str]:
    """这份设定里写了“每个点给”的项。"""
    return sorted(name for name, value in setting["values"].items() if is_per_point(value))


def check_point(point_values, setting: dict, declaration: dict, names: dict | None = None) -> list[str]:
    """核一个点给的那一组取值（第 6 条）：设定里写了“每个点给”的项，这个点都给了，别的没给；每个取值合规矩；
    合起来之后大小关系成立。返回哪里不符；空列表就是对的。"""
    if not isinstance(point_values, dict):
        return [f"一个点给的取值要是一个 JSON 对象（规则 6：{RULES[6]}）"]
    wanted = per_point_items(setting)
    by_name = {item["name"]: item for item in declaration["items"]}
    problems = [_broke(by_name[name], "设定里写了每个点给，这个点没给", 6) for name in wanted if point_values.get(name) is None]
    problems += [f"{name!r}：设定里没写每个点给，这个点不该给（规则 6：{RULES[6]}）" for name in point_values if name not in wanted]
    bad = set()
    for name in wanted:
        if point_values.get(name) is not None:
            why = check_value(by_name[name], point_values[name], names)
            if why:
                problems.append(why)
                bad.add(name)
    given = {k: v for k, v in merged(setting, point_values).items() if k not in bad}
    return problems + _relations_broken(declaration, given)


def merged(setting: dict, point_values: dict) -> dict:
    """一个点上每一项的取值：设定里写的，加上这个点给的。"""
    return {**{k: v for k, v in setting["values"].items() if not is_per_point(v)}, **point_values}


def test_setting(declaration: dict, of) -> dict:
    """照声明里测试轮的取值拼出一份测试用的设定。每一项都照写，来路就是测试轮取值的来路。"""
    values = {item["name"]: item["test"] for item in declaration["items"] if item["test"] is not None}
    by_name = {item["name"]: item for item in declaration["items"]}
    while True:                     # 一层层往下推：它看的那一项不在了，它也不在
        kept = {name: value for name, value in values.items() if _present(by_name[name], values, by_name)}
        if kept == values:
            break
        values = kept
    return {"declaration": {"of": of, "name": declaration["name"], "hash": declaration_hash(declaration)},
            "use": "test", "values": values,
            "sources": {name: by_name[name]["test_source"] for name in values}}
