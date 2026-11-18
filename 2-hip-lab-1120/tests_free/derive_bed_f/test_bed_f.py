"""拆内核 4e：床支撑 F 照名字引用取位置（external/derive_bed_f_named）。目标见 docs/拆内核.md 的“4e”。

照 external/derive_bed_f_named/build.py 现打一个包：
    清单      过契约的核对，带 derive 声明、对输入的要求、needs、columns，programs 是空的；测试轮的推导量设定照声明核得过，
              名字引用的名字都在 M1 柄空间包答应给的 names 和骨模型第 1 版必有的标志点里
    自检      包自带的样本过得去
    位置      一份造的输入（柄的模型、骨模型的清单、十二个节点的点云），哪几个节点落在支撑区里手算得出来：
              包算的和手算的一样；8 项各换一个值，结果照预想的变；整个场面一起挪动转动，F 不变
    算不了的  没有柄的模型、设定缺项、名字不在、0 度的方向定不出来：不交数，说出原因
    3406      设计 A 的柄的模型（4c 的柄空间包交出的，截骨高度 16 mm 和 18 mm 各一个）：旧常数换到骨模型的坐标里，
              就是名字指的那几样；同一份点云上，旧的包（旧常数、旧模型坐标）和这个包只在 ±45° 边上那一窄条里不一样
    fea.run   登记进一本空账，配一个只出点云的假有限元包（fem_cloud），经真的 fea.run：启动前核推导量设定和名字引用；
              推导量定义拿到骨模型、柄的模型和这个点的推导量设定；每个点给的项进数据的行；made_by 里记着推导量设定
设计 A 用真的 Abaqus 走一遍、把 F 和参照包那条的并排打出来，在 tests_free/fem_abaqus（设 STEMLAB_ABAQUS_RUN=1 才跑）。

“3406”“fea.run”两组要旧系统的文件（只读；换了地方设 STEMLAB_LEGACY）和 gmsh。哪样没有，这两组跳过并说明原因：
看到跳过，不等于那部分验过了。external/ 不在检查的范围里，所以测试放在这里。
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from plugins.fea import given
from stemlab.contract import hashing
from stemlab.contract.formats import bone_model
from stemlab.contract.formats import declaration as d
from stemlab.contract.formats import package as package_format
from stemlab.contract.formats import stem_model
from stemlab.contract.formats.manifest import check_format, make_manifest, read_manifest, write_manifest
from stemlab.contract.formats.points import read_points
from stemlab.desk.core import start as starting
from stemlab.experiments import view
from stemlab.registry import lookup, register
from tests import packages, real
from tests.plugins.fea_cases import kept, refused, rows_of, stages
from tests.science import tools
from tests_free import sawbone3406
from tests_free.derive_bed_f.oracle import located, truth

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "external" / "derive_bed_f_named"          # 照名字引用的包：给 fea.run
OLD = REPO / "external" / "derive_bed_f"                 # 旧常数的包：给参照包那条（fea.reference）
CLOUD = Path(__file__).resolve().parent / "fem_cloud"    # 假的有限元包：只出一份点云
COLUMNS = ("F_mm", "F_area_mm2", "F_n_nodes", "F_t_min_mm", "F_frac_floor")


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DECL = _load("external/derive_bed_f_named/declarations.py", "derive_bed_f_named_declarations")
BUILD = _load("external/derive_bed_f_named/build.py", "derive_bed_f_named_build")
STEM_DECL = _load("external/stem_m1_3406/declarations.py", "stem_m1_3406_declarations_4e")
STEM_BUILD = _load("external/stem_m1_3406/build.py", "stem_m1_3406_build_4e")
TEST = d.test_setting(DECL.DERIVE, "R0003")["values"]           # 测试轮的推导量设定
PLACE = d.test_setting(STEM_DECL.PLACEMENT, "R0001")["values"]   # 测试轮的放置设定（设计 A 用的）
SHAPE_A = dict(STEM_DECL.A)                                      # 设计 A 的 12 个形状项


# ---------------------------------------------------------------- 跑包

def start(package: Path, source: Path, out: Path) -> dict:
    """照核心的办法跑一次包：入口后面跟输入文件夹和输出文件夹，在包的文件夹里跑。返回 result.json 的内容。"""
    out.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([sys.executable, str(package / "code" / "main.py"), str(source), str(out)], cwd=package,
                          env=dict(os.environ, **tools.ENV), capture_output=True, timeout=600)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads((out / package_format.RESULT).read_bytes())


def run(package: Path, job: dict, where: Path) -> dict:
    """交一个 job 给包，返回 result。"""
    (where / "ask").mkdir(parents=True, exist_ok=True)
    (where / "ask" / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return start(package, where / "ask", where / "out")


def settings(**change) -> dict:
    """一个点上推导量设定的取值：测试轮的那一套，change 盖掉同名的，写 None 就是去掉这一项。"""
    values = {**TEST, **change}
    return {name: value for name, value in values.items() if value is not None}


# ---------------------------------------------------------------- 一份造的输入：位置都手算得出来

# 柄自己的坐标系：x 内侧，y 前方，z 沿柄轴指向远端（M1 柄空间包的写法）。颈轴从颈底指向头，在 x、z 张成的面里
NECK = (0.6, 0.0, -0.8)
FEATURES = {"head_center": [12.0, 0.0, -16.0], "neck_base": [0.0, 0.0, 0.0], "shoulder": [0.0, 0.0, 0.0], "tip": [0.0, 0.0, 40.0]}
AXES = {"stem_axis": {"point": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0]},
        "neck_axis": {"point": [0.0, 0.0, 0.0], "direction": list(NECK)},
        "up_axis": {"point": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, -1.0]},       # 沿柄轴指向近端：拿来换 depth_axis
        "side_axis": {"point": [0.0, -4.0, 0.0], "direction": [0.0, 0.0, 1.0]},     # 和柄轴平行、往后挪了 4 mm：拿来换 angle_axis
        "front_axis": {"point": [0.0, 0.0, 0.0], "direction": [0.0, 0.8, 0.6]}}     # 投到垂直柄轴的面上朝前：拿来换 angle_from
# 骨的标志点，写在柄的坐标系里（scene 换到骨模型的坐标里）：头心复位，颈中心在颈轴上离头心 2 mm，别的随便放
LANDMARKS = {"head_center": [12.0, 0.0, -16.0], "neck_center": [10.8, 0.0, -14.4], "shaft_proximal": [-20.0, 0.0, 10.0],
             "shaft_distal": [-25.0, 0.0, 150.0], "lesser_trochanter": [0.0, -15.0, 30.0]}


def node(theta_deg: float, s: float, t: float = 1.0, collar: bool = False, r: float = 6.0) -> dict:
    """离柄轴 r、绕柄轴 theta（从内侧起、朝前为正）、沿柄轴 s 处的一个界面节点：面积 2，泡沫厚 t。"""
    angle = math.radians(theta_deg)
    return {"x": [r * math.cos(angle), r * math.sin(angle), s], "area": 2.0, "thickness": t, "collar": collar}


# 测试轮的设定下：参照点是头心沿颈轴往远端 16 mm，就是 (2.4, 0, −3.2)；深度 ζ = 4 − 0.6x + 0.8z；角从 +x 起。
# 落在支撑区里的是 medial、plus30、minus30、edge 四个：F = 2/1 + 2/0.5 + 2/0.25 + 2/4 = 14.5
NODES = {
    "medial": node(0, 5, t=1.0),            # ζ 4.4
    "plus30": node(30, 5, t=0.5),           # ζ 4.88
    "minus30": node(-30, 5, t=0.1),         # ζ 4.88，厚度比下限 0.25 薄
    "front": node(90, 5),                   # ζ 8，角度出去了
    "plus140": node(140, 5),
    "lateral": node(180, 5),
    "minus140": node(-140, 5),
    "back": node(-90, 5),
    "deep": node(0, 20),                    # ζ 16.4，比 15 深
    "collar": node(0, 5, collar=True),      # 领上的不算
    "plus50": node(50, 5, t=2.0),           # ζ 5.69，角度 50° 出去了
    "edge": node(0, 17, t=4.0),             # ζ 14.0，贴着 15 的边
}
BASE = {"F_mm": 14.5, "F_area_mm2": 8.0, "F_n_nodes": 4, "F_t_min_mm": 0.1, "F_frac_floor": 0.25}


def rotation(about, degrees: float) -> np.ndarray:
    """绕一根轴转这么多度的旋转矩阵。"""
    axis = np.asarray(about, float) / np.linalg.norm(about)
    angle = math.radians(degrees)
    cross = np.array([[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]])
    return np.eye(3) + math.sin(angle) * cross + (1.0 - math.cos(angle)) * (cross @ cross)


FRAME = (rotation((1.0, 2.0, -0.5), 73.0), np.array([30.0, -5.0, 90.0]))       # 柄的坐标系在骨模型的坐标里：转一下，再挪开


def scene(folder: Path, values: dict | None, turn=None, shift=(0.0, 0.0, 0.0), cloud_too: bool = True, nodes: dict | None = None,
          drop: tuple = ()) -> dict:
    """写一份造的输入：柄的模型、骨模型的清单、界面点云。返回交给包的 job。

    turn、shift 把整个场面（柄的坐标系、骨的标志点、点云）再刚体挪一次；cloud_too=False 时点云留在原地。
    drop 是点云里不写的数组。"""
    spin, origin = FRAME
    turn = np.eye(3) if turn is None else np.asarray(turn, float)
    spin, origin = turn @ spin, turn @ origin + np.asarray(shift, float)

    def to_bone(point) -> np.ndarray:
        return origin + spin @ np.asarray(point, float)

    stem, bone = folder / "stem", folder / "bone"
    for name in ("geometry/stem.step", "faces/interface.step"):
        (stem / name).parent.mkdir(parents=True, exist_ok=True)
        (stem / name).write_text("not read by a derivation\n", encoding="ascii")
    (stem / stem_model.MANIFEST).write_text(json.dumps({
        "format": 1, "files": ["faces/interface.step", "geometry/stem.step"], "units": {"length": "mm"}, "dimension": "3d", "design": {},
        "regions": [{"name": "stem", "role": "body", "geometry": {"kind": "solid", "file": "geometry/stem.step"},
                     "material": {"model": "elastic", "E": 110000.0, "nu": 0.3}}],
        "faces": {"interface": {"region": "stem", "file": "faces/interface.step"}}, "features": FEATURES, "axes": AXES,
        "placement": {"frame": {"origin": origin.tolist(), "x": spin[:, 0].tolist(), "y": spin[:, 1].tolist(), "z": spin[:, 2].tolist()},
                      "cut": {"point": to_bone(FEATURES["neck_base"]).tolist(), "normal": (spin @ np.asarray(NECK)).tolist()},
                      "removed": None, "landmarks": []},
        "templating": {}}), encoding="utf-8")
    assert stem_model.check(stem) == [], "造的柄的模型本身合格式"
    bone.mkdir(parents=True, exist_ok=True)
    (bone / "manifest.json").write_text(json.dumps({"bone_id": "made-up", "side": "right", "landmarks": {
        name: {"xyz": to_bone(point).tolist(), "definition": "made up"} for name, point in LANDMARKS.items()}}), encoding="utf-8")
    listed = list((NODES if nodes is None else nodes).values())
    arrays = {"X": np.array([(to_bone(one["x"]) if cloud_too else FRAME[1] + FRAME[0] @ np.asarray(one["x"])) for one in listed]),
              "area": np.array([one["area"] for one in listed]), "d_canal": -np.array([one["thickness"] for one in listed]),
              "collar": np.array([one["collar"] for one in listed], bool)}
    np.savez(folder / "interface.npz", **{key: value for key, value in arrays.items() if key not in drop})
    return {"fields": {"interface": str(folder / "interface.npz")}, "labels": {}, "pre": {}, "point": {"name": "made-up"},
            "bone_model": str(bone), "stem_model": str(stem), "settings": values}


# 照定义另算的那一份在 oracle.py：位置留在柄自己的坐标系里、一个节点一个节点地算，不用包里的代码

def same(got: dict, wanted: dict, rel: float = 1e-9) -> bool:
    """包交的五个量和该有的一样。"""
    assert set(got) == set(COLUMNS), got
    return all(got[name] == (wanted[name] if wanted[name] is None else pytest.approx(wanted[name], rel=rel, abs=1e-12)) for name in COLUMNS)


# ---------------------------------------------------------------- 夹具

def _build(script: Path, folder: Path, *before: str) -> Path:
    done = subprocess.run([sys.executable, str(script), *before, str(folder)], capture_output=True, timeout=600,
                          env=dict(os.environ, **tools.ENV))
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return folder


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """照 external/derive_bed_f_named 的做法现打一个包。"""
    return _build(HERE / "build.py", tmp_path_factory.mktemp("bed-f") / "package")


@pytest.fixture(scope="module")
def old_package(tmp_path_factory) -> Path:
    """旧常数的那个包（external/derive_bed_f）：参照包那条用的。"""
    return _build(OLD / "build.py", tmp_path_factory.mktemp("bed-f-old") / "package")


@pytest.fixture(scope="module")
def legacy() -> Path:
    """旧系统的文件夹。只读。"""
    wanted = [tools.LEGACY / "docs" / "freeze" / "M1-3406-v1_files.tar", tools.LEGACY / sawbone3406.SUMMARY,
              *(tools.LEGACY / "v2" / "data" / "femur_3406" / file for file in tools.STEPS.values())]
    missing = [str(path) for path in wanted if not path.is_file()]
    if missing:
        pytest.skip(f"找不到旧系统的文件（{missing[0]}）。换地方了就设 STEMLAB_LEGACY")
    return tools.LEGACY


@pytest.fixture(scope="module")
def summary(legacy) -> dict:
    return json.loads((legacy / sawbone3406.SUMMARY).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def works():
    """gmsh 加载得了。加载不了（比如安全软件还占着它的 DLL）就跳过：出柄的模型要它。"""
    try:
        import gmsh  # noqa: F401
    except (ImportError, OSError) as error:
        pytest.skip(f"gmsh 加载不了：{error}")


@pytest.fixture(scope="module")
def stem_package(legacy, tmp_path_factory) -> Path:
    """照 external/stem_m1_3406 的做法现打一个柄空间包（4c）。"""
    return _build(REPO / "external" / "stem_m1_3406" / "build.py", tmp_path_factory.mktemp("stem") / "package", str(legacy))


@pytest.fixture(scope="module")
def bone(legacy, summary, tmp_path_factory) -> Path:
    return sawbone3406.bone_folder(tmp_path_factory.mktemp("bone3406") / "bone", legacy, summary)


@pytest.fixture(scope="module")
def stems(stem_package, bone, works, tmp_path_factory) -> dict:
    """设计 A 的两个柄的模型：截骨高度 16 mm（入口偏移 0，截骨中心就是旧常数 cref），和 18 mm（入口偏移 −2 mm，
    截骨中心比 cref 深 2 mm，肩部中心也不在截骨中心上）。返回 {名字: 柄的模型的文件夹}。"""
    found = {}
    for name, h_cut in (("h16", 16.0), ("h18", 18.0)):
        where = tmp_path_factory.mktemp(f"stem-model-{name}")
        job = {"mode": "model", "bone_model": str(bone), "bone_id": tools.BONE_ID, "settings": {**PLACE, "h_cut": h_cut},
               "point": {"name": name, "hash": "a" * 64, "design": SHAPE_A}}
        said = run(stem_package, job, where)
        assert said["status"] == "ok", said
        found[name] = where / "out" / given.MODEL
    return found


# ---------------------------------------------------------------- 包本身

def test_the_package_is_a_well_formed_derive_def(built):
    assert check_format("derive_def", built) == []
    listed = read_manifest(built)
    assert listed["declarations"] == DECL.DECLARATIONS and [one["name"] for one in listed["declarations"]] == ["derive"]
    assert all(d.check_declaration(one) == [] for one in listed["declarations"])
    assert listed["modes"] == ["derive"] and listed["needs"] == ["interface"] and listed["programs"] == [], "不用外部程序"
    assert [column["name"] for column in listed["columns"]] == list(COLUMNS)
    assert all(column["unit"] in d.UNITS and column["meaning"].strip() for column in listed["columns"])
    assert set(listed["inputs"]) == {"bone", "stem", "fields"} and "bones" not in listed, "要哪几样输入写在清单里；不再只认一根骨"
    assert [item["name"] for item in DECL.DERIVE["items"]] == [
        "zone_from", "zone_offset_mm", "depth_axis", "zeta_max_mm", "angle_axis", "angle_from", "theta_max_deg", "t_floor_mm"]
    by_name = {item["name"]: item for item in DECL.DERIVE["items"]}
    assert {name for name, item in by_name.items() if item["type"] == "ref"} == {"zone_from", "depth_axis", "angle_axis", "angle_from"}
    assert all(item["per_point"] == (item["type"] == "number") for item in by_name.values()), "数可以每个点给，名字引用所有点都一样"
    assert all(len(item["test_source"]) > 20 for item in by_name.values()), "每项写了来路"
    assert (TEST["zeta_max_mm"], TEST["theta_max_deg"], TEST["t_floor_mm"]) == (15.0, 45.0, 0.25), "区的大小照 bed_f.json"


def test_the_test_round_setting_points_at_names_that_are_there(built):
    """测试轮的推导量设定照声明核得过；它引用的名字，M1 柄空间包答应给，骨模型第 1 版必有。"""
    names = {**bone_model.names({"solids": dict.fromkeys(bone_model.SOLIDS), "landmarks": dict.fromkeys(bone_model.LANDMARKS)}),
             **given.promised({"names": STEM_BUILD.NAMES})}
    setting = d.test_setting(read_manifest(built)["declarations"][0], "R0003")
    assert d.check_setting(setting, DECL.DERIVE, of="R0003", use="test", names=names) == []
    referred = sorted(value["ref"] for value in setting["values"].values() if isinstance(value, dict))
    assert referred == ["bone.landmark.head_center", "stem.axis.neck_axis", "stem.axis.neck_axis", "stem.axis.stem_axis"]
    lost = dict(setting, values=dict(setting["values"], angle_from={"ref": "stem.axis.taper_axis"}))
    assert any("规则 8" in text for text in d.check_setting(lost, DECL.DERIVE, names=names)), "柄空间包没答应给的名字，核得出来"


def test_the_package_passes_its_own_self_check(built, tmp_path):
    listed = read_manifest(built)
    assert listed["selftest"], "包带着自检样本"
    for sample in listed["selftest"]:
        got = start(built, built / sample["input"], tmp_path / sample["name"])
        expected = json.loads((built / sample["expected"]).read_bytes())
        assert package_format.differences(expected, got, listed["tolerance"]) == []


# ---------------------------------------------------------------- 位置是照名字取的

def test_the_zone_is_where_the_names_say(built, tmp_path):
    """造的输入里，照测试轮的设定落在支撑区里的是四个节点，手算 F = 14.5。柄的坐标系在骨模型的坐标里转过、挪过。"""
    result = run(built, scene(tmp_path, settings()), tmp_path)
    assert same(result["derived"], BASE), result
    model = stem_model.read(tmp_path / "stem")
    landmarks = json.loads((tmp_path / "bone" / "manifest.json").read_bytes())["landmarks"]
    assert same(truth(NODES.values(), located(settings(), model, landmarks), settings()), BASE), "测试里另算的那一份也是这个数"


def only(*names: str, floor: float = 0.25) -> dict:
    """只有这几个节点落在支撑区里时该交的五个量。"""
    inside = [NODES[name] for name in names]
    area = sum(one["area"] for one in inside)
    return {"F_mm": sum(one["area"] / max(one["thickness"], floor) for one in inside), "F_area_mm2": area, "F_n_nodes": len(inside),
            "F_t_min_mm": min(one["thickness"] for one in inside),
            "F_frac_floor": sum(one["area"] for one in inside if one["thickness"] < floor) / area}


# 每一项换一个值：项名 ->（换成什么，这时落在支撑区里的节点，为什么）
VARIANTS = {
    "zone_from": ({"zone_from": {"ref": "stem.feature.neck_base"}}, ("medial", "plus30", "minus30", "edge", "deep"),
                  "从颈底量起，参照点往远端挪了 20 mm，所有节点都够得着：deep 进来了"),
    "zone_from_bone": ({"zone_from": {"ref": "bone.landmark.neck_center"}}, ("medial", "plus30", "minus30", "edge", "deep"),
                       "从骨的颈中心（离头心 2 mm）量起，ζ 都小 2：deep 是 14.4，进来了"),
    "zone_offset_mm": ({"zone_offset_mm": 14.0}, ("medial", "plus30", "minus30"), "参照点往近端回 2 mm，ζ 都大 2：edge 成了 16，出去了"),
    "depth_axis": ({"depth_axis": {"ref": "stem.axis.up_axis"}}, ("medial", "plus30", "minus30"),
                   "深度改沿柄轴量：参照点是 (12, 0, 0)，ζ 就是 z。edge 的 17 出去了"),
    "zeta_max_mm": ({"zeta_max_mm": 12.0}, ("medial", "plus30", "minus30"), "edge 的 ζ 是 14，出去了"),
    "zeta_max_mm_up": ({"zeta_max_mm": 17.0}, ("medial", "plus30", "minus30", "edge", "deep"), "deep 的 ζ 是 16.4，进来了"),
    "angle_axis": ({"angle_axis": {"ref": "stem.axis.side_axis"}}, ("medial", "minus30", "edge"),
                   "量角的中心往后挪了 4 mm：plus30 成了 53.4°，出去了；minus30 是 10.9°"),
    "angle_from": ({"angle_from": {"ref": "stem.axis.front_axis"}}, ("front", "plus50"), "0 度改朝前：在里面的是 front（0°）和 plus50（−40°）"),
    "theta_max_deg": ({"theta_max_deg": 60.0}, ("medial", "plus30", "minus30", "edge", "plus50"), "plus50 的 50° 进来了"),
    "t_floor_mm": ({"t_floor_mm": 0.05}, ("medial", "plus30", "minus30", "edge"), "minus30 的 0.1 mm 不再垫到 0.25：F 成了 26.5"),
}


def test_the_variants_cover_every_item():
    changed = {name for change, _, _ in VARIANTS.values() for name in change}
    assert changed == {item["name"] for item in DECL.DERIVE["items"]}, "声明里的每一项都换过值"


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_every_setting_reaches_the_result(built, tmp_path, name):
    """每一项换一个值，结果照预想的变：包用的是设定，不是自己留的常数。"""
    change, inside, why = VARIANTS[name]
    values = settings(**change)
    result = run(built, scene(tmp_path, values), tmp_path)
    wanted = only(*inside, floor=values["t_floor_mm"])
    assert same(result["derived"], wanted), f"{name}：{why}。包交的是 {result}"
    assert not same(result["derived"], BASE), f"{name} 换了值，结果没变"
    model = stem_model.read(tmp_path / "stem")
    landmarks = json.loads((tmp_path / "bone" / "manifest.json").read_bytes())["landmarks"]
    assert same(truth(NODES.values(), located(values, model, landmarks), values), wanted), f"{name}：测试里另算的那一份"


def test_moving_everything_together_changes_nothing(built, tmp_path):
    """柄的坐标系、骨的标志点、点云一起转、一起挪，F 不变；点云留在原地不跟着挪，就不是这个数了：
    包是把位置换到点云的坐标里算的，不认哪个固定的坐标系。"""
    turn, shift = rotation((0.3, -1.0, 2.0), 141.0), (250.0, -80.0, 33.0)
    moved = run(built, scene(tmp_path / "moved", settings(), turn, shift), tmp_path / "moved")
    assert same(moved["derived"], BASE), moved
    left = run(built, scene(tmp_path / "left", settings(), turn, shift, cloud_too=False), tmp_path / "left")
    assert not same(left["derived"], BASE), "点云没跟着挪，却还是原来的数"


# ---------------------------------------------------------------- 算不了的

REFUSED = {
    "no_stem": (lambda job: dict(job, stem_model=None), "柄的模型"),
    "no_setting": (lambda job: dict(job, settings=None), "推导量设定"),
    "missing_item": (lambda job: dict(job, settings=settings(t_floor_mm=None)), "t_floor_mm"),
    "left_per_point": (lambda job: dict(job, settings=settings(zeta_max_mm={"per_point": True})), "zeta_max_mm"),
    "no_such_feature": (lambda job: dict(job, settings=settings(zone_from={"ref": "stem.feature.taper_center"})), "taper_center"),
    "no_such_landmark": (lambda job: dict(job, settings=settings(zone_from={"ref": "bone.landmark.condyle"})), "condyle"),
    "no_such_axis": (lambda job: dict(job, settings=settings(depth_axis={"ref": "stem.axis.taper_axis"})), "taper_axis"),
    "wrong_kind": (lambda job: dict(job, settings=settings(angle_axis={"ref": "stem.feature.tip"})), "angle_axis"),
    "no_zero_direction": (lambda job: dict(job, settings=settings(angle_from={"ref": "stem.axis.up_axis"})), "0 度"),
}


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_what_it_cannot_work_out_it_says(built, tmp_path, name):
    """算不了的不交数，说出原因：包不拿自己的默认值顶上，也不猜。"""
    change, said = REFUSED[name]
    result = run(built, change(scene(tmp_path, settings())), tmp_path)
    assert result["derived"] is None and said in result["reason"], result


def test_a_cloud_without_what_it_reads_is_said(built, tmp_path):
    result = run(built, scene(tmp_path, settings(), drop=("d_canal",)), tmp_path)
    assert result["derived"] is None and "d_canal" in result["reason"], result


# ---------------------------------------------------------------- 3406：旧常数就是名字指的那几样

def unit(vector) -> np.ndarray:
    vector = np.asarray(vector, float)
    return vector / np.linalg.norm(vector)


def angle_between(a, b) -> float:
    """两个方向的夹角，度。"""
    return math.degrees(math.acos(max(-1.0, min(1.0, float(unit(a) @ unit(b))))))


def old_constants(summary: dict) -> dict:
    """bed_f.json 里的旧常数，从旧模型坐标换到骨模型的坐标里。"""
    turned, origin = sawbone3406.model_frame(summary)
    old = json.loads((OLD / "bed_f.json").read_text(encoding="utf-8"))
    return {"cref": np.asarray(old["cref"], float) @ turned + origin, "u_neck": unit(old["u_neck"]) @ turned,
            "n3": np.asarray(old["n3"], float) @ turned, "y": turned[1], "turned": turned, "origin": origin,
            "zone": {name: old[name] for name in ("zeta_max_mm", "theta_max_deg", "t_floor_mm")}}


def turned(model: dict, direction) -> np.ndarray:
    """柄的坐标系里的一个方向，换到骨模型的坐标里。"""
    frame, direction = model["placement"]["frame"], np.asarray(direction, float)
    return direction[0] * np.asarray(frame["x"], float) + direction[1] * np.asarray(frame["y"], float) + direction[2] * np.asarray(frame["z"], float)


def placed(model: dict, point) -> np.ndarray:
    """柄的坐标系里的一个点，换到骨模型的坐标里。"""
    return np.asarray(model["placement"]["frame"]["origin"], float) + turned(model, point)


def test_the_old_constants_are_the_named_things_on_3406(stems, summary, bone):
    """旧常数换到骨模型的坐标里，就是测试轮的设定照名字指的那几样。截骨高度 16 mm 和 18 mm 的两个柄都是：
    参照点是头心沿颈轴往远端 16 mm，不跟着截骨面走（18 mm 的那个，颈底离它 2 mm）。"""
    old = old_constants(summary)
    landmarks = read_manifest(bone)["landmarks"]
    for name, folder in stems.items():
        model = stem_model.read(folder)
        where = located(TEST, model, landmarks)
        axis = turned(model, where["axis"])
        assert np.linalg.norm(placed(model, where["ref"]) - old["cref"]) < 1e-6, f"{name}：参照点就是 cref"
        assert angle_between(turned(model, where["depth"]), old["u_neck"]) < 1e-3, f"{name}：深度轴就是 u_neck（它只留了 5 位小数）"
        zero = turned(model, where["zero"])
        zero, was = unit(zero - (zero @ axis) * axis), unit(old["n3"] - (old["n3"] @ axis) * axis)
        assert angle_between(zero, was) < 0.05, f"{name}：0 度的方向就是 n3 投到垂直柄轴的面上（n3 只留了 3 位小数）"
        skew = angle_between(was, unit(old["y"] - (old["y"] @ axis) * axis))
        assert 86.0 < skew < 89.0, f"{name}：旧写法 90 度的方向（旧模型的 y 轴）和 0 度的方向不垂直，夹角 {skew:.2f}°"
    lower = stem_model.read(stems["h18"])
    assert np.linalg.norm(placed(lower, lower["features"]["neck_base"]) - old["cref"]) == pytest.approx(2.0, abs=1e-6), \
        "截骨高度 18 mm：颈底比 cref 深 2 mm"
    assert np.linalg.norm(placed(lower, lower["features"]["shoulder"]) - placed(lower, lower["features"]["neck_base"])) > 1.0, \
        "截骨高度 18 mm：肩部中心不在颈底上（入口偏移 −2 mm）"


def rings(keep) -> list[dict]:
    """绕柄轴的一圈圈节点，在柄自己的坐标系里：离柄轴 6 mm，从肩部往远端每 0.5 mm 一圈，每圈每 0.5° 一个。
    keep(绕柄轴的角, 度) 说这个角度上的节点留不留。面积和厚度随位置变，免得两处的差正好抵掉；靠近肩部的几圈比下限薄。"""
    made = []
    for ring in range(81):
        s = 0.25 + 0.5 * ring
        for step in range(720):
            theta = -179.75 + 0.5 * step
            if keep(theta):
                angle = math.radians(theta)
                made.append({"x": [6.0 * math.cos(angle), 6.0 * math.sin(angle), s], "area": 0.3 + 0.01 * s + 0.001 * step,
                             "thickness": 0.05 + 0.03 * s + 0.05 * (1.0 + math.cos(angle)), "collar": False})
    return made


def both_packages(built: Path, old_package: Path, folder: Path, model_folder: Path, bone: Path, old: dict, nodes: list[dict]) -> tuple:
    """同一份点云交给两个包：这个包拿骨模型坐标里的点云，旧的包拿换到旧模型坐标里的同一份，外加柄的位姿。
    返回（这个包交的，旧的包交的）。离 ζ = 15 mm 不到 0.05 mm 的节点先去掉：u_neck 只留了 5 位小数。"""
    model = stem_model.read(model_folder)
    frame = {key: np.asarray(value, float) for key, value in model["placement"]["frame"].items()}
    local = np.array([one["x"] for one in nodes])
    X = frame["origin"] + local[:, :1] * frame["x"] + local[:, 1:2] * frame["y"] + local[:, 2:] * frame["z"]
    clear = np.abs(-(X - old["cref"]) @ old["u_neck"] - old["zone"]["zeta_max_mm"]) > 0.05
    X, nodes = X[clear], [one for one, kept_ in zip(nodes, clear) if kept_]
    arrays = {"area": np.array([one["area"] for one in nodes]), "d_canal": -np.array([one["thickness"] for one in nodes]),
              "collar": np.zeros(len(nodes), bool)}
    folder.mkdir(parents=True, exist_ok=True)
    np.savez(folder / "bone-frame.npz", X=X, **arrays)
    np.savez(folder / "model-frame.npz", X=(X - old["origin"]) @ old["turned"].T, P0=(frame["origin"] - old["origin"]) @ old["turned"].T,
             stem_axis=frame["z"] @ old["turned"].T, **arrays)
    ask = {"labels": {}, "pre": {}, "point": {"name": "A"}}
    new = run(built, dict(ask, fields={"interface": str(folder / "bone-frame.npz")}, bone_model=str(bone), stem_model=str(model_folder),
                          settings=settings()), folder / "new")
    was = run(old_package, dict(ask, fields={"interface": str(folder / "model-frame.npz")}), folder / "old")
    return new["derived"], was["derived"]


def test_on_one_cloud_the_old_package_differs_only_at_the_edge(built, old_package, stems, summary, bone, tmp_path):
    """同一份点云上，旧的包（旧常数、旧模型坐标、参照包那条的写法）和这个包（名字引用、骨模型坐标）：
    离 ±45° 那两条边 3° 以外的节点，两个包算出同一个数；差只在边上那一窄条里。旧写法 90 度的方向和 0 度的方向不垂直，
    它的支撑区整个往前偏了约 1.4°：朝前的那条边上旧的包多算进一窄条，朝后的那条边上这个包多算进一窄条。
    截骨高度 16 mm 和 18 mm 的两个柄都是这样：参照点不跟着截骨面走，和旧的包一样。"""
    old = old_constants(summary)
    for name, folder in stems.items():
        new, was = both_packages(built, old_package, tmp_path / name / "clear", folder, bone, old,
                                 rings(lambda theta: abs(abs(theta) - 45.0) > 3.0))
        assert new["F_n_nodes"] > 2000 and new["F_frac_floor"] > 0.0, f"{name}：支撑区里有节点，也有比下限薄的（{new}）"
        assert same(new, was), f"{name}：这个包 {new}，旧的包 {was}"
        new, was = both_packages(built, old_package, tmp_path / name / "front", folder, bone, old,
                                 rings(lambda theta: abs(theta - 45.0) <= 3.0))
        assert was["F_n_nodes"] > new["F_n_nodes"] > 0, f"{name}：朝前的那条边，这个包 {new['F_n_nodes']} 个，旧的包 {was['F_n_nodes']} 个"
        new, was = both_packages(built, old_package, tmp_path / name / "back", folder, bone, old,
                                 rings(lambda theta: abs(theta + 45.0) <= 3.0))
        assert new["F_n_nodes"] > was["F_n_nodes"] > 0, f"{name}：朝后的那条边，这个包 {new['F_n_nodes']} 个，旧的包 {was['F_n_nodes']} 个"


def test_the_old_package_refuses_a_fea_run_job(old_package, tmp_path):
    """旧常数的包只认参照包交的点云（旧模型坐标）。fea.run 的 job 带着骨模型：它不算，说出该用哪个。
    同一份点云照参照包那条的 job 交给它（不带骨模型），照旧算。"""
    job = scene(tmp_path, settings())
    cloud = np.load(job["fields"]["interface"])
    np.savez(tmp_path / "with-pose.npz", **{key: cloud[key] for key in cloud.files}, P0=np.zeros(3), stem_axis=np.array([0.0, 0.0, 1.0]))
    job["fields"]["interface"] = str(tmp_path / "with-pose.npz")
    result = run(old_package, job, tmp_path / "split")
    assert result["derived"] is None and "fea.run" in result["reason"] and "derive_bed_f_named" in result["reason"], result
    reference = {key: value for key, value in job.items() if key not in ("bone_model", "stem_model", "settings")}
    assert set(run(old_package, reference, tmp_path / "reference")["derived"]) == set(COLUMNS), "参照包那条的 job 照旧算"


# ---------------------------------------------------------------- 经真的 fea.run

CLOUD_FEM = {"name": "fem", "groups": ["载荷"], "items": [
    packages.item("load", "载荷", "number", 2000.0, per_point=True, unit="N", range={"min": 0, "max": 10000})]}
CLOUD_OUTPUTS = packages.outputs(("n_nodes", "1", "nodes of the made-up interface cloud", "pre"),
                                 ("load_seen", "N", "the load that reached the solver", "label"),
                                 ("interface", "mm", "interface point cloud in the frame of the bone model: X, area, d_canal, collar", "field"))


def registered(tmp: Path, legacy: Path, summary: dict, stem_package: Path, built: Path) -> dict:
    """在这本空账里登记 3406 的骨模型、4c 的柄空间包、只出点云的假有限元包、这个推导量定义。"""
    bone = register.register_external("bone_model", "sawbone3406-model", source=sawbone3406.bone_folder(tmp / "bone", legacy, summary),
                                      note="测试用：3406 的两个实体，标志点照旧系统找出的", by="tester", bone_id=tools.BONE_ID, new_bone=True)
    stem = register.register_external("stem_space", "m1-3406", source=stem_package, note="测试用：现打的 M1 柄空间包", by="tester")
    shutil.copytree(CLOUD, tmp / "fem-cloud", ignore=shutil.ignore_patterns("__pycache__"))
    write_manifest(tmp / "fem-cloud", make_manifest(
        "fem", hashing.list_tree(tmp / "fem-cloud"), entry=["{python}", "code/main.py"], requires=["python>=3.12", "numpy>=2"],
        tolerance={"rel": 1e-9, "abs": 1e-12},
        selftest=[{"name": "echo", "input": "data/selftest/echo/input", "expected": "data/selftest/echo/expected.json"}],
        programs=[], declarations=[CLOUD_FEM], modes=["build", "post"], inputs={"bone": {}, "stem": {}}, outputs=CLOUD_OUTPUTS,
        test_round={"inputs": {}}))
    fem = register.register_external("fem", "fem-cloud", source=tmp / "fem-cloud", note="测试用：只出点云的假有限元包", by="tester")
    derive = register.register_external("derive_def", "bed-f", source=built, note="测试用：现打的床支撑 F（名字引用）", by="tester")
    return {"bone": bone, "stem": stem, "fem": fem, "derive": derive}


def experiment(tmp: Path, items: dict, rows, skip=(), **derive) -> str:
    """一个 fea.run：截骨高度在放置设定里每个点给，支撑区的深度在推导量设定里每个点给。derive 盖掉推导量设定里的取值。"""
    values = {"placement": real.declared(STEM_DECL.PLACEMENT, items["stem"]["id"], h_cut=real.PER_POINT),
              "fem_setting": real.declared(CLOUD_FEM, items["fem"]["id"], load=real.PER_POINT),
              "derive_setting": real.declared(DECL.DERIVE, items["derive"]["id"], **{"zeta_max_mm": real.PER_POINT, **derive})}
    return real.fea_run(tmp, rows, packages_={name: items[name] for name in ("stem", "fem", "derive")}, settings=values,
                        bone=items["bone"], skip=skip)


def point(name: str, h_cut: float, zeta_max: float) -> dict:
    return {"name": name, "bone_id": tools.BONE_ID, "design": dict(SHAPE_A), "conditions": {"load": 2000.0},
            "placement": {"h_cut": h_cut}, "derive": {"zeta_max_mm": zeta_max}, "reason": "测试"}


def archived(made: str, task: str, name: str) -> dict:
    """归档里这个作业留下的一个 JSON 文件。"""
    archive = real.output(made, "archive")
    row = next(row for row in read_points(archive / "index.jsonl") if row["task"] == task and row["file"].endswith(f"/{name}"))
    return json.loads((Path(read_manifest(archive)["root"]) / row["file"]).read_bytes())


def test_bed_support_goes_through_fea_run(real_lab, data, legacy, summary, stem_package, built, works, tmp_path):
    """现打的包登记进一本空账，配 4c 的柄空间包和一个只出点云的假有限元包，经冻结的 fea.run 骨架走一遍：
    推导量定义拿到了骨模型、柄的模型和这个点的推导量设定，照名字引用算出 F；每个点给的深度进了数据的行。"""
    items = registered(tmp_path, legacy, summary, stem_package, built)
    made = experiment(tmp_path, items, [point("deep", 16.0, 15.0), point("shallow", 16.0, 8.0), point("lower", 18.0, 15.0)])
    began = starting.start(made)
    assert began.ok, began
    real.run(made, seconds=900)
    status = view.view(made)
    assert real.tasks(made) == {name: ("done", "finished") for name in ("deep", "shallow", "lower")}, status.rounds[-1].problems
    assert [stage for stage in stages(made, "deep") if stage != "modeled"] == ["stem", "build", "solve", "post"]

    listed = read_manifest(real.output(made, "data"))
    roles = [(column["name"], column["role"]) for column in listed["columns"]]
    assert roles == ([(name, "design") for name in SHAPE_A] + [("load", "condition"), ("h_cut", "condition"), ("zeta_max_mm", "condition")]
                     + [(column["name"], "pre") for column in STEM_BUILD.OUTPUTS]
                     + [("n_nodes", "pre"), ("load_seen", "label"), ("interface", "field")] + [(name, "derived") for name in COLUMNS]), roles
    frozen = status.frozen
    setting = real.declared(DECL.DERIVE, items["derive"]["id"], zeta_max_mm=real.PER_POINT)
    assert listed["made_by"]["derive"] == {"package": frozen["derive"][0]["hash"]}
    assert listed["made_by"]["settings"]["derive"] == hashing.hash_json(
        {name: value for name, value in setting["values"].items() if name != "zeta_max_mm"}), "每个点给的深度不在共用的那部分里"

    landmarks = read_manifest(lookup.content(items["bone"]["id"]))["landmarks"]
    rows = rows_of(made)
    for name, zeta_max in (("deep", 15.0), ("shallow", 8.0), ("lower", 15.0)):
        values = rows[name]["values"]
        assert values["zeta_max_mm"] == zeta_max
        model, cloud = archived(made, name, "stem_model.json"), archived(made, name, "cloud.json")
        how = settings(zeta_max_mm=zeta_max)
        wanted = truth(cloud["nodes"], located(how, model, landmarks), how)
        assert same({key: values[key] for key in COLUMNS}, wanted), f"{name}：数据里的 {values} 对照定义另算的 {wanted}"
        assert values["F_n_nodes"] > 20 and values["F_frac_floor"] > 0.0, f"{name}：支撑区里有节点，也有比下限薄的（{values}）"
    assert rows["deep"]["values"]["F_mm"] > rows["shallow"]["values"]["F_mm"] > 0.0, "支撑区浅了，F 小了"
    assert rows["lower"]["values"]["F_mm"] != pytest.approx(rows["deep"]["values"]["F_mm"], rel=1e-3), "换了一个柄的模型，F 跟着变"
    assert {"derive-result.json", "stem_model.json", "cloud.json"} <= set().union(*kept(made, "deep").values())


def test_fea_run_checks_the_derive_setting_before_the_start(real_lab, data, legacy, summary, stem_package, built, tmp_path):
    """启动前：这个推导量定义声明了 derive，推导量设定就得填；里面的名字引用照柄空间包答应给的名字和骨模型核；
    每个点给的项，点上得有。"""
    items = registered(tmp_path, legacy, summary, stem_package, built)
    rows = [point("deep", 16.0, 15.0)]
    assert "推导量设定要填" in refused(experiment(tmp_path, items, rows, skip=("derive_setting",)))
    lost = refused(experiment(tmp_path, items, rows, angle_from={"ref": "stem.axis.taper_axis"}))
    assert "规则 8" in lost and "stem.axis.taper_axis" in lost, lost
    nowhere = refused(experiment(tmp_path, items, rows, zone_from={"ref": "bone.landmark.condyle"}))
    assert "规则 8" in nowhere and "bone.landmark.condyle" in nowhere, nowhere
    not_given = refused(experiment(tmp_path, items, [dict(point("deep", 16.0, 15.0), derive={})]))
    assert "规则 6" in not_given and "zeta_max_mm" in not_given, not_given
    too_wide = refused(experiment(tmp_path, items, rows, theta_max_deg=200.0))
    assert "theta_max_deg" in too_wide, too_wide
