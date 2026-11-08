"""b29（RS-1）的判据 G46，看结果前定（2026-11-08，喂料前；第二模型审查后改，改了什么见 review.md）。
行在 experiments/prep_2026-11-08/data/rs1_rows.json（sha256 6c75e048…），不看分数随机抽取，脚本 select_rs1.py。

只读版本目录的 scalars.csv 和 fields/iface_*.npz。条件：δ 0.10，楼梯 2391 N，20° / 18°，h 2.0，μ 0.3，2 循环，只解摩擦（与全解的微动一致，b28 前 4 对最大差 9e-5 dex）。
总体：b28 的环带候选（b28_fam/prep/ring_inputs.py，种子 56103：13 维随机方向，半径在 0.25 到 0.75 里均匀，留在盒内且 m ≥ 1，没有用代理预筛），
生产模板化在 e 0、+1、+2 可行的对，去掉和 b28 的行重合的。半径均匀不是体积均匀，内圈更密。没有做放置检查。
G46 检验 b28 选点时冻结的微动代理（PRED）在这个总体上的误差。行不是按代理挑的，所以没有选择偏差；它不检验代理挑出来的最优点、
可放置的子集，也不检验 R2 用的重训版（PRED2，喂料前冻结，只描述，experiments/prep_2026-11-08/pred2_rs1.py）。
描述（不判）：预测 ≤ 1.6（40 µm）的子集；缺行取最坏误差时 RMSE 的上界；按入口偏移分开；每行相对 A 族曲线的 ΔF、Δlog 微动，有几行按 b28 的 G41 路线超过 A 族。
F 的定义同 b28 的 gates.py：Σ 面积 / max(间隙, 0.25)，颈轴 U_NECK 取 ops/facts.json neck_axis_u（模型坐标，朝向头），截骨中心 15 mm 以内，|θ| ≤ 45°。
"""
from __future__ import annotations

import csv
import glob
import math
import pathlib

import numpy as np

