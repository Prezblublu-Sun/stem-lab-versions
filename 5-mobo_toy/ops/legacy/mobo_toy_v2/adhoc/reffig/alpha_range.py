"""每个柄长下插入角的可行范围（只模板化；adhoc）。椭圆 λ 1.3、截骨 25 mm、余量 −0.25；两种锥度：
缓锥（ρ_tip 0.5, q 1.0，颈部柄现用）与 V3 锥度（ρ_tip 0.3, q 1.5）。可行 = 放得下且肩部 ≥ 假体颈截面 154 mm²。"""
import json
import pathlib
import sys

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import stage_v2a as S  # noqa: E402

fm = FR.build()
out = {}
for taper, (rho, q) in (("gentle", (0.5, 1.0)), ("v3", (0.3, 1.5))):
    for L in (20, 30, 40, 50, 60):
        row = {}
        for a in range(5, 46, 5):
            st = G.Stem3D(**G.ellipse_design(float(L), rho, q, 1.3, float(a)))
            pl = G.template(st, fm)
            row[a] = round(pl["A0"]) if pl["fit"] and pl["A0"] >= S.MIN_A0 else None
        out[f"{taper}_L{L}"] = row
        print(taper, L, json.dumps(row), flush=True)
