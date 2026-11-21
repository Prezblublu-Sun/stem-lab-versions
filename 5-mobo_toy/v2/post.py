"""V2A 后处理（在 Linux 上跑）：作业目录里的 Abaqus 导出 CSV → 关注量。

* f1 初期微动：复用 spot3d/qoi3d.micromotion（从面节点在 LOAD 相对 RELEASE 的切向滑移增量，面积加权 P95，µm）。
* f2 近端应力遮挡：Gruen 7 区（模型坐标 x ≥ 0、z ≥ −10、截骨面以下，全部 y）骨单元的 ΣELSE/ΣEVOL，
  相对完整股骨同一区域的下降率（%）；Gruen 1 区（x < 0）同法记录。完整股骨参照的区域同样限于截骨面以下。
* 约束：粘接模型柄体（截骨面以下）von Mises 的体积加权 P99（MPa）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import qoi  # noqa: E402
from spot3d import qoi3d  # noqa: E402

ZONE_Z_MIN = -10.0                     # mm，模型坐标（小转子下 10 mm）


def _mesh(d: pathlib.Path):
    m = dict(np.load(d / "mesh3d.npz"))
    lab, X = m["node_labels"], m["nodes"]
    lut = np.full(int(lab.max()) + 1, -1); lut[lab] = np.arange(len(lab))
    return m, X, lut


def _centroids(m, X, lut, region):
    return X[lut[m[f"{region}_conn"][:, :4]]].mean(1)


def zone_sed(d: pathlib.Path, job: str, fm) -> dict:
    m, X, lut = _mesh(d)
    en = qoi._csv(d / f"{job}_csv" / "LOAD_ENER.csv")
    e_by = dict(zip(en["elem"].astype(int), en["else"])); v_by = dict(zip(en["elem"].astype(int), en["evol"]))
    out = {}
    for zname, cond in (("gruen7", lambda c: c[:, 0] >= 0.0), ("gruen1", lambda c: c[:, 0] < 0.0)):
        E_, V_ = 0.0, 0.0
        for r in ("cortex", "cancellous"):
            cen = _centroids(m, X, lut, r)
            sel = cond(cen) & (cen[:, 2] >= ZONE_Z_MIN) & fm.below_cut(cen)
            for el in m[f"{r}_elab"][sel]:
                E_ += e_by.get(int(el), 0.0); V_ += v_by.get(int(el), 0.0)
        out[zname] = E_ / V_ if V_ else float("nan")
        out[f"{zname}_vol_mm3"] = V_
    return out


def stem_vm(d: pathlib.Path, job: str, fm) -> dict:
    m, X, lut = _mesh(d)
    s = qoi._csv(d / f"{job}_csv" / "LOAD_S.csv")
    en = qoi._csv(d / f"{job}_csv" / "LOAD_ENER.csv")
    mis = dict(zip(s["elem"].astype(int), s["mises"])); vol = dict(zip(en["elem"].astype(int), en["evol"]))
    cen = _centroids(m, X, lut, "stem")
    sel = fm.below_cut(cen)
    labs = m["stem_elab"][sel]
    v = np.array([mis[int(e)] for e in labs]); w = np.array([vol.get(int(e), 0.0) for e in labs])
    return {"vm_p99": qoi.wquantile(v, w, 0.99), "vm_max": float(v.max()), "n_stem_elems_in_bone": int(len(v))}


def evaluate(d: pathlib.Path, name: str, fm, intact: dict) -> dict:
    """d 里应有 {name}_fric_csv 与 {name}_bond_csv。intact = zone_sed(完整股骨)。"""
    mm = qoi3d.micromotion(d, f"{name}_fric")
    zs = zone_sed(d, f"{name}_bond", fm)
    vm = stem_vm(d, f"{name}_bond", fm)
    out = {**mm, **vm, "sed_gruen7": zs["gruen7"], "sed_gruen1": zs["gruen1"],
           "f2_g7_loss_pct": 100.0 * (1.0 - zs["gruen7"] / intact["gruen7"]),
           "f2_g1_loss_pct": 100.0 * (1.0 - zs["gruen1"] / intact["gruen1"]),
           "f1_p95_um": mm["f1_p95_um"]}
    return out


if __name__ == "__main__":
    import argparse
    import femur_real as FR
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--intact-dir", required=True)
    a = ap.parse_args()
    fm = FR.build()
    intact = zone_sed(pathlib.Path(a.intact_dir), "intact", fm)
    res = evaluate(pathlib.Path(a.dir), a.name, fm, intact)
    print(json.dumps({"intact": intact, "design": res}, indent=1, default=float))
