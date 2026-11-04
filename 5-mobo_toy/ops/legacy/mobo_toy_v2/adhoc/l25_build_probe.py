"""L25 建模崩溃（段错误）的定位：同一圆截面无领设计，只改柄长 L（命令行给），单独建模到临时目录（不入队列）。
每个 L 在自己的进程里跑（外层 bash 循环），段错误只杀自己。输出：是否建成、网格规模、尝试记录。"""
import json
import pathlib
import sys
import time

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import model3d_m1 as M1  # noqa: E402

L = float(sys.argv[1])
lam = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
out = pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "l25_probe" / f"L{L:g}_lam{lam:g}"
out.mkdir(parents=True, exist_ok=True)
fm = FR.build()
st = G.Stem3D(**G.ellipse_design(L, 0.5, 1.0, lam, 40.0))
pl = G.template(st, fm)
print(f"L {L} lam {lam}: fit {pl['fit']} A0 {pl['A0']:.0f} e {pl['e']} s_bind {pl['s_bind']:.1f}", flush=True)
t0 = time.time()
try:
    info = M1.build(st, fm, pl, out, "m", delta=0.025)
    print(f"  BUILT in {time.time() - t0:.0f} s: n_tet {info['n_tet']} attempt {info['mesh_attempt']}", flush=True)
except Exception as e:                                               # noqa: BLE001
    print(f"  EXCEPTION after {time.time() - t0:.0f} s: {type(e).__name__}: {str(e)[:400]}", flush=True)
