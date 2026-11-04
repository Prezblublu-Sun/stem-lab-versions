"""批 D13（阶段 13 / 14 两臂跑完后的前沿核查，2026-10-25；v2/stage_deck.py 批次 D13）的结果汇总。在 Linux 上运行，
只读队列、结果与代码，只写 --out 目录（默认 ~/mobo_toy_v2/deck/D13/）：

    cd ~/mobo_toy_v2 && PYTHONDONTWRITEBYTECODE=1 nice -n 19 taskset -c 4-11 ./run.sh adhoc/deck_D13_collect.py
        [--ids results/deck_D13_ids.json]   ids 文件（{"jobs": {键: 作业号}}）；测试时换成指向类似旧作业的假 ids
        [--out deck/D13]
        [--stage-deck <stage_deck.py>]      d13_select 从哪个文件取（默认 code/v2/stage_deck.py；没有 d13_select → 前沿表不出、写明原因）
        [--no-fronts]                       不求前沿（只汇总 ids 文件里的作业）

键（stage_deck._d13_specs）：D13_bond_<源作业>（bond_only）、D13_sts_<F1714|F3839>_<源作业>（起身，fric_only + cfg.load）、
D13_mesh_h<1.94|2.06>_<源作业>（fric_only + h_int）。源作业 = 键的后缀；spec.source_job 与之不同或缺失 → 警告；
作业与源作业的 design / h_cut 不同 → 警告（D13 的 spec 是源 spec 的副本，应当相同）；比不了（design 或 h_cut 缺失 / 不是数）→ design_match 空、警告。
模板化同源（tpl_match）：作业与源作业的 tpl_A0 / tpl_alpha / tpl_e / bone_mm3 逐项比（rel_tol 1e-9；jobs.prep 会重新模板化、重新划网格），不同 → 警告。
实际网格（prep.json mesh_attempt：algorithm3d、h_int、section_points、previous_errors）：作业与源作业各自与 (spec h_int（没写 = 2.0）, 1, 40)
  比——model3d_m1.build 失败时会退到 algorithm 10、0.97·h 或 24 / 72 个截面点，这些都改网格（0.97 × 2.0 = 1.94），不同 → 警告。
实际头力（prep.json load_N，模型坐标）：|load_N| 与由它反算的 α_front / α_sagit（model3d_v2.load_vector 的逆），起身作业与期望载荷比
  （stage_deck.D13_STS[键标签]，没载入 stage_deck 或标签不在其中 → spec cfg.load，cfg.load 没写的分量 → 有效 load 节），也与键标签的合力比；
  源作业与它自己有效 load 节的楼梯载荷比；不同 → 警告。
每个作业：状态 DONE / FAILED（FAILED.json 的 level / stage / reason）/ pending（NEW / READY / CLAIMED / SOLVED）/ missing（不在队列里），并且
  bond：股骨距 SED 变化——stage_neckopt._calcar 的口径：resorption.design_rows 固定解剖区 G7、只算皮质的 sed_chg_pct（负 = 屏蔽）与 ssi_pct，
        参照 = spec 的 intact_job（femur_id 作业与 _calcar 相同；没有 femur_id、也没有 intact_job 的 CT 作业 = 标准 CT 参照）。
        注意：带 intact_job 的 CT 作业（没有 femur_id）这里用该 intact_job 作参照，而 _calcar 对 CT 作业用标准 CT 参照——两者不同
        （load_wrap_S1B_high_9f489c18：本脚本 SED 变化 −15.3 %，_calcar +92.7 %）；这种作业 calcar_ref_note 写明并警告。D13 全是 femur_id 3406
        作业（spec 带 PHASES 的 intact_job），与 _calcar 完全一致——
        与柄 vM P99（result.json vm_p99）；加源作业的楼梯载荷摩擦指标（stability.py：转动 rot_first_deg 与自转 / 摆动、LOAD2 完全接触面积、
        下沉；柄身微动 P95 = result f1_p95_um = 记录的 f1_body_p95_um；去骨量 bone_loss.total_mm3）；
  sts：同样的摩擦指标，与源作业（同一设计、楼梯载荷）并列，比值 = 起身 / 楼梯；施加的载荷 = spec.json 的 cfg.load（另记 jobs.femur_for
        合并后的有效 load 节）；
  mesh：同样的指标在 h 1.94 / 2.06 与源作业（h 2.0）比，变化 % = 100 (h − 源) / 源。
前沿表：用 stage_deck.d13_select（与提交时同一函数、同一规则）对当前 results/neckopt_p13.json / p14.json 求 F13 / F14 / P3，按单位立方体坐标 x
  把前沿行并成设计；每个设计列出全部粘接结果：两臂自己的粘接作业（每 5 个提交第 5 个带粘接模型，记录 bonded True）与 D13_bond 作业。
  SED / vM 一律按本作业自己的文件重算，再与状态文件记录里的值核对（不同 → 警告）。两臂没跑完 → 前沿是临时的（d13_unfinished 的问题列进警告）。
不假设不同设计（或不同网格）之间节点编号一致：每个量都是一个作业用自己的网格、自己的节点对算出的标量，作业之间只比较标量。
失败不吞（CLAUDE.md §11）：读不到 / 算不出的量留空，原因写进 *_err 列、警告列表与 d13_summary.json 的 fields_not_found；
  某一行整体算不出（意外异常）→ 该行只留状态与 row_err，并警告，其余行照常。
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import pathlib
import re
import sys
import time

sys.dont_write_bytecode = True      # 只读：导入 code/v2 的模块时不写 __pycache__（只写 --out）
HOME = pathlib.Path.home() / "mobo_toy_v2"
Q, RES = HOME / "queue", HOME / "results"
sys.path.insert(0, str(HOME / "code"))
sys.path.insert(0, str(HOME / "code" / "v2"))
import jobs as J  # noqa: E402
import stability as S  # noqa: E402

BOND_PREFIX = "D13_bond_"
KEY_RE = (("bond", re.compile(r"^D13_bond_(?P<src>.+)$")),
          ("sts", re.compile(r"^D13_sts_(?P<label>F[0-9.]+)_(?P<src>.+)$")),
          ("mesh", re.compile(r"^D13_mesh_h(?P<label>[0-9.]+)_(?P<src>.+)$")))
# stability.py 的键（CSV 全列；md 只用 CMP）
STAB_KEYS = ("rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "rot_rev_deg", "rot_perm_deg", "subsid_first_um", "subsid_perm_um",
             "lateral_first_um", "slip_axial_p95_um", "slip_circ_p95_um", "contact_area_load_mm2", "contact_frac_load",
             "contact_area_load2_mm2", "contact_frac_load2", "body_interface_mm2", "rigid_fit_rms_first_um",
             "bench_cx_rot_perm_deg", "bench_cx_subsid_perm_um")
CMP = ("rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "contact_area_load2_mm2", "contact_frac_load2", "f1_body_p95_um",
       "subsid_first_um")
REC_CHECK = (("sed_chg_pct", "sed_chg_pct"), ("ssi_pct", "ssi_pct"), ("vm_p99", "vm_p99"), ("rot_first_deg", "rot_first_deg"),
             ("contact_area_load2_mm2", "contact_area_load2_mm2"), ("f1_body_p95_um", "f1_body_p95_um"), ("bone_mm3", "bone_mm3"))
NEED = {"D13_bond": ("sed_chg_pct", "ssi_pct", "vm_p99", "vm_max", "src_rot_first_deg", "src_contact_area_load2_mm2", "src_f1_body_p95_um",
                     "src_bone_mm3"),
        "D13_sts": CMP + ("spec_load", "load_eff", "load_N_mag") + tuple("src_" + k for k in CMP) + ("src_load_N_mag",),
        "D13_mesh": CMP + ("mesh_h", "mesh_algo", "mesh_sec_pts") + tuple("src_" + k for k in CMP) + ("src_mesh_h", "src_mesh_algo", "src_mesh_sec_pts"),
        "arm_bonded": ("sed_chg_pct", "ssi_pct", "vm_p99", "vm_max", "rot_first_deg", "contact_area_load2_mm2", "f1_body_p95_um", "bone_mm3")}
MESH_H_DEFAULT = 2.0                    # config_v2a.yaml mesh.h_int_mm（spec 没写 h_int 时 model3d_m1.build 用的值）
MESH_FIRST = (1, 40)                    # model3d_m1.build 的第一次尝试：algorithm3d 1、40 个截面点（失败才退到别的组合）
TPL_KEYS = ("tpl_A0", "tpl_alpha", "tpl_e", "bone_mm3")
LOAD_KEYS = ("resultant_N", "alpha_front_deg", "alpha_sagit_deg")
WARN: list = []
_INFO, _STAB, _CAL, _LOAD = {}, {}, {}, {}


def warn(msg: str) -> None:
    WARN.append(msg)
    print("WARNING: " + msg, file=sys.stderr, flush=True)


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {str(e)[:200]}".replace("\n", " | ")


def _rd(p: pathlib.Path):
    return json.loads(p.read_text())


def _f(v):
    """有限浮点或 None。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def job_info(job: str) -> dict:
    """状态 + spec / result / prep / solve 的标量（不含 stability / calcar）。以 _ 开头的键不进 CSV。"""
    if job in _INFO:
        return _INFO[job]
    d = Q / job
    qs = J.state(d)
    out = {"state": {"DONE": "DONE", "FAILED": "FAILED", "MISSING": "missing"}.get(qs, "pending"), "queue_state": qs, "_spec": None}
    if (d / "spec.json").exists():
        try:
            sp = _rd(d / "spec.json")
            out["_spec"] = sp
            cfg = sp.get("cfg")
            load = cfg.get("load") if isinstance(cfg, dict) else None
            out.update({"femur_id": sp.get("femur_id"), "spec_kind": sp.get("kind"), "spec_stage": sp.get("stage"), "spec_tag": sp.get("tag"),
                        "spec_source_job": sp.get("source_job"), "spec_bond_only": bool(sp.get("bond_only")),
                        "spec_fric_only": bool(sp.get("fric_only")), "spec_h_int": sp.get("h_int"), "spec_intact_job": sp.get("intact_job"),
                        "spec_load": json.dumps(load, sort_keys=True) if load is not None else None, "spec_load_case": sp.get("load_case"),
                        "spec_delta": sp.get("delta"), "h_cut": sp.get("h_cut"), "design": json.dumps(sp.get("design"), sort_keys=True)})
        except Exception as e:                                                  # noqa: BLE001
            out["spec_err"] = _err(e)
            warn(f"{job}: spec.json unreadable: {out['spec_err']}")
    if out["state"] == "FAILED":
        try:
            fl = _rd(d / "FAILED.json")
            out.update({"fail_level": fl.get("level"), "fail_stage": fl.get("stage"),
                        "fail_reason": (fl.get("reason") or "")[:300].replace("\n", " | "), "fail_time": fl.get("time")})
        except Exception as e:                                                  # noqa: BLE001
            out["fail_err"] = _err(e)
            warn(f"{job}: FAILED.json unreadable: {out['fail_err']}")
    if out["state"] == "DONE":
        try:
            res = _rd(d / "result.json")
        except Exception as e:                                                  # noqa: BLE001
            out["result_err"] = _err(e)
            warn(f"{job}: DONE but result.json unreadable: {out['result_err']}")
            _INFO[job] = out
            return out
        prep = {}
        if (d / "prep.json").exists():
            try:
                prep = _rd(d / "prep.json")
            except Exception as e:                                              # noqa: BLE001
                out["prep_err"] = _err(e)
                warn(f"{job}: prep.json unreadable: {out['prep_err']}")
        sol = res.get("solve")
        if not isinstance(sol, dict) and (d / "solve.json").exists():
            try:
                sol = _rd(d / "solve.json")
            except Exception as e:                                              # noqa: BLE001
                out["solve_err"] = _err(e)
                warn(f"{job}: solve.json unreadable (wall times left empty): {out['solve_err']}")
        sol = sol if isinstance(sol, dict) else {}
        t = res.get("templating") or prep.get("templating") or {}
        t = t if isinstance(t, dict) else {}
        ma = prep.get("mesh_attempt")
        if not isinstance(ma, dict):
            out["mesh_err"] = f"prep.json has no mesh_attempt dict ({'no prep.json' if not prep else type(ma).__name__})"
            ma = {}
        nt = prep.get("n_tet") or res.get("n_tet") or {}
        n_tet = None
        if isinstance(nt, dict) and nt:
            vals = [_f(v) for v in nt.values()]
            if all(v is not None for v in vals):
                n_tet = int(round(sum(vals)))
            else:
                out["n_tet_err"] = f"non-numeric n_tet values: {json.dumps(nt, default=str)[:200]}"
        elif _f(nt) is not None:
            n_tet = int(round(_f(nt)))
        pe = ma.get("previous_errors")
        out.update({"vm_p99": res.get("vm_p99"), "vm_max": res.get("vm_max"), "f1_body_p95_um": res.get("f1_p95_um"),
                    "f1_all_p95_um": res.get("f1_all_p95_um"), "f2_g7_loss_pct": res.get("f2_g7_loss_pct"),
                    "bone_mm3": (res.get("bone_loss") or {}).get("total_mm3"), "res_intact_job": res.get("intact_job"),
                    "res_bond_only": bool(res.get("bond_only")), "res_fric_only": bool(res.get("fric_only")),
                    "mesh_h": ma.get("h_int"), "mesh_algo": ma.get("algorithm3d"), "mesh_sec_pts": ma.get("section_points"),
                    "mesh_n_prev_err": len(pe) if isinstance(pe, list) else (None if pe is None else 1),
                    "mesh_prev_err": " || ".join(str(x) for x in pe)[:600] if isinstance(pe, list) and pe else None,
                    "n_tet": n_tet, "n_pairs": prep.get("n_pairs"),
                    "tpl_alpha": t.get("alpha"), "tpl_e": t.get("e"), "tpl_A0": t.get("A0"),
                    "wall_fric_s": (sol.get("m_fric") or {}).get("wall_s"), "wall_bond_s": (sol.get("m_bond") or {}).get("wall_s"),
                    "has_m_fric_csv": (d / "m_fric_csv").is_dir(), "has_m_bond_csv": (d / "m_bond_csv").is_dir()})
        out.update(applied_load(prep))
    _INFO[job] = out
    return out


