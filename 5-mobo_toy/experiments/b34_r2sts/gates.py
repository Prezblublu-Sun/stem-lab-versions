"""b34（R2 里比 3b 好、b33 没有挑的四行的坐起行）的判据 G56，看结果前定（2026-11-12，喂料前）。

只读版本目录的 scalars.csv。四行是 b31（R2）的 r2_05、r2_06、r2_08、r2_14，主行楼梯 2391 N、h 2.0、只解摩擦（已在 v0.14）。
r2_14 和 r2_03 是同一个形状，入口偏移不同（+1 对 +1.5），去骨量不同，是另一行。每行配 1 行：坐起 1714 N、24° / 8°，只解摩擦，其余和主行相同。tag = 主行 tag + "_F1714"。转动 = rot_first_deg。
坐起的 A 族曲线和 1.10 的界限同 b28 的 G44、b33 的 G54：A 的 m 1.0 版 e 0 到 +2.5 六行的坐起转动，按去骨量对 log10 转动线性插值。
有效性：坐起行的 iface_force_err_load 超过 1e-3（tools/db_qa.py 第 6 条的界限）时，这一行不按数值用，这个设计不可判。
坐起行按 tag 找；找到的行 load_R_N 不是 1714 N（差 1 N 以上）时不可判（干跑已保证物理，这是多一道保险）。
比较用没取整的比值，容差 1e-9；取 3 位小数只用于显示（b28 的 G44、b33 的 G54 是先取整再比，实际界限是 1.1005）。
4 行没全部终态（DONE 或 FAILED）之前判不适用。
描述（不判）：每个设计楼梯转动比 A 族、坐起比减楼梯比；b33 的 r2_01、r2_03、r2_12 的同两个数。
"""
from __future__ import annotations

import csv
import math
import pathlib

import numpy as np

GATES = {
    "G56": "r2_05、r2_06、r2_08、r2_14 四行，坐起 1714 N 的转动都 ≤ 相同去骨量下 A 族坐起转动的 1.10 倍（界限同 b28 的 G44、b33 的 G54）。"
           "过：只说明这四行坐起转动这一项不比 A 族差太多。它们的'比 3b 好'没有 h 1.94 复核，也没有 h 1.4 行，进后面的比较时要写明。"
           "不过：有设计的坐起转动超过 1.10 倍，报告时写明是哪一个，它不进后面的比较。"
           "不适用：4 行没全部算完；或没有一个超过、而且有行失败、缺数据、有效性量超界、去骨量在坐起曲线外",
}
T = "db_ws_p13_a105_91e458e3_"
STS_CURVE = {"p13_a105_91e458e3_ow_m1_e+2.5_F1714": T + "ow_m1_e+2.5_8a2bd628", "p13_a105_91e458e3_ow_m1_e+2_F1714": T + "ow_m1_e+2_c9ca96c8",
             "p13_a105_91e458e3_ow_m1_e+1.5_F1714": T + "ow_m1_e+1.5_52dc478a", "p13_a105_91e458e3_ow_m1_e+1_F1714": T + "ow_m1_e+1_fea69910",
             "p13_a105_91e458e3_ow_m1_e+0.5_F1714": T + "ow_m1_e+0.5_c17f7b2a", "p13_a105_91e458e3_m1_F1714": T + "m1_2a79b613"}
MAX_STS, MAX_FORCE_ERR, STS_LOAD_N = 1.10, 1e-3, 1714.0
# 设计 → 主行的作业号；坐起行的 tag = 主行的 tag + "_F1714"
MAIN = {"r2_05": "db_al_r2_05_e+1.5_07e94cd0", "r2_06": "db_al_r2_06_e+1_71c6ee2d", "r2_08": "db_al_r2_08_e+1.5_4a1a76ac", "r2_14": "db_al_r2_14_e+1_c143792e"}
DESCRIBE = {"r2_01": "db_al_r2_01_e+1.5_93255a63", "r2_03": "db_al_r2_03_e+1.5_557886c3", "r2_12": "db_al_r2_12_e+1.5_48b9f584"}     # b33 的三个，只描述


def f(x) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def pos(x) -> float | None:
    v = f(x)
    return v if v is not None and v > 0 else None


