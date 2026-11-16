"""真插件的测试共用的样本：一根骨模型、一批点、假的包、各样设定，和把一个实验的输入填齐的办法。

要用 real_lab 或 real_own_lab 夹具。假的包在 tests/packages/ 里。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from stemlab.contract.formats.manifest import make_manifest, write_manifest
from stemlab.contract.formats.points import write_points
from stemlab.desk.core import actions, start
from stemlab.experiments import view
from stemlab.registry import lookup, register
from tests import helpers, packages

BONE = "femur042"
_NAMES = iter(range(1, 1_000_000))

BONE_EXTRA = {
    "side": "right",
    "units": {"length": "mm", "force": "N", "stress": "MPa"},
    "frame": {"origin": "on the shaft axis at the lesser trochanter", "x": "medial", "y": "posterior", "z": "proximal along the shaft"},
    "solids": {"cortical": {"file": "solids/cortical.step"}, "cancellous": {"file": "solids/cancellous.step"}},
    "landmarks": {
        "head_center": {"xyz": [52.4, 1.8, 48.0], "definition": "centre of the sphere fitted to the head"},
        "neck_center": {"xyz": [30.9, 0.4, 39.1], "definition": "centroid of the narrowest neck section"},
        "shaft_proximal": {"xyz": [0.0, 0.0, -20.0], "definition": "centroid of a proximal shaft section"},
        "shaft_distal": {"xyz": [0.0, 0.0, -140.0], "definition": "centroid of a distal shaft section"},
        "lesser_trochanter": {"xyz": [18.0, 14.0, 0.0], "definition": "most prominent point of the lesser trochanter"},
    },
    "materials": {"cortical": {"model": "linear_elastic", "E_MPa": 16800, "nu": 0.3},
                  "cancellous": {"model": "linear_elastic", "E_MPa": 155, "nu": 0.3}},
    "history": [{"step": "import", "what": "two solids read from a test file"}],
    "checks": [{"name": "volume", "value": 1.0, "limit": "within 0.5% of the source", "passed": True}],
}


def bone_folder(root: Path, kind: str = "bone_model", bone_id: str = BONE, **change) -> Path:
    """一个符合格式的骨模型（或候选骨模型）文件夹。"""
    files = {"solids/cortical.step": b"ISO-10303-21; fake cortical shell\n", "solids/cancellous.step": b"ISO-10303-21; fake core\n"}
    helpers.write_files(root, files)
    write_manifest(root, make_manifest(kind, list(files), bone_id=bone_id, **{**BONE_EXTRA, **change}))
    return root


def bone_model(tmp: Path, bone_id: str = BONE) -> dict:
    """登记一根骨模型。这根骨第一次出现时说明是新骨。"""
    seen = any(item["bone_id"] == bone_id for item in lookup.find())
    return register.register_external("bone_model", f"{bone_id}-model", source=bone_folder(tmp / f"bone-{next(_NAMES)}", bone_id=bone_id),
                                      note="测试用的骨模型", by="tester", bone_id=bone_id, new_bone=not seen)


def point(name: str, length: float = 30.0, behave: str = "ok", load: float = 2000.0, bone_id: str = BONE) -> dict:
    return {"name": name, "bone_id": bone_id, "design": {"length": length, "behave": behave},
            "conditions": {"load": load}, "reason": "测试"}


def points(tmp: Path, rows) -> dict:
    """登记一批点。"""
    folder = tmp / f"points-{next(_NAMES)}"
    write_points(folder, rows)
    return register.register_external("points", f"points-{next(_NAMES)}", source=folder, note="测试用的一批点", by="tester")


def package(name: str, tmp: Path, **change) -> dict:
    """把 tests/packages/<name> 登记成一个带代码的包。change 盖掉它清单里的同名项。"""
    kind = packages.EXTRAS[name]["kind"]
    folder = packages.make(name, tmp / f"{name}-{next(_NAMES)}", **change)
    return register.register_external(kind, f"{name.replace('_', '-')}-{next(_NAMES)}", source=folder, note="测试用的包", by="tester")


def setting(value: dict) -> dict:
    return helpers.setting(f"setting-{next(_NAMES)}", value)


def fea(tmp: Path, rows, export: dict | None = None, criteria: dict | None = None, kernel: dict | None = None,
        derive: dict | None = None, bone: dict | None = None) -> str:
    """登记一个 FEA 实验要的全部输入，新建并填好。返回实验的编号。"""
    made = actions.new("fea.run", note="测试用的 FEA 实验")
    filled = {
        "bone": (bone or bone_model(tmp))["id"],
        "points": points(tmp, rows)["id"],
        "kernel": (kernel or package("kernel_fake", tmp))["id"],
        "derive": (derive or package("derive_fake", tmp))["id"],
        "export": setting({"seconds": 0} if export is None else export)["id"],
    }
    if criteria is not None:
        filled["criteria"] = setting(criteria)["id"]
    for name, item in filled.items():
        actions.fill(made, name, [item])
    return made


def run(made: str, seconds: float = 60.0, until=None) -> None:
    """一遍一遍地看，直到这一轮结束（或 until() 为真）。值守做的就是这件事。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        start.poll(made)
        status = view.view(made)
        if (until is not None and until()) or status.rounds[-1].result is not None:
            return
        time.sleep(0.1)
    raise AssertionError(f"{made} 等了 {seconds} 秒还没结束：" + str({name: (task.state, task.stage) for name, task in view.view(made).tasks.items()})
                         + str(view.view(made).rounds[-1].problems))


