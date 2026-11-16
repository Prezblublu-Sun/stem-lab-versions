"""【自由】CT 骨源的重建：参考外形变成实心掩膜，照 CT 值分出皮质和内部，出外表面和内壁两个封闭表面。

做法是 2026-11 的第二版流程（《单根股骨建模流程详解》的第 1 到 15 步），默认的参数也是那一版的：
    1      参考外形只留最外层的一个表面
    2      选 CT、定坐标约定：外形原样、x z 取反、x y 取反，三种里和 CT 重合最多的；重合不到 0.8 就不做
    3      在外形周围截取 CT，重采样成各向同性的体素（默认 0.7 mm，每边外扩 6 mm）
    4      外形变成实心掩膜
    5      皮质候选：掩膜以内、CT 值不低于阈值（默认 500 HU）
    6      两端限深：离外表面比上限更深的不算皮质。上限沿骨长变，骨干不限
    7      皮质闭运算
    8-11   内部 = 股骨 − 皮质；开运算；取最大块；闭运算，填洞
    12     比上限深的并回内部
    13     最小壁厚：内部只能落在“股骨向内收 N 个体素”的范围里（默认 2 个体素，即 1.4 mm）
    14     再取最大块，就是内部（松质和髓腔）；皮质 = 股骨 − 内部
    15     两个掩膜各自高斯平滑、取等值面、网格平滑、只留最大块、减面

分骨不在这里自动做。没有参考外形时，靠阈值和形态学把股骨和骨盆、胫骨分开，2026-11 实测 12 例全部失败。
所以 CT 骨源要带一份股骨的外形：人工描的，或者别的软件分割出来的表面。

重建设定里和这里有关的项：
    source   {"outer": 外形的文件（STL 或 PLY）, "ct": CT 的文件}。ct 可以不写：骨源里的体数据文件都算候选；也可以写一组
    ct       以下各项都可以不写，不写就是 DEFAULTS 里的值
             voxel_mm、margin_mm、cortical_hu、depth_cap（[[位置, 上限毫米], ...]，位置 0 是远端、1 是近端；写 null 就不限深）、
             min_wall_voxels、outer_sigma_mm、inner_sigma_mm、relax、triangles、
             proximal（auto、high_z、low_z：近端在 z 大的一头还是小的一头，auto 是照外形判断）
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

DEFAULTS = {
    "voxel_mm": 0.7, "margin_mm": 6.0, "cortical_hu": 500.0,
    "depth_cap": [[0.00, 3.0], [0.10, 3.0], [0.22, 60.0], [0.72, 60.0], [0.85, 5.0], [1.00, 5.0]],
    "min_wall_voxels": 2, "outer_sigma_mm": 0.7, "inner_sigma_mm": 1.2, "relax": 20, "triangles": 120000, "proximal": "auto",
}
VOLUMES = (".nrrd", ".nii", ".gz", ".mha", ".mhd")
SHAPES = (".stl", ".ply")
FLIPS = ((1, 1, 1), (-1, 1, -1), (-1, -1, 1))       # 原样；x z 取反（上下颠倒存放的 CT）；x y 取反（两种病人坐标系的差别）
ENDS = ("auto", "high_z", "low_z")

# run 量出来、写进候选清单的数。说的都是 CT 这一步：体素、掩膜、平滑之后还没重划的细表面。
# 定稿不重做这一步，所以定稿时照抄这几样（rebuild.finalize）；不在这里的数，定稿量不出来就是没有，不沿用候选的
MEASURES = (
    "ct_file", "ct_overlap", "ct_flip", "ct_spacing_mm", "ct_voxels_million", "reference_groups", "reference_volume_mm3",
    "femur_mask_mm3", "hu_inside_mean", "hu_inside_p95", "surface_on_bone_share", "cortex_by_threshold_mm3",
    "proximal_end", "end_slices", "long_axis_tilt_deg", "cortex_removed_by_depth_mm3",
    "cortex_mask_mm3", "interior_mask_mm3", "cortex_added_by_rules_share",
    *(f"{side}_fine_{what}" for side in ("outer", "inner") for what in ("triangles", "bad_edges", "regions", "volume_mm3")),
    "outer_vs_reference_mean_mm", "outer_vs_reference_p95_mm",
    "wall_fine_min_mm", "wall_fine_p05_mm", "wall_fine_median_mm", "wall_fine_max_mm",
    "length_mm", "isthmus_canal_diameter_mm", "isthmus_outer_diameter_mm", "isthmus_cortex_index", "isthmus_position",
)


def options(setting: dict) -> dict:
    return {**DEFAULTS, **(setting.get("ct") or {})}


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def volumes(folder: Path, named=None) -> list[Path]:
    """骨源里的 CT 候选。named 给了（一个名字或一组）就是它们；不给就是骨源里所有体数据文件，分割标签（.seg.nrrd）不算。"""
    folder = Path(folder)
    if named is not None:
        return [folder / str(name) for name in ([named] if isinstance(named, str) else list(named))]
    return sorted(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in VOLUMES
                  and not path.name.lower().endswith(".seg.nrrd") and not path.name.lower().endswith(".tar.gz"))


def problems(folder: Path, setting: dict) -> list[str]:
    """CT 骨源和重建设定里 CT 那几项对不对。返回哪里不对；空列表就是对的。只读，不打开体数据。"""
    files = setting.get("source")
    if not isinstance(files, dict) or not isinstance(files.get("outer"), str):
        return ["这份骨源是 CT：重建设定的 source 要写 outer（股骨外形的文件，STL 或 PLY），ct 可以另写。"
                "只有 CT、没有外形的，这里不重建：自动分骨靠不住"]
    found = []
    outer = Path(folder) / files["outer"]
    if outer.suffix.lower() not in SHAPES or not outer.is_file():
        found.append(f"CT 骨源里没有重建设定说的外形文件，或者它不是 STL、PLY：{files['outer']}")
    named = files.get("ct")
    if named is not None and not (isinstance(named, str) or (isinstance(named, list) and named and all(isinstance(one, str) for one in named))):
        found.append("重建设定的 source.ct 要写 CT 文件的名字，或者一组名字")
    else:
        listed = volumes(folder, named)
        missing = [path.name for path in listed if not path.exists()]
        if missing or not listed:
            found.append(f"CT 骨源里没有这几个 CT 文件：{missing}" if missing else
                         "CT 骨源里没有找到体数据文件（nrrd、nii、mha）。一组 DICOM 这里不直接读：先转成一个 nrrd（比如用 3D Slicer 导出）")
    from plugins.recon import solids

    chosen = setting.get("ct") or {}
    known = sorted({*DEFAULTS, *solids.DEFAULTS})               # 出表面的这几项在这里，变成实体的那几项在 solids.py 里
    if not isinstance(chosen, dict) or any(name not in known for name in chosen):
        return found + [f"重建设定的 ct 里只有这几项：{known}"]
    how = options(setting)
    if not _number(how["voxel_mm"]) or not 0.2 <= how["voxel_mm"] <= 2.0:
        found.append("ct.voxel_mm 要在 0.2 和 2 之间")
    if not _number(how["margin_mm"]) or not 2 * how["voxel_mm"] <= how["margin_mm"] <= 50:
        found.append("ct.margin_mm 至少要有两个体素宽，不超过 50")
    if not _number(how["cortical_hu"]):
        found.append("ct.cortical_hu 必须是一个数")
    knots = how["depth_cap"]
    if knots is not None and (not isinstance(knots, list) or len(knots) < 2 or not all(
            isinstance(knot, list) and len(knot) == 2 and _number(knot[0]) and _number(knot[1]) and knot[1] >= 0 for knot in knots)
            or [knot[0] for knot in knots] != sorted(knot[0] for knot in knots) or knots[0][0] != 0 or knots[-1][0] != 1):
        found.append("ct.depth_cap 要写成 [[位置, 上限毫米], ...]：位置从 0（远端）排到 1（近端）；不限深就写 null")
    for name, low, high in (("min_wall_voxels", 1, 10), ("relax", 0, 200), ("triangles", 1000, 5_000_000)):
        if isinstance(how[name], bool) or not isinstance(how[name], int) or not low <= how[name] <= high:
            found.append(f"ct.{name} 要是 {low} 到 {high} 之间的整数")
    for name in ("outer_sigma_mm", "inner_sigma_mm"):
        if not _number(how[name]) or not 0 < how[name] <= 5:
            found.append(f"ct.{name} 要在 0 和 5 之间")
    if how["proximal"] not in ENDS:
        found.append(f"ct.proximal 只有 {list(ENDS)}")
    return found


# ---------------------------------------------------------------- 表面（VTK）

_loaded: dict = {}


def toolkit():
    """用得到的那八个 VTK 模块，合成一个名字空间。

    不写 import vtk：那会把一百多个模块连同渲染的全装进来，慢；其中任何一个装不上（没有显示的机器上、
    安全软件还占着文件的时候），整个就用不了。这里用不到渲染。
    """
    if not _loaded:
        from types import SimpleNamespace

        from vtkmodules import (vtkCommonCore, vtkCommonDataModel, vtkCommonTransforms, vtkFiltersCore, vtkFiltersGeneral,
                                vtkImagingStencil, vtkIOGeometry, vtkIOPLY)

        names = {}
        for module in (vtkCommonCore, vtkCommonDataModel, vtkCommonTransforms, vtkFiltersCore, vtkFiltersGeneral,
                       vtkImagingStencil, vtkIOGeometry, vtkIOPLY):
            names.update({name: value for name, value in vars(module).items() if not name.startswith("_")})
        _loaded["vtk"] = SimpleNamespace(**names)
    return _loaded["vtk"]


def read_shape(path):
    vtk = toolkit()

    reader = vtk.vtkSTLReader() if str(path).lower().endswith(".stl") else vtk.vtkPLYReader()
    reader.SetFileName(str(path))
    reader.Update()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(reader.GetOutputPort())
    clean.Update()
    triangles = vtk.vtkTriangleFilter()
    triangles.SetInputConnection(clean.GetOutputPort())
    triangles.Update()
    return triangles.GetOutput()


def outer_only(shape) -> tuple:
    """只留包围盒最大的那一组相连的面片：有的模型里还带着内表面和碎片。返回（表面，原来有几组）。"""
    vtk = toolkit()

    groups = vtk.vtkPolyDataConnectivityFilter()
    groups.SetInputData(shape)
    groups.SetExtractionModeToAllRegions()
    groups.Update()
    count = groups.GetNumberOfExtractedRegions()
    if count <= 1:
        return shape, 1
    best, largest = None, -1.0
    for number in range(count):
        one = vtk.vtkPolyDataConnectivityFilter()
        one.SetInputData(shape)
        one.SetExtractionModeToSpecifiedRegions()
        one.AddSpecifiedRegion(number)
        one.Update()
        clean = vtk.vtkCleanPolyData()
        clean.SetInputConnection(one.GetOutputPort())
        clean.Update()
        box = clean.GetOutput().GetBounds()
        size = (box[1] - box[0]) * (box[3] - box[2]) * (box[5] - box[4])
        if size > largest:
            best, largest = clean.GetOutput(), size
    return best, count


def flipped(shape, signs):
    vtk = toolkit()

    move = vtk.vtkTransform()
    move.Scale(*signs)
    done = vtk.vtkTransformPolyDataFilter()
    done.SetTransform(move)
    done.SetInputData(shape)
    done.Update()
    return done.GetOutput()


def points_of(shape) -> np.ndarray:
    from vtkmodules.util.numpy_support import vtk_to_numpy

    return vtk_to_numpy(shape.GetPoints().GetData()).astype(float)


def triangles_of(shape) -> np.ndarray:
    from vtkmodules.util.numpy_support import vtk_to_numpy

    return vtk_to_numpy(shape.GetPolys().GetData()).reshape(-1, 4)[:, 1:].astype(np.int64)


def described(shape) -> dict:
    """一个表面的几样数：三角形数、开放边和非流形边的条数、相连的块数、围出的体积。"""
    vtk = toolkit()

    edges = vtk.vtkFeatureEdges()
    edges.SetInputData(shape)
    edges.BoundaryEdgesOn()
    edges.NonManifoldEdgesOn()
    edges.FeatureEdgesOff()
    edges.ManifoldEdgesOff()
    edges.Update()
    groups = vtk.vtkPolyDataConnectivityFilter()
    groups.SetInputData(shape)
    groups.SetExtractionModeToAllRegions()
    groups.Update()
    mass = vtk.vtkMassProperties()
    mass.SetInputData(shape)
    mass.Update()
    return {"triangles": int(shape.GetNumberOfCells()), "bad_edges": int(edges.GetOutput().GetNumberOfCells()),
            "regions": int(groups.GetNumberOfExtractedRegions()), "volume_mm3": float(abs(mass.GetVolume()))}


def distances(source, target, count: int = 30000) -> np.ndarray:
    """source 上的点（最多取 count 个）到 target 表面的距离。"""
    vtk = toolkit()

    locator = vtk.vtkCellLocator()
    locator.SetDataSet(target)
    locator.BuildLocator()
    points = points_of(source)
    points = points[:: max(1, len(points) // count)]
    found = np.zeros(len(points))
    closest, cell, sub, squared = [0.0, 0.0, 0.0], vtk.mutable(0), vtk.mutable(0), vtk.mutable(0.0)
    for index, point in enumerate(points):
        locator.FindClosestPoint(point.tolist(), closest, cell, sub, squared)
        found[index] = squared.get() ** 0.5
    return found


def write_stl(shape, path: Path) -> None:
    vtk = toolkit()

    writer = vtk.vtkSTLWriter()
    writer.SetFileTypeToBinary()
    writer.SetFileName(str(path))
    writer.SetInputData(shape)
    writer.Write()


# ---------------------------------------------------------------- CT 和掩膜（SimpleITK）

def box_of(path: Path) -> list:
    """一份 CT 在它自己的坐标系里占的范围：每个方向（最小，最大）。只读文件头。"""
    import SimpleITK as sitk

    reader = sitk.ImageFileReader()
    reader.SetFileName(str(path))
    reader.ReadImageInformation()
    origin, spacing, size, turn = reader.GetOrigin(), reader.GetSpacing(), reader.GetSize(), reader.GetDirection()
    end = [origin[i] + sum(turn[3 * i + j] * (size[j] - 1) * spacing[j] for j in range(3)) for i in range(3)]
    return [(min(a, b), max(a, b)) for a, b in zip(origin, end)]


def choose(shape, paths: list) -> tuple:
    """装得下这根股骨的最小的那份 CT，和外形要用的坐标约定。返回（CT 的文件，三个方向的正负号，重合的比例）。"""
    bounds = shape.GetBounds()
    best = (0.0, None, None)
    for path in sorted(paths, key=lambda one: one.stat().st_size):
        box = box_of(path)
        for signs in FLIPS:
            share = 1.0
            for k in range(3):
                low, high = sorted((bounds[2 * k] * signs[k], bounds[2 * k + 1] * signs[k]))
                share *= max(0.0, min(high, box[k][1]) - max(low, box[k][0])) / max(high - low, 1e-6)
            if share > best[0] + 1e-6:
                best = (share, path, signs)
    if best[0] < 0.8:
        raise ValueError(f"没有一份 CT 装得下这个外形：试过三种坐标约定，重合最多的只有 {best[0]:.2f}。外形和 CT 不是同一次扫描的，或者坐标系对不上")
    return best[1], best[2], round(best[0], 3)


def rasterize(shape, origin, size, voxel: float):
    """表面围住的体素标 1。"""
    import SimpleITK as sitk
    vtk = toolkit()
    from vtkmodules.util.numpy_support import vtk_to_numpy

    image = vtk.vtkImageData()
    image.SetSpacing(voxel, voxel, voxel)
    image.SetOrigin(*origin)
    image.SetDimensions(*size)
    image.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    image.GetPointData().GetScalars().Fill(1)
    stencil = vtk.vtkPolyDataToImageStencil()
    stencil.SetInputData(shape)
    stencil.SetOutputOrigin(*origin)
    stencil.SetOutputSpacing(voxel, voxel, voxel)
    stencil.SetOutputWholeExtent(image.GetExtent())
    stencil.Update()
    cut = vtk.vtkImageStencil()
    cut.SetInputData(image)
    cut.SetStencilConnection(stencil.GetOutputPort())
    cut.ReverseStencilOff()
    cut.SetBackgroundValue(0)
    cut.Update()
    array = vtk_to_numpy(cut.GetOutput().GetPointData().GetScalars()).reshape(size[2], size[1], size[0]).copy()
    mask = sitk.GetImageFromArray(array)
    mask.SetOrigin(origin)
    mask.SetSpacing((voxel, voxel, voxel))
    return mask


def fill_solid(mask):
    """把里面可能剩下的空隙填上：先三维填洞，再逐层填洞。"""
    import SimpleITK as sitk

    array = sitk.GetArrayFromImage(sitk.BinaryFillhole(mask))
    for k in range(array.shape[0]):
        if array[k].any():
            array[k] = sitk.GetArrayFromImage(sitk.BinaryFillhole(sitk.GetImageFromArray(array[k])))
    filled = sitk.GetImageFromArray(array)
    filled.CopyInformation(mask)
    return filled


def largest(mask):
    import SimpleITK as sitk

    return sitk.RelabelComponent(sitk.ConnectedComponent(mask), sortByObjectSize=True) == 1


def to_surface(mask, sigma: float, relax: int, target: int):
    """掩膜变成封闭的三角形表面：高斯平滑，在 0.5 处取等值面，网格平滑，只留最大的一块，减面到 target 个三角形。"""
    import SimpleITK as sitk
    vtk = toolkit()
    from vtkmodules.util.numpy_support import numpy_to_vtk

    soft = sitk.SmoothingRecursiveGaussian(sitk.Cast(sitk.ConstantPad(mask, (2, 2, 2), (2, 2, 2), 0), sitk.sitkFloat32), sigma)
    image = vtk.vtkImageData()
    image.SetDimensions(*soft.GetSize())
    image.SetSpacing(*soft.GetSpacing())
    image.SetOrigin(*soft.GetOrigin())
    image.GetPointData().SetScalars(numpy_to_vtk(sitk.GetArrayViewFromImage(soft).ravel(), deep=True))
    level = vtk.vtkFlyingEdges3D()
    level.SetInputData(image)
    level.SetValue(0, 0.5)
    level.Update()
    smooth = vtk.vtkWindowedSincPolyDataFilter()
    smooth.SetInputConnection(level.GetOutputPort())
    smooth.SetNumberOfIterations(relax)
    smooth.SetPassBand(0.1)
    smooth.NonManifoldSmoothingOn()
    smooth.NormalizeCoordinatesOn()
    smooth.Update()
    groups = vtk.vtkPolyDataConnectivityFilter()
    groups.SetInputConnection(smooth.GetOutputPort())
    groups.SetExtractionModeToLargestRegion()
    groups.Update()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(groups.GetOutputPort())
    clean.Update()
    surface = clean.GetOutput()
    if surface.GetNumberOfCells() > target:
        fewer = vtk.vtkQuadricDecimation()
        fewer.SetInputData(surface)
        fewer.SetTargetReduction(1 - target / surface.GetNumberOfCells())
        fewer.Update()
        surface = fewer.GetOutput()
    return surface


def _end_slices(solid: np.ndarray, voxel: float) -> dict:
    """两头各向里 6 mm 的那一层：有几块、最大的一块有多圆。股骨头那一头是一个圆块。"""
    import SimpleITK as sitk

    used = np.where(solid.any(axis=(1, 2)))[0]
    seen = {}
    for name, k in (("low_z", used.min() + int(6 / voxel)), ("high_z", used.max() - int(6 / voxel))):
        labels = sitk.ConnectedComponent(sitk.GetImageFromArray(solid[k].astype(np.uint8)))
        shape = sitk.LabelShapeStatisticsImageFilter()
        shape.Execute(labels)
        big = max(shape.GetLabels(), key=shape.GetPhysicalSize) if shape.GetNumberOfLabels() else None
        seen[name] = {"blobs": int(shape.GetNumberOfLabels()), "roundness": round(float(shape.GetRoundness(big)), 3) if big else 0.0}
    return seen


def _proximal(how: dict, shape, ends: dict) -> tuple:
    """近端在 z 大的一头还是小的一头。返回（high_z 或 low_z，另一种看法的结果，骨的长轴和 z 方向的夹角）。

    auto 照外形的三角网判断（landmarks.lengthwise）：股骨头的顶截出来是一个圆，髁截出来不是；两头差不多圆时看哪一头
    的点离长轴更远。2026-11 那一批 162 根上都对。另一种独立的看法是掩膜上两头各向里 6 mm 的那一层哪个更圆，
    只在它分得清的时候（两头的圆度差得多于 0.03）拿来对照。
    """
    from plugins.recon import landmarks

    axis = landmarks.lengthwise(points_of(shape), triangles_of(shape))
    tilt = math.degrees(math.acos(min(1.0, abs(float(axis[2])))))
    chosen = how["proximal"] if how["proximal"] != "auto" else ("high_z" if axis[2] > 0 else "low_z")
    if abs(ends["high_z"]["roundness"] - ends["low_z"]["roundness"]) <= 0.03:
        return chosen, chosen, tilt
    return chosen, max(ends, key=lambda name: ends[name]["roundness"]), tilt


# ---------------------------------------------------------------- 整个流程

def run(folder: Path, setting: dict, out: Path, stage=lambda name: None) -> dict:
    """照重建设定把一份 CT 骨源重建成两个表面。返回 outer、inner（两个 STL 的位置）、measures、history、notes。"""
    import SimpleITK as sitk

    how, files, out = options(setting), setting["source"], Path(out)
    voxel, margin, threshold = float(how["voxel_mm"]), float(how["margin_mm"]), float(how["cortical_hu"])
    out.mkdir(parents=True, exist_ok=True)
    measures, notes = {}, []

    stage("ct-read")
    shape, groups = outer_only(read_shape(Path(folder) / files["outer"]))                          # 第 1 步
    path, signs, overlap = choose(shape, volumes(folder, files.get("ct")))                         # 第 2 步
    scan = sitk.ReadImage(str(path), sitk.sitkFloat32)
    if signs != (1, 1, 1):
        shape = flipped(shape, signs)
    reference = described(shape)
    if reference["bad_edges"]:
        notes.append(f"参考外形不是封闭的（{reference['bad_edges']} 条开放边或非流形边）：掩膜靠填洞补上，请核对外形")
    bounds = shape.GetBounds()
    origin = (bounds[0] - margin, bounds[2] - margin, bounds[4] - margin)                           # 第 3 步
    size = [int(math.ceil((bounds[2 * k + 1] - bounds[2 * k] + 2 * margin) / voxel)) for k in range(3)]
    crop = sitk.Resample(scan, size, sitk.Transform(), sitk.sitkLinear, origin, (voxel,) * 3, (1, 0, 0, 0, 1, 0, 0, 0, 1), -1024.0)
    measures.update(ct_file=path.name, ct_overlap=overlap, ct_flip=list(signs), ct_spacing_mm=[round(float(v), 3) for v in scan.GetSpacing()],
                    ct_voxels_million=round(float(np.prod(size)) / 1e6, 1), reference_groups=groups,
                    reference_volume_mm3=reference["volume_mm3"])

    stage("ct-masks")
    femur = fill_solid(rasterize(shape, origin, size, voxel))                                       # 第 4 步
    values, solid = sitk.GetArrayViewFromImage(crop), sitk.GetArrayViewFromImage(femur) > 0
    if not solid.any():
        raise ValueError("参考外形没有围住任何体素：外形是空的，或者不封闭")
    each = voxel ** 3
    shell = sitk.GetArrayFromImage(sitk.And(sitk.BinaryDilate(femur, [1] * 3), sitk.Not(sitk.BinaryErode(femur, [1] * 3)))) > 0
    measures.update(femur_mask_mm3=float(solid.sum()) * each, hu_inside_mean=float(values[solid].mean()),
                    hu_inside_p95=float(np.percentile(values[solid], 95)),
                    surface_on_bone_share=round(float((values[shell] >= 200).mean()), 3))        # 外形是不是压在骨面上
    cortex = sitk.And(crop >= threshold, femur)                                                     # 第 5 步
    measures["cortex_by_threshold_mm3"] = float(sitk.GetArrayViewFromImage(cortex).sum()) * each
    ends = _end_slices(sitk.GetArrayFromImage(femur), voxel)
    proximal, other, tilt = _proximal(how, shape, ends)
    measures.update(proximal_end=proximal, end_slices=ends, long_axis_tilt_deg=round(tilt, 1))
    if other != proximal:
        notes.append(f"近端定在 {proximal} 一头，但另一种判法认为是 {other} 一头：请核对骨的方向（重建设定的 ct.proximal 可以明写）")
    if tilt > 30 and how["depth_cap"] is not None:
        notes.append(f"骨的长轴和 CT 的 z 方向差了 {tilt:.0f} 度：两端限深是沿 z 一层一层算的，骨斜成这样时“两端”的位置对不准，请核对")
    deep = None
    if how["depth_cap"] is not None:                                                                # 第 6 步
        depth = sitk.SignedMaurerDistanceMap(femur, insideIsPositive=True, squaredDistance=False, useImageSpacing=True)
        used = np.where(solid.any(axis=(1, 2)))[0]
        along = np.clip((np.arange(size[2]) - used.min()) / max(used.max() - used.min(), 1), 0, 1)
        if proximal == "low_z":
            along = 1 - along
        limit = np.interp(along, [knot[0] for knot in how["depth_cap"]], [knot[1] for knot in how["depth_cap"]]).astype(np.float32)
        limits = sitk.GetImageFromArray(np.broadcast_to(limit[:, None, None], (size[2], size[1], size[0])).copy())
        limits.CopyInformation(femur)
        deep = sitk.Greater(sitk.Cast(depth, sitk.sitkFloat32), limits)
        measures["cortex_removed_by_depth_mm3"] = float(sitk.GetArrayFromImage(sitk.And(cortex, deep)).sum()) * each
        cortex = sitk.And(cortex, sitk.Not(deep))
    cortex = sitk.BinaryMorphologicalClosing(cortex, [1] * 3)                                       # 第 7 步
    inside = sitk.And(femur, sitk.Not(cortex))                                                      # 第 8 步
    inside = sitk.BinaryMorphologicalOpening(inside, [1] * 3)                                       # 第 9 步
    inside = sitk.BinaryFillhole(sitk.BinaryMorphologicalClosing(largest(inside), [2] * 3))         # 第 10、11 步
    if deep is not None:
        inside = sitk.Or(inside, sitk.And(deep, femur))                                             # 第 12 步
    inside = sitk.And(inside, sitk.BinaryErode(femur, [int(how["min_wall_voxels"])] * 3))           # 第 13 步
    inside = largest(inside)                                                                        # 第 14 步
    cortex = sitk.And(femur, sitk.Not(inside))
    hollow = sitk.GetArrayViewFromImage(inside) > 0
    measures.update(cortex_mask_mm3=float(sitk.GetArrayViewFromImage(cortex).sum()) * each, interior_mask_mm3=float(hollow.sum()) * each)
    measures["cortex_added_by_rules_share"] = round(1 - measures["cortex_by_threshold_mm3"] / max(measures["cortex_mask_mm3"], 1e-9), 3)

    stage("ct-surfaces")
    outer = to_surface(femur, float(how["outer_sigma_mm"]), int(how["relax"]), int(how["triangles"]))      # 第 15 步
    inner = to_surface(inside, float(how["inner_sigma_mm"]), int(how["relax"]), int(how["triangles"]))
    for name, surface in (("outer", outer), ("inner", inner)):
        seen = described(surface)
        measures.update({f"{name}_fine_triangles": seen["triangles"], f"{name}_fine_bad_edges": seen["bad_edges"],
                         f"{name}_fine_regions": seen["regions"], f"{name}_fine_volume_mm3": seen["volume_mm3"]})
    both = np.concatenate([distances(outer, shape), distances(shape, outer)])
    wall = distances(inner, outer)
    measures.update(outer_vs_reference_mean_mm=float(both.mean()), outer_vs_reference_p95_mm=float(np.percentile(both, 95)),
                    wall_fine_min_mm=float(wall.min()), wall_fine_p05_mm=float(np.percentile(wall, 5)),
                    wall_fine_median_mm=float(np.median(wall)), wall_fine_max_mm=float(wall.max()))
    # 骨干的样子：沿长轴 30% 到 70% 之间髓腔最细的那一层
    areas, whole = hollow.sum(axis=(1, 2)) * voxel ** 2, solid.sum(axis=(1, 2)) * voxel ** 2
    used = np.where(whole > 0)[0]
    low, high = int(used.min()), int(used.max())
    first, last = int(low + 0.3 * (high - low)), int(low + 0.7 * (high - low))
    narrow = first + int(np.argmin(areas[first:last]))
    canal, across = 2 * math.sqrt(areas[narrow] / math.pi), 2 * math.sqrt(whole[narrow] / math.pi)
    measures.update(length_mm=float((high - low + 1) * voxel), isthmus_canal_diameter_mm=float(canal), isthmus_outer_diameter_mm=float(across),
                    isthmus_cortex_index=float(1 - canal / across), isthmus_position=round(float((narrow - low) / (high - low)), 2))
    write_stl(outer, out / "outer.stl")
    write_stl(inner, out / "inner.stl")

    cap = "不限深" if how["depth_cap"] is None else "两端限深，上限 " + "、".join(f"{knot[0]:g}→{knot[1]:g} mm" for knot in how["depth_cap"])
    turned = "外形的坐标原样用" if signs == (1, 1, 1) else (f"外形的 x、y、z 各乘了 {list(signs)} 才和 CT 对上："
                                                      "两个实体和标志点在 CT 的坐标系里，不在外形文件原来的坐标系里")
    history = [
        {"step": "ct-input", "what": f"CT 骨源：外形 {files['outer']}（{groups} 组面片里只留最外层），CT {path.name}，和 CT 重合 {overlap}。{turned}"},
        {"step": "ct-resample", "what": f"在外形周围外扩 {margin:g} mm 截取，重采样成 {voxel:g} mm 的体素（{size[0]} × {size[1]} × {size[2]}）"},
        {"step": "ct-cortex", "what": f"皮质候选：外形以内、不低于 {threshold:g} HU；{cap}；近端在 {proximal} 一头"},
        {"step": "ct-interior", "what": f"内部 = 股骨 − 皮质，经开运算、取最大块、闭运算、填洞；最小壁厚 {how['min_wall_voxels']} 个体素（{how['min_wall_voxels'] * voxel:g} mm）。"
                                        f"最终的皮质里有 {measures['cortex_added_by_rules_share']:.0%} 不是阈值直接得到的，是这些规则补出来的"},
        {"step": "ct-surfaces", "what": f"两个掩膜各自高斯平滑（外表面 {how['outer_sigma_mm']:g} mm，内壁 {how['inner_sigma_mm']:g} mm）、取等值面、"
                                        f"网格平滑 {how['relax']} 次、减面到 {how['triangles']} 个三角形"},
    ]
    return {"outer": out / "outer.stl", "inner": out / "inner.stl", "measures": measures, "history": history, "notes": notes}
