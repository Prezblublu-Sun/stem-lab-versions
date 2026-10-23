"""S1：把 Churun 的未切割 Sawbones 3406（左股骨，原生坐标 +z 向远端）烘焙成"右侧化"的 STEP 对，供 femur_3406.py 用。

变换只有一个：z 取反（S = diag(1, 1, −1)），不用 README 的 A 系（A 系把 y 也取反，+y 会变成前方；
femur_real.landmarks 假定右股骨、+y 后方：髁 = argmax(y)，前倾符号 = −(u·ey)，model3d_v2.load_vector 的符号也写死了 +y 后方）。
原生系 x 内侧、y 后方、z 远端（左股骨）；只翻 z ⇒ x 内侧、y 后方、z 近端，而且左→右镜像，正好是检测器的约定。

输出（v2/data/femur_3406/，STEP 本身被 .gitignore 排除，只提交校验和与来源说明）
    3406R_cortical.STEP, 3406R_cancellous.STEP, SHA256SUMS.txt, PROVENANCE.md
验收（与 2026-10-23 侦察在 gmsh 4.15.2 里验证过的数一致）
    体积 271 529 / 127 952 mm³（±0.01 %），面数 869 / 155，fragment(皮质, 松质) → 147 个共享面。
用法
    .venv-mobo/Scripts/python.exe v2/tools/bake_3406.py [--src DIR] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
V2 = HERE.parent
OUT = V2 / "data" / "femur_3406"
SRC_DEFAULT = pathlib.Path(r"H:/projects/application/research-log/sawbone_3406_2026-10-23/churun_uncut_export")
FILES = {"cortical": ("Cortical_AP214.STEP", "3406R_cortical.STEP"), "cancellous": ("Cancellou_AP214.STEP", "3406R_cancellous.STEP")}
MIRROR_Z = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0]        # 3×4 行优先：diag(1, 1, −1)
EXPECT = {"cortical": {"mm3": 271529.0, "faces": 869}, "cancellous": {"mm3": 127952.0, "faces": 155}, "shared_faces": 147}
VOL_TOL = 1e-4                                                                  # ±0.01 %


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def _session():
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("General.NumThreads", 1)
    return gmsh


def bake_one(src: pathlib.Path, dst: pathlib.Path) -> dict:
    """导入 → 只翻 z → 写 STEP。返回原生与镜像后的体积、面数。"""
    gmsh = _session()
    try:
        occ = gmsh.model.occ
        V = [x for x in occ.importShapes(str(src)) if x[0] == 3]
        occ.synchronize()
        if len(V) != 1:
            raise RuntimeError(f"{src.name}: expected 1 volume, got {len(V)}")
        native = {"mm3": occ.getMass(*V[0]), "faces": len([t for d, t in gmsh.model.getBoundary(V, oriented=False) if d == 2]),
                  "bbox": list(gmsh.model.getBoundingBox(*V[0]))}
        occ.affineTransform(V, MIRROR_Z)
        occ.synchronize()
        mirrored = {"mm3": occ.getMass(*V[0]), "faces": len([t for d, t in gmsh.model.getBoundary(V, oriented=False) if d == 2]),
                    "bbox": list(gmsh.model.getBoundingBox(*V[0]))}
        t0 = time.time()
        tmp = dst.with_name(dst.stem + "_tmp.step")                     # gmsh 只认小写扩展名；写完改名为 .STEP（Windows 不分大小写，所以先用别的名字）
        gmsh.write(str(tmp))
        tmp.replace(dst)
        mirrored["write_s"] = round(time.time() - t0, 1)
    finally:
        gmsh.finalize()
    return {"native": native, "mirrored": mirrored}


def verify(paths: dict) -> dict:
    """重新导入两件：体积、面数；fragment 后的共享面数与体积（共形界面的证据）。"""
    gmsh = _session()
    try:
        occ = gmsh.model.occ
        C = [x for x in occ.importShapes(str(paths["cortical"])) if x[0] == 3]
        K = [x for x in occ.importShapes(str(paths["cancellous"])) if x[0] == 3]
        occ.synchronize()
        out = {}
        for k, V in (("cortical", C), ("cancellous", K)):
            if len(V) != 1:
                raise RuntimeError(f"{k}: re-import gives {len(V)} volumes")
            out[k] = {"mm3": occ.getMass(*V[0]), "faces": len([t for d, t in gmsh.model.getBoundary(V, oriented=False) if d == 2]),
                      "bbox": list(gmsh.model.getBoundingBox(*V[0]))}
        t0 = time.time()
        frag, fmap = occ.fragment(C, K)
        occ.synchronize()
        fc = {t for dt in fmap[:len(C)] for d, t in dt if d == 3}
        fk = {t for dt in fmap[len(C):] for d, t in dt if d == 3}
        bc = {t for d, t in gmsh.model.getBoundary([(3, v) for v in fc], oriented=False) if d == 2}
        bk = {t for d, t in gmsh.model.getBoundary([(3, v) for v in fk], oriented=False) if d == 2}
        out["fragment"] = {"cortex_vols": len(fc), "core_vols": len(fk), "shared_faces": len(bc & bk), "core_faces": len(bk),
                           "cortex_mm3_after": sum(occ.getMass(3, t) for t in fc), "core_mm3_after": sum(occ.getMass(3, t) for t in fk),
                           "fragment_s": round(time.time() - t0, 1)}
    finally:
        gmsh.finalize()
    return out


def accept(v: dict) -> list[str]:
    bad = []
    for k in ("cortical", "cancellous"):
        e = EXPECT[k]
        if abs(v[k]["mm3"] - e["mm3"]) > VOL_TOL * e["mm3"]:
            bad.append(f"{k} volume {v[k]['mm3']:.1f} vs {e['mm3']:.0f} (tol ±{VOL_TOL * 100:.2f} %)")
        if v[k]["faces"] != e["faces"]:
            bad.append(f"{k} faces {v[k]['faces']} vs {e['faces']}")
        if v[k]["bbox"][5] < 100 or v[k]["bbox"][2] > -100 and k == "cortical":
            bad.append(f"{k} z range {v[k]['bbox'][2]:.1f}..{v[k]['bbox'][5]:.1f}: head should be at +z (proximal) after mirroring")
    f = v["fragment"]
    if f["cortex_vols"] != 1 or f["core_vols"] != 1:
        bad.append(f"fragment gives {f['cortex_vols']} cortex / {f['core_vols']} core volumes")
    if f["shared_faces"] != EXPECT["shared_faces"]:
        bad.append(f"shared faces {f['shared_faces']} vs {EXPECT['shared_faces']}")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=pathlib.Path, default=SRC_DEFAULT)
    ap.add_argument("--force", action="store_true", help="overwrite existing baked files")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    paths = {k: OUT / dst for k, (_, dst) in FILES.items()}
    if all(p.exists() for p in paths.values()) and not a.force:
        print("baked files exist; use --force to re-bake:", *paths.values(), sep="\n  ")
        return 0
    rep = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "gmsh": None, "source_dir": str(a.src), "transform": "diag(1, 1, -1) (z -> -z only)",
           "bodies": {}}
    import gmsh
    rep["gmsh"] = gmsh.__version__
    for k, (s, _) in FILES.items():
        src = a.src / s
        rep["bodies"][k] = {"source": str(src), "source_sha256": sha256(src), **bake_one(src, paths[k]), "output": str(paths[k])}
        print(k, json.dumps({kk: vv for kk, vv in rep["bodies"][k].items() if kk in ("native", "mirrored")}, default=float))
    rep["verify"] = verify(paths)
    rep["accept_errors"] = accept(rep["verify"])
    rep["output_sha256"] = {k: sha256(p) for k, p in paths.items()}
    (OUT / "bake_report.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    print(json.dumps(rep["verify"], indent=1, default=float))
    if rep["accept_errors"]:
        print("NOT ACCEPTED:", *rep["accept_errors"], sep="\n  ")
        return 1
    (OUT / "SHA256SUMS.txt").write_text("".join(f"{rep['output_sha256'][k]} *{paths[k].name}\n" for k in FILES)
                                        + f"source: {a.src} (Churun uncut 3406, SolidWorks 2025 AP214 export 2026-10-23); transform diag(1,1,-1)\n",
                                        encoding="utf-8")
    prov = f"""# v2/data/femur_3406 来源与变换（烘焙于 {rep['date']}，gmsh {rep['gmsh']}）

