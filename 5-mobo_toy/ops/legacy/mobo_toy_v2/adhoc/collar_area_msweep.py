"""B1 余量 m 扫描在两种领规则下的领面积（只读，Linux）：领环面积 = 领外形 − 柄截口；颈底圆伸出领外的面积与最大伸出距离。
用来核对"现行规则下 m 增大时微动陡升，是因为领随柄一起缩小、颈底伸出领外"。输入作业号在命令行：old:<job> 或 wrap:<job>。
输出 ~/mobo_toy_v2/deck/F/collar_area_msweep.json"""
from __future__ import annotations

import json
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402


def one(rule: str, j: str) -> dict:
    import collar_rule as CR
    import fe3d_geom as E
    import geom3d as G
    import jobs as J
    from shapely.geometry import Point
    spec = json.loads((J.QROOT / j / "spec.json").read_text())
    if rule == "wrap":
        if spec.get("collar_rule") != "wrap_fit":
            raise RuntimeError(f"{j}: spec has no collar_rule wrap_fit")
        CR.install(min_A0=float(spec.get("min_A0", 0.0)))                # 与 jobs.py 相同
    st = G.Stem3D(**spec["design"])
    fm = J.femur_for(spec)
    pl = G.template(st, fm, margin=spec.get("margin"))
    info = E.collar_outline(st, fm, pl)
    foot, col = info["footprint"], info["poly"]
    neck = Point(0.0, 0.0).buffer(float(fm.cfg["prosthesis"]["neck_radius_mm"]), quad_segs=32)
    prot = max(neck.exterior.interpolate(t, normalized=True).distance(col) for t in np.linspace(0, 1, 256))
    return {"rule": rule, "job": j, "A0": float(pl["A0"]), "e": float(pl.get("e", float("nan"))), "collar_w": float(st.collar_w),
            "collar_ring_mm2": float(col.area - foot.area), "collar_total_mm2": float(col.area),
            "neck_outside_collar_mm2": float(neck.difference(col).area), "neck_protrusion_mm": float(prot)}


if __name__ == "__main__":
    out = []
    for a in sys.argv[1:]:
        rule, j = a.split(":", 1)
        try:
            out.append(one(rule, j))
        except Exception as e:                                          # noqa: BLE001
            out.append({"rule": rule, "job": j, "error": f"{type(e).__name__}: {e}"[:200]})
    p = HOME / "deck" / "F" / "collar_area_msweep.json"
    p.write_text(json.dumps(out, indent=1))
    for r in out:
        print(json.dumps(r))
