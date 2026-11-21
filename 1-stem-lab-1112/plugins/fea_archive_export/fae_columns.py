"""标签表有哪些列，每列从哪来。

列名沿用旧表（db3406 的 scalars.csv）里同一个量的名字，这样两张表能按列名对上。
旧表里要靠旧管线代码、归档以外的记录、或整个数据版本才能算的列，这里不导出；
哪些没导出、为什么，见 old_columns.json，汇总时写进「标签说明」。

来源一栏的三种：
  json    归档里的 json 文件、标记文件直接有的，或只由它们算出来的
  界面场  由本插件导出的界面场算的
  本插件  旧表没有的列，本插件自己加的
"""

VERSION = "0.1"
QUANTITIES = ("标签", "界面场", "整体场")

DESIGN_VARS = ("L", "alpha", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")

# result.json 的键 → 列名（名字不同的才写）
RESULT_MAP = {
    "n_pairs": "n_pairs_body",
    "interface_area": "interface_area_body_mm2",
    "vm_p99": "vm_p99_MPa",
    "vm_max": "vm_max_MPa",
    "gruen7_vol_mm3": "intact_gruen7_vol_mm3",
    "gruen1_vol_mm3": "intact_gruen1_vol_mm3",
    "gruen7": "sed_gruen7",
    "gruen1": "sed_gruen1",
}
# result.json 里不当成数值列的键
RESULT_SKIP = {
    "spec", "solve", "templating", "n_tet", "bone_loss", "job_id", "model", "intact_job",
    "intact_substituted_h", "fric_only", "bond_only", "h_cut_mm",
}

_RESULT_FLOAT = (
    "f1_p95_um", "f1_rev_p50_um", "f1_rev_max_um", "f1_first_p95_um", "f1_first_p50_um", "normal_rev_p95_um",
    "area_frac_gt40", "area_frac_gt150", "open_frac_release", "open_frac_load", "open_frac_load2",
    "gap_p95_release_um", "gap_p95_load2_um", "n_pairs_body", "interface_area_body_mm2", "cortex_area_frac",
    "f1_closed_p95_um", "f1_canc_p95_um", "cpress_release_p50", "cpress_release_p95", "cpress_release_max",
    "cpress_release_mean_all", "status_frac_stick", "status_frac_slip", "status_frac_open", "stick_cslip_p95_um",
    "stick_cslip_max_um", "slide_cslip_p95_um", "f1_cslip_p95_um", "frac_open",
    "vm_p99_MPa", "vm_max_MPa", "n_stem_elems_in_bone", "sed_gruen7", "sed_gruen1", "f2_g7_loss_pct", "f2_g1_loss_pct",
    "intact_gruen7_vol_mm3", "intact_gruen1_vol_mm3",
)
_RESULT_INT = {"n_pairs_body", "n_stem_elems_in_bone"}
RESULT_COLS = set(_RESULT_FLOAT)

COLUMNS: list[tuple] = []  # (列名, 类型, 来源, 从哪来)


def _c(name, typ, cls, src):
    COLUMNS.append((name, typ, cls, src))


def _build():
    J, F, P = "json", "界面场", "本插件"
    _c("row_id", "str", J, "= 作业号")
    _c("job_id", "str", J, "归档的名字")
    _c("stage", "str", J, "spec.json stage")
    _c("tag", "str", J, "spec.json tag")
    _c("kind", "str", J, "spec.json kind")
    _c("status", "str", J, "标记文件：DONE、FAILED.json、SOLVED、CLAIMED、READY，按这个顺序第一个有的")
    _c("design_key", "str", J, "13 个设计量各取 6 位小数、用逗号连起来的 sha1；只由 spec.json 算")
    _c("spec_hash", "str", J, "spec.json 去掉 stage、tag、created 之后的 sha1")
    _c("fidelity", "str", J, "h<spec.json h_int>，有 foam_refine 时加 +f5h<h>")
    _c("code_hash", "str", J, "prep.json code_hash。没有 prep.json 时旧表是从作业号反推的，这里留空")
    _c("femur_id", "str", J, "spec.json femur_id")
    _c("neck_axis", "json", J, "spec.json neck_axis")
    _c("solver", "str", J, "solve.json：有 solver 键用它；odb_meta.odb 以 .odb 结尾记 abaqus")
    _c("steps", "json", J, "prep.json steps；没有时用 solve.json 里第一个模型的分析步名")
    _c("collar_rule", "str", J, "spec.json collar_rule")
    _c("margin_check", "str", J, "spec.json margin_check")
    _c("a_bounds_max", "float", J, "spec.json a_bounds_max")
    _c("ref_cut_mm", "float", J, "spec.json ref_cut_mm")
    _c("min_A0_mm2", "float", J, "spec.json min_A0")
    for k in DESIGN_VARS:
        if k == "h_cut":
            src = "spec.json h_cut。没有这个键时旧管线用 25，这里留空"
        elif k == "m":
            src = "spec.json design.m；没有时用 spec.json margin；都没有时旧管线用一个常数，这里留空"
        else:
            src = f"spec.json design.{k}"
        _c(k, "float", J, src)
    _c("cap_h_mm", "float", J, "spec.json design.cap_h")
    _c("collar_w_mm", "float", J, "spec.json design.collar_w；没有这个键就是没有领，记 0")
    _c("delta_spec_mm", "float", J, "spec.json delta")
    _c("delta_mm", "float", J, "prep.json delta")
    _c("mu", "float", J, "prep.json mu")
    _c("E_canc_MPa", "float", J, "prep.json E_canc")
    _c("load_vec_N", "json", J, "prep.json load_N")
    _c("load_vec_norm_N", "float", J, "load_vec_N 的模")
    _c("h_int_mm", "float", J, "spec.json h_int")
    _c("h_int_prep_mm", "float", J, "prep.json h_int，没有时用 h_roi")
    _c("h_far_mm", "float", J, "prep.json h_far")
    _c("slip_tol", "float", J, "prep.json slip_tol")
    _c("cycles", "int", J, "prep.json cycles")
    _c("interference", "str", J, "prep.json interference")
    _c("torque", "bool", J, "prep.json torque")
    _c("entry_offset_forced_mm", "float", J, "spec.json entry_offset")
    _c("torsion", "json", J, "spec.json torsion")
    _c("pose", "json", J, "spec.json pose_fixed")
    _c("foam_refine", "json", J, "spec.json foam_refine")
    _c("cfg_override", "json", J, "spec.json cfg")
    _c("bond_only", "bool", J, "spec.json bond_only")
    _c("fric_only", "bool", J, "spec.json fric_only")
    _c("has_prep", "bool", J, "归档里有 prep.json")
    _c("has_fric_model", "bool", J, "归档里有 m_fric_csv 文件夹（只对完成的 design、variant 作业）")
    _c("has_bond_model", "bool", J, "归档里有 m_bond_csv 文件夹（只对完成的 design、variant 作业）")
    _c("cons_delta", "bool", J, "spec.json delta 和 prep.json delta 相同")
    _c("cons_h_int", "bool", J, "spec.json h_int 和 prep.json h_int（或 h_roi）相同")
    _c("spec_in_result_match", "bool", J, "result.json 里抄的 spec 和 spec.json 相同")
    for k in ("alpha", "e", "A0", "contact", "s_bind", "volume", "margin"):
        _c("tpl_" + k, "float", J, f"prep.json templating.{k}")
    _c("bone_resected_mm3", "float", J, "prep.json bone_loss.resected_mm3")
    _c("bone_reamed_mm3", "float", J, "prep.json bone_loss.reamed_mm3")
    _c("bone_total_mm3", "float", J, "prep.json bone_loss.total_mm3")
    _c("stem_volume_mm3", "float", J, "prep.json stem_volume_mm3")
    _c("fail_level", "str", J, "FAILED.json level")
    _c("fail_stage", "str", J, "FAILED.json stage")
    _c("fail_reason", "str", J, "FAILED.json reason 的前 500 个字符")
    _c("fail_code", "str", P, "FAILED.json code（2026-11-11 之后的失败记录才有）。旧表的 result_code 另外由文字认，这里不认")
    _c("n_tet_cortex", "int", J, "prep.json n_tet.cortex")
    _c("n_tet_cancellous", "int", J, "prep.json n_tet.cancellous")
    _c("n_tet_stem", "int", J, "prep.json n_tet.stem")
    _c("n_tet_total", "int", J, "prep.json n_tet 各项之和")
    _c("n_nodes", "int", J, "prep.json n_nodes")
    _c("n_pairs", "int", J, "prep.json n_pairs")
    _c("n_pairs_cortex", "int", J, "prep.json n_pairs_cortex")
    _c("interface_area_mm2", "float", J, "prep.json interface_area_mm2")
    _c("mesh_algo", "int", J, "prep.json mesh_attempt.algorithm3d")
    _c("mesh_h_used_mm", "float", J, "prep.json mesh_attempt.h_int")
    _c("mesh_section_points", "int", J, "prep.json mesh_attempt.section_points")
    _c("mesh_retries", "int", J, "prep.json mesh_attempt.previous_errors 的条数")
    _c("mesh_min_vol_mm3", "float", J, "prep.json mesh_quality.min_vol 里最小的")
    _c("solve_wall_s_fric", "float", J, "solve.json m_fric.wall_s")
    _c("solve_wall_s_bond", "float", J, "solve.json m_bond.wall_s")
    _c("solve_tries_fric", "int", J, "solve.json m_fric.tries")
    _c("solve_tries_bond", "int", J, "solve.json m_bond.tries")
    _c("extra_result_keys", "json", P, "result.json 里是数值、但上面没有对应列的键，原样放在这里。旧表的同名列还混有 stability.py 的键")
    inv = {v: k for k, v in RESULT_MAP.items()}
    for k in _RESULT_FLOAT:
        key = inv.get(k, k)
        if k in ("sed_gruen7", "sed_gruen1"):
            src = f"result.json {k}（完整股骨作业是 {key}）"
        else:
            src = f"result.json {key}"
        _c(k, "int" if k in _RESULT_INT else "float", J, src)
    _c("intact_job_spec", "str", J, "spec.json intact_job")
    _c("intact_job", "str", J, "result.json intact_job（只对有粘接模型的作业）")
    _c("intact_substituted_h", "float", J, "result.json intact_substituted_h（只对有粘接模型的作业）")
    _c("source_job", "str", J, "spec.json source_job。旧表在这个键没有时还会从批次清单里补，这里不补")
    _c("field_n_nodes", "int", F, "界面场的节点对数")
    _c("field_n_tri", "int", F, "界面场的三角形数")
    _c("tri_area_ratio", "float", F, "三角形面积之和 / 节点面积之和")
    _c("iface_force_load_N", "json", F, "LOAD 步骨侧接触力（CNORMF + CSHEARF）的合力")
    _c("iface_force_err_load", "float", F, "LOAD 步：|合力 - load_vec_N| / |load_vec_N|")
    _c("iface_force_err_load2", "float", F, "LOAD2 步：同上")
    for k, f in (("t_spec_utc", "spec.json"), ("t_prep_utc", "prep.json"), ("t_ready_utc", "READY，没有时用 CLAIMED"),
                 ("t_solved_utc", "SOLVED"), ("t_done_utc", "DONE"), ("t_failed_utc", "FAILED.json")):
        _c(k, "str", J, f"归档里 {f} 的修改时间（UTC）")
    _c("created_local", "str", J, "spec.json created")
    _c("archive_sha256", "str", P, "这个作业的归档文件 .tar.xz 的 sha256")
    _c("archive_bytes", "int", P, "归档文件的大小")
    _c("export_notes", "json", P, "导出这一行时记下的事：缺了什么键、哪里没法核对")


_build()
NAMES = [c[0] for c in COLUMNS]
TYPE = {c[0]: c[1] for c in COLUMNS}
CLASS = {c[0]: c[2] for c in COLUMNS}
assert len(NAMES) == len(set(NAMES)), "列名重了"