def tasks(made: str) -> dict:
    """任务名 ->（状态，结局名）。"""
    return {name: (task.state, task.outcome) for name, task in view.view(made).tasks.items()}


def output(made: str, name: str, number: int | None = None) -> Path:
    """这个实验某一轮（默认最后一轮）发布的一样产物的文件夹。"""
    rounds = view.view(made).rounds
    one = rounds[-1] if number is None else rounds[number - 1]
    return lookup.content(one.outputs[name]["item"])


# ---------------------------------------------------------------- 重建：一根造出来的 CAD 假股骨

NECK = (0.8, 0.0, 0.6)                              # 颈轴的方向：从颈指向头
HEAD = (45.0, 0.0, 60.0)                            # 头心
TRUTH = {
    "head_center": HEAD, "head_radius": 22.0,
    "neck_center": tuple(h - 23.0 * d for h, d in zip(HEAD, NECK)),        # 颈最细的截面：离头心 23 mm
    "neck_axis": NECK, "shaft_axis": (0.0, 0.0, 1.0), "neck_shaft_angle": 126.8699,
    "lesser_trochanter": (15.56, 15.56, 5.0),       # 后内侧那个鼓包的顶
    "neck_wall": 4.0,                               # 颈最细处皮质壳的厚度
}
_CAD: dict[str, bytes] = {}


def _femur_shapes(occ, inner: bool) -> list:
    """假股骨的几块：骨干是圆柱，颈是两段圆台（中间最细），头是球，后内侧有个鼓包当小转子。inner 是里面的松质芯。"""
    less = 4.0 if inner else 0.0
    base = tuple(h - 48.0 * d for h, d in zip(HEAD, NECK))
    middle = TRUTH["neck_center"]
    parts = [occ.addCylinder(0, 0, -100, 0, 0, 135, 9)] if inner else [occ.addCylinder(0, 0, -330, 0, 0, 370, 14),
                                                                         occ.addSphere(9.9, 9.9, 5.0, 8.0)]
    parts.append(occ.addCone(*base, *(m - b for m, b in zip(middle, base)), 17 - less, 11 - less))
    parts.append(occ.addCone(*middle, *(h - m for h, m in zip(HEAD, middle)), 11 - less, 15 - less))
    parts.append(occ.addSphere(*HEAD, 22 - less))
    fused, _ = occ.fuse([(3, parts[0])], [(3, part) for part in parts[1:]])
    return fused


