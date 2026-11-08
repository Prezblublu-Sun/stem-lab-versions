"""b28（FAM-1）的判据 G41–G45，看结果前定（2026-11-08，喂料前；第二模型审查后改过一次，见 review.md 和 approval.md）。选点和预测在 experiments/b28_fam/prep/。

只读版本目录的 scalars.csv 和 fields/iface_*.npz。条件：δ 0.10，楼梯 2391 N，20° / 18°，h 2.0，μ 0.3，2 循环，只解摩擦；对照和复算行 h 1.94，网格核对行 h 1.4，坐起行 1714 N 24° / 8°。
F = Σ A / max(t, 0.25)，z ≤ 15 mm，|θ| ≤ 45°，用网格界面节点算。深度轴 U_NECK 是新轴（ops/facts.json neck_axis_u）；z 从 CREF 起量，CREF 是
geometry.json stems.sb13_a105_91e458e3.cut_centre（A 的截骨中心）；θ 的零方向 N3 = 远端方向 −z 在颈截面上的投影（单位化，指向股骨距一侧），与 U_NECK 垂直。
微动 = f1_p95_um。去骨 = bone_total_mm3。只解摩擦和带粘接的同一物理行，微动逐位相同（v0.11 里 4 对，最大差 9e-5 dex），所以主行只解摩擦、曲线行带粘接可以比。
"A 族曲线" = A 的 m 1.0 版在 e +2.5、+2、+1.5、+1、+0.5、0、−0.5 的 7 行（楼梯，h 2.0），按去骨量对 F 线性插值、对 log10 微动线性插值。
一行"超过 A"：路线 1，F ≥ A + 5 mm 且微动 ≤ 1.05 × A；或路线 2，微动 ≤ 0.80 × A 且 F ≥ A − 2 mm。
G43 实际只由 2 mm、0.04 dex 两个界限决定（在这两个界限内两条路线都不可能触发）。
"""
from __future__ import annotations

import csv
import glob
import math
import pathlib

import numpy as np

GATES = {
    "G41": "5 个方向族里至少 1 个族有一行超过 A，且它的 h 1.94 重划复算也超过 A。过：在这些族里开第二轮（另行批准）；不过：15 行都算完、都可比，且没有一行超过 A，和 G42 一起读。有行没算完、算失败或缺数据时不判不过，判不适用",
    "G42": "15 行全部算完时，微动代理的 log10 RMSE ≤ 0.10 dex，且标定后 90 % 区间的覆盖 ≥ 0.70。过：代理在环带也能用；不过：环带只能靠 FE 铺点。有行失败或缺数据：不适用",
    "G43": "2 行阴性对照（A 的 m 1.0 版 e +1、e +2，h 1.94）相对 A 族曲线微动差 ≤ 0.04 dex、F 差 ≤ 2 mm。不过：G41 判为不适用",
    "G44": "G41 的每个赢家，坐起 1714 N 的转动 ≤ 相同去骨量下 A 族坐起转动的 1.10 倍。没有赢家，或去骨量在坐起曲线外：不适用",
    "G45": "G41 的每个赢家，h 1.4 对 h 2.0 的微动差 ≤ +0.062 dex（v0.11 里 11 对细网格的最大值）。过：赢家的微动对网格的敏感程度不超过已有设计；不过：赢家对网格敏感，报告时写明。没有赢家：不适用",
}
T = "db_ws_p13_a105_91e458e3_"
CURVE = (T + "ow_m1_e+2.5_8a2bd628", T + "ow_m1_e+2_c9ca96c8", T + "ow_m1_e+1.5_52dc478a", T + "ow_m1_e+1_fea69910", T + "ow_m1_e+0.5_c17f7b2a", T + "m1_2a79b613", T + "ow_m1_e-0.5_03b0a7bc")
# 坐起 1714 N 的 A 族（b26），标签 → 楼梯基线行（取去骨量）
STS_CURVE = {"p13_a105_91e458e3_ow_m1_e+2.5_F1714": T + "ow_m1_e+2.5_8a2bd628", "p13_a105_91e458e3_ow_m1_e+2_F1714": T + "ow_m1_e+2_c9ca96c8",
             "p13_a105_91e458e3_ow_m1_e+1.5_F1714": T + "ow_m1_e+1.5_52dc478a", "p13_a105_91e458e3_ow_m1_e+1_F1714": T + "ow_m1_e+1_fea69910",
             "p13_a105_91e458e3_ow_m1_e+0.5_F1714": T + "ow_m1_e+0.5_c17f7b2a", "p13_a105_91e458e3_m1_F1714": T + "m1_2a79b613"}