GATES = {
    "G46": "RS-1 48 行上，b28 代理（选点时冻结）的 log10 RMSE ≤ 0.07 dex（只算有微动的行），且标定后 90 % 区间的覆盖 ≥ 0.70（分母 48，没有微动的行算没覆盖）。"
           "没有微动的行超过 8 行：不适用。过：在环带的随机总体上，代理的误差和标定区间可信，可以靠代理在环带排序再用 FE 核对；不外推到代理挑出的最优点、可放置的子集和 R2 的重训版。"
           "不过：环带上代理的误差比标定的大，环带要继续靠 FE 铺点",
}
T = "db_ws_p13_a105_91e458e3_"
CURVE = (T + "ow_m1_e+2.5_8a2bd628", T + "ow_m1_e+2_c9ca96c8", T + "ow_m1_e+1.5_52dc478a", T + "ow_m1_e+1_fea69910", T + "ow_m1_e+0.5_c17f7b2a", T + "m1_2a79b613", T + "ow_m1_e-0.5_03b0a7bc")
N3 = np.array([0.381, 0.025, -0.924])
U_NECK = np.array([0.92228, 0.06137, 0.38162]) / np.linalg.norm([0.92228, 0.06137, 0.38162])
CREF = np.array([37.65271204198696, 0.8509371708090849, 41.89415555538172])
DF1, R1, R2, DF2 = 5.0, math.log10(1.05), math.log10(0.80), -2.0
MAX_RMSE, MIN_COVER, MAX_BAD, LOW = 0.07, 0.70, 8, 1.6
# 标签 → (入口偏移, 预测 log10 微动, 标定后的 σ dex)；和 rs1_rows.json 到 5 位小数一致（rs29 的 2.00000 是 1.9999995，不是手填）
PRED = {"rs01": (0.0, 2.39273, 0.05574), "rs02": (0.0, 1.54231, 0.03304), "rs03": (2.0, 1.87070, 0.04506), "rs04": (2.0, 1.87404, 0.06159), "rs05": (1.0, 1.50911, 0.03036), "rs06": (1.0, 1.62497, 0.03757), "rs07": (2.0, 1.64194, 0.03707), "rs08": (0.0, 2.40186, 0.07364), "rs09": (1.0, 1.59543, 0.03202), "rs10": (0.0, 1.60556, 0.04298), "rs11": (1.0, 2.19214, 0.06003), "rs12": (2.0, 2.03310, 0.04622), "rs13": (0.0, 1.74424, 0.03665), "rs14": (0.0, 1.53560, 0.04283), "rs15": (2.0, 2.22463, 0.06804), "rs16": (1.0, 1.97015, 0.04688), "rs17": (1.0, 2.27513, 0.05295), "rs18": (1.0, 2.20812, 0.04867), "rs19": (1.0, 2.04250, 0.05568), "rs20": (1.0, 2.23562, 0.04489), "rs21": (2.0, 2.17041, 0.06145), "rs22": (0.0, 1.91528, 0.04492), "rs23": (1.0, 2.23154, 0.05832), "rs24": (0.0, 1.72138, 0.03384), "rs25": (0.0, 2.05300, 0.04347), "rs26": (2.0, 2.11117, 0.04731), "rs27": (0.0, 1.29549, 0.02649), "rs28": (2.0, 1.90926, 0.04727), "rs29": (0.0, 2.00000, 0.04300), "rs30": (1.0, 1.84123, 0.03900), "rs31": (1.0, 1.96988, 0.04631), "rs32": (0.0, 1.60716, 0.03200), "rs33": (1.0, 1.33696, 0.03960), "rs34": (0.0, 1.75518, 0.03645), "rs35": (2.0, 2.30557, 0.06821), "rs36": (0.0, 1.74272, 0.04749), "rs37": (1.0, 1.89156, 0.03832), "rs38": (1.0, 1.78168, 0.04540), "rs39": (0.0, 1.25628, 0.03032), "rs40": (0.0, 1.61442, 0.03590), "rs41": (0.0, 2.40187, 0.05920), "rs42": (2.0, 2.05584, 0.04396), "rs43": (0.0, 1.65894, 0.03204), "rs44": (1.0, 2.20633, 0.05367), "rs45": (2.0, 1.72478, 0.03934), "rs46": (2.0, 1.80130, 0.05445), "rs47": (1.0, 1.64126, 0.05103), "rs48": (0.0, 2.32742, 0.06060)}
# R2 用的重训版（b28 的 GP 加 b28 的 14 行）对同 48 行的预测，(预测 log10 微动, 标定后的 σ dex)，data/rs1_pred2.json，只进描述
PRED2 = {"rs01": (2.37988, 0.05602), "rs02": (1.53581, 0.03208), "rs03": (1.90054, 0.03701), "rs04": (1.86478, 0.03718), "rs05": (1.50118, 0.02975), "rs06": (1.62538, 0.03794), "rs07": (1.65740, 0.03521), "rs08": (2.37728, 0.06931), "rs09": (1.59385, 0.03166), "rs10": (1.59243, 0.04365), "rs11": (2.18291, 0.05903), "rs12": (2.02754, 0.04442), "rs13": (1.73030, 0.03519), "rs14": (1.53008, 0.04102), "rs15": (2.22569, 0.06510), "rs16": (1.96893, 0.04952), "rs17": (2.27405, 0.05303), "rs18": (2.21597, 0.04939), "rs19": (2.01467, 0.04073), "rs20": (2.23325, 0.04396), "rs21": (2.14670, 0.04491), "rs22": (1.92794, 0.04095), "rs23": (2.21433, 0.05023), "rs24": (1.71704, 0.03344), "rs25": (2.03539, 0.04224), "rs26": (2.12129, 0.04653), "rs27": (1.29134, 0.02742), "rs28": (1.90199, 0.03789), "rs29": (1.99971, 0.04298), "rs30": (1.83531, 0.03844), "rs31": (1.97514, 0.04426), "rs32": (1.60499, 0.03195), "rs33": (1.31895, 0.03805), "rs34": (1.74281, 0.03580), "rs35": (2.28168, 0.06059), "rs36": (1.69768, 0.03729), "rs37": (1.89438, 0.03836), "rs38": (1.77971, 0.03903), "rs39": (1.24499, 0.03087), "rs40": (1.60559, 0.03387), "rs41": (2.40751, 0.05851), "rs42": (2.06322, 0.04005), "rs43": (1.65295, 0.03287), "rs44": (2.21353, 0.05208), "rs45": (1.71998, 0.02848), "rs46": (1.76926, 0.03185), "rs47": (1.59966, 0.04720), "rs48": (2.32818, 0.05984)}


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
    return f"rs1_{lab[2:]}_e{PRED[lab][0]:+g}"


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


def why_bad(r, why):
    """None = 有微动；否则原因：没提交、tag 重复、算失败、没算完、缺微动。"""
    if r is None:
        return why
    if r["status"] != "DONE":
        return "算失败" if r["status"] == "FAILED" else "没算完"
    return None if pos(r["f1_p95_um"]) is not None else "缺微动"


def stats(err: dict, sig: dict, n_all: int) -> tuple:
    """(RMSE, 覆盖)；覆盖的分母是 n_all，缺的行算没覆盖。"""
    if not err:
        return None, None
    rmse = float(np.sqrt(np.mean(np.square(list(err.values())))))
    return round(rmse, 4), round(sum(abs(e) <= 1.645 * sig[k] for k, e in err.items()) / n_all, 3)


