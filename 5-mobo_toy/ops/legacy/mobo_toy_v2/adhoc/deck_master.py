"""批次 0：全部已解作业的新旧两套口径主表（0 次 FE，只读正式队列；在 Linux 上跑，结果写 ~/mobo_toy_v2/deck/）。

范围：阶段 0 网格与领文档（stage collar）、M1 验证（m1、ref2）、优化 p1–p6（neck1–neck6；neck4 = 暂停的稳健优化）、
验证 A（verify）、截深扫描（hsweep）、Ata 对照（ata）。只收 DONE；失败的另写 master_failed.csv。

口径
  旧（metric v1，优化时用的）：整界面微动 f1_all_p95_um（柄身 + 领面，含张开节点）；股骨距 = 固定 7 区皮质应力屏蔽 ssi_pct。
  新（metric v2，图一律用这个）：柄身微动 f1_p95_um（< 2 µm 标 "<2"）；股骨距 = 固定 7 区皮质应变能变化 sed_chg_pct；
      去骨 = 截骨 resected_mm3 + 锉腔 reamed_mm3（两项分开存）。
  贴合节点口径（副本 2610 opt 的 post_m1 定义，这里由 CSV 现算，不改正式代码）：LOAD2 时间隙 ≤ 1 µm 的节点才算，
      f1_all_closed_p95_um、collar_slip_closed_p95_um、collar_closed_frac_load2。
  截骨面下方近端带低应变能比例 band_res06_pct：固定区 G1 + G7（小转子下 10 mm 到截骨面）皮质里，
      应变能比 < 0.4（死区 s = 0.6）的体积分数；另给 G7 单独的 g7_res06_pct。

    ~/mobo_toy_v2/run.sh deck_master.py [--workers 4]
"""
from __future__ import annotations

import csv
import json
import math
import os
import pathlib
import sys
import time
from multiprocessing import Pool

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import jobs as J  # noqa: E402

OUT = HOME / "deck"
STAGES = ("collar", "m1", "ref2", "neck1", "neck2", "neck3", "neck4", "neck5", "neck6", "verify", "hsweep", "ata")
PHASE = {"neck1": "p1", "neck2": "p2", "neck3": "p3 joint", "neck4": "p4 robust (paused)", "neck5": "p5 new split s1",
         "neck6": "p6 new split s2", "verify": "verify A", "hsweep": "resection sweep", "ata": "Ata comparison",
         "m1": "M1 verification", "ref2": "M1 re-solve of old fronts"}
# 代码哈希 → 模型版本（由 git 提交反推，见 README）
VERSION = {"45a3906c22": "M1 v1 (09-29, d227168)", "43be8692bf": "M1 + exports (09-29, 2d2ede6)",
           "84cdf2dab5": "collar (10-02, 1d36c78)", "4f5d99f453": "flat-tip option (10-02, 120dc38)",
           "6d7af243d0": "current: unified cut plane (10-02, 6ced235)"}
DESIGN_KEYS = ("L", "alpha", "collar_w", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "cap_h", "collar_t")
STORED = ("f1_p95_um", "f1_all_p95_um", "f1_closed_p95_um", "f1_first_p95_um", "f1_first_all_p95_um", "area_frac_gt40",
          "open_frac_release", "open_frac_load2", "collar_force_share_load2", "collar_open_frac_load2", "collar_slip_rev_p95_um",
          "cpress_release_p50", "cpress_release_p95", "vm_p99", "vm_max", "f2_g7_loss_pct")


def grade(stage: str, tag: str) -> str:
    if stage == "hsweep" or (stage == "collar" and not tag.startswith("neck")):
        return "A single-factor"
    if stage == "collar":
        return "B grid"
    if stage in ("verify", "ata", "m1", "ref2"):
        return "C sensitivity/verification"
    return "D optimisation sample"


