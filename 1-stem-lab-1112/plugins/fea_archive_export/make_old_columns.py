"""生成 old_columns.json：旧表（db3406 的 scalars.csv）的每一列，这个插件导出了没有，没导出是为什么。

只读旧库的 schema.json。旧表的列变了才需要重跑：
    PYTHONUTF8=1 python make_old_columns.py "H:/projects/Femoral implant generation/db3406/v0.14/schema.json"
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fae_columns as C  # noqa: E402

OWN = "旧导出器自己的记录（哪一批、什么时候导出、存在哪个分片、重算误差），不是作业的数据"
RESERVED = "旧表里定义了但一直是空的"
STAB = "要旧管线的 stability.py 由位移场算。位移在界面场和整体场里，以后可以另算"
RESORB = "要旧管线的 resorption，加完整股骨参照作业的应变能"
DBLEVEL = "数据库层面的列：要看整个数据版本的所有行才能定（划分、重复组、排除集）"
CANAL = "要界面节点到髓腔壁的距离，这要股骨几何，归档里没有"
OUTSIDE = "要归档以外的记录（选点记录、批次清单、另补的来源说明）"
FEMUR = "要股骨模型的配置和几何（旧管线的股骨模块），归档里没有"
CODE = "要旧管线的代码文件在场才能算（代码哈希、由代码重算作业号）"
BOUNDS = "要设计空间的上下界。那是选点时的设定，不在归档里"
REF = "要对照另一个作业（完整股骨参照）和股骨几何"
CODES = "旧表由失败原因的文字认出来，要旧管线的 result_codes。FAILED.json 里原有的 code 在 fail_code 列"

BY_NAME = {
    **{n: OWN for n in ("exporter_version", "export_batch", "export_time_utc", "export_host", "export_status",
                        "export_errors", "export_warnings", "field_shard", "field_index")},
    **{n: CANAL for n in ("foam_thk_p05_mm", "foam_thk_p50_mm", "area_foam_lt1_mm2", "F", "F_area_mm2", "F_n_nodes",
                          "F_t_min_mm", "F_frac_floor")},
    **{n: OUTSIDE for n in ("source", "source_detail", "selection", "layer", "manifest_refs", "provenance", "acq_name",
                            "acq_round", "pool_idx", "record_phase", "rot_record_deg", "rot_record_match",
                            "source_job_n_tet_total", "source_job_design_key", "in_family_phases", "solver_basis")},
    **{n: FEMUR for n in ("femur_geom_key", "femur_geom_verified", "femur_geom_basis", "femur_model_version", "hollow_core",
                          "femur_pose_match", "femur_pose_dev_mm", "load_R_N", "alpha_front_deg", "alpha_sagit_deg",
                          "head_coupling_radius_mm", "torque_stem_axis_Nmm", "moment_shoulder_bend_Nmm", "cons_load",
                          "cond_key", "realization_key")},
    **{n: CODE for n in ("code_hash_source", "code_hash_now", "job_id_matches_code", "aux_code_md5")},
    **{n: BOUNDS for n in ("bounds_version", "in_bounds_v1")},
    **{n: REF for n in ("ref_match", "ref_mismatch")},
    "result_code": CODES,
    "result_class": CODES,
}


def reason(col: dict) -> str:
    name, src = col["name"], col["source"]
    if name in BY_NAME:
        return BY_NAME[name]
    if name.startswith("fld_err_"):
        return OWN
    if name.startswith("u_"):
        return BOUNDS
    if col["required"] == "reserved":
        return RESERVED
    if src.startswith("stability.py"):
        return STAB
    if src.startswith("resorption"):
        return RESORB
    if src.startswith("finalize"):
        return DBLEVEL
    return ""


def main() -> int:
    schema = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out, unknown = [], []
    for col in schema["columns"]:
        exported = col["name"] in C.NAMES
        why = "" if exported else reason(col)
        if not exported and not why:
            unknown.append(col["name"])
        out.append({"name": col["name"], "exported": exported, "why_not": why, "old_source": col["source"]})
    if unknown:
        print("没有归类的列：", unknown)
        return 1
    doc = {"old_table": "db3406 scalars.csv", "old_schema_by": schema.get("generated_by"), "n_old_columns": len(out),
           "n_exported": sum(c["exported"] for c in out), "columns": out}
    (HERE / "old_columns.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    counts: dict = {}
    for c in out:
        counts[c["why_not"] or "导出了"] = counts.get(c["why_not"] or "导出了", 0) + 1
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(v, k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
