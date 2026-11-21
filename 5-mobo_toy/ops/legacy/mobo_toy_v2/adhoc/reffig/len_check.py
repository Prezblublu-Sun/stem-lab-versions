"""柄长 20–60 mm × 插入角的可放置性（只模板化，不求解；adhoc）。椭圆 λ 1.3、ρ_tip 0.5、q 1.0、余量 −0.25、截骨 25 mm，与颈部柄阶段相同。
柄尖高度以小转子水平为 0（股骨坐标 z 原点在小转子），负值 = 在小转子以下。"""
import json
import pathlib
import sys

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import stage_v2a as S  # noqa: E402

fm = FR.build()
rows = []
for L in (20, 25, 30, 35, 40, 50, 60):
    for a in (20, 30, 40):
        st = G.Stem3D(**G.ellipse_design(float(L), 0.5, 1.0, 1.3, float(a)))
        pl = G.template(st, fm)
        r = {"L": L, "alpha": a, "fit": bool(pl["fit"])}
        if pl["fit"]:
            P0, d = fm.pose(pl["alpha"], pl["e"])[:2]
            tip = P0 + (st.L + st.cap_length(pl["A0"])) * d
            r.update(A0=round(pl["A0"]), e=pl["e"], removal_cm3=round(pl["volume"] / 1000, 1), tip_z_vs_LT=round(float(tip[2]), 1),
                     ok_neck=bool(pl["A0"] >= S.MIN_A0))
        else:
            r["reason"] = pl.get("reason")
        rows.append(r)
        print(json.dumps(r), flush=True)