def cad_femur(folder: Path) -> Path:
    """在 folder 里造出假股骨的两个 STEP：cortical.step（皮质壳）和 cancellous.step（松质芯）。真值见 TRUTH。"""
    folder.mkdir(parents=True, exist_ok=True)
    if not _CAD:
        import gmsh

        kept = os.environ.get("PATH", "")
        for name in ("cancellous", "cortical"):
            gmsh.initialize()
            try:
                gmsh.option.setNumber("General.Terminal", 0)
                occ = gmsh.model.occ
                core = _femur_shapes(occ, inner=True)
                if name == "cortical":
                    occ.cut(_femur_shapes(occ, inner=False), core, removeObject=True, removeTool=True)
                occ.synchronize()
                gmsh.write(str(folder / f"{name}.step"))
            finally:
                gmsh.finalize()
                os.environ["PATH"] = kept       # gmsh 初始化时会把这个进程的 PATH 截短；放回去，不然后面找不到 git
            _CAD[name] = (folder / f"{name}.step").read_bytes()
    for name, content in _CAD.items():
        (folder / f"{name}.step").write_bytes(content)
    return folder


def cad_source(tmp: Path, bone_id: str = BONE, files: dict | None = None) -> dict:
    """登记一份 CAD 骨源：假股骨的两个 STEP。files 给了就用它当文件夹的内容。"""
    folder = tmp / f"source-{next(_NAMES)}"
    if files is None:
        cad_femur(folder)
        files = {path.name: path.read_bytes() for path in folder.iterdir()}
    helpers.make_folder(folder, kind="bone_source", files=files, bone_id=bone_id)
    seen = any(item["bone_id"] == bone_id for item in lookup.find())
    return register.register_external("bone_source", f"{bone_id}-cad", source=folder, note="测试用的 CAD 骨源", by="tester",
                                      bone_id=bone_id, new_bone=not seen)


GATE = [
    {"name": "cortical_closed", "value": "cortical_watertight", "equals": True, "what": "皮质实体的表面封闭"},
    {"name": "cancellous_closed", "value": "cancellous_watertight", "equals": True, "what": "松质实体的表面封闭"},
    {"name": "head_fit", "value": "head_fit_rms_mm", "max": 1.0, "what": "股骨头球拟合的残差不超过 1 mm"},
    {"name": "neck_wall", "value": "neck_wall_min_mm", "min": 0.3, "what": "股骨颈处皮质最薄不小于 0.3 mm"},
]
FINAL_GATE = GATE + [
    {"name": "volume_kept", "value": "cortical_volume_change", "max": 0.005, "what": "皮质实体的体积和候选时相差不超过 0.5%"},
    {"name": "landmarks_near", "value": "landmark_shift_max_mm", "max": 5.0, "what": "定稿的标志点离自动找的不超过 5 mm"},
]


def recon_setting(gate=None, **change) -> dict:
    """登记一份重建设定。"""
    value = {"side": "right", "frame": BONE_EXTRA["frame"], "materials": BONE_EXTRA["materials"],
             "source": {"cortical": "cortical.step", "cancellous": "cancellous.step"}, "tessellation_mm": 4.0,
             "gate": GATE if gate is None else gate}
    return setting({**value, **change})


def recon_draft(tmp: Path, source: dict | None = None, value: dict | None = None) -> str:
    """新建一个 recon.draft 实验并填好。"""
    made = actions.new("recon.draft", note="测试用的重建")
    actions.fill(made, "source", [(source or cad_source(tmp))["id"]])
    actions.fill(made, "setting", [(value or recon_setting())["id"]])
    return made


def recon_finalize(draft: str, value: dict | None = None, edits: dict | None = None, kernel: dict | None = None) -> str:
    """新建一个 recon.finalize 实验：draft 是登记的候选骨模型的编号。"""
    made = actions.new("recon.finalize", note="测试用的定稿")
    actions.fill(made, "draft", [draft])
    actions.fill(made, "setting", [(value or recon_setting(FINAL_GATE))["id"]])
    if edits is not None:
        actions.fill(made, "edits", [edits["id"]])
    if kernel is not None:
        actions.fill(made, "kernel", [kernel["id"]])
    return made


def edits(tmp: Path, value: dict, files: dict | None = None) -> dict:
    """登记一份人工修改。"""
    import json

    folder = tmp / f"edits-{next(_NAMES)}"
    helpers.make_folder(folder, kind="edits", files={"edits.json": json.dumps(value, ensure_ascii=False).encode("utf-8"), **(files or {})})
    return register.register_external("edits", f"edits-{next(_NAMES)}", source=folder, note="测试用的人工修改", by="tester")