def applied_load(prep: dict) -> dict:
    """prep.json load_N（模型坐标，+x 内侧、+y 后方、+z 向上）→ |F| 与 α_front / α_sagit（model3d_v2.load_vector 的逆：
    F = (−tan α_f · fz, tan α_s · fz, −fz)；torque False 时 F_y = 0 → α_sagit 0）。读不到 → load_N_err。"""
    out = {"load_N_mag": None, "load_alpha_front_deg": None, "load_alpha_sagit_deg": None, "load_torque": prep.get("torque")}
    F = prep.get("load_N")
    if not isinstance(F, (list, tuple)) or len(F) != 3 or any(_f(v) is None for v in F):
        out["load_N_err"] = f"prep.json load_N missing or not 3 finite numbers: {json.dumps(F, default=str)[:120]}"
        return out
    F = [float(v) for v in F]
    out["load_N_mag"] = math.sqrt(sum(v * v for v in F))
    if F[2] >= 0.0:
        out["load_N_err"] = f"prep.json load_N z component {F[2]:g} >= 0 (expected a downward head force); angles not derived"
        return out
    out["load_alpha_front_deg"] = math.degrees(math.atan(F[0] / F[2]))
    out["load_alpha_sagit_deg"] = math.degrees(math.atan(-F[1] / F[2]))
    return out


def stab_of(job: str) -> dict:
    """stability.stability（只读 m_fric_csv + mesh3d.npz）；没有 m_fric_csv（bond_only）→ 不算、写明。"""
    if job not in _STAB:
        if not (Q / job / "m_fric_csv").is_dir():
            inf = job_info(job)
            _STAB[job] = {"err": f"no m_fric_csv (spec bond_only={inf.get('spec_bond_only')}, result bond_only={inf.get('res_bond_only')})"}
        else:
            try:
                _STAB[job] = {"ok": S.stability(Q / job)}
            except Exception as e:                                              # noqa: BLE001
                _STAB[job] = {"err": _err(e)}
                warn(f"{job}: stability failed: {_STAB[job]['err']}")
    return _STAB[job]


