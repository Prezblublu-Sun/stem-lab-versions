"""b33（R2 候选的条件行，五天计划 CAND 的复核部分）的判据 G53–G55，看结果前定（2026-11-08，喂料前）。候选名单见 data/picks.json 和 pick.py。

只读版本目录的 scalars.csv 和 fields/iface_*.npz。三个候选是 b31（R2）的 r2_01、r2_03、r2_12，主行楼梯 2391 N、h 2.0、只解摩擦（已在 v0.13）。
每个候选 3 行：h 1.94 重划复算（带粘接，摩擦部分和只解摩擦相同）、h 1.4（带粘接）、坐起 1714 N（只解摩擦）。tag = 主行 tag + "_h1.94" / "_h1.4" / "_F1714"。
比较基准同 b31：A 族曲线（7 行，按去骨量对新轴网格 F、log10 微动线性插值），3b 在这把尺子上 ΔF +9.68 mm、Δlog 微动 −0.0738 dex，当场重算，
差过 0.05 mm 或 0.002 dex 三条判据都判不适用。"比 3b 好"同 b31 的 G49。坐起的 A 族曲线和 G54、G55 的门槛同 b28 的 G44、G45。
噪声：F 重划网格标准差约 0.6 mm，微动重划网格最大差 0.029 dex（b28 提议第 6 节）。候选主行离"比 3b 好"门槛的余量（以这两个数为单位）是 2.78、2.73、1.06。
G53 是网格噪声下的确认，主行的优势是真的就该过：只靠噪声，三个复算都掉到门槛下的概率极小（第二模型审查 N1）。它拦的是主行被这次网格撑出来的假优势。
描述（不判）：复算减主行的 ΔF、Δlog 微动（超过 1.4 mm 或 0.029 dex 标出）；复算和 3b 的 h 1.94 复算逐项比；主行和复算的平均。
9 行没全部终态（DONE 或 FAILED）之前三条都判不适用（审查 N4）。
F 的定义同 b28 的 gates.py。
"""
from __future__ import annotations

import csv
import glob
import math
import pathlib

import numpy as np

GATES = {
    "G53": "3 个候选里至少一个，h 2.0 主行和 h 1.94 重划复算都比 3b 好（定义同 b31 的 G49）。这是网格噪声下的确认，主行的优势是真的就该过。"
           "过：前沿越过 3b 得到确认；后面的批次用'可用的候选'（确认、G54 和 G55 都不判不过）代替 3b。"
           "不过：三个主行和复算都可判，没有一个两次都比 3b 好：R2 的优势经不起重划，3b 仍是确认过的最好。"
           "不适用：9 行没全部算完；或没有一个确认、而且有主行或复算失败、缺数据",
    "G54": "G53 确认的每个候选，坐起 1714 N 的转动 ≤ 相同去骨量下 A 族坐起转动的 1.10 倍（同 b28 的 G44）。过：确认的候选在坐起工况下转动不比 A 族差太多；"
           "不过：有确认的候选坐起转动偏大，报告时写明。没有确认的候选、坐起行缺或去骨量在坐起曲线外：不适用",
    "G55": "G53 确认的每个候选，h 1.4 对 h 2.0 的 log10 微动差 ≤ +0.062 dex（同 b28 的 G45，v0.11 里 11 对细网格的最大值）。过：确认的候选对网格不比已有设计敏感；"
           "不过：有确认的候选对网格敏感，报告时写明。没有确认的候选或 h 1.4 行缺：不适用",
}
T = "db_ws_p13_a105_91e458e3_"
CURVE = (T + "ow_m1_e+2.5_8a2bd628", T + "ow_m1_e+2_c9ca96c8", T + "ow_m1_e+1.5_52dc478a", T + "ow_m1_e+1_fea69910", T + "ow_m1_e+0.5_c17f7b2a", T + "m1_2a79b613", T + "ow_m1_e-0.5_03b0a7bc")
STS_CURVE = {"p13_a105_91e458e3_ow_m1_e+2.5_F1714": T + "ow_m1_e+2.5_8a2bd628", "p13_a105_91e458e3_ow_m1_e+2_F1714": T + "ow_m1_e+2_c9ca96c8",
             "p13_a105_91e458e3_ow_m1_e+1.5_F1714": T + "ow_m1_e+1.5_52dc478a", "p13_a105_91e458e3_ow_m1_e+1_F1714": T + "ow_m1_e+1_fea69910",
             "p13_a105_91e458e3_ow_m1_e+0.5_F1714": T + "ow_m1_e+0.5_c17f7b2a", "p13_a105_91e458e3_m1_F1714": T + "m1_2a79b613"}