# ---------------------------------------------------------------- 代理：一张现造的数据

# 和假内核、假推导量定义给出的列一样（少一个场），数也照它们的算法来：这样预测可以拿去和假 FEA 的结果复核
DATA_COLUMNS = [
    {"name": "length", "unit": "mm", "meaning": "stem length", "role": "design"},
    {"name": "behave", "unit": "1", "meaning": "how the fake kernel behaves for this design", "role": "design"},
    {"name": "load", "unit": "N", "meaning": "head load", "role": "condition"},
    {"name": "bone_removed", "unit": "mm3", "meaning": "bone removed, known from templating", "role": "pre"},
    {"name": "rotation", "unit": "deg", "meaning": "rotation under the first load", "role": "label"},
    {"name": "contact", "unit": "1", "meaning": "closed share of the interface", "role": "label"},
    {"name": "slip_p95", "unit": "um", "meaning": "95th percentile of the interface slip", "role": "derived"},
]


FIELD_COLUMN = {"name": "interface_slip", "unit": "um", "meaning": "slip at each interface node", "role": "field"}
# 现造的数据记着是哪个内核、哪份推导量定义算的（清单里的 made_by）。几份放在一起用的时候靠它拦住不同内核的数
MADE_BY = {"kernel": {"name": "fake-kernel-1", "code_hash": "0123456789"}, "derive": {"package": "d" * 64}}


def fe_truth(length: float, load: float) -> dict:
    """假内核对这个设计会算出的数。"""
    return {"rotation": load / (length * 1000.0), "contact": 0.5, "slip_p95": 0.95 * length / 2.0}


def field_of(length: float) -> list[float]:
    """假内核对这个设计给出的场：界面上五个节点的滑移。它的最大值乘 0.95 就是 slip_p95。"""
    return [length / 10.0 * step for step in range(1, 6)]


def spread(count: int, seed: int = 1, lengths=(25.0, 55.0), loads=(1500.0, 2500.0)) -> list[tuple]:
    """count 个（长度，载荷），在范围里撒开。同样的种子给同样的一批。"""
    import random

    rng = random.Random(seed)
    return [(round(rng.uniform(*lengths), 3), round(rng.uniform(*loads), 1)) for _ in range(count)]


def data_rows(designs, bone_id: str = BONE, number: int = 1, misfit=(), fields: bool = False) -> list[dict]:
    """数据的各行。misfit 里的（长度，载荷）记成放不进去：这一行在，FE 的结果是空的。
    fields 给 True，算出来的各行另带一个场（interface_slip）：data() 登记时照 field_of 把它的文件写出来。"""
    from stemlab.contract.formats.points import point_hash
    from stemlab.contract.hashing import hash_json

    rows = []
    for length, load in designs:
        point = {"bone_id": bone_id, "design": {"length": length, "behave": "ok"}, "conditions": {"load": load}}
        known = (length, load) not in misfit
        numbers = fe_truth(length, load) if known else {"rotation": None, "contact": None, "slip_p95": None}
        made = point_hash(point)
        rows.append({"point": made, "bone_id": bone_id, "round": number, "fingerprint": hash_json({"of": point}),
                     "outcome": "finished" if known else "misfit",
                     "fields": {FIELD_COLUMN["name"]: f"fields/{made[:16]}/interface_slip.json"} if fields and known else {},
                     "values": {"length": length, "behave": "ok", "load": load, "bone_removed": length * 100.0 if known else None, **numbers}})
    return rows


