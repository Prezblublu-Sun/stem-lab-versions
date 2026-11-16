"""把“床支撑 F”打成 stem-lab 的一个带代码的包（种类 derive_def）。

    python external/derive_bed_f/build.py <包放到哪个文件夹>

自检样本是这里现造的一小片界面点云：九个节点，哪几个落在支撑区里、F 该是多少，手算得出来（见 sample()）。
打好之后登记：python -m stemlab.desk register derive_def bed-f-3406 --path <包的文件夹> --note "..."
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXTRA = {
    "needs": ["interface"],
    "columns": [
        {"name": "F_mm", "unit": "mm", "meaning": "床支撑：支撑区内 面积 / max(泡沫厚度, 0.25) 之和"},
        {"name": "F_area_mm2", "unit": "mm2", "meaning": "支撑区内的界面面积"},
        {"name": "F_n_nodes", "unit": "1", "meaning": "支撑区内的界面节点数"},
        {"name": "F_t_min_mm", "unit": "mm", "meaning": "支撑区内最薄的泡沫厚度（取下限之前）"},
        {"name": "F_frac_floor", "unit": "1", "meaning": "支撑区内厚度小于下限的面积占比"},
    ],
}


def sample() -> tuple[dict, dict]:
    """一小片点云和它该算出的数。

    柄轴取颈轴的反方向，入口取参考点。九个节点都在入口往远端 5 mm 的截面上，绕柄轴放在 0、±30、±90、±135、180 度，
    外加一个领上的节点。支撑区是从股骨距一侧起 ±45 度，所以落进去的是 0、+30、−30 度这三个；领上的那个不算。
    三个节点的面积都是 2，泡沫厚度是 1、0.5、0.1（最后一个按下限 0.25 算）：F = 2/1 + 2/0.5 + 2/0.25 = 14。
    """
    how = json.loads((HERE / "bed_f.json").read_text(encoding="utf-8"))
    u = np.array(how["u_neck"]) / np.linalg.norm(how["u_neck"])
    axis, start = -u, np.array(how["cref"])
    n3 = np.array(how["n3"])
    em = n3 - (n3 @ axis) * axis
    em /= np.linalg.norm(em)
    ep = np.array([0.0, 1.0, 0.0]) - axis[1] * axis
    ep /= np.linalg.norm(ep)
    angles = np.radians([0, 30, -30, 90, 135, 180, -135, -90])
    X = [start + 5.0 * axis + 6.0 * (np.cos(angle) * em + np.sin(angle) * ep) for angle in angles]
    X.append(start + 5.0 * axis + 6.0 * em)                                   # 领上的节点，和 0 度那个同一个位置
    thickness = [1.0, 0.5, 0.1, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    cloud = {"X": np.array(X), "area": np.full(9, 2.0), "d_canal": -np.array(thickness), "collar": np.array([False] * 8 + [True]),
             "P0": start, "stem_axis": axis}
    expected = {"derived": {"F_mm": 14.0, "F_area_mm2": 6.0, "F_n_nodes": 3, "F_t_min_mm": 0.1, "F_frac_floor": 1.0 / 3.0}}
    return cloud, expected


def main() -> int:
    package = Path(sys.argv[1])
    if package.exists():
        shutil.rmtree(package)
    (package / "code").mkdir(parents=True)
    (package / "data" / "selftest" / "nine_nodes" / "input").mkdir(parents=True)
    shutil.copyfile(HERE / "main.py", package / "code" / "main.py")
    shutil.copyfile(HERE / "bed_f.json", package / "data" / "bed_f.json")
    cloud, expected = sample()
    test = package / "data" / "selftest" / "nine_nodes"
    np.savez(test / "input" / "interface.npz", **cloud)
    (test / "input" / "job.json").write_text(json.dumps({"fields": {"interface": "interface.npz"}, "labels": {}, "pre": {}, "point": {}}))
    (test / "expected.json").write_text(json.dumps(expected))
    files = sorted((path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()),
                   key=lambda rel: rel.encode("utf-8"))
    manifest = {"format": 1, "kind": "derive_def", "files": files, "entry": ["{python}", "code/main.py"],
                "requires": ["python>=3.12", "numpy>=2"], "tolerance": {"rel": 1e-9, "abs": 1e-9},
                "selftest": [{"name": "nine_nodes", "input": "data/selftest/nine_nodes/input",
                              "expected": "data/selftest/nine_nodes/expected.json"}],
                "bones": ["sawbone3406"], **EXTRA}
    (package / "manifest.json").write_bytes(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    print(f"打好了：{package}（{len(files)} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
