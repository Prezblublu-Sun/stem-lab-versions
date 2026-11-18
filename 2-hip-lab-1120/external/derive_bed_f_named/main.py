"""推导量定义：床支撑 F，和它是由什么组成的。支撑区照名字引用定，从界面点云算。

    python code/main.py <输入文件夹> <输出文件夹>

F = 对柄身（不在领上）界面节点里落在支撑区内的那些，求 面积 / max(泡沫厚度, 下限) 之和，单位 mm。
    泡沫厚度 t   = 柄面到髓腔壁的距离（点云里的 −d_canal）
    深度 ζ       = 从参照点起、逆着 depth_axis 的方向量。参照点是 zone_from 那个点沿 depth_axis 往远端挪 zone_offset_mm
    角 θ         = 节点绕 angle_axis 的角度，从 angle_from 的方向（投到垂直 angle_axis 的面上）量起
    支撑区       = ζ 不超过 zeta_max_mm，而且 |θ| 不超过 theta_max_deg
    下限 t_floor = 厚度小于它的按它算，免得贴着皮质的几个节点把和撑爆

输入文件夹里的 job.json（约定见 stemlab/contract/formats/package.py 的“推导量定义”，拆内核以后的那条路）：
    fields.interface   界面点云（npz）：X、area、d_canal、collar，在骨模型的坐标里
    bone_model         骨模型的文件夹：读清单里的标志点（zone_from 指向骨模型时）
    stem_model         柄的模型的文件夹：读特征点、轴和 placement.frame。无植入物（null）不算
    settings           这个点的推导量设定，照清单里的 derive 声明。每一项都从这里取，这里不留它们的默认值
柄的特征点和轴在柄自己的坐标系里，照 placement.frame 换到骨模型的坐标里；骨的标志点和点云本来就在骨模型的坐标里。
算不了的不交数：result.json 里 derived 是 null，reason 说原因（也打在输出里）。

这个定义不认哪一根骨：位置都来自输入。旧常数（旧模型坐标、3406 专用）的那一个在 external/derive_bed_f，只给参照包那条用。
"""
import json
import pathlib
import sys

import numpy as np

NEEDED = ("zone_from", "zone_offset_mm", "depth_axis", "zeta_max_mm", "angle_axis", "angle_from", "theta_max_deg", "t_floor_mm")
NUMBERS = ("zone_offset_mm", "zeta_max_mm", "theta_max_deg", "t_floor_mm")
POINTS = ("bone.landmark", "stem.feature")      # zone_from 能指向的
AXES = ("stem.axis",)                           # 三根轴能指向的
CLOUD = ("X", "area", "d_canal", "collar")      # 点云里要读的数组


class Unsupported(Exception):
    """这个点的床支撑算不了。"""


def reading(settings) -> dict:
    """这个点的推导量设定。要的项都得在，而且是取值：不拿自己的默认值顶上。"""
    if not isinstance(settings, dict):
        raise Unsupported("job 里没有推导量设定（settings）：支撑区在哪、多大都从设定来")
    missing = [name for name in NEEDED if settings.get(name) is None]
    if missing:
        raise Unsupported(f"推导量设定里少了 {missing}：这个包不拿自己的默认值顶上")
    left = [name for name in NEEDED if settings[name] == {"per_point": True}]
    if left:
        raise Unsupported(f"推导量设定里 {left} 写的还是“每个点给”，没有取值")
    odd = [name for name in NUMBERS if isinstance(settings[name], bool) or not isinstance(settings[name], (int, float))]
    if odd:
        raise Unsupported(f"推导量设定里 {odd} 要是数")
    return settings


def reference(item: str, value, allowed: tuple) -> tuple[str, str]:
    """一个名字引用：（哪一份输入的哪一类，叫什么）。"""
    text = value.get("ref") if isinstance(value, dict) and set(value) == {"ref"} else None
    parts = text.split(".", 2) if isinstance(text, str) else []
    if len(parts) != 3 or f"{parts[0]}.{parts[1]}" not in allowed:
        raise Unsupported(f"{item} 要是名字引用，指向 {list(allowed)} 里的一样，这里是 {value!r}")
    return f"{parts[0]}.{parts[1]}", parts[2]


def _unit(vector, what: str):
    size = float(np.linalg.norm(vector))
    if size < 1e-9:
        raise Unsupported(f"{what}定不出来")
    return vector / size


