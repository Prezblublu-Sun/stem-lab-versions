"""皮质余量 m 对尺寸的影响（只读）：M 类椭圆颈部柄，m 从 −0.25 到 +2 mm 时模板化选出的肩部面积与接触皮质的比例。"""
import pathlib
import sys

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402

fm = FR.build()
for m in (-0.25, 0.0, 0.5, 1.0, 2.0):
    st = G.Stem3D(**G.ellipse_design(30.0, 0.5, 1.0, 1.3, 40.0, m=m))
    pl = G.template(st, fm)
    cf = G.contact_fraction(st, fm, pl["A0"], pl["pose"]) if pl["fit"] else None
    print(f"m {m:+.2f} mm: fit {pl['fit']}  A0 {pl['A0']:.0f} mm²  ML x AP ≈ {2 * (pl['A0'] * 1.3 / 3.1416) ** 0.5:.1f} x {2 * (pl['A0'] / 1.3 / 3.1416) ** 0.5:.1f} mm"
          f"  within 0.5 mm of cortex: {100 * cf:.0f}%  volume {pl['volume'] / 1000:.1f} cm³", flush=True)
