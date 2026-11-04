"""阶段 9 启动前的检查（只读，Linux）：无领柄的假体颈底面伸出柄体截口的情况。
无领时 M1 不给截骨面（plane = None），颈底伸出截口、压在截骨面上的那部分会成为普通界面节点（带过盈、计入柄身微动），
等于一块小领。这里量：(1) 已解的无领作业里，落在截骨面上的界面节点数与面积；(2) 阶段 9 设计空间随机 2000 个可行设计里，
颈底伸出截口的面积分布。输出打印。"""
from __future__ import annotations

import json
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402
from shapely.geometry import Point  # noqa: E402

import collar_rule as CR  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402


def cutplane_pairs(j):
    d = J.QROOT / j
    m = np.load(d / "mesh3d.npz")
    lab = m["node_labels"]; X = m["nodes"]
    lut = {int(n): i for i, n in enumerate(lab)}
    P = np.array([X[lut[int(n)]] for n in m["pair_bone"]])
    spec = json.loads((d / "spec.json").read_text())
    fm = J.femur_for(spec)
    on = np.abs((P - fm.C03) @ fm.u3) <= 0.05
    area = m["pair_area"]
    return int(on.sum()), float(area[on].sum()), float(area.sum()), float((m["pair_interf"][on] > 0).sum())


def overhang(st, fm, pl):
    foot = CR.footprint(st, fm, pl["A0"], pl["pose"])
    neck = Point(0.0, 0.0).buffer(float(fm.cfg["prosthesis"]["neck_radius_mm"]), quad_segs=32)
    return float(neck.difference(foot).area)


if __name__ == "__main__":
    nocollar = []
    for d in J.QROOT.iterdir():
        f = d / "spec.json"
        if not f.exists() or not (d / "DONE").exists() or not (d / "mesh3d.npz").exists():
            continue
        s = json.loads(f.read_text())
        if s.get("kind") in ("design", "variant") and s.get("model") == "m1" and not (s.get("design") or {}).get("collar_w") and not s.get("bond_only"):
            nocollar.append(d.name)
    print("solved collarless M1 jobs:", len(nocollar))
    for j in sorted(nocollar)[:40]:
        try:
            n, a, at, ni = cutplane_pairs(j)
            sp = json.loads((J.QROOT / j / "spec.json").read_text())
            t = (J.result(j) or {}).get("templating") or {}
            print(f"  {j:42s} A0 {t.get('A0', 0):5.0f} e {t.get('e', 0):+.0f}  cut-plane pairs {n:4d}  area {a:6.1f} of {at:7.1f} mm²  with interference {ni:.0f}")
        except Exception as e:                                          # noqa: BLE001
            print("  ", j, type(e).__name__, str(e)[:100])
    ph = N.Phase(9, None, "abs")
    fm0 = FR.build()
    rng = np.random.default_rng(0)
    out = []
    for u in rng.random((2000, len(ph.vars))):
        d, h = ph.design_of(u)
        fm = fm0.with_cut(h)
        st = G.Stem3D(**d)
        pl = G.template(st, fm)
        if not (pl["fit"] and pl["A0"] >= 153.938):
            continue
        out.append((overhang(st, fm, pl), pl["A0"], pl["e"]))
    o = np.array(out)
    print(f"phase-9 space, {len(o)} feasible of 2000 random: neck base outside the shoulder > 1 mm² in {100 * (o[:, 0] > 1).mean():.0f} %, "
          f"> 10 mm² in {100 * (o[:, 0] > 10).mean():.0f} %; median {np.median(o[:, 0]):.1f}, P90 {np.percentile(o[:, 0], 90):.1f}, max {o[:, 0].max():.1f} mm² "
          f"(neck base 153.9 mm²)")
    for lo, hi in ((154, 200), (200, 300), (300, 1e9)):
        k = (o[:, 1] >= lo) & (o[:, 1] < hi)
        if k.any():
            print(f"  A0 {lo}-{hi if hi < 1e8 else 'max'}: n {k.sum()}, overhang > 1 mm² {100 * (o[k, 0] > 1).mean():.0f} %, median {np.median(o[k, 0]):.1f} mm²")
    for e in sorted(set(o[:, 2])):
        k = o[:, 2] == e
        print(f"  e {e:+.0f}: n {k.sum()}, overhang > 1 mm² {100 * (o[k, 0] > 1).mean():.0f} %")
