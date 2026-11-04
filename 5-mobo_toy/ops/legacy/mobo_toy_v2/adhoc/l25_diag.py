"""L25 建模失败（PLC 相交 / 段错误）的几何诊断（Linux，只读，单进程）：
对若干设计采样柄表面点，看它们离内膜面（canal_sdf）、外膜面（outer_sdf）有多近——近乎重合的面是布尔碎片化出细片、网格器失败的典型来源。
按柄长方向分段（上 / 中 / 尖端 3 mm + 帽）统计。"""
import json
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc"))
import front_shapes as FS  # noqa: E402
from front_shapes import G  # noqa: E402

ids = json.loads((HOME / "results" / "collar_ids.json").read_text())["jobs"]
NAMES = ["neck_circ_L25_w0", "neck_asym_L25_w0", "neck_ell_L25_w0", "neck_circ_L30_w0", "neck_asym_L30_w0", "neck_w0", "neck_circ_L35_w0", "neck_ell_L25_w4"]
out = {}
for k in NAMES:
    spec = FS.spec_of(ids[k])
    st, fm, pl = FS.template(spec)
    loc = st.local_surface(pl["A0"], ns=140, m=96, ncap=10)
    P = G.Femur3D.to_world(loc, pl["pose"])
    s = loc[:, 0]
    below = fm.below_cut(P)
    cs, os_ = fm.canal_sdf(P), fm.outer_sdf(P)
    rec = {"L": st.L, "A0": round(pl["A0"]), "e": pl["e"], "s_bind": pl["s_bind"]}
    for lab, msk in (("upper", (s >= 0) & (s < st.L / 3)), ("middle", (s >= st.L / 3) & (s < 2 * st.L / 3)),
                     ("lower", (s >= 2 * st.L / 3) & (s < st.L - 3)), ("tip3mm", (s >= st.L - 3) & (s <= st.L)), ("cap", s > st.L)):
        m = msk & below
        if not m.any():
            continue
        rec[lab] = {"n": int(m.sum()),
                    "in_cortex_frac": float(np.mean(cs[m] > 0)),              # 表面点进入皮质（越过内膜面）
                    "canal_sdf_max": float(cs[m].max()),                        # 最深进入皮质 (mm)
                    "near_endosteal_frac": float(np.mean(np.abs(cs[m]) < 0.15)),  # 与内膜面近乎重合
                    "outer_sdf_max": float(os_[m].max()),                       # > 0 = 穿出骨外
                    "near_periosteal_frac": float(np.mean(os_[m] > -0.5))}      # 离外膜面不到 0.5 mm
    # 尖端位置（项目坐标，z 相对小转子）
    tip = pl["pose"][0] + (st.L + st.cap_length(pl["A0"])) * pl["pose"][1]
    rec["tip_xyz"] = [round(float(v), 1) for v in tip]
    rec["tip_outer_sdf"] = float(fm.outer_sdf(tip[None])[0]); rec["tip_canal_sdf"] = float(fm.canal_sdf(tip[None])[0])
    out[k] = rec
    print(k, json.dumps(rec), flush=True)
(HOME / "adhoc" / "out" / "l25_diag.json").write_text(json.dumps(out, indent=1))
