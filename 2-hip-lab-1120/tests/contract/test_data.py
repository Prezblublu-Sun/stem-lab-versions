"""数据和一份预测：好样本过，坏样本被点名哪里不符。"""
from __future__ import annotations

import json

import pytest

from stemlab.contract.formats import data
from stemlab.contract.formats.manifest import check_format, make_manifest, read_manifest, write_manifest
from stemlab.contract.hashing import hash_bytes

P1, P2, F1, F2 = (hash_bytes(text) for text in (b"point 1", b"point 2", b"job 1", b"job 2"))

COLUMNS = [
    {"name": "stem_length", "unit": "mm", "meaning": "柄长", "role": "design"},
    {"name": "load_case", "unit": "1", "meaning": "工况", "role": "condition"},
    {"name": "bone_removed", "unit": "mm3", "meaning": "去骨量，模板化时就有", "role": "pre"},
    {"name": "rotation", "unit": "deg", "meaning": "首次加载的转动", "role": "label"},
    {"name": "slip_p95", "unit": "um", "meaning": "界面滑移的 95 分位，由场算出", "role": "derived"},
    {"name": "interface_slip", "unit": "um", "meaning": "界面各节点的滑移", "role": "field"},
]
ROWS = [
    {"point": P1, "bone_id": "femur042", "round": 1, "fingerprint": F1, "outcome": "finished",
     "values": {"stem_length": 30.0, "load_case": "stair", "bone_removed": 5200.5, "rotation": 0.12, "slip_p95": 41.0},
     "fields": {"interface_slip": "fields/p1/interface_slip.npy"}},
    {"point": P2, "bone_id": "femur042", "round": 2, "fingerprint": F2, "outcome": "misfit",
     "values": {"stem_length": 45.0, "load_case": "stair", "bone_removed": None, "rotation": None, "slip_p95": None},
     "fields": {}},
]
FILES = {"fields/p1/interface_slip.npy": b"\x93NUMPY fake"}

PREDICTED = [column for column in COLUMNS if column["role"] in ("label", "derived")]
GUESSES = [
    {"point": P1, "bone_id": "femur042", "values": {"rotation": 0.11, "slip_p95": 40.0},
     "lower": {"rotation": 0.08, "slip_p95": 30.0}, "upper": {"rotation": 0.16, "slip_p95": 55.0}},
    {"point": P2, "bone_id": "femur042", "values": {"rotation": 0.5, "slip_p95": None},
     "lower": {"rotation": 0.5, "slip_p95": None}, "upper": {"rotation": 0.5, "slip_p95": None}},
]


def make(root, kind="data", rows=None, columns=None, files=None, lines=None, **change):
    """写一个数据或预测的文件夹。change 里的项盖掉清单里的同名项；值是 ... 就把那一项去掉。"""
    rows = (ROWS if kind == "data" else GUESSES) if rows is None else rows
    files = (FILES if kind == "data" else {}) if files is None else files
    columns = (COLUMNS if kind == "data" else PREDICTED) if columns is None else columns
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
    raw = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8") if lines is None else lines
    (root / data.ROWS_FILE).write_bytes(raw)
    extra = {"count": len(rows), "columns": columns}
    if kind == "prediction":
        extra["level"] = 0.95
    extra.update(change)
    manifest = make_manifest(kind, [data.ROWS_FILE, *files], **{key: value for key, value in extra.items() if value is not ...})
    write_manifest(root, manifest)
    return root


def changed(rows, index=0, **over):
    """把第 index 行换几项。值是 ... 就把那一项去掉。"""
    row = {key: value for key, value in {**rows[index], **over}.items() if value is not ...}
    return [row if number == index else other for number, other in enumerate(rows)]


def values(index=0, group="values", rows=ROWS, **over):
    """把第 index 行的 values（或别的一组）换几项。值是 ... 就把那一项去掉。"""
    inner = {key: value for key, value in {**rows[index][group], **over}.items() if value is not ...}
    return changed(rows, index, **{group: inner})


