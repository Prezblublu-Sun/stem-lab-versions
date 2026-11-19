"""拆内核 4d：Abaqus 的有限元包（external/fem_abaqus）。目标见 docs/拆内核.md 的“4d”。

照 external/fem_abaqus/build.py 现打一个包，在 Sawbones 3406 上用 4c 的柄空间包交出的设计 A 的柄的模型建模：
    清单      过契约的核对，带改过的 fem 声明，programs 写着 Abaqus 2025；声明引用的柄上的名字，柄空间包都答应给
    原字节    用到的 7 个冻结文件和冻结时存下的一样，别的运行时文件和旧系统工作树里的一样；code_hash 对不上不打包
    自检      包自带的样本过得去
    建模      设计 A 照测试轮的设定建模：Abaqus 的输入里材料、节点集、载荷、远端约束、接触、分析步、输出都照设定和两份输入
    骨模型    清单是叫包的一方读成第 2 版交来的（job 的 bone），包照角色找两个实体，干轴、内侧、后方照骨模型记的解剖坐标系
              （第 5 步的 5b）。盘上第 1 版的 3406：读出来的坐标系就是这个包原来自己从颈轴算的那一个，建模出的数和 4d 记的一样。
              盘上第 2 版、照后髁连线定的 3406：合力在旧系统的模型坐标里就是旧系统加的那个向量，和前一种绕干轴差 3.8°
    设定      每一项换一个值，输入跟着变：包用的是设定，不是自己留的常数
    别的结局  没有柄的模型归 error；job 里没有 Abaqus 的位置、写的位置上没有启动器，归 env；求解没留下结果、没算完，后处理各归到对的结局
    fea.run   登记进一本空账，经真的 fea.run：操作台的机器清单里没写 Abaqus 2025 就不启动；放不下的设计归 misfit、不建模；
              写的位置上找不到启动器的归 env（这几样不用 Abaqus）。
              设计 A 用真的 Abaqus 走完一遍：一次要十几分钟到半小时，设 STEMLAB_ABAQUS_RUN=1 才跑

要旧系统的文件（只读；换了地方设 STEMLAB_LEGACY）、gmsh 和 Abaqus（启动器在哪照这个仓库的机器清单，操作台那一项的 programs）。
哪样没有，这里的测试跳过并说明原因：看到跳过，不等于那部分验过了。
Abaqus 装在哪是机器的事：叫有限元包的一方照包清单里的名字和版本，在机器清单里找到位置，放进 job.json 的 programs。
只建模、不求解的测试不要 Abaqus：job 里给一个假的启动器（一个空文件），包只核它在不在。
经 fea.run 的几条在这次测试自己的仓库拷贝（real_own_lab）里改写机器清单，写上这次要的 Abaqus 的位置。
external/ 不在检查的范围里，所以测试放在这里。
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import numpy as np
import pytest

from plugins.fea import given
from stemlab.contract import hashing
from stemlab.contract.formats import bone_model
from stemlab.contract.formats import declaration as d
from stemlab.contract.formats import package as package_format
from stemlab.contract.formats import stem_model
from stemlab.contract.formats.manifest import check_format, read_manifest
from stemlab.contract.formats.points import read_points
from stemlab.contract.machines import parse_machines
from stemlab.desk.core import start as starting
from stemlab.experiments import view
from stemlab.registry import register
from tests import real
from tests.plugins.fea_cases import kept, refused, rows_of, stages
from tests.science import tools
from tests_free import sawbone3406
from tests_free.derive_bed_f import oracle
from tests_free.sawbone3406 import SUMMARY, bone_folder

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "external" / "fem_abaqus"
LEGACY_JOB = "sb13_a105_91e458e3"              # 旧数据库 v0.14 里设计 A 的那一行
SLOW = os.environ.get("STEMLAB_ABAQUS_RUN") == "1"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DECL = _load("external/fem_abaqus/declarations.py", "fem_abaqus_declarations_4d")
BUILD = _load("external/fem_abaqus/build.py", "fem_abaqus_build_4d")
STEM_DECL = _load("external/stem_m1_3406/declarations.py", "stem_m1_3406_declarations_4d")
STEM_BUILD = _load("external/stem_m1_3406/build.py", "stem_m1_3406_build_4d")
KERNEL = _load("external/kernel_m1_3406/build.py", "kernel_m1_3406_build_4d")
BED_F = _load("external/derive_bed_f_named/declarations.py", "derive_bed_f_named_declarations_4d")    # 床支撑 F（名字引用，4e）
SHAPE_A = dict(STEM_DECL.A)                                 # 设计 A 的 12 个形状项
TEST = d.test_setting(DECL.FEM, "R0002")["values"]          # 测试轮的有限元设定
PLACE = d.test_setting(STEM_DECL.PLACEMENT, "R0001")["values"]
# 原来的 8 个条件：拆开以后它们是有限元设定里每个点能变的项，测试轮的取值就是设计 A 在旧数据库里用的
CONDITIONS = ("E_canc_MPa", "h_int_mm", "mu", "cycles", "load_N", "load_front_deg", "load_sagit_deg", "delta_mm")
# 3406 的骨模型（两个实体、标志点、材料）怎么造，在 tests_free/sawbone3406.py：4e 的测试也用


# ---------------------------------------------------------------- 造输入

def settings(**change) -> dict:
    """一个点上有限元设定的取值：测试轮的那一套，change 盖掉同名的，写 None 就是去掉这一项。"""
    values = {**TEST, **change}
    return {name: value for name, value in values.items() if value is not None}


def build_job(bone: Path, stem: Path | None, where: Path, values: dict | None = None, programs: dict | None = None) -> dict:
    """交给有限元包建模的 job。programs 是叫它的一方照机器清单找到的外部程序的位置：{名字: 位置}。
    骨模型照约定是两样：文件夹，和读成第 2 版的清单（盘上是第 1 版的也读成第 2 版）。"""
    return {"mode": "build", "bone_model": str(bone), "bone": bone_model.read(bone), "bone_id": tools.BONE_ID,
            "stem_model": None if stem is None else str(stem),
            "point": {"name": "A", "hash": "a" * 64}, "settings": settings() if values is None else values, "job": str(where),
            "programs": programs or {}}


def start(package: Path, source: Path, out: Path, env: dict | None = None) -> dict:
    """照核心的办法跑一次包：入口后面跟输入文件夹和输出文件夹，在包的文件夹里跑。返回 result.json 的内容。"""
    out.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([sys.executable, str(package / "code" / "main.py"), str(source), str(out)], cwd=package,
                          env=dict(os.environ, **tools.ENV, **(env or {})), capture_output=True, timeout=3600)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads((out / package_format.RESULT).read_bytes())


def run(package: Path, job: dict, where: Path, env: dict | None = None) -> dict:
    """交一个 job 给包，返回 result。"""
    (where / "ask").mkdir(parents=True, exist_ok=True)
    (where / "ask" / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return start(package, where / "ask", where / "out", env)


# ---------------------------------------------------------------- 读 Abaqus 的输入

def deck(path: Path) -> dict:
    """读这个包写的 Abaqus 输入：节点、节点集、单元、材料、截面、分析步，和整段文字。"""
    lines = path.read_text(encoding="ascii").splitlines()
    found = {"nodes": {}, "nsets": {}, "elements": {}, "materials": {}, "sections": {}, "steps": [], "text": "\n".join(lines)}
    i = 0

    def block(start: int) -> tuple[list[str], int]:
        rows = []
        while start < len(lines) and not lines[start].startswith("*"):
            rows.append(lines[start])
            start += 1
        return rows, start

    while i < len(lines):
        line, upper = lines[i], lines[i].upper()
        if upper == "*NODE":
            rows, i = block(i + 1)
            found["nodes"] = {int(row.split(",")[0]): tuple(float(part) for part in row.split(",")[1:]) for row in rows}
        elif upper.startswith("*NSET, NSET="):
            rows, i = block(i + 1)
            found["nsets"][line.split("=", 1)[1].strip()] = [int(part) for row in rows for part in row.split(",") if part.strip()]
        elif upper.startswith("*ELEMENT, TYPE="):
            kind, where = (part.split("=")[1].strip() for part in line.split(",")[1:3])
            rows, i = block(i + 1)
            found["elements"][where] = (kind, len(rows))
        elif upper.startswith("*MATERIAL, NAME="):
            E, nu = lines[i + 2].split(",")
            found["materials"][line.split("=", 1)[1].strip()] = (float(E), float(nu))
            i += 3
        elif upper.startswith("*SOLID SECTION"):
            params = dict(part.strip().split("=") for part in line.split(",")[1:])
            found["sections"][params["ELSET"]] = params["MATERIAL"]
            i += 1
        elif upper.startswith("*STEP"):
            params = dict(part.strip().split("=") for part in line.split(",")[1:])
            step = {"name": params.pop("NAME"), "params": params, "lines": []}
            i += 1
            while not lines[i].upper().startswith("*END STEP"):
                step["lines"].append(lines[i])
                i += 1
            found["steps"].append(step)
            i += 1
        else:
            i += 1
    return found


def unit(vector) -> list:
    size = math.sqrt(sum(part * part for part in vector))
    return [part / size for part in vector]


def sub(a, b):
    return [p - q for p, q in zip(a, b)]


def dot(a, b):
    return sum(p * q for p, q in zip(a, b))


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def anatomical(bone: Path) -> dict:
    """骨模型记的解剖坐标系：原点和三个轴（x 内侧、y 后方、z 沿干轴指向近端）。包加力、截远端都照它。"""
    return {key: bone_model.read(bone)["frame"][key] for key in ("origin", "x", "y", "z")}


def from_neck(listed: dict) -> dict:
    """这个包在 5b 以前自己算的那个坐标系（原来的 load_frame = shaft_neck），照原来的定义再算一遍：
    z 沿干轴指向近端，x 是颈轴投到垂直干轴的面上、指向内侧，y 指向后方。listed 是骨模型的清单（两个版本的标志点都有 xyz）。"""
    points = {name: listed["landmarks"][name]["xyz"] for name in listed["landmarks"]}
    z = unit(sub(points["shaft_proximal"], points["shaft_distal"]))
    neck = sub(points["head_center"], points["neck_center"])
    x = unit(sub(neck, [dot(neck, z) * part for part in z]))
    y = cross(z, x) if listed["side"] == "right" else cross(x, z)
    return {"x": x, "y": y, "z": z}


def level(frame: dict, point) -> float:
    """一个点沿干轴的高度：从解剖坐标系的原点量起。"""
    return dot(sub(point, frame["origin"]), frame["z"])


def expected_load(values: dict) -> list:
    """照原项目 model3d_v2.load_vector 的写法（Bergmann 2016）：载荷的坐标系里 x 内侧、y 后方、z 近端。"""
    tx, ty = math.tan(math.radians(values["load_front_deg"])), math.tan(math.radians(values["load_sagit_deg"]))
    fz = values["load_N"] / math.sqrt(1 + tx * tx + ty * ty)
    return [-tx * fz, ty * fz, -fz]


def to_bone(frame: dict, point) -> list:
    return [frame["origin"][k] + sum(point[axis] * frame[name][k] for axis, name in enumerate("xyz")) for k in range(3)]


def cload(step: dict) -> list:
    """一个加载步里每个节点上的力（三个分量）。"""
    parts = [line.split(",") for line in step["lines"] if line.startswith("HEADN,")]
    return [float(next(row[2] for row in parts if int(row[1]) == axis)) for axis in (1, 2, 3)]


# ---------------------------------------------------------------- 夹具

@pytest.fixture(scope="module")
def legacy() -> Path:
    """旧系统的文件夹。只读。"""
    wanted = [tools.LEGACY / "docs" / "freeze" / "M1-3406-v1_files.tar", tools.LEGACY / SUMMARY,
              *(tools.LEGACY / "v2" / "data" / "femur_3406" / file for file in tools.STEPS.values())]
    missing = [str(path) for path in wanted if not path.is_file()]
    if missing:
        pytest.skip(f"找不到旧系统的文件（{missing[0]}）。换地方了就设 STEMLAB_LEGACY")
    return tools.LEGACY


@pytest.fixture(scope="module")
def summary(legacy) -> dict:
    return json.loads((legacy / SUMMARY).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def works():
    """gmsh 加载得了。加载不了（比如安全软件还占着它的 DLL）就跳过：建模要划网格。"""
    try:
        import gmsh  # noqa: F401
    except (ImportError, OSError) as error:
        pytest.skip(f"gmsh 加载不了：{error}")


def _build(script: Path, legacy: Path, folder: Path, *more: str) -> Path:
    done = subprocess.run([sys.executable, str(script), str(legacy), str(folder), *more], capture_output=True, timeout=600,
                          env=dict(os.environ, **tools.ENV))
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return folder


@pytest.fixture(scope="module")
def built(legacy, tmp_path_factory) -> Path:
    """照 external/fem_abaqus 的做法现打一个有限元包。"""
    return _build(HERE / "build.py", legacy, tmp_path_factory.mktemp("fem") / "package")


@pytest.fixture(scope="module")
def stem_package(legacy, tmp_path_factory) -> Path:
    """照 external/stem_m1_3406 的做法现打一个柄空间包（4c）。"""
    return _build(REPO / "external" / "stem_m1_3406" / "build.py", legacy, tmp_path_factory.mktemp("stem") / "package")


@pytest.fixture(scope="module")
def bone(legacy, summary, tmp_path_factory) -> Path:
    return bone_folder(tmp_path_factory.mktemp("bone3406") / "bone", legacy, summary)


@pytest.fixture(scope="module")
def stem(stem_package, bone, works, tmp_path_factory) -> Path:
    """设计 A 的柄的模型：4c 的柄空间包照测试轮的放置设定交出来的。返回柄的模型的文件夹。"""
    where = tmp_path_factory.mktemp("stem-model")
    job = {"mode": "model", "bone_model": str(bone), "bone": bone_model.read(bone), "bone_id": tools.BONE_ID, "settings": PLACE,
           "point": {"name": "A", "hash": "a" * 64, "design": SHAPE_A}}
    (where / "ask").mkdir()
    (where / "ask" / "job.json").write_text(json.dumps(job), encoding="utf-8")
    said = start(stem_package, where / "ask", where / "out")
    assert said["status"] == "ok", said
    return where / "out" / given.MODEL


@pytest.fixture(scope="module")
def launcher(tmp_path_factory) -> dict:
    """只建模的测试交给包的 programs：Abaqus 的启动器是一个空文件。包只核它在不在，不去起它。"""
    fake = tmp_path_factory.mktemp("abaqus") / "abq-not-run.bat"
    fake.write_text("@echo this test only builds\n", encoding="ascii")
    return {"abaqus": str(fake)}


@pytest.fixture(scope="module")
def made_a(built, bone, stem, launcher, tmp_path_factory) -> tuple[dict, Path]:
    """设计 A 照测试轮的设定建模。返回（result，求解用的文件夹）。"""
    where = tmp_path_factory.mktemp("build-A")
    result = run(built, build_job(bone, stem, where / "solve", programs=launcher), where)
    return result, where / "solve"


@pytest.fixture(scope="module")
def bone_v2(legacy, summary, tmp_path_factory) -> Path:
    """3406 的骨模型，盘上就是第 2 版：完整的股骨，解剖坐标系照后髁连线定。两个实体和 bone 那一份是同样的两个文件。"""
    return sawbone3406.bone_folder_v2(tmp_path_factory.mktemp("bone3406-v2") / "bone", legacy, summary)


# 设定换值的两次建模：网格放粗一点，省时间。每一项换成什么、在输入里该看到什么，见 test_every_setting_reaches_the_deck
VARIANTS = {
    "penalty": settings(h_int_mm=3.0, h_far_mm=9.0, dist_min_mm=1.0, dist_max_mm=12.0, E_canc_MPa=9000.0,
                        override_region={"ref": "bone.region.cortical"}, mu=0.5, elastic_slip_um=1.2, cycles=3, nlgeom=True,
                        max_increments=500, initial_increment=0.1, min_increment=1e-06, max_increment=0.5,
                        distal_cut_mm=120.0, load_N=3000.0, load_front_deg=10.0, load_sagit_deg=-5.0,
                        load_point={"ref": "stem.feature.head_center"}, load_spread_mm=10.0, delta_mm=0.05,
                        field_outputs=["U", "RF", "S"], contact_outputs=["CSTRESS", "CDISP", "CSTATUS"], cpus=3),
    "lagrange": settings(h_int_mm=3.0, h_far_mm=9.0, tangential="lagrange", elastic_slip_um=None, interference_method="offset",
                         distal_from={"ref": "bone.landmark.head_center"}, distal_cut_mm=180.0),
}
FIXED_CHOICE = {"element", "models", "normal", "sliding", "distal"}     # 只有一种可选的值：换不了
ELSEWHERE = {"contact_faces"}       # 柄的模型只有一组面：换它另有一条测试（test_a_stem_touching_bone_outside_the_named_faces_is_refused）


@pytest.fixture(scope="module")
def varied(built, bone, stem, launcher, tmp_path_factory) -> dict:
    """设定换了值的两次建模。返回 {名字: (result, 求解用的文件夹)}。"""
    found = {}
    for name, values in VARIANTS.items():
        where = tmp_path_factory.mktemp(f"build-{name}")
        found[name] = (run(built, build_job(bone, stem, where / "solve", values, programs=launcher), where), where / "solve")
    return found


# ---------------------------------------------------------------- 包本身

def test_the_package_is_a_well_formed_fem(built):
    assert check_format("fem", built) == []
    listed = read_manifest(built)
    assert listed["declarations"] == DECL.DECLARATIONS, "清单里带的就是 declarations.py 的那份声明"
    assert listed["programs"] == [{"name": "abaqus", "version": "2025"}]
    assert listed["modes"] == ["build", "post"]
    roles = {column["name"]: column["role"] for column in listed["outputs"]}
    assert {name for name, role in roles.items() if role == "pre"} == {"n_tet", "n_pairs", "mesh_attempt", "h_mesh_mm"}, \
        "原内核给的建模前的量里，网格的 4 个由有限元包给"
    assert {column["name"] for column in KERNEL.EXTRA["labels"]} <= {name for name, role in roles.items() if role == "label"}, \
        "原内核给的标签，这个包都给"
    assert [name for name, role in roles.items() if role == "field"] == ["interface"]
    assert listed["inputs"]["stem"]["required"] is True and listed["inputs"]["stem"]["materials"] == ["elastic"]
    wanted = listed["inputs"]["bone"]
    assert bone_model.check_wanted(wanted) == [], "对骨模型的要求照契约的写法：fea.run 启动前照它核"
    assert {key: value for key, value in wanted.items() if key != "what"} == {
        "regions": {"cortical": [1, 1], "cancellous": [1, 1]}, "geometry": ["step"], "materials": ["elastic"],
        "landmarks": ["shaft_distal"], "frame": {"methods": ["shaft_condyles", "shaft_neck"], "unknown_anteversion": True}}, \
        "这个包自己的限制照实写在这里：皮质、松质各一个 STEP 实体，线弹性；干轴上的一个点；坐标系两种定法都收，前倾角不知道的也收"
    assert listed["test_round"] == {"inputs": {}}, "3406 的骨模型还没登记：测试轮的骨模型打包时用 --test-bone 写进来"


def test_both_bone_models_of_3406_have_what_the_package_asks_for(built, bone, bone_v2):
    """3406 的两份骨模型（盘上第 1 版的、盘上第 2 版照后髁连线定的）都合这个包写的要求。
    STL 的、带髓腔的骨不合，缺的是哪一样说得出来：这是这个包自己的限制，启动前照它的清单拦下，骨架里没有这一条。"""
    wanted = read_manifest(built)["inputs"]["bone"]
    assert check_format("bone_model", bone) == [] and check_format("bone_model", bone_v2) == []
    assert read_manifest(bone)["format"] == 1 and read_manifest(bone_v2)["format"] == 2
    assert bone_model.lacking(wanted, bone_model.read(bone)) == [] and bone_model.lacking(wanted, bone_model.read(bone_v2)) == []
    from tests.contract import bone_samples

    said = bone_model.lacking(wanted, bone_samples.manifest(bone_samples.good()))
    assert any("不收髓腔" in text for text in said) and any("几何" in text and "stl" in text for text in said), said


def test_a_version_1_bone_model_records_the_frame_this_package_used_to_work_out(bone, bone_v2, summary):
    """盘上第 1 版的骨模型读成第 2 版，记的解剖坐标系是照颈轴定的：就是这个包 5b 以前自己从标志点算的那一个，所以旧骨模型上的数不变。
    盘上第 2 版、照后髁连线定的那一份，记的是旧系统的模型坐标；两个绕干轴差 3.8°（3406 的前倾角）。"""
    old, was = anatomical(bone), from_neck(read_manifest(bone))
    for axis in "xyz":
        assert old[axis] == pytest.approx(was[axis], abs=1e-12), axis
    new = anatomical(bone_v2)
    turned, origin = sawbone3406.model_frame(summary)
    for axis, row in zip("xyz", turned):
        assert new[axis] == pytest.approx(list(row), abs=1e-9), axis
    assert new["origin"] == pytest.approx(list(origin), abs=1e-9) and new["z"] == pytest.approx(old["z"], abs=1e-12)
    assert math.degrees(math.acos(dot(new["x"], old["x"]))) == pytest.approx(abs(summary["anteversion_deg"]), abs=1e-6)


def test_the_names_it_refers_to_are_there(built, stem_package):
    """有限元声明里引用的名字：柄上的，4c 的柄空间包在清单里答应给；骨上的，骨模型第 1 版有。"""
    promised = given.promised(read_manifest(stem_package))
    names = {"bone.region": {"cortical", "cancellous"},
             "bone.landmark": {"head_center", "neck_center", "shaft_proximal", "shaft_distal", "lesser_trochanter"}, **promised}
    listed = read_manifest(built)
    fem = d.find(listed["declarations"], "fem")
    assert d.check_setting(d.test_setting(fem, "R0002"), fem, of="R0002", use="test", names=names) == []
    for name, values in VARIANTS.items():
        assert d.check_setting(dict(d.test_setting(fem, "R0002"), values=values), fem, names=names) == [], name


def test_the_test_round_bone_is_written_in_when_it_is_named(legacy, tmp_path):
    folder = _build(HERE / "build.py", legacy, tmp_path / "package", "--test-bone", "R0007")
    assert check_format("fem", folder) == []
    assert read_manifest(folder)["test_round"] == {"inputs": {"bone": {"item": "R0007"}}}


def test_the_frozen_files_are_taken_byte_for_byte(built, legacy):
    with tarfile.open(legacy / "docs" / "freeze" / "M1-3406-v1_files.tar") as archive:
        frozen = {Path(member.name).name: archive.extractfile(member).read() for member in archive.getmembers() if member.isfile()}
    digest = hashlib.sha256()
    for name in BUILD.HASHED:
        digest.update(frozen[name])
    assert digest.hexdigest()[:10] == BUILD.CODE_HASH == KERNEL.CODE_HASH
    assert BUILD.HASHED == KERNEL.HASHED and set(BUILD.TAKEN) < set(BUILD.HASHED)
    folder = built / "code" / "legacy"
    for name in BUILD.TAKEN:
        assert (folder / "v2" / name).read_bytes() == frozen[name], name
    assert not [name for name in set(BUILD.HASHED) - set(BUILD.TAKEN) if (folder / "v2" / name).exists()], "用不到的冻结文件不带"
    for rel in BUILD.RUNTIME:
        assert (folder / rel).read_bytes() == (legacy / rel).read_bytes(), rel
    carried = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}
    assert carried == {f"v2/{name}" for name in BUILD.TAKEN} | set(BUILD.RUNTIME), "旧代码只带这几个文件"


def test_nothing_is_packed_when_the_frozen_files_are_not_the_frozen_ones(tmp_path):
    """冻结时存下的原字节包对不上 code_hash，就不打包。不用真的旧系统：造一个假的。"""
    fake = tmp_path / "legacy"
    (fake / "docs" / "freeze").mkdir(parents=True)
    with tarfile.open(fake / "docs" / "freeze" / "M1-3406-v1_files.tar", "w") as archive:
        for name in BUILD.HASHED:
            content = f"# not the frozen {name}\n".encode()
            member = tarfile.TarInfo(f"v2/{name}")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    done = subprocess.run([sys.executable, str(HERE / "build.py"), str(fake), str(tmp_path / "package")], capture_output=True,
                          timeout=600, env=dict(os.environ, **tools.ENV))
    assert done.returncode != 0 and BUILD.CODE_HASH in done.stderr.decode("utf-8", "replace")
    assert not (tmp_path / "package" / "manifest.json").exists()


def test_the_package_passes_its_own_self_check(built, works, tmp_path):
    listed = read_manifest(built)
    for number, one in enumerate(listed["selftest"]):
        got = start(built, built / one["input"], tmp_path / f"out-{number}")
        expected = json.loads((built / one["expected"]).read_bytes())
        assert package_format.differences(expected, got, listed["tolerance"]) == [], one["name"]


# ---------------------------------------------------------------- 建模：设计 A

def test_design_a_is_built_and_says_how(made_a, built, stem):
    result, where = made_a
    assert result["status"] == "built" and result["reason"] == "", result
    listed = read_manifest(built)
    assert set(result["pre"]) == {column["name"] for column in listed["outputs"] if column["role"] == "pre"}
    assert result["pre"]["mesh_attempt"] == 1 and result["pre"]["h_mesh_mm"] == TEST["h_int_mm"]
    command = result["solve"]["command"]
    assert command[0] == "{python}" and Path(command[1]).resolve() == (built / "code" / "solve.py").resolve(), command
    assert command[2:4] == ["m_fric", str(TEST["cpus"])], command
    assert "timeout_s" not in result["solve"], "求解的时限由运行设定管，包不另给"
    for name in ("m_fric.inp", "mesh3d.npz", "model3d.json"):
        assert (where / name).is_file(), name
    model = json.loads((where / "model3d.json").read_text(encoding="utf-8"))
    assert model["n_pairs"] == result["pre"]["n_pairs"] and sum(model["n_tet"].values()) == result["pre"]["n_tet"]
    area = stem_model.read(stem)["templating"]["interface_area_mm2"]
    assert 0.98 < model["interface_area_mm2"] / area < 1.0, \
        "接触面就是柄的模型里的那组面：网格是折面，比曲面小一点（4c 量过：2 mm 网格小 0.34%）"
    assert (result["pre"]["n_tet"], result["pre"]["n_pairs"]) == (30686, 4016) and model["interface_area_mm2"] == pytest.approx(
        2427.85, abs=0.01), "和 4d 记的一样（2026-11-18；旧数据库里设计 A 的界面节点对也是 4016）：5b 改成读骨模型记的坐标系以后，数没有变"


def test_the_deck_takes_the_materials_from_the_two_models_and_the_setting(made_a, bone, stem):
    result, where = made_a
    found = deck(where / "m_fric.inp")
    given_ = {region["role"]: region["material"] for region in bone_model.read(bone)["regions"]}       # 交给包的那一份清单里的
    titanium = stem_model.read(stem)["regions"][0]["material"]
    assert found["materials"] == {"CORTICAL": (given_["cortical"]["E"], given_["cortical"]["nu"]),
                                  "CANCELLOUS": (TEST["E_canc_MPa"], given_["cancellous"]["nu"]),
                                  "STEM": (titanium["E"], titanium["nu"])}, "柄的材料照柄的模型（钛合金），不再写死在包里"
    assert found["materials"]["CORTICAL"] == (sawbone3406.MATERIALS["cortical"]["E_MPa"], 0.3), "盘上第 1 版写的 E_MPa 读成了 E"
    assert found["sections"] == {"CORTEX": "CORTICAL", "CANC": "CANCELLOUS", "STEM": "STEM"}
    assert {kind for kind, _ in found["elements"].values()} == {TEST["element"]}
    assert sum(count for _, count in found["elements"].values()) == result["pre"]["n_tet"]


def test_the_bone_is_cut_where_the_stem_model_and_the_setting_say(made_a, bone, stem):
    """骨在截骨面以下（照柄的模型的 placement.cut），远端在小转子那一层以下 150 mm 截断、截断面上的节点三个方向都固定。"""
    import numpy as np

    _, where = made_a
    found = deck(where / "m_fric.inp")
    mesh = np.load(where / "mesh3d.npz")
    lookup = {int(label): row for label, row in zip(mesh["node_labels"], mesh["nodes"])}
    cut = stem_model.read(stem)["placement"]["cut"]
    bone_nodes = {int(n) for part in ("cortex_conn", "cancellous_conn") for n in mesh[part].ravel()}
    assert max(dot(sub(lookup[n], cut["point"]), cut["normal"]) for n in bone_nodes) < 1e-6, "骨都在截骨面以下"
    frame = anatomical(bone)
    lt = read_manifest(bone)["landmarks"]["lesser_trochanter"]["xyz"]
    bottom = level(frame, lt) - TEST["distal_cut_mm"]
    assert min(level(frame, lookup[n]) for n in bone_nodes) == pytest.approx(bottom, abs=1e-6)
    fixed = found["nsets"]["FIXED"]
    assert len(fixed) >= 10 and all(abs(level(frame, found["nodes"][n]) - bottom) < 1e-4 for n in fixed)
    assert set(fixed) == {n for n in bone_nodes if abs(level(frame, lookup[n]) - bottom) < 1e-4}, "截断面上的骨的节点都固定，别的不固定"
    for step in found["steps"]:
        assert ("FIXED, 1, 3" in step["lines"]) == (step["name"] in ("PRESSFIT", "RELEASE")), step["name"]


def test_the_load_is_put_where_and_how_the_setting_says(made_a, bone):
    """关节力：合力的大小和两个倾角照设定，方向在骨模型记的解剖坐标系里；平均分到柄上离作用点 load_spread_mm 以内的节点上。"""
    import numpy as np

    _, where = made_a
    found = deck(where / "m_fric.inp")
    listed = read_manifest(bone)
    frame = anatomical(bone)
    head = listed["landmarks"]["head_center"]["xyz"]          # load_point 的测试轮取值是 bone.landmark.head_center
    spread = TEST["load_spread_mm"]
    loaded = found["nsets"]["HEADN"]
    mesh = np.load(where / "mesh3d.npz")
    lookup = {int(label): row for label, row in zip(mesh["node_labels"], mesh["nodes"])}
    stem_nodes = {int(n) for n in mesh["stem_conn"].ravel()}
    near = {n for n in stem_nodes if math.dist(lookup[n], head) <= spread + 1e-6}
    assert len(loaded) >= 10 and set(loaded) == near, "柄上离作用点这么远以内的节点"
    assert not set(loaded) & ({int(n) for n in mesh["pair_bone"]} | {int(n) for n in mesh["pair_stem"]}), "加载的节点不碰界面"
    model = json.loads((where / "model3d.json").read_text(encoding="utf-8"))
    assert [dot(model["load_N"], frame[axis]) for axis in "xyz"] == pytest.approx(expected_load(TEST), abs=1e-9), \
        "合力照原项目的写法（Bergmann 2016）：三个分量各乘上骨模型记的三个轴"
    assert model["load_frame_N"] == pytest.approx(expected_load(TEST), abs=1e-9)
    assert model["frames"]["load"] == {axis: pytest.approx(frame[axis], abs=1e-15) for axis in "xyz"}, "用的就是骨模型记的那三个轴"
    steps = {step["name"]: step for step in found["steps"]}
    assert cload(steps["LOAD"]) == pytest.approx([part / len(loaded) for part in model["load_N"]], rel=1e-8), "平均分到这些节点上"
    assert cload(steps["LOAD2"]) == cload(steps["LOAD"]) and cload(steps["UNLOAD"]) == [0.0, 0.0, 0.0]
    assert "HEADN, 1, 3" in steps["PRESSFIT"]["lines"], "压配那一步头是固定的（原模型的写法）"


def test_the_interface_is_the_named_face_group_in_contact(made_a, stem):
    import numpy as np

    _, where = made_a
    found = deck(where / "m_fric.inp")
    text = found["text"]
    mesh = np.load(where / "mesh3d.npz")
    slip = TEST["elastic_slip_um"] * 1e-3 / TEST["h_int_mm"]
    assert f"*FRICTION, SLIP TOLERANCE={slip:.9g}\n{TEST['mu']:.9g}," in text, "罚摩擦的弹性滑移照设定，除以界面处的网格尺寸"
    assert "*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=HARD" in text and "SMALL SLIDING" in text
    assert f"*CLEARANCE, SLAVE=S_BONE, MASTER=S_STEM, TABULAR\nNS_INTERF, {-TEST['delta_mm']:.9g}" in text
    interfered = set(found["nsets"]["NS_INTERF"])
    assert interfered | set(found["nsets"].get("NS_NOINT", [])) == {int(n) for n in mesh["pair_bone"]}
    assert interfered == {int(n) for n, cortex in zip(mesh["pair_bone"], mesh["pair_cortex"]) if not cortex}, \
        "与皮质相邻的节点不施过盈"
    stem_rows = {int(label): row for label, row in zip(mesh["node_labels"], mesh["nodes"])}
    assert max(math.dist(stem_rows[int(a)], stem_rows[int(b)]) for a, b in zip(mesh["pair_bone"], mesh["pair_stem"])) < 1e-12, \
        "过盈照 clearance 给：几何不动，孪生节点和骨侧节点重合"
    model = json.loads((where / "model3d.json").read_text(encoding="utf-8"))
    assert model["contact_faces"] == "interface" and model["off_group_faces"] == 0


def test_the_steps_and_outputs_follow_the_setting(made_a):
    _, where = made_a
    found = deck(where / "m_fric.inp")
    assert [step["name"] for step in found["steps"]] == ["PRESSFIT", "RELEASE", "LOAD", "UNLOAD", "LOAD2"]
    for step in found["steps"]:
        assert step["params"] == {"INC": str(TEST["max_increments"])}, "几何非线性关着：不写 NLGEOM（Abaqus/Standard 默认关）"
        static = step["lines"][step["lines"].index("*STATIC") + 1]
        assert static == f"{TEST['initial_increment']:.9g}, 1, {TEST['min_increment']:.9g}, {TEST['max_increment']:.9g}"
        assert "*NODE OUTPUT" in step["lines"] and "U, RF" in step["lines"] and "S, E, ELSE, EVOL" in step["lines"]
        assert "CSTRESS, CDISP, CSTATUS, CFORCE, CNAREA" in step["lines"]
    assert "*CONTACT INTERFERENCE, SHRINK" in found["steps"][0]["lines"]


# ---------------------------------------------------------------- 力照骨模型记的解剖坐标系加

def test_the_load_follows_the_frame_the_bone_model_records(built, bone_v2, stem, launcher, made_a, summary, tmp_path):
    """同一个设计、同一份设定，骨模型换成盘上第 2 版、照后髁连线定的那一份（实体还是那两个文件）：
    合力在旧系统的模型坐标里就是旧系统加的那个向量（两个倾角直接量在它的冠状面、矢状面里），
    和配第 1 版骨模型建的那一次（照颈轴定）绕干轴差 3.8°。远端截断、加载的节点、材料都不跟着变。网格放粗，省时间。"""
    values = settings(h_int_mm=3.0, h_far_mm=9.0)
    result = run(built, build_job(bone_v2, stem, tmp_path / "solve", values, programs=launcher), tmp_path)
    assert result["status"] == "built", result
    model = json.loads((tmp_path / "solve" / "model3d.json").read_text(encoding="utf-8"))
    turned, origin = sawbone3406.model_frame(summary)           # 旧系统的模型坐标：三行是内侧、后方、近端
    assert [dot(model["load_N"], row) for row in turned] == pytest.approx(expected_load(TEST), abs=1e-6), \
        "合力在旧系统的模型坐标里，就是旧系统照这两个倾角加的那个向量"
    before = json.loads((made_a[1] / "model3d.json").read_text(encoding="utf-8"))
    assert before["load_frame_N"] == model["load_frame_N"], "三个分量是同一组数：变的只是坐标系"
    force = expected_load(TEST)
    across = (force[0] ** 2 + force[1] ** 2) / TEST["load_N"] ** 2          # 合力垂直干轴的那部分占多少
    apart = 1.0 - dot(unit(model["load_N"]), unit(before["load_N"]))
    assert apart == pytest.approx(across * (1.0 - math.cos(math.radians(summary["anteversion_deg"]))), rel=1e-6) and apart > 1e-4, \
        "两次的合力方向不一样：垂直干轴的那部分绕干轴转了 3.8°"
    for axis, row in zip("xyz", turned):
        assert model["frames"]["load"][axis] == pytest.approx(list(row), abs=1e-9), axis
    assert math.degrees(math.acos(dot(model["frames"]["load"]["x"], before["frames"]["load"]["x"]))) == pytest.approx(
        abs(summary["anteversion_deg"]), abs=1e-6), "两次的内侧方向绕干轴差 3406 的前倾角"
    assert model["truncation"]["normal"] == pytest.approx(before["truncation"]["normal"], abs=1e-12)
    assert dot(sub(model["truncation"]["point"], before["truncation"]["point"]), model["truncation"]["normal"]) == pytest.approx(
        0.0, abs=1e-9), "远端还是截在同一层：干轴是同一根，小转子那一层没有变"
    assert model["materials"] == before["materials"] and model["load_point"] == before["load_point"]


def test_a_bone_manifest_that_was_not_read_as_version_2_is_refused(built, bone, stem, launcher, tmp_path):
    """约定是叫包的一方把清单读成第 2 版交来。交来的还是盘上原样的第 1 版，或者根本没带，包不猜，说出来。"""
    job = build_job(bone, stem, tmp_path / "solve", programs=launcher)
    for number, handed in enumerate((read_manifest(bone), None)):
        result = run(built, {**job, "bone": handed}, tmp_path / str(number))
        assert result["status"] == "error" and "第 2 版" in result["reason"] and "bone" in result["reason"], result


# ---------------------------------------------------------------- 设定是真用上的

def test_every_setting_reaches_the_deck(varied, made_a, bone, stem):
    """每一项换一个值（两次建模合起来），输入跟着变。只有一种可选的值的那几项换不了。"""
    import numpy as np

    names = {item["name"] for item in DECL.FEM["items"]}
    changed = {name for values in VARIANTS.values() for name, value in values.items() if value != TEST.get(name)}
    changed |= {name for values in VARIANTS.values() for name in TEST if name not in values}
    assert changed | FIXED_CHOICE | ELSEWHERE == names, \
        f"有限元声明加了项：这里也要加上换它一个值的情形（{sorted(names - changed - FIXED_CHOICE - ELSEWHERE)}）"
    base = deck(made_a[1] / "m_fric.inp")
    listed = read_manifest(bone)
    frame = anatomical(bone)
    lt = listed["landmarks"]["lesser_trochanter"]["xyz"]

    result, where = varied["penalty"]
    values = VARIANTS["penalty"]
    assert result["status"] == "built", result
    found = deck(where / "m_fric.inp")
    model = json.loads((where / "model3d.json").read_text(encoding="utf-8"))
    assert result["pre"]["h_mesh_mm"] == 3.0 and result["pre"]["n_tet"] < made_a[0]["pre"]["n_tet"]
    assert model["mesh"] == {"h_int_mm": 3.0, "h_far_mm": 9.0, "dist_min_mm": 1.0, "dist_max_mm": 12.0}, "网格的四项照设定交给 gmsh"
    assert found["materials"]["CORTICAL"] == (9000.0, 0.3) and found["materials"]["CANCELLOUS"] == (155.0, 0.3), \
        "E_canc_MPa 盖的是 override_region 引用的那个区域，另一个照骨模型"
    assert f"*FRICTION, SLIP TOLERANCE={1.2e-3 / 3.0:.9g}\n0.5," in found["text"]
    assert f"NS_INTERF, {-0.05:.9g}" in found["text"]
    assert [step["name"] for step in found["steps"]] == ["PRESSFIT", "RELEASE", "LOAD", "UNLOAD", "LOAD2", "UNLOAD2", "LOAD3"]
    for step in found["steps"]:
        assert step["params"] == {"INC": "500", "NLGEOM": "YES"}
        assert step["lines"][step["lines"].index("*STATIC") + 1] == "0.1, 1, 1e-06, 0.5"
        assert "S" in step["lines"] and "U, RF" in step["lines"] and "CSTRESS, CDISP, CSTATUS" in step["lines"]
        assert not any("ELSE" in line or "CFORCE" in line for line in step["lines"])
    mesh = np.load(where / "mesh3d.npz")
    lookup = {int(label): row for label, row in zip(mesh["node_labels"], mesh["nodes"])}
    bone_nodes = {int(n) for part in ("cortex_conn", "cancellous_conn") for n in mesh[part].ravel()}
    assert min(level(frame, lookup[n]) for n in bone_nodes) == pytest.approx(level(frame, lt) - 120.0, abs=1e-6)
    head = to_bone(stem_model.read(stem)["placement"]["frame"], stem_model.read(stem)["features"]["head_center"])
    loaded = found["nsets"]["HEADN"]
    stem_nodes = {int(n) for n in mesh["stem_conn"].ravel()}
    assert set(loaded) == {n for n in stem_nodes if math.dist(lookup[n], head) <= 10.0 + 1e-6}, \
        "作用点照 stem.feature.head_center（柄的模型的坐标换到骨上），范围照 load_spread_mm"
    assert [dot(model["load_N"], frame[axis]) for axis in "xyz"] == pytest.approx(expected_load(values), abs=1e-9)
    steps = {step["name"]: step for step in found["steps"]}
    assert cload(steps["LOAD3"]) == pytest.approx([part / len(loaded) for part in model["load_N"]], rel=1e-8)
    assert result["solve"]["command"][3] == "3", "核数照设定"

    result, where = varied["lagrange"]
    assert result["status"] == "built", result
    found = deck(where / "m_fric.inp")
    assert "*FRICTION, LAGRANGE" in found["text"] and "SLIP TOLERANCE" not in found["text"]
    assert "*CLEARANCE" not in found["text"], "过盈照 offset 给：柄侧节点沿法向挪出去，不写 *CLEARANCE"
    mesh = np.load(where / "mesh3d.npz")
    lookup = {int(label): row for label, row in zip(mesh["node_labels"], mesh["nodes"])}
    moved = [float(np.dot(lookup[int(s)] - lookup[int(b)], normal)) for b, s, normal, gap in
             zip(mesh["pair_bone"], mesh["pair_stem"], mesh["pair_normal"], mesh["pair_interf"]) if gap > 0]
    assert moved and max(abs(value - TEST["delta_mm"]) for value in moved) < 1e-9
    bone_nodes = {int(n) for part in ("cortex_conn", "cancellous_conn") for n in mesh[part].ravel()}
    head = listed["landmarks"]["head_center"]["xyz"]
    assert min(level(frame, lookup[n]) for n in bone_nodes) == pytest.approx(level(frame, head) - 180.0, abs=1e-6), \
        "截断照 distal_from 引用的那个标志点量起"
    assert base["materials"]["CANCELLOUS"] == (TEST["E_canc_MPa"], 0.3)


def test_a_stem_touching_bone_outside_the_named_faces_is_refused(built, bone, stem, launcher, tmp_path, works):
    """contact_faces 指的那组面就是柄和骨接触的全部：柄的模型另造一组只有一半的面，指它，柄在这组面以外也碰到骨，归出错。"""
    import gmsh

    model = stem_model.read(stem)
    shutil.copytree(stem, tmp_path / "stem")
    path = os.environ.get("PATH", "")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        faces = [tag for _, tag in gmsh.model.occ.importShapes(str(stem / model["faces"]["interface"]["file"]))]
        gmsh.model.occ.synchronize()
        tip = model["features"]["tip"][2]
        upper = [tag for tag in faces if gmsh.model.occ.getCenterOfMass(2, tag)[2] < 0.5 * tip]
        gmsh.model.occ.remove([(2, tag) for tag in faces if tag not in upper], recursive=True)
        gmsh.model.occ.synchronize()
        gmsh.write(str(tmp_path / "stem" / "faces" / "upper.step"))
    finally:
        gmsh.finalize()
        os.environ["PATH"] = path           # gmsh 初始化时会把这个进程的 PATH 截短；放回去
    assert 0 < len(upper) < len(faces)
    model["faces"]["upper"] = {"region": "stem", "file": "faces/upper.step"}
    model["files"] = sorted(model["files"] + ["faces/upper.step"])
    (tmp_path / "stem" / stem_model.MANIFEST).write_text(json.dumps(model), encoding="utf-8")
    assert stem_model.check(tmp_path / "stem") == []
    values = settings(h_int_mm=4.0, h_far_mm=10.0, contact_faces={"ref": "stem.faces.upper"})
    result = run(built, build_job(bone, tmp_path / "stem", tmp_path / "solve", values, programs=launcher), tmp_path)
    assert result["status"] == "error" and "upper" in result["reason"], result


# ---------------------------------------------------------------- 别的结局

def test_a_point_without_a_stem_model_is_refused(built, bone, launcher, tmp_path):
    result = run(built, build_job(bone, None, tmp_path / "solve", programs=launcher), tmp_path)
    assert result["status"] == "error" and "无植入物" in result["reason"], result


def test_a_launcher_that_is_not_where_the_machine_list_says_is_an_environment_problem(built, bone, stem, tmp_path):
    missing = tmp_path / "nowhere" / "abq2025.bat"
    result = run(built, build_job(bone, stem, tmp_path / "solve", programs={"abaqus": str(missing)}), tmp_path)
    assert result["status"] == "env" and str(missing) in result["reason"], result


def test_without_the_place_of_abaqus_in_the_job_it_is_an_environment_problem(built, bone, stem, tmp_path):
    """包不自己找启动器（不看环境变量，不用原项目配置里的位置）：位置要由叫它的一方照机器清单给。"""
    result = run(built, build_job(bone, stem, tmp_path / "solve"), tmp_path, {"STEMLAB_ABAQUS": r"D:\SIMULIA\Commands\abq2025.bat"})
    assert result["status"] == "env" and "机器清单" in result["reason"] and "abaqus 2025" in result["reason"], result


def test_a_setting_that_is_not_filled_is_said_by_name(built, bone, stem, launcher, tmp_path):
    result = run(built, build_job(bone, stem, tmp_path / "solve", settings(distal_cut_mm=None), programs=launcher), tmp_path)
    assert result["status"] == "error" and "distal_cut_mm" in result["reason"], result


def post_job(where: Path, bone: Path, stem: Path) -> dict:
    return {**build_job(bone, stem, where), "mode": "post"}


def test_post_without_a_solver_record_is_an_environment_problem(built, made_a, bone, stem, tmp_path):
    shutil.copytree(made_a[1], tmp_path / "solve")
    result = run(built, post_job(tmp_path / "solve", bone, stem), tmp_path)
    assert result["status"] == "env" and "solve.json" in result["reason"], result
    assert set(result["keep"]["mesh"]) == {"mesh3d.npz", "model3d.json"} and result["keep"]["settings"] == ["m_fric.inp"]


@pytest.mark.parametrize(("said", "status"), [({"status": "L4", "reason": "license unavailable after 30 tries", "code": "license_unavailable"}, "env"),
                                              ({"status": "L4", "reason": "TOO MANY ATTEMPTS MADE FOR THIS INCREMENT"}, "not_converged"),
                                              ({"status": "L4", "reason": "analysis not completed (see .msg)"}, "error")])
def test_post_of_a_solve_that_did_not_finish(built, made_a, bone, stem, tmp_path, said, status):
    shutil.copytree(made_a[1], tmp_path / "solve")
    (tmp_path / "solve" / "solve.json").write_text(json.dumps({"m_fric": said}), encoding="utf-8")
    result = run(built, post_job(tmp_path / "solve", bone, stem), tmp_path)
    assert result["status"] == status and result["steps"]["done"] == 0, result


# ---------------------------------------------------------------- 经真的 fea.run

def derive_package(folder: Path, which: str = "derive_bed_f_named") -> Path:
    """现打一个床支撑 F 的推导量定义：照名字引用的（给 fea.run），或者 derive_bed_f，旧常数的那个（参照包那条用的）。"""
    done = subprocess.run([sys.executable, str(REPO / "external" / which / "build.py"), str(folder)],
                          capture_output=True, timeout=600, env=dict(os.environ, **tools.ENV))
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return folder


def registered(legacy: Path, summary: dict, tmp: Path, stem_package: Path, built: Path, maker=bone_folder) -> dict:
    """在这本空账里登记 3406 的骨模型、4c 的柄空间包、这个有限元包、床支撑 F 的推导量定义（照名字引用的那个，4e）。
    maker 造骨模型的文件夹：默认是盘上第 1 版的，sawbone3406.bone_folder_v2 是盘上第 2 版、照后髁连线定的。"""
    bone = register.register_external("bone_model", "sawbone3406-model", source=maker(tmp / "bone", legacy, summary),
                                      note="测试用：3406 的两个实体，标志点照旧系统找出的", by="tester", bone_id=tools.BONE_ID, new_bone=True)
    stem = register.register_external("stem_space", "m1-3406", source=stem_package, note="测试用：现打的 M1 柄空间包", by="tester")
    fem = register.register_external("fem", "abaqus-m1", source=built, note="测试用：现打的 Abaqus 有限元包", by="tester")
    derive = register.register_external("derive_def", "bed-f", source=derive_package(tmp / "derive"),
                                        note="测试用：床支撑 F（支撑区照名字引用定）", by="tester")
    return {"bone": bone, "stem": stem, "fem": fem, "derive": derive}


def experiment(tmp: Path, items: dict, rows) -> str:
    """一个 fea.run：原来的 8 个条件在有限元设定里写成每个点给，截骨高度在放置设定里每个点给，推导量设定照测试轮的取值。"""
    values = {"placement": real.declared(STEM_DECL.PLACEMENT, items["stem"]["id"], h_cut=real.PER_POINT),
              "fem_setting": real.declared(DECL.FEM, items["fem"]["id"], **{name: real.PER_POINT for name in CONDITIONS}),
              "derive_setting": real.declared(BED_F.DERIVE, items["derive"]["id"])}
    return real.fea_run(tmp, rows, packages_={name: items[name] for name in ("stem", "fem", "derive")}, settings=values,
                        bone=items["bone"])


def legacy_cloud(row: dict):
    """旧数据库里这一行的界面点云（参照包那一套算的，在旧模型坐标里），写成旧的床支撑 F 要的那几个数组。没有就是 None。"""
    shard = tools.LEGACY_DB.parent / "fields" / f"{row.get('field_shard')}.npz"
    if not row.get("field_shard") or not shard.is_file():
        return None
    held, index = np.load(shard, allow_pickle=False), int(row["field_index"])
    start_, stop = int(held["off"][index]), int(held["off"][index + 1])
    assert row["job_id"] == str(held["job_id"][index])
    return {"X": held["X"][start_:stop], "area": held["area"][start_:stop], "d_canal": held["d_canal"][start_:stop],
            "collar": held["collar"][start_:stop].astype(bool), "P0": held["frame"][index][0], "stem_axis": held["frame"][index][1]}


def bed_support_side_by_side(tmp: Path, new: dict, cloud, model: dict, summary: dict, landmarks: dict, old_row: dict) -> list[str]:
    """设计 A 的床支撑 F 四种算法并排，给人看，不判：旧常数或名字引用，配旧点云或这次的点云。
    旧常数的两个数是旧的包（external/derive_bed_f）算的，点云在旧模型坐标里交给它；名字引用配旧点云的那个是照定义另算的。"""
    turned, origin = sawbone3406.model_frame(summary)
    package = derive_package(tmp / "derive-old", "derive_bed_f")
    values = d.test_setting(BED_F.DERIVE, "none")["values"]

    def old_way(name: str, arrays: dict) -> dict:
        (tmp / name).mkdir()
        np.savez(tmp / name / "interface.npz", **arrays)
        return run(package, {"fields": {"interface": str(tmp / name / "interface.npz")}, "labels": {}, "pre": {}, "point": {}},
                   tmp / name)["derived"]

    frame = model["placement"]["frame"]
    there = old_way("old-on-new", {"X": (np.asarray(cloud["X"], float) - origin) @ turned.T, "area": cloud["area"], "d_canal": cloud["d_canal"],
                                   "collar": cloud["collar"], "P0": (np.asarray(frame["origin"], float) - origin) @ turned.T,
                                   "stem_axis": np.asarray(frame["z"], float) @ turned.T})
    lines = ["", "设计 A 的床支撑 F（mm，括号里是支撑区里的节点数），四种算法并排，不判：",
             f"  {'':14}{'旧点云（参照包那一套算的）':>22}{'这次 fea.run 的点云':>22}"]
    was = legacy_cloud(old_row)
    if was is None:
        lines.append("  旧数据库里找不到设计 A 的界面点云：左边一列没有")
        here = renamed = None
    else:
        here = old_way("old-on-old", was)
        renamed = oracle.of_cloud({**was, "X": was["X"] @ turned + origin}, values, model, landmarks)

    def cell(found) -> str:
        return f"{'':>22}" if found is None else f"{found['F_mm']:>14.2f} ({found['F_n_nodes']})".rjust(22)

    lines.append(f"  {'旧常数、旧算法':<10}{cell(here)}{cell(there)}")
    lines.append(f"  {'名字引用':<13}{cell(renamed)}{cell(new)}")
    lines.append("  左上是参照包那条的数，右下是这次 fea.run 交的数")
    return lines


def point(name: str, h_cut: float) -> dict:
    return {"name": name, "bone_id": tools.BONE_ID, "design": dict(SHAPE_A), "conditions": {name: TEST[name] for name in CONDITIONS},
            "placement": {"h_cut": h_cut}, "derive": {}, "reason": "测试"}


def watch(made: str, seconds: float) -> None:
    """像值守那样一遍一遍地看，直到这一轮结束。求解要很久，所以隔几秒看一次。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        starting.poll(made)
        if view.view(made).rounds[-1].result is not None:
            return
        time.sleep(5.0)
    raise AssertionError(f"{made} 等了 {seconds} 秒还没结束：{real.tasks(made)}")


