"""E0 机制数据集（Linux，0 次 FE，只读正式队列）：每个已解的 M1 摩擦模型作业一行 =
    条件（阶段、代码哈希、领规则、模型假设、载荷覆盖）+ 设计 x + 放置 p + 主目标 + 领描述量 + 柄身描述量 + 二级指标。
在 deck_master.row_of 的基础上加：
  领（几何，按作业自己的规则与偏移重算）：领总面积、领环面积、领环落在皮质上的比例 C_geo、颈底伸出领外的面积与距离、重算的号 / 偏移是否与记录一致
  领（网格）：领面节点对里挨着皮质单元的面积比例 C_mesh（所有作业都有）
  领（力学，LOAD2）：贴合比例、法向合力、皮质 / 松质的贴合面积、平均压力、皮质承担的法向力份额 C_mech
  柄身：按柄局部坐标分近 / 中 / 远三段 × 内 / 外 / 前 / 后：面积份额、挨皮质的面积比例、贴合比例、可恢复滑移 P95、压配压力（RELEASE）均值
输出 ~/mobo_toy_v2/deck/E0/mechanism_dataset.csv（+ errors.json）。
    ~/mobo_toy_v2/run.sh e0_descriptors.py [--workers 3] [--only job1,job2]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import pathlib
import sys
import time
from multiprocessing import Pool

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2")); sys.path.insert(0, str(HOME / "adhoc"))
import numpy as np  # noqa: E402

import jobs as J  # noqa: E402

OUT = HOME / "deck" / "E0"
_FM: dict = {}
SPEC_KEYS = ("collar_rule", "bond_collar", "entry_offset", "deck_code", "source_job", "load_case", "margin", "keep_odb")


def femur(spec: dict):
    import femur_real as FR
    if "base" not in _FM:
        _FM["base"] = FR.build()
    h = float(spec.get("h_cut", 25.0))
    if h not in _FM:
        _FM[h] = _FM["base"].with_cut(h)
    return _FM[h]


def collar_geometry(spec: dict, res: dict, fm) -> dict:
    """领外形按作业自己的规则（现行 / wrap_fit）与偏移（固定或搜索）重算。"""
    import collar_rule as CR
    import geom3d as G
    from shapely.geometry import Point
    st = G.Stem3D(**spec["design"])
    if not getattr(st, "has_collar", False):
        return {"has_collar": False}
    offs = np.array([float(spec["entry_offset"])]) if spec.get("entry_offset") is not None else np.arange(-8.0, 8.1, 2.0)
    if spec.get("collar_rule") == "wrap_fit":
        pl = CR.template_wrap_fit(st, fm, offsets=offs, margin=spec.get("margin"), min_A0=float(spec.get("min_A0", 0.0)))
        info = CR.collar_outline_wrap(st, fm, pl)
    else:
        pl = CR._ORIG["template"](st, fm, offsets=offs, margin=spec.get("margin"))
        info = CR._ORIG["collar_outline"](st, fm, pl)
    foot, col = info["footprint"], info["poly"]
    neck = Point(0.0, 0.0).buffer(float(fm.cfg["prosthesis"]["neck_radius_mm"]), quad_segs=32)
    t = res.get("templating") or {}
    return {"has_collar": True, "collar_total_mm2": float(col.area), "collar_ring_mm2": float(col.area - foot.area),
            "footprint_mm2": float(foot.area), "C_geo_ring_cortex_frac": info.get("ring_cortex_frac"),
            "neck_outside_collar_mm2": float(neck.difference(col).area),
            "neck_protrusion_mm": float(max(neck.exterior.interpolate(q, normalized=True).distance(col) for q in np.linspace(0, 1, 256))),
            "geom_retemplate_A0": float(pl["A0"]), "geom_retemplate_e": float(pl["e"]),
            "geom_check_A0_e": bool(abs(pl["A0"] - t.get("A0", -1)) < 0.5 and abs(pl["e"] - t.get("e", 99)) < 1e-6)}


def collar_mechanics(d: pathlib.Path, p: dict, closed: np.ndarray) -> dict:
    """LOAD2 时领面：皮质 / 松质的贴合面积、法向力、平均压力、皮质份额（deck_collar_pressure 的口径）。"""
    import qoi
    col, w, cort, pb = p["pair_collar"], p["pair_area"], p["pair_cortex"].astype(bool), p["pair_bone"]
    out = {"C_mesh_collar_cortex_area_frac": float(w[col & cort].sum() / w[col].sum()), "collar_closed_frac": float(w[col & closed].sum() / w[col].sum()),
           "collar_closed_cortex_area_mm2": float(w[col & closed & cort].sum()), "collar_closed_cancellous_area_mm2": float(w[col & closed & ~cort].sum())}
    f = d / "m_fric_csv" / "LOAD2_CFORCE.csv"
    if not f.exists():
        return out
    t = qoi._csv(f)
    node = t["node"].astype(int)
    Fn = np.zeros(p["n"] + 1)
    k = (t["field"] == "CNORMF") & (node <= p["n"])
    np.add.at(Fn, node[k], np.linalg.norm(np.c_[t["f1"], t["f2"], t["f3"]][k], axis=1))
    fn = Fn[pb]
    tot = float(fn[col & closed].sum())
    out["collar_normal_force_N"] = float(fn[col].sum())
    for name, sel in (("cortex", cort), ("cancellous", ~cort)):
        m = col & closed & sel
        A, F = float(w[m].sum()), float(fn[m].sum())
        out[f"collar_{name}_mean_p_MPa"] = F / A if A > 0 else math.nan
        out[f"collar_{name}_force_share"] = F / tot if tot > 0 else math.nan
    out["C_mech_collar_cortex_force_share"] = out["collar_cortex_force_share"]
    return out


def body_regions(d: pathlib.Path, p: dict, spec: dict, res: dict, fm, rev: np.ndarray, closed: np.ndarray) -> dict:
    """柄身按局部坐标分区（audit3 的口径）：s 沿柄轴向远端增大，x 内侧为正，y 前方为正。"""
    import post_m1 as PM1
    body = ~p["pair_collar"]
    pb, w, cort = p["pair_bone"], p["pair_area"], p["pair_cortex"].astype(bool)
    lut = np.full(p["n"] + 1, -1)
    lut[p["node_labels"]] = np.arange(len(p["node_labels"]))
    X = p["nodes"][lut[pb]]
    t = res["templating"]
    pose = fm.pose(t["alpha"], t["e"])
    Q = X - pose[0]
    s_, x_, y_ = Q @ pose[1], Q @ pose[2], Q @ pose[3]
    L = float(spec["design"]["L"])
    C = PM1._ctab(d / "m_fric_csv" / "RELEASE_CONTACT.csv", p["n"])
    cp = np.nan_to_num(C["CPRESS"][pb])
    W = float(w[body].sum())
    out = {"body_area_mm2": W, "body_cortex_area_frac": float(w[body & cort].sum() / W), "body_closed_frac": float(w[body & closed].sum() / W),
           "body_cortex_closed_area_mm2": float(w[body & cort & closed].sum()), "body_press_fit_mean_MPa": float((cp[body] * w[body]).sum() / W)}
    for name, k in (("prox", s_ < L / 3), ("mid", (s_ >= L / 3) & (s_ < 2 * L / 3)), ("dist", s_ >= 2 * L / 3),
                    ("med", x_ >= 0), ("lat", x_ < 0), ("ant", y_ >= 0), ("post", y_ < 0)):
        m = body & k
        Wm = float(w[m].sum())
        if Wm <= 0:
            continue
        out[f"{name}_area_frac"] = Wm / W
        out[f"{name}_cortex_area_frac"] = float(w[m & cort].sum() / Wm)
        out[f"{name}_closed_frac"] = float(w[m & closed].sum() / Wm)
        out[f"{name}_cortex_closed_area_mm2"] = float(w[m & cort & closed].sum())
        out[f"{name}_slip_rev_p95_um"] = PM1._wq(rev[m], w[m], 0.95)
        out[f"{name}_press_fit_mean_MPa"] = float((cp[m] * w[m]).sum() / Wm)
    out["prox_cortex_closed_area_frac_of_body"] = out.get("prox_cortex_closed_area_mm2", 0.0) / W
    return out


def one(j: str) -> dict:
    import deck_master as D
    import post_m1 as PM1
    d = J.QROOT / j
    spec = json.loads((d / "spec.json").read_text())
    res = json.loads((d / "result.json").read_text())
    r = D.row_of(j)
    r["tag"] = spec.get("tag")
    r.update({f"spec_{k}": (json.dumps(spec[k]) if isinstance(spec.get(k), (dict, list)) else spec.get(k)) for k in SPEC_KEYS})
    r["production_settings"] = bool(spec.get("mu") is None and spec.get("E_canc") is None and spec.get("cfg") is None and spec.get("cycles") is None
                                    and abs(float(spec.get("delta", 0)) - 0.025) < 1e-9 and abs(float(spec.get("slip_tol", 0)) - 2.5e-4) < 1e-12
                                    and float(spec.get("h_int", 0)) == 2.0 and spec.get("entry_offset") is None)
    t = res.get("templating") or {}
    r["templ_contact_frac"] = t.get("contact"); r["templ_s_bind"] = t.get("s_bind")
    fm = femur(spec)
    errs = []
    try:
        r.update(collar_geometry(spec, res, fm))
    except Exception as e:                                                  # noqa: BLE001
        errs.append(f"geometry: {type(e).__name__}: {e}"[:160])
    try:
        p = PM1.pairs(d)
        pb, ps, nrm, w, di = p["pair_bone"], p["pair_stem"], p["pair_normal"], p["pair_area"], p["pair_interf"]
        U = {s: PM1._utab(d / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in ("UNLOAD", "LOAD2")}
        rel = {s: U[s][ps] - U[s][pb] for s in U}
        dv = rel["LOAD2"] - rel["UNLOAD"]
        rev = np.linalg.norm(dv - (dv * nrm).sum(1)[:, None] * nrm, axis=1) * 1e3
        closed = (-(di + (rel["LOAD2"] * nrm).sum(1)) * 1e3) <= PM1.OPEN_UM
        r["interface_area_mm2"] = float(w.sum())
        if p["pair_collar"].any():
            r.update(collar_mechanics(d, p, closed))
        r.update(body_regions(d, p, spec, res, fm, rev, closed))
    except Exception as e:                                                  # noqa: BLE001
        errs.append(f"mechanics: {type(e).__name__}: {e}"[:160])
    r["e0_errors"] = "; ".join(errs) or None
    return r


def select() -> list[str]:
    sel = []
    for d in sorted(J.QROOT.iterdir()):
        if not (d / "DONE").exists() or not (d / "spec.json").exists() or not (d / "m_fric_csv" / "LOAD2_U.csv").exists():
            continue
        sp = json.loads((d / "spec.json").read_text())
        if sp.get("model") == "m1" and sp.get("kind") in ("design", "variant") and not sp.get("bond_only"):
            sel.append(d.name)
    return sel


def safe(j: str) -> dict:
    try:
        return one(j)
    except Exception as e:                                                  # noqa: BLE001
        return {"job_id": j, "e0_errors": f"FATAL {type(e).__name__}: {e}"[:200]}


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = a.only.split(",") if a.only else select()
    t0 = time.time()
    print(f"E0: {len(jobs)} jobs, {a.workers} workers", flush=True)
    rows = []
    with Pool(a.workers) as pool:
        for i, r in enumerate(pool.imap_unordered(safe, jobs, chunksize=4), 1):
            rows.append(r)
            if i % 50 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}  {time.time() - t0:.0f} s", flush=True)
    rows.sort(key=lambda r: r["job_id"])
    keys = list(dict.fromkeys(k for r in rows for k in r))
    name = "mechanism_dataset.csv" if not a.only else "test_subset.csv"
    with open(OUT / name, "w", newline="") as fh:
        wr = csv.DictWriter(fh, keys)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: ("" if v is None or (isinstance(v, float) and not math.isfinite(v)) else v) for k, v in r.items()})
    errs = {r["job_id"]: r["e0_errors"] for r in rows if r.get("e0_errors")}
    (OUT / ("errors.json" if not a.only else "test_errors.json")).write_text(json.dumps(errs, indent=1))
    print(f"wrote {len(rows)} rows, {len(keys)} columns, {len(errs)} with errors, {time.time() - t0:.0f} s", flush=True)
