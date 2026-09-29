"""第三份评估后 23 个验证作业的分析（在 Linux 上跑）。

    python v2/audit3b.py        → results/audit3b/summary.json
内容：循环稳定性；等绝对弹性滑移下的网格差；短柄阈值工况的噪声底；反力与接触合力的平衡检查；柄周骨主应变；
同一规格跨代码版本重解的一致性；用 Abaqus 节点接触面积作权重的 P95。
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import femur_real as FR  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402
import qoi  # noqa: E402

OUT = J.RESULTS / "audit3b"
NAMES = ("base", "readout", "short")
FM = {}


def fm_of(spec):
    if "fm" not in FM:
        FM["fm"] = FR.build()
    return FM["fm"].with_cut(float(spec.get("h_cut", 25.0)))


def wq(x, w, p):
    x, w = np.asarray(x, float), np.asarray(w, float)
    ok = np.isfinite(x)
    return float(qoi.wquantile(x[ok], w[ok], p))


def spec_of(d):
    return json.loads((d / "spec.json").read_text())


def find(label, h, delta, tol, cycles=None, exclude=()):
    """满足条件的已完成 M1 作业，按完成时间从新到旧。"""
    out = []
    for d in J.QROOT.glob(f"m1_{label}_h*"):
        if not (d / "DONE").exists() or d.name in exclude:
            continue
        sp = spec_of(d)
        if sp.get("lagrange") or sp.get("mu") is not None or not sp.get("torque", True):
            continue
        if abs(sp["h_int"] - h) > 1e-9 or abs(sp.get("delta", 0.10) - delta) > 1e-9 or abs(sp.get("slip_tol", 0) - tol) > 1e-9:
            continue
        if (sp.get("cycles") or 2) != (cycles or 2):
            continue
        out.append(((d / "DONE").stat().st_mtime, d))
    return [d for _, d in sorted(out, reverse=True)]


def steps_of(d):
    info = json.loads((d / "model3d.json").read_text())
    return info.get("steps", ["PRESSFIT", "RELEASE", "LOAD", "UNLOAD", "LOAD2"])[1:]


def rel_disp(d):
    p = PM.pairs(d)
    st = steps_of(d)
    U = {s: PM._utab(d / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in st}
    rel = {s: U[s][p["pair_stem"]] - U[s][p["pair_bone"]] for s in st}
    return p, st, rel


def tang(v, n):
    return v - (v * n).sum(1)[:, None] * n


def cycles(d):
    p, st, rel = rel_disp(d)
    n, w = p["pair_normal"], p["pair_area"]

    def m(a, b):
        return np.linalg.norm(tang(rel[a] - rel[b], n), axis=1) * 1e3
    loads = [s for s in st if s.startswith("LOAD")]
    unl = [s for s in st if s.startswith("UNLOAD")]
    out = {"job": d.name, "steps": st, "first_loading_P95": wq(m("LOAD", "RELEASE"), w, .95)}
    for k in range(len(unl)):
        out[f"unloading_{k + 1}_P95"] = wq(m(loads[k], unl[k]), w, .95)
        out[f"unloading_{k + 1}_P50"] = wq(m(loads[k], unl[k]), w, .5)
        if k + 1 < len(loads):
            out[f"reloading_{k + 2}_P95"] = wq(m(loads[k + 1], unl[k]), w, .95)
            out[f"reloading_{k + 2}_P50"] = wq(m(loads[k + 1], unl[k]), w, .5)
            out[f"peak_drift_{k + 1}to{k + 2}_P95"] = wq(m(loads[k + 1], loads[k]), w, .95)
            out[f"peak_drift_{k + 1}to{k + 2}_P50"] = wq(m(loads[k + 1], loads[k]), w, .5)
        if k >= 1:
            out[f"valley_drift_{k}to{k + 1}_P95"] = wq(m(unl[k], unl[k - 1]), w, .95)
    gap = {s: -(p["pair_interf"] + (rel[s] * n).sum(1)) * 1e3 for s in st}
    out["open_gt5um"] = {s: float(w[gap[s] > 5].sum() / w.sum()) for s in st}
    return out


def ftab(path, n):
    F = {k: np.zeros((n + 1, 3)) for k in ("CNORMF", "CSHEARF")}
    A = np.zeros(n + 1)
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            i = int(r["node"])
            if i > n:
                continue
            if r["field"] == "CNAREA":
                A[i] = float(r["f1"])
            elif r["field"] in F:
                F[r["field"]][i] += [float(r["f1"]), float(r["f2"]), float(r["f3"])]
    return F, A


def equilibrium(d):
    sp = spec_of(d)
    res = J.result(d.name)
    info = json.loads((d / "model3d.json").read_text())
    p, st, rel = rel_disp(d)
    fm = fm_of(sp)
    t = res["templating"]
    pose = fm.pose(t["alpha"], t["e"])
    lut = np.full(p["n"] + 1, -1)
    lut[p["node_labels"]] = np.arange(len(p["node_labels"]))
    X = p["nodes"]
    pb, n, w = p["pair_bone"], p["pair_normal"], p["pair_area"]
    Fapp = np.array(info["load_N"])
    m = dict(np.load(d / "mesh3d.npz"))
    sn = np.unique(m["stem_conn"].ravel())
    XS = X[lut[sn]]
    c = XS[np.linalg.norm(XS - fm.H, axis=1) <= fm.cfg["load"]["head_coupling_radius_mm"] + 1e-6].mean(0)
    Mapp = np.cross(c - pose[0], Fapp) / 1e3
    out = {"job": d.name, "applied_F_N": Fapp.tolist(), "applied_M_about_shoulder_Nm": Mapp.tolist(), "steps": {}}
    for s in st:
        loaded = s.startswith("LOAD")
        rf = qoi._csv(d / "m_fric_csv" / f"{s}_RF.csv")
        lab = rf["node"].astype(int)
        R = np.c_[rf["rf1"], rf["rf2"], rf["rf3"]]
        fixed = np.abs(X[lut[lab], 2] - fm.z_trunc) < 1e-3
        Rf = R[fixed].sum(0)
        Mr = np.cross(X[lut[lab[fixed]]] - pose[0], R[fixed]).sum(0) / 1e3
        F, A = ftab(d / "m_fric_csv" / f"{s}_CFORCE.csv", p["n"])
        fb = F["CNORMF"][pb] + F["CSHEARF"][pb]
        Fc = fb.sum(0)
        Mc = np.cross(X[lut[pb]] - pose[0], fb).sum(0) / 1e3
        nf = (F["CNORMF"][pb] * n).sum(1)
        exp = Fapp if loaded else np.zeros(3)
        out["steps"][s] = {"loaded": loaded, "reaction_sum_N": Rf.tolist(), "reaction_plus_applied_N": (Rf + exp).tolist(),
                           "reaction_residual_norm_N": float(np.linalg.norm(Rf + exp)),
                           "reaction_moment_about_shoulder_Nm": Mr.tolist(),
                           "contact_force_on_bone_N": Fc.tolist(), "contact_minus_applied_norm_N": float(np.linalg.norm(Fc - exp)),
                           "contact_force_on_bone_other_sign_norm_N": float(np.linalg.norm(Fc + exp)),
                           "contact_moment_about_shoulder_Nm": Mc.tolist(),
                           "normal_force_total_N": float(np.abs(nf).sum()), "shear_force_total_N": float(np.linalg.norm(F["CSHEARF"][pb], axis=1).sum()),
                           "mean_pressure_force_over_geometric_area_MPa": float(np.abs(nf).sum() / w.sum()),
                           "geometric_area_mm2": float(w.sum()), "cnarea_sum_mm2": float(A[pb].sum())}
    # 用 Abaqus 节点接触面积作权重的 P95（最后一个加载步）
    last = [s for s in st if s.startswith("LOAD")][-1]
    prev = [s for s in st if s.startswith("UNLOAD")][-1]
    rev = np.linalg.norm(tang(rel[last] - rel[prev], n), axis=1) * 1e3
    _, A = ftab(d / "m_fric_csv" / f"{last}_CFORCE.csv", p["n"])
    a = A[pb]
    out["P95_last_cycle"] = {"geometric_weights": wq(rev, w, .95), "cnarea_weights_contact_nodes_only": wq(rev[a > 0], a[a > 0], .95) if (a > 0).any() else None,
                             "share_of_nodes_with_cnarea": float((a > 0).mean())}
    return out


def strains(d):
    from scipy.spatial import cKDTree
    p = PM.pairs(d)
    st = steps_of(d)
    m = dict(np.load(d / "mesh3d.npz"))
    lut = np.full(p["n"] + 1, -1)
    lut[p["node_labels"]] = np.arange(len(p["node_labels"]))
    X = p["nodes"]
    tree = cKDTree(X[lut[p["pair_bone"]]])
    en = qoi._csv(d / "m_bond_csv" / "LOAD_ENER.csv")
    vol = dict(zip(en["elem"].astype(int), en["evol"]))
    out = {"job": d.name}
    for s in ("RELEASE", [x for x in st if x.startswith("LOAD")][-1]):
        e = qoi._csv(d / "m_fric_csv" / f"{s}_E.csv")
        emin = dict(zip(e["elem"].astype(int), e["e_min"]))
        emax = dict(zip(e["elem"].astype(int), e["e_max"]))
        for tis in ("cancellous", "cortex"):
            el = m[f"{tis}_elab"].astype(int)
            cen = X[lut[m[f"{tis}_conn"][:, :4]]].mean(1)
            dist, _ = tree.query(cen)
            for band, k in (("within_2mm", dist <= 2.0), ("2_to_5mm", (dist > 2.0) & (dist <= 5.0))):
                if not k.any():
                    continue
                v = np.array([vol.get(int(x), 0.0) for x in el[k]])
                a = np.array([emin.get(int(x), np.nan) for x in el[k]])
                b = np.array([emax.get(int(x), np.nan) for x in el[k]])
                V = v.sum()
                out[f"{s}:{tis}:{band}"] = {"n_elem": int(k.sum()), "volume_mm3": float(V),
                                           "emin_P50": wq(a, v, .5), "emin_P5": wq(a, v, .05), "emin_P1": wq(a, v, .01),
                                           "emax_P50": wq(b, v, .5), "emax_P95": wq(b, v, .95), "emax_P99": wq(b, v, .99),
                                           "vol_frac_comp_gt_0.7pct": float(v[a < -0.007].sum() / V), "vol_frac_comp_gt_1pct": float(v[a < -0.01].sum() / V),
                                           "vol_frac_comp_gt_2pct": float(v[a < -0.02].sum() / V), "vol_frac_tens_gt_0.7pct": float(v[b > 0.007].sum() / V)}
    return out


KEYS = ("f1_p95_um", "f1_rev_p50_um", "f1_first_p95_um", "f1_cslip_p95_um", "open_frac_release", "stick_cslip_p95_um", "cpress_release_p50", "f2_g7_loss_pct",
        "vm_p99", "n_pairs")


def brief(d):
    r = J.result(d.name)
    out = {k: r[k] for k in KEYS if k in r}
    out["job"] = d.name
    out["wall_fric_s"] = r["solve"]["m_fric"].get("wall_s")
    out["code"] = json.loads((d / "prep.json").read_text()).get("code_hash")
    out["n_tet"] = r.get("n_tet")
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ids = json.loads((J.RESULTS / "m1_review3_ids.json").read_text())
    S = {"ids": ids, "states": {k: J.state(J.QROOT / j) for k, j in ids.items()}, "failed": {}}
    for k, j in ids.items():
        f = J.QROOT / j / "FAILED.json"
        if f.exists():
            S["failed"][k] = json.loads(f.read_text())
    done = {k: J.QROOT / j for k, j in ids.items() if (J.QROOT / j / "DONE").exists()}
    new = set(ids.values())
    # 1 循环稳定性
    S["cycles"] = {k: cycles(d) for k, d in done.items() if k.startswith("cycle3:")}
    # 2 网格（等绝对弹性滑移）
    S["mesh"] = {}
    for k, d in done.items():
        if not k.startswith("mesh14:"):
            continue
        sp = spec_of(d)
        lab, dl = k.split(":")[1], sp.get("delta", 0.10)
        ref = find(lab, 2.0, dl, 0.00025)
        old14 = find(lab, 1.4, dl, 0.00025)
        S["mesh"][k] = {"h1.4_const_slip": brief(d), "h2.0": brief(ref[0]) if ref else None, "h1.4_same_tol": brief(old14[0]) if old14 else None}
    # 3 短柄阈值工况的噪声底
    S["noise"] = {}
    for dl in (0.05, 0.025):
        rows = []
        for h in (1.94, 1.97, 2.0, 2.03, 2.06):
            c = find("short", h, dl, 0.00025)
            if c:
                rows.append({"h": h, **brief(c[0])})
        o = {"rows": rows}
        for qn in ("f1_p95_um", "f1_first_p95_um", "f1_cslip_p95_um", "vm_p99", "open_frac_release"):
            v = np.array([r[qn] for r in rows], float)
            if len(v) >= 3:
                o[qn] = {"n": int(len(v)), "mean": float(v.mean()), "sd": float(v.std(ddof=1)), "cv_pct": float(100 * v.std(ddof=1) / abs(v.mean())),
                         "min": float(v.min()), "max": float(v.max())}
        S["noise"][f"short:d{dl:g}"] = o
    # 4 平衡检查与 5 应变：带新导出的代表工况
    S["equilibrium"], S["strain"] = {}, {}
    for k, d in done.items():
        if k.startswith("export:") or k.startswith("cycle3:"):
            try:
                S["equilibrium"][k] = equilibrium(d)
                S["strain"][k] = strains(d)
            except Exception as e:                                         # noqa: BLE001  单个作业的文件缺失不应中断全部分析，原因写进结果
                S.setdefault("analysis_errors", {})[k] = f"{type(e).__name__}: {e}"
    # 6 跨版本一致性
    S["determinism"] = {}
    for k, d in done.items():
        if not k.startswith("export:"):
            continue
        sp = spec_of(d)
        lab = k.split(":")[1]
        prev = [x for x in find(lab, 2.0, sp.get("delta", 0.10), 0.00025) if x.name not in new]
        if prev:
            a, b = brief(d), brief(prev[0])
            S["determinism"][k] = {"new": a, "old": b, "identical": {q: (a.get(q) == b.get(q)) for q in ("f1_p95_um", "f1_first_p95_um", "vm_p99", "n_pairs")},
                                   "abs_diff": {q: abs(a[q] - b[q]) for q in ("f1_p95_um", "f1_first_p95_um", "vm_p99") if q in a and q in b}}
    S["briefs"] = {k: brief(d) for k, d in done.items()}
    (OUT / "summary.json").write_text(json.dumps(S, indent=1, default=float))
    print(json.dumps({"states": {s: list(S["states"].values()).count(s) for s in set(S["states"].values())}, "failed": S["failed"],
                      "analysis_errors": S.get("analysis_errors")}, indent=1, default=float))
    for k, v in S["cycles"].items():
        print(k, {a: round(b, 3) for a, b in v.items() if isinstance(b, float)})
    for k, v in S["mesh"].items():
        print(k, {a: (None if b is None else (round(b["f1_p95_um"], 3), round(b["f1_first_p95_um"], 2), round(b["vm_p99"], 1), round(b["wall_fric_s"]))) for a, b in v.items()})
    for k, v in S["noise"].items():
        print(k, {a: (round(b["mean"], 2), round(b["cv_pct"], 1)) for a, b in v.items() if isinstance(b, dict)})
    for k, v in S["equilibrium"].items():
        print(k, "applied", [round(x) for x in v["applied_F_N"]], {s: (round(o["reaction_residual_norm_N"], 2), round(o["contact_minus_applied_norm_N"], 1),
                                                                        round(o["contact_force_on_bone_other_sign_norm_N"], 1),
                                                                        round(o["mean_pressure_force_over_geometric_area_MPa"], 2)) for s, o in v["steps"].items()},
              v["P95_last_cycle"])
    for k, v in S["strain"].items():
        print(k, {a: (round(100 * b["emin_P50"], 3), round(100 * b["emin_P1"], 2), round(b["vol_frac_comp_gt_0.7pct"], 3), round(b["vol_frac_comp_gt_1pct"], 3))
                  for a, b in v.items() if isinstance(b, dict) and "cancellous:within_2mm" in a})
    for k, v in S["determinism"].items():
        print(k, v["identical"], v["abs_diff"], v["new"]["code"], v["old"]["code"])


if __name__ == "__main__":
    main()
