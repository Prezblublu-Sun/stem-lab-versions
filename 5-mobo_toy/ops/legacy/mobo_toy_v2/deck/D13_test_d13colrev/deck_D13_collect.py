"""批 D13（阶段 13 / 14 两臂跑完后的前沿核查，2026-10-25；v2/stage_deck.py 批次 D13）的结果汇总。在 Linux 上运行，
只读队列、结果与代码，只写 --out 目录（默认 ~/mobo_toy_v2/deck/D13/）：

    cd ~/mobo_toy_v2 && nice -n 19 taskset -c 4-11 ./run.sh adhoc/deck_D13_collect.py
        [--ids results/deck_D13_ids.json]   ids 文件（{"jobs": {键: 作业号}}）；测试时换成指向类似旧作业的假 ids
        [--out deck/D13]
        [--stage-deck <stage_deck.py>]      d13_select 从哪个文件取（默认 code/v2/stage_deck.py；没有 d13_select → 前沿表不出、写明原因）
        [--no-fronts]                       不求前沿（只汇总 ids 文件里的作业）

键（stage_deck._d13_specs）：D13_bond_<源作业>（bond_only）、D13_sts_<F1714|F3839>_<源作业>（起身，fric_only + cfg.load）、
D13_mesh_h<1.94|2.06>_<源作业>（fric_only + h_int）。源作业 = 键的后缀；spec.source_job 与之不同或缺失 → 警告；
作业与源作业的 design / h_cut 不同 → 警告（D13 的 spec 是源 spec 的副本，应当相同）。
每个作业：状态 DONE / FAILED（FAILED.json 的 level / stage / reason）/ pending（NEW / READY / CLAIMED / SOLVED）/ missing（不在队列里），并且
  bond：股骨距 SED 变化——stage_neckopt._calcar 的口径：resorption.design_rows 固定解剖区 G7、只算皮质的 sed_chg_pct（负 = 屏蔽）与 ssi_pct，
        参照 = spec 的 intact_job（femur_id 作业与 _calcar 相同；没有 femur_id、也没有 intact_job 的 CT 作业 = 标准 CT 参照）——
        与柄 vM P99（result.json vm_p99）；加源作业的楼梯载荷摩擦指标（stability.py：转动 rot_first_deg 与自转 / 摆动、LOAD2 完全接触面积、
        下沉；柄身微动 P95 = result f1_p95_um = 记录的 f1_body_p95_um；去骨量 bone_loss.total_mm3）；
  sts：同样的摩擦指标，与源作业（同一设计、楼梯载荷）并列，比值 = 起身 / 楼梯；施加的载荷 = spec.json 的 cfg.load（另记 jobs.femur_for
        合并后的有效 load 节）；
  mesh：同样的指标在 h 1.94 / 2.06 与源作业（h 2.0）比，变化 % = 100 (h − 源) / 源。
前沿表：用 stage_deck.d13_select（与提交时同一函数、同一规则）对当前 results/neckopt_p13.json / p14.json 求 F13 / F14 / P3，按单位立方体坐标 x
  把前沿行并成设计；每个设计列出全部粘接结果：两臂自己的粘接作业（每 5 个提交第 5 个带粘接模型，记录 bonded True）与 D13_bond 作业。
  SED / vM 一律按本作业自己的文件重算，再与状态文件记录里的值核对（不同 → 警告）。两臂没跑完 → 前沿是临时的（d13_unfinished 的问题列进警告）。
不假设不同设计（或不同网格）之间节点编号一致：每个量都是一个作业用自己的网格、自己的节点对算出的标量，作业之间只比较标量。
失败不吞（CLAUDE.md §11）：读不到 / 算不出的量留空，原因写进 *_err 列、警告列表与 d13_summary.json 的 fields_not_found。
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
NEED = {"D13_bond": ("sed_chg_pct", "ssi_pct", "vm_p99", "src_rot_first_deg", "src_contact_area_load2_mm2", "src_f1_body_p95_um", "src_bone_mm3"),
        "D13_sts": CMP + ("spec_load", "load_eff") + tuple("src_" + k for k in CMP),
        "D13_mesh": CMP + ("mesh_h",) + tuple("src_" + k for k in CMP),
        "arm_bonded": ("sed_chg_pct", "ssi_pct", "vm_p99", "rot_first_deg", "contact_area_load2_mm2", "f1_body_p95_um", "bone_mm3")}
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
            load = (sp.get("cfg") or {}).get("load")
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
        sol = sol if isinstance(sol, dict) else {}
        t = res.get("templating") or prep.get("templating") or {}
        ma = prep.get("mesh_attempt") or {}
        nt = prep.get("n_tet") or res.get("n_tet") or {}
        out.update({"vm_p99": res.get("vm_p99"), "vm_max": res.get("vm_max"), "f1_body_p95_um": res.get("f1_p95_um"),
                    "f1_all_p95_um": res.get("f1_all_p95_um"), "f2_g7_loss_pct": res.get("f2_g7_loss_pct"),
                    "bone_mm3": (res.get("bone_loss") or {}).get("total_mm3"), "res_intact_job": res.get("intact_job"),
                    "res_bond_only": bool(res.get("bond_only")), "res_fric_only": bool(res.get("fric_only")),
                    "mesh_h": ma.get("h_int"), "mesh_attempt": ma.get("attempt"),
                    "n_tet": sum(int(v) for v in nt.values()) if isinstance(nt, dict) and nt else None, "n_pairs": prep.get("n_pairs"),
                    "tpl_alpha": t.get("alpha"), "tpl_e": t.get("e"), "tpl_A0": t.get("A0"),
                    "wall_fric_s": (sol.get("m_fric") or {}).get("wall_s"), "wall_bond_s": (sol.get("m_bond") or {}).get("wall_s"),
                    "has_m_fric_csv": (d / "m_fric_csv").is_dir(), "has_m_bond_csv": (d / "m_bond_csv").is_dir()})
    _INFO[job] = out
    return out


def stab_of(job: str) -> dict:
    """stability.stability（只读 m_fric_csv + mesh3d.npz）；没有 m_fric_csv（bond_only）→ 不算、写明。"""
    if job not in _STAB:
        if not (Q / job / "m_fric_csv").is_dir():
            _STAB[job] = {"err": "no m_fric_csv (bond_only job: no friction model)"}
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
                raise FileNotFoundError("no m_bond_csv (fric_only job: no bonded model)")
            spec = _rd(Q / job / "spec.json")
            iname = spec.get("intact_job")
            if spec.get("femur_id") and not iname:
                raise ValueError(f"femur_id {spec['femur_id']!r} job without intact_job: no reference for the calcar index")
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


def design_match(a: dict | None, b: dict | None):
    if not a or not b or "design" not in a or "design" not in b:
        return None
    da, db = a["design"], b["design"]
    if set(da) != set(db):
        return False
    same = all((_f(da[k]) is not None and _f(db[k]) is not None and math.isclose(float(da[k]), float(db[k]), rel_tol=1e-9, abs_tol=1e-12))
               or da[k] == db[k] for k in da)
    return same and math.isclose(float(a.get("h_cut", 25.0)), float(b.get("h_cut", 25.0)), rel_tol=1e-9)


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


def d13_row(key: str, job: str, group: str, label: str | None, src: str, recs: dict) -> dict:
    info = job_info(job)
    r = {"group": "D13_" + group, "key": key, "job": job, "label": label, "source_job": src}
    r.update(metrics(job, sed=(group == "bond"), load=(group == "sts")))
    sp = info.get("_spec")
    if sp is not None:
        if sp.get("source_job") is None:
            warn(f"{key}: spec.json of {job} has no source_job (source taken from the key: {src})")
        elif sp["source_job"] != src:
            warn(f"{key}: spec.source_job {sp['source_job']} != key suffix {src} (source taken from the key)")
        flag = {"bond": ("bond_only", bool(sp.get("bond_only"))), "sts": ("fric_only + cfg.load", bool(sp.get("fric_only")) and bool((sp.get("cfg") or {}).get("load"))),
                "mesh": ("fric_only + h_int", bool(sp.get("fric_only")) and sp.get("h_int") is not None)}[group]
        if not flag[1]:
            warn(f"{key}: {job} is not a {flag[0]} job (spec kind {sp.get('kind')!r} stage {sp.get('stage')!r}) — not a D13 spec")
        if group == "sts":
            want = _f(label[1:])
            got = _f(((sp.get("cfg") or {}).get("load") or {}).get("resultant_N"))
            if want is not None and got is not None and not math.isclose(want, got):
                warn(f"{key}: key label {label} but spec cfg.load resultant_N = {got:g} N")
        if group == "mesh" and _f(label) is not None and _f(sp.get("h_int")) is not None and not math.isclose(float(label), float(sp["h_int"])):
            warn(f"{key}: key label h{label} but spec h_int = {sp['h_int']}")
    r.update(metrics(src, prefix="src_", load=(group == "sts")))
    r["design_match"] = design_match(sp, job_info(src).get("_spec"))
    if r["design_match"] is False:
        warn(f"{key}: {job} and its source {src} have different design / h_cut")
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


def fronts(ids_jobs: dict, sd_path: str | None, recs: dict, st: dict) -> dict:
    """F13 / F14 / P3（stage_deck.d13_select），按 x 并成设计。失败 → {"err": 原因}（前沿表不出，原因写进 md / json）。"""
    try:
        SD = load_sd(sd_path)
    except Exception as e:                                                      # noqa: BLE001
        return {"err": f"stage_deck: {_err(e)}"}
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
    return s or "—"


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
    by_job = {}
    for r in rows:
        by_job.setdefault(r["job"], []).append(r)
    by_key = {r["key"]: r for r in rows if r["key"]}
    if fr.get("err"):
        L.append(f"前沿没有算出：{fr['err']}。下面只列 ids 文件里的 D13_bond 作业。")
        L += ["", "| 键 | 作业 | 状态 | SED 变化 % | SSI % | vM P99 MPa | 源作业楼梯：转动° (自转/摆动) | 接触 mm² | 微动 µm | 去骨 mm³ |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            if r["group"] == "D13_bond":
                L.append(f"| {r['key']} | {r['job']} | {state_txt(r)} | {fmt(r.get('sed_chg_pct'))} | {fmt(r.get('ssi_pct'))} | {fmt(r.get('vm_p99'))} | "
                         f"{rot3(r, 'src_')} | {fmt(r.get('src_contact_area_load2_mm2'), 0)} | {fmt(r.get('src_f1_body_p95_um'))} | {fmt(r.get('src_bone_mm3'), 0)} |")
    else:
        L += ["楼梯载荷指标 = 代表作业在状态文件里的记录（stability.py 同一口径）；粘接结果按作业自己的文件重算。"
              "来源 arm = 两臂自己的粘接作业，D13 = D13_bond 作业。", "",
              "| # | 设计（代表作业） | 前沿 | 转动° (自转/摆动) | 接触 mm² | 微动 µm | 去骨 mm³ | 来源 | 粘接作业 | 状态 | SED 变化 % | SSI % | vM P99 MPa |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for i, d in enumerate(fr["designs"], 1):
            head = (f"| {i} | {d['rep_job']} | {d['fronts']} | {rot3(d)} | {fmt(d['contact_area_load2_mm2'], 0)} | {fmt(d['f1_body_p95_um'])} | "
                    f"{fmt(d['bone_mm3'], 0)} |")
            blank = "| | | | | | | |"
            srcs = [("arm", j, by_job.get(j, [{}])[0]) for j in d["arm_bonded_jobs"]] + [("D13", k, by_key.get(k, {})) for k in d["d13_bond_keys"]]
            if not srcs:
                why = ("cap 外（dropped by the cap）" if d["dropped_by_cap"] else
                       "当前选择会新提交 D13_bond（ids 文件里没有）" if d["selection_would_add_bond"] else "—")
                L.append(head + f" — | — | 无粘接结果：{why} | — | — | — |")
            for n, (kind, name, r) in enumerate(srcs):
                L.append((head if n == 0 else blank) + f" {kind} | {r.get('job', name)} | {state_txt(r)} | {fmt(r.get('sed_chg_pct'))} | "
                         f"{fmt(r.get('ssi_pct'))} | {fmt(r.get('vm_p99'))} |")
        nb = sum(1 for d in fr["designs"] if d["arm_bonded_jobs"] or d["d13_bond_keys"])
        ok = sum(1 for d in fr["designs"] if any(_f(r.get("sed_chg_pct")) is not None for j in d["arm_bonded_jobs"] for r in by_job.get(j, []))
                 or any(_f(by_key.get(k, {}).get("sed_chg_pct")) is not None for k in d["d13_bond_keys"]))
        L += ["", f"{len(fr['designs'])} 个前沿设计：{nb} 个有粘接作业，其中 {ok} 个已有 SED 值；"
              f"{len(fr['designs']) - nb} 个没有任何粘接作业。"]
        other = [r for r in rows if r["group"] == "D13_bond" and not any(r["key"] in d["d13_bond_keys"] for d in fr["designs"])]
        if other:
            L += ["", "不在当前前沿上的 D13_bond 作业（过时键或源作业不在记录里）：", "",
                  "| 键 | 状态 | SED 变化 % | SSI % | vM P99 MPa | 源作业转动° | 接触 mm² | 微动 µm | 去骨 mm³ |", "|---|---|---|---|---|---|---|---|---|"]
            for r in other:
                L.append(f"| {r['key']} | {state_txt(r)} | {fmt(r.get('sed_chg_pct'))} | {fmt(r.get('ssi_pct'))} | {fmt(r.get('vm_p99'))} | "
                         f"{fmt(r.get('src_rot_first_deg'), 4)} | {fmt(r.get('src_contact_area_load2_mm2'), 0)} | {fmt(r.get('src_f1_body_p95_um'))} | "
                         f"{fmt(r.get('src_bone_mm3'), 0)} |")
    # 表 2
    roles = {e["job_id"]: e.get("role") for e in (fr.get("sts") or [])}
    sts = [r for r in rows if r["group"] == "D13_sts"]
    L += ["", "## 表 2　起身（sit-to-stand）vs 楼梯载荷（同一设计 = 源作业）", "",
          "比值 = 起身 / 楼梯。载荷 = 起身作业 spec.json 的 cfg.load（有效 load 节见 CSV 的 load_eff）。"
          "下沉是有符号的小量（µm 级时接近 0），它的比值只作参考。", "",
          "| 键 | 角色 | 状态 | 载荷 cfg.load | 转动° 起身 (自转/摆动) | 转动° 楼梯 (自转/摆动) | 比 | 接触 mm² 起身 / 楼梯 | 比 | 微动 µm 起身 / 楼梯 | 比 | 下沉 µm 起身 / 楼梯 | 比 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sts:
        L.append(f"| {r['key']} | {roles.get(r['source_job'], '—')} | {state_txt(r)} | {r.get('spec_load') or '—'} | {rot3(r)} | {rot3(r, 'src_')} | "
                 f"{fmt(r.get('ratio_rot_first_deg'), 2)} | {fmt(r.get('contact_area_load2_mm2'), 0)} / {fmt(r.get('src_contact_area_load2_mm2'), 0)} | "
                 f"{fmt(r.get('ratio_contact_area_load2_mm2'), 2)} | {fmt(r.get('f1_body_p95_um'))} / {fmt(r.get('src_f1_body_p95_um'))} | "
                 f"{fmt(r.get('ratio_f1_body_p95_um'), 2)} | {fmt(r.get('subsid_first_um'))} / {fmt(r.get('src_subsid_first_um'))} | "
                 f"{fmt(r.get('ratio_subsid_first_um'), 2)} |")
    if not sts:
        L.append("| （ids 文件里没有 D13_sts 作业） | | | | | | | | | | | | |")
    for lab in sorted({r["label"] for r in sts}):
        done = [r for r in sts if r["label"] == lab and _f(r.get("rot_first_deg")) is not None and _f(r.get("src_rot_first_deg")) is not None]
        if len(done) >= 2:
            a = [r["source_job"] for r in sorted(done, key=lambda r: r["src_rot_first_deg"])]
            b = [r["source_job"] for r in sorted(done, key=lambda r: r["rot_first_deg"])]
            L.append(f"\n{lab}：转动排序（小 → 大）楼梯 {' < '.join(a)}；起身 {' < '.join(b)} → {'保持' if a == b else '改变'}（{len(done)} 个设计都算完）")
        else:
            L.append(f"\n{lab}：算完的设计不足 2 个（{len(done)}），排序不比较")
    # 表 3
    mesh = [r for r in rows if r["group"] == "D13_mesh"]
    mrole = {e["job_id"]: ("转动最小" if i == 0 else "F14 去骨居中") for i, e in enumerate(fr.get("mesh") or [])}
    L += ["", "## 表 3　网格噪声（h_int 1.94 / 2.06 vs 源作业 h 2.0）", "",
          "变化 % = 100 (h − 源) / 源；实际网格 h 来自 prep.json mesh_attempt。每个作业用自己的网格与节点对，只比较标量。", "",
          "| 键 | 角色 | 状态 | 网格 h（实际） | 四面体数 Δ% | 节点对 Δ% | 转动° h / 源 | Δ% | 自转 Δ% | 摆动 Δ% | 接触 mm² h / 源 | Δ% | 微动 µm h / 源 | Δ% | 下沉 µm h / 源 | Δ% |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in mesh:
        L.append(f"| {r['key']} | {mrole.get(r['source_job'], '—')} | {state_txt(r)} | {fmt(r.get('mesh_h'), 2)} (源 {fmt(r.get('src_mesh_h'), 2)}) | {fmt(r.get('pct_n_tet'), 1, True)} | "
                 f"{fmt(r.get('pct_n_pairs'), 1, True)} | {fmt(r.get('rot_first_deg'), 4)} / {fmt(r.get('src_rot_first_deg'), 4)} | "
                 f"{fmt(r.get('pct_rot_first_deg'), 1, True)} | {fmt(r.get('pct_rot_axial_first_deg'), 1, True)} | {fmt(r.get('pct_rot_tilt_first_deg'), 1, True)} | "
                 f"{fmt(r.get('contact_area_load2_mm2'), 0)} / {fmt(r.get('src_contact_area_load2_mm2'), 0)} | {fmt(r.get('pct_contact_area_load2_mm2'), 1, True)} | "
                 f"{fmt(r.get('f1_body_p95_um'))} / {fmt(r.get('src_f1_body_p95_um'))} | {fmt(r.get('pct_f1_body_p95_um'), 1, True)} | "
                 f"{fmt(r.get('subsid_first_um'))} / {fmt(r.get('src_subsid_first_um'))} | {fmt(r.get('pct_subsid_first_um'), 1, True)} |")
    if not mesh:
        L.append("| （ids 文件里没有 D13_mesh 作业） | | | | | | | | | | | | | | | |")
    # 未完成 / 失败 / 警告
    pend = [r for r in rows if r["group"].startswith("D13") and r.get("state") in ("pending", "missing")]
    fail = [r for r in rows if r.get("state") == "FAILED"]
    L += ["", "## 未完成与失败", ""]
    L += [f"- {r['key'] or r['job']}：{r['job']} {state_txt(r)}" for r in pend] or ["- 没有 pending / missing 的 D13 作业"]
    L += [f"- {r['key'] or r['job']}：{r['job']} FAILED level {r.get('fail_level')} stage {r.get('fail_stage')}：{r.get('fail_reason')}" for r in fail] \
        or ["- 没有 FAILED 作业"]
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
    rows = []
    for key in sorted(ids_jobs):
        job = ids_jobs[key]
        for group, rx in KEY_RE:
            m = rx.match(key)
            if m:
                rows.append(d13_row(key, job, group, m.groupdict().get("label"), m["src"], recs))
                print(f"{key}: {rows[-1]['state']}", flush=True)
                break
        else:
            warn(f"{key}: not a D13 key (D13_bond_ / D13_sts_F<N>_ / D13_mesh_h<h>_); state only")
            rows.append({"group": "other", "key": key, "job": job, **public(job_info(job))})
    fr = {"err": "--no-fronts"} if args.no_fronts else fronts(ids_jobs, args.stage_deck, recs, st)
    if fr.get("err") and not args.no_fronts:
        warn("fronts not computed: " + fr["err"])
    have = {r["job"] for r in rows}
    for d in fr.get("designs") or []:
        for j in d["arm_bonded_jobs"]:
            if j not in have:
                rows.append(arm_row(j, recs))
                have.add(j)
                print(f"arm bonded {j}: {rows[-1]['state']}", flush=True)
    missing_fields = []
    for r in rows:
        if r.get("state") == "DONE":
            for k in NEED.get(r["group"], ()):
                if r.get(k) is None:
                    why = r.get("calcar_err") if k in ("sed_chg_pct", "ssi_pct") else r.get("src_stab_err" if k.startswith("src_") else "stab_err")
                    if k.startswith("src_") and r.get("src_state") != "DONE":
                        why = f"source {r.get('source_job')} is {r.get('src_state')}"
                    missing_fields.append(f"{r['key'] or r['job']}: {k}" + (f" ({why})" if why else ""))
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
            "bond": [{k: r.get(k) for k in ("key", "job", "state", "sed_chg_pct", "ssi_pct", "vm_p99", "calcar_err", "src_rot_first_deg",
                                            "src_contact_area_load2_mm2", "src_f1_body_p95_um", "src_bone_mm3")}
                     for r in rows if r["group"] in ("D13_bond", "arm_bonded")],
            "sts": [{k: r.get(k) for k in ("key", "job", "source_job", "state", "spec_load", "load_eff", "src_load_eff")
                     + CMP + tuple("src_" + m for m in CMP) + tuple("ratio_" + m for m in CMP)} for r in rows if r["group"] == "D13_sts"],
            "mesh": [{k: r.get(k) for k in ("key", "job", "source_job", "state", "mesh_h", "src_mesh_h", "n_tet", "src_n_tet", "pct_n_tet", "pct_n_pairs")
                      + CMP + tuple("src_" + m for m in CMP) + tuple("pct_" + m for m in CMP)} for r in rows if r["group"] == "D13_mesh"],
            "warnings": WARN}
    (out / "d13_summary.json").write_text(json.dumps(summ, indent=1, default=str, ensure_ascii=False))
    (out / "d13_summary.md").write_text(md_tables(rows, fr, counts, args, meta), encoding="utf-8")
    print(f"{len(rows)} rows -> {out / 'd13_rows.csv'}; {out / 'd13_summary.json'}; {out / 'd13_summary.md'}; "
          f"{len(WARN)} warnings; {len(missing_fields)} fields not found; {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
