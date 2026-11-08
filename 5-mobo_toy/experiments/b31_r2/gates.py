"""b31（R2，b28 的第二轮）的判据 G49、G50，看结果前定（2026-11-08，喂料前；第二模型审查后改，改了什么见 review.md）。
行在 experiments/prep_2026-11-08/data/r2_rows.json（sha256 24efdb13…），脚本 select_r2.py。

只读版本目录的 scalars.csv 和 fields/iface_*.npz。条件同 b28：δ 0.10，楼梯 2391 N，20° / 18°，h 2.0，μ 0.3，2 循环，只解摩擦，入口偏移固定。
比较基准同 b28：A 族曲线（7 行，按去骨量对新轴网格 F、log10 微动线性插值）。3b 在这把尺子上是 ΔF +9.68 mm、Δlog 微动 −0.0738 dex（v0.12，FE）；
这两个数当场用本文件的 mesh_F 从 3b 的作业重算，差过 0.05 mm 或 0.002 dex 两条判据都判不适用。
"比 3b 好"：ΔF ≥ 9.68 + 3 mm 且 Δlog ≤ −0.0738 + log10 1.05；或 Δlog ≤ −0.0738 − 0.05 且 ΔF ≥ 9.68 − 2 mm。两条路线混在一起算，不是帕累托意义的更好。
"保留 3b 一半以上的优势"：ΔF ≥ 9.68 / 2 mm 且 Δlog ≤ −0.0738 / 2 dex。
噪声：F 重划网格标准差约 0.6 mm；微动重划网格标准差 0.011 到 0.014 dex（b28 提议第 6 节，h 1.94、2.06 各 10 对；和 facts.json 的转动噪声 0.012 同值是巧合），
两次运行之差约 0.017 dex。3 mm 和 0.05 dex 都大于差值噪声的 2.5 倍；路线 1 对微动只容许比 3b 差 log10 1.05 = 0.021 dex，约 1.2 倍差值噪声，是软条件，
路线 1 的"更好"主要看 F。超过 A：b28 的两条路线，只描述。
"""
from __future__ import annotations

import csv
import glob
import math
import pathlib

import numpy as np

GATES = {
    "G49": "15 行里至少一行比 3b 好。过：3b 附近还能改进，前沿往这个方向推。"
           "不过：这 15 个代理选的点里没有明显比 3b 好的，不证明 3b 是局部最好。没有一行过、而且不可判的行 ≥ 3：不适用",
    "G50": "15 行里至少 8 行保留 3b 一半以上的优势（ΔF ≥ 4.84 mm 且 Δlog 微动 ≤ −0.0369 dex，相对同去骨量的 A 族）。"
           "过：3b 附近单位距离 0.15 以内，代理挑的点多数保住了 3b 一半以上的优势，3b 不是孤立的一个点；"
           "不过：3b 的优势在邻域里多数保不住一半，3b 接近孤立点，用它当候选要小心。不到 8 行、但加上不可判的行能到 8 行：不适用",
}
T = "db_ws_p13_a105_91e458e3_"
CURVE = (T + "ow_m1_e+2.5_8a2bd628", T + "ow_m1_e+2_c9ca96c8", T + "ow_m1_e+1.5_52dc478a", T + "ow_m1_e+1_fea69910", T + "ow_m1_e+0.5_c17f7b2a", T + "m1_2a79b613", T + "ow_m1_e-0.5_03b0a7bc")
JOB_3B, DF3, DL3, TOL_F, TOL_L = "db_al_fam1_3b_e+1.5_58336253", 9.68, -0.0738, 0.05, 0.002
IMP_F, IMP_L, IMP_L2, IMP_F2 = 3.0, math.log10(1.05), 0.05, 2.0
DF1, R1, R2, DF2 = 5.0, math.log10(1.05), math.log10(0.80), -2.0
MIN_HALF, NA_UNUSABLE = 8, 3
# 标签 → (入口偏移, 预测 log10 微动, 标定后的 σ dex)；预测只进 note
PRED = {"r2_01": (1.5, 1.31877, 0.02468), "r2_02": (1.5, 1.28110, 0.02498), "r2_03": (1.5, 1.26260, 0.02861), "r2_04": (1.0, 1.18497, 0.02536), "r2_05": (1.5, 1.34885, 0.02358), "r2_06": (1.0, 1.22171, 0.02864), "r2_07": (1.0, 1.22320, 0.02545), "r2_08": (1.5, 1.38557, 0.02693), "r2_09": (1.5, 1.31890, 0.02397), "r2_10": (1.0, 1.20932, 0.02529), "r2_11": (1.0, 1.20604, 0.02512), "r2_12": (1.5, 1.25725, 0.02313), "r2_13": (1.5, 1.55085, 0.03200), "r2_14": (1.0, 1.15037, 0.02919), "r2_15": (1.0, 1.18402, 0.02799)}
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
    return f"r2_{lab[3:]}_e{PRED[lab][0]:+g}"


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


