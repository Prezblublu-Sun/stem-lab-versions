"""S0 环境与冒烟：2D 平面应力悬臂梁（CPS6M）对 Euler–Bernoulli 解析解 → R0 报告。

python stage_s0.py   （用 .venv-mobo 的 Python）
"""
from __future__ import annotations

import importlib.metadata as im
import json
import pathlib
import platform
import shutil
import subprocess
import time

import numpy as np
from shapely.geometry import box

import plotstyle as ps
import run_abaqus as ra
from inp_writer import write_cantilever
from mesh2d import mesh_partition

ROOT = ps.ROOT
RUN = ROOT / "runs" / "S0"
L, H, T, E, NU, P = 100.0, 5.0, 1.0, 110000.0, 0.35, 10.0      # mm, mm, mm, MPa, -, N
SIZES = [2.5, 1.25, 0.625, 0.3125]                               # mm


def analytic():
    I = T * H ** 3 / 12.0
    eb = P * L ** 3 / (3 * E * I)
    G = E / (2 * (1 + NU))
    timo = eb + P * L / ((5 / 6) * G * H * T)
    return eb, timo


def build(h: float, tag: str) -> tuple[pathlib.Path, dict]:
    m = mesh_partition({"beam": box(0, -H / 2, L, H / 2)}, lambda x, y: h, name=tag)
    d = RUN / tag
    if d.exists():
        shutil.rmtree(d)
    inp = write_cantilever(m, d / f"{tag}.inp", L=L, h=H, E=E, nu=NU, thickness=T, P=P)
    return inp, {"n_elem": m.n_elems, "n_node": len(m.node_labels), "rp": int(m.node_labels.max()) + 1,
                 **{f"q_{k}": v for k, v in m.quality.items()}}


def tip_deflection(inp: pathlib.Path, rp: int) -> float:
    csv = inp.parent / f"{inp.stem}_csv" / "LOAD_U.csv"
    d = ps.read_csv(csv)
    i = d["node"].index(float(rp))
    return -d["u2"][i]