def closed_metrics(d: pathlib.Path) -> dict:
    """副本 post_m1 的贴合节点口径，由 CSV 现算；同时重算柄身 P95 作自检。"""
    import post_m1 as PM1
    p = PM1.pairs(d)
    col = p["pair_collar"]
    pb, ps, nrm, w, di = p["pair_bone"], p["pair_stem"], p["pair_normal"], p["pair_area"], p["pair_interf"]
    U = {s: PM1._utab(d / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in ("UNLOAD", "LOAD2")}
    rel = {s: U[s][ps] - U[s][pb] for s in U}
    dv = rel["LOAD2"] - rel["UNLOAD"]
    rev = np.linalg.norm(dv - (dv * nrm).sum(1)[:, None] * nrm, axis=1) * 1e3
    gap = -(di + (rel["LOAD2"] * nrm).sum(1)) * 1e3
    closed = gap <= PM1.OPEN_UM
    out = {"f1_all_closed_p95_um": PM1._wq(rev[closed], w[closed], 0.95), "_f1_body_check": PM1._wq(rev[~col], w[~col], 0.95)}
    if col.any():
        cc = col & closed
        out["collar_slip_closed_p95_um"] = PM1._wq(rev[cc], w[cc], 0.95) if cc.any() else math.nan
        out["collar_closed_frac_load2"] = float(w[cc].sum() / w[col].sum())
    return out


def calcar(j: str, iname: str | None) -> dict:
    import resorption as RS
    rows, _ = RS.design_rows(j, iname)
    fx = {r["zone"]: r for r in rows if r["scheme"] == "fixed" and r["tissue"] == "cortex"}
    g7, g1 = fx.get("G7", {}), fx.get("G1", {})
    out = {"sed_chg_pct": g7.get("sed_chg_pct"), "ssi_pct": g7.get("ssi_pct"), "g7_res06_pct": g7.get("res_0.6")}
    if g7.get("res_0.6") is not None and g1.get("res_0.6") is not None:
        v7, v1 = g7["vol"], g1["vol"]
        out["band_res06_pct"] = (g7["res_0.6"] * v7 + g1["res_0.6"] * v1) / (v7 + v1)
    return out


def row_of(j: str) -> dict:
    d = J.QROOT / j
    spec = json.loads((d / "spec.json").read_text())
    res = json.loads((d / "result.json").read_text())
    prep = json.loads((d / "prep.json").read_text()) if (d / "prep.json").exists() else {}
    dsg = spec.get("design") or {}
    h = prep.get("code_hash")
    cap = dsg.get("cap_h")
    t = res.get("templating") or {}
    bl = res.get("bone_loss") or {}
    r = {"job_id": j, "stage": spec.get("stage"), "phase": PHASE.get(spec.get("stage"), "stage 0 / collar doc"),
         "evidence": grade(spec.get("stage", ""), spec.get("tag", "")), "kind": spec.get("kind"), "model": spec.get("model", "v2 (old interface)"),
         "code_hash": h, "model_version": VERSION.get(h, "pre-M1 (old interface)" if spec.get("model") != "m1" else h),
         "tip": "flat" if (cap is not None and cap > 0) else "dome", "cut_plane": "unified" if h == "6d7af243d0" else "old (4.1 deg off)",
         **{f"var_{k}": spec.get(k) for k in ("delta", "mu", "slip_tol", "h_int", "E_canc", "cycles", "bond_only", "intact_job")},
         "var_cfg": json.dumps(spec["cfg"]) if spec.get("cfg") else None,
         **{k: dsg.get(k) for k in DESIGN_KEYS}, "h_cut": res.get("h_cut_mm", spec.get("h_cut", 25.0)),
         "A0_shoulder_mm2": t.get("A0"), "entry_offset_e": t.get("e"),
         **{k: res.get(k) for k in STORED},
         "resected_mm3": bl.get("resected_mm3"), "reamed_mm3": bl.get("reamed_mm3"), "intact_ref": res.get("intact_job")}
    f1 = res.get("f1_p95_um")
    r["f1_body_label"] = (None if f1 is None else ("<2" if f1 < 2.0 else f"{f1:.1f}"))
    r["bone_removed_mm3"] = (r["resected_mm3"] or 0) + (r["reamed_mm3"] or 0) if r["reamed_mm3"] is not None else None
    notes = []
    if (d / "m_fric_csv").exists() and spec.get("model") == "m1":
        try:
            cm = closed_metrics(d)
            chk = cm.pop("_f1_body_check")
            if f1 is not None and abs(chk - f1) > 1e-6 * max(1.0, abs(f1)):
                notes.append(f"body P95 recomputed {chk:.4g} vs stored {f1:.4g}")
            r.update(cm)
        except Exception as e:                                              # noqa: BLE001
            notes.append(f"closed metrics: {type(e).__name__}: {e}"[:160])
    if (d / "m_bond_csv").exists() and spec.get("kind") != "intact":
        try:
            r.update(calcar(j, res.get("intact_job")))
        except Exception as e:                                              # noqa: BLE001
            notes.append(f"calcar: {type(e).__name__}: {e}"[:160])
    r["notes"] = "; ".join(notes) or None
    return r


def main(workers: int = 4) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    done, failed = [], []
    for d in sorted(J.QROOT.iterdir()):
        if not (d / "spec.json").exists():
            continue
        sp = json.loads((d / "spec.json").read_text())
        if sp.get("stage") not in STAGES or sp.get("kind") in ("intact", "bench"):
            continue
        if (d / "DONE").exists() and (d / "result.json").exists():
            done.append(d.name)
        elif (d / "FAILED.json").exists():
            f = json.loads((d / "FAILED.json").read_text())
            failed.append({"job_id": d.name, "stage": sp.get("stage"), "level": f.get("level"), "where": f.get("stage"),
                           "reason": (f.get("reason") or "").splitlines()[0][:200], **{k: (sp.get("design") or {}).get(k) for k in ("L", "alpha", "collar_w", "m")},
                           "h_cut": sp.get("h_cut")})
    t0 = time.time()
    print(f"{len(done)} solved, {len(failed)} failed", flush=True)
    os.environ["OMP_NUM_THREADS"] = "1"
    with Pool(workers) as pool:
        rows = []
        for i, r in enumerate(pool.imap(row_of, done, chunksize=4)):
            rows.append(r)
            if (i + 1) % 50 == 0:
                print(f"{i + 1}/{len(done)} ({time.time() - t0:.0f} s)", flush=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(OUT / "master_table.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None or (isinstance(v, float) and not math.isfinite(v)) else v) for k, v in r.items()})
    with open(OUT / "master_failed.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, list(failed[0]) if failed else ["job_id"])
        w.writeheader(); w.writerows(failed)
    print(f"done: {len(rows)} rows, {len(failed)} failed ({time.time() - t0:.0f} s); notes on {sum(1 for r in rows if r['notes'])} rows", flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    main(ap.parse_args().workers)
