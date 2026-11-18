"""把从 M1-3406-v1 拆出来的柄的那一半打成 stem-lab 的一个带代码的包（种类 stem_space）。

    python external/stem_m1_3406/build.py <旧系统 mobo_toy 的位置> <包放到哪个文件夹> [--test-bone <登记的 3406 骨模型的编号>]

旧系统只读：这里只从它那里读文件，逐字节复制，不改它任何东西。
8 个计入 code_hash 的文件从冻结时存下的原字节包（docs/freeze/M1-3406-v1_files.tar）里取，
取出来先算 code_hash，对不上 6d7af243d0 就不打包。柄的参数化、模板化、放置只用到其中 4 个（TAKEN），包里只放这 4 个。
别的运行时文件（RUNTIME）从工作树按字节复制，复制完照自检样本里记的哈希核一遍：工作树里的文件变了，就不打包。
打好的包里没有两个 STEP 文件：它们属于骨模型，由 stem-lab 把骨模型的位置交给包。

清单里带 declarations.py 的两份声明（design、placement），names（交出的柄的模型里一定有的名字），
outputs（模板化算出的量）。测试轮用的骨模型：3406 的骨模型登记以后，用 --test-bone 把它的编号写进来；
测试轮的那个点就是声明里各项测试轮的取值（设计 A）。

打好之后登记：python -m stemlab.desk register stem_space m1-3406 --path <包的文件夹> --note "..."
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE_HASH = "6d7af243d0"
HASHED = ("femur_real.py", "geom3d.py", "fe3d_geom.py", "model3d_v2.py", "post.py", "config_v2a.yaml",
          "model3d_m1.py", "post_m1.py")                         # 顺序固定：code_hash 就是按这个顺序算的
TAKEN = ("femur_real.py", "geom3d.py", "fe3d_geom.py", "config_v2a.yaml")       # 柄的这一半用到的 4 个
# 模板化运行时还要的别的文件（相对旧系统的根目录）
RUNTIME = ("config.yaml", "femur2d.py", "plotstyle.py", "v2/collar_rule.py", "v2/femur_3406.py")
SELFTEST = "stem"
BONE_ID = "sawbone3406"

# 交出的柄的模型里一定有的名字。有限元设定、推导量设定里的名字引用（比如 stem.faces.interface）照它核
NAMES = {"region": ["stem"], "faces": ["interface"], "feature": ["head_center", "neck_base", "shoulder", "tip"],
         "axis": ["stem_axis", "neck_axis"]}
# 模板化算出的量：建模之前就知道。原内核给的那 11 个里，网格的 4 个留给有限元包
OUTPUTS = [dict(zip(("name", "unit", "meaning", "role"), row + ("pre",))) for row in (
    ("e_mm", "mm", "实际用的入口偏移"), ("A0_mm2", "mm2", "模板化选出的肩部面积（号）"),
    ("alpha_placed_deg", "deg", "放置后的柄轴角"), ("contact_templated", "1", "模板化时的贴合比例"),
    ("bone_resected_mm3", "mm3", "截掉的骨：参照截骨面到这个截骨面之间"),
    ("bone_reamed_mm3", "mm3", "锉掉的骨：柄体占的体积"), ("bone_total_mm3", "mm3", "去骨量：截掉的加锉掉的"))]


def _declarations() -> list[dict]:
    spec = importlib.util.spec_from_file_location("stem_m1_3406_declarations", HERE / "declarations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DECLARATIONS


def take_hashed(legacy: Path, target: Path) -> str:
    """从冻结时存下的原字节包里读 8 个文件，把用到的 4 个放进 target。返回 8 个文件合起来的 code_hash。"""
    digest = hashlib.sha256()
    with tarfile.open(legacy / "docs" / "freeze" / "M1-3406-v1_files.tar") as archive:
        members = {Path(member.name).name: member for member in archive.getmembers() if member.isfile()}
        for name in HASHED:
            data = archive.extractfile(members[name]).read()
            digest.update(data)
            if name in TAKEN:
                (target / name).write_bytes(data)
    return digest.hexdigest()[:10]


def bone_solids(source: bytes) -> dict:
    """旧代码认的那两个 STEP 文件的 sha256：从 femur_3406.py 里读，清单里写的和包真去核的是同一处。"""
    found = dict(re.findall(r'"(cortical|cancellous)":\s*"([0-9a-f]{64})"', source.decode("utf-8")))
    if set(found) != {"cortical", "cancellous"}:
        raise SystemExit("femur_3406.py 里读不出两个 STEP 文件的 sha256：没有打包")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="打 M1-3406 的柄空间包")
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
    shutil.copyfile(HERE / "main.py", code / "main.py")
    shutil.copytree(HERE / "selftest", package / "data" / "selftest")

    files = sorted((path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()),
                   key=lambda rel: rel.encode("utf-8"))
    samples = sorted(path.name for path in (package / "data" / "selftest").iterdir() if path.is_dir())
    manifest = {
        "format": 2, "kind": "stem_space", "files": files,
        "entry": ["{python}", "code/main.py"],
        "requires": ["python==3.12.*", "numpy==2.5.3", "scipy==1.18.1", "gmsh==4.15.2", "shapely==2.1.2", "contourpy==1.4.0",
                     "pyyaml==6.0.3", "matplotlib==3.11.2"],
        "selftest": [{"name": name, "input": f"data/selftest/{name}/input", "expected": f"data/selftest/{name}/expected.json"}
                     for name in samples],
        "tolerance": {"rel": 1e-6, "abs": 1e-9},
        "programs": [],
        "declarations": _declarations(),
        "modes": ["template", "model"],
        "inputs": {"bone": {"bone_id": [BONE_ID], "solids": bone_solids((code / "legacy" / "v2" / "femur_3406.py").read_bytes()),
                            "landmarks": [],
                            "what": "只认 3406R_v1_hollowcore 的两个实体，按 sha256 认。头心、颈轴、骨干轴由包从这两个实体里自己找，"
                                    "不用骨模型清单里的标志点"}},
        "outputs": OUTPUTS,
        "test_round": {"inputs": {"bone": {"item": args.test_bone}} if args.test_bone else {}},
        "names": NAMES,
        "source": {"model": "M1-3406-v1", "code_hash": CODE_HASH, "taken": list(TAKEN)},
    }
    text = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    (package / "manifest.json").write_bytes(text.encode("utf-8") + b"\n")
    print(f"打好了：{package}（{len(files)} 个文件，旧代码取自 code_hash {found} 的那一版）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
