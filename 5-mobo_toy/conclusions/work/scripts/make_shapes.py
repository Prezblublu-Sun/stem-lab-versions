"""Stem shapes by case: pick the best design in each case from a db3406 export, take its stem surface from the local job archive, and write a page with a draggable 3D view.

    python -X utf8 make_shapes.py [--db <export dir>]

Reads db3406/<export>/scalars.csv, db3406/raw/<job>.tar.xz (mesh3d.npz, spec.json, prep.json) and the femur surfaces in p13_3406/visual_report_2026-10-25/data/geometry.json.
Writes 股骨柄形状_2026-11-04.html (full page, double-click to open), data/shapes_cases.csv, and the same page without the html skeleton to --artifact-out for publishing.
"""
import argparse
import base64
import csv
import io
import json
import math
import pathlib
import sys
import tarfile
from statistics import median

import numpy as np
import shapely
from shapely.geometry import Polygon

HERE = pathlib.Path(__file__).resolve().parent.parent
VARS = ("L", "alpha", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")
SIG_VARS = tuple(v for v in VARS if v != "h_cut")
RAW =pathlib.Path(r"H:/projects/Femoral implant generation/db3406/raw")
GEO = HERE.parent / "p13_3406/visual_report_2026-10-25/data/geometry.json"
FY = HERE.parent / "db3406_checks/FEA_settings_2026-10-28/fy_analysis.json"
TET_FACES = np.array([[0, 1, 2], [0, 1, 3], [1, 2, 3], [0, 2, 3]])
STEP = 0.05  # mm per integer step of the stored coordinates, as in geometry.json
N3 = np.array([0.381, 0.025, -0.924])  # direction of a positive entry offset in the cut plane, third-version plan section 12

W = "db_ws_p13_a105_91e458e3_"
JOB = {"A": "sb13_a105_91e458e3", "A_L44.5": W + "L44.5_67ffc6b1", "a96": "sb13_a96_429a3bcc", "a79": "sb13_a79_14e2b689", "B": "sb13_a78_b0f465da", "a61": "sb13_a61_7afcca3a",
       "al1_07": "db_al_al1_07_b4ea44f0", "al2_28": "db_al_al2_28_0a3a43cf", "pick4": "db_al_al3m_04_b4c86b5f", "m1_L44": W + "wl_m1_L44_08f4c01a", "a96_m1": "db_ws_p13_a96_429a3bcc_ow_m1_e+0_4107fde2",
       "m1": W + "m1_2a79b613", "m1.5": W + "m1.5_96e9b62a", "m1.75": W + "m1.75_3bd4ac69", "pick1": "db_al_al3m_01_a6949792", "pick6": "db_al_al3m_06_7d0063e3",
       "e+0.5": W + "ow_m1_e+0.5_c17f7b2a", "e+1": W + "ow_m1_e+1_fea69910", "e+1.5": W + "ow_m1_e+1.5_52dc478a", "e+2": W + "ow_m1_e+2_c9ca96c8", "e+2.5": W + "ow_m1_e+2.5_8a2bd628", "a95_e+2.5": "db_ws_p13_a95_173c181a_ow_m1_e+2.5_67a9f0f2",
       "a50": W + "a50_4f9e71ac", "m1_a50": W + "m1_a50_baa53da3", "m1_a50_L44": W + "wl_m1_a50_L44_595802f4", "m1_a55_L44.75": W + "wl_m1_a55_L44.75_2d91a2fa",
       "Bp": "sb13_a53_23a3f031", "C": "sb14_a29_6ad70033", "D": "sb14_a26_96c5ab9b", "init29": "sb13_init_2943f28a", "e2a": "v3406_e2a_h16_b962fc76"}
NAME = {"A": "A", "A_L44.5": "A，L 44.5", "a96": "a96", "a79": "a79", "B": "B", "a61": "a61", "al1_07": "al1_07", "al2_28": "al2_28", "pick4": "选点 4", "m1_L44": "A，m 1.0，L 44", "a96_m1": "a96，m 1.0",
        "m1": "A，m 1.0", "m1.5": "A，m 1.5", "m1.75": "A，m 1.75", "pick1": "选点 1", "pick6": "选点 6", "e+0.5": "A，m 1.0，e +0.5", "e+1": "A，m 1.0，e +1", "e+1.5": "A，m 1.0，e +1.5", "e+2": "A，m 1.0，e +2", "e+2.5": "A，m 1.0，e +2.5",
        "a95_e+2.5": "a95，m 1.0，e +2.5", "a50": "A，α 50", "m1_a50": "A，m 1.0，α 50", "m1_a50_L44": "A，m 1.0，α 50，L 44", "m1_a55_L44.75": "A，m 1.0，α 55，L 44.75", "Bp": "B′", "C": "C", "D": "D", "init29": "init29", "e2a": "e2a 默认"}
NOTE = {"A": "搜索到的最好设计，m 贴下限 0.5。放置偏 de +1 或插入角 −3° 时进皮质（Z2）。楼梯载荷单元峰值 0.663 % 超限，区域 P99 不超（Z1）。",
        "A_L44.5": "同形里转动最低。偏移固定 0，柄尖贴空腔，依赖空芯假设。",
        "al1_07": "模板选到 e +2，m 贴下限。",
        "al2_28": "模板选到 e +4，柄长只有 34 mm。",
        "pick4": "AL-3′ 选点，转动已高于判据线 0.19°。",
        "m1_L44": "m 1.0 的台架候选。依赖空芯假设。L 44 在 e +0.5 到 +2.5 全部低于号下限，不能和正偏移叠加。",
        "a96_m1": "a96 的形状改 m 1.0，偏移固定 0。",
        "m1": "同形对照：只把 A 的余量改成 1.0。e 再往负走有悬崖，在 e −0.5 和 −1 之间。",
        "m1.5": "只改余量。",
        "m1.75": "贴在偏移跳变边上：m 2.0 就跳到 e −2，转动放大到 0.383°。",
        "pick1": "AL-3′ 选点，模板选到 e +2，肩面积只有 240 mm²。",
        "pick6": "AL-3′ 选点，模板选到 e −2。",
        "e+0.5": "尺寸在 e +0.5 重新模板化，这不是放置误差。",
        "e+1": "去骨和 m 1.75 差不多，转动只有它的一半。相对 e 0 放大 1.15 倍，残留转动几乎不变。",
        "e+1.5": "尺寸在 e +1.5 重新模板化。扭矩容量比 e 0 少，独立扭矩要等 TQ-1。",
        "e+2": "几何上名义 e 的上限：号固定时 8 个位姿颈底伸出都不超过 2 mm²（Z2）。已算过 h 1.4、10 循环和差条件（G17、G30、G31）。",
        "e+2.5": "G32 规则下的低去骨候选。贴模板边缘，颈底伸出 1.7 mm²，e +3 超限；号固定时 de +1 伸出 9.0 mm²（Z2）。",
        "a95_e+2.5": "和 A 的 e +2.5 差 −0.003 dex，在噪声内，属于同一族。",
        "a50": "α 超出 45° 上限，放宽要用户批准。",
        "m1_a50": "α 超出上限，要过 G2，等 TQ-1。",
        "m1_a50_L44": "L 和 α 可以叠加（G21）。两者都贴空腔，依赖空芯假设。α 要过 G2。",
        "m1_a55_L44.75": "m ≥ 1.0 全部已算设计里转动最低。超出盒子，贴空腔。",
        "B": "两目标搜索里去骨 ≤ 8 cm³ 转动最小的设计。",
        "Bp": "和 B 接近，两目标搜索的备选。附近有入口偏移跳变。",
        "C": "10-25 时三目标搜索里去骨 ≤ 6 cm³ 转动最小的设计，后来被 al1_07 超过。",
        "D": "三目标搜索里离开边界和悬崖的设计，邻域平滑。",
        "init29": "初始 32 个设计里转动最低，用来看优化改善了多少。",
        "e2a": "优化前的默认设计，δ 0.025，转动不能和其他行直接比。"}


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def from_export(r):
    """Same columns and units as pack_data.from_export."""
    o = {"job_id": r["job_id"], "layer": r["layer"], "status": r["status"], "bone": (num(r["bone_total_mm3"]) or float("nan")) / 1000, "e": num(r["tpl_e"]), "A0": num(r["tpl_A0"]), "rot": num(r["rot_first_deg"]),
         "rot_perm": num(r["rot_perm_deg"]), "rot_rev": num(r["rot_rev_deg"]), "contact": num(r["contact_area_load2_mm2"]), "f1": num(r["f1_p95_um"]), "press": num(r["cpress_release_p95"]), "vm": num(r["vm_p99_MPa"]),
         "delta": num(r["delta_mm"]), "load_R": num(r["load_R_N"]), "af": num(r["alpha_front_deg"]), "as": num(r["alpha_sagit_deg"]), "h_int": num(r["h_int_mm"]), "E_canc": num(r["E_canc_MPa"]), "mu": num(r["mu"]),
         "cycles": num(r["cycles"]), "forced_e": num(r["entry_offset_forced_mm"]), "in_box": r["in_bounds_v1"] == "true"}
    o.update({v: num(r[v]) for v in VARS})
    return o


def sig(r):
    return tuple(None if r[v] is None else round(r[v], 6) for v in SIG_VARS)


def b64(arr):
    return base64.b64encode(arr.tobytes()).decode("ascii")


def read_job(job):
    out = {}
    with tarfile.open(RAW / f"{job}.tar.xz") as tf:
        for x in tf:
            base = x.name.split("/")[-1]
            if x.name.count("/") == 1 and base in ("mesh3d.npz", "spec.json", "prep.json"):
                out[base] = tf.extractfile(x).read()
            if len(out) == 3:
                break
    z = np.load(io.BytesIO(out["mesh3d.npz"]))
    return z, json.loads(out["spec.json"]), json.loads(out["prep.json"])


def boundary(conn4, X):
    F = conn4[:, TET_FACES].reshape(-1, 3)
    opp = conn4[:, [3, 2, 0, 1]].reshape(-1)
    _, inv, cnt = np.unique(np.sort(F, axis=1), axis=0, return_inverse=True, return_counts=True)
    keep = cnt[inv.ravel()] == 1
    F, opp = F[keep], opp[keep]
    n = np.cross(X[F[:, 1]] - X[F[:, 0]], X[F[:, 2]] - X[F[:, 0]])
    flip = ((X[opp] - X[F[:, 0]]) * n).sum(1) > 0
    F = F.copy()
    F[flip] = F[flip][:, [0, 2, 1]]
    return F


def silhouette(X, F, i, j):
    polys = []
    for t in F:
        q = X[t][:, [i, j]]
        if 0.5 * abs((q[1, 0] - q[0, 0]) * (q[2, 1] - q[0, 1]) - (q[2, 0] - q[0, 0]) * (q[1, 1] - q[0, 1])) > 1e-6:
            polys.append(Polygon(q))
    u = shapely.union_all(shapely.make_valid(np.array(polys, dtype=object)), grid_size=1e-3).buffer(1e-2).buffer(-1e-2)
    m = u if u.geom_type == "Polygon" else max(u.geoms, key=lambda g: g.area)
    s = m.simplify(0.12, preserve_topology=True)
    return [[round(float(a), 1), round(float(b), 1)] for a, b in s.exterior.coords]


def stem(job, row, H, U3):
    z, spec, prep = read_job(job)
    labs, X = z["node_labels"], z["nodes"]
    conn = np.searchsorted(labs, z["stem_conn_bond"][:, :4])
    F = boundary(conn, X)
    # same surface checks every time: the mesh is closed, and the archive holds the design this row reports
    E = np.sort(np.r_[F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], axis=1)
    _, ec = np.unique(E, axis=0, return_counts=True)
    assert (ec == 2).all(), (job, "open stem surface")
    d = spec["design"]
    for k in ("L", "alpha", "m"):
        assert abs(d[k] - row[k]) < 1e-6, (job, k, d[k], row[k])
    assert abs(spec["h_cut"] - row["h_cut"]) < 1e-6, (job, "h_cut")
    tpl = prep["templating"]
    assert abs(tpl["A0"] - row["A0"]) < 0.01 and abs(tpl["e"] - row["e"]) < 1e-6, (job, tpl["A0"], tpl["e"], row["A0"], row["e"])
    C = np.array(prep["femur_hook"]["cut_centre_m"])
    assert np.linalg.norm(C - (H - spec["h_cut"] * U3)) < 0.01, (job, "cut centre")
    dj = (X - C) @ U3
    is_body = (dj[F] <= 1e-6).all(1)
    Fb, Fn = F[is_body], F[~is_body]
    u, inv = np.unique(np.r_[Fb, Fn].ravel(), return_inverse=True)
    Fo = inv.reshape(-1, 3)
    Xo = X[u]
    q = np.round(Xo / STEP).astype(np.int16)
    assert np.abs(Xo / STEP).max() < 32000
    a = math.radians(tpl["alpha"])
    sn = np.unique(conn)
    Pb = X[sn[dj[sn] <= 1e-6]]
    ax = np.array([-math.sin(a), 0.0, -math.cos(a)])
    s_max = float(((Pb - (C + tpl["e"] * N3)) @ ax).max())
    assert abs(s_max - (d["L"] + d["cap_h"])) < 0.6, (job, s_max, d["L"], d["cap_h"])  # measured from the shoulder centre; the stem axis has a small y part, so this is close, not exact
    Xb, Fb2 = X, Fb
    return {"v": b64(q), "f": b64(Fo.astype(np.uint16)), "nb": int(len(Fb)), "nf": int(len(Fo)),
            "c": [round(float(x), 1) for x in Pb.mean(0)], "size": round(float(np.ptp(Pb, axis=0).max()), 1),
            "s_max": round(s_max, 2), "cor": silhouette(Xb, Fb2, 0, 2), "sag": silhouette(Xb, Fb2, 1, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=r"H:/projects/Femoral implant generation/db3406/v0.9")
    ap.add_argument("--artifact-out", default="")
    a = ap.parse_args()
    db = pathlib.Path(a.db)
    rows = [from_export(r) for r in csv.DictReader(open(db / "scalars.csv", encoding="utf-8"))]
    by = {r["job_id"]: r for r in rows}
    nominal = lambda r: (r["status"] == "DONE" and r["rot"] is not None and r["bone"] == r["bone"] and r["delta"] == 0.1 and r["load_R"] == 2391.0 and r["af"] == 20.0 and r["as"] == 18.0  # noqa: E731
                         and r["h_int"] == 2.0 and r["E_canc"] == 155.0 and r["mu"] == 0.3 and r["cycles"] == 2)
    tmpl = [r for r in rows if nominal(r) and (r["forced_e"] is None or (r["forced_e"] == 0.0 and r["layer"] in ("W-0 L", "WL-1", "OW-2")))]
    fixed = [r for r in rows if nominal(r) and r["forced_e"] is not None and r["forced_e"] != 0.0 and r["layer"] in ("OW-2", "OW-3")]

    # the case tables come from the data: a job typed in JOB has to be the winner the data gives
    rev = {v: k for k, v in JOB.items()}

    def by_caps(S, caps, top_label):
        out, last = [], None
        for cap in caps:
            s = [r for r in S if r["bone"] <= cap]
            if not s:
                continue
            b = min(s, key=lambda r: r["rot"])
            assert b["job_id"] in rev, ("winner not in JOB", cap, b["job_id"], b["rot"], b["bone"])
            if last and last[0] == b["job_id"]:
                last[1].append(cap)
            else:
                last = [b["job_id"], [cap]]
                out.append(last)
        items = []
        for job, cs in out[::-1]:
            lab = top_label if cs[-1] == caps[-1] else ("去骨 ≤ " + (f"{cs[0]:g}" if len(cs) == 1 else f"{cs[0]:g} 到 {cs[-1]:g}") + " cm³")
            items.append({"key": rev[job], "case": lab})
        return items

    caps = (5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 10)
    inb = [r for r in tmpl if r["in_box"]]
    g_any = by_caps(inb, caps, "不限去骨")
    g_any.insert(1, {"key": "A", "case": "搜索到的最好"})
    g_m1 = by_caps([r for r in inb if r["m"] >= 0.999], caps, "不限去骨")
    g_m1.insert(1, {"key": "m1", "case": "只改余量的对照"})
    for key, e in (("m1", 0.0), ("e+0.5", 0.5), ("e+1", 1.0), ("e+1.5", 1.5), ("e+2", 2.0), ("e+2.5", 2.5)):
        r = by[JOB[key]]
        assert r["e"] == e and r["L"] == by[JOB["m1"]]["L"], key
    best_fixed = min((r for r in fixed if r["bone"] <= 5.0), key=lambda r: r["rot"])
    assert best_fixed["job_id"] == JOB["a95_e+2.5"], best_fixed["job_id"]
    groups = [
        {"id": "any", "title": "不限余量", "def": "基准工况，设计盒内，尺寸和入口偏移由模板决定，只限去骨量。", "items": g_any},
        {"id": "m1", "title": "余量 m ≥ 1.0", "def": "规则同上，只留 m ≥ 1.0。默认放置公差下 A（m 0.5）会进皮质，m 1.0 这一族不进（Z2）。m 的下限还待导师定。", "items": g_m1},
        {"id": "e", "title": "余量 1.0，入口偏移固定", "def": "A 的形状，把入口偏移固定在某一档，尺寸在该档重新模板化。去骨少了很多，增加的转动几乎都是可逆的。", "items": [{"key": "m1", "case": "e 0"}, {"key": "e+0.5", "case": "e +0.5"}, {"key": "e+1", "case": "e +1"}, {"key": "e+1.5", "case": "e +1.5"}, {"key": "e+2", "case": "e +2"}, {"key": "e+2.5", "case": "e +2.5"}, {"key": "a95_e+2.5", "case": "≤ 5 cm³ 转动最低"}]},
        {"id": "box", "title": "放宽边界", "def": "α 超过 45° 上限，都在设计盒外，放宽要用户批准。", "items": [{"key": "a50", "case": "m 0.5，α 50"}, {"key": "m1_a55_L44.75", "case": "m 1.0，α 55，L 44.75"}, {"key": "m1_a50_L44", "case": "m 1.0，α 50，L 44"}, {"key": "m1_a50", "case": "m 1.0，α 50"}]},
        {"id": "obj", "title": "不同优化目标", "def": "两条并行的贝叶斯优化，起点相同，预算相同。两目标是转动和接触面积，三目标再加去骨量。", "items": [{"key": "A", "case": "两目标"}, {"key": "B", "case": "两目标"}, {"key": "Bp", "case": "两目标"}, {"key": "D", "case": "三目标"}, {"key": "C", "case": "三目标"}]},
        {"id": "ref", "title": "未优化的对照", "def": "用来看优化前后形状变了多少。", "items": [{"key": "init29", "case": "初始批最好"}, {"key": "e2a", "case": "默认设计"}]},
    ]
    used = sorted({it["key"] for g in groups for it in g["items"]}, key=lambda k: list(JOB).index(k))
    assert set(used) == set(JOB), set(JOB) ^ set(used)

    G = json.load(open(GEO, encoding="utf-8"))
    H, U3 = np.array(G["head_centre"]), np.array(G["neck_axis"]["u"])
    stems = {}
    for k in used:
        stems[k] = stem(JOB[k], by[JOB[k]], H, U3)
        print(k, stems[k]["nf"], stems[k]["nb"], len(stems[k]["cor"]), len(stems[k]["sag"]), "s_max - (L + cap)", round(stems[k]["s_max"] - by[JOB[k]]["L"] - 1.5, 2), flush=True)
    # femur surfaces as stored for the earlier viewer, in the same frame
    femur = {}
    for k in ("cortex", "canal", "cut_ring", "core_exposed"):
        s = G["femur"][k]
        femur[k] = {"v": b64(np.round(np.array(s["v"]) / STEP).astype(np.int16)), "f": b64(np.array(s["f"], dtype=np.uint16))}

    def rec(k):
        r = by[JOB[k]]
        keys = ("rot", "bone", "f1", "contact", "A0", "e", "rot_perm", "rot_rev", "vm", "press", "delta") + VARS
        return dict({x: (round(r[x], 5) if r[x] is not None else None) for x in keys}, in_box=r["in_box"], job=JOB[k], name=NAME[k], note=NOTE.get(k, ""))

    # conditions: nothing was re-optimised, the designs already computed were rerun
    sig_A = sig(by[JOB["A"]])
    cond = [("过盈 δ 0.025", lambda r: r["delta"] == 0.025 and r["load_R"] == 2391.0 and r["as"] == 18.0), ("过盈 δ 0.05", lambda r: r["delta"] == 0.05 and r["load_R"] == 2391.0 and r["as"] == 18.0), ("过盈 δ 0.20", lambda r: r["delta"] == 0.2 and r["load_R"] == 2391.0),
            ("起身 1714 N", lambda r: r["delta"] == 0.1 and r["load_R"] == 1714.0), ("起身 3839 N", lambda r: r["delta"] == 0.1 and r["load_R"] == 3839.0), ("δ 0.05 且 3839 N", lambda r: r["delta"] == 0.05 and r["load_R"] == 3839.0),
            ("楼梯方向 3606 N", lambda r: r["load_R"] == 3606.0), ("矢状角 40°", lambda r: r["as"] == 40.0), ("摩擦 μ 0.2", lambda r: r["mu"] == 0.2), ("摩擦 μ 0.15", lambda r: r["mu"] == 0.15), ("10 循环", lambda r: r["cycles"] == 10), ("网格 h 1.4", lambda r: r["h_int"] == 1.4)]
    conds = []
    for lab, fn in cond:
        s = sorted([r for r in rows if r["status"] == "DONE" and r["rot"] is not None and r["forced_e"] is None and fn(r)], key=lambda r: r["rot"])
        assert sig(s[0]) == sig_A, (lab, s[0]["job_id"])
        conds.append({"cond": lab, "n": len(s), "rot": round(s[0]["rot"], 4), "gap": round(math.log10(s[1]["rot"] / s[0]["rot"]), 3)})
    conds_fy = json.load(open(HERE / "data/metrics.json", encoding="utf-8"))["sensitivity"]["foam_yield"]

    D = {"groups": groups, "rows": {k: rec(k) for k in used}, "stems": stems, "femur": femur, "head": G["head_centre"], "load": G["load_dir"], "step": STEP, "conds": conds,
         "foam": {"n": conds_fy["n"], "median": round(conds_fy["times_median"], 2)}, "export": db.name, "n_rows": len(rows), "n_done": sum(r["status"] == "DONE" for r in rows),
         "bounds": {"L": [20, 45], "alpha": [15, 45], "h_cut": [16, 32], "m": [0.5, 2], "rho_tip": [0.1, 0.5], "q": [0.5, 3], "lam": [1, 2.2], "g_ml": [0.35, 0.65], "g_ap": [0.35, 0.65], "n_a": [2, 6], "n_p": [2, 6], "tau_a": [-0.3, 0.3], "tau_p": [-0.3, 0.3]}}
    with open(HERE / "data/shapes_cases.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["group", "case", "design", "job_id", "bone_cm3", "rot_deg", "f1_p95_um", "contact_mm2", "A0_mm2", "e_mm", "in_box", "delta_mm"] + list(VARS))
        for g in groups:
            for it in g["items"]:
                r = by[JOB[it["key"]]]
                w.writerow([g["title"], it["case"], NAME[it["key"]], r["job_id"], r["bone"], r["rot"], r["f1"], r["contact"], r["A0"], r["e"], r["in_box"], r["delta"]] + [r[v] for v in VARS])
    page = (HERE / "scripts/shapes_template.html").read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps(D, ensure_ascii=False, separators=(",", ":")))
    full = '<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n</head>\n<body>\n' + page + "\n</body>\n</html>\n"
    out = HERE / "股骨柄形状_2026-11-04.html"
    out.write_text(full, encoding="utf-8")
    if a.artifact_out:
        pathlib.Path(a.artifact_out).write_text(page, encoding="utf-8")
    print("written", out, round(out.stat().st_size / 1e6, 2), "MB;", len(used), "stems;", "A top in", len(conds), "conditions")
    print("median faces", median(s["nf"] for s in stems.values()))


if __name__ == "__main__":
    main()
