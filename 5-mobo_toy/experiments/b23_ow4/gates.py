"""b23（OW-4）的判据 G17、G30、G31、G32，照第三版计划第 7 节写，看结果前定（2026-11-03 21:42 UTC 喂料前）。
本文件是重组第 3 步的试点：把已判过的批次用脚本回放，与第 12 节的人工判定比。

行：设计 A（p13_a105_91e458e3）的 m 1.0 版。e 族 = entry_offset_forced_mm ∈ {1, 2, 2.5} 且 job_id 含 "ow_m1"；
    对照 WS_m1 = job_id 含 "_m1_" 且不含 "ow_m1"、不含 "wl_m1"、偏移未强制。
条件键 = (δ, 合力 N, 矢状角°)：名义 (0.1, 2391, 18)、d0.05 (0.05, 2391, 18)、F3839 (0.1, 3839, 8)、两者 (0.05, 3839, 8)、S40 (0.1, 2391, 40)。
"""
from __future__ import annotations

import csv
import math
import pathlib

GATES = {
    "G17": "A e +2 的 h 1.4 / h 2.0 转动比 ≤ 1.10（粗网格不改变结论）",
    "G30": "e +1、+2、+2.5 在 δ 0.05、3839 N、两者、S40 下相对同条件 WS_m1 的 Δ，减去名义工况的 Δ，都 ≤ 0.10 dex",
    "G31": "A e +2 第 10 循环残留转动 ÷ 第 1 循环残留转动，相对 Am1 的同一比值，高出 ≤ 0.05 dex",
    "G32": "G17、G30、G31 都过 → 这一族有资格当候选，低去骨候选用还过线的最大 e",
}
DESIGN = "p13_a105_91e458e3"
NOMINAL = (0.1, 2391.0, 18.0)
CONDS = {"d0.05": (0.05, 2391.0, 18.0), "F3839": (0.1, 3839.0, 8.0), "both": (0.05, 3839.0, 8.0), "S40": (0.1, 2391.0, 40.0)}
E_LEVELS = (1.0, 2.0, 2.5)


def f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def key(r: dict) -> tuple:
    return (round(f(r["delta_mm"]) or 0, 3), round(f(r["load_R_N"]) or 0, 1), round(f(r["alpha_sagit_deg"]) or 0, 1))


def base_row(r: dict) -> bool:
    return (f(r.get("cycles")) == 2 and abs((f(r.get("h_int_mm")) or 0) - 2.0) < 1e-6 and abs((f(r.get("mu")) or 0) - 0.3) < 1e-6)


def judge(db_dir: str) -> dict:
    with open(pathlib.Path(db_dir) / "scalars.csv", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("status") == "DONE" and DESIGN in r["job_id"]]
    m1 = {}      # cond -> rot
    e_rows = {}  # (e, cond) -> (rot, job_id)
    used = []
    for r in rows:
        jid = r["job_id"]
        rot = f(r["rot_first_deg"])
        if rot is None or not base_row(r):
            continue
        eo = f(r.get("entry_offset_forced_mm"))
        if "_m1_" in jid and "ow_m1" not in jid and "wl_m1" not in jid and eo is None:
            m1.setdefault(key(r), (rot, jid))
        elif "ow_m1" in jid and eo in E_LEVELS:
            e_rows.setdefault((eo, key(r)), (rot, jid))
    out = {}

    # G30
    vals, miss = {}, []
    for e in E_LEVELS:
        if (e, NOMINAL) not in e_rows or NOMINAL not in m1:
            miss.append(f"e {e} 名义")
            continue
        d_nom = math.log10(e_rows[(e, NOMINAL)][0] / m1[NOMINAL][0])
        for cname, c in CONDS.items():
            if (e, c) not in e_rows or c not in m1:
                miss.append(f"e {e} {cname}")
                continue
            d_c = math.log10(e_rows[(e, c)][0] / m1[c][0])
            vals[f"e{e:g}×{cname}"] = round(d_c - d_nom, 4)
            used += [e_rows[(e, c)][1], m1[c][1], e_rows[(e, NOMINAL)][1], m1[NOMINAL][1]]
    if miss:
        out["G30"] = {"status": "NA", "value": None, "threshold": 0.10, "rows": [], "note": "缺行：" + ", ".join(miss)}
    else:
        worst = max(vals, key=vals.get)
        out["G30"] = {"status": "PASS" if vals[worst] <= 0.10 else "FAIL", "value": vals[worst], "threshold": 0.10,
                      "rows": sorted(set(used)), "note": f"12 项超额，最大 {worst} {vals[worst]:+.3f} dex；全部：{vals}"}

    # G17
    h14 = [(f(r["rot_first_deg"]), r["job_id"]) for r in rows if "ow_m1_e+2_h1.4" in r["job_id"] and abs((f(r.get("h_int_mm")) or 0) - 1.4) < 1e-6]
    h20 = e_rows.get((2.0, NOMINAL))
    if h14 and h20:
        ratio = h14[0][0] / h20[0]
        out["G17"] = {"status": "PASS" if ratio <= 1.10 else "FAIL", "value": round(ratio, 4), "threshold": 1.10, "rows": [h14[0][1], h20[1]], "note": "h 1.4 / h 2.0 的 rot_first 比"}
    else:
        out["G17"] = {"status": "NA", "value": None, "threshold": 1.10, "rows": [], "note": "缺 h 1.4 行或 e +2 名义行"}

    # G31：逐循环残留转动不在 scalars.csv（rot_perm 只读前两循环），要从原始 CSV 或点云重算
    c10 = [r["job_id"] for r in rows if f(r.get("cycles")) == 10]
    out["G31"] = {"status": "NA", "value": None, "threshold": 0.05, "rows": c10,
                  "note": "需要第 1 与第 9 次卸载的残留转动（scalars.csv 只有前两循环）；来源 = 作业原始 CSV 的逐步点云，用 stability.py 重算。人工判定（第 12 节 11-04 00:51）：e +2 1.069，Am1 1.079，−0.004 dex，通过"}

    # G32
    sub = [out["G17"]["status"], out["G30"]["status"], out["G31"]["status"]]
    if all(s == "PASS" for s in sub):
        st = "PASS"
    elif "FAIL" in sub:
        st = "FAIL"
    else:
        st = "NA"
    out["G32"] = {"status": st, "value": None, "threshold": "G17∧G30∧G31", "rows": [], "note": f"G17 {sub[0]}，G30 {sub[1]}，G31 {sub[2]}；NA 的那条要人工补判"}
    return out
