"""把“床支撑 F（支撑区照名字引用定）”打成 stem-lab 的一个带代码的包（种类 derive_def）。给 fea.run 用。

    python external/derive_bed_f_named/build.py <包放到哪个文件夹>

清单照改格式以后的写法：programs（空的：不用外部程序）、declarations（declarations.py 的那份 derive）、modes、
inputs（要骨模型、柄的模型、界面点云里的什么）、needs（要哪个场）、columns（算出的五个量）。不写只认哪根骨：位置都来自输入。
自检样本是这里现造的一份输入：一个柄的模型（只写了这个包读的那几段）、一份骨模型的清单（只有标志点）、十二个节点的界面点云。
哪几个节点落在支撑区里、F 该是多少，手算得出来（见 sample()）。
打好之后登记：python -m stemlab.desk register derive_def bed-f --path <包的文件夹> --note "..."

旧常数（旧模型坐标、3406 专用）的那一个在 external/derive_bed_f，只给参照包那条（fea.reference）用。
"""
from __future__ import annotations

import importlib.util
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SAMPLE = "twelve_nodes"
NEEDS = ["interface"]
COLUMNS = [
    {"name": "F_mm", "unit": "mm", "meaning": "床支撑：支撑区内 面积 / max(泡沫厚度, 下限) 之和。支撑区和下限照推导量设定"},
    {"name": "F_area_mm2", "unit": "mm2", "meaning": "支撑区内的界面面积"},
    {"name": "F_n_nodes", "unit": "1", "meaning": "支撑区内的界面节点数"},
    {"name": "F_t_min_mm", "unit": "mm", "meaning": "支撑区内最薄的泡沫厚度（取下限之前）"},
    {"name": "F_frac_floor", "unit": "1", "meaning": "支撑区内厚度小于下限的面积占比"},
]
INPUTS = {
    "bone": {"version": 1, "what": "zone_from 指向骨模型时，读那个标志点的位置。点云就在骨模型的坐标里"},
    "stem": {"required": True, "what": "读设定引用到的特征点和轴，和 placement.frame（把它们从柄自己的坐标系换到骨模型的坐标里）。"
                                       "无植入物（没有柄的模型）不算：没有柄就没有床支撑"},
    "fields": {"interface": ["X", "area", "d_canal", "collar"],
               "what": "界面点云，在骨模型的坐标里：每个界面节点的位置、面积、到髓腔壁的距离（松质里为负）、在不在领上"},
}


