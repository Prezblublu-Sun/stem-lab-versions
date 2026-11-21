"""诊断：截骨面上骨单元的面，哪些与领共面接触（在界面里），哪些落在领的外形内却没进界面。"""
import json
import pathlib
import sys

import numpy as np

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import fe3d_geom as E  # noqa: E402
from spot3d.model3d import FACES  # noqa: E402
from shapely.geometry import Point, Polygon  # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else "base_w2"
d = pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "build_test" / name
m = dict(np.load(d / "mesh3d.npz"))
info = json.loads((d / "model3d.json").read_text())
fm = FR.build()
C, e1, e2, _ = E.cut_plane(fm)
lab, X = m["node_labels"], m["nodes"]
lut = np.full(int(lab.max()) + 1, -1); lut[lab] = np.arange(len(lab))
slave = {(int(a), int(b)) for a, b in info["slave"]}
poly = Polygon(info["collar"]["outline_uv"])
foot_area = info["collar"]["footprint_mm2"]
off = {"cortex": 0, "cancellous": len(m["cortex_conn"])}
rows = []
for r in ("cortex", "cancellous"):
    conn = m[f"{r}_conn"]
    el = m[f"{r}_elab"]
    for i, row in enumerate(conn):
        for fc, idx in FACES.items():
            nodes = [int(row[k]) for k in idx]
            P = X[lut[nodes]]
            if np.abs((P - C) @ E.cut_plane(fm)[3]).max() > 1e-3:
                continue
            A = 0.5 * np.linalg.norm(np.cross(P[1] - P[0], P[2] - P[0]))
            c = P.mean(0) - C
            uv = (float(c @ e1), float(c @ e2))
            rows.append((r, A, (int(el[i]), fc) in slave, poly.contains(Point(*uv)), uv))
tot = sum(a for _, a, *_ in rows)
inter = sum(a for _, a, s, *_ in rows if s)
inside_not = [(r, a, uv) for r, a, s, ins, uv in rows if ins and not s]
outside_in = sum(a for _, a, s, ins, _ in rows if s and not ins)
print(json.dumps({"bone_faces_on_plane_mm2": tot, "in_interface_mm2": inter, "inside_collar_not_interface_mm2": sum(a for _, a, _ in inside_not),
                  "interface_outside_collar_mm2": outside_in, "collar_ring_mm2": info["collar"]["ring_mm2"],
                  "collar_area_mm2": info["collar"]["area_mm2"], "footprint_mm2": foot_area,
                  "n_inside_not": len(inside_not), "example_uv": [uv for _, _, uv in inside_not[:8]]}, indent=1))