| 输出 | 来源 | 来源 SHA256 | 输出 SHA256 |
|---|---|---|---|
""" + "".join(f"| `{paths[k].name}` | `{rep['bodies'][k]['source']}` | `{rep['bodies'][k]['source_sha256']}` | `{rep['output_sha256'][k]}` |\n" for k in FILES) + f"""
- 来源：Churun Lin 的未切割 Sawbones 3406（左股骨）Parasolid → 本机 SolidWorks 2025 转 STEP AP214（2026-10-23，见
  `H:/projects/application/research-log/sawbone_3406_2026-10-23/README_3406模型来源与核对_2026-10-23.md` 与 `churun_uncut_export/convert_log.txt`）。
- 变换：**只把 z 取反**，S = diag(1, 1, −1)，用 `gmsh.model.occ.affineTransform`；原生系 x 内侧、y 后方、z 远端（左股骨）
  ⇒ 烘焙后 x 内侧、y 后方、z 近端，并且左→右镜像。
- 为什么不用 README 的 A 系（x, −y, −z）：A 系是绕 x 转 180°，保持左股骨手性、+y 变成前方。计入哈希的代码假定
  右股骨且 +y 后方：`femur_real.landmarks` 取 argmax(y) 为后髁、前倾角符号 = −(u·ey)、`RealFemur.ant = (0, −1, 0)`，
  `model3d_v2.load_vector` 的 Bergmann → 模型符号也写死了 +y 后方（model3d_m1 按名导入同一函数）。A 系会让髁检测和载荷符号都错。
