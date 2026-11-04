"""只建模不求解（adhoc，不碰队列）：25 mm 颈部柄的圆、非对称截面在第一阶段的平端帽（cap_h 1.5）下能否建成。
第零阶段同样的设计用旧半椭球帽在三种网格尺寸下都崩溃。每个设计一个子进程、12 GB 地址空间上限。"""
import json
import pathlib
import resource
import subprocess
import sys

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
OUT = pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "cap_build"
CHILD = r"""
import sys, json, time, pathlib
sys.path.insert(0, '.'); sys.path.insert(0, 'v2')
import femur_real as FR, geom3d as G, model3d_m1 as M1, stage_collar as SC
name, cap = sys.argv[1], float(sys.argv[2])
sec = name.split('_')[0]
d = SC.NECK_SETS[sec](25.0)
d['cap_h'] = cap
st = G.Stem3D(**d); fm = FR.build(); pl = G.template(st, fm)
t = time.time()
info = M1.build(st, fm, pl, pathlib.Path(sys.argv[3]), 'm', delta=0.025)
print(json.dumps({'name': name, 'cap_h': cap, 'A0': pl['A0'], 'n_tet': info['n_tet'], 'mesh_attempt': info.get('mesh_attempt'), 's': round(time.time() - t, 1)}))
"""


def lim():
    g = int(12 * 2 ** 30)
    resource.setrlimit(resource.RLIMIT_AS, (g, g))


for name, cap in [(a, float(b)) for a, b in (x.split(":") for x in sys.argv[1:])]:
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.run([sys.executable, "-c", CHILD, name, str(cap), str(d)], cwd=str(CODE), capture_output=True, text=True,
                           timeout=900, preexec_fn=lim)
        tail = (p.stdout.strip().splitlines() or [""])[-1]
        print(name, "exit", p.returncode, tail if p.returncode == 0 else p.stderr.strip()[-400:], flush=True)
    except subprocess.TimeoutExpired:
        print(name, "timeout 900 s", flush=True)