def calcar_of(job: str) -> dict:
    """stage_neckopt._calcar 的口径（G7 固定区、皮质；参照 = spec 的 intact_job），出错不吞：calcar_err 写原因。"""
    if job not in _CAL:
        out = {"ssi_pct": None, "sed_chg_pct": None}
        try:
            import numpy as np
            import resorption as RS
            if not (Q / job / "m_bond_csv").is_dir():
                inf = job_info(job)
                raise FileNotFoundError(f"no m_bond_csv (spec fric_only={inf.get('spec_fric_only')}, result fric_only={inf.get('res_fric_only')})")
            spec = _rd(Q / job / "spec.json")
            iname = spec.get("intact_job")
            if spec.get("femur_id") and not iname:
                raise ValueError(f"femur_id {spec['femur_id']!r} job without intact_job: no reference for the calcar index")
            if not spec.get("femur_id") and iname:
                out["calcar_ref_note"] = (f"CT job with intact_job {iname}: reference = that job, unlike stage_neckopt._calcar "
                                          "(standard CT reference for CT jobs)")
                warn(f"{job}: calcar SED reference: {out['calcar_ref_note']}")
            rows, _ = RS.design_rows(job, iname=iname)
            g7 = next((r for r in rows if r["scheme"] == "fixed" and r["zone"] == "G7" and r["tissue"] == "cortex"), None)
            if g7 is None:
                raise LookupError("resorption.design_rows has no fixed / G7 / cortex row")
            for k in ("ssi_pct", "sed_chg_pct"):
                v = g7.get(k)
                out[k] = None if v is None or not np.isfinite(v) else float(v)
            out["calcar_ref"] = iname or "standard CT reference"
            if out["sed_chg_pct"] is None or out["ssi_pct"] is None:
                out["calcar_err"] = f"non-finite G7 cortex value(s): ssi {g7.get('ssi_pct')}, sed_chg {g7.get('sed_chg_pct')}"
        except Exception as e:                                                  # noqa: BLE001
            out["calcar_err"] = _err(e)
        if out.get("calcar_err"):
            warn(f"{job}: calcar SED: {out['calcar_err']}")
        _CAL[job] = out
    return _CAL[job]


def load_eff(job: str) -> dict:
    """jobs.femur_for 合并 cfg 之后本作业的 load 节（= model3d_m1 用的头力参数）。"""
    if job not in _LOAD:
        try:
            _LOAD[job] = {"load_eff": json.dumps(J.femur_for(_rd(Q / job / "spec.json")).cfg.get("load"), sort_keys=True, default=float)}
        except Exception as e:                                                  # noqa: BLE001
            _LOAD[job] = {"load_eff": None, "load_eff_err": _err(e)}
            warn(f"{job}: effective load not found: {_LOAD[job]['load_eff_err']}")
    return _LOAD[job]


def public(info: dict, prefix: str = "") -> dict:
    return {prefix + k: v for k, v in info.items() if not k.startswith("_")}


def metrics(job: str, prefix: str = "", sed: bool = False, load: bool = False) -> dict:
    """一个作业的全部量（状态、result 标量、stability、可选 calcar 与有效载荷），键加 prefix。"""
    info = job_info(job)
    r = public(info, prefix)
    if info["state"] != "DONE" or info.get("result_err"):
        return r
    st = stab_of(job)
    if "ok" in st:
        r.update({prefix + k: st["ok"].get(k) for k in STAB_KEYS})
    else:
        r[prefix + "stab_err"] = st["err"]
    if sed:
        r.update({prefix + k: v for k, v in calcar_of(job).items()})
    if load:
        r.update({prefix + k: v for k, v in load_eff(job).items()})
    return r


def _load_of(spec) -> dict | None:
    """spec 的 cfg.load（dict），没有或不是 dict → None（不抛异常）。"""
    cfg = spec.get("cfg") if isinstance(spec, dict) else None
    L = cfg.get("load") if isinstance(cfg, dict) else None
    return L if isinstance(L, dict) else None


def _json_dict(s) -> dict | None:
    if isinstance(s, dict):
        return s
    try:
        v = json.loads(s) if isinstance(s, str) else None
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def _close(a, b, kind: str = "N") -> bool:
    """力：rel_tol 1e-6；角度（kind 以 _deg 结尾）：abs 1e-6°。任一不是有限数 → False。"""
    a, b = _f(a), _f(b)
    if a is None or b is None:
        return False
    return abs(a - b) <= 1e-6 if kind.endswith("_deg") else math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


def design_cmp(a: dict | None, b: dict | None) -> tuple:
    """(True / False / None, 说明)。None = 比不了：spec 缺失、design 缺失或不是 dict、h_cut 缺失或不是数。"""
    if not a or not b:
        return None, "spec.json missing or unreadable on " + ("the job" if not a else "the source")
    da, db = a.get("design"), b.get("design")
    if not isinstance(da, dict) or not isinstance(db, dict):
        return None, f"design missing or not a dict (job {type(da).__name__}, source {type(db).__name__})"
    ha, hb = _f(a.get("h_cut")), _f(b.get("h_cut"))
    if ha is None or hb is None:
        return None, f"h_cut missing or not numeric (job {a.get('h_cut')!r}, source {b.get('h_cut')!r})"
    if set(da) != set(db):
        return False, f"design keys differ: only job {sorted(set(da) - set(db))}, only source {sorted(set(db) - set(da))}"
    diff = [f"{k} {da[k]!r} vs {db[k]!r}" for k in sorted(da)
            if not ((_f(da[k]) is not None and _f(db[k]) is not None and math.isclose(_f(da[k]), _f(db[k]), rel_tol=1e-9, abs_tol=1e-12))
                    or da[k] == db[k])]
    if not math.isclose(ha, hb, rel_tol=1e-9):
        diff.append(f"h_cut {ha:g} vs {hb:g}")
    return (not diff), ("; ".join(diff) if diff else None)


def design_match(a: dict | None, b: dict | None):
    return design_cmp(a, b)[0]


def tpl_cmp(r: dict) -> tuple:
    """作业 vs 源作业的模板化与去骨量（TPL_KEYS，rel_tol 1e-9）：(True / False / None, 说明)；任一方没 DONE → (None, None)。"""
    if r.get("state") != "DONE" or r.get("src_state") != "DONE":
        return None, None
    miss = [k for k in TPL_KEYS if _f(r.get(k)) is None or _f(r.get("src_" + k)) is None]
    diffs = [f"{k} {_f(r[k]):.10g} vs source {_f(r['src_' + k]):.10g}" for k in TPL_KEYS
             if k not in miss and not math.isclose(_f(r[k]), _f(r["src_" + k]), rel_tol=1e-9, abs_tol=1e-12)]
    if diffs:
        return False, "; ".join(diffs + ([f"not compared: {', '.join(miss)}"] if miss else []))
    if miss:
        return None, f"not available on the job or the source: {', '.join(miss)}"
    return True, None


def mesh_check(r: dict, p: str = "") -> tuple:
    """实际网格 (mesh_h, mesh_algo, mesh_sec_pts) vs 第一次尝试 (spec h_int（没写 = 2.0）, 1, 40)：(True / False / None, 说明)；没 DONE → (None, None)。"""
    if r.get(p + "state") != "DONE":
        return None, None
    h_exp = _f(r.get(p + "spec_h_int"))
    h_exp = MESH_H_DEFAULT if h_exp is None else h_exp
    got = (_f(r.get(p + "mesh_h")), r.get(p + "mesh_algo"), r.get(p + "mesh_sec_pts"))
    if any(v is None for v in got):
        return None, f"mesh_attempt not available ({r.get(p + 'mesh_err') or 'missing keys'}): h {got[0]}, algorithm {got[1]}, section points {got[2]}"
    same = math.isclose(got[0], h_exp, rel_tol=1e-9) and _f(got[1]) == MESH_FIRST[0] and _f(got[2]) == MESH_FIRST[1]
    txt = (f"actual h {got[0]:g} / algorithm {got[1]} / {got[2]} section points vs expected h {h_exp:g} / {MESH_FIRST[0]} / {MESH_FIRST[1]}"
           + (f"; {r.get(p + 'mesh_n_prev_err')} earlier attempt(s) failed: {r.get(p + 'mesh_prev_err')}" if r.get(p + "mesh_n_prev_err") else ""))
    return same, (None if same else txt)