def judge(db_dir: str) -> dict:
    with open(pathlib.Path(db_dir) / "scalars.csv", encoding="utf-8") as fh:
        R = list(csv.DictReader(fh))
    by_id = {r["job_id"]: r for r in R}
    by_tag = {}
    for r in R:
        by_tag.setdefault(r["tag"], []).append(r)
    thr = {"G49": 1, "G50": MIN_HALF}

    def na_all(why):
        return {g: {"status": "NA", "value": None, "threshold": thr[g], "rows": [], "note": why} for g in GATES}
    miss = [j for j in (*CURVE, JOB_3B) if j not in by_id or by_id[j]["status"] != "DONE" or pos(by_id[j]["bone_total_mm3"]) is None or pos(by_id[j]["f1_p95_um"]) is None]
    if miss:
        return na_all(f"A 族曲线或 3b 缺行或缺数据 {miss}")
    rows, why0 = {}, {}
    for lab in PRED:
        rows[lab], why0[lab] = one(by_tag, tag_of(lab))
    want = set(CURVE) | {JOB_3B} | {r["job_id"] for r in rows.values() if r is not None and r["status"] == "DONE"}
    Fv = mesh_F(db_dir, want)
    if (set(CURVE) | {JOB_3B}) - set(Fv):
        return na_all(f"fields 里缺 A 族曲线或 3b 的界面节点 {sorted((set(CURVE) | {JOB_3B}) - set(Fv))}")
    cb = np.array([pos(by_id[j]["bone_total_mm3"]) / 1000 for j in CURVE])
    o = np.argsort(cb)
    cb, cF, cl = cb[o], np.array([Fv[j] for j in CURVE])[o], np.log10([pos(by_id[j]["f1_p95_um"]) for j in CURVE])[o]

    def gap(r, why):
        """(去骨, ΔF, Δlog 微动) 或 (None, 原因)。"""
        if r is None:
            return None, why
        if r["status"] != "DONE":
            return None, "算失败" if r["status"] == "FAILED" else "没算完"
        b, f1 = pos(r["bone_total_mm3"]), pos(r["f1_p95_um"])
        if b is None:
            return None, "缺去骨量"
        if f1 is None:
            return None, "缺微动"
        if r["job_id"] not in Fv:
            return None, "fields 里缺界面节点"
        b /= 1000
        if not (cb[0] <= b <= cb[-1]):
            return None, f"去骨 {b:.2f} 在曲线外"
        return (b, Fv[r["job_id"]] - float(np.interp(b, cb, cF)), math.log10(f1) - float(np.interp(b, cb, cl))), None
    g3, why3 = gap(by_id[JOB_3B], None)
    if g3 is None or abs(g3[1] - DF3) > TOL_F or abs(g3[2] - DL3) > TOL_L:
        return na_all(f"3b 复核不上：记下 ({DF3}, {DL3})，现在 {why3 or (round(g3[1], 3), round(g3[2], 4))}")
    table, unusable, better, half, beat, err = {}, {}, [], [], [], {}
    for lab, r in rows.items():
        g, why = gap(r, why0[lab])
        if g is None:
            unusable[lab] = why
            continue
        b, dF, dl = g
        err[lab] = math.log10(pos(r["f1_p95_um"])) - PRED[lab][1]
        is_better = (dF >= DF3 + IMP_F and dl <= DL3 + IMP_L) or (dl <= DL3 - IMP_L2 and dF >= DF3 - IMP_F2)
        is_half = dF >= DF3 / 2 and dl <= DL3 / 2
        is_beat = (dF >= DF1 and dl <= R1) or (dl <= R2 and dF >= DF2)
        table[lab] = {"bone": round(b, 3), "dF_mm": round(dF, 2), "dlog_f1": round(dl, 4), "better_than_3b": is_better, "half_of_3b": is_half, "beats_A": is_beat}
        better += [lab] if is_better else []
        half += [lab] if is_half else []
        beat += [lab] if is_beat else []
    desc = f"3b 复核 ({g3[1]:+.2f} mm, {g3[2]:+.4f} dex)；逐行 {table}；不可判 {unusable or '无'}；按 b28 路线超过 A 的 {len(beat)} 行（描述）"
    if err:
        desc += f"；代理 FE 减预测 平均 {np.mean(list(err.values())):+.3f}，RMSE {np.sqrt(np.mean(np.square(list(err.values())))):.3f} dex（描述）"
    out = {}
    if better:
        out["G49"] = {"status": "PASS", "value": len(better), "threshold": 1, "rows": sorted(rows[lab]["job_id"] for lab in better), "note": f"比 3b 好的 {better}；" + desc}
    elif len(unusable) >= NA_UNUSABLE:
        out["G49"] = {"status": "NA", "value": 0, "threshold": 1, "rows": [], "note": f"没有一行比 3b 好，不可判的 {len(unusable)} 行 ≥ {NA_UNUSABLE}；" + desc}
    else:
        out["G49"] = {"status": "FAIL", "value": 0, "threshold": 1, "rows": sorted(r["job_id"] for r in rows.values() if r is not None), "note": f"可判的 {len(table)} 行没有一行比 3b 好；" + desc}
    if len(half) >= MIN_HALF:
        out["G50"] = {"status": "PASS", "value": len(half), "threshold": MIN_HALF, "rows": sorted(rows[lab]["job_id"] for lab in half), "note": f"保留一半以上优势的 {half}"}
    elif len(half) + len(unusable) >= MIN_HALF:
        out["G50"] = {"status": "NA", "value": len(half), "threshold": MIN_HALF, "rows": [], "note": f"保留一半以上优势的 {half}；不可判 {unusable}"}
    else:
        out["G50"] = {"status": "FAIL", "value": len(half), "threshold": MIN_HALF, "rows": sorted(r["job_id"] for r in rows.values() if r is not None), "note": f"保留一半以上优势的 {half}；不可判 {unusable or '无'}"}
    return out