JOB_3B, DF3, DL3, TOL_F, TOL_L = "db_al_fam1_3b_e+1.5_58336253", 9.68, -0.0738, 0.05, 0.002
JOB_3B_REP = "db_nz_fam1_3b_e+1.5_h1.94_88da6ea6"                      # 3b 的 h 1.94 复算（b28c），只用来描述
REP_FLAG_F, REP_FLAG_L = 1.4, 0.029                                       # 复算减主行超过这些就在描述里标出（重划的最大差）
IMP_F, IMP_L, IMP_L2, IMP_F2 = 3.0, math.log10(1.05), 0.05, 2.0
DF1, R1, R2, DF2 = 5.0, math.log10(1.05), math.log10(0.80), -2.0
MAX_STS, MAX_H14 = 1.10, 0.062
# 候选 → 主行的入口偏移；主行 tag = r2_<号>_e<偏移，:+g>
CAND = {"r2_01": 1.5, "r2_03": 1.5, "r2_12": 1.5}
N3 = np.array([0.381, 0.025, -0.924])
U_NECK = np.array([0.92228, 0.06137, 0.38162]) / np.linalg.norm([0.92228, 0.06137, 0.38162])
CREF = np.array([37.65271204198696, 0.8509371708090849, 41.89415555538172])


def f(x) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def pos(x) -> float | None:
    v = f(x)
    return v if v is not None and v > 0 else None


def tag_of(lab: str) -> str:
    return f"r2_{lab[3:]}_e{CAND[lab]:+g}"


def mesh_F(db_dir: str, want: set) -> dict:
    out = {}
    for p in sorted(glob.glob(str(pathlib.Path(db_dir) / "fields" / "iface_*.npz"))):
        z = np.load(p, allow_pickle=False)
        jobs = [str(j) for j in z["job_id"]]
        if not want & set(jobs):
            continue
        off, frame, X_, ar, dc, co = z["off"], z["frame"], z["X"], z["area"], z["d_canal"], z["collar"]
        for j, job in enumerate(jobs):
            if job not in want:
                continue
            a, b = off[j], off[j + 1]
            body = ~co[a:b]
            X, w, t = X_[a:b][body], ar[a:b][body], -dc[a:b][body]
            P0, ax = frame[j, 0], frame[j, 1]
            q = X - P0
            rad = q - (q @ ax)[:, None] * ax
            em = N3 - (N3 @ ax) * ax
            em /= np.linalg.norm(em)
            ep = np.array([0.0, 1.0, 0.0]) - ax[1] * ax
            ep /= np.linalg.norm(ep)
            th = np.degrees(np.arctan2(rad @ ep, rad @ em))
            m = (-(X - CREF) @ U_NECK <= 15) & (np.abs(th) <= 45)
            out[job] = float((w[m] / np.maximum(t[m], 0.25)).sum())
    return out


def one(by_tag: dict, tag: str):
    """(行, 原因)：没有这个 tag → 没提交；多行里恰好一行 DONE → 那行；否则 tag 重复。"""
    rs = by_tag.get(tag, [])
    if not rs:
        return None, "没提交"
    if len(rs) == 1:
        return rs[0], None
    done = [r for r in rs if r["status"] == "DONE"]
    return (done[0], None) if len(done) == 1 else (None, "tag 重复")


def better(dF: float, dl: float) -> bool:
    return (dF >= DF3 + IMP_F and dl <= DL3 + IMP_L) or (dl <= DL3 - IMP_L2 and dF >= DF3 - IMP_F2)


def beats_A(dF: float, dl: float) -> bool:
    return (dF >= DF1 and dl <= R1) or (dl <= R2 and dF >= DF2)