def _load_diffs(r: dict, p: str, exp: dict, what: str) -> list:
    """实际头力（prep.json load_N 反算的 |F|、α_front、α_sagit，键前缀 p）vs exp（LOAD_KEYS）；exp 没有的分量不比。"""
    got = {"resultant_N": r.get(p + "load_N_mag"), "alpha_front_deg": r.get(p + "load_alpha_front_deg"),
           "alpha_sagit_deg": r.get(p + "load_alpha_sagit_deg")}
    out = []
    for k in LOAD_KEYS:
        e = _f(exp.get(k))
        if e is None:
            continue
        if _f(got[k]) is None:
            out.append(f"applied {k} not available ({r.get(p + 'load_N_err') or 'no prep.json load_N'}) vs {what} {e:g}")
        elif not _close(got[k], e, k):
            out.append(f"applied {k} {_f(got[k]):.6g} vs {what} {e:g}")
    return out


def sts_load(r: dict, label: str | None, sp: dict | None, SD) -> None:
    """起身作业的载荷核对（写 load_expected / load_expected_from / load_check / src_load_check，不同 → 警告）。"""
    key = r["key"]
    eff = _json_dict(r.get("load_eff"))
    spec_L = _load_of(sp) or {}
    tab = getattr(SD, "D13_STS", None) if SD is not None else None
    diffs = []
    if isinstance(tab, dict) and label in tab and isinstance(tab[label], dict):
        exp = {k: tab[label].get(k) for k in LOAD_KEYS}
        frm = f"stage_deck D13_STS[{label}]"
        if sp is not None:
            diffs += [f"spec cfg.load {k} {spec_L.get(k)} vs {frm} {exp[k]}" for k in LOAD_KEYS if not _close(spec_L.get(k), exp[k], k)]
    else:
        exp = {k: spec_L[k] for k in LOAD_KEYS if k in spec_L}
        frm = "spec cfg.load (" + ("stage_deck not loaded" if SD is None else f"label {label} not in stage_deck D13_STS") + ")"
        fill = [k for k in LOAD_KEYS if k not in exp]
        if fill and eff:
            exp.update({k: eff.get(k) for k in fill if k in eff})
            frm += f"; {', '.join(fill)} from the effective load section"
    r["load_expected"] = json.dumps(exp, sort_keys=True)
    r["load_expected_from"] = frm
    if r.get("state") == "DONE":
        if eff is None:
            diffs.append(f"effective load section not available ({r.get('load_eff_err')})")
        else:
            diffs += [f"effective load {k} {eff.get(k)} vs expected {exp[k]}" for k in LOAD_KEYS
                      if _f(exp.get(k)) is not None and not _close(eff.get(k), exp[k], k)]
        diffs += _load_diffs(r, "", exp, "expected")
        lab = _f(label[1:]) if label else None
        if lab is not None and _f(r.get("load_N_mag")) is not None and not _close(r["load_N_mag"], lab):
            diffs.append(f"applied |load_N| {r['load_N_mag']:.6g} N vs key label {label}")
    if sp is not None:
        r["load_check"] = ("ok" if not diffs else "; ".join(diffs)) + ("" if r.get("state") == "DONE" else " (spec only: job not DONE)")
    if diffs:
        warn(f"{key}: sit-to-stand load: {'; '.join(diffs)} (expected from {frm}; prep torque {r.get('load_torque')})")
    if r.get("src_state") == "DONE":
        se = _json_dict(r.get("src_load_eff"))
        sd = ([f"source effective load section not available ({r.get('src_load_eff_err')})"] if se is None else
              _load_diffs(r, "src_", {k: se.get(k) for k in LOAD_KEYS}, "its effective (stair) load"))
        r["src_load_check"] = "ok" if not sd else "; ".join(sd)
        if sd:
            warn(f"{key}: source {r['source_job']} head force: {'; '.join(sd)} (prep torque {r.get('src_load_torque')})")


def check_vs_record(r: dict, job: str, rec: dict | None, prefix: str = "") -> None:
    """记录（状态文件）里的值 vs 本次从作业文件重算的值：两者都有且相对差 > 1e-6 → 警告。"""
    if not rec:
        return
    r[prefix + "rec_phase"] = rec.get("_phase")
    r[prefix + "rec_bonded"] = rec.get("bonded")
    r[prefix + "rec_ok"] = rec.get("ok")
    diffs = []
    for mine, theirs in REC_CHECK:
        a, b = _f(r.get(prefix + mine)), _f(rec.get(theirs))
        r[prefix + "rec_" + theirs] = rec.get(theirs)
        if a is not None and b is not None and abs(a - b) > 1e-6 * max(1.0, abs(b)):
            diffs.append(f"{mine} {a:.6g} vs record {b:.6g}")
    r[prefix + "rec_check"] = "; ".join(diffs) if diffs else "ok"
    if diffs:
        warn(f"{job}: recomputed values differ from the state-file record: {'; '.join(diffs)}")


def d13_row(key: str, job: str, group: str, label: str | None, src: str, recs: dict, SD=None) -> dict:
    info = job_info(job)
    r = {"group": "D13_" + group, "key": key, "job": job, "label": label, "source_job": src}
    r.update(metrics(job, sed=(group == "bond"), load=(group == "sts")))
    sp = info.get("_spec")
    if sp is not None:
        if sp.get("source_job") is None:
            warn(f"{key}: spec.json of {job} has no source_job (source taken from the key: {src})")
        elif sp["source_job"] != src:
            warn(f"{key}: spec.source_job {sp['source_job']} != key suffix {src} (source taken from the key)")
        flag = {"bond": ("bond_only", bool(sp.get("bond_only"))), "sts": ("fric_only + cfg.load", bool(sp.get("fric_only")) and bool(_load_of(sp))),
                "mesh": ("fric_only + h_int", bool(sp.get("fric_only")) and sp.get("h_int") is not None)}[group]
        if not flag[1]:
            warn(f"{key}: {job} is not a {flag[0]} job (spec kind {sp.get('kind')!r} stage {sp.get('stage')!r}) — not a D13 spec")
        if group == "sts":
            want = _f(label[1:])
            got = _f((_load_of(sp) or {}).get("resultant_N"))
            if want is not None and got is not None and not math.isclose(want, got):
                warn(f"{key}: key label {label} but spec cfg.load resultant_N = {got:g} N")
        if group == "mesh" and _f(label) is not None and _f(sp.get("h_int")) is not None and not math.isclose(float(label), float(sp["h_int"])):
            warn(f"{key}: key label h{label} but spec h_int = {sp['h_int']}")
    r.update(metrics(src, prefix="src_", load=(group == "sts")))
    src_sp = job_info(src).get("_spec")
    r["design_match"], r["design_diff"] = design_cmp(sp, src_sp)
    if r["design_match"] is False:
        warn(f"{key}: {job} and its source {src} have different design / h_cut: {r['design_diff']}")
    elif r["design_match"] is None and sp is not None and src_sp is not None:
        warn(f"{key}: design / h_cut of {job} and its source {src} not compared: {r['design_diff']}")
    r["tpl_match"], r["tpl_diff"] = tpl_cmp(r)
    if r["tpl_match"] is False:
        warn(f"{key}: templating differs from source {src}: {r['tpl_diff']}")
    elif r["tpl_match"] is None and r["tpl_diff"]:
        warn(f"{key}: templating of {job} vs source {src} not compared: {r['tpl_diff']}")
    for p, jb in (("", job), ("src_", src)):
        ok, txt = mesh_check(r, p)
        r[p + "mesh_check"] = "ok" if ok else txt
        if ok is False:
            warn(f"{key}: {'source ' if p else ''}{jb} mesh is not the first attempt: {txt}")
        elif ok is None and txt:
            warn(f"{key}: {'source ' if p else ''}{jb} mesh not checked: {txt}")
    if group == "sts":
        sts_load(r, label, sp, SD)
    elif r.get("state") == "DONE" and r.get("src_state") == "DONE":
        if _f(r.get("src_load_N_mag")) is None:
            r["load_check"] = f"not compared: source applied load not available ({r.get('src_load_N_err')})"
            warn(f"{key}: head force vs source {src} {r['load_check']}")
        else:
            d = _load_diffs(r, "", {"resultant_N": r.get("src_load_N_mag"), "alpha_front_deg": r.get("src_load_alpha_front_deg"),
                                    "alpha_sagit_deg": r.get("src_load_alpha_sagit_deg")}, "source applied")
            r["load_check"] = "ok" if not d else "; ".join(d)
            if d:
                warn(f"{key}: head force differs from source {src}: {r['load_check']}")
    if group == "mesh" and _f(r.get("src_spec_h_int")) not in (None, 2.0):
        warn(f"{key}: source {src} has h_int {r.get('src_spec_h_int')}, not 2.0")
    if group == "sts" and r.get("src_spec_load") is not None:
        warn(f"{key}: source {src} itself has cfg.load {r['src_spec_load']} (not the default stair load)")
    if r["src_state"] != "DONE":
        warn(f"{key}: source job {src} is {r['src_state']} ({r.get('src_queue_state')})")
    check_vs_record(r, job, recs.get(job))
    check_vs_record(r, src, recs.get(src), prefix="src_")
    for m in CMP:
        a, b = _f(r.get(m)), _f(r.get("src_" + m))
        if group == "sts":
            r["ratio_" + m] = a / b if a is not None and b not in (None, 0.0) else None
        elif group == "mesh":
            r["pct_" + m] = 100.0 * (a - b) / b if a is not None and b not in (None, 0.0) else None
    if group == "mesh":
        for m in ("n_tet", "n_pairs"):
            a, b = _f(r.get(m)), _f(r.get("src_" + m))
            r["pct_" + m] = 100.0 * (a - b) / b if a is not None and b not in (None, 0.0) else None
    return r