def located(settings: dict, stem_folder: pathlib.Path, bone_folder: pathlib.Path) -> dict:
    """照名字引用把位置找出来，都放在骨模型的坐标里：参照点 ref、深度轴的方向 depth、量角的轴 axis 和它过的点 centre、
    0 度的方向 zero 和 90 度的方向 side。"""
    try:
        model = json.loads((stem_folder / "stem_model.json").read_text(encoding="utf-8"))
        frame = {key: np.asarray(model["placement"]["frame"][key], float) for key in ("origin", "x", "y", "z")}
        features, axes = model["features"], model["axes"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Unsupported(f"读不出柄的模型：{type(error).__name__}: {error}") from None

    def turn(direction):
        direction = np.asarray(direction, float)
        return direction[0] * frame["x"] + direction[1] * frame["y"] + direction[2] * frame["z"]

    def point(item: str):
        where, name = reference(item, settings[item], POINTS)
        if where == "stem.feature":
            if name not in features:
                raise Unsupported(f"{item} 指的是 {where}.{name}，柄的模型里没有这个特征点（有 {sorted(features)}）")
            return frame["origin"] + turn(features[name])
        try:
            landmarks = json.loads((bone_folder / "manifest.json").read_text(encoding="utf-8"))["landmarks"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise Unsupported(f"读不出骨模型的标志点：{type(error).__name__}: {error}") from None
        if name not in landmarks:
            raise Unsupported(f"{item} 指的是 {where}.{name}，骨模型里没有这个标志点（有 {sorted(landmarks)}）")
        return np.asarray(landmarks[name]["xyz"], float)

    def axis(item: str):
        where, name = reference(item, settings[item], AXES)
        if name not in axes:
            raise Unsupported(f"{item} 指的是 {where}.{name}，柄的模型里没有这根轴（有 {sorted(axes)}）")
        return frame["origin"] + turn(axes[name]["point"]), _unit(turn(axes[name]["direction"]), f"{item} 那根轴的方向")

    _, depth = axis("depth_axis")
    centre, around = axis("angle_axis")
    _, start = axis("angle_from")
    zero = _unit(start - (start @ around) * around, "0 度的方向（angle_from 那根轴和 angle_axis 平行）")
    return {"ref": point("zone_from") - float(settings["zone_offset_mm"]) * depth, "depth": depth, "centre": centre, "axis": around,
            "zero": zero, "side": np.cross(around, zero)}


def cloud_of(path: pathlib.Path) -> dict:
    """界面点云里要读的几个数组。"""
    try:
        loaded = np.load(path)
        have = {name: np.asarray(loaded[name]) for name in CLOUD if name in loaded.files}
        listed = sorted(loaded.files)
    except Exception as error:  # noqa: BLE001  numpy 读一个坏文件抛的错不止一种
        raise Unsupported(f"读不出界面点云：{type(error).__name__}: {error}") from None
    missing = [name for name in CLOUD if name not in have]
    if missing:
        raise Unsupported(f"界面点云里没有 {missing}（有 {listed}）")
    cloud = {"X": have["X"].astype(float), "area": have["area"].astype(float), "d_canal": have["d_canal"].astype(float),
             "collar": have["collar"].astype(bool)}
    count, shapes = len(cloud["X"]), {name: cloud[name].shape for name in CLOUD}
    if shapes["X"] != (count, 3) or any(shapes[name] != (count,) for name in CLOUD[1:]):
        raise Unsupported(f"界面点云里几个数组的形状对不上：{shapes}")
    return cloud


def bed_support(cloud: dict, where: dict, how: dict) -> dict:
    """F 和它是由什么组成的。cloud 和 where 都在骨模型的坐标里。"""
    body = ~cloud["collar"]
    X, w, t = cloud["X"][body], cloud["area"][body], -cloud["d_canal"][body]
    zeta = -(X - where["ref"]) @ where["depth"]
    out = X - where["centre"]
    theta = np.degrees(np.arctan2(out @ where["side"], out @ where["zero"]))
    floor = float(how["t_floor_mm"])
    inside = (zeta <= float(how["zeta_max_mm"])) & (np.abs(theta) <= float(how["theta_max_deg"]))
    count, total = int(inside.sum()), float(w[inside].sum())
    return {"F_mm": float((w[inside] / np.maximum(t[inside], floor)).sum()), "F_area_mm2": total, "F_n_nodes": count,
            "F_t_min_mm": float(t[inside].min()) if count else None,
            "F_frac_floor": float(w[inside][t[inside] < floor].sum() / total) if total > 0 else None}


def derive(job: dict, source: pathlib.Path) -> dict:
    def folder(given) -> pathlib.Path:
        where = pathlib.Path(given)
        return where if where.is_absolute() else source / where

    if job.get("stem_model") is None:
        raise Unsupported("这个点没有柄的模型（无植入物）：床支撑量的是柄周围的骨床，没有柄就没有这个量")
    settings = reading(job.get("settings"))
    if not job.get("bone_model"):
        raise Unsupported("job 里没有骨模型（bone_model）")
    where = located(settings, folder(job["stem_model"]), folder(job["bone_model"]))
    given = (job.get("fields") or {}).get("interface")
    if not given:
        raise Unsupported("job 里没有界面点云（fields.interface）")
    return bed_support(cloud_of(folder(given)), where, settings)


def main() -> int:
    source, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out.mkdir(parents=True, exist_ok=True)
    job = json.loads((source / "job.json").read_text(encoding="utf-8"))
    try:
        result = {"derived": derive(job, source)}
    except Unsupported as error:
        print(f"床支撑 F 算不了：{error}")
        result = {"derived": None, "reason": str(error)}
    (out / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
