"""阶段 1 审查用的两项只读检查（adhoc，不提交作业）。
1 完整股骨的 7 区应变能密度随“截骨面以下”的区域怎么变：同一个完整股骨结果，按截骨 25–40 mm 取区域。
  设计侧用 with_cut(h) 取区域，完整股骨对照固定按 25 mm 取 → 比值里混进区域差。
2 截骨面（解析面，垂直颈轴）与骨的交线有几块：深截骨时平面是否切到大转子；切下的骨里有多少在大转子一侧。"""
import json
import pathlib
import sys

import numpy as np
from scipy import ndimage

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import jobs as J  # noqa: E402
import post as P  # noqa: E402

fm0 = FR.build()
ref = J.intact_ref(2.0)
job = ref.get("intact_job")
print("intact job", job, "stored gruen7", ref.get("gruen7"), flush=True)
R = J.QROOT / job
for h in (25.0, 30.0, 35.0, 40.0):
    zs = P.zone_sed(R, "intact", fm0.with_cut(h))
    print(json.dumps({"h_cut": h, "gruen7_density": zs["gruen7"], "gruen7_vol_mm3": zs["gruen7_vol_mm3"],
                      "ratio_vs_25": zs["gruen7"] / ref["gruen7"]}), flush=True)

# 截骨面上的骨：连通块
for h in (30.0, 33.0, 35.0, 37.5, 40.0):
    fm = fm0.with_cut(h)
    e1 = fm.n3; e2 = np.cross(fm.u3, e1); e2 /= np.linalg.norm(e2)
    u = np.arange(-60, 60.01, 0.25)
    U, V = np.meshgrid(u, u)
    P3 = fm.C03 + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
    bone = (fm.outer_sdf(P3) <= 0).reshape(U.shape)
    lab, n = ndimage.label(bone)
    areas = sorted((float((lab == i).sum()) * 0.0625 for i in range(1, n + 1)), reverse=True)
    # 切下的骨（25 mm 与 h 之间的板层）里，离颈轴超过 25 mm（颈部最宽处约 18 mm）的部分 ≈ 大转子一侧
    nx, ny, nz = fm.sdf_o.shape
    gx = fm.g0[0] + (np.arange(nx) + 0.5) * fm.h; gy = fm.g0[1] + (np.arange(ny) + 0.5) * fm.h; gz = fm.g0[2] + (np.arange(nz) + 0.5) * fm.h
    Gx, Gy, Gz = np.meshgrid(gx, gy, gz, indexing="ij")
    D = np.stack([fm.H[0] - Gx, fm.H[1] - Gy, fm.H[2] - Gz], -1)
    t = D @ fm.u3
    rad = np.linalg.norm(D - t[..., None] * fm.u3, axis=-1)
    slab = (fm.sdf_o <= 0) & (t > 25.0) & (t <= h)
    far = slab & (rad > 25.0)
    print(json.dumps({"h_cut": h, "components_mm2": [round(a) for a in areas[:4]], "resected_mm3": round(float(slab.sum()) * fm.h ** 3),
                      "resected_far_from_neck_axis_mm3": round(float(far.sum()) * fm.h ** 3)}), flush=True)