def arm_row(job: str, recs: dict) -> dict:
    r = {"group": "arm_bonded", "key": "", "job": job, "label": None, "source_job": job}
    r.update(metrics(job, sed=True))
    check_vs_record(r, job, recs.get(job))
    return r


def load_sd(path: str | None):
    if path:
        spec = importlib.util.spec_from_file_location("stage_deck_d13", str(pathlib.Path(path).resolve()))
        SD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(SD)
    else:
        import stage_deck as SD
    if not hasattr(SD, "d13_select"):
        raise AttributeError(f"{SD.__file__} has no d13_select (Linux code not synced with the D13 version of stage_deck.py?)")
    return SD


def _xkey(rec: dict) -> tuple:
    return tuple(round(float(v), 9) for v in rec["x"])                 # 与 stage_deck._d13_row 的 key 相同


def fronts(ids_jobs: dict, SD, sd_err: str | None, recs: dict, st: dict) -> dict:
    """F13 / F14 / P3（stage_deck.d13_select），按 x 并成设计。失败 → {"err": 原因}（前沿表不出，原因写进 md / json）。"""
    if SD is None:
        return {"err": sd_err or "stage_deck not loaded"}
    if st.get("err"):
        return {"err": st["err"]}
    prior, unmatched = {}, []
    for k, j in ids_jobs.items():
        if k.startswith(BOND_PREFIX):
            if k[len(BOND_PREFIX):] in recs:
                prior[k] = j
            else:
                unmatched.append(k)
    for k in unmatched:
        warn(f"{k}: source job {k[len(BOND_PREFIX):]} is in neither state file's records; it cannot be matched to a front design")
    try:
        sel = SD.d13_select(st[13], st[14], prior=prior)
    except SystemExit as e:                                                     # d13_select 拒绝时是 SystemExit
        return {"err": f"d13_select refused: {e}"}
    except Exception as e:                                                      # noqa: BLE001
        return {"err": f"d13_select failed: {_err(e)}"}
    try:
        probs = SD.d13_unfinished(st[13], st[14])
    except Exception as e:                                                      # noqa: BLE001
        probs = [f"d13_unfinished failed: {_err(e)}"]
    for p in probs:
        warn("arms not finished, fronts are provisional: " + p)
    for w in sel.get("warnings") or []:
        warn("d13_select: " + w)
    designs = {}
    for name in ("F13", "F14", "P3"):
        for e in sel[name]:
            k = _xkey(recs[e["job_id"]])
            d = designs.setdefault(k, {"entries": [], "fronts": set(), "bonded_jobs": set(), "d13_keys": set()})
            d["entries"].append({**e, "front": name})
            d["fronts"] |= set(e["fronts"])
            d["bonded_jobs"] |= set(e["bonded_jobs"])
            d["d13_keys"] |= set(e.get("d13_keys") or [])
    arm_by_x = {}
    for j, rec in recs.items():                                                # 两臂自己的粘接作业（bonded True，不论记录 ok 与否）
        if rec.get("bonded"):
            arm_by_x.setdefault(_xkey(rec), []).append(j)
    left_out = {e["job_id"] for e in sel["bond_left_out"]}
    new_bond = {e["job_id"] for e in sel["bond"]}
    out = []
    for k, d in designs.items():
        ff = [e for e in d["entries"] if e["front"] != "P3"]
        rep = sorted(ff or d["entries"], key=lambda e: (e["phase"], e["job_id"]))[0]["job_id"]
        rr = recs[rep]
        out.append({"rep_job": rep, "fronts": "+".join(sorted(d["fronts"])), "front_jobs": ",".join(sorted({e["job_id"] for e in d["entries"]})),
                    "rot_first_deg": rr.get("rot_first_deg"), "rot_axial_first_deg": rr.get("rot_axial_first_deg"),
                    "rot_tilt_first_deg": rr.get("rot_tilt_first_deg"), "contact_area_load2_mm2": rr.get("contact_area_load2_mm2"),
                    "f1_body_p95_um": rr.get("f1_body_p95_um"), "bone_mm3": rr.get("bone_mm3"),
                    "usable_bonded_jobs": sorted(d["bonded_jobs"]), "arm_bonded_jobs": sorted(arm_by_x.get(k, [])),
                    "d13_bond_keys": sorted(d["d13_keys"]), "dropped_by_cap": rep in left_out,
                    "selection_would_add_bond": rep in new_bond and not d["d13_keys"], "_x": k})
    out.sort(key=lambda d: (_f(d["rot_first_deg"]) if _f(d["rot_first_deg"]) is not None else 1e9, d["rep_job"]))
    return {"designs": out, "sts": sel["sts"], "mesh": sel["mesh"], "unmatched_bond_keys": unmatched, "unfinished": probs,
            "stage_deck": str(getattr(SD, "__file__", "?")),
            "summary": SD._d13_summary(sel) if hasattr(SD, "_d13_summary") else None,
            "n": {"F13": len(sel["F13"]), "F14": len(sel["F14"]), "P3": len(sel["P3"]), "designs": len(out)}}


def read_states() -> dict:
    st = {}
    try:
        for p in (13, 14):
            st[p] = _rd(RES / f"neckopt_p{p}.json")
            if st[p].get("phase") != p:
                raise ValueError(f"neckopt_p{p}.json holds phase {st[p].get('phase')!r}")
    except Exception as e:                                                      # noqa: BLE001
        return {"err": f"state files: {_err(e)}"}
    return st


# ---------------------------------------------------------------- 输出
def fmt(v, nd=1, pct=False):
    v2 = _f(v)
    if v2 is None:
        return "—" if v is None else str(v)
    return (f"{v2:+.{nd}f}" if pct else f"{v2:.{nd}f}")


def rot3(r, p=""):
    return f"{fmt(r.get(p + 'rot_first_deg'), 4)} ({fmt(r.get(p + 'rot_axial_first_deg'), 4)} / {fmt(r.get(p + 'rot_tilt_first_deg'), 4)})"


def state_txt(r):
    s = r.get("state")
    if s == "FAILED":
        return f"FAILED {r.get('fail_level')}/{r.get('fail_stage')}"
    if s == "pending":
        return f"pending ({r.get('queue_state')})"
    return (s or "—") + (" (row_err)" if r.get("row_err") else "")


def tpl_txt(r):
    m = r.get("tpl_match")
    return "同" if m is True else "不同（见警告）" if m is False else ("比不了（见警告）" if r.get("tpl_diff") else "—")


def _ok(c) -> bool:
    return isinstance(c, str) and c.startswith("ok")


def check_txt(job_c, src_c=None):
    """作业 / 源作业的核对列（"ok…" / 说明 / None = 没核对）→ md 短文本。"""
    if job_c is None and src_c is None:
        return "—"
    if any(c is not None and not _ok(c) for c in (job_c, src_c)):
        return "不符（见警告）"
    if job_c == "ok" and _ok(src_c):
        return "ok"
    return (f"作业 {'ok' if job_c == 'ok' else '只核对了 spec' if _ok(job_c) else '没核对'}；"
            f"源 {'ok' if _ok(src_c) else '没核对'}")


def load_txt(r, p=""):
    return f"{fmt(r.get(p + 'load_N_mag'), 0)} / {fmt(r.get(p + 'load_alpha_front_deg'), 1)} / {fmt(r.get(p + 'load_alpha_sagit_deg'), 1)}"


