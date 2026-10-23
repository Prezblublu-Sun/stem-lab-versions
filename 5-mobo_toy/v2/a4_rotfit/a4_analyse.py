"""A4 本机分析：读 plan/a4/rotfit_rows.jsonl（Linux 重拟合结果）与 data/metrics_all.csv（生产口径的存值），
输出 a4_table.csv / a4_table.json（逐作业）与 a4_stats.json（汇总统计）。摘要 a4_summary.md 由 a4_summary.py 生成。

用法（仓库 venv）：python v2/a4_rotfit/a4_analyse.py
"""
from __future__ import annotations

import csv
import json
import pathlib

import numpy as np
from scipy.stats import spearmanr

ML = pathlib.Path(r"H:/projects/application/research-log/neck_implant_2026-10-02/ml_efficiency_2026-10-22")
A4 = ML / "plan" / "a4"
ROWS = A4 / "rotfit_rows.jsonl"
METRICS = ML / "data" / "metrics_all.csv"
FRONT = {"a69": "neck10_a69_e394e85c", "a24": "neck10_a24_41b88dd9", "a36": "neck10_a36_0911f520", "a19": "neck10_a19_c15fe9c6"}
RS = {**FRONT, "a12": "neck10_a12_b1fbfd1c", "e2a": "neck9_init_e2a68dea", "J1": "collar_rule_J1_6024f7e9"}
DOMS = ("all", "prox", "dist", "unw")
BENCH = ("bench", "bench_cx")
SEGS = ("first", "rev", "perm")
STORED = {"all_rot_first_deg": "rot_first_deg", "all_rot_axial_first_deg": "rot_axial_first_deg",
          "all_rot_tilt_first_deg": "rot_tilt_first_deg", "all_rms_first_um": "rigid_fit_rms_first_um",
          "all_subsid_first_um": "subsid_first_um", "all_lateral_first_um": "lateral_first_um",
          "all_rot_rev_deg": "rot_rev_deg", "all_rot_perm_deg": "rot_perm_deg", "all_rms_rev_um": "rigid_fit_rms_rev_um",
          "all_rms_perm_um": "rigid_fit_rms_perm_um", "all_subsid_perm_um": "subsid_perm_um"}


def med(x):
    return float(np.median(x))


def pct(x, q):
    return float(np.percentile(x, q))


def sp(a, b):
    r = spearmanr(a, b)
    return float(r.correlation)


def ranks(v):
    """1 = 最小。"""
    order = np.argsort(np.argsort(np.asarray(v)))
    return order + 1


