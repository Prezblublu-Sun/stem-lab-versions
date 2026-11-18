"""推导量定义：床支撑 F，和它是由什么组成的。从界面点云算，不用别的。

    python code/main.py <输入文件夹> <输出文件夹>

F = 对柄身界面节点里落在支撑区内的那些，求 面积 / max(泡沫厚度, 下限) 之和，单位 mm。
    泡沫厚度 t   = 柄面到髓腔壁的距离（点云里的 −d_canal）
    支撑区       = 从参考点沿颈轴往远端不超过 zeta_max，而且绕柄轴、从股骨距一侧量的角不超过 theta_max
    下限 t_floor = 厚度小于它的按它算，免得贴着皮质的几个节点把和撑爆

区的边界、参考点、颈轴这几个常数在 data/bed_f.json 里，是 Sawbones 3406 这根骨专用的：换一根骨要另登记一份定义。
算法和旧系统判定文件里的 mesh_F 逐行相同。

只给参照包那条（fea.reference）用：常数写在旧系统的模型坐标里，参照包交的点云也在那个坐标里。
fea.run 上有限元包交的点云在骨模型的坐标里，这里的常数对不上：那条路上的 job 带着骨模型，碰到就不算、说出原因。
fea.run 用照名字引用的那个定义（external/derive_bed_f_named）。
"""
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent


def bed_support(X, area, d_canal, collar, P0, ax, how: dict) -> dict:
    n3, cref = np.array(how["n3"], float), np.array(how["cref"], float)
    u = np.array(how["u_neck"], float)
    u = u / np.linalg.norm(u)
    body = ~collar
    X, w, t = X[body], area[body], -d_canal[body]
    q = X - P0
    rad = q - (q @ ax)[:, None] * ax
    em = n3 - (n3 @ ax) * ax
    em /= np.linalg.norm(em)
    ep = np.array([0.0, 1.0, 0.0]) - ax[1] * ax
    ep /= np.linalg.norm(ep)
    theta = np.degrees(np.arctan2(rad @ ep, rad @ em))
    inside = (-(X - cref) @ u <= how["zeta_max_mm"]) & (np.abs(theta) <= how["theta_max_deg"])
    count, total = int(inside.sum()), float(w[inside].sum())
    return {"F_mm": float((w[inside] / np.maximum(t[inside], how["t_floor_mm"])).sum()), "F_area_mm2": total, "F_n_nodes": count,
            "F_t_min_mm": float(t[inside].min()) if count else None,
            "F_frac_floor": float(w[inside][t[inside] < how["t_floor_mm"]].sum() / total) if total > 0 else None}


def main() -> int:
    source, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    job = json.loads((source / "job.json").read_text(encoding="utf-8"))
    if "bone_model" in job:             # fea.run 那条路上的 job 另带骨模型、柄的模型和推导量设定
        reason = ("这个定义只认参照包（fea.reference）交的点云：它的常数写在旧模型的坐标里。fea.run 上的点云在骨模型的坐标里，"
                  "要用照名字引用的那个定义（external/derive_bed_f_named）")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(f"床支撑 F 算不了：{reason}")
        (out / "result.json").write_text(json.dumps({"derived": None, "reason": reason}), encoding="utf-8")
        return 0
    where = pathlib.Path(job["fields"]["interface"])
    cloud = np.load(where if where.is_absolute() else source / where)
    how = json.loads((HERE.parent / "data" / "bed_f.json").read_text(encoding="utf-8"))
    axis = np.asarray(cloud["stem_axis"], float)
    derived = bed_support(np.asarray(cloud["X"], float), np.asarray(cloud["area"], float), np.asarray(cloud["d_canal"], float),
                          np.asarray(cloud["collar"], bool), np.asarray(cloud["P0"], float), axis / np.linalg.norm(axis), how)
    (out / "result.json").write_text(json.dumps({"derived": derived}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
