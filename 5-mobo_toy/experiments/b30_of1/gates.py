"""b30（OF-1）的判据 G48、G51，看结果前定（2026-11-08，喂料前；第二模型审查后改，改了什么见 review.md）。
行在 experiments/prep_2026-11-08/data/of1_rows.json 和 of1_back.json。

只读版本目录的 scalars.csv 和 fields/iface_*.npz。条件：δ 0.10，楼梯 2391 N，20° / 18°，h 2.0，μ 0.3，2 循环，只解摩擦。
10 行是 A 的 m 1.0 版只改一个形状量，入口偏移 0；2 行是 b28 的 3b 只把一个量放回 A 的 m 1.0 版的值，入口偏移 +1.5（同 3b）。
比较基准同 b28：A 族曲线（7 行，按去骨量对新轴网格 F、log10 微动线性插值）。3b 的方向是 n_a 减小 0.174、τ_a 增大 0.105（单位坐标）。
3b 的位置当场从库里重算（主行 h 2.0 和 h 1.94 复算），和 b28 记下的数差过 0.05 mm 或 0.002 dex 就判不适用。
噪声：微动重划网格的标准差 0.011 到 0.014 dex（b28 提议第 6 节，h 1.94、2.06 各 10 对），两次运行之差约 0.017 dex，再加曲线插值误差。
G48 门槛 0.04 dex，没有作用时三行里任一行碰巧过的概率约 2.5 %；G51 门槛 0.035 dex（3b 两次平均的微动优势 0.070 的一半），两行合起来约 2 %。
F 的定义同 b28 的 gates.py。
"""
from __future__ import annotations

import csv
import glob
import math
import pathlib

import numpy as np

GATES = {
    "G48": "n_a −0.15、τ_a +0.15、τ_a +0.30 三行里至少一行，在相同去骨量下微动比 A 族低 ≥ 0.04 dex，且 F 不比 A 族低 2 mm 以上。有一行过就判过；没有一行过、而且有关键行不可判：不适用。"
           "过：在 e 0、A 的 m 1.0 版上，单改这个量就能降微动，3b 的改进可能有一部分来自它。"
           "不过：在 e 0 处 n_a 或 τ_a 单走一档都降不了 0.04 dex；这不等于 3b 的改进要几个量一起改，3b 在 e +1.5、去骨约 5.4 cm³，和 e、去骨的交互没测，G51 直接测",
    "G51": "3b 还原 n_a、3b 还原 τ_a 两行里至少一行，相同去骨量下的 Δlog 微动比 3b 高 ≥ 0.035 dex，即丢掉 3b 一半以上的微动优势（3b 取主行和 h 1.94 复算的平均）。"
           "有一行过就判过；没有一行过、而且有一行不可判：不适用。"
           "过：其他量都在 3b 的值时，3b 的微动优势有一半以上靠这个量；不过：单独还原 n_a 或 τ_a，3b 的微动优势都留下一半以上，优势不靠其中任何一个单独撑着",
}
T = "db_ws_p13_a105_91e458e3_"
CURVE = (T + "ow_m1_e+2.5_8a2bd628", T + "ow_m1_e+2_c9ca96c8", T + "ow_m1_e+1.5_52dc478a", T + "ow_m1_e+1_fea69910", T + "ow_m1_e+0.5_c17f7b2a", T + "m1_2a79b613", T + "ow_m1_e-0.5_03b0a7bc")
# 标签 → 入口偏移；行的 tag = of1_<标签>_e<偏移，:+g>
E = {"rho_tip-0.15": 0.0, "rho_tip+0.15": 0.0, "q-0.15": 0.0, "q-0.30": 0.0, "n_a-0.15": 0.0, "n_a+0.15": 0.0, "g_ap-0.15": 0.0, "g_ap+0.15": 0.0, "tau_a+0.15": 0.0, "tau_a+0.30": 0.0,
     "3b_back_n_a": 1.5, "3b_back_tau_a": 1.5}
