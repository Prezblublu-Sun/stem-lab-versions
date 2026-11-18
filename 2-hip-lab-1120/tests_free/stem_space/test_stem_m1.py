"""拆内核 4c：M1 的柄空间包（external/stem_m1_3406）。目标见 docs/拆内核.md 的“4c”。

照 external/stem_m1_3406/build.py 现打一个包，在 Sawbones 3406 上跑：
    清单      过契约的核对，带 4b 的两份声明和 names；有限元声明引用的柄上的名字都在 names 里
    原字节    用到的 4 个冻结文件和冻结时存下的一样；别的运行时文件和旧系统工作树里的一样
    自检      包自带的样本过得去
    模板化    同一批设计，结果和参照包（external/kernel_m1_3406 现打的内核包）一样
    柄的模型  设计 A 交出的过契约的核对，也过 fea.run 冻结的 stem_wrong；几何和清单里写的对得上
    别的结局  放不下的归 misfit；不是 3406 的骨归 error
    设定      放置设定换一个值，结果跟着变：包用的是设定，不是自己留的常数

要旧系统的文件（只读；换了地方设 STEMLAB_LEGACY）和 gmsh。哪样没有，这里的测试跳过并说明原因：看到跳过，不等于那部分验过了。
两个包各自在这台机器上留一份股骨距离场的缓存（%LOCALAPPDATA%/stemlab/ 下），第一次跑要多等一两分钟。
external/ 不在检查的范围里，所以测试放在这里。
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from plugins.fea import given
from stemlab import hooks
from stemlab.contract import hashing
from stemlab.contract.formats import bone_model
from stemlab.contract.formats import declaration as d
from stemlab.contract.formats import package as package_format
from stemlab.contract.formats import stem_model
from stemlab.contract.formats.manifest import check_format, make_manifest, read_manifest, write_manifest
from stemlab.contract.formats.points import read_points
from stemlab.desk.core import start as starting
from stemlab.experiments import view
from stemlab.registry import register
from tests import packages, real
from tests.plugins.fea_cases import kept, rows_of, stages
from tests.science import tools

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "external" / "stem_m1_3406"
CAP = 1.5                   # 平端的帽高，mm：算作这个柄空间本身的（declarations.py 开头的说明）
HEAD_RADIUS = 14.0          # 假体头的半径，mm：同上（旧系统 v2/config_v2a.yaml 的 prosthesis.head_radius_mm）
# 3406 的股骨头心，在骨模型文件的坐标里：旧系统自己拟合出来、记在 v2/out/femur_3406_summary.json 里的 head_c
# （离厂家说明书上的头心 1.16 mm，那份摘要里也记着这个差）
HEAD_3406 = (50.66093682772986, 1.6714987757428237, 109.12888423325442)
MESH_ONLY = {"n_tet", "n_pairs", "mesh_attempt", "h_mesh_mm"}      # 原内核给的建模前的量里，属于网格的那 4 个：留给有限元包
# 参照包给设计 A 建模（界面网格 2 mm）以后，界面上 4020 个节点对的面积之和，mm2：mesh3d.npz 的 pair_area。
# 2026-11-18 在这台机器上用 external/kernel_m1_3406 现打的包跑出来的，拿来核交出的面组是不是同一片面
REFERENCE_INTERFACE_MM2 = 2427.7137931448924


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DECL = _load("external/stem_m1_3406/declarations.py", "stem_m1_3406_declarations_4c")
BUILD = _load("external/stem_m1_3406/build.py", "stem_m1_3406_build")
FEM = _load("external/fem_abaqus/declarations.py", "fem_abaqus_declarations_4c")
KERNEL = _load("external/kernel_m1_3406/build.py", "kernel_m1_3406_build_4c")
SHAPE_A = {item["name"]: item["test"] for item in DECL.DESIGN["items"]}        # 设计 A 的 12 个形状项


# ---------------------------------------------------------------- 造输入

def placement(**change) -> dict:
    """放置设定在一个点上的取值：测试轮的那一套（设计 A 用的），change 盖掉同名的，写 None 就是去掉这一项。"""
    values = {**d.test_setting(DECL.PLACEMENT, "R0001")["values"], **change}
    return {name: value for name, value in values.items() if value is not None}


def fixed(e: float, **change) -> dict:
    """入口固定在 e：那几档偏移就没有了。"""
    return placement(entry="fixed", e=e, offset_min_mm=None, offset_max_mm=None, offset_step_mm=None, **change)


def sample(count: int, seed: int) -> list[tuple[str, dict]]:
    """在声明的设计空间里随机取几个设计。同一个种子取出的是同一批。"""
    draw = random.Random(seed)
    return [(f"s{number}", {item["name"]: draw.uniform(item["range"]["min"], item["range"]["max"]) for item in DECL.DESIGN["items"]})
            for number in range(count)]


def near(count: int, seed: int, spread: float = 0.2) -> list[tuple[str, dict]]:
    """在设计 A 附近随机取几个设计：每一项离 A 不超过它范围的 spread 倍。全空间里随机取的多数放不下，这样取的多数放得下。"""
    draw = random.Random(seed)
    return [(f"n{number}", {item["name"]: min(item["range"]["max"], max(item["range"]["min"], item["test"] + draw.uniform(
        -spread, spread) * (item["range"]["max"] - item["range"]["min"]))) for item in DECL.DESIGN["items"]}) for number in range(count)]


def as_kernel(design: dict, settings: dict) -> dict:
    """同一个设计照参照包的写法：截骨高度和入口偏移算在设计项里。"""
    return {**design, "h_cut": settings["h_cut"], "e": "rule" if settings["entry"] == "rule" else settings["e"]}


# 拿去和参照包比的几批：批名 ->（放置设定，[(设计的名字, 设计)]）
BATCHES = {
    "rule16": (placement(), [("A", SHAPE_A)] + sample(12, seed=3406) + near(6, seed=16)),
    "rule20": (placement(h_cut=20.0), [("A", SHAPE_A)] + near(3, seed=20)),
    "rule24": (placement(h_cut=24.0), [("A", SHAPE_A)]),
    "fixed": (fixed(2.0), [("A", SHAPE_A)] + near(2, seed=2)),
}
# 放置设定每一项换一个值：项名 ->（换过的设定，拿 rule16 那一批里的哪个设计来试）。e 跟着 entry 一起换；
# section_points 只管柄的实体，另有一条测试。查得稀还是密对设计 A 没有差别，所以那一项换一个有差别的设计（s9）
VARIANTS = {
    "h_cut": (placement(h_cut=24.0), "A"),
    "ref_cut_mm": (placement(ref_cut_mm=10.0), "A"),
    "neck_axis": (placement(neck_axis="detector"), "A"),
    "entry": (fixed(2.0), "A"),
    "offset_min_mm": (placement(offset_min_mm=2.0), "A"),
    "offset_max_mm": (placement(offset_max_mm=-2.0), "A"),
    "offset_step_mm": (placement(offset_step_mm=3.0), "A"),
    "collar_rule": (placement(collar_rule="wrap_fit"), "A"),
    "neck_radius_mm": (placement(neck_radius_mm=13.0), "A"),
    "margin_check": (placement(margin_check="sparse"), "s9"),
    "area_min_mm2": (placement(area_min_mm2=600.0), "A"),
    "area_max_mm2": (placement(area_max_mm2=400.0), "A"),
    "bisection_iters": (placement(bisection_iters=6), "A"),
    "min_tip_area_mm2": (placement(min_tip_area_mm2=150.0), "A"),
}


def template_job(bone: Path, settings: dict, designs) -> dict:
    return {"mode": "template", "bone_model": str(bone), "bone_id": tools.BONE_ID, "settings": settings,
            "designs": [{"name": name, "design": design} for name, design in designs]}


def model_job(bone: Path, settings: dict, design: dict | None = None, name: str = "A") -> dict:
    return {"mode": "model", "bone_model": str(bone), "bone_id": tools.BONE_ID, "settings": settings,
            "point": {"name": name, "hash": "a" * 64, "design": dict(SHAPE_A if design is None else design)}}


def start(package: Path, source: Path, out: Path) -> dict:
    """照核心的办法跑一次包：入口后面跟输入文件夹和输出文件夹，在包的文件夹里跑。返回 result.json 的内容。"""
    out.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([sys.executable, str(package / "code" / "main.py"), str(source), str(out)], cwd=package,
                          env=dict(os.environ, **tools.ENV), capture_output=True, timeout=1800)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads((out / package_format.RESULT).read_bytes())


def run(package: Path, job: dict, where: Path) -> tuple[dict, Path]:
    """交一个 job 给包。返回（result，输出文件夹）。"""
    (where / "ask").mkdir(parents=True)
    (where / "ask" / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return start(package, where / "ask", where / "out"), where / "out"


def bone_folder(folder: Path, files: dict, bone_id: str = tools.BONE_ID) -> Path:
    """一个骨模型文件夹。包只认骨标识和两个实体，所以清单只写它用得到的几项（和科学验收的夹具一样）。"""
    (folder / "solids").mkdir(parents=True)
    for name, content in files.items():
        if isinstance(content, Path):
            shutil.copyfile(content, folder / "solids" / f"{name}.step")
        else:
            (folder / "solids" / f"{name}.step").write_bytes(content)
    listed = {"format": 1, "kind": "bone_model", "files": sorted(f"solids/{name}.step" for name in files), "bone_id": bone_id,
              "solids": {name: {"file": f"solids/{name}.step"} for name in files}}
    (folder / "manifest.json").write_text(json.dumps(listed), encoding="utf-8")
    return folder


# ---------------------------------------------------------------- 夹具

@pytest.fixture(scope="module")
def legacy() -> Path:
    """旧系统的文件夹。只读。"""
    wanted = [tools.LEGACY / "docs" / "freeze" / "M1-3406-v1_files.tar",
              *(tools.LEGACY / "v2" / "data" / "femur_3406" / file for file in tools.STEPS.values())]
    missing = [str(path) for path in wanted if not path.is_file()]
    if missing:
        pytest.skip(f"找不到旧系统的文件（{missing[0]}）。换地方了就设 STEMLAB_LEGACY")
    return tools.LEGACY


@pytest.fixture(scope="module")
def works():
    """gmsh 加载得了。加载不了（比如安全软件还占着它的 DLL）就跳过：模板化要的距离场、柄的实体都靠它。"""
    try:
        import gmsh  # noqa: F401
    except (ImportError, OSError) as error:
        pytest.skip(f"gmsh 加载不了：{error}")


@pytest.fixture(scope="module")
def built(legacy, tmp_path_factory) -> Path:
    """照 external/stem_m1_3406 的做法现打一个柄空间包。"""
    return _build(HERE / "build.py", legacy, tmp_path_factory.mktemp("stem") / "package")


@pytest.fixture(scope="module")
def reference(legacy, tmp_path_factory) -> Path:
    """照 external/kernel_m1_3406 的做法现打一个内核包：参照包。"""
    return _build(REPO / "external" / "kernel_m1_3406" / "build.py", legacy, tmp_path_factory.mktemp("kernel") / "package")


def _build(script: Path, legacy: Path, folder: Path, *more: str) -> Path:
    done = subprocess.run([sys.executable, str(script), str(legacy), str(folder), *more], capture_output=True, timeout=600,
                          env=dict(os.environ, **tools.ENV))
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return folder


@pytest.fixture(scope="module")
def bone(legacy, tmp_path_factory) -> Path:
    """3406 的骨模型：两个实体就是旧系统用的那两个 STEP。"""
    source = legacy / "v2" / "data" / "femur_3406"
    return bone_folder(tmp_path_factory.mktemp("bone3406"), {name: source / file for name, file in tools.STEPS.items()})


@pytest.fixture(scope="module")
def templated(built, reference, bone, works, tmp_path_factory) -> tuple[dict, dict]:
    """同一批设计让两个包各模板化一遍。返回（这个包的，参照包的），都是 {批名-设计名: 一行}。"""
    where = tmp_path_factory.mktemp("templated")
    old_job = template_job(bone, {}, [(f"{batch}-{name}", as_kernel(design, settings))
                                      for batch, (settings, designs) in BATCHES.items() for name, design in designs])

    def mine(batch: str) -> dict:
        settings, designs = BATCHES[batch]
        result, _ = run(built, template_job(bone, settings, designs), where / batch)
        assert "designs" in result, result
        return {f"{batch}-{row['name']}": row for row in result["designs"]}

    first = mine("rule16")                  # 先跑一批：缓存不在的话由它建好，后面几批并着跑
    with ThreadPoolExecutor(4) as pool:
        old = pool.submit(run, reference, old_job, where / "reference")
        rest = list(pool.map(mine, [batch for batch in BATCHES if batch != "rule16"]))
    got = dict(first)
    for rows in rest:
        got.update(rows)
    said = old.result()[0]
    assert "designs" in said, said
    return got, {row["name"]: row for row in said["designs"]}


@pytest.fixture(scope="module")
def handed(built, bone, works, tmp_path_factory) -> tuple[dict, Path, dict]:
    """设计 A 出柄的模型。返回（result，包的输出文件夹，交给包的 job）。"""
    job = model_job(bone, placement())
    result, out = run(built, job, tmp_path_factory.mktemp("model-A"))
    return result, out, job


@pytest.fixture(scope="module")
def varied(built, bone, works, templated, tmp_path_factory) -> dict:
    """放置设定每一项换一个值，各模板化一遍。返回 {项名: result}。"""
    where = tmp_path_factory.mktemp("varied")
    designs = dict(BATCHES["rule16"][1])

    def one(name: str) -> dict:
        settings, design = VARIANTS[name]
        return run(built, template_job(bone, settings, [(design, designs[design])]), where / name)[0]

    with ThreadPoolExecutor(4) as pool:
        return dict(zip(VARIANTS, pool.map(one, VARIANTS)))


# ---------------------------------------------------------------- 读几何、算坐标

def shapes(path: Path) -> dict:
    """用 gmsh 读一个 STEP：几个体、体积、包围盒，每个面的面积和质心。"""
    import gmsh

    kept = os.environ.get("PATH", "")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        occ.importShapes(str(path))
        occ.synchronize()
        volumes = [tag for _, tag in gmsh.model.getEntities(3)]
        faces = [{"area": occ.getMass(2, tag), "center": list(occ.getCenterOfMass(2, tag))} for _, tag in gmsh.model.getEntities(2)]
        return {"volumes": len(volumes), "volume": sum(occ.getMass(3, tag) for tag in volumes), "faces": faces,
                "box": list(gmsh.model.getBoundingBox(-1, -1))}
    finally:
        gmsh.finalize()
        os.environ["PATH"] = kept           # gmsh 初始化时会把这个进程的 PATH 截短；放回去


def sub(a, b):
    return [p - q for p, q in zip(a, b)]


def dot(a, b):
    return sum(p * q for p, q in zip(a, b))


def length(a):
    return math.sqrt(dot(a, a))


def to_bone(frame: dict, point) -> list:
    """柄自己的坐标系里的点，换到骨模型的坐标系里。"""
    return [frame["origin"][k] + sum(point[axis] * frame[name][k] for axis, name in enumerate("xyz")) for k in range(3)]


def turned(frame: dict, direction) -> list:
    """骨模型坐标系里的方向，换到柄自己的坐标系里。"""
    return [dot(direction, frame[name]) for name in "xyz"]


def to_stem(frame: dict, point) -> list:
    return turned(frame, sub(point, frame["origin"]))


class Given:
    """stem_wrong 要的那一点 handle：它只问柄空间包放在哪。"""

    def __init__(self, stem: Path):
        self.stem = stem

    def input(self, name: str) -> Path:
        assert name == "stem"
        return self.stem


# ---------------------------------------------------------------- 包本身

def test_the_package_is_a_well_formed_stem_space(built):
    assert check_format("stem_space", built) == []
    listed = read_manifest(built)
    assert listed["declarations"] == DECL.DECLARATIONS, "清单里带的就是 declarations.py 的两份声明"
    assert set(listed["modes"]) == {"template", "model"} and listed["programs"] == []
    assert set(listed["names"]) == set(given.NAME_PARTS) and all(listed["names"][part] for part in given.NAME_PARTS)
    assert listed["outputs"] and all(column["role"] == "pre" for column in listed["outputs"])
    assert {column["name"] for column in listed["outputs"]} == {column["name"] for column in KERNEL.EXTRA["pre"]} - MESH_ONLY, \
        "原内核给的建模之前就知道的量里，模板化的那几个由柄空间包给，网格的那几个留给有限元包"
    assert listed["inputs"]["bone"]["bone_id"] == [tools.BONE_ID]
    assert listed["test_round"] == {"inputs": {}}, "3406 的骨模型还没登记：测试轮的骨模型打包时用 --test-bone 写进来"


def test_the_names_the_fem_declaration_refers_to_are_promised(built):
    """4b 的有限元声明里引用的柄上的名字（stem.faces.interface），这个包在清单里答应一定给。"""
    promised = given.promised(read_manifest(built))
    names = {"bone.region": {"cortical", "cancellous"}, "bone.landmark": set(bone_model.LANDMARKS), **promised}   # 骨模型第 1 版必有的五个
    assert d.check_setting(d.test_setting(FEM.FEM, "R0002"), FEM.FEM, names=names) == []
    referred = [item["test"]["ref"] for item in FEM.FEM["items"] if item["type"] == "ref" and item["test"]["ref"].startswith("stem.")]
    assert referred == ["stem.faces.interface"], "有限元声明引用的柄上的名字变了：这里跟着核"
    assert d.check_setting(dict(d.test_setting(FEM.FEM, "R0002"), values={
        **d.test_setting(FEM.FEM, "R0002")["values"], "load_point": {"ref": "stem.feature.head_center"}}), FEM.FEM, names=names) == [], \
        "关节力也可以指到柄的模型上的假体头心"


def test_the_test_round_settings_fit_the_declarations(built):
    listed = read_manifest(built)
    design, place = (d.find(listed["declarations"], name) for name in ("design", "placement"))
    assert d.check_design(SHAPE_A, design) == []
    assert d.check_setting(d.test_setting(place, "R0001"), place, of="R0001", use="test") == []
    assert d.check_point({"h_cut": 20.0}, dict(d.test_setting(place, "R0001"), values={
        **d.test_setting(place, "R0001")["values"], "h_cut": dict(d.PER_POINT)}), place) == [], "截骨高度可以每个点给"


def test_the_test_round_bone_is_written_in_when_it_is_named(legacy, tmp_path):
    folder = _build(HERE / "build.py", legacy, tmp_path / "package", "--test-bone", "R0007")
    assert check_format("stem_space", folder) == []
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


# ---------------------------------------------------------------- 模板化：和参照包一样

def test_templating_gives_what_the_reference_kernel_gives(templated):
    mine, old = templated
    assert set(mine) == set(old)
    for name in sorted(old):
        for part in ("feasible", "info"):       # 放不放得下；放得下的每个量、放不下的原因，一位不差
            assert mine[name][part] == old[name][part], f"{name} 的 {part}：这个包 {mine[name][part]}，参照包 {old[name][part]}"
    fits = [row["feasible"] for row in old.values()]
    assert fits.count(True) >= 8 and fits.count(False) >= 8, f"放得下的、放不下的都要比到不少：{fits}"
    assert old["rule16-A"]["feasible"] and old["fixed-A"]["feasible"] and not old["rule24-A"]["feasible"]
    assert old["fixed-A"]["info"]["e_mm"] == 2.0


# ---------------------------------------------------------------- 柄的模型

def test_the_stem_model_of_design_a_passes_the_contract_and_the_fea_check(handed, built, templated):
    result, out, job = handed
    assert result["status"] == "ok" and result["reason"] == "", result
    assert result["pre"] == templated[0]["rule16-A"]["info"], "出柄的模型时模板化的量，和只模板化时给的一样"
    assert set(result["pre"]) == {column["name"] for column in read_manifest(built)["outputs"]}
    assert stem_model.check(out / given.MODEL) == []
    assert given.stem_wrong(Given(built), job, out) == []


def test_the_stem_model_says_what_the_manifest_promised(handed, built):
    _, out, job = handed
    model = stem_model.read(out / given.MODEL)
    have = hooks.stem_names(model)
    for part, wanted in given.promised(read_manifest(built)).items():
        assert wanted <= have[part], f"{part} 少了 {sorted(wanted - have[part])}"
    assert model["design"] == job["point"]["design"] == SHAPE_A
    assert model["dimension"] == "3d" and model["placement"]["removed"] is None and model["placement"]["landmarks"] == []
    assert handed[0]["pre"].items() <= model["templating"].items(), "模板化的量也抄在柄的模型里"
    (region,) = model["regions"]
    config = (built / "code" / "legacy" / "v2" / "config_v2a.yaml").read_text(encoding="utf-8")
    assert region["name"] == "stem" and region["role"] == "body" and region["geometry"]["kind"] == "solid"
    assert region["material"] == {"model": "elastic", "E": 110000.0, "nu": 0.3} and "titanium: {E: 110000.0, nu: 0.3}" in config, \
        "柄的材料照旧系统配置里的钛合金"
    assert model["faces"]["interface"]["region"] == "stem"


def test_the_stem_is_placed_where_templating_put_it(handed):
    """清单里的姿态、截骨面、特征点和轴互相对得上，也对得上骨：头心复位，截骨面离头心就是设定的截骨高度。"""
    result, out, job = handed
    model = stem_model.read(out / given.MODEL)
    frame, cut = model["placement"]["frame"], model["placement"]["cut"]
    features, axes = model["features"], model["axes"]
    head = to_bone(frame, features["head_center"])
    assert length(sub(head, HEAD_3406)) < 1e-3, "假体头心就是股骨头心（头心复位）：换到骨模型文件的坐标里，就是旧系统找到的那个头心"
    assert dot(sub(head, cut["point"]), cut["normal"]) == pytest.approx(job["settings"]["h_cut"], abs=1e-6), \
        "截骨面离头心就是截骨高度，法向指向头那一侧"
    assert length(sub(to_bone(frame, features["neck_base"]), cut["point"])) < 1e-6, "假体颈的底面中心就是截骨中心"
    assert abs(dot(sub(to_bone(frame, features["shoulder"]), cut["point"]), cut["normal"])) < 1e-6, "肩部中心在截骨面上"
    assert length(sub(features["shoulder"], features["neck_base"])) == pytest.approx(abs(result["pre"]["e_mm"]), abs=1e-6), \
        "肩部中心离截骨中心就是入口偏移"
    along = axes["stem_axis"]["direction"]
    assert along == pytest.approx([0.0, 0.0, 1.0], abs=1e-9), "柄自己的坐标系：z 沿柄轴指向远端"
    assert axes["stem_axis"]["point"] == features["shoulder"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)
    assert sub(features["tip"], features["shoulder"]) == pytest.approx([(SHAPE_A["L"] + CAP) * part for part in along], abs=1e-9), \
        "柄尖在柄轴上，离肩部是柄长加平端的帽高"
    assert axes["neck_axis"]["point"] == features["neck_base"]
    assert axes["neck_axis"]["direction"] == pytest.approx(turned(frame, cut["normal"]), abs=1e-9), "颈轴就是截骨面的法向"
    shaft = turned(frame, [0.0, 0.0, 1.0])              # 3406 的文件坐标里 z 大致沿骨干指向近端
    tilt = math.degrees(math.acos(-dot(along, shaft)))
    assert abs(tilt - result["pre"]["alpha_placed_deg"]) < 5.0, f"柄轴和骨干的夹角 {tilt:.1f}° 大致就是插入角"


def test_the_solid_and_the_interface_are_what_the_manifest_says(handed, works):
    result, out, job = handed
    folder = out / given.MODEL
    model = stem_model.read(folder)
    frame, cut = model["placement"]["frame"], model["placement"]["cut"]
    solid = shapes(folder / model["regions"][0]["geometry"]["file"])
    assert solid["volumes"] == 1, "柄体、假体颈、假体头并成一个实体"
    assert solid["box"][5] == pytest.approx(model["features"]["tip"][2], abs=1e-4), "实体沿柄轴伸到柄尖为止"
    ball = [face for face in solid["faces"] if length(sub(face["center"], model["features"]["head_center"])) < 2.0]
    assert len(ball) == 1 and 0.8 < ball[0]["area"] / (4.0 * math.pi * HEAD_RADIUS ** 2) < 1.0, \
        "假体头是绕着头心的一个球面，被颈占掉一小块"

    where, normal = to_stem(frame, cut["point"]), turned(frame, cut["normal"])

    def below(face: dict) -> bool:
        return dot(sub(face["center"], where), normal) < -1e-6

    patch = shapes(folder / model["faces"]["interface"]["file"])
    under = sorted(face["area"] for face in solid["faces"] if below(face))
    assert patch["volumes"] == 0 and patch["faces"] and all(below(face) for face in patch["faces"])
    assert sorted(face["area"] for face in patch["faces"]) == pytest.approx(under, rel=1e-6), \
        "界面就是实体在截骨面以下的那些面，不多不少"
    assert 0 < len(under) < len(solid["faces"]), "截骨面上露出来的那一块、假体颈、假体头不算界面"
    area = sum(under)
    assert area == pytest.approx(model["templating"]["interface_area_mm2"], rel=1e-6)
    assert 1.0 < area / REFERENCE_INTERFACE_MM2 < 1.01, \
        "和参照包建模时柄和骨真接触上的那片面一样大：它那边是 2 mm 的折面网格，比曲面小一点"


def test_the_number_of_section_points_changes_the_cad_not_the_stem(handed, built, bone, works, tmp_path):
    """section_points 只改柄的实体怎么分片：模板化的量不变，界面的面积几乎不变。原项目划不成网格时就换它重建柄。"""
    result, out = run(built, model_job(bone, placement(section_points=24)), tmp_path)
    assert result["status"] == "ok" and result["pre"] == handed[0]["pre"]
    assert stem_model.check(out / given.MODEL) == []
    coarse = stem_model.read(out / given.MODEL)["templating"]["interface_area_mm2"]
    fine = stem_model.read(handed[1] / given.MODEL)["templating"]["interface_area_mm2"]
    assert coarse != fine and coarse == pytest.approx(fine, rel=1e-2)


# ---------------------------------------------------------------- 别的结局

def test_a_design_that_does_not_fit_is_a_misfit_without_a_stem_model(built, bone, works, templated, tmp_path):
    result, out = run(built, model_job(bone, BATCHES["rule24"][0]), tmp_path)
    assert result["status"] == "misfit" and result["pre"] == {}
    assert result["reason"] == templated[0]["rule24-A"]["info"]["reason"], "为什么放不下，和模板化时说的一样"
    assert not (out / given.MODEL).exists()


def test_a_bone_it_was_not_made_for_is_refused(built, legacy, tmp_path):
    """这个包只认 3406 的那两个实体。别的骨、或者骨标识对而实体不是那两个文件的，都说出原因，不算。"""
    fake = {"cortical": b"ISO-10303-21; another cortical shell\n", "cancellous": b"ISO-10303-21; another core\n"}
    other = bone_folder(tmp_path / "other", fake, bone_id="femur042")
    renamed = bone_folder(tmp_path / "renamed", fake)
    for number, (folder, said) in enumerate(((other, "femur042"), (renamed, "哈希"))):
        result, _ = run(built, template_job(folder, placement(), [("A", SHAPE_A)]), tmp_path / f"template-{number}")
        assert result.get("status") == "error" and said in result["reason"] and "designs" not in result, result
        result, out = run(built, model_job(folder, placement()), tmp_path / f"model-{number}")
        assert result["status"] == "error" and said in result["reason"] and result["pre"] == {}, result
        assert not (out / given.MODEL).exists()


def test_a_setting_that_is_not_filled_is_said_by_name(built, bone, tmp_path):
    """放置设定少了一项，包说出是哪一项，不拿自己的默认值顶上。"""
    short = {name: value for name, value in placement().items() if name != "ref_cut_mm"}
    result, out = run(built, model_job(bone, short), tmp_path)
    assert result["status"] == "error" and "ref_cut_mm" in result["reason"], result
    assert not (out / given.MODEL).exists()


# ---------------------------------------------------------------- 放置设定是真用上的

def test_every_placement_setting_changes_what_comes_out(varied, templated):
    assert set(VARIANTS) | {"e", "section_points"} == {item["name"] for item in DECL.PLACEMENT["items"]}, \
        "放置设定加了项：这里也要加上换它一个值的情形"
    refused = varied["collar_rule"]
    assert refused.get("status") == "error" and "wrap_fit" in refused["reason"], "这个柄空间只会无领的那一种选号规则"
    rows = {name: result["designs"][0] for name, result in varied.items() if name != "collar_rule"}
    before = {name: templated[0][f"rule16-{VARIANTS[name][1]}"] for name in rows}       # 同一个设计，设定没换时的结果
    for name, row in rows.items():
        assert (row["feasible"], row["info"]) != (before[name]["feasible"], before[name]["info"]), f"{name} 换了值，结果没变"
    for name in ("h_cut", "neck_radius_mm", "area_min_mm2", "min_tip_area_mm2"):
        assert before[name]["feasible"] and not rows[name]["feasible"], f"{name}：{rows[name]}"
    info = {name: row["info"] for name, row in rows.items() if row["feasible"]}
    base = before["ref_cut_mm"]["info"]
    assert info["ref_cut_mm"]["bone_resected_mm3"] > 0 == base["bone_resected_mm3"], "截骨参照挪高了，截骨面以上到它之间就有骨"
    assert info["ref_cut_mm"]["A0_mm2"] == base["A0_mm2"]
    assert info["entry"]["e_mm"] == 2.0
    assert "offset_min_mm" not in info or info["offset_min_mm"]["e_mm"] >= 2.0
    assert "offset_max_mm" not in info or info["offset_max_mm"]["e_mm"] <= -2.0
    assert "offset_step_mm" not in info or info["offset_step_mm"]["e_mm"] in (-8.0, -5.0, -2.0, 1.0, 4.0, 7.0)
    assert info["margin_check"]["A0_mm2"] > before["margin_check"]["info"]["A0_mm2"], "查得稀，放得进更大的号"
    assert "area_max_mm2" not in info or info["area_max_mm2"]["A0_mm2"] < 400.0
    assert info["bisection_iters"]["A0_mm2"] == pytest.approx(base["A0_mm2"], rel=0.05)


# ---------------------------------------------------------------- 经真的 fea.run 走一遍

READER = Path(__file__).resolve().parent / "fem_reader"     # 假的有限元包：只读柄的模型，照名字引用去里面找东西
READER_FEM = {"name": "fem", "groups": ["相互作用", "载荷"], "items": [
    packages.item("contact_faces", "相互作用", "ref", {"ref": "stem.faces.interface"}, refers=["stem.faces"]),
    packages.item("load_point", "载荷", "ref", {"ref": "stem.feature.head_center"}, refers=["stem.feature", "bone.landmark"]),
    packages.item("load", "载荷", "number", 2000.0, per_point=True, unit="N", range={"min": 0, "max": 10000})]}
READER_OUTPUTS = packages.outputs(("interface_kb", "1", "size of the interface patch the stem model handed over, kB", "pre"),
                                  ("load_seen", "N", "the load that reached the solver", "label"),
                                  ("interface_slip", "um", "slip at each interface node", "field"))


def registered_bone(folder: Path, legacy: Path) -> dict:
    """把 3406 登记成一根骨模型：两个实体是旧系统的那两个 STEP。标志点只有头心是准的，别的写的是大致的位置：
    这个柄空间不用清单里的标志点，头心、颈轴、骨干轴它自己从实体里找。"""
    source = legacy / "v2" / "data" / "femur_3406"
    for name, file in tools.STEPS.items():
        (folder / "solids").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / file, folder / "solids" / f"{name}.step")
    rough = "approximate, for this test only"
    landmarks = {"head_center": {"xyz": list(HEAD_3406), "definition": "centre of the sphere fitted to the head by the legacy code"},
                 "neck_center": {"xyz": [32.4, 0.4, 101.1], "definition": rough}, "shaft_proximal": {"xyz": [7.0, 0.0, 0.0], "definition": rough},
                 "shaft_distal": {"xyz": [7.0, 0.0, -150.0], "definition": rough}, "lesser_trochanter": {"xyz": [20.0, 15.0, 30.0], "definition": rough}}
    frame = {"origin": "the origin of the baked 3406R CAD files", "x": "medial", "y": "posterior", "z": "proximal"}
    write_manifest(folder, make_manifest("bone_model", hashing.list_tree(folder), bone_id=tools.BONE_ID,
                                         **{**real.BONE_EXTRA, "landmarks": landmarks, "frame": frame}))
    return register.register_external("bone_model", "sawbone3406-model", source=folder, note="测试用：3406 的两个实体", by="tester",
                                      bone_id=tools.BONE_ID, new_bone=True)


def registered_reader(folder: Path) -> dict:
    """把假的有限元包（fem_reader）写上清单，登记。"""
    shutil.copytree(READER, folder, ignore=shutil.ignore_patterns("__pycache__"))
    write_manifest(folder, make_manifest(
        "fem", hashing.list_tree(folder), entry=["{python}", "code/main.py"], requires=["python>=3.12"],
        tolerance={"rel": 1e-9, "abs": 1e-12},
        selftest=[{"name": "echo", "input": "data/selftest/echo/input", "expected": "data/selftest/echo/expected.json"}],
        programs=[], declarations=[READER_FEM], modes=["build", "post"], inputs={"bone": {}, "stem": {}}, outputs=READER_OUTPUTS,
        test_round={"inputs": {}}))
    return register.register_external("fem", "fem-reader", source=folder, note="测试用：只读柄的模型的假有限元包", by="tester")


def test_the_stem_space_goes_through_fea_run(real_lab, data, built, legacy, works, handed, tmp_path):
    """现打的 M1 柄空间包登记进一本空账，配一个只读柄的模型的假有限元包，经冻结的 fea.run 骨架走一遍：
    启动前的核对认它的清单、声明和 names；一个点交出柄的模型、往下建模；一个点放不下，归 misfit、不再建模。"""
    stem = register.register_external("stem_space", "m1-3406", source=built, note="测试用：现打的 M1 柄空间包", by="tester")
    fem = registered_reader(tmp_path / "fem-reader")
    settings = {"placement": real.declared(DECL.PLACEMENT, stem["id"], h_cut=real.PER_POINT),
                "fem_setting": real.declared(READER_FEM, fem["id"], load=real.PER_POINT)}
    rows = [{"name": name, "bone_id": tools.BONE_ID, "design": dict(SHAPE_A), "conditions": {"load": 2000.0},
             "placement": {"h_cut": h_cut}, "derive": {}, "reason": "测试"} for name, h_cut in (("fits", 16.0), ("tight", 24.0))]
    made = real.fea_run(tmp_path, rows, packages_={"stem": stem, "fem": fem}, settings=settings,
                        bone=registered_bone(tmp_path / "bone3406", legacy))
    began = starting.start(made)
    assert began.ok, began
    real.run(made, seconds=600)
    status = view.view(made)
    assert real.tasks(made) == {"fits": ("done", "finished"), "tight": ("done", "misfit")}, status.rounds[-1].problems
    assert [stage for stage in stages(made, "fits") if stage != "modeled"] == ["stem", "build", "solve", "post"]
    assert stages(made, "tight") == ["stem"], "放不下的不再去建模"

    listed = read_manifest(real.output(made, "data"))
    assert [(column["name"], column["role"]) for column in listed["columns"]] == (
        [(name, "design") for name in SHAPE_A] + [("load", "condition"), ("h_cut", "condition")]
        + [(column["name"], "pre") for column in BUILD.OUTPUTS]
        + [("interface_kb", "pre"), ("load_seen", "label"), ("interface_slip", "field"), ("slip_p95", "derived")]), \
        "数据说明：12 个设计项，每个点给的载荷和截骨高度，柄空间包模板化的量，有限元包的，推导量"
    values = rows_of(made)["fits"]["values"]
    assert {name: values[name] for name in SHAPE_A} == SHAPE_A and values["h_cut"] == 16.0
    assert {column["name"]: values[column["name"]] for column in BUILD.OUTPUTS} == handed[0]["pre"], "模板化的量进了数据的行"
    assert values["interface_kb"] > 100.0 and values["load_seen"] == 2000.0
    frozen = status.frozen
    assert listed["made_by"]["kernel"] is None and listed["made_by"]["stem"] == {"package": frozen["stem"][0]["hash"]}
    assert listed["made_by"]["settings"]["placement"] == hashing.hash_json(
        {name: value for name, value in settings["placement"]["values"].items() if name != "h_cut"}), "每个点给的截骨高度不在共用的那部分里"

    files = kept(made, "fits")
    assert {"stem_model.json", "stem.step", "interface.step", "deck.json"} <= files["settings"], "交出的柄的模型也归档"
    archive = real.output(made, "archive")
    row = next(row for row in read_points(archive / "index.jsonl") if row["task"] == "fits" and row["file"].endswith("/deck.json"))
    deck = json.loads((Path(read_manifest(archive)["root"]) / row["file"]).read_bytes())
    model = stem_model.read(handed[1] / given.MODEL)
    assert deck["load_point"] == pytest.approx(model["features"]["head_center"], abs=1e-9), "有限元包照名字引用找到了柄的模型上的假体头心"
    assert deck["design"] == SHAPE_A and deck["material"] == model["regions"][0]["material"]
    for part in ("origin", "x", "y", "z"):
        assert deck["frame"][part] == pytest.approx(model["placement"]["frame"][part], abs=1e-9), \
            "柄放在骨上的哪里：有限元包读到的，和柄空间包单独跑时交出的一样"