def data(tmp: Path, rows, bone_id: str | None = BONE, columns=None, field=field_of, made_by=MADE_BY) -> dict:
    """登记一份数据。几根骨混在一起的，bone_id 给 None。columns 给了就用它当数据说明（默认是 DATA_COLUMNS）。
    行里带着场的，场的文件在这里写出来（内容是 field(这一行的长度)），数据说明里也加上场的那一列。
    made_by 是清单里记的“哪个内核算的”，默认是 MADE_BY；给 None 就是没记。"""
    import json

    from stemlab.contract.hashing import canonical

    folder = tmp / f"data-{next(_NAMES)}"
    folder.mkdir(parents=True)
    (folder / "rows.jsonl").write_bytes(b"".join(canonical(row) + b"\n" for row in rows))
    extra = {"bone_id": bone_id} if bone_id else {}
    files = ["rows.jsonl"]
    for row in rows:
        for rel in row["fields"].values():
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_bytes(json.dumps(field(row["values"]["length"])).encode("utf-8"))
            files.append(rel)
    if len(files) > 1 and columns is None:
        columns = DATA_COLUMNS + [FIELD_COLUMN]
    if made_by is not None:                 # 给 None：不知道是哪个内核算的
        extra["made_by"] = made_by
    write_manifest(folder, make_manifest("data", files, count=len(rows), columns=columns or DATA_COLUMNS, **extra))
    seen = bone_id is None or any(item["bone_id"] == bone_id for item in lookup.find())
    return register.register_external("data", f"data-{next(_NAMES)}", source=folder, note="测试用的数据", by="tester",
                                      bone_id=bone_id, new_bone=not seen)


LINES = [
    {"id": "a1", "what": "转动的留出误差不超过 0.05 dex", "target": "rotation", "on": "holdout", "metric": "rmse", "op": "<=", "limit": 0.05},
    {"id": "a2", "what": "转动的区间覆盖率不低于 0.8", "target": "rotation", "on": "holdout", "metric": "coverage", "op": ">=", "limit": 0.8},
]


def train_setting(**change) -> dict:
    """登记一份训练设定。"""
    return setting({"targets": ["rotation", "slip_p95"], "seed": 11, "level": 0.95, "scale": {"rotation": "log10"},
                    "acceptance": LINES, **change})


def split_setting(**change) -> dict:
    return setting({"by": "row", "fraction": 0.25, "seed": 3, **change})


def train(datas, value: dict | None = None, split: dict | None = None) -> str:
    """新建一个 surrogate.train 实验并填好。"""
    made = actions.new("surrogate.train", note="测试用的训练")
    actions.fill(made, "data", [item["id"] for item in datas])
    actions.fill(made, "setting", [(value or train_setting())["id"]])
    actions.fill(made, "split", [(split or split_setting())["id"]])
    return made


def predict(predictor: str, batch: dict) -> str:
    """新建一个 surrogate.predict 实验：predictor 是登记的预测器的编号，batch 是登记的一批点。"""
    made = actions.new("surrogate.predict", note="测试用的出预测")
    actions.fill(made, "predictor", [predictor])
    actions.fill(made, "points", [batch["id"]])
    return made


def check(prediction: str, measured: dict) -> str:
    """新建一个 surrogate.check 实验：prediction 是登记的一份预测的编号，measured 是登记的一份数据。"""
    made = actions.new("surrogate.check", note="测试用的复核")
    actions.fill(made, "prediction", [prediction])
    actions.fill(made, "data", [measured["id"]])
    return made


OUTSIDE_MAIN = b"""\
import json, pathlib, sys
source, out = map(pathlib.Path, sys.argv[1:3])
rows = []
for point in json.loads((source / "job.json").read_text())["points"]:
    value = point["conditions"]["load"] / (point["design"]["length"] * 1000.0)
    rows.append({"point": point["hash"], "values": {"rotation": value}, "lower": {"rotation": 0.9 * value}, "upper": {"rotation": 1.1 * value}})
(out / "result.json").write_text(json.dumps({"rows": rows}))
"""


