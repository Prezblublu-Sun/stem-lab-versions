"""短柄网格失败的定位：直接调 _build（不走重试链），可指定远场网格 h_far；打开 gmsh 终端输出以拿到 PLC 相交点坐标。
用法：plc_probe.py L lam h_far h_int [asym]      lam 1.0 圆、1.3 椭圆；h_far / h_int 给 - 用默认；第 5 个参数 asym 用非对称截面。"""
import pathlib
import sys
import time

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import gmsh  # noqa: E402

_init = gmsh.initialize


def _init_verbose(*a, **k):
    _init(*a, **k)
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.option.setNumber("General.Verbosity", 2)          # 只要 error / warning


gmsh.initialize = _init_verbose
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import model3d_m1 as M1  # noqa: E402
import stage_collar as SC  # noqa: E402

L = float(sys.argv[1]); lam = float(sys.argv[2])
fm = FR.build()
h_far = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "-" else fm.cfg["mesh"]["h_far_mm"]
h_int = float(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] != "-" else 2.0
asym = len(sys.argv) > 5 and sys.argv[5] == "asym"
d = {**SC.NECK_ASYM, "L": L} if asym else G.ellipse_design(L, 0.5, 1.0, lam, 40.0)
tag = f"L{L:g}_{'asym' if asym else f'lam{lam:g}'}_hfar{h_far:g}_hint{h_int:g}"
out = pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "plc_probe" / tag
out.mkdir(parents=True, exist_ok=True)
st = G.Stem3D(**d)
pl = G.template(st, fm)
print(f"== {tag}: A0 {pl['A0']:.0f} e {pl['e']} s_bind {pl['s_bind']:.1f}", flush=True)
t0 = time.time()
try:
    info = M1._build(st, fm, pl, out, "m", h_int=h_int, h_far=h_far, delta=0.025, mu=None, torque=True, algo=1,
                     sec_pts=40, E_canc=None, slip_tol=2.5e-4, lagrange=False, interference=None)
    print(f"== {tag}: BUILT {time.time() - t0:.0f} s n_tet {info['n_tet']}", flush=True)
except Exception as e:                                               # noqa: BLE001
    print(f"== {tag}: EXCEPTION {time.time() - t0:.0f} s: {type(e).__name__}: {e}", flush=True)