def mesh_txt(r, p=""):
    def v(k):
        x = r.get(p + k)
        return "—" if x is None else str(x)
    n = r.get(p + "mesh_n_prev_err")
    return f"{fmt(r.get(p + 'mesh_h'), 2)} / {v('mesh_algo')} / {v('mesh_sec_pts')}" + (f"（前 {n} 次失败）" if n else "")


def min_gap(vals) -> float | None:
    """相邻（排序后）两个值的最小相对差 %（相对于较小者）；不足 2 个正值 → None。"""
    v = sorted(x for x in (_f(x) for x in vals) if x is not None and x > 0)
    g = [100.0 * (b - a) / a for a, b in zip(v, v[1:])]
    return min(g) if g else None


def md_tables(rows, fr, counts, args, meta) -> str:
    L = [f"# 批 D13 结果汇总（{meta['generated']}）", "",
         f"- ids 文件：`{args.ids}`（updated {meta['ids_updated']}）；输出：`{args.out}`；代码 {meta['code_version']}",
         f"- 状态文件：阶段 13 {meta['state13']}；阶段 14 {meta['state14']}", ""]
    L += ["## 计数", "", "| 组 | 作业 | DONE | FAILED | pending | missing |", "|---|---|---|---|---|---|"]
    for g, c in counts.items():
        L.append(f"| {g} | {c['n']} | {c.get('DONE', 0)} | {c.get('FAILED', 0)} | {c.get('pending', 0)} | {c.get('missing', 0)} |")
    if fr.get("n"):
        L += ["", f"前沿：F13 {fr['n']['F13']} 行、F14 {fr['n']['F14']} 行、P3 {fr['n']['P3']} 行 → {fr['n']['designs']} 个不同设计"
              + ("（两臂还没跑完，前沿是临时的）" if fr.get("unfinished") else "") + f"；d13_select 取自 `{fr.get('stage_deck')}`"]
    # 表 1
    L += ["", "## 表 1　前沿设计的粘接结果（股骨距 G7 皮质 SED 变化、柄 vM P99）", ""]
    by_job, by_gj = {}, {}
    for r in rows:
        by_job.setdefault(r["job"], []).append(r)
        by_gj.setdefault((r["group"], r["job"]), r)
    by_key = {r["key"]: r for r in rows if r["key"]}
    if fr.get("err"):
        L.append(f"前沿没有算出：{fr['err']}。下面只列 ids 文件里的 D13_bond 作业。")
        L += ["", "| 键 | 作业 | 状态 | SED 变化 % | SSI % | vM P99 MPa | 源作业楼梯：转动° (自转/摆动) | 接触 mm² | 微动 µm | 去骨 mm³ | 模板同源 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            if r["group"] == "D13_bond":
                L.append(f"| {r['key']} | {r['job']} | {state_txt(r)} | {fmt(r.get('sed_chg_pct'))} | {fmt(r.get('ssi_pct'))} | {fmt(r.get('vm_p99'))} | "
                         f"{rot3(r, 'src_')} | {fmt(r.get('src_contact_area_load2_mm2'), 0)} | {fmt(r.get('src_f1_body_p95_um'))} | {fmt(r.get('src_bone_mm3'), 0)} | "
                         f"{tpl_txt(r)} |")
    else:
        L += ["楼梯载荷指标 = 代表作业在状态文件里的记录（stability.py 同一口径）；粘接结果按作业自己的文件重算。"
              "来源 arm = 两臂自己的粘接作业，D13 = D13_bond 作业；模板同源 = D13 作业与源作业的 A0 / α / e / 去骨量相同（arm 行是源作业本身）。", "",
              "| # | 设计（代表作业） | 前沿 | 转动° (自转/摆动) | 接触 mm² | 微动 µm | 去骨 mm³ | 来源 | 粘接作业 | 状态 | SED 变化 % | SSI % | vM P99 MPa | 模板同源 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for i, d in enumerate(fr["designs"], 1):
            head = (f"| {i} | {d['rep_job']} | {d['fronts']} | {rot3(d)} | {fmt(d['contact_area_load2_mm2'], 0)} | {fmt(d['f1_body_p95_um'])} | "
                    f"{fmt(d['bone_mm3'], 0)} |")
            blank = "| | | | | | | |"
            srcs = ([("arm", j, by_gj.get(("arm_bonded", j)) or by_job.get(j, [{}])[0]) for j in d["arm_bonded_jobs"]]
                    + [("D13", k, by_key.get(k, {})) for k in d["d13_bond_keys"]])
            if not srcs:
                why = ("cap 外（dropped by the cap）" if d["dropped_by_cap"] else
                       "当前选择会新提交 D13_bond（ids 文件里没有）" if d["selection_would_add_bond"] else "—")
                L.append(head + f" — | — | 无粘接结果：{why} | — | — | — | — |")
            for n, (kind, name, r) in enumerate(srcs):
                L.append((head if n == 0 else blank) + f" {kind} | {r.get('job', name)} | {state_txt(r)} | {fmt(r.get('sed_chg_pct'))} | "
                         f"{fmt(r.get('ssi_pct'))} | {fmt(r.get('vm_p99'))} | {'—（同一作业）' if kind == 'arm' else tpl_txt(r)} |")
        nb = sum(1 for d in fr["designs"] if d["arm_bonded_jobs"] or d["d13_bond_keys"])
        ok = sum(1 for d in fr["designs"] if any(_f(r.get("sed_chg_pct")) is not None for j in d["arm_bonded_jobs"] for r in by_job.get(j, []))
                 or any(_f(by_key.get(k, {}).get("sed_chg_pct")) is not None for k in d["d13_bond_keys"]))
        L += ["", f"{len(fr['designs'])} 个前沿设计：{nb} 个有粘接作业，其中 {ok} 个已有 SED 值；"
              f"{len(fr['designs']) - nb} 个没有任何粘接作业。"]
        other = [r for r in rows if r["group"] == "D13_bond" and not any(r["key"] in d["d13_bond_keys"] for d in fr["designs"])]
        if other:
            L += ["", "不在当前前沿上的 D13_bond 作业（过时键或源作业不在记录里）：", "",
                  "| 键 | 状态 | SED 变化 % | SSI % | vM P99 MPa | 源作业转动° | 接触 mm² | 微动 µm | 去骨 mm³ | 模板同源 |", "|---|---|---|---|---|---|---|---|---|---|"]
            for r in other:
                L.append(f"| {r['key']} | {state_txt(r)} | {fmt(r.get('sed_chg_pct'))} | {fmt(r.get('ssi_pct'))} | {fmt(r.get('vm_p99'))} | "
                         f"{fmt(r.get('src_rot_first_deg'), 4)} | {fmt(r.get('src_contact_area_load2_mm2'), 0)} | {fmt(r.get('src_f1_body_p95_um'))} | "
                         f"{fmt(r.get('src_bone_mm3'), 0)} | {tpl_txt(r)} |")
    mesh = [r for r in rows if r["group"] == "D13_mesh"]
    noise_v = [abs(_f(r["pct_rot_first_deg"])) for r in mesh if _f(r.get("pct_rot_first_deg")) is not None]
    noise = max(noise_v) if noise_v else None
    # 表 2
    roles = {e["job_id"]: e.get("role") for e in (fr.get("sts") or [])}
    sts = [r for r in rows if r["group"] == "D13_sts"]
    L += ["", "## 表 2　起身（sit-to-stand）vs 楼梯载荷（同一设计 = 源作业）", "",
          "比值 = 起身 / 楼梯。载荷 cfg.load = 起身作业 spec.json 的 cfg.load（有效 load 节见 CSV 的 load_eff）；施加 = prep.json load_N 的 |F| 与"
          "反算的 α_front / α_sagit（起身作业 / 源作业）；载荷核对 = 与期望载荷（stage_deck D13_STS 或 spec cfg.load，CSV 的 load_expected_from）"
          "及源作业有效楼梯载荷的比较。下沉是有符号的小量（µm 级时接近 0），它的比值只作参考。", "",
          "| 键 | 角色 | 状态 | 载荷 cfg.load | 施加 N / α_f° / α_s°：起身；楼梯 | 载荷核对 | 模板同源 | 转动° 起身 (自转/摆动) | 转动° 楼梯 (自转/摆动) | 比 | "
          "接触 mm² 起身 / 楼梯 | 比 | 微动 µm 起身 / 楼梯 | 比 | 下沉 µm 起身 / 楼梯 | 比 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sts:
        L.append(f"| {r['key']} | {roles.get(r['source_job'], '—')} | {state_txt(r)} | {r.get('spec_load') or '—'} | {load_txt(r)}；{load_txt(r, 'src_')} | "
                 f"{check_txt(r.get('load_check'), r.get('src_load_check'))} | {tpl_txt(r)} | {rot3(r)} | {rot3(r, 'src_')} | "
                 f"{fmt(r.get('ratio_rot_first_deg'), 2)} | {fmt(r.get('contact_area_load2_mm2'), 0)} / {fmt(r.get('src_contact_area_load2_mm2'), 0)} | "
                 f"{fmt(r.get('ratio_contact_area_load2_mm2'), 2)} | {fmt(r.get('f1_body_p95_um'))} / {fmt(r.get('src_f1_body_p95_um'))} | "
                 f"{fmt(r.get('ratio_f1_body_p95_um'), 2)} | {fmt(r.get('subsid_first_um'))} / {fmt(r.get('src_subsid_first_um'))} | "
                 f"{fmt(r.get('ratio_subsid_first_um'), 2)} |")
    if not sts:
        L.append("| （ids 文件里没有 D13_sts 作业） | | | | | | | | | | | | | | | |")
    for lab in sorted({r["label"] for r in sts}):
        done = [r for r in sts if r["label"] == lab and _f(r.get("rot_first_deg")) is not None and _f(r.get("src_rot_first_deg")) is not None]
        if len(done) >= 2:
            a = [r["source_job"] for r in sorted(done, key=lambda r: r["src_rot_first_deg"])]
            b = [r["source_job"] for r in sorted(done, key=lambda r: r["rot_first_deg"])]
            ga, gb = min_gap([r["src_rot_first_deg"] for r in done]), min_gap([r["rot_first_deg"] for r in done])
            gtxt = f"相邻转动的最小相对差：楼梯 {fmt(ga, 1)} %、起身 {fmt(gb, 1)} %"
            gmin = min(g for g in (ga, gb) if g is not None) if (ga is not None or gb is not None) else None
            if noise is None:
                gtxt += "；表 3 没有可用的转动 Δ%，网格噪声未知"
            elif gmin is not None and gmin < noise:
                gtxt += f" < 表 3 最大 |Δ% 转动| {noise:.1f} % → within mesh noise（在网格噪声内，这个排序结论不可靠）"
            else:
                gtxt += f" ≥ 表 3 最大 |Δ% 转动| {noise:.1f} %"
            L.append(f"\n{lab}：转动排序（小 → 大）楼梯 {' < '.join(a)}；起身 {' < '.join(b)} → {'保持' if a == b else '改变'}"
                     f"（{len(done)} 个设计都算完）；{gtxt}")
        else:
            L.append(f"\n{lab}：算完的设计不足 2 个（{len(done)}），排序不比较")
    # 表 3
    mrole = {}
    for i, e in enumerate(fr.get("mesh") or []):                     # d13_select：[0] = 覆盖集转动最小；[1] = F14 去骨居中，F14 没有别的设计时 = 转动第二
        mrole[e["job_id"]] = "转动最小" if i == 0 else ("F14 去骨居中" if "F14" in (e.get("fronts") or []) else "转动第二")
    L += ["", "## 表 3　网格噪声（h_int 1.94 / 2.06 vs 源作业 h 2.0）", "",
          "变化 % = 100 (h − 源) / 源；实际网格 = prep.json mesh_attempt 的 h / algorithm3d / 截面点（第一次尝试 = spec h / 1 / 40；"
          "退到别的组合会改网格，见网格核对与警告）。每个作业用自己的网格与节点对，只比较标量。", "",
          "| 键 | 角色 | 状态 | 网格 h / 算法 / 截面点：作业；源 | 网格核对 | 模板同源 | 四面体数 Δ% | 节点对 Δ% | 转动° h / 源 | Δ% | 自转 Δ% | 摆动 Δ% | "
          "接触 mm² h / 源 | Δ% | 微动 µm h / 源 | Δ% | 下沉 µm h / 源 | Δ% |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in mesh:
        L.append(f"| {r['key']} | {mrole.get(r['source_job'], '—')} | {state_txt(r)} | {mesh_txt(r)}；{mesh_txt(r, 'src_')} | "
                 f"{check_txt(r.get('mesh_check'), r.get('src_mesh_check'))} | {tpl_txt(r)} | {fmt(r.get('pct_n_tet'), 1, True)} | "
                 f"{fmt(r.get('pct_n_pairs'), 1, True)} | {fmt(r.get('rot_first_deg'), 4)} / {fmt(r.get('src_rot_first_deg'), 4)} | "
                 f"{fmt(r.get('pct_rot_first_deg'), 1, True)} | {fmt(r.get('pct_rot_axial_first_deg'), 1, True)} | {fmt(r.get('pct_rot_tilt_first_deg'), 1, True)} | "
                 f"{fmt(r.get('contact_area_load2_mm2'), 0)} / {fmt(r.get('src_contact_area_load2_mm2'), 0)} | {fmt(r.get('pct_contact_area_load2_mm2'), 1, True)} | "
                 f"{fmt(r.get('f1_body_p95_um'))} / {fmt(r.get('src_f1_body_p95_um'))} | {fmt(r.get('pct_f1_body_p95_um'), 1, True)} | "
                 f"{fmt(r.get('subsid_first_um'))} / {fmt(r.get('src_subsid_first_um'))} | {fmt(r.get('pct_subsid_first_um'), 1, True)} |")
    if not mesh:
        L.append("| （ids 文件里没有 D13_mesh 作业） | | | | | | | | | | | | | | | | | |")
    elif noise is not None:
        L.append(f"\n表 3 最大 |Δ% 转动| = {noise:.1f} %（表 2 的排序判断用它作网格噪声）")
    # 未完成 / 失败 / 警告
    pend = [r for r in rows if r["group"].startswith("D13") and r.get("state") in ("pending", "missing")]
    fail = [r for r in rows if r.get("state") == "FAILED"]
    L += ["", "## 未完成与失败", ""]
    L += [f"- {r['key'] or r['job']}：{r['job']} {state_txt(r)}" for r in pend] or ["- 没有 pending / missing 的 D13 作业"]
    L += [f"- {r['key'] or r['job']}：{r['job']} FAILED level {r.get('fail_level')} stage {r.get('fail_stage')}：{r.get('fail_reason')}" for r in fail] \
        or ["- 没有 FAILED 作业"]
    rerr = [r for r in rows if r.get("row_err")]
    if rerr:
        L += ["", "## 行级错误（该行只有状态，其余量没算）", ""] + [f"- {r['key'] or r['job']}（{r['group']}）：{r['row_err']}" for r in rerr]
    if meta["fields_not_found"]:
        L += ["", "## 没取到的量", ""] + [f"- {x}" for x in meta["fields_not_found"]]
    if WARN:
        L += ["", f"## 警告（{len(WARN)}）", ""] + [f"- {w}" for w in WARN]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ids", default=str(RES / "deck_D13_ids.json"))
    ap.add_argument("--out", default=str(HOME / "deck" / "D13"))
    ap.add_argument("--stage-deck", default=None, help="stage_deck.py with d13_select (default: code/v2/stage_deck.py)")
    ap.add_argument("--no-fronts", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    f = pathlib.Path(args.ids)
    if not f.exists():
        raise SystemExit(f"{f} missing: batch D13 has not been submitted (or pass --ids)")
    ids = _rd(f)
    if "jobs" not in ids or not isinstance(ids["jobs"], dict):
        raise SystemExit(f"{f}: expected {{\"jobs\": {{key: job_id}}}}")
    ids_jobs = ids["jobs"]
    st = read_states()
    if st.get("err"):
        warn(st["err"])
    recs = {}
    for p in (13, 14):
        for r in (st.get(p) or {}).get("records") or []:
            recs.setdefault(r["job_id"], {**r, "_phase": p})
    SD, sd_err = None, None
    try:                                                                        # d13_select（前沿）与 D13_STS（起身期望载荷）都从这里取
        SD = load_sd(args.stage_deck)
    except Exception as e:                                                      # noqa: BLE001
        sd_err = f"stage_deck: {_err(e)}"
        warn(f"{sd_err}; sit-to-stand loads are checked against spec cfg.load only")

    def safe_row(build, base: dict) -> dict:
        """一行算不出（意外异常）→ 只留状态 + row_err，并警告（不让整个汇总停掉，CLAUDE.md §11）。"""
        try:
            return build()
        except Exception as e:                                                  # noqa: BLE001
            r = {**base, "row_err": _err(e)}
            warn(f"{base.get('key') or base['job']} ({base['group']}): row not built: {r['row_err']}")
            try:
                r.update(public(job_info(base["job"])))
            except Exception as e2:                                             # noqa: BLE001
                r["row_err"] += f" | job_info: {_err(e2)}"
                r.setdefault("state", "?")
            return r

    rows = []
    for key in sorted(ids_jobs):
        job = ids_jobs[key]
        for group, rx in KEY_RE:
            m = rx.match(key)
            if m:
                lab, src = m.groupdict().get("label"), m["src"]
                rows.append(safe_row(lambda: d13_row(key, job, group, lab, src, recs, SD),
                                     {"group": "D13_" + group, "key": key, "job": job, "label": lab, "source_job": src}))
                print(f"{key}: {rows[-1].get('state')}", flush=True)
                break
        else:
            warn(f"{key}: not a D13 key (D13_bond_ / D13_sts_F<N>_ / D13_mesh_h<h>_); state only")
            rows.append(safe_row(lambda: {"group": "other", "key": key, "job": job, **public(job_info(job))},
                                 {"group": "other", "key": key, "job": job}))
    if args.no_fronts:
        fr = {"err": "--no-fronts"}
    else:
        try:
            fr = fronts(ids_jobs, SD, sd_err, recs, st)
        except Exception as e:                                                  # noqa: BLE001
            fr = {"err": f"fronts failed: {_err(e)}"}
        if fr.get("err"):
            warn("fronts not computed: " + fr["err"])
    have = {(r["group"], r["job"]) for r in rows}                               # 去重按 (组, 作业)：D13 键指向的作业照样有自己的 arm_bonded 行
    for d in fr.get("designs") or []:
        for j in d["arm_bonded_jobs"]:
            if ("arm_bonded", j) not in have:
                rows.append(safe_row(lambda: arm_row(j, recs), {"group": "arm_bonded", "key": "", "job": j, "label": None, "source_job": j}))
                have.add(("arm_bonded", j))
                print(f"arm bonded {j}: {rows[-1].get('state')}", flush=True)
    missing_fields = []
    for r in rows:
        if r.get("state") == "DONE":
            for k in NEED.get(r["group"], ()):
                if r.get(k) is None:
                    base = k[4:] if k.startswith("src_") else k
                    p = "src_" if k.startswith("src_") else ""
                    if r.get("row_err"):
                        why = f"row not built: {r['row_err']}"
                    elif p and r.get("src_state") != "DONE":
                        why = f"source {r.get('source_job')} is {r.get('src_state')}"
                    elif base in ("sed_chg_pct", "ssi_pct"):
                        why = r.get(p + "calcar_err")
                    elif base in ("vm_p99", "vm_max"):
                        why = f"result.json has no {base} (res_fric_only={r.get(p + 'res_fric_only')}, res_bond_only={r.get(p + 'res_bond_only')})"
                    elif base in ("mesh_h", "mesh_algo", "mesh_sec_pts"):
                        why = r.get(p + "mesh_err") or "prep.json mesh_attempt lacks this key"
                    elif base == "load_N_mag":
                        why = r.get(p + "load_N_err")
                    elif base in ("load_eff",):
                        why = r.get(p + "load_eff_err")
                    elif base == "spec_load":
                        why = "spec.json has no cfg.load"
                    elif base in ("bone_mm3",):
                        why = "result.json has no bone_loss.total_mm3"
                    elif base == "f1_body_p95_um":
                        why = "result.json has no f1_p95_um"
                    else:
                        why = r.get(p + "stab_err")
                    missing_fields.append(f"{r['key'] or r['job']}: {k}" + (f" ({why})" if why else " (reason unknown)"))
    counts = {}
    for r in rows:
        c = counts.setdefault(r["group"], {"n": 0})
        c["n"] += 1
        c[r.get("state", "?")] = c.get(r.get("state", "?"), 0) + 1
    code_v = (HOME / "code" / "VERSION").read_text().replace("\n", " ").strip() if (HOME / "code" / "VERSION").exists() else "unknown"
    meta = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "ids_updated": ids.get("updated"), "code_version": code_v,
            "state13": "—" if st.get("err") else f"updated {st[13].get('updated')}, {len(st[13]['records'])} records / budget {st[13].get('budget')}, "
                                                  f"{len(st[13].get('pending') or {})} pending",
            "state14": "—" if st.get("err") else f"updated {st[14].get('updated')}, {len(st[14]['records'])} records / budget {st[14].get('budget')}, "
                                                  f"{len(st[14].get('pending') or {})} pending",
            "fields_not_found": missing_fields}
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys and not k.startswith("_")]
    with open(out / "d13_rows.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items() if not k.startswith("_")})
    if fr.get("designs"):
        dk = [k for k in fr["designs"][0] if not k.startswith("_")]
        with open(out / "d13_front_designs.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=dk)
            w.writeheader()
            for d in fr["designs"]:
                w.writerow({k: (",".join(v) if isinstance(v, list) else v) for k, v in d.items() if not k.startswith("_")})
    summ = {**meta, "ids_file": str(f), "out": str(out), "counts": counts, "elapsed_s": round(time.time() - t0, 1),
            "fronts": {k: v for k, v in fr.items() if k != "designs"} | {"designs": [{k: v for k, v in d.items() if not k.startswith("_")}
                                                                             for d in fr.get("designs") or []]},
            "pending": [{"key": r["key"], "job": r["job"], "queue_state": r.get("queue_state")} for r in rows if r.get("state") in ("pending", "missing")],
            "failed": [{"key": r["key"], "job": r["job"], "level": r.get("fail_level"), "stage": r.get("fail_stage"), "reason": r.get("fail_reason")}
                       for r in rows if r.get("state") == "FAILED"],
            "bond": [{k: r.get(k) for k in ("group", "key", "job", "state", "sed_chg_pct", "ssi_pct", "vm_p99", "calcar_err", "calcar_ref",
                                            "calcar_ref_note", "tpl_match", "tpl_diff", "design_match", "mesh_check", "load_check", "src_rot_first_deg",
                                            "src_contact_area_load2_mm2", "src_f1_body_p95_um", "src_bone_mm3", "row_err")}
                     for r in rows if r["group"] in ("D13_bond", "arm_bonded")],
            "sts": [{k: r.get(k) for k in ("key", "job", "source_job", "state", "spec_load", "load_eff", "src_load_eff", "load_expected",
                                           "load_expected_from", "load_N_mag", "load_alpha_front_deg", "load_alpha_sagit_deg", "src_load_N_mag",
                                           "src_load_alpha_front_deg", "src_load_alpha_sagit_deg", "load_check", "src_load_check", "tpl_match",
                                           "tpl_diff", "design_match", "mesh_check", "src_mesh_check", "row_err")
                     + CMP + tuple("src_" + m for m in CMP) + tuple("ratio_" + m for m in CMP)} for r in rows if r["group"] == "D13_sts"],
            "mesh": [{k: r.get(k) for k in ("key", "job", "source_job", "state", "mesh_h", "mesh_algo", "mesh_sec_pts", "mesh_n_prev_err",
                                            "src_mesh_h", "src_mesh_algo", "src_mesh_sec_pts", "src_mesh_n_prev_err", "mesh_check", "src_mesh_check",
                                            "tpl_match", "tpl_diff", "design_match", "load_check", "n_tet", "src_n_tet", "pct_n_tet", "pct_n_pairs", "row_err")
                      + CMP + tuple("src_" + m for m in CMP) + tuple("pct_" + m for m in CMP)} for r in rows if r["group"] == "D13_mesh"],
            "row_errors": [{"group": r["group"], "key": r["key"], "job": r["job"], "row_err": r["row_err"]} for r in rows if r.get("row_err")],
            "stage_deck_err": sd_err,
            "warnings": WARN}
    (out / "d13_summary.json").write_text(json.dumps(summ, indent=1, default=str, ensure_ascii=False))
    (out / "d13_summary.md").write_text(md_tables(rows, fr, counts, args, meta), encoding="utf-8")
    print(f"{len(rows)} rows -> {out / 'd13_rows.csv'}; {out / 'd13_summary.json'}; {out / 'd13_summary.md'}; "
          f"{len(WARN)} warnings; {len(missing_fields)} fields not found; {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