def desk_programs(repo: Path, programs: list) -> None:
    """这次测试自己的仓库拷贝里，操作台这台的机器清单只写这几个外部程序（名字、版本、位置）。"""
    listed = json.loads((repo / "machines.json").read_bytes())
    for machine in listed["machines"]:
        if machine["role"] == "desk":
            machine["programs"] = programs
    (repo / "machines.json").write_bytes(hashing.canonical(listed) + b"\n")


def abaqus_here() -> Path | None:
    """这个仓库的机器清单里，操作台这台写的 Abaqus 2025 的位置。没写就是 None。"""
    desk = next(machine for machine in parse_machines(json.loads((REPO / "machines.json").read_bytes())) if machine.role == "desk")
    where = desk.program("abaqus", "2025")
    return Path(where) if where else None


def test_fea_run_with_the_split_packages_without_abaqus(real_own_lab, data, legacy, summary, stem_package, built, works, tmp_path):
    """不用 Abaqus。操作台的机器清单里没写 Abaqus 2025，启动前就拒。写了位置以后：放不下的设计归 misfit、不建模；
    放得下的在写的位置上找不到启动器，建模那一步归 env、不求解。启动前的核对认两个包的清单、声明和 names；
    包的自检在这台机器上第一次用时跑。"""
    items = registered(legacy, summary, tmp_path, stem_package, built)
    said = refused(experiment(tmp_path, items, [point("fits", 16.0)]))
    assert "有限元包要 abaqus 2025" in said and "机器清单" in said, said
    desk_programs(real_own_lab, [{"name": "abaqus", "version": "2025", "path": str(tmp_path / "nowhere" / "abq2025.bat")}])
    made = experiment(tmp_path, items, [point("fits", 16.0), point("tight", 24.0)])
    began = starting.start(made)
    assert began.ok, began
    real.run(made, seconds=900)
    assert real.tasks(made) == {"fits": ("failed", "env"), "tight": ("done", "misfit")}, view.view(made).rounds[-1].problems
    assert stages(made, "tight") == ["stem"], "放不下的不再去建模"
    assert [stage for stage in stages(made, "fits") if stage != "modeled"] == ["stem", "build"], "找不到启动器，不去求解"


