"""mobo_toy 作图样式与产物写出（REPORTING_SPEC.md 第 3、4 节的代码实现）。

约定
----
* 每张图 = PNG(300 dpi) + SVG(文字可编辑) + 数据 CSV + meta JSON，四件同名，放在
  reports/<Rk 目录>/figures/。图只能由 CSV 画出：``plot_fn(csv_path) -> Figure``，
  因此 ``python report.py --replot R2-F03`` 可以只凭数据一键重画。
* 每张表 = CSV + meta JSON，放在 reports/<Rk 目录>/tables/。
* 验收结果写 reports/<Rk 目录>/acceptance.json；输入与版本写 inputs.json。
* Dorr A/B/C 固定用 Okabe–Ito 色盲友好色；方法用线型区分；失败等级固定颜色。
* 图内文字用英文（便于直接进论文与导师汇报），报告正文用中文。
* 合成数据（demo / 占位）必须 ``synthetic=True``：图上加水印，报告首页加横幅。

单位：长度 mm、力 N、应力 MPa、微动 µm（CLAUDE.md §7）。
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import importlib.util
import inspect
import json
import math
import pathlib
import platform
import sys
from typing import Callable, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SPEC_PATH = REPORTS / "spec.yaml"
CONFIG_PATH = ROOT / "config.yaml"

# ---------------------------------------------------------------- colours
OKABE_ITO = {
    "black": "#000000", "orange": "#E69F00", "sky": "#56B4E9", "green": "#009E73",
    "yellow": "#F0E442", "blue": "#0072B2", "vermillion": "#D55E00", "purple": "#CC79A7",
}
DORR = {"A": "#0072B2", "B": "#009E73", "C": "#D55E00"}          # 固定，全项目不改
DORR_MARKER = {"A": "o", "B": "s", "C": "^"}                      # 灰度打印时靠形状区分
METHOD = {                                                        # 方法靠线型区分，颜色跟分型走
    "qNEHVI": {"ls": "-", "lw": 1.4},
    "Sobol": {"ls": "--", "lw": 1.2, "color": "#7F7F7F"},
    "reference": {"ls": "-", "lw": 1.0, "color": "#000000"},
}
STATUS = {"OK": "#000000", "L1": "#E69F00", "L2": "#CC79A7", "L3": "#56B4E9",
          "L4": "#D55E00", "L5": "#F0E442"}                      # CLAUDE.md §10 失败分级
GREY, LIGHT = "#7F7F7F", "#BBBBBB"
THRESHOLD = {"color": "#000000", "ls": ":", "lw": 0.9}            # 门槛线（50/150 µm、0.9 HV 比…）

# ---------------------------------------------------------------- sizes (Elsevier 栏宽)
MM = 1 / 25.4
WIDTH_MM = {"single": 90, "onehalf": 140, "double": 190}
DPI = 300

# ---------------------------------------------------------------- canonical axis labels（带单位）
LABEL = {
    "f1": "Micromotion P95 (µm)",
    "f1_log": "log10 micromotion P95 (log µm)",
    "f2": "Gruen 7 SED loss (%)",
    "f2_g1": "Gruen 1 SED loss (%)",
    "vm_p99": "Stem von Mises P99 (MPa)",
    "slip": "Tangential slip increment (µm)",
    "cpress": "Contact pressure (MPa)",
    "arc": "Arc length from resection (mm)",
    "h": "Interface element size (mm)",
    "n_elem": "Number of elements (–)",
    "wall": "Wall-clock time (s)",
    "n_fe": "FE evaluations (–)",
    "n_eval": "Function evaluations (–)",
    "hv_ratio": "HV / HV_ref (–)",
    "log_hv_diff": "log10(HV_ref − HV) (–)",
    "igd": "IGD (normalised, –)",
    "wall_thk": "Residual cortical wall (mm)",
    "L": "Arc length L (mm)",
    "kappa": "Curvature κ (1/mm)",
    "w_prox": "Proximal half-width / canal (–)",
    "taper": "Tip / proximal half-width (–)",
    "theta_in": "Entry angle vs neck axis (°)",
    "nominal": "Nominal coverage (–)",
    "empirical": "Empirical coverage (–)",
}


def apply_style() -> None:
    """全项目统一 rcParams。字号按印刷尺寸：正文 8 pt，最小 6.5 pt。"""
    plt.rcParams.update({
        "font.family": ["Arial", "Microsoft YaHei", "DejaVu Sans"],
        "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
        "legend.frameon": False, "axes.linewidth": 0.8, "lines.linewidth": 1.2,
        "lines.markersize": 3.5, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#E5E5E5", "grid.linewidth": 0.5,
        "figure.dpi": 100, "savefig.dpi": DPI, "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02, "svg.fonttype": "none", "svg.hashsalt": "mobo_toy",
        "axes.unicode_minus": False, "figure.constrained_layout.use": True,
    })


apply_style()


def new_figure(width: str = "single", height_mm: float = 65, nrows: int = 1, ncols: int = 1,
               **kw):
    """按栏宽建图。width ∈ single(90 mm) / onehalf(140 mm) / double(190 mm)。"""
    fig, axes = plt.subplots(nrows, ncols, figsize=(WIDTH_MM[width] * MM, height_mm * MM), **kw)
    return fig, axes


def panel_labels(axes, start: str = "a") -> None:
    """多面板图左上角加 (a)(b)(c)…。"""
    flat = list(axes) if isinstance(axes, (list, tuple)) else list(getattr(axes, "flat", [axes]))
    for i, ax in enumerate(flat):
        ax.text(-0.02, 1.02, f"({chr(ord(start) + i)})", transform=ax.transAxes,
                ha="right", va="bottom", fontsize=8, fontweight="bold")


def shared_limits(*arrays: Iterable[float], pad: float = 0.05, log: bool = False):
    """跨分型图共用坐标范围：返回 (lo, hi)。"""
    vals = [float(v) for a in arrays for v in a if v is not None and math.isfinite(float(v))]
    if log:
        vals = [math.log10(v) for v in vals if v > 0]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or abs(hi) or 1.0
    lo, hi = lo - pad * span, hi + pad * span
    return (10 ** lo, 10 ** hi) if log else (lo, hi)


def threshold_line(ax, value: float, axis: str = "y", label: str | None = None) -> None:
    (ax.axhline if axis == "y" else ax.axvline)(value, **THRESHOLD)
    if label:
        if axis == "y":
            ax.annotate(label, (1.0, value), xycoords=("axes fraction", "data"), xytext=(-1, 1),
                        textcoords="offset points", ha="right", va="bottom", fontsize=6.5)
        else:
            ax.annotate(label, (value, 0.98), xycoords=("data", "axes fraction"), xytext=(2, 0),
                        textcoords="offset points", ha="left", va="top", fontsize=6.5, rotation=90)


def mark_synthetic(fig) -> None:
    fig.text(0.5, 0.5, "SYNTHETIC — pipeline demo, not a result", ha="center", va="center",
             rotation=25, fontsize=14, color="#D55E00", alpha=0.28, fontweight="bold",
             transform=fig.transFigure, zorder=100)


# ---------------------------------------------------------------- spec / paths
def load_spec() -> dict:
    import yaml
    with open(SPEC_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def report_id_of(item_id: str) -> str:
    """'R2-F03' -> 'R2'；'RD-T01' -> 'RD'。"""
    return item_id.split("-")[0]


def report_dir(report_id: str) -> pathlib.Path:
    spec = load_spec()
    if report_id not in spec["reports"]:
        raise KeyError(f"未登记的报告 {report_id}（见 reports/spec.yaml）")
    d = REPORTS / spec["reports"][report_id]["dir"]
    for sub in ("figures", "tables", "text", "history"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def _registered_ids(report_id: str, kind: str) -> set[str]:
    rep = load_spec()["reports"][report_id]
    return {x["id"] for x in rep.get(kind, [])}


def rel(p: pathlib.Path | str) -> str:
    p = pathlib.Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def sha256_file(path: pathlib.Path | str) -> str | None:
    p = pathlib.Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- CSV io
def write_csv(path: pathlib.Path, rows: Sequence[Mapping], columns: Sequence[str] | None = None) -> None:
    if not rows:
        raise ValueError(f"{path.name}: 空数据不写（禁止静默产出空图）")
    columns = list(columns or rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="raise")
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt_cell(r.get(k)) for k in columns})


def _fmt_cell(v):
    if isinstance(v, float):
        return repr(v)            # 全精度，保证重画逐位一致
    return "" if v is None else v


def read_csv(path: pathlib.Path | str) -> dict[str, list]:
    """读成 {列名: 值列表}；能转成数的转成 float。"""
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    cols = {k: [] for k in (rows[0].keys() if rows else [])}
    for r in rows:
        for k, v in r.items():
            cols[k].append(_num(v))
    return cols


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return v


# ---------------------------------------------------------------- publishing
def _fn_ref(fn: Callable) -> tuple[str, str]:
    src = inspect.getsourcefile(fn)
    if src is None:
        raise ValueError("plot_fn 必须是模块顶层函数（replot 要能按文件导入）")
    if fn.__qualname__ != fn.__name__:
        raise ValueError("plot_fn 必须是模块顶层函数，不能是嵌套函数或 lambda")
    return rel(src), fn.__name__


def _caller_script() -> str:
    for fr in inspect.stack()[2:]:
        if pathlib.Path(fr.filename).resolve() != pathlib.Path(__file__).resolve():
            return fr.filename
    return sys.argv[0]


def publish_figure(fig_id: str, rows: Sequence[Mapping], plot_fn: Callable, *, title: str,
                   caption: str, units: Mapping[str, str] | None = None, synthetic: bool = False,
                   sources: Mapping | None = None, columns: Sequence[str] | None = None) -> pathlib.Path:
    """写 CSV → 用 plot_fn 从 CSV 画图 → 存 PNG/SVG/meta。

    title   : 结论句（报告里作图题，例如 "BO reaches 90 % of HV_ref within 36 FE runs for Dorr B"）。
    caption : 图里有什么、怎么读、样本量、误差棒含义。
    sources : 数据来源，如 {"runs_csv_rows": "2–257", "design_ids": "d000001–d000256"}。
    """
    rid = report_id_of(fig_id)
    if fig_id not in _registered_ids(rid, "figures"):
        print(f"[plotstyle] 注意：{fig_id} 未在 spec.yaml 登记，将作为附加图出现在报告末尾")
    d = report_dir(rid) / "figures"
    csv_path = d / f"{fig_id}.csv"
    write_csv(csv_path, rows, columns)
    fig = plot_fn(csv_path)
    if synthetic:
        mark_synthetic(fig)
    png, svg = d / f"{fig_id}.png", d / f"{fig_id}.svg"
    fig.savefig(png, dpi=DPI, metadata={"Software": None})
    fig.savefig(svg, metadata={"Date": None, "Creator": None})
    plt.close(fig)
    mod_path, fn_name = _fn_ref(plot_fn)
    producer = _caller_script()
    meta = {
        "id": fig_id, "report": rid, "kind": "figure", "title": title, "caption": caption,
        "synthetic": bool(synthetic), "units": dict(units or {}), "sources": dict(sources or {}),
        "csv": rel(csv_path), "csv_sha256": sha256_file(csv_path),
        "png": rel(png), "svg": rel(svg),
        "plot_fn": f"{mod_path}:{fn_name}", "plot_module_sha256": sha256_file(ROOT / mod_path),
        "producer": rel(producer), "producer_sha256": sha256_file(producer),
        "config_sha256": sha256_file(CONFIG_PATH), "spec_sha256": sha256_file(SPEC_PATH),
        "created": _now(), "python": platform.python_version(), "matplotlib": matplotlib.__version__,
    }
    (d / f"{fig_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return png


def publish_table(table_id: str, rows: Sequence[Mapping], *, title: str, caption: str = "",
                  units: Mapping[str, str] | None = None, synthetic: bool = False,
                  sources: Mapping | None = None, columns: Sequence[str] | None = None) -> pathlib.Path:
    rid = report_id_of(table_id)
    if table_id not in _registered_ids(rid, "tables"):
        print(f"[plotstyle] 注意：{table_id} 未在 spec.yaml 登记，将作为附加表出现在报告末尾")
    d = report_dir(rid) / "tables"
    csv_path = d / f"{table_id}.csv"
    write_csv(csv_path, rows, columns)
    producer = _caller_script()
    meta = {
        "id": table_id, "report": rid, "kind": "table", "title": title, "caption": caption,
        "synthetic": bool(synthetic), "units": dict(units or {}), "sources": dict(sources or {}),
        "csv": rel(csv_path), "csv_sha256": sha256_file(csv_path),
        "producer": rel(producer), "producer_sha256": sha256_file(producer),
        "config_sha256": sha256_file(CONFIG_PATH), "created": _now(),
    }
    (d / f"{table_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path


VALID_STATUS = ("PASS", "FAIL", "NA", "PENDING")


def publish_acceptance(report_id: str, results: Sequence[Mapping], synthetic: bool = False) -> pathlib.Path:
    """results: [{"id": "R2-A1", "measured": "3.1 %", "status": "PASS", "note": "…"}]。

    status ∈ PASS / FAIL / NA / PENDING。FAIL 与 NA 必须写 note（原因与处置）。
    """
    known = _registered_ids(report_id, "acceptance")
    out = []
    for r in results:
        if r["id"] not in known:
            raise KeyError(f"{r['id']} 不是 {report_id} 的登记验收项（spec.yaml）")
        if r["status"] not in VALID_STATUS:
            raise ValueError(f"{r['id']}: status 必须是 {VALID_STATUS}")
        if r["status"] in ("FAIL", "NA") and not r.get("note"):
            raise ValueError(f"{r['id']}: {r['status']} 必须写 note（原因与处置）")
        out.append({"id": r["id"], "measured": r.get("measured", ""), "status": r["status"],
                    "note": r.get("note", "")})
    p = report_dir(report_id) / "acceptance.json"
    p.write_text(json.dumps({"report": report_id, "synthetic": synthetic, "created": _now(),
                             "producer": rel(_caller_script()), "items": out},
                            ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def publish_inputs(report_id: str, **info) -> pathlib.Path:
    """阶段输入与版本，例如 abaqus="2025 (abq2025.bat)", runs_csv_rows="2–257", seeds=[0,1,2]。"""
    p = report_dir(report_id) / "inputs.json"
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    old.update({k: v for k, v in info.items()})
    old["updated"] = _now()
    p.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def replot(fig_id: str, out_suffix: str = "") -> pathlib.Path:
    """只凭 CSV + meta 里登记的 plot_fn 重画（校验 CSV 哈希未变）。"""
    d = report_dir(report_id_of(fig_id)) / "figures"
    meta = json.loads((d / f"{fig_id}.json").read_text(encoding="utf-8"))
    csv_path = ROOT / meta["csv"]
    if sha256_file(csv_path) != meta["csv_sha256"]:
        raise RuntimeError(f"{fig_id}: CSV 哈希与 meta 不符，数据被改过")
    mod_path, fn_name = meta["plot_fn"].rsplit(":", 1)
    spec = importlib.util.spec_from_file_location(f"_replot_{fn_name}", ROOT / mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fig = getattr(mod, fn_name)(csv_path)
    if meta.get("synthetic"):
        mark_synthetic(fig)
    # 保存顺序必须与 publish_figure 相同（先 PNG 后 SVG）：constrained layout 每次绘制会微调，
    # 顺序不同会让 SVG 坐标差在亚像素级
    out = d / f"{fig_id}{out_suffix}.svg"
    fig.savefig(d / f"{fig_id}{out_suffix}.png", dpi=DPI, metadata={"Software": None})
    fig.savefig(out, metadata={"Date": None, "Creator": None})
    plt.close(fig)
    return out


def sig(x, n: int = 3) -> str:
    """表格数值统一三位有效数字。"""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if x == 0 or not math.isfinite(x):
        return str(x)
    return f"{x:.{n}g}"
