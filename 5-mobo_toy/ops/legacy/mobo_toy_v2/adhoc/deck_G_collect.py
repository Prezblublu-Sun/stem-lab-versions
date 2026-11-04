"""批次 G 汇总（Linux）→ ~/mobo_toy_v2/deck/G/{G1_entry_offset.csv, G2_load_dir.csv, G3_remesh.csv, G4_p7_records.csv, G4_p7_meta.json}。
G1  入口偏移诊断：B1（= FI）余量 m × 领规则 × 入口偏移 e；已有作业（批次 C / F3 / B / BW）+ G1 新作业，加领外形面积。
G2  载荷方向分解：FI、J1、R2、B2（新领规则）× 爬楼 20°/18°、前 10°、矢 9°、ISO 角 10°/9°（2391 N）、ISO 2300 N；加绕柄轴扭矩与弯矩。
G3  重新划网格的噪声：BW 原作业 + 柄长 ±0.002 mm 两个复本。
G4  阶段 7 优化（neckopt_p7.json）的全部记录与 GP 长度尺度。"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2")); sys.path.insert(0, str(HOME / "adhoc"))
import numpy as np  # noqa: E402

import deck_master as D  # noqa: E402
import jobs as J  # noqa: E402

OUT = HOME / "deck" / "G"
KEYS = ("A0_shoulder_mm2", "entry_offset_e", "collar_w", "f1_p95_um", "f1_all_p95_um", "collar_force_share_load2", "collar_open_frac_load2",
        "sed_chg_pct", "vm_p99", "resected_mm3", "reamed_mm3", "bone_removed_mm3")


def rowm(j: str | None) -> dict:
    if not j:
        return {"state": "missing"}
    st = J.state(J.QROOT / j)
    if st != "DONE":
        out = {"state": st, "job": j}
        if st == "FAILED":
            out["reason"] = (json.loads((J.QROOT / j / "FAILED.json").read_text()).get("reason") or "").splitlines()[0][:200]
        return out
    r = D.row_of(j)
    return {"state": "DONE", "job": j, **{k: r.get(k) for k in KEYS}}


def write(path, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None or (isinstance(v, float) and not math.isfinite(v)) else v) for k, v in r.items()})


def collar_geom(rule: str, j: str) -> dict:
    """领外形（按作业自己的规则与固定偏移重算，不改全局函数）：领环面积、领环落在皮质上的比例、颈底伸出领外的面积与距离；
    并核对重算的号、偏移与作业记录一致。"""
    import collar_rule as CR
    import geom3d as G
    from shapely.geometry import Point
    try:
        spec = json.loads((J.QROOT / j / "spec.json").read_text())
        st = G.Stem3D(**spec["design"])
        if not getattr(st, "has_collar", False):
            return {}
        fm = J.femur_for(spec)
        offs = np.array([float(spec["entry_offset"])]) if spec.get("entry_offset") is not None else np.arange(-8.0, 8.1, 2.0)
        if rule == "wrap_fit":
            pl = CR.template_wrap_fit(st, fm, offsets=offs, margin=spec.get("margin"), min_A0=float(spec.get("min_A0", 0.0)))
            info = CR.collar_outline_wrap(st, fm, pl)
        else:
            pl = CR._ORIG["template"](st, fm, offsets=offs, margin=spec.get("margin"))
            info = CR._ORIG["collar_outline"](st, fm, pl)
        foot, col = info["footprint"], info["poly"]
        neck = Point(0.0, 0.0).buffer(float(fm.cfg["prosthesis"]["neck_radius_mm"]), quad_segs=32)
        t = (J.result(j) or {}).get("templating") or {}
        return {"collar_ring_mm2": float(col.area - foot.area), "collar_total_mm2": float(col.area), "ring_cortex_frac": info.get("ring_cortex_frac"),
                "neck_outside_collar_mm2": float(neck.difference(col).area),
                "neck_protrusion_mm": float(max(neck.exterior.interpolate(q, normalized=True).distance(col) for q in np.linspace(0, 1, 256))),
                "geom_check_A0_e": bool(abs(pl["A0"] - t.get("A0", -1)) < 0.5 and abs(pl["e"] - t.get("e", 99)) < 1e-6)}
    except Exception as ex:                                             # noqa: BLE001
        return {"geom_error": f"{type(ex).__name__}: {ex}"[:160]}


def g1(G_ids, ids):
    C = ids["C"]; F = ids["F"]
    cases = [("current", -0.25, -2.0, ids["B"]["FI"]), ("current", 0.0, -2.0, C["B1_m_0.0"]), ("current", 0.5, -2.0, C["B1_m_0.5"]),
             ("current", 1.0, -2.0, C["B1_m_1.0"]), ("current", 1.5, -2.0, C["B1_m_1.5"]),
             ("wrap_fit", -0.25, 0.0, ids["BW"]["FI"]), ("wrap_fit", 0.0, 0.0, F["F3_B1_m_0.0"]), ("wrap_fit", 0.5, 0.0, F["F3_B1_m_0.5"]),
             ("wrap_fit", 1.0, 0.0, F["F3_B1_m_1.0"]), ("wrap_fit", 1.5, 0.0, F["F3_B1_m_1.5"])]
    for k, j in G_ids.items():
        if k.startswith("G1_"):
            sp = json.loads((J.QROOT / j / "spec.json").read_text())
            cases.append((sp.get("collar_rule") or "current", float(sp["design"].get("m", -0.25)), float(sp["entry_offset"]), j))
    rows = []
    for rule, m, e, j in cases:
        r = {"rule": rule, "m": m, "e_fixed_or_chosen": e, "new_G1": j.startswith("diag_e"), **rowm(j)}
        if r["state"] == "DONE":
            r.update(collar_geom(rule, j))
        rows.append(r)
    return rows


def moments(j: str) -> dict:
    """绕柄轴扭矩与绕前后轴 / 内外轴的弯矩（N·m），对柄肩中心取矩，力作用在头心（与 audit3 相同的口径，只是用头心代替头节点形心）。"""
    try:
        spec = json.loads((J.QROOT / j / "spec.json").read_text())
        res = J.result(j) or {}
        info = json.loads((J.QROOT / j / "model3d.json").read_text()) if (J.QROOT / j / "model3d.json").exists() else {}
        F = np.array(info.get("load_N") or res.get("load_N"), float)
        fm = J.femur_for(spec)
        t = res["templating"]
        pose = fm.pose(t["alpha"], t["e"])
        M0 = np.cross(np.asarray(fm.H) - pose[0], F)
        return {"F_x": float(F[0]), "F_y": float(F[1]), "F_z": float(F[2]), "torsion_Nm": float(M0 @ pose[1] / 1e3),
                "bend_AP_axis_Nm": float(M0 @ pose[3] / 1e3), "bend_ML_axis_Nm": float(M0 @ pose[2] / 1e3)}
    except Exception as ex:                                             # noqa: BLE001
        return {"moment_error": f"{type(ex).__name__}: {ex}"[:160]}


def g2(G_ids, ids):
    rows = []
    F = ids["F"]
    for c in ("FI", "J1", "R2", "B2"):
        for ln, j in (("stair 20/18 2391", ids["BW"][c]), ("front 10/18 2391", G_ids.get(f"G2_{c}_front10")), ("sagittal 20/9 2391", G_ids.get(f"G2_{c}_sag9")),
                      ("ISO angles 10/9 2391", G_ids.get(f"G2_{c}_iso2391")), ("ISO 10/9 2300", F.get(f"F2_{c}_iso"))):
            r = {"code": c, "load": ln, **rowm(j)}
            if r["state"] == "DONE":
                r.update(moments(j))
            rows.append(r)
    return rows


def g3(G_ids, ids):
    rows = []
    for c in ("FI", "J1", "R2", "B2"):
        for tag, j in (("original", ids["BW"][c]), ("L+0.002", G_ids.get(f"G3_{c}_L+0.002")), ("L-0.002", G_ids.get(f"G3_{c}_L-0.002"))):
            rows.append({"code": c, "replicate": tag, **rowm(j)})
    return rows


def g4(phase: int = 7):
    f = J.RESULTS / f"neckopt_p{phase}.json"
    if not f.exists():
        return [], {}
    st = json.loads(f.read_text())
    rows = []
    for r in st["records"]:
        rows.append({"job": r["job_id"], "round": r["round"], **{f"x_{k}": v for k, v in r["design"].items()}, "x_h_cut": r.get("h_cut"), "ok": r["ok"],
                     "feasible": bool(r["ok"] and r["c"][0] <= 0), "mm_floored_um": 10 ** r["y"][0] if r["ok"] else None,
                     "f1_body_p95_um": r.get("f1_body_p95_um"), "f1_all_p95_um": r.get("f1_all_p95_um"), "bone_mm3": r["y"][1] if r["ok"] else None,
                     "sed_chg_pct": r.get("sed_chg_pct"), "vm_p99": r.get("vm_p99"), "A0": r.get("A0"), "entry_offset_e": r.get("entry_offset_e"),
                     "collar_force_share_load2": r.get("collar_force_share_load2"), "state": J.state(J.QROOT / r["job_id"]),
                     **{k: r.get(k) for k in ("rot_first_deg", "rot_tilt_first_deg", "rot_axial_first_deg", "rot_rev_deg", "subsid_first_um", "subsid_perm_um",
                                              "slip_axial_p95_um", "slip_circ_p95_um", "contact_area_load2_mm2", "contact_frac_load2", "bone_mm3")
                        if k in r}})
    meta = {k: st.get(k) for k in ("space", "fixed", "ref_point", "hv_hist", "budget", "inflight", "pool_size", "updated", "stopped_early")}
    meta["lengthscales_last"] = st.get("lengthscales", {}).get(max(st.get("lengthscales", {"0": None}), key=lambda s: int(s))) if st.get("lengthscales") else None
    meta["n_pending"] = len(st.get("pending", {}))
    meta["warm_start_ids"] = st.get("warm_start_ids", [])
    return rows, meta


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    G_ids = json.loads((J.RESULTS / "deck_G_ids.json").read_text())["jobs"]
    ids = {b: json.loads((J.RESULTS / f"deck_{b}_ids.json").read_text())["jobs"] for b in ("B", "BW", "C", "F")}
    for name, rows in (("G1_entry_offset", g1(G_ids, ids)), ("G2_load_dir", g2(G_ids, ids)), ("G3_remesh", g3(G_ids, ids))):
        write(OUT / f"{name}.csv", rows)
        print(name, len(rows), "rows;", sum(r["state"] == "DONE" for r in rows), "done")
    for tag, ph in (("G4", 7), ("G5", 8), ("G6", 9), ("G7", 10)):
        rows, meta = g4(ph)
        if rows:
            write(OUT / f"{tag}_p{ph}_records.csv", rows)
        if meta:
            (OUT / f"{tag}_p{ph}_meta.json").write_text(json.dumps(meta, indent=1, default=float))
        print(tag, f"p{ph}", len(rows), "records;", sum(r["ok"] for r in rows), "ok;", sum(r["feasible"] for r in rows), "feasible; pending", meta.get("n_pending"))


if __name__ == "__main__":
    main()
