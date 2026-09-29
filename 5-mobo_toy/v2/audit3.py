"""第三份评估意见的零 FE 复核（在 Linux 上跑）：微动的重算与定义、压配状态、载荷与力矩、去骨体积、模型版本、超体积参考点、
应力屏蔽的固定区相关性。只读已有结果，不提交作业。

    python v2/audit3.py        → results/audit3/summary.json，并打印各项
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402
import qoi  # noqa: E402
from spot3d.model3d import FACES  # noqa: E402
from spot3d.qoi3d import FACE_MID  # noqa: E402

OUT = J.RESULTS / "audit3"
NAMED = {"base": "m1_base_h2_tol0.00025_", "readout": "m1_readout_h2_tol0.00025_", "short": "m1_short_h2_tol0.00025_"}
FM = {}


def fm_of(spec):
    if "fm" not in FM:
        FM["fm"] = FR.build()
    return FM["fm"].with_cut(float(spec.get("h_cut", 25.0)))


def find(label, delta):
    for d in sorted(J.QROOT.glob(f"m1_{label}_h2_tol0.00025*")):
        sp = json.loads((d / "spec.json").read_text())
        if abs(sp.get("delta", 0.10) - delta) < 1e-9 and sp.get("mu") is None and sp.get("torque", True) and (d / "DONE").exists():
            return d
    return None


def wq(x, w, p):
    return float(qoi.wquantile(np.asarray(x, float), np.asarray(w, float), p))


def consistent_weights(d, p):
    """二次三角形的一致节点面积：角节点 0，边中节点 A/3。"""
    m = dict(np.load(d / "mesh3d.npz"))
    info = json.loads((d / "model3d.json").read_text())
    lab, X = m["node_labels"], m["nodes"]
    lut = np.full(int(lab.max()) + 1, -1)
    lut[lab] = np.arange(len(lab))
    conn = {}
    for r in ("cortex", "cancellous"):
        for el, row in zip(m[f"{r}_elab"], m[f"{r}_conn"]):
            conn[int(el)] = row
    w = {}
    corner = set()
    for el, fc in info["slave"]:
        row = conn[int(el)]
        c = [int(row[k]) for k in FACES[fc]]
        P = X[lut[c]]
        A = 0.5 * np.linalg.norm(np.cross(P[1] - P[0], P[2] - P[0]))
        corner.update(c)
        for n in (int(row[k]) for k in FACE_MID[fc]):
            w[n] = w.get(n, 0.0) + A / 3.0
    wc = np.array([w.get(int(n), 0.0) for n in p["pair_bone"]])
    return wc, np.array([int(n) in corner for n in p["pair_bone"]])


def micromotion_audit(d):
    spec = json.loads((d / "spec.json").read_text())
    res = J.result(d.name)
    p = PM.pairs(d)
    pb, ps, nrm, w, di, cort = p["pair_bone"], p["pair_stem"], p["pair_normal"], p["pair_area"], p["pair_interf"], p["pair_cortex"]
    U = {s: PM._utab(d / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in PM.STEPS}
    rel = {s: U[s][ps] - U[s][pb] for s in PM.STEPS}

    def tang(v):
        return v - (v * nrm).sum(1)[:, None] * nrm

    def mag(a, b):
        return np.linalg.norm(tang(rel[a] - rel[b]), axis=1) * 1e3
    rev2, rev1, first = mag("LOAD2", "UNLOAD"), mag("LOAD", "UNLOAD"), mag("LOAD", "RELEASE")
    resid, drift = mag("UNLOAD", "RELEASE"), mag("LOAD2", "LOAD")
    wc, is_corner = consistent_weights(d, p)
    W = w.sum()
    out = {"job": d.name, "delta": spec.get("delta", 0.10), "n_pairs": int(len(pb)), "area_mm2": float(W),
           "stored_f1": res["f1_p95_um"], "stored_first": res["f1_first_p95_um"],
           "P95": {"reversible_cycle2": wq(rev2, w, .95), "reversible_cycle1_unloading": wq(rev1, w, .95), "first_loading": wq(first, w, .95),
                   "residual_after_cycle1": wq(resid, w, .95), "peak_to_peak_drift": wq(drift, w, .95)},
           "P50": {"reversible_cycle2": wq(rev2, w, .5), "first_loading": wq(first, w, .5), "residual_after_cycle1": wq(resid, w, .5),
                   "peak_to_peak_drift": wq(drift, w, .5)},
           "weights": {"A/6 all nodes": wq(rev2, w, .95), "consistent (midside A/3)": wq(rev2[wc > 0], wc[wc > 0], .95),
                       "unweighted": float(np.percentile(rev2, 95)), "first A/6": wq(first, w, .95),
                       "first consistent": wq(first[wc > 0], wc[wc > 0], .95), "first unweighted": float(np.percentile(first, 95))},
           "wrong_way_difference_of_P95": wq(np.linalg.norm(tang(rel["LOAD2"]), axis=1) * 1e3, w, .95)
           - wq(np.linalg.norm(tang(rel["UNLOAD"]), axis=1) * 1e3, w, .95),
           "quantiles_rev2": {f"P{int(100 * q)}": wq(rev2, w, q) for q in (.5, .75, .9, .95, .99)} | {"max": float(rev2.max())},
           "area_frac_rev2_gt": {str(t): float(w[rev2 > t].sum() / W) for t in (1, 5, 20, 40, 150)},
           "area_frac_first_gt": {str(t): float(w[first > t].sum() / W) for t in (1, 5, 20, 40, 150)}}
    # 压配与接触状态
    gap = {s: -(di + (rel[s] * nrm).sum(1)) * 1e3 for s in PM.STEPS}
    out["interference"] = {"area_with_delta": float(w[di > 0].sum() / W), "area_zero": float(w[di <= 0].sum() / W),
                           "area_weighted_mean_mm": float((di * w).sum() / W)}
    out["open_area"] = {s: {"gt1um": float(w[gap[s] > 1].sum() / W), "gt5um": float(w[gap[s] > 5].sum() / W),
                            "gap_P50": wq(gap[s], w, .5), "gap_P95": wq(gap[s], w, .95), "gap_P99": wq(gap[s], w, .99), "gap_max": float(gap[s].max())}
                        for s in PM.STEPS}
    C = PM._ctab(d / "m_fric_csv" / "RELEASE_CONTACT.csv", p["n"])
    cp = np.nan_to_num(C["CPRESS"][pb])
    out["cpress_release"] = {"area_weighted_P50_contact_nodes": wq(cp[cp > 0], w[cp > 0], .5), "area_weighted_mean_all": float((cp * w).sum() / W),
                             "arithmetic_mean_contact_nodes": float(cp[cp > 0].mean()), "consistent_weight_mean_all": float((cp * wc).sum() / wc.sum()),
                             "corner_mean": float(cp[is_corner].mean()), "midside_mean": float(cp[~is_corner].mean()),
                             "normal_force_N_A6": float((cp * w).sum()), "normal_force_N_consistent": float((cp * wc).sum())}
    # 位置：柄局部坐标
    fm = fm_of(spec)
    t = res["templating"]
    pose = fm.pose(t["alpha"], t["e"])
    lut = np.full(p["n"] + 1, -1)
    lut[p["node_labels"]] = np.arange(len(p["node_labels"]))
    X = p["nodes"][lut[pb]]
    Q = X - pose[0]
    s_, x_, y_ = Q @ pose[1], Q @ pose[2], Q @ pose[3]
    L = spec["design"]["L"]
    reg = {}
    for nm, k in (("proximal third", s_ < L / 3), ("middle third", (s_ >= L / 3) & (s_ < 2 * L / 3)), ("distal third + tip", s_ >= 2 * L / 3),
                  ("medial", x_ >= 0), ("lateral", x_ < 0), ("anterior", y_ >= 0), ("posterior", y_ < 0)):
        if k.any():
            reg[nm] = {"area_frac": float(w[k].sum() / W), "rev2_P95": wq(rev2[k], w[k], .95), "first_P95": wq(first[k], w[k], .95),
                       "share_of_top5pct_area": float(w[k & (rev2 >= out["quantiles_rev2"]["P95"])].sum() / max(w[rev2 >= out["quantiles_rev2"]["P95"]].sum(), 1e-12))}
    out["regions"] = reg
    # 载荷
    m = dict(np.load(d / "mesh3d.npz"))
    info = json.loads((d / "model3d.json").read_text())
    sn = np.unique(m["stem_conn"].ravel())
    XS = p["nodes"][lut[sn]]
    head = np.linalg.norm(XS - fm.H, axis=1) <= fm.cfg["load"]["head_coupling_radius_mm"] + 1e-6
    c = XS[head].mean(0)
    F = np.array(info["load_N"])
    Mp = np.cross(c - fm.H, F)
    M0 = np.cross(c - pose[0], F)
    out["load"] = {"F_N": F.tolist(), "resultant_N": float(np.linalg.norm(F)), "n_head_nodes": int(head.sum()), "n_head_in_json": info["n_head"],
                   "head_centre": fm.H.tolist(), "load_centroid_offset_mm": (c - fm.H).tolist(), "offset_norm_mm": float(np.linalg.norm(c - fm.H)),
                   "parasitic_moment_about_head_Nmm": Mp.tolist(), "parasitic_moment_norm_Nm": float(np.linalg.norm(Mp) / 1e3),
                   "moment_about_shoulder_centre_Nm": (M0 / 1e3).tolist(), "moment_norm_Nm": float(np.linalg.norm(M0) / 1e3),
                   "torsion_about_stem_axis_Nm": float(M0 @ pose[1] / 1e3),
                   "bending_about_AP_axis_Nm": float(M0 @ pose[3] / 1e3), "bending_about_ML_axis_Nm": float(M0 @ pose[2] / 1e3),
                   "lever_arm_head_to_stem_axis_mm": float(np.linalg.norm(np.cross(fm.H - pose[0], pose[1]))),
                   "applied_moment": "none (only *CLOAD forces on head nodes)"}
    return out


def volumes(spec, templ, h=0.4):
    """柄 ∩ 骨的体积，按体素独立计算，并按骨质拆分；与模板化给出的解析柄体积比较。"""
    fm = fm_of(spec)
    st = G.Stem3D(**spec["design"])
    pose = fm.pose(templ["alpha"], templ["e"])
    A0 = templ["A0"]
    k0 = math.sqrt(A0) * 1.6
    s = np.arange(-35.0, st.L + st.cap_length(A0) + 1.0, h) + h / 2
    a = np.arange(-k0, k0, h) + h / 2
    S_, X_, Y_ = np.meshgrid(s, a, a, indexing="ij")
    loc = np.c_[S_.ravel(), X_.ravel(), Y_.ravel()]
    ins = G.inside_stem(st, A0, loc)
    P = fm.to_world(loc[ins], pose)
    below = fm.below_cut(P)
    inbone = fm.outer_sdf(P) <= 0
    canc = fm.canal_sdf(P) <= 0
    dv = h ** 3
    body = loc[ins][:, 0] >= 0
    out = {"analytic_stem_volume": float(templ["volume"]),
           "voxel_stem_body_s_ge_0": float(body.sum() * dv),
           "reamed_total_in_bone": float((below & inbone).sum() * dv),
           "reamed_cancellous": float((below & inbone & canc).sum() * dv),
           "reamed_cortex": float((below & inbone & ~canc).sum() * dv),
           "stem_body_above_cut_plane": float((body & ~below).sum() * dv),
           "prism_below_cut_in_bone": float((~body & below & inbone).sum() * dv),
           "stem_below_cut_outside_bone": float((below & ~inbone).sum() * dv),
           "resected_slab": float(fm.resected_volume())}
    out["bone_loss_old_definition"] = out["analytic_stem_volume"] + out["resected_slab"]
    out["bone_loss_voxel"] = out["reamed_total_in_bone"] + out["resected_slab"]
    out["ratio_voxel_to_old"] = out["bone_loss_voxel"] / out["bone_loss_old_definition"]
    return out


def all_designs():
    rows, seen = [], set()
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists() or not (d / "DONE").exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") != "design":
            continue
        prep = json.loads((d / "prep.json").read_text()) if (d / "prep.json").exists() else {}
        r = J.result(d.name)
        rows.append({"job": d.name, "stage": spec.get("stage"), "model": spec.get("model", "old"), "h": spec.get("h_int"), "code": prep.get("code_hash"),
                     "done": (d / "DONE").read_text().strip(), "spec": spec, "templ": r.get("templating"), "f1": r.get("f1_p95_um"),
                     "f2": r.get("f2_g7_loss_pct"), "vm": r.get("vm_p99"),
                     "variant": {k: spec.get(k) for k in ("delta", "mu", "torque", "E_canc", "slip_tol", "lagrange") if spec.get(k) is not None}})
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    S = {}
    # A–C：三个代表设计 × 过盈
    S["micromotion"] = {}
    for lab in NAMED:
        for dlt in (0.10, 0.05, 0.025, 0.01):
            d = find(lab, dlt)
            if d is not None:
                S["micromotion"][f"{lab}:delta{dlt:g}"] = micromotion_audit(d)
    rows = all_designs()
    # E：版本表
    ver = {}
    for r in rows:
        k = (r["model"], r["code"])
        v = ver.setdefault(k, {"n": 0, "stages": {}, "first": r["done"], "last": r["done"], "vm": []})
        v["n"] += 1
        v["stages"][r["stage"]] = v["stages"].get(r["stage"], 0) + 1
        v["first"], v["last"] = min(v["first"], r["done"]), max(v["last"], r["done"])
        if r["vm"] is not None and not r["variant"]:
            v["vm"].append(r["vm"])
    S["versions"] = [{"model": k[0], "code_hash": k[1], "n_jobs": v["n"], "stages": v["stages"], "first_done": v["first"], "last_done": v["last"],
                      "vm_median_standard": float(np.median(v["vm"])) if v["vm"] else None} for k, v in sorted(ver.items(), key=lambda kv: kv[1]["first"])]
    # D：去骨体积（全部标准旧模型设计 + M1 代表设计；同一设计只算一次）
    vol, seen = [], set()
    for r in rows:
        if r["templ"] is None or r["h"] != 2.0:
            continue
        key = json.dumps({**G.design_of_spec(r["spec"]), "h_cut": float(r["spec"].get("h_cut", 25.0)), "margin": r["spec"].get("margin")}, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        v = volumes(r["spec"], r["templ"])
        dsg = G.design_of_spec(r["spec"])
        vol.append({"job": r["job"], "stage": r["stage"], "L": dsg["L"], "alpha": dsg["alpha"], "m": dsg["m"], "rho_tip": dsg["rho_tip"], "q": dsg["q"],
                    "h_cut": float(r["spec"].get("h_cut", 25.0)), "A0": r["templ"]["A0"], **v})
    S["volumes"] = vol
    ratio = np.array([v["ratio_voxel_to_old"] for v in vol])
    cort = np.array([v["reamed_cortex"] / max(v["reamed_total_in_bone"], 1e-9) for v in vol])
    above = np.array([v["stem_body_above_cut_plane"] / v["analytic_stem_volume"] for v in vol])
    S["volume_summary"] = {"n": len(vol), "ratio_voxel_to_old": {"median": float(np.median(ratio)), "min": float(ratio.min()), "max": float(ratio.max()),
                                                                 "P5": float(np.percentile(ratio, 5)), "P95": float(np.percentile(ratio, 95))},
                           "voxel_vs_analytic_body_check_median": float(np.median([v["voxel_stem_body_s_ge_0"] / v["analytic_stem_volume"] for v in vol])),
                           "cortex_share_of_reamed": {"median": float(np.median(cort)), "max": float(cort.max())},
                           "stem_body_above_cut_share": {"median": float(np.median(above)), "max": float(above.max())},
                           "rank_change": None}
    from scipy.stats import spearmanr
    S["volume_summary"]["spearman_old_vs_voxel"] = float(spearmanr([v["bone_loss_old_definition"] for v in vol], [v["bone_loss_voxel"] for v in vol])[0])
    # F：超体积参考点
    hv = {}
    for sd in (0, 1):
        p = J.RESULTS / f"v3_bo_s{sd}.json"
        if p.exists():
            b = json.loads(p.read_text())
            rp = b["ref_point"]
            rec = [r for r in b["records"] if r["ok"]]
            hv[f"s{sd}"] = {"ref_log10_f1": rp[0], "ref_f1_um": 10 ** rp[0], "ref_bone_loss_mm3": rp[1],
                            "n_eval_ok": len(rec), "n_beyond_f1_ref": sum(r["y"][0] > rp[0] for r in rec),
                            "n_beyond_bone_ref": sum(r["y"][1] > rp[1] for r in rec),
                            "n_feasible_inside_box": sum(r["c"][0] <= 0 and r["y"][0] <= rp[0] and r["y"][1] <= rp[1] for r in rec)}
    old = [r for r in rows if r["model"] == "old" and r["h"] == 2.0 and not r["variant"] and r["f1"] is not None]
    if hv:
        rp = json.loads((J.RESULTS / "v3_bo_s0.json").read_text())["ref_point"]
        hv["all_old_designs"] = {"n": len(old), "f1_gt_ref": sum(r["f1"] > 10 ** rp[0] for r in old),
                                 "f1_gt_ref_and_sed_le30": sum(r["f1"] > 10 ** rp[0] and abs(r["f2"]) <= 30 for r in old),
                                 "f1_gt_40": sum(r["f1"] > 40 for r in old), "f1_gt_40_and_sed_le30": sum(r["f1"] > 40 and abs(r["f2"]) <= 30 for r in old)}
    S["hypervolume"] = hv
    # G：应力屏蔽的固定区相关性
    zp = J.RESULTS / "shielding" / "zones.csv"
    if zp.exists():
        import csv
        z = [r for r in csv.DictReader(open(zp, encoding="utf-8")) if r["version"] == "current" and r["tissue"] == "cortex"]
        sh = {}
        for zone in ("G7", "calcar_fixed", "G1"):
            rr = [r for r in z if r["zone"] == zone]
            for key in ("chg_vm_pct", "chg_sed_pct"):
                y = np.array([float(r[key]) for r in rr])
                ok = np.isfinite(y)
                sh[f"{zone}:{key}"] = {"n": int(ok.sum()), "median": float(np.median(y[ok])), "min": float(y[ok].min()), "max": float(y[ok].max()),
                                       **{f"spearman_{v}": float(spearmanr(np.array([float(r[v]) for r in rr])[ok], y[ok])[0]) for v in ("alpha", "L", "A0", "m")}}
        S["shielding_fixed_zone"] = sh
    (OUT / "summary.json").write_text(json.dumps(S, indent=1, default=float))
    # 打印
    for k, a in S["micromotion"].items():
        print(f"== {k}  stored f1 {a['stored_f1']:.3f} first {a['stored_first']:.2f} | recomputed P95: " +
              ", ".join(f"{n} {v:.3f}" for n, v in a["P95"].items()))
        print("   weights:", {n: round(v, 3) for n, v in a["weights"].items()}, "| wrong-way ΔP95", round(a["wrong_way_difference_of_P95"], 3))
        print("   rev2 quantiles", {n: round(v, 2) for n, v in a["quantiles_rev2"].items()}, "| area>", {n: round(v, 3) for n, v in a["area_frac_rev2_gt"].items()})
        print("   interference", {n: round(v, 4) for n, v in a["interference"].items()}, "| open>5um by step", {s: round(v["gt5um"], 3) for s, v in a["open_area"].items()},
              "| open>1um", {s: round(v["gt1um"], 3) for s, v in a["open_area"].items()})
        print("   cpress", {n: round(v, 2) for n, v in a["cpress_release"].items()})
        print("   regions", {n: (round(v["rev2_P95"], 2), round(v["first_P95"], 1), round(v["share_of_top5pct_area"], 2)) for n, v in a["regions"].items()})
        lo = a["load"]
        print("   load |F|", round(lo["resultant_N"], 1), "n_head", lo["n_head_nodes"], lo["n_head_in_json"], "centroid offset mm", round(lo["offset_norm_mm"], 3),
              "parasitic M Nm", round(lo["parasitic_moment_norm_Nm"], 3), "| M about shoulder Nm", [round(x, 1) for x in lo["moment_about_shoulder_centre_Nm"]],
              "norm", round(lo["moment_norm_Nm"], 1), "torsion about stem axis", round(lo["torsion_about_stem_axis_Nm"], 1),
              "bend AP-axis", round(lo["bending_about_AP_axis_Nm"], 1), "bend ML-axis", round(lo["bending_about_ML_axis_Nm"], 1),
              "lever", round(lo["lever_arm_head_to_stem_axis_mm"], 1))
    print("== versions")
    for v in S["versions"]:
        print("  ", v["model"], v["code_hash"], v["n_jobs"], v["first_done"][5:16], "→", v["last_done"][5:16], v["stages"],
              "vm median", None if v["vm_median_standard"] is None else round(v["vm_median_standard"], 1))
    print("== volumes", json.dumps(S["volume_summary"], default=float))
    for v in vol:
        if v["job"].startswith(("m1_base_h2_tol0.00025_c", "m1_readout_h2_tol0.00025_3", "m1_short_h2_tol0.00025_2", "bo_qnehvi_s1_r0_62bbf792", "ref_r51", "ref_r2_", "ref_r9_")):
            print("  ", v["job"][:34], "L", round(v["L"]), "cut", round(v["h_cut"]), {k: round(v[k]) for k in ("analytic_stem_volume", "voxel_stem_body_s_ge_0", "reamed_total_in_bone",
                  "reamed_cancellous", "reamed_cortex", "stem_body_above_cut_plane", "prism_below_cut_in_bone", "stem_below_cut_outside_bone", "resected_slab")},
                  "ratio", round(v["ratio_voxel_to_old"], 3))
    print("== hypervolume", json.dumps(S["hypervolume"], default=float))
    print("== shielding", json.dumps(S.get("shielding_fixed_zone"), default=float))


if __name__ == "__main__":
    main()
