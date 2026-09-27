"""把 v2 的 Markdown 文档转成 PDF（图片内嵌，样式与 report.py 相同）。用法：python v2/build_doc.py v2/TEST_DESIGN.md"""
from __future__ import annotations

import base64
import html as _html
import pathlib
import re
import sys

import markdown

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import report  # noqa: E402

IMG = re.compile(r'<p><img alt="([^"]*)" src="([^"]+)" ?/?></p>')


def main(md_path: str) -> int:
    src = pathlib.Path(md_path).resolve()
    body = markdown.markdown(src.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "sane_lists"])
    n = {"k": 0}

    def rep(mo):
        n["k"] += 1
        png = (src.parent / mo.group(2)).resolve()
        raw = png.read_bytes()
        uri = "data:image/png;base64," + base64.b64encode(raw).decode()
        return (f'<figure><img src="{uri}" style="width:100%"/><figcaption><span class="cap">图 {n["k"]}</span>　'
                f'{_html.escape(mo.group(1))}<br><span class="src">{_html.escape(str(png.relative_to(HERE.parent)))}</span>'
                f'</figcaption></figure>')
    body = IMG.sub(rep, body)
    title = src.stem
    page = (f"<!doctype html><html><head><meta charset='utf-8'><title>{_html.escape(title)}</title>"
            f"<style>{report.CSS}</style></head><body>{body}</body></html>")
    html_path = src.with_suffix(".html")
    html_path.write_text(page, encoding="utf-8")
    ok = report.to_pdf(html_path, src.with_suffix(".pdf"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
