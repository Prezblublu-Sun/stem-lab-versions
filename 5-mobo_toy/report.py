#!/usr/bin/env python3
"""mobo_toy 阶段报告生成器（REPORTING_SPEC.md 第 2、5 节的代码实现）。

用法
----
  python report.py --report R2            # 或 --stage S2；生成 Markdown + HTML + PDF
  python report.py --check R2             # 只查缺项；齐全返回 0，不齐返回 2
  python report.py --replot R2-F03        # 只凭 CSV 重画一张图（写 *_replot.png/svg）
  python report.py --render-spec          # 把 spec.yaml 的报告清单渲染进 REPORTING_SPEC.md
  python report.py --demo                 # 用合成数据演示整条流水线（reports/_demo_pipeline）

报告结构固定六节：0 结论摘要 · 1 使用情境与问题 · 2 输入与版本 · 3 方法 · 4 结果 · 5 验收 ·
6 局限与下一阶段输入，另附溯源附录与缺项附录。
每份报告的必备图、表、验收项由 reports/spec.yaml 规定；缺项不阻止生成，但报告首页标"草稿"，
退出码为 2。PDF 流程改自 femstem-2607 final/scripts/build_report_pdf.py（headless Chrome）。
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html as _html
import importlib.metadata as im
import json
import pathlib
import platform
import re
import shutil
import subprocess
import sys

import markdown

import plotstyle as ps

ROOT = ps.ROOT
SPEC_DOC = ROOT / "REPORTING_SPEC.md"
MDX = ["tables", "fenced_code", "sane_lists", "attr_list"]
ANCHOR = re.compile(r'(?:<p>\s*)?\[\[FIG:([A-Z0-9]+-F\d+)\]\](?:\s*</p>)?')
PKGS = ["numpy", "scipy", "matplotlib", "shapely", "PyYAML", "markdown", "torch", "botorch",
        "gpytorch", "gmsh", "meshio", "scikit-learn", "pymoo"]
CHROME = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
          r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
          r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]

CSS = """
@page { size: A4; margin: 16mm 15mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI","Microsoft YaHei",Arial,sans-serif; font-size: 10pt; line-height: 1.5; color:#111; }
h1 { font-size: 18pt; border-bottom: 3px solid #333; padding-bottom:5px; margin-bottom:4px; }
h2 { font-size: 13pt; margin-top: 1.2em; border-bottom:1px solid #bbb; padding-bottom:2px; page-break-after: avoid; }
h3 { font-size: 11pt; margin-top: 0.9em; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 8.5pt; margin: 0.5em 0; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th,td { border: 1px solid #999; padding: 4px 6px; text-align: left; vertical-align: top; }
th { background:#f0f0f0; }
td:first-child { white-space: nowrap; }
code,pre { font-family: Consolas,monospace; font-size: 8.5pt; background:#f6f6f6; }
.meta { color:#444; font-size:9pt; margin: 2px 0 10px 0; }
.banner { padding:6px 10px; margin:6px 0; border-radius:4px; font-weight:600; }
.banner.syn { background:#FDE8DC; border:1px solid #D55E00; color:#8a3200; }
.banner.draft { background:#FFF4CC; border:1px solid #E69F00; color:#6b4a00; }
figure { margin: 0.8em 0; page-break-inside: avoid; border:1px solid #ccc; background:#fafafa; padding:8px; border-radius:4px; }
figure img { max-width: 100%; display:block; margin: 0 auto; background:#fff; }
figcaption { font-size: 8.8pt; color:#222; margin-top:6px; }
figcaption .cap { font-weight:600; }
figcaption .src { color:#666; font-size: 7.8pt; }
td.PASS { background:#DDF2EA; color:#00553d; font-weight:600; }
td.FAIL { background:#FBE0D3; color:#8a3200; font-weight:600; }
td.PENDING { background:#EEEEEE; color:#555; font-weight:600; }
td.NA { background:#E8F1F8; color:#0b4a78; font-weight:600; }
.verdict { font-weight:700; padding:1px 6px; border-radius:3px; }
.verdict.PASS { background:#DDF2EA; color:#00553d; } .verdict.FAIL { background:#FBE0D3; color:#8a3200; }
.verdict.INCOMPLETE { background:#FFF4CC; color:#6b4a00; }
.verdict.FAIL-APPROVED { background:#E8F1F8; color:#0b4a78; }
"""


# ---------------------------------------------------------------- helpers
def _load_json(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _short(h: str | None) -> str:
    return h[:8] if h else "—"


def _pkg_versions() -> list[tuple[str, str]]:
    out = [("Python", platform.python_version())]
    for p in PKGS:
        try:
            out.append((p, im.version(p)))
        except im.PackageNotFoundError:
            out.append((p, "未安装"))
    return out


def _md_escape(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _csv_to_md(csv_path: pathlib.Path, max_rows: int = 60) -> str:
    cols = ps.read_csv(csv_path)
    names = list(cols)
    n = len(cols[names[0]]) if names else 0
    lines = ["| " + " | ".join(_md_escape(c) for c in names) + " |",
             "|" + "|".join("---" for _ in names) + "|"]
    for i in range(min(n, max_rows)):
        lines.append("| " + " | ".join(_md_escape(ps.sig(cols[c][i])) for c in names) + " |")
    if n > max_rows:
        lines.append(f"\n*仅显示前 {max_rows} 行，共 {n} 行；全表见 `{ps.rel(csv_path)}`。*")
    return "\n".join(lines)


def _read_text(p: pathlib.Path) -> str | None:
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def resolve_report_id(arg: str, spec: dict) -> str:
    if arg in spec["reports"]:
        return arg
    for rid, rep in spec["reports"].items():
        if str(rep.get("stage")) == arg:
            return rid
    raise SystemExit(f"未知报告或阶段：{arg}（见 reports/spec.yaml）")


# ---------------------------------------------------------------- completeness
def collect(rid: str, spec: dict) -> dict:
    rep = spec["reports"][rid]
    d = ps.report_dir(rid)
    figs = {p.stem: _load_json(p) for p in sorted((d / "figures").glob("*.json"))}
    tabs = {p.stem: _load_json(p) for p in sorted((d / "tables").glob("*.json"))}
    acc = _load_json(d / "acceptance.json") or {"items": []}
    acc_by = {a["id"]: a for a in acc["items"]}
    missing = []
    for f in rep.get("figures", []):
        if f["id"] not in figs:
            missing.append(("图", f["id"], f["what"]))
    for t in rep.get("tables", []):
        if t["id"] not in tabs:
            missing.append(("表", t["id"], t["what"]))
    for a in rep.get("acceptance", []):
        if a["id"] not in acc_by:
            missing.append(("验收", a["id"], a["criterion"]))
    for name, label in (("summary.md", "结论摘要 text/summary.md"), ("methods.md", "方法 text/methods.md")):
        if not (d / "text" / name).exists():
            missing.append(("文字", name, label))
    # 数据完整性：CSV 哈希必须与 meta 一致
    tampered = [m["id"] for m in list(figs.values()) + list(tabs.values())
                if ps.sha256_file(ROOT / m["csv"]) != m["csv_sha256"]]
    synthetic = any(m.get("synthetic") for m in list(figs.values()) + list(tabs.values())) or acc.get("synthetic")
    return {"rep": rep, "dir": d, "figs": figs, "tabs": tabs, "acc": acc_by, "missing": missing,
            "tampered": tampered, "synthetic": bool(synthetic)}


def verdict(c: dict) -> str:
    items = [c["acc"].get(a["id"], {"status": "PENDING"}) for a in c["rep"].get("acceptance", [])]
    if c["missing"] or c["tampered"] or any(i["status"] == "PENDING" for i in items):
        return "INCOMPLETE"
    fails = [i for i in items if i["status"] == "FAIL"]
    if any(not i.get("approved") for i in fails):
        return "FAIL"
    if fails:
        return "FAIL-APPROVED"                             # 不通过项的处置均已获用户同意，可进入下一阶段
    return "PASS"


# ---------------------------------------------------------------- markdown assembly
def build_markdown(rid: str, spec: dict, c: dict) -> str:
    rep, d = c["rep"], c["dir"]
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    v = verdict(c)
    out = [f"# {rid} {rep['title']}",
           f'<div class="meta">阶段 {rep["stage"]} · 生成 {now} · 规范 reports/spec.yaml '
           f'(sha {_short(ps.sha256_file(ps.SPEC_PATH))}) · 总判定 '
           f'<span class="verdict {v}">{v}</span></div>']
    if c["synthetic"]:
        out.append('<div class="banner syn">本报告含合成数据（synthetic=True），只用于演示流水线，不构成任何结果。</div>')
    if c["missing"] or c["tampered"]:
        out.append(f'<div class="banner draft">草稿：缺 {len(c["missing"])} 项'
                   + (f'，{len(c["tampered"])} 个数据文件哈希不符' if c["tampered"] else "")
                   + '，见文末"缺项"附录。</div>')

    out += ["## 0 结论摘要", _read_text(d / "text" / "summary.md") or "*（缺：text/summary.md）*"]

    out += ["## 1 使用情境与问题",
            "| 项 | 内容 |", "|---|---|",
            f"| 使用情境（COU） | {_md_escape(rep['cou'])} |",
            f"| 本阶段要回答 | {_md_escape(rep['question'])} |",
            f"| 本阶段不回答 | {_md_escape(rep['not_answered'])} |",
            f"| 依据规范 | {_md_escape('；'.join(rep.get('standards', [])))} |"]

    out += ["## 2 输入与版本", "| 项 | 值 |", "|---|---|",
            f"| config.yaml | sha {_short(ps.sha256_file(ps.CONFIG_PATH))} |",
            f"| spec.yaml | sha {_short(ps.sha256_file(ps.SPEC_PATH))} |"]
    inputs = _load_json(d / "inputs.json") or {}
    for k, val in inputs.items():
        out.append(f"| {_md_escape(k)} | {_md_escape(val)} |")
    scripts = {}
    for m in list(c["figs"].values()) + list(c["tabs"].values()):
        scripts[m["producer"]] = m.get("producer_sha256")
        if m.get("plot_fn"):
            mp = m["plot_fn"].split(":")[0]
            scripts[mp] = m.get("plot_module_sha256")
    for s, h in sorted(scripts.items()):
        out.append(f"| 脚本 `{_md_escape(s)}` | sha {_short(h)} |")
    out.append("| 软件包 | " + "；".join(f"{n} {ver}" for n, ver in _pkg_versions()) + " |")

    out += ["## 3 方法", _read_text(d / "text" / "methods.md") or "*（缺：text/methods.md）*"]

    out += ["## 4 结果", "### 4.1 图"]
    order = [f["id"] for f in rep.get("figures", [])]
    extra = [k for k in c["figs"] if k not in order]
    for fid in order + extra:
        out.append(f"[[FIG:{fid}]]" if fid in c["figs"] else f"*（缺图 {fid}）*")
    out.append("### 4.2 表")
    torder = [t["id"] for t in rep.get("tables", [])]
    textra = [k for k in c["tabs"] if k not in torder]
    for k, tid in enumerate(torder + textra, 1):
        m = c["tabs"].get(tid)
        if not m:
            out.append(f"*（缺表 {tid}）*")
            continue
        syn = "（合成数据）" if m.get("synthetic") else ""
        out.append(f"**表 {k}（{tid}）{_md_escape(m['title'])}**{syn}")
        out.append(_csv_to_md(ROOT / m["csv"]))
        units = "；".join(f"{a}: {b}" for a, b in m.get("units", {}).items())
        out.append(f"<span class='src'>{_md_escape(m.get('caption', ''))} "
                   + (f"单位 {units}。" if units else "")
                   + f" 数据 `{m['csv']}`（sha {_short(m['csv_sha256'])}），"
                   f"生成脚本 `{m['producer']}`。</span>")

    out += ["## 5 验收", "| ID | 判据 | 门槛 | 实测 | 状态 | 原因与处置 |", "|---|---|---|---|---|---|"]
    for a in rep.get("acceptance", []):
        r = c["acc"].get(a["id"], {"measured": "", "status": "PENDING", "note": "尚未提交结果"})
        st = r["status"] + (f"（处置已获同意 {r['approved']}）" if r.get("approved") else "")
        out.append(f"| {a['id']} | {_md_escape(a['criterion'])} | {_md_escape(a['threshold'])} | "
                   f"{_md_escape(r.get('measured', ''))} | {st} | {_md_escape(r.get('note', ''))} |")
    out.append(f"\n总判定：<span class=\"verdict {v}\">{v}</span>（全部 PASS 或写明理由的 NA 才算通过；"
               "不通过项的处置全部获用户同意时为 FAIL-APPROVED，可进入下一阶段；有 PENDING 或缺项为 INCOMPLETE）。")

    out += ["## 6 局限与下一阶段输入", "**通用局限**"]
    out += [f"- {x}" for x in spec.get("common_limitations", [])]
    lim = _read_text(d / "text" / "limitations.md")
    if lim:
        out += ["**本阶段局限**", lim]
    out += ["**下一阶段输入**"] + [f"- {x}" for x in rep.get("next_inputs", [])]

    out += ["## 附录 A 溯源", "| 图/表 | 数据 sha | 作图函数 | 生成脚本 sha | 合成 | 来源 |",
            "|---|---|---|---|---|---|"]
    for m in list(c["figs"].values()) + list(c["tabs"].values()):
        src = "；".join(f"{a}={b}" for a, b in m.get("sources", {}).items())
        out.append(f"| {m['id']} | {_short(m['csv_sha256'])} | `{m.get('plot_fn', '—')}` | "
                   f"{_short(m.get('producer_sha256'))} | {'是' if m.get('synthetic') else '否'} | {_md_escape(src)} |")
    if c["missing"] or c["tampered"]:
        out += ["## 附录 B 缺项", "| 类别 | ID | 规范要求 |", "|---|---|---|"]
        out += [f"| {k} | {i} | {_md_escape(w)} |" for k, i, w in c["missing"]]
        out += [f"| 数据被改 | {i} | CSV 哈希与 meta 不符，需重跑生成脚本 |" for i in c["tampered"]]
    text = "\n\n".join(out) + "\n"
    # 表格行之间不能有空行，否则 Markdown 不认表格：把"行尾 | + 空行 + 行首 |"并成相邻行
    return re.sub(r"\|[ \t]*\n\n(?=\|)", "|\n", text)


def _figure_caption(m: dict, n: int) -> tuple[str, str]:
    units = "；".join(f"{a}: {b}" for a, b in m.get("units", {}).items())
    cap = f"图 {n}（{m['id']}）{m['title']}"
    src = (f"数据 {m['csv']}（sha {_short(m['csv_sha256'])}）· 作图 {m['plot_fn']} · "
           f"生成脚本 {m['producer']}（sha {_short(m.get('producer_sha256'))}）"
           + (f" · 单位 {units}" if units else "") + (" · 合成数据" if m.get("synthetic") else ""))
    return cap, src


def md_for_file(md: str, c: dict) -> str:
    """Markdown 版：锚点换成相对路径图片 + 图注（可在任何 md 阅读器里看）。"""
    n = {"k": 0}

    def rep(mo):
        m = c["figs"][mo.group(1)]
        n["k"] += 1
        cap, src = _figure_caption(m, n["k"])
        return (f"![{m['id']}](figures/{m['id']}.png)\n\n**{cap}**　{m['caption']}\n\n"
                f"<span class='src'>{src}</span>")
    return re.sub(r"\[\[FIG:([A-Z0-9]+-F\d+)\]\]", rep, md)


def html_for_pdf(md: str, c: dict, title: str) -> str:
    body = markdown.markdown(md, extensions=MDX)
    n = {"k": 0}

    def rep(mo):
        m = c["figs"][mo.group(1)]
        n["k"] += 1
        cap, src = _figure_caption(m, n["k"])
        png = ROOT / m["png"]
        raw = png.read_bytes()
        width_in = int.from_bytes(raw[16:20], "big") / ps.DPI      # 按印刷尺寸显示，不拉伸
        uri = "data:image/png;base64," + base64.b64encode(raw).decode()
        return (f'<figure><img src="{uri}" style="width:{width_in:.2f}in;max-width:100%"/><figcaption><span class="cap">{_html.escape(cap)}</span>　'
                f'{_html.escape(m["caption"])}<br><span class="src">{_html.escape(src)}</span>'
                f'</figcaption></figure>')
    body = ANCHOR.sub(rep, body)
    body = re.sub(r"<td>(PASS|FAIL|PENDING|NA)</td>", r'<td class="\1">\1</td>', body)
    body = re.sub(r"<td>FAIL（处置已获同意([^<]*)）</td>", r'<td class="NA">FAIL（处置已获同意\1）</td>', body)
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_html.escape(title)}</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")


def to_pdf(html_path: pathlib.Path, pdf_path: pathlib.Path) -> bool:
    chrome = next((p for p in CHROME if pathlib.Path(p).exists()), None)
    if not chrome:
        print("[report] 找不到 Chrome/Edge，只生成 HTML：", html_path)
        return False
    if pdf_path.exists():
        pdf_path.unlink()
    subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                    "--virtual-time-budget=15000", f"--print-to-pdf={pdf_path}", html_path.as_uri()],
                   capture_output=True, text=True, timeout=240)
    ok = pdf_path.exists() and pdf_path.stat().st_size > 1000
    print(f"[report] PDF {'OK' if ok else '失败'} -> {pdf_path}")
    return ok


def build(rid: str, pdf: bool = True) -> int:
    spec = ps.load_spec()
    c = collect(rid, spec)
    md = build_markdown(rid, spec, c)
    d = c["dir"]
    base = f"{rid}_report"
    (d / f"{base}.md").write_text(md_for_file(md, c), encoding="utf-8")
    html_path = d / f"{base}.html"
    html_path.write_text(html_for_pdf(md, c, f"{rid} {c['rep']['title']}"), encoding="utf-8")
    if pdf:
        pdf_path = d / f"{base}.pdf"
        if to_pdf(html_path, pdf_path):
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
            shutil.copy2(pdf_path, d / "history" / f"{base}_{stamp}.pdf")
    v = verdict(c)
    print(f"[report] {rid}: 判定 {v}；缺项 {len(c['missing'])}；哈希不符 {len(c['tampered'])}；"
          f"合成数据 {'是' if c['synthetic'] else '否'}")
    for k, i, w in c["missing"]:
        print(f"    缺{k} {i}: {w}")
    return 0 if not (c["missing"] or c["tampered"]) else 2


def check(rid: str) -> int:
    spec = ps.load_spec()
    c = collect(rid, spec)
    for k, i, w in c["missing"]:
        print(f"缺{k} {i}: {w}")
    for i in c["tampered"]:
        print(f"哈希不符 {i}")
    print(f"{rid}: {'齐全' if not (c['missing'] or c['tampered']) else '不齐'}；判定 {verdict(c)}")
    return 0 if not (c["missing"] or c["tampered"]) else 2


# ---------------------------------------------------------------- spec rendering
BEGIN, END = "<!-- BEGIN:REGISTRY (report.py --render-spec 自动生成，勿手改) -->", "<!-- END:REGISTRY -->"


def render_spec() -> int:
    spec = ps.load_spec()
    lines = []
    for rid, rep in spec["reports"].items():
        if rep.get("demo"):
            continue
        lines += [f"### {rid} {rep['title']}（阶段 {rep['stage']}，目录 `reports/{rep['dir']}/`）", "",
                  f"- **使用情境**：{rep['cou']}", f"- **要回答**：{rep['question']}",
                  f"- **不回答**：{rep['not_answered']}", f"- **依据**：{'；'.join(rep.get('standards', []))}", "",
                  "| 图号 | 必备图 | 规范来源 |", "|---|---|---|"]
        lines += [f"| {f['id']} | {_md_escape(f['what'])} | {_md_escape(f.get('std', ''))} |" for f in rep["figures"]]
        lines += ["", "| 表号 | 必备表 |", "|---|---|"]
        lines += [f"| {t['id']} | {_md_escape(t['what'])} |" for t in rep["tables"]]
        lines += ["", "| 验收号 | 判据 | 门槛 |", "|---|---|---|"]
        lines += [f"| {a['id']} | {_md_escape(a['criterion'])} | {_md_escape(a['threshold'])} |" for a in rep["acceptance"]]
        lines += ["", "下一阶段输入：" + "；".join(rep.get("next_inputs", [])), ""]
    block = BEGIN + "\n\n" + "\n".join(lines) + "\n" + END
    doc = SPEC_DOC.read_text(encoding="utf-8")
    if BEGIN not in doc or END not in doc:
        raise SystemExit("REPORTING_SPEC.md 缺少 REGISTRY 标记")
    doc = doc[:doc.index(BEGIN)] + block + doc[doc.index(END) + len(END):]
    SPEC_DOC.write_text(doc, encoding="utf-8")
    # 同时出一份 PDF 便于审阅
    body = markdown.markdown(doc, extensions=MDX)
    html_path = ps.REPORTS / "REPORTING_SPEC.html"
    html_path.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>REPORTING_SPEC</title>"
                         f"<style>{CSS}</style></head><body>{body}</body></html>", encoding="utf-8")
    to_pdf(html_path, ps.REPORTS / "REPORTING_SPEC.pdf")
    n_fig = sum(len(r["figures"]) for k, r in spec["reports"].items() if not r.get("demo"))
    n_tab = sum(len(r["tables"]) for k, r in spec["reports"].items() if not r.get("demo"))
    n_acc = sum(len(r["acceptance"]) for k, r in spec["reports"].items() if not r.get("demo"))
    print(f"[report] 已渲染 {len(spec['reports']) - 1} 份报告：图 {n_fig}、表 {n_tab}、验收 {n_acc}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--report")
    g.add_argument("--stage")
    g.add_argument("--check")
    g.add_argument("--replot")
    g.add_argument("--render-spec", action="store_true")
    g.add_argument("--demo", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args()
    spec = ps.load_spec()
    if a.render_spec:
        return render_spec()
    if a.replot:
        print(ps.replot(a.replot, out_suffix="_replot"))
        return 0
    if a.check:
        return check(resolve_report_id(a.check, spec))
    if a.demo:
        import demo_report
        demo_report.make()
        return build("RD", pdf=not a.no_pdf)
    return build(resolve_report_id(a.report or a.stage, spec), pdf=not a.no_pdf)


if __name__ == "__main__":
    sys.exit(main())