LABELS = tuple(E)
KEY_ROWS = ("n_a-0.15", "tau_a+0.15", "tau_a+0.30")
BACK_ROWS = ("3b_back_n_a", "3b_back_tau_a")
# 3b：job → b28 记下的 (ΔF mm, Δlog 微动 dex)，db3406 v0.12
REF_3B = {"db_al_fam1_3b_e+1.5_58336253": (9.68, -0.0738), "db_nz_fam1_3b_e+1.5_h1.94_88da6ea6": (10.16, -0.0661)}
TOL_F, TOL_L = 0.05, 0.002
N3 = np.array([0.381, 0.025, -0.924])
U_NECK = np.array([0.92228, 0.06137, 0.38162]) / np.linalg.norm([0.92228, 0.06137, 0.38162])
CREF = np.array([37.65271204198696, 0.8509371708090849, 41.89415555538172])
MIN_DROP, MAX_F_LOSS, MIN_BACK = 0.04, 2.0, 0.035


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
    return f"of1_{lab}_e{E[lab]:+g}"


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
    thr = {"G48": {"dlog_f1": -MIN_DROP, "dF_mm": -MAX_F_LOSS}, "G51": {"dlog_over_3b": MIN_BACK}}

    def na_all(why):
        return {g: {"status": "NA", "value": None, "threshold": thr[g], "rows": [], "note": why} for g in GATES}
    miss = [j for j in (*CURVE, *REF_3B) if j not in by_id or by_id[j]["status"] != "DONE" or pos(by_id[j]["bone_total_mm3"]) is None or pos(by_id[j]["f1_p95_um"]) is None]
    if miss:
        return na_all(f"A 族曲线或 3b 缺行或缺数据 {miss}")
    rows, why0 = {}, {}
    for lab in LABELS:
        rows[lab], why0[lab] = one(by_tag, tag_of(lab))
    want = set(CURVE) | set(REF_3B) | {r["job_id"] for r in rows.values() if r is not None and r["status"] == "DONE"}
    Fv = mesh_F(db_dir, want)
    if (set(CURVE) | set(REF_3B)) - set(Fv):
        return na_all(f"fields 里缺 A 族曲线或 3b 的界面节点 {sorted((set(CURVE) | set(REF_3B)) - set(Fv))}")
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
    ref = {}
    for j, (dF0, dl0) in REF_3B.items():
        g, why = gap(by_id[j], None)
        if g is None or abs(g[1] - dF0) > TOL_F or abs(g[2] - dl0) > TOL_L:
            return na_all(f"3b 复核不上：{j} 记下 ({dF0}, {dl0})，现在 {why or (round(g[1], 3), round(g[2], 4))}")
        ref[j] = g
    dl3b = float(np.mean([g[2] for g in ref.values()]))
    table, bad = {}, {}
    for lab, r in rows.items():
        g, why = gap(r, why0[lab])
        if g is None:
            bad[lab] = why
            continue
        table[lab] = {"bone": round(g[0], 3), "dF_mm": round(g[1], 2), "dlog_f1": round(g[2], 4), "rot_deg": f(r.get("rot_first_deg"))}
    desc = f"逐行（相对同去骨量的 A 族）{table}；不可判 {bad or '无'}"
    out = {}
    # G48
    hit = [k for k in KEY_ROWS if k in table and table[k]["dlog_f1"] <= -MIN_DROP and table[k]["dF_mm"] >= -MAX_F_LOSS]
    best = min((table[k]["dlog_f1"] for k in KEY_ROWS if k in table), default=None)
    if hit:
        out["G48"] = {"status": "PASS", "value": best, "threshold": thr["G48"], "rows": sorted(rows[k]["job_id"] for k in hit), "note": f"过的关键行 {hit}；" + desc}
    elif any(k in bad for k in KEY_ROWS):
        out["G48"] = {"status": "NA", "value": best, "threshold": thr["G48"], "rows": [], "note": f"没有关键行过，关键行不可判 { {k: bad[k] for k in KEY_ROWS if k in bad} }；" + desc}
    else:
        out["G48"] = {"status": "FAIL", "value": best, "threshold": thr["G48"], "rows": sorted(rows[k]["job_id"] for k in KEY_ROWS), "note": f"关键三行最低的微动差 {best:+.4f} dex；" + desc}
    # G51
    up = {k: round(table[k]["dlog_f1"] - dl3b, 4) for k in BACK_ROWS if k in table}
    hit = [k for k, v in up.items() if v >= MIN_BACK]
    n51 = f"3b 的 Δlog 微动两次平均 {dl3b:+.4f} dex（{ {j: round(g[2], 4) for j, g in ref.items()} }）；还原行比 3b 高 {up}"
    if hit:
        out["G51"] = {"status": "PASS", "value": max(up.values()), "threshold": thr["G51"], "rows": sorted(rows[k]["job_id"] for k in hit), "note": f"过的 {hit}；" + n51}
    elif any(k in bad for k in BACK_ROWS):
        out["G51"] = {"status": "NA", "value": max(up.values(), default=None), "threshold": thr["G51"], "rows": [], "note": f"没有一行过，不可判 { {k: bad[k] for k in BACK_ROWS if k in bad} }；" + n51}
    else:
        out["G51"] = {"status": "FAIL", "value": max(up.values()), "threshold": thr["G51"], "rows": sorted(rows[k]["job_id"] for k in BACK_ROWS), "note": n51}
    return out