def main():
    rows = [json.loads(l) for l in ROWS.read_text(encoding="utf-8").splitlines() if l.strip()]
    met = {r["job"]: r for r in csv.DictReader(open(METRICS, encoding="utf-8"))}
    jl = json.loads((A4 / "joblist.json").read_text(encoding="utf-8"))
    set129 = set(jl["phase10set"])
    assert all("err" not in r for r in rows), [r for r in rows if "err" in r]
    # ---- 逐作业表 ----
    table = []
    for r in rows:
        m = met[r["job"]]
        fr = r["frame"]
        e_ml, e_ap, ax = (np.array(fr[k]) for k in ("e_ml", "e_ap", "ax"))
        t = {"job": r["job"], "tag": r["tag"], "stage": r["stage"], "in_phase10_set": r["job"] in set129,
             "collar": r["collar"], "L": r["L"], "alpha": r["alpha"], "e": r["e"], "h_cut": r["h_cut"],
             "n_body_pairs": r["n_body"], "s_ax_med_mm": r["s_ax_med_mm"], "r_med_mm": r["r_med_mm"],
             "contact_area_load2_mm2": float(m["contact_area_load2_mm2"]), "sed_chg_pct": float(m["sed_chg_pct"]),
             "bone_resected_mm3": float(m["bone_resected_mm3"]), "f1_p95_um": float(m["f1_p95_um"])}
        for d in DOMS:
            t[f"{d}_n"] = r[f"{d}_n"]
            for s in SEGS:
                for k in ("rot", "rot_axial", "rot_tilt"):
                    t[f"{d}_{k}_{s}_deg"] = r[f"{d}_{k}_{s}_deg"]
                t[f"{d}_rms_{s}_um"] = r[f"{d}_rms_{s}_um"]
                t[f"{d}_subsid_{s}_um"] = r[f"{d}_subsid_{s}_um"]
            om = np.array(r[f"{d}_omega_first"])
            t[f"{d}_tilt_ml_first_deg"] = float(np.degrees(om @ e_ml))      # 绕内外侧轴 = 屈伸向摆动（有符号）
            t[f"{d}_tilt_ap_first_deg"] = float(np.degrees(om @ e_ap))      # 绕前后轴 = 内外翻向摆动（有符号）
            t[f"{d}_axial_signed_first_deg"] = float(np.degrees(om @ ax))
        for s in SEGS:
            t[f"spin_circ_{s}_deg"] = r[f"spin_circ_{s}_deg"]
            t[f"spin_circ_signed_{s}_deg"] = r[f"spin_circ_signed_{s}_deg"]
            t[f"circ_arc_med_{s}_um"] = r[f"circ_arc_med_{s}_um"]
        for k in ("n_S10", "n_B5", "n_CX5", "n_stem_all", "stem_h_max_mm"):
            t[k] = r[k]
        for b in BENCH:
            for s in SEGS:
                for k in ("rot", "rot_axial", "rot_tilt", "rot_neckaxis"):
                    t[f"{b}_{k}_{s}_deg"] = r[f"{b}_{k}_{s}_deg"]
                t[f"{b}_subsid_{s}_um"] = r[f"{b}_subsid_{s}_um"]
                t[f"{b}_lateral_{s}_um"] = r[f"{b}_lateral_{s}_um"]
        for s in SEGS:
            for k in ("S10", "B5", "CX5", "stem_all"):
                t[f"abs_{k}_rot_{s}_deg"] = r[f"abs_{k}_rot_{s}_deg"]
                t[f"abs_{k}_rms_{s}_um"] = r[f"abs_{k}_rms_{s}_um"]
            t[f"neck_bend_{s}_deg"] = r[f"neck_bend_{s}_deg"]
            for bk in ("B5", "CX5"):
                for k in ("rot", "rot_axial", "rot_tilt"):
                    t[f"stemall_vs_{bk}_{k}_{s}_deg"] = r[f"stemall_vs_{bk}_{k}_{s}_deg"]
        for mine, st in STORED.items():
            t[f"stored_{st}"] = float(m[st])
            t[f"diff_{st}"] = r[mine] - float(m[st])
        table.append(t)
    table.sort(key=lambda t: (not t["in_phase10_set"], t["all_rot_first_deg"]))
    cols = list(table[0].keys())
    with open(A4 / "a4_table.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(table)
    # ---- 统计（129 个阶段 10 集合设计）----
    T = [t for t in table if t["in_phase10_set"]]
    n = len(T)
    col = lambda k, rows=T: np.array([x[k] for x in rows], float)  # noqa: E731
    S: dict = {"n_phase10_set": n, "n_rows": len(table), "repro_max_abs_diff_all_130": {}}
    for st in STORED.values():
        S["repro_max_abs_diff_all_130"][st] = float(np.max(np.abs(col(f"diff_{st}", table))))
    ref_rot, ref_ax, ref_tl = col("all_rot_first_deg"), col("all_rot_axial_first_deg"), col("all_rot_tilt_first_deg")
    S["domains_first"] = {}
    for d in DOMS:
        rot, axl, tl = col(f"{d}_rot_first_deg"), col(f"{d}_rot_axial_first_deg"), col(f"{d}_rot_tilt_first_deg")
        ra, rt = axl / ref_ax, tl / ref_tl
        S["domains_first"][d] = {
            "n_pairs_med": med(col(f"{d}_n")), "rms_med_um": med(col(f"{d}_rms_first_um")),
            "rot_med_deg": med(rot), "axial_med_deg": med(axl), "tilt_med_deg": med(tl),
            "axial_over_tilt_med": med(axl / tl), "frac_axial_gt_tilt": float(np.mean(axl > tl)),
            "axial_sq_share_med": med(axl ** 2 / (axl ** 2 + tl ** 2)),
            "spearman_rot_vs_all": sp(rot, ref_rot), "spearman_axial_vs_all": sp(axl, ref_ax), "spearman_tilt_vs_all": sp(tl, ref_tl),
            "axial_ratio_to_all": {"med": med(ra), "p10": pct(ra, 10), "p90": pct(ra, 90), "frac_within_25pct": float(np.mean(np.abs(ra - 1) <= 0.25))},
            "tilt_ratio_to_all": {"med": med(rt), "p10": pct(rt, 10), "p90": pct(rt, 90), "frac_within_25pct": float(np.mean(np.abs(rt - 1) <= 0.25))},
            "rot_ratio_to_all": {"med": med(rot / ref_rot), "p10": pct(rot / ref_rot, 10), "p90": pct(rot / ref_rot, 90)},
            "top10_overlap_with_all": int(len(set(np.argsort(rot)[:10]) & set(np.argsort(ref_rot)[:10]))),
            "spearman_subsid_vs_all": sp(col(f"{d}_subsid_first_um"), col("all_subsid_first_um")),
        }
    # 自转 / 摆动 在四个域间的离散度（逐设计）
    A = np.c_[[col(f"{d}_rot_axial_first_deg") for d in DOMS]].T
    Tt = np.c_[[col(f"{d}_rot_tilt_first_deg") for d in DOMS]].T
    cv_a, cv_t = A.std(1) / A.mean(1), Tt.std(1) / Tt.mean(1)
    rng_a, rng_t = A.max(1) / A.min(1), Tt.max(1) / Tt.min(1)
    S["robustness_across_domains"] = {
        "axial_cv_med": med(cv_a), "tilt_cv_med": med(cv_t), "axial_maxmin_ratio_med": med(rng_a), "tilt_maxmin_ratio_med": med(rng_t),
        "axial_maxmin_ratio_p90": pct(rng_a, 90), "tilt_maxmin_ratio_p90": pct(rng_t, 90),
        "frac_tilt_more_variable_than_axial": float(np.mean(cv_t > cv_a)),
        "frac_axial_maxmin_le_1p5": float(np.mean(rng_a <= 1.5)), "frac_tilt_maxmin_le_1p5": float(np.mean(rng_t <= 1.5)),
        "frac_prox_tilt_dominant": float(np.mean(col("prox_rot_tilt_first_deg") > col("prox_rot_axial_first_deg"))),
        "frac_all_tilt_dominant": float(np.mean(ref_tl > ref_ax)),
        "frac_dominance_flips_prox_vs_all": float(np.mean((col("prox_rot_tilt_first_deg") > col("prox_rot_axial_first_deg")) != (ref_tl > ref_ax))),
        "frac_dominance_flips_dist_vs_all": float(np.mean((col("dist_rot_tilt_first_deg") > col("dist_rot_axial_first_deg")) != (ref_tl > ref_ax))),
        "frac_dominance_flips_unw_vs_all": float(np.mean((col("unw_rot_tilt_first_deg") > col("unw_rot_axial_first_deg")) != (ref_tl > ref_ax))),
    }
    # 周向自转估计 vs 拟合自转
    spin = col("spin_circ_first_deg")
    rel = np.abs(spin - ref_ax) / ref_ax
    S["spin_circ_vs_all_axial"] = {"rel_diff_med": med(rel), "rel_diff_p90": pct(rel, 90), "frac_within_15pct": float(np.mean(rel <= 0.15)),
                                   "spearman": sp(spin, ref_ax), "arc_med_um_med": med(col("circ_arc_med_first_um")),
                                   "frac_arc_lt_rms": float(np.mean(col("circ_arc_med_first_um") < col("all_rms_first_um"))),
                                   "sign_agree_frac": float(np.mean(np.sign(col("spin_circ_signed_first_deg")) == np.sign(col("all_axial_signed_first_deg"))))}
    # 摆动的方向：屈伸向 vs 内外翻向
    for d in DOMS:
        ml, ap = col(f"{d}_tilt_ml_first_deg"), col(f"{d}_tilt_ap_first_deg")
        S["domains_first"][d]["tilt_dir"] = {"abs_ml_med": med(np.abs(ml)), "abs_ap_med": med(np.abs(ap)),
                                              "frac_ml_dominant": float(np.mean(np.abs(ml) > np.abs(ap))),
                                              "sign_ml_pos_frac": float(np.mean(ml > 0)), "sign_ap_pos_frac": float(np.mean(ap > 0))}
    # ---- 虚拟台架 ----
    S["bench"] = {}
    for b in BENCH + ("stemall_vs_B5", "stemall_vs_CX5"):
        S["bench"][b] = {}
        for s in SEGS:
            rot, axl, tl = col(f"{b}_rot_{s}_deg"), col(f"{b}_rot_axial_{s}_deg"), col(f"{b}_rot_tilt_{s}_deg")
            rr, ra, rt = col(f"all_rot_{s}_deg"), col(f"all_rot_axial_{s}_deg"), col(f"all_rot_tilt_{s}_deg")
            S["bench"][b][s] = {"rot_med_deg": med(rot), "axial_med_deg": med(axl), "tilt_med_deg": med(tl),
                                "ratio_rot_to_all_med": med(rot / rr), "ratio_axial_to_all_med": med(axl / ra), "ratio_tilt_to_all_med": med(tl / rt),
                                "ratio_rot_to_all_p10": pct(rot / rr, 10), "ratio_rot_to_all_p90": pct(rot / rr, 90),
                                "spearman_rot_vs_all": sp(rot, rr), "spearman_axial_vs_all": sp(axl, ra), "spearman_tilt_vs_all": sp(tl, rt),
                                "frac_axial_gt_tilt": float(np.mean(axl > tl)),
                                "spearman_rot_vs_all_first": sp(rot, ref_rot)}
            if b in BENCH:
                S["bench"][b][s]["subsid_med_um"] = med(col(f"{b}_subsid_{s}_um"))
                S["bench"][b][s]["spearman_subsid_vs_all"] = sp(col(f"{b}_subsid_{s}_um"), col(f"all_subsid_{s}_um"))
                S["bench"][b][s]["neckaxis_med_deg"] = med(col(f"{b}_rot_neckaxis_{s}_deg"))
    S["bench"]["absolute_rotation_first_deg_med"] = {k: med(col(f"abs_{k}_rot_first_deg")) for k in ("S10", "B5", "CX5", "stem_all")}
    S["bench"]["absolute_rms_first_um_med"] = {k: med(col(f"abs_{k}_rms_first_um")) for k in ("S10", "B5", "CX5", "stem_all")}
    S["bench"]["absolute_rotation_perm_deg_med"] = {k: med(col(f"abs_{k}_rot_perm_deg")) for k in ("S10", "B5", "CX5", "stem_all")}
    S["bench"]["neck_bend_deg_med"] = {s: med(col(f"neck_bend_{s}_deg")) for s in SEGS}
    S["bench"]["marker_counts_med"] = {k: med(col(k)) for k in ("n_S10", "n_B5", "n_CX5", "n_stem_all")}
    S["bench"]["marker_counts_min"] = {k: float(col(k).min()) for k in ("n_S10", "n_B5", "n_CX5")}
    # 台架读数分解：bench_first = (S10−stem_all) + (stem_all−B5)；后者 ≈ 柄身相对骨环的弹性弯曲 + 真实相对转动
    S["bench"]["decomp_first_med"] = {"bench_rot": med(col("bench_rot_first_deg")), "neck_bend": med(col("neck_bend_first_deg")),
                                      "stemall_vs_B5": med(col("stemall_vs_B5_rot_first_deg")), "interface_fit_all": med(ref_rot),
                                      "bench_minus_interface_over_bench_med": med((col("bench_rot_first_deg") - ref_rot) / col("bench_rot_first_deg"))}
    # ---- 参考设计与前沿排名 ----
    keys = {f"{d}_rot_first_deg": d for d in DOMS}
    keys.update({"bench_rot_first_deg": "bench_first", "bench_cx_rot_first_deg": "bench_cx_first", "bench_rot_perm_deg": "bench_perm",
                 "bench_cx_rot_perm_deg": "bench_cx_perm", "all_rot_perm_deg": "all_perm", "all_rot_axial_first_deg": "all_axial",
                 "all_rot_tilt_first_deg": "all_tilt", "prox_rot_tilt_first_deg": "prox_tilt", "spin_circ_first_deg": "spin_circ"})
    byjob = {t["job"]: t for t in table}
    S["front_ranking"] = {}
    S["rank_in_129"] = {}
    for k, name in keys.items():
        v = col(k)
        rk = ranks(v)
        jobs = [t["job"] for t in T]
        S["front_ranking"][name] = {a: {"value": byjob[j][k], "rank_in_front4": None} for a, j in FRONT.items()}
        fv = sorted(FRONT, key=lambda a: byjob[FRONT[a]][k])
        for i, a in enumerate(fv, 1):
            S["front_ranking"][name][a]["rank_in_front4"] = i
        S["front_ranking"][name]["order"] = fv
        S["rank_in_129"][name] = {a: int(rk[jobs.index(j)]) for a, j in RS.items() if j in jobs}
    S["reference_designs"] = {}
    for a, j in RS.items():
        t = byjob[j]
        S["reference_designs"][a] = {k: t[k] for k in cols if any(k.startswith(p) for p in ("all_rot", "prox_rot", "dist_rot", "unw_rot", "bench_rot", "bench_cx_rot", "spin_circ_first", "all_rms_first", "prox_rms_first", "dist_rms_first", "neck_bend_first", "bench_subsid_first", "all_subsid_first")) and ("_first_" in k or k.endswith("_first_deg"))} | {"job": j, "collar": t["collar"]}
    # ---- 子集：固定好 / 差 ----
    good = [t for t in T if t["all_rot_first_deg"] < 0.03]
    bad = [t for t in T if t["all_rot_first_deg"] > 0.15]
    for nm, sub in (("good_lt_0p03", good), ("bad_gt_0p15", bad)):
        S[f"subset_{nm}"] = {"n": len(sub)}
        for d in DOMS + ("bench",):
            axl, tl = col(f"{d}_rot_axial_first_deg", sub), col(f"{d}_rot_tilt_first_deg", sub)
            S[f"subset_{nm}"][d] = {"frac_axial_gt_tilt": float(np.mean(axl > tl)), "axial_over_tilt_med": med(axl / tl)}
    # ---- 零散核对 ----
    critic10 = ["neck10_a57_09bff191", "neck10_a64_2649f8de", "neck10_a68_2302d773", "neck10_a69_e394e85c", "neck10_a12_b1fbfd1c",
                "neck10_a59_0f44d7e2", "neck10_a24_41b88dd9", "neck10_a36_0911f520", "neck10_a19_c15fe9c6", "neck10_a46_be288f8f"]
    c10 = [byjob[j] for j in critic10 if j in byjob]
    S["critic10_check"] = {"n": len(c10)}
    for d in DOMS:
        order = [t["tag"] for t in sorted(c10, key=lambda t: t[f"{d}_rot_first_deg"])]
        S["critic10_check"][d] = {"order": order, "a69_rank": order.index("a69") + 1,
                                  "frac_tilt_dominant": float(np.mean([t[f"{d}_rot_tilt_first_deg"] > t[f"{d}_rot_axial_first_deg"] for t in c10]))}
    pa, pt = col("all_rot_axial_perm_deg"), col("all_rot_tilt_perm_deg")
    S["all_perm"] = {"rot_med_deg": med(col("all_rot_perm_deg")), "frac_axial_gt_tilt": float(np.mean(pa > pt)), "axial_over_tilt_med": med(pa / pt),
                     "spearman_vs_all_first": sp(col("all_rot_perm_deg"), ref_rot)}
    S["subsid_med_um"] = {f"{d}_{s}": med(col(f"{d}_subsid_{s}_um")) for d in DOMS for s in SEGS}
    S["subsid_med_um"].update({f"{b}_{s}": med(col(f"{b}_subsid_{s}_um")) for b in BENCH for s in SEGS})
    S["bench"]["frac_bench_first_gt_all_first"] = float(np.mean(col("bench_rot_first_deg") > ref_rot))
    S["bench"]["bench_cx_perm_ratio_frac_within_25pct"] = float(np.mean(np.abs(col("bench_cx_rot_perm_deg") / col("all_rot_perm_deg") - 1) <= 0.25))
    S["bench"]["top10_overlap_with_all_first"] = {k: int(len(set(np.argsort(col(k))[:10]) & set(np.argsort(ref_rot)[:10])))
                                                  for k in ("bench_rot_first_deg", "bench_cx_rot_first_deg", "bench_rot_perm_deg", "bench_cx_rot_perm_deg", "all_rot_perm_deg")}
    (A4 / "a4_stats.json").write_text(json.dumps(S, indent=1, ensure_ascii=False), encoding="utf-8")
    (A4 / "a4_table.json").write_text(json.dumps({"columns": cols, "rows": table, "stats": S}, indent=0, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(S, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
