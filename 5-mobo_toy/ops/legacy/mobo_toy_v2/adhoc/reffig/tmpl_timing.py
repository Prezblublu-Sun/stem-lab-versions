"""模板化耗时与领外形检查（只读，adhoc）。"""
import pathlib
import sys
import time

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import fe3d_geom as E  # noqa: E402

t = time.time()
fm0 = FR.build()
print("build", round(time.time() - t, 1), flush=True)
for h in (25.0, 35.0):
    fm = fm0.with_cut(h)
    for L, w in ((25.0, 4.0), (30.0, 2.0)):
        d = G.ellipse_design(L, 0.5, 1.0, 1.3, 40.0, collar_w=w)
        st = G.Stem3D(**d)
        t = time.time()
        pl = G.template(st, fm)
        t1 = time.time() - t
        pl["pose"] = fm.pose(pl["alpha"], pl["e"])
        t = time.time()
        c = E.collar_outline(st, fm, pl)
        print(h, L, w, "template", round(t1, 2), "s fit", pl["fit"], "A0", round(pl["A0"]), "e", pl["e"], "vol", round(pl["volume"]),
              "resected", round(fm.resected_volume()), "collar", round(time.time() - t, 2), "s ring", round(c["ring_mm2"]),
              "cortex", round(c["ring_cortex_frac"], 2), flush=True)
C, e1, e2 = fm0.neck_plane()
print("neck plane C", C, "H", fm0.H)
