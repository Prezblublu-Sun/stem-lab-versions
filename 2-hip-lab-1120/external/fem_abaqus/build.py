"""把从 M1-3406-v1 拆出来的建模、求解、后处理那一半打成 stem-lab 的一个带代码的包（种类 fem）。

    python external/fem_abaqus/build.py <旧系统 mobo_toy 的位置> <包放到哪个文件夹> [--test-bone <登记的 3406 骨模型的编号>]

旧系统只读：这里只从它那里读文件，逐字节复制，不改它任何东西。
8 个计入 code_hash 的文件从冻结时存下的原字节包（docs/freeze/M1-3406-v1_files.tar）里取，
取出来先算 code_hash，对不上 6d7af243d0 就不打包。建模、求解、后处理用到其中 7 个（TAKEN），包里只放这 7 个：
config_v2a.yaml 用不到，材料、载荷、网格都从骨模型、柄的模型和有限元设定来。
别的运行时文件（RUNTIME）从工作树按字节复制，复制完照自检样本里记的哈希核一遍：工作树里的文件变了，就不打包。

清单里带 declarations.py 的那份声明（fem）、programs（Abaqus 2025）、对两份输入的要求、产出的列。
Abaqus 的启动器不写进清单：包先看环境变量 STEMLAB_ABAQUS，没设就用旧系统配置里的位置（config.yaml 的 abaqus.launcher）。
测试轮用的骨模型：3406 的骨模型登记以后，用 --test-bone 把它的编号写进来。

打好之后登记：python -m stemlab.desk register fem abaqus-m1 --path <包的文件夹> --note "..."
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE_HASH = "6d7af243d0"
HASHED = ("femur_real.py", "geom3d.py", "fe3d_geom.py", "model3d_v2.py", "post.py", "config_v2a.yaml",
          "model3d_m1.py", "post_m1.py")                         # 顺序固定：code_hash 就是按这个顺序算的
TAKEN = ("femur_real.py", "geom3d.py", "fe3d_geom.py", "model3d_v2.py", "post.py", "model3d_m1.py", "post_m1.py")
# 建模、求解、后处理运行时还要的别的文件（相对旧系统的根目录）。多数只是 import 时要在：旧代码在模块顶上互相 import
RUNTIME = ("config.yaml", "femur2d.py", "plotstyle.py", "stem2d.py", "inp_writer.py", "qoi.py", "run_abaqus.py",
           "abaqus/odb_export.py", "spot3d/model3d.py", "spot3d/qoi3d.py", "v2/jobs.py", "v2/stability.py")
SELFTEST = "fem"
PROGRAMS = [{"name": "abaqus", "version": "2025"}]
LANDMARKS = ["head_center", "neck_center", "shaft_proximal", "shaft_distal", "lesser_trochanter"]


def _columns(role: str, *rows) -> list[dict]:
    return [dict(zip(("name", "unit", "meaning"), row), role=role) for row in rows]


# 产出的列：建模时就有的（原内核给的建模前的量里，网格的那 4 个）、标量（和原内核的一样）、场
OUTPUTS = _columns(
    "pre", ("n_tet", "1", "四面体数"), ("n_pairs", "1", "界面节点对数"), ("mesh_attempt", "1", "第几档网格设置划成的"),
    ("h_mesh_mm", "mm", "划成时实际用的界面网格尺寸")) + _columns(
    "label", ("rot_first_deg", "deg", "首次加载柄相对骨的转动：界面相对位移的刚体拟合"),
    ("rot_rev_deg", "deg", "第二循环可恢复的转动"), ("rot_perm_deg", "deg", "卸载后残留的转动"),
    ("subsid_first_um", "um", "首次加载沿柄轴的下沉"), ("f1_p95_um", "um", "第二循环可恢复切向微动，面积加权 95 分位"),
    ("f1_first_p95_um", "um", "首次加载切向相对位移，面积加权 95 分位"),
    ("contact_area_load2_mm2", "mm2", "第二次加载时闭合（间隙不超过 1 微米）的柄身界面面积"),
    ("open_frac_load2", "1", "第二次加载时张开的界面面积比例"), ("area_frac_gt150", "1", "微动超过 150 微米的界面面积比例"),
    ("interface_area", "mm2", "柄身界面面积"), ("iface_force_err_load", "1", "界面接触力之和对外载的相对差，首次加载"),
    ("iface_force_err_load2", "1", "同上，第二次加载"),
    ("load_x_N", "N", "实际加的载荷，载荷的坐标系里的 x（内侧为正）"), ("load_y_N", "N", "同上 y（后方为正）"),
    ("load_z_N", "N", "同上 z（沿干轴向近端为正）")) + _columns(
    "field", ("interface", "mm", "界面点云：每个节点对的位置、法向、面积、过盈、四个分析步的相对位移、到髓腔壁的距离，都在骨模型的坐标里"))
INPUTS = {
    "bone": {"version": 1, "solids": ["cortical", "cancellous"], "landmarks": LANDMARKS, "materials": ["linear_elastic"],
             "what": "两个实体照原样用；干轴、颈轴、远端截断、载荷的坐标系由标志点定；两个实体的材料照清单，override_region 那个的模量换成 E_canc_MPa"},
    "stem": {"required": True, "dimension": "3d", "regions": 1, "geometry": ["solid"], "materials": ["elastic"],
             "what": "一个区域的实体（柄体、假体颈、假体头并好的），contact_faces 引用的那组面落在它上面；placement.frame 和 placement.cut "
                     "照原样用。无植入物（没有柄的模型）不做：这个包只会 M1 的界面做法"},
}


def _declarations() -> list[dict]:
    spec = importlib.util.spec_from_file_location("fem_abaqus_declarations", HERE / "declarations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DECLARATIONS


def take_hashed(legacy: Path, target: Path) -> str:
    """从冻结时存下的原字节包里读 8 个文件，把用到的 7 个放进 target。返回 8 个文件合起来的 code_hash。"""
    digest = hashlib.sha256()
    with tarfile.open(legacy / "docs" / "freeze" / "M1-3406-v1_files.tar") as archive:
        members = {Path(member.name).name: member for member in archive.getmembers() if member.isfile()}
        for name in HASHED:
            data = archive.extractfile(members[name]).read()
            digest.update(data)
            if name in TAKEN:
                (target / name).write_bytes(data)
    return digest.hexdigest()[:10]


def main() -> int:
    parser = argparse.ArgumentParser(description="打 M1 的 Abaqus 有限元包")
    parser.add_argument("legacy", type=Path, help="旧系统 mobo_toy 的位置（只读）")
    parser.add_argument("package", type=Path, help="包放到哪个文件夹")
    parser.add_argument("--test-bone", help="测试轮用的骨模型：登记的 3406 骨模型的编号")
    args = parser.parse_args()
    legacy, package = args.legacy, args.package
    if package.exists():
        shutil.rmtree(package)
    code = package / "code"
    (code / "legacy" / "v2").mkdir(parents=True)
    found = take_hashed(legacy, code / "legacy" / "v2")
    if found != CODE_HASH:
        shutil.rmtree(package)
        raise SystemExit(f"8 个冻结文件的 code_hash 是 {found}，不是 {CODE_HASH}：没有打包")
    for rel in RUNTIME:
        (code / "legacy" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(legacy / rel, code / "legacy" / rel)
    known = json.loads((HERE / "selftest" / SELFTEST / "expected.json").read_bytes())["legacy"]
    carried = {path.relative_to(code / "legacy").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()[:16]
               for path in (code / "legacy").rglob("*") if path.is_file()}
    if carried != known:
        changed = sorted(name for name in set(carried) | set(known) if carried.get(name) != known.get(name))
        shutil.rmtree(package)
        raise SystemExit(f"旧系统里的 {changed} 和写这个包时认的不一样：没有打包")
    for name in ("main.py", "solve.py"):
        shutil.copyfile(HERE / name, code / name)
    shutil.copytree(HERE / "selftest", package / "data" / "selftest")

    files = sorted((path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()),
                   key=lambda rel: rel.encode("utf-8"))
    samples = sorted(path.name for path in (package / "data" / "selftest").iterdir() if path.is_dir())
    manifest = {
        "format": 2, "kind": "fem", "files": files,
        "entry": ["{python}", "code/main.py"],
        "requires": ["python==3.12.*", "numpy==2.5.3", "scipy==1.18.1", "gmsh==4.15.2", "shapely==2.1.2", "contourpy==1.4.0",
                     "pyyaml==6.0.3", "matplotlib==3.11.2", "Abaqus/Standard 2025"],
        "selftest": [{"name": name, "input": f"data/selftest/{name}/input", "expected": f"data/selftest/{name}/expected.json"}
                     for name in samples],
        "tolerance": {"rel": 1e-6, "abs": 1e-9},
        "programs": PROGRAMS,
        "declarations": _declarations(),
        "modes": ["build", "post"],
        "inputs": INPUTS,
        "outputs": OUTPUTS,
        "test_round": {"inputs": {"bone": {"item": args.test_bone}} if args.test_bone else {}},
        "source": {"model": "M1-3406-v1", "code_hash": CODE_HASH, "taken": list(TAKEN)},
    }
    text = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    (package / "manifest.json").write_bytes(text.encode("utf-8") + b"\n")
    print(f"打好了：{package}（{len(files)} 个文件，旧代码取自 code_hash {found} 的那一版）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