def describe_A(db_dir: str, R: list, got: dict) -> str:
    """描述（不判）：相对 A 族曲线。"""
    by_id = {r["job_id"]: r for r in R}
    if any(j not in by_id or by_id[j]["status"] != "DONE" or pos(by_id[j]["f1_p95_um"]) is None or pos(by_id[j]["bone_total_mm3"]) is None for j in CURVE):
        return "A 族曲线缺行或缺数据，不描述"
    Fv = mesh_F(db_dir, set(CURVE) | {r["job_id"] for r in got.values()})
    if set(CURVE) - set(Fv):
        return "fields 里缺 A 族曲线的界面节点，不描述"
    cb = np.array([pos(by_id[j]["bone_total_mm3"]) / 1000 for j in CURVE])
    o = np.argsort(cb)
    cb, cF, cl = cb[o], np.array([Fv[j] for j in CURVE])[o], np.log10([pos(by_id[j]["f1_p95_um"]) for j in CURVE])[o]
    beat, table = [], {}
    for lab, r in got.items():
        b = pos(r["bone_total_mm3"])
        if b is None or not (cb[0] <= b / 1000 <= cb[-1]) or r["job_id"] not in Fv:
            continue
        b /= 1000
        dF = Fv[r["job_id"]] - float(np.interp(b, cb, cF))
        dl = math.log10(pos(r["f1_p95_um"])) - float(np.interp(b, cb, cl))
        table[lab] = (round(b, 2), round(dF, 1), round(dl, 3))
        if (dF >= DF1 and dl <= R1) or (dl <= R2 and dF >= DF2):
            beat.append(lab)
    return f"去骨在 A 族曲线范围内的 {len(table)} 行，按 G41 路线超过 A 族的 {beat}；逐行（去骨 cm³, ΔF mm, Δlog 微动）{table}"


def judge(db_dir: str) -> dict:
    with open(pathlib.Path(db_dir) / "scalars.csv", encoding="utf-8") as fh:
        R = list(csv.DictReader(fh))
    by_tag = {}
    for r in R:
        by_tag.setdefault(r["tag"], []).append(r)
    got, bad = {}, {}
    for lab in PRED:
        r, why = one(by_tag, tag_of(lab))
        why = why_bad(r, why)
        if why is None:
            got[lab] = r
        else:
            bad[lab] = why
    kinds = {k: sorted(lab for lab, w in bad.items() if w == k) for k in ("没提交", "tag 重复", "算失败", "没算完", "缺微动")}
    kinds = {k: v for k, v in kinds.items() if v}
    thr = [MAX_RMSE, MIN_COVER]
    if len(bad) > MAX_BAD:
        return {"G46": {"status": "NA", "value": None, "threshold": thr, "rows": [], "note": f"{len(bad)} 行没有微动（多于 {MAX_BAD}）：{kinds}"}}
    err = {lab: math.log10(pos(r["f1_p95_um"])) - PRED[lab][1] for lab, r in got.items()}
    sig = {k: v[2] for k, v in PRED.items()}
    rmse, cover = stats(err, sig, len(PRED))
    note = f"{len(got)} 行有微动；FE 减预测 平均 {np.mean(list(err.values())):+.3f} dex，最大 {max(err.values()):+.3f}，最小 {min(err.values()):+.3f}；没有微动的行 {kinds or '无'}"
    try:
        if bad:
            worst = max(abs(e) for e in err.values())
            note += f"；缺行取最坏误差 {worst:.3f} 时 RMSE 上界 {math.sqrt((sum(e * e for e in err.values()) + len(bad) * worst ** 2) / len(PRED)):.4f}（描述）"
        n_low = sum(PRED[k][1] <= LOW for k in PRED)
        note += f"；预测 ≤ {LOW}（{10 ** LOW:.0f} µm）的 {n_low} 行，RMSE 和覆盖 {stats({k: e for k, e in err.items() if PRED[k][1] <= LOW}, sig, n_low)}（描述）"
        err2 = {lab: math.log10(pos(r["f1_p95_um"])) - PRED2[lab][0] for lab, r in got.items()}
        note += f"；R2 的重训版 平均 {np.mean(list(err2.values())):+.3f}，RMSE 和覆盖 {stats(err2, {k: v[1] for k, v in PRED2.items()}, len(PRED2))}（描述）"
        by_e = {e: stats({k: v for k, v in err.items() if PRED[k][0] == e}, sig, sum(PRED[k][0] == e for k in PRED)) for e in (0.0, 1.0, 2.0)}
        note += f"；按入口偏移的 RMSE 和覆盖 {by_e}（描述）；" + describe_A(db_dir, R, got)
    except Exception as ex:                             # noqa: BLE001  描述出错只进 note，不影响判定
        note += f"；描述出错 {type(ex).__name__}: {str(ex)[:200]}"
    return {"G46": {"status": "PASS" if rmse <= MAX_RMSE and cover >= MIN_COVER else "FAIL", "value": [rmse, cover], "threshold": thr,
                    "rows": sorted(r["job_id"] for r in got.values()), "note": note}}