# ---- 数据 ----

def test_good_data_passes(tmp_path):
    assert check_format("data", make(tmp_path / "d")) == []


def test_every_row_carries_the_five_keys_and_every_column_a_unit():
    assert data.ROW_KEYS == ("point", "bone_id", "round", "fingerprint", "outcome")
    assert data.ROLES == ("design", "condition", "pre", "label", "derived", "field")
    assert data.FE_ROLES == ("label", "derived", "field"), "这三种是做了 FE 才有的列：代理的特征里不能有它们"


def test_data_without_fields_is_fine(tmp_path):
    columns = [column for column in COLUMNS if column["role"] != "field"]
    rows = changed(ROWS, 0, fields={})
    assert check_format("data", make(tmp_path / "d", rows=rows, columns=columns, files={})) == []


def test_a_design_or_condition_may_be_a_word_or_a_flag_but_results_are_numbers(tmp_path):
    rows = values(0, stem_length=30, load_case=True)
    assert check_format("data", make(tmp_path / "ok", rows=rows)) == []
    problems = check_format("data", make(tmp_path / "bad", rows=values(0, rotation="small")))
    assert any("rotation" in text and "数" in text for text in problems)


BAD_DATA = [
    ("没有 rows.jsonl", dict(files={"fields/p1/interface_slip.npy": b"x"}, lines=b"", damage="drop_rows"), "rows.jsonl"),
    ("fields 之外还有别的文件", dict(files={**FILES, "notes.txt": b"x"}), "fields/"),
    ("行数对不上", dict(count=3), "3"),
    ("没有行", dict(rows=[], files={}), "空"),
    ("没写 columns", dict(columns=...), "columns"),
    ("columns 不是列表", dict(columns={"rotation": "deg"}), "columns"),
    ("列少了单位", dict(columns=[{k: v for k, v in COLUMNS[0].items() if k != "unit"}, *COLUMNS[1:]]), "unit"),
    ("单位是空的", dict(columns=[dict(COLUMNS[0], unit=""), *COLUMNS[1:]]), "单位"),
    ("含义是空的", dict(columns=[dict(COLUMNS[0], meaning=""), *COLUMNS[1:]]), "含义"),
    ("不认识的 role", dict(columns=[dict(COLUMNS[0], role="input"), *COLUMNS[1:]]), "role"),
    ("列名重复", dict(columns=[*COLUMNS, dict(COLUMNS[3])]), "重复"),
    ("列名不是规定的写法", dict(columns=[dict(COLUMNS[0], name="Stem Length"), *COLUMNS[1:]]), "列名"),
    ("行不是对象", dict(lines=b"[1, 2]\n", count=1), "JSON 对象"),
    ("行不是 JSON", dict(lines=b"{half\n", count=1), "不是合法的 JSON"),
    ("点的哈希不对", dict(rows=changed(ROWS, 0, point="abc")), "点的哈希"),
    ("骨标识不对", dict(rows=changed(ROWS, 0, bone_id="骨 1")), "骨标识"),
    ("轮号是 0", dict(rows=changed(ROWS, 0, round=0)), "轮号"),
    ("轮号是字符串", dict(rows=changed(ROWS, 0, round="1")), "轮号"),
    ("轮号是 true", dict(rows=changed(ROWS, 0, round=True)), "轮号"),
    ("输入指纹不对", dict(rows=changed(ROWS, 0, fingerprint="f" * 63)), "输入指纹"),
    ("结局是空的", dict(rows=changed(ROWS, 0, outcome="")), "结局"),
    ("values 少一列", dict(rows=values(0, rotation=...)), "rotation"),
    ("values 多一列", dict(rows=values(0, extra=1.0)), "extra"),
    ("values 里有场的列", dict(rows=values(0, interface_slip=1.0)), "interface_slip"),
    ("设计是 null", dict(rows=values(0, stem_length=None)), "stem_length"),
    ("条件是 null", dict(rows=values(1, load_case=None)), "load_case"),
    ("结果不是数", dict(rows=values(0, rotation=[0.1])), "rotation"),
    ("结果是 NaN", dict(lines=(json.dumps(ROWS[0]).replace("0.12", "NaN") + "\n" + json.dumps(ROWS[1]) + "\n").encode()), "rotation"),
    ("场指的文件清单里没有", dict(rows=changed(ROWS, 0, fields={"interface_slip": "fields/p9/none.npy"})), "fields/p9/none.npy"),
    ("场的名字不是场的列", dict(rows=changed(ROWS, 0, fields={"rotation": "fields/p1/interface_slip.npy"})), "rotation"),
    ("场不在 fields/ 下", dict(rows=changed(ROWS, 0, fields={"interface_slip": "rows.jsonl"})), "fields/"),
    ("fields 不是对象", dict(rows=changed(ROWS, 0, fields=[])), "fields"),
    ("有没人指着的场文件", dict(files={**FILES, "fields/p3/orphan.npy": b"x"}), "fields/p3/orphan.npy"),
    ("同一个点两行", dict(rows=[ROWS[0], dict(ROWS[1], point=P1)]), "同一个点"),
    ("多了一样键", dict(rows=changed(ROWS, 0, note="hi")), "note"),
]
BAD_DATA += [(f"行缺 {key}", dict(rows=changed(ROWS, 1, **{key: ...})), key) for key in data.ROW_KEYS]


