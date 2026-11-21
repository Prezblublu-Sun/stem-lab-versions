"""b32、b32b（F5 冒烟）的判据 G52，看结果前定（2026-11-08，喂料前；第二模型审查后改，改了什么见 review.md）。

只读版本目录的 scalars.csv 和 fields/iface_*.npz。两行：A 的 m 1.0 版 e +2，楼梯 2391 N，20° / 18°，δ 0.10，μ 0.3，2 循环，只解摩擦，
h_int 2.0，界面附近的骨用 foam_refine {"h": 1.0}（b32）或 {"h": 0.7}（b32b，等 b32 的实测槽时出来再喂），slip_tol = 2.5e-4 × 2.0 / h。
底行是同一设计 h 2.0 带粘接的那行（摩擦部分和只解摩擦相同，n_pairs 3193）。
G52 是冒烟：钩子从 spec 到 prep、求解、导出一路都通，结果没有离谱。不是网格收敛的判据，收敛看 MC-1。
"钩子真的生效"看界面接触对数：导出的 foam_refine 只是 spec 原样，钩子在 Linux 上静默不生效时它照样在；本机 e 0 的冒烟里 h 1.0、h 0.7
的接触对数是生产网格的 3.2 倍和 6.2 倍，门槛取 2.0 倍和 4.0 倍。
对照（描述，不判）：同一设计 h 2.0、h 1.94 复算、整体 h 1.4 三行，微动 26.30、26.63、27.02 µm（v0.12）。
F 的定义同 b28 的 gates.py。
"""
from __future__ import annotations

import csv
import glob
import json
import math
import pathlib

import numpy as np

GATES = {
    "G52": "F5 两行（h 1.0、h 0.7）都算完；导出里记着 foam_refine 的 h 和放大后的 slip_tol；界面接触对数比底行多，h 1.0 至少 2.0 倍、h 0.7 至少 4.0 倍；"
           "微动、转动、F 都是有限数；log10 微动和同一设计 h 2.0 的底行差不超过 0.30 dex（2 倍）。"
           "过：钩子一路通，可以排 MC-1。不过：钩子、求解或导出有问题，或者界面加密让微动变了一倍以上；停下来查，不排 MC-1。有一行算失败（不是超时）就判不过，不等另一行。"
           "不适用：有行没提交、没算完、tag 重复，或求解超时（worker 上限 6 h，是成本问题，不算钩子错）",
}
T = "p13_a105_91e458e3_ow_m1_e+2"
H_LEVELS = (1.0, 0.7)
BASE = "db_ws_p13_a105_91e458e3_ow_m1_e+2_c9ca96c8"                        # h 2.0（stage_db.F5_SMOKE_BASE）
OTHERS = {"h1.94": "db_nz_p13_a105_91e458e3_ow_m1_e+2_h1.94_259889a9", "h1.4": "db_fd_p13_a105_91e458e3_ow_m1_e+2_h1.4_d637579f"}
MAX_DLOG = 0.30
MIN_PAIR_RATIO = {1.0: 2.0, 0.7: 4.0}
SLIP_REF, H_PROD = 2.5e-4, 2.0
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


def tag_of(h: float) -> str:
    return f"{T}_f5h{h:g}"


def slip_of(h: float) -> float:
    return round(SLIP_REF * H_PROD / float(h), 9)


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


def is_timeout(r: dict) -> bool:
    """求解超时：run_abaqus 写 'm_fric: timeout > 21600 s'，level L4，stage solve。odb 导出超时（L5）不算。"""
    w = (r.get("fail_reason") or "").lower()
    return r.get("fail_stage") == "solve" and ("timeout" in w or "timed out" in w)