def tag_of(job: str) -> str:
    return job.split("_", 2)[2].rsplit("_", 1)[0]


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

    def na(why):
        return {"G56": {"status": "NA", "value": None, "threshold": MAX_STS, "rows": [], "note": why}}
    sts = {lab: one(by_tag, tag_of(j) + "_F1714") for lab, j in MAIN.items()}
    pending = {lab: (why or r["status"]) for lab, (r, why) in sts.items() if r is None and why == "没提交" or r is not None and r["status"] not in ("DONE", "FAILED")}
    if pending:
        return na(f"批还没算完：{pending}")
    curve = []
    for t, base in STS_CURVE.items():
        r, _ = one(by_tag, t)
        b0 = by_id.get(base)
        if r is None or r["status"] != "DONE" or pos(r.get("rot_first_deg")) is None or b0 is None or b0["status"] != "DONE" or pos(b0["bone_total_mm3"]) is None or pos(b0["rot_first_deg"]) is None:
            return na(f"坐起的 A 族曲线缺行或缺数据：{t}")
        curve.append((pos(b0["bone_total_mm3"]) / 1000, math.log10(pos(r["rot_first_deg"])), math.log10(pos(b0["rot_first_deg"]))))
    sb, s_sts, s_stair = (np.array(v) for v in zip(*sorted(curve)))

    def ratios(job: str, rw):
        """(坐起比 A 族, 楼梯比 A 族) 或 (None, 原因)。"""
        r, why = rw
        m = by_id.get(job)
        if m is None or m["status"] != "DONE" or pos(m["bone_total_mm3"]) is None or pos(m["rot_first_deg"]) is None:
            return None, "主行缺或缺数据"
        if r is None:
            return None, why
        if r["status"] != "DONE":
            return None, "算失败"
        if pos(r.get("rot_first_deg")) is None:
            return None, "缺转动"
        ld = f(r.get("load_R_N"))
        if ld is None or abs(ld - STS_LOAD_N) > 1.0:
            return None, f"坐起行的载荷是 {ld}，不是 {STS_LOAD_N:g} N"
        e = f(r.get("iface_force_err_load"))
        if e is None or e > MAX_FORCE_ERR:
            return None, f"界面合力误差 {e} 超过 {MAX_FORCE_ERR} 或缺"
        b = pos(m["bone_total_mm3"]) / 1000
        if not (sb[0] <= b <= sb[-1]):
            return None, f"去骨 {b:.2f} 在坐起曲线外"
        return (10 ** (math.log10(pos(r["rot_first_deg"])) - float(np.interp(b, sb, s_sts))),
                10 ** (math.log10(pos(m["rot_first_deg"])) - float(np.interp(b, sb, s_stair)))), None

    def show(v):
        return {"sts": round(v[0], 3), "stair": round(v[1], 3), "sts_minus_stair": round(v[0] - v[1], 3)}
    got, bad = {}, {}
    for lab, j in MAIN.items():
        v, why = ratios(j, sts[lab])
        if v is None:
            bad[lab] = why
        else:
            got[lab] = v
    desc = {}
    for lab, j in DESCRIBE.items():
        v, why = ratios(j, one(by_tag, tag_of(j) + "_F1714"))
        desc[lab] = why if v is None else show(v)
    table = {lab: show(v) for lab, v in got.items()}
    worst = round(max((v[0] for v in got.values()), default=float("nan")), 4) if got else None
    note = f"坐起转动比 A 族 / 楼梯转动比 A 族 / 差：{table}；不可判 {bad}；b33 的三个（描述）{desc}"
    rows = sorted(sts[lab][0]["job_id"] for lab in got)
    over = sorted(lab for lab, v in got.items() if v[0] > MAX_STS + 1e-9)
    if over:
        return {"G56": {"status": "FAIL", "value": worst, "threshold": MAX_STS, "rows": rows, "note": f"超过 1.10 倍的设计 {over}；" + note}}
    if bad:
        return {"G56": {"status": "NA", "value": worst, "threshold": MAX_STS, "rows": rows, "note": "没有超过的，但有设计不可判；" + note}}
    return {"G56": {"status": "PASS", "value": worst, "threshold": MAX_STS, "rows": rows, "note": note}}
