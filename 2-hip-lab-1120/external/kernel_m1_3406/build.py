"""把旧系统的 FE 内核打成 stem-lab 的一个带代码的包（种类 kernel）。

    python external/kernel_m1_3406/build.py <旧系统 mobo_toy 的位置> <包放到哪个文件夹>

旧系统只读：这里只从它那里读文件，逐字节复制，不改它任何东西。
8 个计入 code_hash 的文件从冻结时存下的原字节包（docs/freeze/M1-3406-v1_files.tar）里取，
取出来先算 code_hash，对不上 6d7af243d0 就不打包。别的运行时文件从工作树按字节复制。
打好的包里没有两个 STEP 文件：它们属于骨模型，求解时由 stem-lab 把骨模型的位置交给内核。

打好之后登记：python -m stemlab.desk register kernel m1-3406 --path <包的文件夹> --note "..."
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE_HASH = "6d7af243d0"
HASHED = ("femur_real.py", "geom3d.py", "fe3d_geom.py", "model3d_v2.py", "post.py", "config_v2a.yaml",
          "model3d_m1.py", "post_m1.py")                         # 顺序固定：code_hash 就是按这个顺序算的
# 一个 3406 作业运行时还要的别的文件（相对旧系统的根目录）
RUNTIME = ("config.yaml", "inp_writer.py", "qoi.py", "femur2d.py", "plotstyle.py", "stem2d.py", "run_abaqus.py",
           "abaqus/odb_export.py", "spot3d/model3d.py", "spot3d/qoi3d.py",
           "v2/jobs.py", "v2/femur_3406.py", "v2/collar_rule.py", "v2/result_codes.py", "v2/stability.py",
           "v2/torsion_load.py", "v2/pose_fixed.py", "v2/foam_refine.py")
COLUMN = ("name", "unit", "meaning")


def columns(*rows) -> list[dict]:
    return [dict(zip(COLUMN, row)) for row in rows]


EXTRA = {
    "modes": ["template", "build", "post", "bench"],
    "bones": ["sawbone3406"],
    "model": {"name": "M1-3406-v1", "code_hash": CODE_HASH, "solver": "Abaqus/Standard 2025"},
    "design": columns(
        ("L", "mm", "柄长：肩部到尖端"), ("alpha", "deg", "颈平面内柄轴和干轴的夹角"),
        ("h_cut", "mm", "截骨面到头心的距离，沿颈轴"), ("m", "mm", "皮质余量：柄面到内膜面至少留这么多"),
        ("rho_tip", "1", "尖端和肩部的截面积之比"), ("q", "1", "面积沿柄递减的指数"),
        ("lam", "1", "截面内外宽和前后厚之比"), ("g_ml", "1", "内侧占宽度的比例"), ("g_ap", "1", "前方占厚度的比例"),
        ("n_a", "1", "前半的超椭圆指数"), ("n_p", "1", "后半的超椭圆指数"),
        ("tau_a", "1", "前半的楔形斜度"), ("tau_p", "1", "后半的楔形斜度"),
        ("e", "mm", "入口偏移，沿截骨面内指向内下；写 rule 就由生产规则在九档里选")),
    "conditions": columns(
        ("delta_mm", "mm", "松质界面的径向过盈"), ("mu", "1", "摩擦系数"), ("E_canc_MPa", "MPa", "松质（泡沫）的模量"),
        ("load_N", "N", "头上的合力"), ("load_front_deg", "deg", "合力在冠状面里的倾角"),
        ("load_sagit_deg", "deg", "合力在矢状面里的倾角"), ("cycles", "1", "加载循环数"),
        ("h_int_mm", "mm", "界面处的网格尺寸")),
    "pre": columns(
        ("e_mm", "mm", "实际用的入口偏移"), ("A0_mm2", "mm2", "模板化选出的肩部面积（号）"),
        ("alpha_placed_deg", "deg", "放置后的柄轴角"), ("contact_templated", "1", "模板化时的贴合比例"),
        ("bone_resected_mm3", "mm3", "截掉的骨：参照截骨面到这个截骨面之间"),
        ("bone_reamed_mm3", "mm3", "锉掉的骨：柄体占的体积"), ("bone_total_mm3", "mm3", "去骨量：截掉的加锉掉的"),
        ("n_tet", "1", "四面体数"), ("n_pairs", "1", "界面节点对数"), ("mesh_attempt", "1", "第几档网格设置划成的"),
        ("h_mesh_mm", "mm", "划成时实际用的界面网格尺寸")),
    "labels": columns(
        ("rot_first_deg", "deg", "首次加载柄相对骨的转动：界面相对位移的刚体拟合"),
        ("rot_rev_deg", "deg", "第二循环可恢复的转动"), ("rot_perm_deg", "deg", "卸载后残留的转动"),
        ("subsid_first_um", "um", "首次加载沿柄轴的下沉"), ("f1_p95_um", "um", "第二循环可恢复切向微动，面积加权 95 分位"),
        ("f1_first_p95_um", "um", "首次加载切向相对位移，面积加权 95 分位"),
        ("contact_area_load2_mm2", "mm2", "第二次加载时闭合（间隙不超过 1 微米）的柄身界面面积"),
        ("open_frac_load2", "1", "第二次加载时张开的界面面积比例"), ("area_frac_gt150", "1", "微动超过 150 微米的界面面积比例"),
        ("interface_area", "mm2", "柄身界面面积"),
        ("iface_force_err_load", "1", "界面接触力之和对外载的相对差，首次加载"),
        ("iface_force_err_load2", "1", "同上，第二次加载"),
        ("load_x_N", "N", "实际加的载荷，模型坐标 x（内侧为正）"), ("load_y_N", "N", "同上 y（后方为正）"),
        ("load_z_N", "N", "同上 z（近端为正）")),
    "fields": columns(("interface", "mm", "界面点云：每个节点对的位置、法向、面积、过盈、四个分析步的相对位移、到髓腔壁的距离")),
}


def take_hashed(legacy: Path, target: Path) -> str:
    """从冻结时存下的原字节包里取 8 个文件，放进 target，返回算出的 code_hash。"""
    digest = hashlib.sha256()
    with tarfile.open(legacy / "docs" / "freeze" / "M1-3406-v1_files.tar") as archive:
        members = {Path(member.name).name: member for member in archive.getmembers() if member.isfile()}
        for name in HASHED:
            data = archive.extractfile(members[name]).read()
            digest.update(data)
            (target / name).write_bytes(data)
    return digest.hexdigest()[:10]


def main() -> int:
    legacy, package = Path(sys.argv[1]), Path(sys.argv[2])
    if package.exists():
        shutil.rmtree(package)
    code = package / "code"
    (code / "legacy" / "v2").mkdir(parents=True)
    found = take_hashed(legacy, code / "legacy" / "v2")
    if found != CODE_HASH:
        raise SystemExit(f"8 个冻结文件的 code_hash 是 {found}，不是 {CODE_HASH}：没有打包")
    for rel in RUNTIME:
        (code / "legacy" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(legacy / rel, code / "legacy" / rel)
    for name in ("main.py", "solve.py"):
        shutil.copyfile(HERE / name, code / name)
    shutil.copytree(HERE / "selftest", package / "data" / "selftest")

    files = sorted((path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()),
                   key=lambda rel: rel.encode("utf-8"))
    samples = sorted(path.name for path in (package / "data" / "selftest").iterdir() if path.is_dir())
    manifest = {
        "format": 1, "kind": "kernel", "files": files,
        "entry": ["{python}", "code/main.py"],
        "requires": ["python==3.12.*", "numpy==2.5.3", "scipy==1.18.1", "gmsh==4.15.2", "shapely==2.1.2", "contourpy==1.4.0",
                     "pyyaml==6.0.3", "matplotlib==3.11.2", "Abaqus/Standard 2025 (D:/SIMULIA/Commands/abq2025.bat)"],
        "selftest": [{"name": name, "input": f"data/selftest/{name}/input", "expected": f"data/selftest/{name}/expected.json"}
                     for name in samples],
        "tolerance": {"rel": 1e-6, "abs": 1e-9},
        **EXTRA,
    }
    text = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    (package / "manifest.json").write_bytes(text.encode("utf-8") + b"\n")
    print(f"打好了：{package}（{len(files)} 个文件，code_hash {found}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