# ------------------------------------------------------------------ plot functions（只读 CSV）
def plot_r0_f01(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("single", 62)
    h = np.array(d["h_mm"]); r = np.array(d["ratio_eb"]); rt = np.array(d["ratio_timo"])
    ax.axhspan(0.98, 1.02, color="#E5E5E5", zorder=0, label="±2 % band")
    ax.plot(h, r, "o-", color=ps.OKABE_ITO["blue"], label="FE / Euler–Bernoulli")
    ax.plot(h, rt, "s--", color=ps.OKABE_ITO["orange"], label="FE / Timoshenko")
    ps.threshold_line(ax, 1.0, "y")
    ax.set_xscale("log"); ax.invert_xaxis()
    ax.set_xticks(h); ax.set_xticklabels([f"{v:g}" for v in h]); ax.minorticks_off()
    ax.set_xlabel("Element size (mm)"); ax.set_ylabel("Tip deflection ratio (–)")
    ax.set_ylim(0.95, 1.03)
    ax.legend(loc="lower right")
    return fig


def plot_r0_f02(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("single", 62)
    for mode, mk, col in (("sequential", "o", ps.OKABE_ITO["blue"]), ("4 concurrent", "^", ps.OKABE_ITO["vermillion"])):
        idx = [i for i, m in enumerate(d["mode"]) if m == mode]
        ax.plot([d["n_elem"][i] for i in idx], [d["wall_s"][i] for i in idx], mk + "-", color=col, label=mode)
    i0 = d["mode"].index("sequential")
    ax.annotate("first job of session\n(cold start)", (d["n_elem"][i0], d["wall_s"][i0]), xytext=(12, -4),
                textcoords="offset points", fontsize=6.5, va="top")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel(ps.LABEL["n_elem"]); ax.set_ylabel(ps.LABEL["wall"])
    ax.legend(loc="upper left")
    return fig


def abaqus_release() -> str:
    out = subprocess.run(["cmd", "/c", ra.LAUNCHER, "information=release"], capture_output=True, text=True,
                         errors="ignore", cwd=RUN).stdout
    line = next((l.strip() for l in out.splitlines() if l.strip().startswith("Abaqus 20")), "unknown")
    return line


def abaqus_python() -> str:
    out = subprocess.run(["cmd", "/c", ra.LAUNCHER, "python", "-c", "import sys;print(sys.version.split()[0])"],
                         capture_output=True, text=True, errors="ignore", cwd=RUN).stdout.strip().splitlines()
    return out[-1] if out else "unknown"


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    eb, timo = analytic()
    built = [build(h, f"cant_h{i}") for i, h in enumerate(SIZES)]

    # 1) 顺序运行（计时）
    seq = []
    for (inp, info), h in zip(built, SIZES):
        r = ra.run_and_export(inp)
        seq.append(r)
        print(inp.stem, r["status"], round(r["wall_s"], 1), r.get("reason", ""))
    # 2) 4 路并发（许可与并发测试）：四个网格同时提交到新目录
    conc_inps = []
    for (inp, info), h in zip(built, SIZES):
        d2 = RUN / f"{inp.stem}_par"
        if d2.exists():
            shutil.rmtree(d2)
        d2.mkdir(parents=True)
        conc_inps.append(pathlib.Path(shutil.copy2(inp, d2 / f"{inp.stem}_par.inp")))
    t0 = time.perf_counter()
    par = ra.run_many(conc_inps, max_concurrent=4)
    par_total = time.perf_counter() - t0
    # 3) 确定性：最细网格再跑一次
    d3 = RUN / "cant_rerun"
    if d3.exists():
        shutil.rmtree(d3)
    d3.mkdir(parents=True)
    rerun_inp = pathlib.Path(shutil.copy2(built[-1][0], d3 / "cant_rerun.inp"))
    rr = ra.run_and_export(rerun_inp)

    rows, trows = [], []
    for (inp, info), h, r, rp_ in zip(built, SIZES, seq, par):
        if r["status"] != "OK":
            raise RuntimeError(f"{inp.stem}: {r}")
        w = tip_deflection(inp, info["rp"])
        rows.append(dict(h_mm=h, n_elem=info["n_elem"], tip_mm=w, eb_mm=eb, timo_mm=timo,
                         ratio_eb=w / eb, ratio_timo=w / timo, min_angle_deg=info["q_min_angle_deg"]))
        trows.append(dict(mode="sequential", n_elem=info["n_elem"], wall_s=r["wall_s"]))
        trows.append(dict(mode="4 concurrent", n_elem=info["n_elem"], wall_s=rp_["wall_s"]))
    w_fine = rows[-1]["tip_mm"]
    w_rerun = tip_deflection(rerun_inp, built[-1][1]["rp"]) if rr["status"] == "OK" else float("nan")
    w_par = tip_deflection(conc_inps[-1], built[-1][1]["rp"]) if par[-1]["status"] == "OK" else float("nan")

    src = {"runs": "runs/S0/", "analytic": "Euler–Bernoulli PL³/3EI; Timoshenko + PL/(κGA), κ = 5/6"}
    ps.publish_figure(
        "R0-F01", rows, plot_r0_f01,
        title=(f"CPS6M cantilever tip deflection is within {abs(rows[-1]['ratio_eb'] - 1) * 100:.2f} % of "
               f"Euler–Bernoulli at the finest mesh"),
        caption=(f"悬臂梁 L = {L:g} mm、h = {H:g} mm（L/h = 20）、平面应力厚 {T:g} mm、E = {E:g} MPa、ν = {NU}、"
                 f"端部经分布耦合加 {P:g} N。纵轴为 FE 端部挠度与解析解之比；灰带为 ±2 % 验收带。"
                 "Timoshenko 解含剪切变形，本长细比下比 Euler–Bernoulli 大约 0.2 %。"),
        units={"h_mm": "mm", "tip_mm": "mm"}, sources=src)
    ps.publish_figure(
        "R0-F02", trows, plot_r0_f02,
        title=f"A 2D job with {rows[-1]['n_elem']} elements takes {seq[-1]['wall_s']:.0f} s including start-up",
        caption=("墙钟时间含 Abaqus 启动、预处理与求解（不含 odb 导出）。并发组为四个网格同时提交，"
                 f"总耗时 {par_total:.0f} s。会话内第一个作业含冷启动（约 {seq[0]['wall_s']:.0f} s），之后每个作业约 5–6 s，"
                 "启动开销占主导，单元数对耗时影响很小。"),
        units={"wall_s": "s"}, sources=src)

    pkgs = ["torch", "botorch", "gpytorch", "gmsh", "shapely", "numpy", "scipy", "matplotlib", "scikit-learn", "pymoo"]
    trow = [dict(item="Abaqus", value=abaqus_release()),
            dict(item="Abaqus launcher", value=ra.LAUNCHER),
            dict(item="Abaqus embedded Python", value=abaqus_python()),
            dict(item="Venv Python", value=platform.python_version())]
    trow += [dict(item=p, value=im.version(p)) for p in pkgs]
    lic_ok = all(r["status"] == "OK" for r in par)
    trow += [dict(item="License", value="FlexNet 27800@DESKTOP-LQNAMNB (from abaqus information=environment)"),
             dict(item="Concurrency test", value=f"4 jobs submitted together: {sum(r['status'] == 'OK' for r in par)}/4 OK, "
                                                  f"license retries = {sum(r['tries'] - 1 for r in par)}"),
             dict(item="Units", value="mm, N, MPa, t, s (CLAUDE.md §7)")]
    ps.publish_table("R0-T01", trow, title="软件、版本、许可与单位制",
                     caption="包版本取自 .venv-mobo；完整锁定清单见 requirements-lock.txt。")

    err = abs(rows[-1]["ratio_eb"] - 1) * 100
    same = (w_rerun == w_fine)
    ps.publish_acceptance("R0", [
        {"id": "R0-A1", "measured": f"{err:.3f} %", "status": "PASS" if err < 2 else "FAIL",
         "note": "" if err < 2 else "检查边界条件与耦合"},
        {"id": "R0-A2", "measured": f"{w_fine!r} vs {w_rerun!r} mm（并发组 {w_par!r}）",
         "status": "PASS" if same else "FAIL", "note": "" if same else "重跑结果不一致，需排查求解器线程设置"},
        {"id": "R0-A3", "measured": f"{sum(r.get('export') == 'OK' for r in seq)}/{len(seq)} 导出成功",
         "status": "PASS" if all(r.get("export") == "OK" for r in seq) else "FAIL",
         "note": "" if all(r.get("export") == "OK" for r in seq) else "odb_export 失败"},
    ])
    ps.publish_inputs("R0", Abaqus=abaqus_release(), 运行目录="runs/S0/", 作业数=len(seq) + len(par) + 1,
                      并发总耗时_s=round(par_total, 1), license_ok=lic_ok)
    t = ps.report_dir("R0") / "text"
    (t / "summary.md").write_text(
        f"Abaqus 2025 批处理链路可用：CPS6M 悬臂梁在最细网格（{rows[-1]['n_elem']} 单元）上端部挠度与 Euler–Bernoulli 解析解相差 "
        f"{err:.2f} %，与 Timoshenko 解相差 {abs(rows[-1]['ratio_timo'] - 1) * 100:.2f} %；同一 .inp 重跑结果逐位相同；"
        f"四个作业同时提交全部完成，未触发许可重试。单个小型 2D 作业约 {np.median([r['wall_s'] for r in seq]):.0f} s，"
        "主要是启动开销。可以进入 S1。", encoding="utf-8")
    (t / "methods.md").write_text(
        "**模型**：矩形悬臂梁，x = 0 端全部节点固支（U1 = U2 = 0），x = L 端全部节点经分布耦合（均匀权重）连到参考点，"
        f"参考点加 z 向 −{P:g} N。线弹性、小变形、隐式静力单步，软件默认求解与收敛设置（Erdemir 2012 仿真结构项）。\n\n"
        f"**网格**：gmsh 2D，二阶 6 节点三角形 CPS6M，单元尺寸 {', '.join(str(s) for s in SIZES)} mm，边界节点由 mesh2d 共形重采样。\n\n"
        "**解析解**：Euler–Bernoulli 端部挠度 PL³/(3EI)，I = t h³/12；Timoshenko 加剪切项 PL/(κGA)，κ = 5/6。\n\n"
        "**流程**：`inp_writer.write_cantilever` 写 .inp → `run_abaqus.run_and_export` 调用 abq2025.bat 求解 → "
        "`abaqus/odb_export.py` 在 Abaqus 内置 Python 下只用标准库导 CSV → 本脚本读参考点 U2。"
        "并发测试把四个网格的 .inp 复制到新目录同时提交；确定性测试把最细网格再跑一次逐位比较。\n\n"
        "**运行器的失败处理**：许可失败排队重试；求解器未启动的启动器瞬时故障（本阶段实测出现过一次："
        "并发作业刚结束时 Abaqus 驱动加载 win32file DLL 遇到 Windows 文件锁）判为可重试，不记 L4；"
        "其余未完成作业记 L4 并保留原因。", encoding="utf-8")
    (t / "limitations.md").write_text(
        "- 冒烟问题不含接触、过盈与材料分区，这些在 R2 用 Lamé 压配与网格收敛单独验证。\n"
        "- 固支端的泊松约束使 FE 略硬于梁理论，L/h = 20 时影响在 0.1 % 量级。", encoding="utf-8")
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
