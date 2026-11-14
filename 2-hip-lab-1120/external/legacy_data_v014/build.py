"""把旧数据库（db3406 v0.14 的 scalars.csv）转成本系统的一份数据（data）。只读旧数据库。

    python external/legacy_data_v014/build.py <scalars.csv> <内核包的文件夹> <写到哪个文件夹>

列的名字、单位、含义照内核包的清单（external/kernel_m1_3406 打出来的那个包）：这样这份数据和以后 fea.run 用同一个内核
算出来的数据是同一套列，代理可以把它们放在一起训练，预测也能和新的 FEA 结果按点的哈希对上。

收哪些行：算完的（DONE）、有摩擦模型结果的（rot_first_deg 有数）、不是完整股骨参照、不是扭转之类的特殊工况。
旧库里失败的 22 行（14 个网格失败、8 个不收敛）在本系统里都属于待查，不进数据，这里不收。
同一个点（骨、设计、条件都相同）在旧库里出现几次的，只留第一行（旧库的重复计算是为了量噪声）。
每行的输入指纹用旧作业的编号和代码哈希算；轮号都记 1。场不转。

转出来的文件夹过了格式核对才算成。要用它，再由你登记：种类 data，骨标识 sawbone3406。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from stemlab.contract.formats.manifest import check_format, make_manifest, write_manifest  # noqa: E402
from stemlab.contract.formats.points import point_hash  # noqa: E402
from stemlab.contract.hashing import canonical, hash_json  # noqa: E402

BONE = "sawbone3406"
# 内核包里的列名 -> 旧库里的列名（一样的不用写）
FROM = {"e": "entry_offset_forced_mm", "load_N": "load_R_N", "load_front_deg": "alpha_front_deg", "load_sagit_deg": "alpha_sagit_deg",
        "e_mm": "tpl_e", "A0_mm2": "tpl_A0", "alpha_placed_deg": "tpl_alpha", "contact_templated": "tpl_contact",
        "n_tet": "n_tet_total", "h_mesh_mm": "mesh_h_used_mm", "interface_area": "interface_area_body_mm2"}
WHOLE = ("cycles", "n_tet", "n_pairs")                                   # 这几列是整数


def number(text: str, whole: bool = False):
    if text in ("", "nan", "None", "NaN"):
        return None
    value = float(text)
    return int(value) if whole and value.is_integer() else value


def convert(table: Path, package: Path, out: Path) -> dict:
    listed = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    groups = [("design", "design"), ("conditions", "condition"), ("pre", "pre"), ("labels", "label")]
    columns = [dict(column, role=role) for group, role in groups for column in listed[group]]
    with open(table, newline="", encoding="utf-8") as stream:
        legacy = list(csv.DictReader(stream))
    rows, seen, counts = [], set(), {"旧库的行": len(legacy), "没算完或没有摩擦结果": 0, "特殊工况": 0, "重复的点": 0}
    for old in legacy:
        if old["status"] != "DONE" or old["kind"] == "intact" or number(old["rot_first_deg"]) is None:
            counts["没算完或没有摩擦结果"] += 1
            continue
        if old["torsion"] or old["pose"] or old["femur_id"] != BONE:
            counts["特殊工况"] += 1
            continue
        values = {}
        for column in columns:
            text = old.get(FROM.get(column["name"], column["name"]), "")
            values[column["name"]] = "rule" if column["name"] == "e" and text == "" else number(text, column["name"] in WHOLE)
        point = {"bone_id": BONE, "design": {column["name"]: values[column["name"]] for column in columns if column["role"] == "design"},
                 "conditions": {column["name"]: values[column["name"]] for column in columns if column["role"] == "condition"}}
        if any(value is None for group in ("design", "conditions") for value in point[group].values()):
            counts["特殊工况"] += 1
            continue
        key = point_hash(point)
        if key in seen:
            counts["重复的点"] += 1
            continue
        seen.add(key)
        rows.append({"point": key, "bone_id": BONE, "round": 1, "outcome": "finished", "values": values, "fields": {},
                     "fingerprint": hash_json({"legacy_job": old["job_id"], "code_hash": old["code_hash"]})})
    out.mkdir(parents=True, exist_ok=True)
    (out / "rows.jsonl").write_bytes(b"".join(canonical(row) + b"\n" for row in rows))
    write_manifest(out, make_manifest("data", ["rows.jsonl"], count=len(rows), columns=columns, bone_id=BONE))
    wrong = check_format("data", out)
    if wrong:
        raise SystemExit("转出来的数据不符合格式：" + "；".join(wrong[:5]))
    return dict(counts, 收下的行=len(rows))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    print(json.dumps(convert(*map(Path, sys.argv[1:4])), ensure_ascii=False, indent=1))