def _declarations() -> list[dict]:
    spec = importlib.util.spec_from_file_location("derive_bed_f_named_declarations", HERE / "declarations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DECLARATIONS


def sample() -> tuple[dict, dict, dict, dict]:
    """一份造的输入和它该算出的数：（柄的模型，骨模型的清单，点云，该交的结果）。

    柄自己的坐标系里：柄轴是 z（指向远端），颈轴从原点指向 (0.6, 0, −0.8)，头心在颈轴上离原点 20 mm。
    测试轮的设定下，参照点是头心沿颈轴往远端 16 mm，就是 (2.4, 0, −3.2)；一个节点 (x, y, z) 的深度 ζ = 4 − 0.6x + 0.8z，
    角度从 +x 起、绕 z 量。十二个节点都离柄轴 6 mm：
        z = 5，角度 0、±30：ζ 是 4.4、4.88、4.88，都在支撑区里。泡沫厚 1、0.5、0.1（最后一个按下限 0.25 算）
        z = 5，角度 50、±90、±140、180：角度出去了
        z = 20，角度 0：ζ = 16.4，比 15 深
        z = 17，角度 0：ζ = 14.0，在里面，泡沫厚 4
        z = 5，角度 0，在领上：不算
    四个在里面，面积都是 2：F = 2/1 + 2/0.5 + 2/0.25 + 2/4 = 14.5，面积 8，最薄 0.1，比下限薄的占 2/8。
    柄的坐标系在骨模型的坐标里转过、挪过（x、y、z 轴分别朝骨模型的 y、z、x，原点在 (30, −5, 90)）：点云写在骨模型的坐标里。
    """
    spin = np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])        # 三列是柄的 x、y、z 轴
    origin = np.array([30.0, -5.0, 90.0])

    def to_bone(point) -> list:
        return (origin + spin @ np.asarray(point, float)).tolist()

    def node(theta: float, z: float) -> list:
        return [6.0 * math.cos(math.radians(theta)), 6.0 * math.sin(math.radians(theta)), z]

    nodes = [(node(0, 5), 1.0, False), (node(30, 5), 0.5, False), (node(-30, 5), 0.1, False), (node(50, 5), 2.0, False),
             (node(90, 5), 1.0, False), (node(-90, 5), 1.0, False), (node(140, 5), 1.0, False), (node(-140, 5), 1.0, False),
             (node(180, 5), 1.0, False), (node(0, 20), 1.0, False), (node(0, 17), 4.0, False), (node(0, 5), 1.0, True)]
    stem = {"format": 1,
            "features": {"head_center": [12.0, 0.0, -16.0], "neck_base": [0.0, 0.0, 0.0], "shoulder": [0.0, 0.0, 0.0], "tip": [0.0, 0.0, 40.0]},
            "axes": {"stem_axis": {"point": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0]},
                     "neck_axis": {"point": [0.0, 0.0, 0.0], "direction": [0.6, 0.0, -0.8]}},
            "placement": {"frame": {"origin": origin.tolist(), "x": spin[:, 0].tolist(), "y": spin[:, 1].tolist(), "z": spin[:, 2].tolist()}}}
    bone = {"landmarks": {"head_center": {"xyz": to_bone([12.0, 0.0, -16.0]), "definition": "made up for the self-check: the head centre is restored"}}}
    cloud = {"X": np.array([to_bone(x) for x, _, _ in nodes]), "area": np.full(len(nodes), 2.0),
             "d_canal": -np.array([thickness for _, thickness, _ in nodes]), "collar": np.array([collar for _, _, collar in nodes])}
    expected = {"derived": {"F_mm": 14.5, "F_area_mm2": 8.0, "F_n_nodes": 4, "F_t_min_mm": 0.1, "F_frac_floor": 0.25}}
    return stem, bone, cloud, expected


def main() -> int:
    package = Path(sys.argv[1])
    declarations = _declarations()
    if package.exists():
        shutil.rmtree(package)
    (package / "code").mkdir(parents=True)
    shutil.copyfile(HERE / "main.py", package / "code" / "main.py")
    test = package / "data" / "selftest" / SAMPLE
    stem, bone, cloud, expected = sample()
    for name, listed in (("stem/stem_model.json", stem), ("bone/manifest.json", bone)):
        (test / "input" / name).parent.mkdir(parents=True)
        (test / "input" / name).write_bytes(json.dumps(listed).encode("utf-8") + b"\n")
    np.savez(test / "input" / "interface.npz", **cloud)
    settings = {item["name"]: item["test"] for item in declarations[0]["items"]}
    job = {"fields": {"interface": "interface.npz"}, "labels": {}, "pre": {}, "point": {}, "bone_model": "bone", "stem_model": "stem",
           "settings": settings}
    (test / "input" / "job.json").write_bytes(json.dumps(job).encode("utf-8") + b"\n")
    (test / "expected.json").write_bytes(json.dumps(expected).encode("utf-8") + b"\n")
    files = sorted((path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()),
                   key=lambda rel: rel.encode("utf-8"))
    manifest = {"format": 2, "kind": "derive_def", "files": files, "entry": ["{python}", "code/main.py"],
                "requires": ["python>=3.12", "numpy>=2"], "tolerance": {"rel": 1e-9, "abs": 1e-9},
                "selftest": [{"name": SAMPLE, "input": f"data/selftest/{SAMPLE}/input", "expected": f"data/selftest/{SAMPLE}/expected.json"}],
                "programs": [], "declarations": declarations, "modes": ["derive"], "inputs": INPUTS, "needs": NEEDS, "columns": COLUMNS}
    (package / "manifest.json").write_bytes(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    print(f"打好了：{package}（{len(files)} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