@pytest.mark.parametrize("why,how,word", BAD_DATA, ids=[row[0] for row in BAD_DATA])
def test_bad_data_is_named(tmp_path, why, how, word):
    how = dict(how)
    damage = how.pop("damage", None)
    root = make(tmp_path / "d", **how)
    if damage == "drop_rows":
        (root / data.ROWS_FILE).unlink()
        write_manifest(root, dict(read_manifest(root), files=["fields/p1/interface_slip.npy"]))
    problems = check_format("data", root)
    assert problems and any(word in text for text in problems), f"{why}：{problems}"


def test_many_bad_rows_do_not_flood(tmp_path):
    rows = [dict(ROWS[1], point=hash_bytes(str(n).encode()), round=0) for n in range(60)]
    problems = check_format("data", make(tmp_path / "d", rows=rows, files={}))
    assert len(problems) <= 25 and "还有更多" in problems[-1]


# ---- 一份预测 ----

def test_good_prediction_passes(tmp_path):
    assert check_format("prediction", make(tmp_path / "p", kind="prediction")) == []


BAD_PREDICTIONS = [
    ("没写 level", dict(level=...), "level"),
    ("level 不在 0 和 1 之间", dict(level=1.5), "level"),
    ("level 是 true", dict(level=True), "level"),
    ("列不是预测得了的", dict(columns=[COLUMNS[0], *PREDICTED]), "stem_length"),
    ("一列都没有", dict(columns=[]), "columns"),
    ("下界比值大", dict(rows=values(0, "lower", GUESSES, rotation=0.2)), "rotation"),
    ("上界比值小", dict(rows=values(0, "upper", GUESSES, rotation=0.1)), "rotation"),
    ("有值没有区间", dict(rows=values(0, "upper", GUESSES, slip_p95=None)), "slip_p95"),
    ("没有值却有区间", dict(rows=values(1, "lower", GUESSES, slip_p95=1.0)), "slip_p95"),
    ("缺 upper", dict(rows=changed(GUESSES, 0, upper=...)), "upper"),
    ("带了数据才有的键", dict(rows=changed(GUESSES, 0, round=1)), "round"),
    ("values 少一列", dict(rows=values(0, "values", GUESSES, rotation=...)), "rotation"),
    ("lower 多一列", dict(rows=values(0, "lower", GUESSES, extra=1)), "extra"),
    ("同一个点两行", dict(rows=[GUESSES[0], dict(GUESSES[1], point=P1)]), "同一个点"),
    ("有没人指着的场文件", dict(files={"fields/x.npy": b"x"}), "fields/x.npy"),
    ("fields 之外还有别的文件", dict(files={"notes.txt": b"x"}), "fields/"),
    ("点的哈希不对", dict(rows=changed(GUESSES, 0, point=None)), "点的哈希"),
]