- 验收（重新导入）：皮质 {rep['verify']['cortical']['mm3']:.1f} mm³ / {rep['verify']['cortical']['faces']} 面，
  松质 {rep['verify']['cancellous']['mm3']:.1f} mm³ / {rep['verify']['cancellous']['faces']} 面；
  fragment(皮质, 松质) → 共享面 {rep['verify']['fragment']['shared_faces']} 个（松质 {rep['verify']['fragment']['core_faces']} 面中），
  体积不变（{rep['verify']['fragment']['cortex_mm3_after']:.1f} / {rep['verify']['fragment']['core_mm3_after']:.1f} mm³）。
  目标：271 529 / 127 952 mm³（±0.01 %）、869 / 155 面、147 个共享面。
- 原生体积：皮质 {rep['bodies']['cortical']['native']['mm3']:.1f}，松质 {rep['bodies']['cancellous']['native']['mm3']:.1f} mm³
  （gmsh 对裁剪 B 样条体积偏低约 4 %，与 SolidWorks 的 271.5 / 127.9 cm³ 一致）。
- 皮质壳是**开放**的（远端横销孔连通髓腔），无封闭的内膜空腔；松质芯（含头、颈）与皮质在同一坐标系，界面共形。
- 数据不进 git（`.gitignore: v2/data/**/*.STEP`）；校验和在 `SHA256SUMS.txt`，`femur_3406.py` 的配置里也写死同样的 SHA256。
- 完整报告：`bake_report.json`。
"""
    (OUT / "PROVENANCE.md").write_text(prov, encoding="utf-8")
    print("ACCEPTED ->", OUT)
    for k, p in paths.items():
        print(f"  sha256_{k}: {rep['output_sha256'][k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