# 15 行：标签 → 入口偏移；行的 tag = fam1_<标签>_e<偏移，:+g>，复算 + "_h1.94"，网格核对 + "_h1.4"，坐起 + "_F1714"
ROWS = {"0b": 1.5, "0o": 1.0, "0x": 2.0, "1b": 2.0, "1o": 0.5, "1x": 0.5, "2b": 0.5, "2o": 0.0, "2x": 2.0, "3b": 1.5, "3o": 0.5, "3x": 0.5, "4b": 2.0, "4o": 2.5, "4x": 2.5}
# 选点时的预测：标签 → (log10 微动, 标定后的 σ dex)；快速 F（网格尺度，mm）只作描述，不进判据。prep/data/fam1_rows.json
PRED = {"0b": (1.49570, 0.04107), "0o": (1.79919, 0.05084), "0x": (1.99791, 0.06530), "1b": (1.51031, 0.04599), "1o": (2.07760, 0.07039), "1x": (1.84483, 0.09522),
        "2b": (1.31186, 0.04718), "2o": (1.19463, 0.04540), "2x": (1.87355, 0.06840), "3b": (1.38344, 0.03445), "3o": (1.30816, 0.04103), "3x": (2.06277, 0.09602),
        "4b": (1.61493, 0.04049), "4o": (1.68003, 0.04303), "4x": (1.85927, 0.05947)}
FAST_F = {"0b": 116.90, "0o": 111.19, "0x": 98.61, "1b": 116.46, "1o": 105.33, "1x": 107.89, "2b": 130.63, "2o": 139.48, "2x": 94.39, "3b": 120.72, "3o": 126.78, "3x": 109.33,
          "4b": 110.10, "4o": 102.29, "4x": 100.27}
CONTROLS = {"e+1": "p13_a105_91e458e3_ow_m1_e+1_h1.94", "e+2": "p13_a105_91e458e3_ow_m1_e+2_h1.94"}
N3 = np.array([0.381, 0.025, -0.924])
U_NECK = np.array([0.92228, 0.06137, 0.38162]) / np.linalg.norm([0.92228, 0.06137, 0.38162])
CREF = np.array([37.65271204198696, 0.8509371708090849, 41.89415555538172])
DF1, R1, R2, DF2 = 5.0, math.log10(1.05), math.log10(0.80), -2.0
MAX_RMSE, MIN_COVER = 0.10, 0.70
CTRL_DL, CTRL_DF = 0.04, 2.0
MAX_STS = 1.10
MAX_H14 = 0.062


def f(x) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def tag_of(lab: str) -> str:
    return f"fam1_{lab}_e{ROWS[lab]:+g}"


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


def beats(dF: float, dl: float) -> bool:
    return (dF >= DF1 and dl <= R1) or (dl <= R2 and dF >= DF2)


def na_all(note: str) -> dict:
    return {g: {"status": "NA", "value": None, "threshold": None, "rows": [], "note": note} for g in GATES}