# 预测出来的场：列里多一个场，行里用 fields 说它存在哪个文件（值和区间都在那个文件里，怎么放由代理插件的冻结文件定）
FIELD_GUESSES = [dict(GUESSES[0], fields={"interface_slip": "fields/p1/interface_slip.npy"}), dict(GUESSES[1], fields={})]
WITH_FIELD = dict(rows=FIELD_GUESSES, columns=[*PREDICTED, COLUMNS[5]], files=FILES)
BAD_PREDICTIONS += [
    ("场的名字不是场的列", dict(WITH_FIELD, rows=changed(FIELD_GUESSES, 0, fields={"rotation": "fields/p1/interface_slip.npy"})), "rotation"),
    ("场指的文件清单里没有", dict(WITH_FIELD, rows=changed(FIELD_GUESSES, 0, fields={"interface_slip": "fields/p9/none.npy"})), "fields/p9/none.npy"),
    ("场不在 fields/ 下", dict(WITH_FIELD, rows=changed(FIELD_GUESSES, 0, fields={"interface_slip": "rows.jsonl"})), "fields/"),
    ("fields 不是对象", dict(WITH_FIELD, rows=changed(FIELD_GUESSES, 0, fields=[])), "fields"),
    ("values 里有场的列", dict(WITH_FIELD, rows=values(0, "values", FIELD_GUESSES, interface_slip=1.0)), "interface_slip"),
    ("列里没有场，行里却带了场", dict(WITH_FIELD, columns=PREDICTED), "interface_slip"),
]


def test_a_prediction_may_carry_predicted_fields(tmp_path):
    assert data.PREDICTABLE == ("label", "derived", "field"), "标签、推导量和场都预测得了；设计、条件和建模时的量不是预测出来的"
    assert check_format("prediction", make(tmp_path / "p", kind="prediction", **WITH_FIELD)) == []
    assert check_format("prediction", make(tmp_path / "none", kind="prediction", rows=changed(FIELD_GUESSES, 0, fields={}),
                                           columns=[*PREDICTED, COLUMNS[5]])) == [], "列里有场，这几个点没给出场：可以"
    only = [{"point": P1, "bone_id": "femur042", "values": {}, "lower": {}, "upper": {}, "fields": FIELD_GUESSES[0]["fields"]}]
    assert check_format("prediction", make(tmp_path / "only", kind="prediction", rows=only, columns=[COLUMNS[5]], files=FILES)) == [], \
        "只预测场、一个标量都不预测，也是一份预测"


@pytest.mark.parametrize("why,how,word", BAD_PREDICTIONS, ids=[row[0] for row in BAD_PREDICTIONS])
def test_bad_predictions_are_named(tmp_path, why, how, word):
    problems = check_format("prediction", make(tmp_path / "p", kind="prediction", **how))
    assert problems and any(word in text for text in problems), f"{why}：{problems}"


def test_a_prediction_table_cannot_pass_as_data_and_the_other_way_round(tmp_path):
    as_data = make(tmp_path / "p", kind="prediction")
    write_manifest(as_data, dict(read_manifest(as_data), kind="data"))
    assert check_format("data", as_data)
    as_prediction = make(tmp_path / "d")
    write_manifest(as_prediction, dict(read_manifest(as_prediction), kind="prediction", level=0.95))
    assert check_format("prediction", as_prediction)
