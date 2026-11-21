"""b26（STS-1）和 b27（STS-1 mesh）的判据 G38、G39、G40，看结果前定（2026-11-04，喂料前）。

只读版本目录的 scalars.csv。楼梯 = 基线行，2391 N，20° / 18°。坐起 = 同一设计只把头力换成 1714 N，24° / 8°。其余 δ 0.10、h 2.0、μ 0.3、2 循环、泡沫 155 MPa。
1714 N 不是原文值，是 1600 × 2391 / 2232。不涉及扭矩。转动 = rot_first_deg，微动 = f1_p95_um。
"""
from __future__ import annotations

import csv
import math
import pathlib

import numpy as np

GATES = {
    "G38": "15 个设计在楼梯 2391 N 和坐起 1714 N 下的转动 Spearman ≥ 0.90。过：楼梯的排序可以代表坐起。不过：候选要按 1714 N 重新排序",
    "G39": "A 的 m 1.0 版 e +1、+1.5、+2、+2.5 相对 e 0 的转动升高（dex），坐起减楼梯，都 ≤ +0.10。过：坐起下 e 族的代价不比楼梯高。不过：低去骨候选要按 1714 N 重新定 e",
    "G40": "A 的 m 1.0 版和 e +2 在 h 1.94、2.06 相对 h 2.0 的坐起转动差，最大 ≤ 0.03 dex。过：相差超过这个值的候选可以比。不过：邻近候选不比较，用 G40 的值当噪声",
}
T = "db_ws_p13_a105_91e458e3_"
BASE = {"A_m1_L44": T + "wl_m1_L44_08f4c01a", "A_m1": T + "m1_2a79b613", "A_m1_e+0.5": T + "ow_m1_e+0.5_c17f7b2a", "a96_m1": "db_ws_p13_a96_429a3bcc_ow_m1_e+0_4107fde2",
        "A_m1_e+1": T + "ow_m1_e+1_fea69910", "A_m1_e+1.5": T + "ow_m1_e+1.5_52dc478a", "A_m1_e+2": T + "ow_m1_e+2_c9ca96c8", "A_m1.5": T + "m1.5_96e9b62a",
        "a95_m1_e+2.5": "db_ws_p13_a95_173c181a_ow_m1_e+2.5_67a9f0f2", "A_m1_e+2.5": T + "ow_m1_e+2.5_8a2bd628", "A_m1.75": T + "m1.75_3bd4ac69",
        "al3m_01": "db_al_al3m_01_a6949792", "al3m_06": "db_al_al3m_06_7d0063e3", "al3m_04": "db_al_al3m_04_b4c86b5f", "opt1_08": "db_al_opt1_08_e+0_68d23c0c"}
E_FAMILY = ("A_m1_e+1", "A_m1_e+1.5", "A_m1_e+2", "A_m1_e+2.5")
MESH = ("A_m1", "A_m1_e+2")
MESH_H = (1.94, 2.06)
MIN_RHO, MAX_EXCESS, MAX_MESH = 0.90, 0.10, 0.03


def f(x) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def tag_of(job: str) -> str:
    return job.split("_", 2)[2].rsplit("_", 1)[0]


def ranks(a) -> np.ndarray:
    return np.argsort(np.argsort(np.asarray(a, float))).astype(float)


def judge(db_dir: str) -> dict:
    with open(pathlib.Path(db_dir) / "scalars.csv", encoding="utf-8") as fh:
        R = [r for r in csv.DictReader(fh) if r.get("status") == "DONE"]
    by_id = {r["job_id"]: r for r in R}
    by_tag = {r["tag"]: r for r in R if f(r["load_R_N"]) == 1714.0 and f(r["rot_first_deg"]) is not None}
    stair, sts, f1s, f1t, miss = {}, {}, {}, {}, []
    for lab, j in BASE.items():
        r0, r1 = by_id.get(j), by_tag.get(tag_of(j) + "_F1714")
        if r0 is None or r1 is None or f(r1["h_int_mm"]) != 2.0:
            miss.append(lab)
            continue
        stair[lab], sts[lab], f1s[lab], f1t[lab] = f(r0["rot_first_deg"]), f(r1["rot_first_deg"]), f(r0["f1_p95_um"]), f(r1["f1_p95_um"])
    out = {}
    if miss:
        out["G38"] = {"status": "NA", "value": None, "threshold": MIN_RHO, "rows": [], "note": f"缺行：{miss}"}
    else:
        labs = list(BASE)
        rho = float(np.corrcoef(ranks([stair[k] for k in labs]), ranks([sts[k] for k in labs]))[0, 1])
        rho_f1 = float(np.corrcoef(ranks([f1s[k] for k in labs]), ranks([f1t[k] for k in labs]))[0, 1])
        out["G38"] = {"status": "PASS" if rho >= MIN_RHO else "FAIL", "value": round(rho, 4), "threshold": MIN_RHO, "rows": [by_tag[tag_of(BASE[k]) + "_F1714"]["job_id"] for k in labs],
                      "note": f"微动的同一 Spearman {rho_f1:.3f}（不判）；逐行 楼梯° / 坐起° / 楼梯 µm / 坐起 µm：" + str({k: (round(stair[k], 4), round(sts[k], 4), round(f1s[k], 2), round(f1t[k], 2)) for k in labs})}
    if "A_m1" in sts and all(k in sts for k in E_FAMILY):
        ex = {k: round(math.log10(sts[k] / sts["A_m1"]) - math.log10(stair[k] / stair["A_m1"]), 4) for k in E_FAMILY}
        w = max(ex, key=ex.get)
        out["G39"] = {"status": "PASS" if ex[w] <= MAX_EXCESS else "FAIL", "value": ex[w], "threshold": MAX_EXCESS, "rows": [], "note": f"超额 dex：{ex}"}
    else:
        out["G39"] = {"status": "NA", "value": None, "threshold": MAX_EXCESS, "rows": [], "note": "缺 A 的 e 行"}
    vals, used = {}, []
    for lab in MESH:
        ref = by_tag.get(tag_of(BASE[lab]) + "_F1714")
        for h in MESH_H:
            r = by_tag.get(f"{tag_of(BASE[lab])}_h{h:g}_F1714")
            if ref is None or r is None:
                continue
            vals[f"{lab} h{h:g}"] = round(abs(math.log10(f(r["rot_first_deg"]) / f(ref["rot_first_deg"]))), 4)
            used.append(r["job_id"])
    if len(vals) < len(MESH) * len(MESH_H):
        out["G40"] = {"status": "NA", "value": None, "threshold": MAX_MESH, "rows": used, "note": f"网格行只有 {len(vals)} / {len(MESH) * len(MESH_H)} 行；要先算 h 1.94、2.06 × 1714 N 的完整股骨参照（b27）"}
    else:
        w = max(vals, key=vals.get)
        out["G40"] = {"status": "PASS" if vals[w] <= MAX_MESH else "FAIL", "value": vals[w], "threshold": MAX_MESH, "rows": used, "note": f"|Δ log10 转动|：{vals}"}
    return out
