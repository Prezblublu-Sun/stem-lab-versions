"""b25（OPT-1）的判据 G36、G37，看结果前定（2026-11-04，喂料前）。选点和预测在研究日志 opt_F微动去骨_2026-11-04/。

只读版本目录的 scalars.csv 和 fields/iface_*.npz。条件都是基线：δ 0.10，楼梯 2391 N，20° / 18°，h 2.0，μ 0.3，2 循环。
F = Σ A / max(t, 0.25)，z ≤ 15 mm，内侧 ±45°，用网格界面节点算（同研究日志 zfe_fit_metric.py 的 z15_S_med）。微动 = f1_p95_um。去骨 = bone_total_mm3。
"A 族"= A 的 m 1.0 版在 e +2.5、+2、+1.5、+1、+0.5、0、−0.5 的 7 行，按去骨量对 F 线性插值、对 log10 微动线性插值。
"""
from __future__ import annotations

import csv
import glob
import math
import pathlib

import numpy as np

GATES = {
    "G36": "8 行里至少 2 行在相同去骨量下 F 比 A 族高 ≥ 3 mm 且微动 ≤ 0.96 倍。过：围绕这些行做第二轮；不过：停止，A 的 m 1.0 这一族就是这组目标下的前沿",
    "G37": "8 行的 log10 微动预测 RMSE ≤ 0.06 dex。不过：第二轮之前先改模型",
}
T = "db_ws_p13_a105_91e458e3_"
CURVE = (T + "ow_m1_e+2.5_8a2bd628", T + "ow_m1_e+2_c9ca96c8", T + "ow_m1_e+1.5_52dc478a", T + "ow_m1_e+1_fea69910", T + "ow_m1_e+0.5_c17f7b2a", T + "m1_2a79b613", T + "ow_m1_e-0.5_03b0a7bc")
# 选点时的预测（opt_F微动去骨_2026-11-04/data/opt1_rows.json），标签 → (F mm, 微动 µm)
PRED = {"opt1_01": (112.1, 22.49), "opt1_02": (117.3, 25.2), "opt1_03": (126.2, 15.29), "opt1_04": (126.7, 9.29), "opt1_05": (133.1, 11.21), "opt1_06": (134.0, 7.93), "opt1_07": (135.9, 6.41), "opt1_08": (141.2, 5.83)}
N3 = np.array([0.381, 0.025, -0.924])
U_NECK = np.array([0.9138995811072274, 0.06263424660728525, 0.4010791777242645])
CREF = np.array([37.65271204198696, 0.8509371708090849, 41.89415555538172])
MIN_F, MAX_RATIO, MIN_ROWS = 3.0, 0.96, 2
MAX_RMSE = 0.06


def f(x) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def mesh_F(db_dir: str, want: set) -> dict:
    """{job_id: F}，只算 want 里的作业。"""
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
            zeta = -(X - CREF) @ U_NECK
            m = (zeta <= 15) & (np.abs(th) <= 45)
            out[job] = float((w[m] / np.maximum(t[m], 0.25)).sum())
    return out


def judge(db_dir: str) -> dict:
    with open(pathlib.Path(db_dir) / "scalars.csv", encoding="utf-8") as fh:
        R = {r["job_id"]: r for r in csv.DictReader(fh)}
    new = {r["job_id"]: r for r in R.values() if r["job_id"].startswith("db_al_opt1_")}
    done = {j: r for j, r in new.items() if r["status"] == "DONE" and f(r["f1_p95_um"]) is not None}
    miss = [j for j in CURVE if j not in R or R[j]["status"] != "DONE"]
    if miss or len(done) < len(PRED):
        note = f"缺行：A 族 {miss}；OPT-1 算完 {len(done)} / {len(PRED)} 行，FAILED {[j for j, r in new.items() if r['status'] == 'FAILED']}"
        return {g: {"status": "NA", "value": None, "threshold": (MIN_ROWS if g == "G36" else MAX_RMSE), "rows": sorted(new), "note": note} for g in GATES}
    Fv = mesh_F(db_dir, set(CURVE) | set(done))
    if set(CURVE) - set(Fv) or set(done) - set(Fv):
        note = f"fields/ 里缺界面节点：{sorted((set(CURVE) | set(done)) - set(Fv))}"
        return {g: {"status": "NA", "value": None, "threshold": (MIN_ROWS if g == "G36" else MAX_RMSE), "rows": sorted(new), "note": note} for g in GATES}
    cb = np.array([f(R[j]["bone_total_mm3"]) / 1000 for j in CURVE])
    cF = np.array([Fv[j] for j in CURVE])
    cl = np.log10([f(R[j]["f1_p95_um"]) for j in CURVE])
    o = np.argsort(cb)
    cb, cF, cl = cb[o], cF[o], cl[o]
    table, good, errs = {}, [], []
    for j, r in sorted(done.items()):
        tag = "_".join(j.split("_")[2:4])
        b, f1 = f(r["bone_total_mm3"]) / 1000, f(r["f1_p95_um"])
        dF = Fv[j] - float(np.interp(b, cb, cF))
        ratio = f1 / 10 ** float(np.interp(b, cb, cl))
        hit = dF >= MIN_F and ratio <= MAX_RATIO
        good += [j] if hit else []
        errs.append(math.log10(PRED[tag][1]) - math.log10(f1))
        table[tag] = {"bone_cm3": round(b, 3), "F_mm": round(Fv[j], 1), "F_pred_mm": PRED[tag][0], "f1_um": round(f1, 2), "f1_pred_um": PRED[tag][1], "rot_stair_deg": f(r["rot_first_deg"]), "dF_vs_A_mm": round(dF, 1), "f1_vs_A": round(ratio, 3), "improved": hit}
    rmse = float(np.sqrt(np.mean(np.square(errs))))
    return {"G36": {"status": "PASS" if len(good) >= MIN_ROWS else "FAIL", "value": len(good), "threshold": MIN_ROWS, "rows": sorted(done), "note": f"改进的行 {good}；逐行 {table}"},
            "G37": {"status": "PASS" if rmse <= MAX_RMSE else "FAIL", "value": round(rmse, 4), "threshold": MAX_RMSE, "rows": sorted(done), "note": f"预测减 FE 的偏差 {np.mean(errs):+.3f} dex，最大 {max(np.abs(errs)):.3f} dex"}}