def judge(db_dir: str) -> dict:
    with open(pathlib.Path(db_dir) / "scalars.csv", encoding="utf-8") as fh:
        R = list(csv.DictReader(fh))
    by_id = {r["job_id"]: r for r in R}
    by_tag = {}
    for r in R:
        by_tag.setdefault(r["tag"], []).append(r)
    thr = {"G53": "better than 3b, main and h 1.94", "G54": MAX_STS, "G55": MAX_H14}

    def na_all(why):
        return {g: {"status": "NA", "value": None, "threshold": thr[g], "rows": [], "note": why} for g in GATES}
    miss = [j for j in (*CURVE, JOB_3B) if j not in by_id or by_id[j]["status"] != "DONE" or pos(by_id[j]["bone_total_mm3"]) is None or pos(by_id[j]["f1_p95_um"]) is None]
    if miss:
        return na_all(f"A 族曲线或 3b 缺行或缺数据 {miss}")
    main, rep, h14, sts = {}, {}, {}, {}
    for lab in CAND:
        main[lab], rep[lab], h14[lab], sts[lab] = (one(by_tag, tag_of(lab) + s) for s in ("", "_h1.94", "_h1.4", "_F1714"))
    pending = {f"{lab}{s_}": (why or r["status"]) for lab in CAND for s_, (r, why) in (("_h1.94", rep[lab]), ("_h1.4", h14[lab]), ("_F1714", sts[lab]))
               if r is None and why == "没提交" or r is not None and r["status"] not in ("DONE", "FAILED")}
    if pending:
        return na_all(f"批还没算完：{pending}")
    want = set(CURVE) | {JOB_3B, JOB_3B_REP} | {r["job_id"] for d in (main, rep) for r, _ in d.values() if r is not None and r["status"] == "DONE"}
    Fv = mesh_F(db_dir, want)
    if (set(CURVE) | {JOB_3B}) - {j for j in Fv if math.isfinite(Fv[j])}:
        return na_all(f"fields 里缺 A 族曲线或 3b 的界面节点 {sorted((set(CURVE) | {JOB_3B}) - set(Fv))}")
    cb = np.array([pos(by_id[j]["bone_total_mm3"]) / 1000 for j in CURVE])
    o = np.argsort(cb)
    cb, cF, cl = cb[o], np.array([Fv[j] for j in CURVE])[o], np.log10([pos(by_id[j]["f1_p95_um"]) for j in CURVE])[o]

    def gap(rw):
        """(去骨, ΔF, Δlog 微动) 或 (None, 原因)。"""
        r, why = rw
        if r is None:
            return None, why
        if r["status"] != "DONE":
            return None, "算失败" if r["status"] == "FAILED" else "没算完"
        b, f1 = pos(r["bone_total_mm3"]), pos(r["f1_p95_um"])
        if b is None:
            return None, "缺去骨量"
        if f1 is None:
            return None, "缺微动"
        if r["job_id"] not in Fv or not math.isfinite(Fv[r["job_id"]]):
            return None, "fields 里缺界面节点或 F 不是有限数"
        b /= 1000
        if not (cb[0] <= b <= cb[-1]):
            return None, f"去骨 {b:.2f} 在曲线外"
        return (b, Fv[r["job_id"]] - float(np.interp(b, cb, cF)), math.log10(f1) - float(np.interp(b, cb, cl))), None
    g3, why3 = gap((by_id[JOB_3B], None))
    if g3 is None or abs(g3[1] - DF3) > TOL_F or abs(g3[2] - DL3) > TOL_L:
        return na_all(f"3b 复核不上：记下 ({DF3}, {DL3})，现在 {why3 or (round(g3[1], 3), round(g3[2], 4))}")
    g3r, _ = gap((by_id.get(JOB_3B_REP), "3b 的复算不在库里"))
    table, confirmed, rep_bad = {}, [], {}
    for lab in CAND:
        gm, wm = gap(main[lab])
        gr, wr = gap(rep[lab])
        t = {}
        if gm is not None:
            t["main"] = {"bone": round(gm[0], 3), "dF_mm": round(gm[1], 2), "dlog_f1": round(gm[2], 4), "better_than_3b": better(gm[1], gm[2])}
        else:
            t["main"] = wm
            rep_bad[lab] = f"主行 {wm}"
        if gr is not None:
            t["h1.94"] = {"bone": round(gr[0], 3), "dF_mm": round(gr[1], 2), "dlog_f1": round(gr[2], 4), "better_than_3b": better(gr[1], gr[2]), "beats_A": beats_A(gr[1], gr[2])}
        else:
            t["h1.94"] = wr
            rep_bad[lab] = wr
        if gm is not None and gr is not None:
            d_F, d_l = gr[1] - gm[1], gr[2] - gm[2]
            t["rep_minus_main"] = {"dF_mm": round(d_F, 2), "dlog_f1": round(d_l, 4), "beyond_noise": abs(d_F) > REP_FLAG_F or abs(d_l) > REP_FLAG_L}
            t["mean_main_rep"] = {"dF_mm": round((gm[1] + gr[1]) / 2, 2), "dlog_f1": round((gm[2] + gr[2]) / 2, 4)}
            if g3r is not None:
                t["rep_vs_3b_rep"] = {"dF_mm": round(gr[1] - g3r[1], 2), "dlog_f1": round(gr[2] - g3r[2], 4)}
        if gm is not None and gr is not None and better(gm[1], gm[2]) and better(gr[1], gr[2]):
            confirmed.append(lab)
        table[lab] = t
    out = {}
    desc = (f"3b 复核 ({g3[1]:+.2f} mm, {g3[2]:+.4f} dex)；3b 的 h 1.94 复算 "
            f"{'缺' if g3r is None else f'({g3r[1]:+.2f} mm, {g3r[2]:+.4f} dex)'}；逐个候选 {table}")
    if confirmed:
        out["G53"] = {"status": "PASS", "value": confirmed, "threshold": thr["G53"], "rows": sorted(main[lab][0]["job_id"] for lab in confirmed) + sorted(rep[lab][0]["job_id"] for lab in confirmed),
                      "note": f"确认的候选 {confirmed}；" + desc}
    elif rep_bad:
        out["G53"] = {"status": "NA", "value": [], "threshold": thr["G53"], "rows": [], "note": f"没有确认的候选，复算不可判 {rep_bad}；" + desc}
    else:
        out["G53"] = {"status": "FAIL", "value": [], "threshold": thr["G53"], "rows": sorted(r["job_id"] for r, _ in rep.values() if r is not None), "note": "三个复算都不比 3b 好；" + desc}
    # G54、G55 只看确认的候选；未确认的候选的数只描述
    sc = []
    for t, base in STS_CURVE.items():
        r, _ = one(by_tag, t)
        if r is None or r["status"] != "DONE" or pos(r.get("rot_first_deg")) is None or base not in by_id or pos(by_id[base]["bone_total_mm3"]) is None:
            sc = None
            break
        sc.append((pos(by_id[base]["bone_total_mm3"]) / 1000, math.log10(pos(r["rot_first_deg"]))))
    ratios, shifts = {}, {}
    for lab in CAND:
        r, why = sts[lab]
        b = None if main[lab][0] is None else pos(main[lab][0]["bone_total_mm3"])
        if sc is None or r is None or r["status"] != "DONE" or pos(r.get("rot_first_deg")) is None or b is None:
            ratios[lab] = None
        else:
            sb, sr = (np.array(v) for v in zip(*sorted(sc)))
            ratios[lab] = round(10 ** (math.log10(pos(r["rot_first_deg"])) - float(np.interp(b / 1000, sb, sr))), 3) if sb[0] <= b / 1000 <= sb[-1] else None
        r0, r14 = main[lab][0], h14[lab][0]
        ok_ = r0 is not None and r14 is not None and r0["status"] == "DONE" and r14["status"] == "DONE" and pos(r0["f1_p95_um"]) and pos(r14["f1_p95_um"])
        shifts[lab] = round(math.log10(pos(r14["f1_p95_um"]) / pos(r0["f1_p95_um"])), 4) if ok_ else None
    if not confirmed:
        out["G54"] = {"status": "NA", "value": None, "threshold": MAX_STS, "rows": [], "note": f"没有确认的候选；坐起转动比 A 族（描述）{ratios}"}
        out["G55"] = {"status": "NA", "value": None, "threshold": MAX_H14, "rows": [], "note": f"没有确认的候选；h 1.4 减 h 2.0（描述）{shifts}"}
        return out
    cr = {lab: ratios[lab] for lab in confirmed}
    if sc is None or any(v is None for v in cr.values()):
        out["G54"] = {"status": "NA", "value": None, "threshold": MAX_STS, "rows": [], "note": f"坐起的 A 族曲线缺行，或确认的候选缺坐起行、去骨量在坐起曲线外：{ratios}"}
    else:
        w = max(cr.values())
        out["G54"] = {"status": "PASS" if w <= MAX_STS else "FAIL", "value": w, "threshold": MAX_STS, "rows": sorted(sts[lab][0]["job_id"] for lab in confirmed),
                      "note": f"坐起转动比 A 族，确认的 {cr}；全部（描述）{ratios}"}
    cs = {lab: shifts[lab] for lab in confirmed}
    usable = [lab for lab in confirmed if cr.get(lab) is not None and cr[lab] <= MAX_STS and cs.get(lab) is not None and cs[lab] <= MAX_H14]
    out["G54"]["note"] += f"；可用的候选（确认、坐起和 h 1.4 都不超）{usable}"
    if any(v is None for v in cs.values()):
        out["G55"] = {"status": "NA", "value": None, "threshold": MAX_H14, "rows": [], "note": f"确认的候选缺 h 1.4 行或缺数据：{shifts}"}
    else:
        w = max(cs.values())
        out["G55"] = {"status": "PASS" if w <= MAX_H14 else "FAIL", "value": w, "threshold": MAX_H14, "rows": sorted(h14[lab][0]["job_id"] for lab in confirmed),
                      "note": f"h 1.4 减 h 2.0 的 log10 微动，确认的 {cs}；全部（描述）{shifts}；可用的候选（确认、坐起和 h 1.4 都不超）{usable}"}
    return out
