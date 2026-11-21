"""把 Methods 初稿与十篇参考文献的原文合成一个 PDF（带书签）。

    python v2/build_methods_bundle.py
输入：v2/METHODS_draft.pdf（由 build_doc.py 生成）、v2/refs_pdf/NN_*.pdf（NN = 参考文献序号）。
缺原文的序号：插入一页题录页并注明"原文未取得"。Erdemir 2012 若无 PDF，则由 refs/Erdemir2012_PMC3278509_fulltext.xml
排版成 PDF（作者手稿全文，非原刊版面）。
输出：v2/METHODS_with_references.pdf
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import fitz  # PyMuPDF

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
REFS = HERE / "refs_pdf"
OUT = HERE / "METHODS_with_references.pdf"
CITES = {
    1: "Reimeringer M, Nuño N, Desmarais-Trépanier C, Lavigne M, Vendittoli P-A. The influence of uncemented femoral stem length and design on its primary stability: a finite element analysis. Comput Methods Biomech Biomed Engin 2013;16(11):1221–1231.",
    2: "Abdul-Kadir MR, Hansen U, Klabunde R, Lucas D, Amis A. Finite element modelling of primary hip stem stability: the effect of interference fit. J Biomech 2008;41(3):587–594.",
    3: "Bieger R, Ignatius A, Decking R, Claes L, Reichel H, Dürselen L. Primary stability and strain distribution of cementless hip stems as a function of implant design. Clin Biomech 2012;27(2):158–164.",
    4: "Viceconti M, Muccini R, Bernakiewicz M, Baleani M, Cristofolini L. Large-sliding contact elements accurately predict levels of bone–implant micromotion relevant to osseointegration. J Biomech 2000;33(12):1611–1618.",
    5: "Huiskes R, Weinans H, van Rietbergen B. The relationship between stress shielding and bone resorption around total hip stems and the effects of flexible materials. Clin Orthop Relat Res 1992;274:124–134.",
    6: "Bergmann G, Bender A, Dymke J, Duda G, Damm P. Standardized loads acting in hip implants. PLOS ONE 2016;11(5):e0155612.",
    7: "Cilla M, Borgiani E, Martínez J, Duda GN, Checa S. Machine learning techniques for the optimization of joint replacements: application to a short-stem hip implant. PLOS ONE 2017;12(9):e0183755.",
    8: "Kanaizumi A, Suzuki D, Nagoya S, Teramoto A, Yamashita T. Patient-specific three-dimensional evaluation of interface micromotion in two different short stem designs in cementless total hip arthroplasty: a finite element analysis. J Orthop Surg Res 2022;17:437.",
    9: "Erdemir A, Guess TM, Halloran J, Tadepalli SC, Morrison TM. Considerations for reporting finite element analysis studies in biomechanics. J Biomech 2012;45(4):625–633.",
    10: "Ament S, Daulton S, Eriksson D, Balandat M, Bakshy E. Unexpected improvements to expected improvement for Bayesian optimization. Adv Neural Inf Process Syst 2023;36:20577–20612.",
}


def erdemir_xml_to_pdf(xml_path: pathlib.Path, out_pdf: pathlib.Path) -> bool:
    """PMC JATS 全文 XML → Markdown → PDF（用 build_doc.py 的流程）。"""
    ns_strip = lambda t: t.split("}")[-1]                            # noqa: E731
    root = ET.parse(xml_path).getroot()

    def text_of(el):
        return "".join(el.itertext()).strip()
    lines = []
    art = root.find(".//{*}article") or root
    title = art.find(".//{*}article-title")
    lines.append("# " + (text_of(title) if title is not None else "Erdemir et al. 2012"))
    lines.append("*PMC3278509 author manuscript, rendered from the full-text XML (not the journal layout).*\n")
    abst = art.find(".//{*}abstract")
    if abst is not None:
        lines.append("## Abstract\n")
        for p in abst.iter():
            if ns_strip(p.tag) == "p":
                lines.append(text_of(p) + "\n")
    body = art.find(".//{*}body")

    def walk(sec, level):
        for ch in list(sec):
            tag = ns_strip(ch.tag)
            if tag == "title":
                lines.append("#" * min(level, 4) + " " + text_of(ch) + "\n")
            elif tag == "p":
                lines.append(text_of(ch) + "\n")
            elif tag == "sec":
                walk(ch, level + 1)
            elif tag == "table-wrap":
                cap = ch.find(".//{*}caption")
                lines.append("**Table.** " + (text_of(cap) if cap is not None else "") + "\n")
                for tr in ch.iter():
                    if ns_strip(tr.tag) == "tr":
                        cells = [text_of(c) for c in tr if ns_strip(c.tag) in ("td", "th")]
                        if cells:
                            lines.append("| " + " | ".join(cells) + " |")
                lines.append("")
            elif tag == "list":
                for li in ch.iter():
                    if ns_strip(li.tag) == "list-item":
                        lines.append("- " + text_of(li))
                lines.append("")
    if body is not None:
        walk(body, 2)
    md = HERE / "_erdemir2012_fulltext.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    r = subprocess.run([sys.executable, str(HERE / "build_doc.py"), str(md)], capture_output=True, text=True)
    pdf = md.with_suffix(".pdf")
    ok = pdf.exists()
    if ok:
        pdf.replace(out_pdf)
    md.unlink(missing_ok=True); md.with_suffix(".html").unlink(missing_ok=True)
    return ok


def cover(doc: fitz.Document, n: int, cite: str, note: str, pages: int | None):
    page = doc.new_page(width=595, height=842)
    y = 110
    page.insert_text((60, y), f"Reference {n}", fontsize=20, fontname="helv")
    y += 40
    for line in _wrap(cite, 88):
        page.insert_text((60, y), line, fontsize=11, fontname="helv"); y += 16
    y += 20
    for line in _wrap(note, 88):
        page.insert_text((60, y), line, fontsize=10, fontname="helv", color=(0.35, 0.35, 0.35)); y += 14
    if pages:
        page.insert_text((60, y + 10), f"{pages} pages follow.", fontsize=10, fontname="helv", color=(0.35, 0.35, 0.35))


def _wrap(s, width):
    out, cur = [], ""
    for w in s.split():
        if len(cur) + len(w) + 1 > width:
            out.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out


def main():
    out = fitz.open()
    toc = []
    meth = fitz.open(HERE / "METHODS_draft.pdf")
    out.insert_pdf(meth)
    toc.append([1, "Methods (draft) + reference list", 1])
    missing = []
    for n in range(1, 11):
        files = sorted(REFS.glob(f"{n:02d}_*.pdf"))
        if not files and n == 9 and (ROOT / "refs" / "Erdemir2012_PMC3278509_fulltext.xml").exists():
            target = REFS / "09_Erdemir_2012_PMC_manuscript.pdf"
            if erdemir_xml_to_pdf(ROOT / "refs" / "Erdemir2012_PMC3278509_fulltext.xml", target):
                files = [target]
        start = out.page_count + 1
        if files:
            src = fitz.open(files[0])
            note = f"Source file: {files[0].name}" + ("  (PMC author-manuscript full text rendered from XML, not the journal layout)" if "PMC_manuscript" in files[0].name else "")
            cover(out, n, CITES[n], note, src.page_count)
            out.insert_pdf(src)
            toc.append([1, f"[{n}] {CITES[n][:70]}…", start])
        else:
            cover(out, n, CITES[n], "Full text not available locally at the time of this build (paywalled or not yet obtained).", None)
            toc.append([1, f"[{n}] {CITES[n][:70]}… (citation only)", start])
            missing.append(n)
    out.set_toc(toc)
    out.save(OUT, garbage=3, deflate=True)
    print(f"written {OUT} ({out.page_count} pages, {OUT.stat().st_size / 1e6:.1f} MB); missing full text: {missing}")


if __name__ == "__main__":
    main()
