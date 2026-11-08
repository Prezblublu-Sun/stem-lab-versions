"""骨在柄骨界面附近加密（规格键 foam_refine，F5，五天计划，用户 2026-11-08"整份批准"）。

    spec["foam_refine"] = {"h": mm, "dist_min": mm, "dist_max": mm}   h 必填；dist_min 默认 1.5，dist_max 默认 4.0
        h          界面附近骨里的单元尺寸，0.3 ≤ h < h_int
        dist_min   离柄骨界面这么近的骨都用 h
        dist_max   到这里长回 h_int（之外仍是生产的尺寸场）

为什么：3406 的松质骨是泡沫，柄和皮质之间的泡沫层常只有 1 mm 上下，h 2.0 时层里只有一层单元，微动和接触可能没收敛。
做法：只替换本建模进程里 model3d_m1._size_field（model3d_m1 从 model3d_v2 按名字导入，调用时按模块全局名查）。新函数先调原函数，
生产的 Distance / Threshold 一个不改；再加一个只看柄骨界面的 Distance、一个 Threshold（h 到 h_int）、一个 Restrict（只在皮质和松质体里），
背景场换成两者的 Min。所以界面附近的骨不会比生产网格粗，离界面 dist_max 以外和柄里面跟生产完全一样。不改 model3d_m1.py、model3d_v2.py。
柄骨界面 = 柄体的边界面里同时是皮质体或松质体边界的那些面（fragment 之后是同一个面）。找不到界面面 → 抛错，prep 记 L3。
记录：参数、界面面数、加的场号，进 prep.json 的 foam_refine；单元数在 model3d.json 里本来就有。
局限：只加密骨这一侧；柄那一侧在界面面上跟着变细，往里按 gmsh 的梯度长回去，所以柄里也比生产网格细（玩具模型 h 0.5：柄里离表面
4.5 mm 处 1.25 mm，生产 3.8 mm；不加 Restrict 时是 0.7 mm）。单元数涨得多（玩具模型 h 0.5 是生产的 18 倍），真实模型的量要在 Linux 冒烟里实测。
重试时 h_int 变成 0.97 倍（model3d_m1.build），h 不变。dist_max 处加密场给 h_int，再往外是生产的场（4 mm 处约 3 mm），所以有一个台阶，
1.5 到 4 mm 这一带都比生产网格细。
钩子是进程级的：jobs.prep 建完一定调 uninstall() 还原，免得同一进程里后面的作业（比如 ccx_port 的循环）继承加密。
"""
from __future__ import annotations

KEYS = ("h", "dist_min", "dist_max")
DEFAULTS = {"dist_min": 1.5, "dist_max": 4.0}
BONE_GROUPS = ("cortex", "cancellous")
INFO: dict = {}


def unsupported(spec: dict) -> str | None:
    """jobs.prep 在建模前问：这个作业能不能用 foam_refine。只有柄的建模（kind design / variant）可以；不能 → 原因。"""
    k = spec.get("kind")
    return None if k in ("design", "variant") else f"foam_refine is only for design / variant jobs, not kind {k!r}"


def validate(fr: dict, h_int: float) -> dict:
    """补默认值后的参数；不合法 → ValueError。"""
    if not isinstance(fr, dict) or set(fr) - set(KEYS) or "h" not in fr or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in fr.values()):
        raise ValueError(f"foam_refine must be a dict with 'h' and optional 'dist_min', 'dist_max' (numbers), got {fr!r}")
    p = {**DEFAULTS, **{k: float(v) for k, v in fr.items()}}
    if not (0.3 <= p["h"] < float(h_int)):
        raise ValueError(f"foam_refine h {p['h']:g} must be in [0.3, h_int {h_int:g})")
    if not (0.0 <= p["dist_min"] < p["dist_max"] <= 10.0):
        raise ValueError(f"foam_refine needs 0 <= dist_min < dist_max <= 10, got {p['dist_min']:g}, {p['dist_max']:g}")
    return p


def interface_surfaces(gmsh, stem_surfs) -> tuple:
    """(柄骨界面面, 骨体)：柄体边界面里同时是骨体边界的面。"""
    names = {gmsh.model.getPhysicalName(3, t): t for _, t in gmsh.model.getPhysicalGroups(3)}
    missing = [g for g in BONE_GROUPS if g not in names]
    if missing:
        raise RuntimeError(f"foam_refine: physical groups {missing} not defined before the size field")
    bone_vols = sorted({int(v) for g in BONE_GROUPS for v in gmsh.model.getEntitiesForPhysicalGroup(3, names[g])})
    bone_surfs = {t for v in bone_vols for d, t in gmsh.model.getBoundary([(3, v)], oriented=False) if d == 2}
    return sorted(set(int(s) for s in stem_surfs) & {abs(int(t)) for t in bone_surfs}), bone_vols


def make_size_field(orig, p: dict):
    """包住生产的 _size_field：先建生产的场，再把背景场换成 Min(生产, 界面加密)。"""
    def size_field(gmsh, surfs, cfg, h_int, h_far):
        F = gmsh.model.mesh.field
        before = set(F.list())
        orig(gmsh, surfs, cfg, h_int, h_far)
        made = sorted(set(F.list()) - before)
        thr = [t for t in made if F.getType(t) == "Threshold"]
        if len(thr) != 1:
            raise RuntimeError(f"foam_refine: expected one Threshold from the production size field, got fields {made}")
        iface, bone_vols = interface_surfaces(gmsh, surfs)
        if not iface:
            raise RuntimeError("foam_refine: no stem-bone interface surface found")
        fd = F.add("Distance")
        F.setNumbers(fd, "SurfacesList", iface)
        ft = F.add("Threshold")
        for k, v in (("InField", fd), ("SizeMin", p["h"]), ("SizeMax", float(h_int)), ("DistMin", p["dist_min"]), ("DistMax", p["dist_max"]),
                     ("StopAtDistMax", 1)):                     # dist_max 以外不给尺寸，Min 取生产的场（不加这个，整块骨会被压到 h_int）
            F.setNumber(ft, k, v)
        fr_ = F.add("Restrict")
        F.setNumber(fr_, "InField", ft)
        F.setNumbers(fr_, "VolumesList", bone_vols)
        fm_ = F.add("Min")
        F.setNumbers(fm_, "FieldsList", [thr[0], fr_])
        F.setAsBackgroundMesh(fm_)
        INFO.clear()
        INFO.update({**p, "h_int_at_build": float(h_int), "n_interface_surfaces": len(iface), "n_bone_volumes": len(bone_vols),
                     "fields": {k: int(v) for k, v in (("production_threshold", thr[0]), ("distance", fd), ("threshold", ft), ("restrict", fr_), ("min", fm_))}})
    return size_field


def install(fr: dict, h_int: float) -> dict:
    """只替换本建模进程的 model3d_m1._size_field。返回补了默认值的参数。"""
    import model3d_m1 as M1
    p = validate(fr, h_int)
    orig = getattr(M1._size_field, "_foam_orig", M1._size_field)
    new = make_size_field(orig, p)
    new._foam_orig = orig
    M1._size_field = new
    INFO.clear()
    return p


def uninstall() -> None:
    """还原 model3d_m1._size_field（没装过 = 什么都不做）。"""
    import model3d_m1 as M1
    orig = getattr(M1._size_field, "_foam_orig", None)
    if orig is not None:
        M1._size_field = orig