@pytest.mark.skipif(not SLOW, reason="设计 A 用真的 Abaqus 走一遍要十几分钟到半小时：设 STEMLAB_ABAQUS_RUN=1 才跑")
@pytest.mark.parametrize("stored", ["v1", "v2"])
def test_design_a_goes_through_fea_run_with_abaqus(real_own_lab, data, legacy, summary, stem_package, built, works, tmp_path, capsys,
                                                   stored):
    """真的 Abaqus：设计 A 走完出柄的模型、建模、求解、后处理、推导量、交数据、归档；放不下的那个归 misfit。
    Abaqus 的位置照这个仓库的机器清单，写进这次测试自己的仓库拷贝的机器清单里。
    算得对不对暂时不判（2026-11-16 定的）：和旧数据库里设计 A 的那一行并排打出来，不拿差去挡。
    两根骨模型各走一遍（第 5 步的 5b），实体是同样的两个文件：
        v1  盘上第 1 版的，读出来是照颈轴定的解剖坐标系：合力和旧系统的绕干轴差 3.8°（4d 记的转动、微动小 7% 到 11% 就是它）
        v2  盘上第 2 版、照后髁连线定的：合力的方向就是旧系统的那一个"""
    launcher = abaqus_here()
    if launcher is None or not launcher.is_file():
        pytest.skip(f"这个仓库的机器清单里，操作台没写 Abaqus 2025 的位置，或者那个位置上没有启动器（{launcher}）")
    desk_programs(real_own_lab, [{"name": "abaqus", "version": "2025", "path": str(launcher)}])
    items = registered(legacy, summary, tmp_path, stem_package, built, bone_folder if stored == "v1" else sawbone3406.bone_folder_v2)
    made = experiment(tmp_path, items, [point("A", 16.0), point("tight", 24.0)])
    began = starting.start(made)
    assert began.ok, began
    watch(made, seconds=4 * 3600)
    status = view.view(made)
    assert real.tasks(made) == {"A": ("done", "finished"), "tight": ("done", "misfit")}, status.rounds[-1].problems
    assert [stage for stage in stages(made, "A") if stage != "modeled"] == ["stem", "build", "solve", "post"]
    assert stages(made, "tight") == ["stem"]

    listed = read_manifest(real.output(made, "data"))
    fem = read_manifest(built)
    roles = [(column["name"], column["role"]) for column in listed["columns"]]
    assert roles == ([(name, "design") for name in SHAPE_A] + [(name, "condition") for name in sorted(CONDITIONS)]
                     + [("h_cut", "condition")] + [(column["name"], "pre") for column in STEM_BUILD.OUTPUTS]
                     + [(column["name"], column["role"]) for column in fem["outputs"]]
                     + [(column["name"], "derived") for column in json.loads(
                         (tmp_path / "derive" / "manifest.json").read_bytes())["columns"]]), roles
    row = rows_of(made)["A"]
    values = row["values"]
    assert {name: values[name] for name in SHAPE_A} == SHAPE_A and values["h_cut"] == 16.0
    assert values["n_pairs"] > 1000 and values["mesh_attempt"] == 1 and values["h_mesh_mm"] == 2.0
    load = math.sqrt(sum(values[f"load_{axis}_N"] ** 2 for axis in "xyz"))
    assert load == pytest.approx(TEST["load_N"], rel=1e-6) and values["load_z_N"] < -0.8 * load
    assert values["iface_force_err_load"] < 1e-3 and values["iface_force_err_load2"] < 1e-3, "界面上接触力之和和外载平衡"
    assert row["fields"]["interface"].endswith(".npz")
    frozen = status.frozen
    assert listed["made_by"]["kernel"] is None and listed["made_by"]["fem"] == {"package": frozen["fem"][0]["hash"]}
    files = kept(made, "A")
    assert {"m_fric.inp", "model3d.json", "mesh3d.npz", "m_fric.sta", "m_fric.msg", "solve.json", "stem_model.json"} <= set().union(*files.values())
    archive = real.output(made, "archive")
    solved = next(row for row in read_points(archive / "index.jsonl") if row["task"] == "A" and row["file"].endswith("/solve.json"))
    record = json.loads((Path(read_manifest(archive)["root"]) / solved["file"]).read_bytes())["m_fric"]
    assert record["status"] == "OK" and record["release"].startswith("2025"), "求解器报的版本就是清单里写的 Abaqus 2025"
    assert Path(record["launcher"]) == launcher, "用的启动器就是机器清单里写的那个"

    # 床支撑 F（4e）：推导量定义照名字引用，从这次的点云、柄的模型和骨模型算出来的，和照定义另算的一样
    cloud = np.load(real.output(made, "data") / row["fields"]["interface"])
    shown = next(row for row in read_points(archive / "index.jsonl") if row["task"] == "A" and row["file"].endswith("/stem_model.json"))
    model = json.loads((Path(read_manifest(archive)["root"]) / shown["file"]).read_bytes())
    landmarks = read_manifest(tmp_path / "bone")["landmarks"]
    wanted = oracle.of_cloud(cloud, d.test_setting(BED_F.DERIVE, "none")["values"], model, landmarks)
    bed = {name: values[name] for name in wanted}
    assert bed == pytest.approx(wanted, rel=1e-9) and bed["F_n_nodes"] > 100, f"数据里的 {bed}，照定义另算的 {wanted}"
    assert listed["made_by"]["derive"] == {"package": frozen["derive"][0]["hash"]} and listed["made_by"]["settings"]["derive"]

    old = tools.legacy_rows(LEGACY_JOB)[0]
    with capsys.disabled():
        frame = "盘上第 1 版，照颈轴定" if stored == "v1" else "盘上第 2 版，照后髁连线定"
        print(f"\n设计 A：fea.run（柄空间包加有限元包；骨模型{frame}） 和 旧数据库（参照包那一套） 并排，不判")
        for name in ("rot_first_deg", "rot_rev_deg", "rot_perm_deg", "subsid_first_um", "f1_p95_um", "f1_first_p95_um",
                     "contact_area_load2_mm2", "open_frac_load2", "area_frac_gt150", "iface_force_err_load", "n_pairs",
                     "bone_total_mm3"):
            print(f"  {name:24} 新 {values.get(name)!s:>24}  旧 {old.get(name)!s:>24}")
        print("\n".join(bed_support_side_by_side(tmp_path, bed, cloud, model, summary, landmarks, old)))