def judge(db_dir: str) -> dict:
    with open(pathlib.Path(db_dir) / "scalars.csv", encoding="utf-8") as fh:
        R = list(csv.DictReader(fh))
    by_id = {r["job_id"]: r for r in R}
    by_tag = {}
    for r in R:
        by_tag.setdefault(r["tag"], []).append(r)
    thr = {"max_abs_dlog_f1_vs_h2": MAX_DLOG, "min_n_pairs_ratio": MIN_PAIR_RATIO, "slip_tol": {h: slip_of(h) for h in H_LEVELS}}

    def na(why):
        return {"G52": {"status": "NA", "value": None, "threshold": thr, "rows": [], "note": why}}
    b = by_id.get(BASE)
    if b is None or b["status"] != "DONE" or pos(b.get("f1_p95_um")) is None or pos(b.get("n_pairs")) is None:
        return na(f"底行 {BASE} 缺，或缺微动、接触对数")
    rows, unfinished, timeout, failed = {}, {}, {}, {}
    for h in H_LEVELS:
        rs = by_tag.get(tag_of(h), [])
        done = [r for r in rs if r["status"] == "DONE"]
        bad_ = [r for r in rs if r["status"] == "FAILED"]
        if not rs:
            unfinished[h] = "没提交"
        elif len(done) == 1:
            rows[h] = done[0]
        elif len(done) > 1:
            unfinished[h] = "tag 重复"
        elif bad_ and all(is_timeout(r) for r in bad_):
            timeout[h] = (bad_[0].get("fail_reason") or "")[:120]
        elif bad_:
            failed[h] = f"{bad_[0].get('fail_level')} {bad_[0].get('fail_stage')}: {(bad_[0].get('fail_reason') or '')[:160]}"
        else:
            unfinished[h] = "没算完"
    if failed:                                                     # 有一行算失败就不过，不等另一行
        return {"G52": {"status": "FAIL", "value": None, "threshold": thr, "rows": sorted(r["job_id"] for h in failed for r in by_tag[tag_of(h)]),
                        "note": f"算失败 {failed}；其余 没算完 {unfinished or '无'}、超时 {timeout or '无'}"}}
    want = {BASE, *OTHERS.values(), *(r["job_id"] for r in rows.values())}
    Fv = mesh_F(db_dir, want)
    lb, pb = math.log10(pos(b["f1_p95_um"])), pos(b["n_pairs"])
    table, bad = {}, {}
    for h, r in rows.items():
        why = []
        try:
            fr = json.loads(r.get("foam_refine") or "null")
        except (TypeError, ValueError):
            fr = None
        if not isinstance(fr, dict) or f(fr.get("h")) != float(h):
            why.append(f"导出的 foam_refine 是 {r.get('foam_refine')!r}")
        st = f(r.get("slip_tol"))
        if st is None or abs(st - slip_of(h)) > 1e-9:
            why.append(f"slip_tol {r.get('slip_tol')!r}，应为 {slip_of(h):g}")
        np_ = pos(r.get("n_pairs"))
        if np_ is None or np_ / pb < MIN_PAIR_RATIO[h]:
            why.append(f"接触对数 {r.get('n_pairs')!r} 是底行的 {None if np_ is None else round(np_ / pb, 2)} 倍，钩子可能没生效")
        f1, rot, F = pos(r.get("f1_p95_um")), f(r.get("rot_first_deg")), Fv.get(r["job_id"])
        if f1 is None or rot is None or F is None or not math.isfinite(F):
            why.append(f"微动 {r.get('f1_p95_um')!r}、转动 {r.get('rot_first_deg')!r}、F {F!r} 不全是有限数")
        else:
            dl = math.log10(f1) - lb
            table[h] = {"f1_um": round(f1, 3), "dlog_f1_vs_h2": round(dl, 4), "rot_deg": round(rot, 5), "F_mm": round(F, 2),
                        "dF_vs_h2_mm": round(F - Fv[BASE], 2) if BASE in Fv else None, "n_pairs_ratio": None if np_ is None else round(np_ / pb, 2),
                        "solve_wall_h": None if f(r.get("solve_wall_s_fric")) is None else round(f(r.get("solve_wall_s_fric")) / 3600, 2)}
            if abs(dl) > MAX_DLOG:
                why.append(f"微动和 h 2.0 差 {dl:+.3f} dex")
        if why:
            bad[h] = why
    ref = {"h2.0": BASE, **OTHERS}
    desc = {k: {"f1_um": round(pos(by_id[j]["f1_p95_um"]), 3), "dlog_f1_vs_h2": round(math.log10(pos(by_id[j]["f1_p95_um"])) - lb, 4),
                "rot_deg": f(by_id[j].get("rot_first_deg")), "F_mm": round(Fv[j], 2) if j in Fv else None, "n_pairs": by_id[j].get("n_pairs"),
                "solve_wall_h": None if f(by_id[j].get("solve_wall_s_fric")) is None else round(f(by_id[j].get("solve_wall_s_fric")) / 3600, 2)}
            for k, j in ref.items() if j in by_id and pos(by_id[j].get("f1_p95_um")) is not None}
    note = f"F5 行 {table}；对照（描述）{desc}；不过的原因 {bad or '无'}"
    if unfinished or timeout:                                     # 复核 N2：不适用时也报已算完那几行的检查
        return na(f"批还没算完 {unfinished or '无'}；求解超时 {timeout or '无'}；已算完的行（只描述）：" + note)
    return {"G52": {"status": "FAIL" if bad else "PASS", "value": {h: v["dlog_f1_vs_h2"] for h, v in table.items()}, "threshold": thr,
                    "rows": sorted(r["job_id"] for r in rows.values()), "note": note}}