def judge(db_dir: str) -> dict:
    with open(pathlib.Path(db_dir) / "scalars.csv", encoding="utf-8") as fh:
        R = list(csv.DictReader(fh))
    by_id = {r["job_id"]: r for r in R}
    by_tag = {}
    for r in R:
        by_tag.setdefault(r["tag"], []).append(r)
    dups = sorted(t for t, v in by_tag.items() if len(v) > 1 and (t.startswith("fam1_") or t in CONTROLS.values()))

    def one(tag: str):
        rs = by_tag.get(tag, [])
        return rs[0] if len(rs) == 1 else None
    miss = [j for j in CURVE if j not in by_id or by_id[j]["status"] != "DONE" or f(by_id[j]["bone_total_mm3"]) is None or f(by_id[j]["f1_p95_um"]) is None]
    if miss:
        return na_all(f"A 族曲线缺行或缺数据 {miss}")
    rows = {lab: one(tag_of(lab)) for lab in ROWS}
    reps = {lab: one(tag_of(lab) + "_h1.94") for lab in ROWS}
    ctrls = {k: one(t) for k, t in CONTROLS.items()}
    want = set(CURVE) | {r["job_id"] for r in [*rows.values(), *reps.values(), *ctrls.values()] if r is not None and r["status"] == "DONE"}
    Fv = mesh_F(db_dir, want)
    if set(CURVE) - set(Fv):
        return na_all(f"fields 里缺 A 族曲线的界面节点 {sorted(set(CURVE) - set(Fv))}")
    cb = np.array([f(by_id[j]["bone_total_mm3"]) / 1000 for j in CURVE])
    cF = np.array([Fv[j] for j in CURVE])
    cl = np.log10([f(by_id[j]["f1_p95_um"]) for j in CURVE])
    o = np.argsort(cb)
    cb, cF, cl = cb[o], cF[o], cl[o]

    def gap(r):
        """(去骨, ΔF, Δlog 微动) 或 (None, 原因)。原因：失败、没算完、缺 F、缺微动、去骨缺失、在曲线外。"""
        if r is None:
            return None, "没算完或 tag 重复"
        if r["status"] == "FAILED":
            return None, "算失败"
        if r["status"] != "DONE":
            return None, "没算完"
        b, f1 = f(r["bone_total_mm3"]), f(r["f1_p95_um"])
        if b is None:
            return None, "缺去骨量"
        if f1 is None:
            return None, "缺微动"
        if r["job_id"] not in Fv:
            return None, "fields 里缺界面节点"
        b /= 1000
        if not (cb[0] <= b <= cb[-1]):
            return None, "去骨量在曲线外"
        return (b, Fv[r["job_id"]] - float(np.interp(b, cb, cF)), math.log10(f1) - float(np.interp(b, cb, cl))), None
    out = {}
    # G43
    ctab, cok, cbad = {}, True, []
    for k, r in ctrls.items():
        g, why = gap(r)
        if g is None:
            cbad.append(f"{k} {why}")
            continue
        ctab[k] = (round(g[1], 2), round(g[2], 4))
        cok &= abs(g[1]) <= CTRL_DF and abs(g[2]) <= CTRL_DL
    if cbad:
        out["G43"] = {"status": "NA", "value": None, "threshold": [CTRL_DF, CTRL_DL], "rows": [], "note": f"对照不可用：{cbad}"}
    else:
        out["G43"] = {"status": "PASS" if cok else "FAIL", "value": ctab, "threshold": [CTRL_DF, CTRL_DL], "rows": [r["job_id"] for r in ctrls.values()], "note": "（ΔF mm, Δlog10 微动）"}
    # G42
    bad42 = {lab: (gap(r)[1] if r is None or r["status"] != "DONE" or f(r["f1_p95_um"]) is None else None) for lab, r in rows.items()}
    bad42 = {k: v for k, v in bad42.items() if v is not None}
    if bad42:
        out["G42"] = {"status": "NA", "value": None, "threshold": [MAX_RMSE, MIN_COVER], "rows": [],
                      "note": f"不是 15 行都有微动：{bad42}；缺的行的预测 {{k: round(10 ** PRED[k][0], 1) for k in bad42}} µm".replace("{k: round(10 ** PRED[k][0], 1) for k in bad42}", str({k: round(10 ** PRED[k][0], 1) for k in bad42}))}
    else:
        err = {lab: math.log10(f(r["f1_p95_um"])) - PRED[lab][0] for lab, r in rows.items()}
        rmse = float(np.sqrt(np.mean(np.square(list(err.values())))))
        cover = float(np.mean([abs(e) <= 1.645 * PRED[lab][1] for lab, e in err.items()]))
        role_mean = {role: round(float(np.mean([e for lab, e in err.items() if lab[1] == role])), 3) for role in "box"}
        fdesc = {lab: round(Fv[r["job_id"]] - FAST_F[lab], 1) for lab, r in rows.items() if r["job_id"] in Fv}
        out["G42"] = {"status": "PASS" if rmse <= MAX_RMSE and cover >= MIN_COVER else "FAIL", "value": [round(rmse, 4), round(cover, 3)], "threshold": [MAX_RMSE, MIN_COVER],
                      "rows": sorted(r["job_id"] for r in rows.values()),
                      "note": "FE 减预测 dex：" + str({k: round(v, 3) for k, v in err.items()}) + f"；平均 {np.mean(list(err.values())):+.3f}；按角色平均（b 最好、o 外圈、x 探索）{role_mean}"
                              + f"；网格 F 减快速 F mm（描述，不判）{fdesc}"}
    # G41
    table, winners, pending, unusable = {}, [], [], {}
    for lab, r in rows.items():
        g, why = gap(r)
        if g is None:
            unusable[lab] = why
            continue
        hit = beats(g[1], g[2])
        table[lab] = {"bone": round(g[0], 3), "dF_mm": round(g[1], 2), "dlog_f1": round(g[2], 4), "beats": hit}
        if hit:
            gr, whyr = gap(reps[lab])
            if gr is None:
                table[lab]["replicate"] = whyr
                pending.append(lab)
                continue
            okr = beats(gr[1], gr[2])
            table[lab]["replicate"] = {"dF_mm": round(gr[1], 2), "dlog_f1": round(gr[2], 4), "beats": okr}
            if okr:
                winners.append(lab)
    fams = sorted({lab[0] for lab in winners})
    g43 = out["G43"]["status"]
    if g43 != "PASS":
        out["G41"] = {"status": "NA", "value": None, "threshold": 1, "rows": [], "note": f"G43 {g43}；逐行 {table}；不可用 {unusable}"}
    elif fams:
        out["G41"] = {"status": "PASS", "value": len(fams), "threshold": 1, "rows": sorted(r["job_id"] for r in rows.values() if r is not None),
                      "note": f"确认的赢家 {winners}，族 {fams}；待复算 {pending}；不可用 {unusable}；逐行 {table}；tag 重复 {dups}"}
    elif pending or unusable:
        out["G41"] = {"status": "NA", "value": None, "threshold": 1, "rows": [], "note": f"没有确认的赢家，但不是 15 行都可判：待复算 {pending}，不可用 {unusable}（{15 - len(unusable)} / 15 行可判）；逐行 {table}；tag 重复 {dups}"}
    else:
        out["G41"] = {"status": "FAIL", "value": 0, "threshold": 1, "rows": sorted(r["job_id"] for r in rows.values()), "note": f"15 行都可判，没有一行超过 A 后复算也成立；逐行 {table}"}
    # G44、G45：只看确认的赢家
    if out["G41"]["status"] != "PASS":
        out["G44"] = {"status": "NA", "value": None, "threshold": MAX_STS, "rows": [], "note": "没有确认的赢家"}
        out["G45"] = {"status": "NA", "value": None, "threshold": MAX_H14, "rows": [], "note": "没有确认的赢家"}
        return out
    sts = []
    for t, base in STS_CURVE.items():
        r = one(t)
        if r is None or r["status"] != "DONE" or f(r["rot_first_deg"]) is None or f(by_id[base]["bone_total_mm3"]) is None:
            sts = None
            break
        sts.append((f(by_id[base]["bone_total_mm3"]) / 1000, math.log10(f(r["rot_first_deg"]))))
    if sts is None:
        out["G44"] = {"status": "NA", "value": None, "threshold": MAX_STS, "rows": [], "note": "坐起的 A 族曲线缺行或缺数据"}
    else:
        sb, sr = (np.array(v) for v in zip(*sorted(sts)))
        ratios, used = {}, []
        for lab in winners:
            r = one(tag_of(lab) + "_F1714")
            b = None if r is None else f(r["bone_total_mm3"])
            if r is None or r["status"] != "DONE" or f(r["rot_first_deg"]) is None or b is None or not (sb[0] <= b / 1000 <= sb[-1]):
                ratios[lab] = None
                continue
            ratios[lab] = round(10 ** (math.log10(f(r["rot_first_deg"])) - float(np.interp(b / 1000, sb, sr))), 3)
            used.append(r["job_id"])
        if any(v is None for v in ratios.values()):
            out["G44"] = {"status": "NA", "value": None, "threshold": MAX_STS, "rows": used, "note": f"赢家缺坐起行、缺数据或去骨量在坐起曲线 {sb[0]:.2f} 到 {sb[-1]:.2f} cm³ 外：{ratios}"}
        else:
            w = max(ratios.values())
            out["G44"] = {"status": "PASS" if w <= MAX_STS else "FAIL", "value": w, "threshold": MAX_STS, "rows": used, "note": f"坐起转动比 A 族：{ratios}"}
    shifts, used = {}, []
    for lab in winners:
        r0, r14 = rows[lab], one(tag_of(lab) + "_h1.4")
        if r14 is None or r14["status"] != "DONE" or f(r14["f1_p95_um"]) is None:
            shifts[lab] = None
            continue
        shifts[lab] = round(math.log10(f(r14["f1_p95_um"]) / f(r0["f1_p95_um"])), 4)
        used.append(r14["job_id"])
    if any(v is None for v in shifts.values()):
        out["G45"] = {"status": "NA", "value": None, "threshold": MAX_H14, "rows": used, "note": f"赢家缺 h 1.4 行或缺数据：{shifts}"}
    else:
        w = max(shifts.values())
        out["G45"] = {"status": "PASS" if w <= MAX_H14 else "FAIL", "value": w, "threshold": MAX_H14, "rows": used, "note": f"h 1.4 减 h 2.0 的 log10 微动：{shifts}"}
    return out