def outside_predictor(tmp: Path, lengths=(20.0, 60.0), made_by=None) -> dict:
    """登记一个外面训练好的预测器：它有自己的入口，不是这个系统打的包。"""
    import json

    from stemlab.contract.formats.points import point_hash

    sample = {"bone_id": BONE, "design": {"length": 30.0, "behave": "ok"}, "conditions": {"load": 2100.0}}
    sample["hash"] = point_hash(sample)
    expected = {"rows": [{"point": sample["hash"], "values": {"rotation": 0.07}, "lower": {"rotation": 0.063}, "upper": {"rotation": 0.077}}]}
    files = {"code/main.py": OUTSIDE_MAIN, "data/selftest/one/input/job.json": json.dumps({"points": [sample]}).encode(),
             "data/selftest/one/expected.json": json.dumps(expected).encode()}
    folder = helpers.write_files(tmp / f"outside-predictor-{next(_NAMES)}", files)
    scope = {"bones": [BONE], "design": {"length": {"min": lengths[0], "max": lengths[1]}, "behave": {"values": ["ok"]}},
             "conditions": {"load": {"min": 1000.0, "max": 3000.0}}}
    write_manifest(folder, make_manifest(
        "predictor", list(files), entry=["{python}", "code/main.py"], requires=["python>=3.12"], tolerance={"rel": 1e-9, "abs": 1e-12},
        selftest=[{"name": "one", "input": "data/selftest/one/input", "expected": "data/selftest/one/expected.json"}], range=scope,
        level=0.9, columns=[column for column in DATA_COLUMNS if column["name"] == "rotation"], **({"made_by": made_by} if made_by else {})))
    return register.register_external("predictor", f"outside-predictor-{next(_NAMES)}", source=folder, note="测试：外面训练的预测器", by="tester")


# ---------------------------------------------------------------- 优化：候选池、目标、选点设定

SPACE = {"design": {"length": [20.0, 80.0], "behave": {"values": ["ok"]}}, "count": 12, "seed": 5}


def objective(**change) -> dict:
    """登记一份目标和约束。"""
    value = {"version": "v1", "objectives": [{"column": "rotation", "goal": "min"}], "constraints": [], **change}
    return register.register_external("objective", f"objective-{next(_NAMES)}", value=value, note="测试用的目标", by="tester")


def how(**change) -> dict:
    """登记一份选点设定：条件默认、选几个、种子。"""
    return setting({"conditions": {"load": 2000.0}, "count": 3, "seed": 7, **change})


def pool_rows(lengths, bone_id: str = BONE) -> list[dict]:
    """候选池的各行，照假内核的规矩：长度超过 60 的放不进去。"""
    rows = []
    for number, length in enumerate(lengths, start=1):
        fits = length <= 60
        info = {"bone_removed": length * 100.0, **({} if fits else {"reason": "no entry offset lets this stem fit"})}
        rows.append({"name": f"c{number:04d}", "bone_id": bone_id, "design": {"length": float(length), "behave": "ok"},
                     "feasible": fits, "info": info})
    return rows


def pool(tmp: Path, rows, made_by=None) -> dict:
    """直接登记一个候选池（不经 opt.pool）。made_by 给了就写进清单：这个池是哪个内核模板化的。"""
    folder = tmp / f"pool-{next(_NAMES)}"
    write_points(folder, rows, kind="pool", **({"made_by": made_by} if made_by else {}))
    return register.register_external("pool", f"pool-{next(_NAMES)}", source=folder, note="测试用的候选池", by="tester")


def opt_pool(tmp: Path, space: dict | None = None, kernel: dict | None = None, bone: dict | None = None) -> str:
    """新建一个 opt.pool 实验并填好。"""
    made = actions.new("opt.pool", note="测试用的出候选池")
    actions.fill(made, "bone", [(bone or bone_model(tmp))["id"]])
    actions.fill(made, "kernel", [(kernel or package("kernel_fake", tmp))["id"]])
    actions.fill(made, "range", [setting(SPACE if space is None else space)["id"]])
    return made


def opt_select(tmp: Path, candidates: str, strategy: dict | None = None, goal: dict | None = None, defaults: dict | None = None,
               datas=(), predictor: dict | None = None) -> str:
    """新建一个 opt.select 实验并填好。candidates 是登记的候选池的编号。"""
    made = actions.new("opt.select", note="测试用的选点")
    actions.fill(made, "objective", [(goal or objective())["id"]])
    actions.fill(made, "strategy", [(strategy or package("strategy_fake", tmp))["id"]])
    actions.fill(made, "pool", [candidates])
    actions.fill(made, "defaults", [(defaults or how())["id"]])
    if datas:
        actions.fill(made, "data", [item["id"] for item in datas])
    if predictor is not None:
        actions.fill(made, "predictor", [predictor["id"]])
    return made
