"""Second-model review packet: everything a reviewer needs to check one batch before approval, in one markdown file.
The reviewer is another model (not the one that wrote the batch); its findings go to experiments/<batch>/review.md from the template.

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/review_packet.py b25 [--out experiments/b25_opt1/_packet/packet.md]

Contents: proposal.md; gates.py; the build_<batch> function and every module-level constant of v2/stage_db.py that it names;
rows.json (first lines); the checklist. The packet is generated, kept out of git (experiments/*/_packet/); review.md records its sha256.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKLIST = """## 审查清单（逐条回答，写进 review.md）

1. 常量来源：每个写死的数（坐标、轴向量、阈值、行数、槽时）在哪里核过？有没有在别处定义为不同的值？
2. 轴和坐标系：用到的轴向量是 `ops/facts.json` 里的那个吗？单位和方向写明了吗？
3. 判据方向：每条 G 的"通过"是数值小还是大？阈值和第三版计划第 7 节一致吗？
4. 行的物理：每行相对基线改了哪些键？是不是只改了提议里说的那几个？
5. 对照行：对照是哪一行，它 DONE 了吗，条件和本批相同吗？
6. 数据可用性：judge 需要的列都在 scalars.csv 里吗？要 fields 的话 fields 里有吗？
7. 失败模式：哪一行最可能不收敛或模板化失败？build 会怎么报？
8. 成本：行数 × 单价和 approval 的上限一致吗？
9. 没写的假设：提议没写但代码里有的假设。
"""


def builder_source(batch: str) -> str:
    src = (ROOT / "v2" / "stage_db.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == f"build_{batch}"), None)
    if fn is None:
        return f"(no build_{batch} in v2/stage_db.py: the rows come from experiments/{batch}_*/batch.py)"
    body = "\n".join(lines[fn.lineno - 1:fn.end_lineno])
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    consts = []
    for n in tree.body:
        if isinstance(n, ast.Assign):
            tg = [t.id for t in n.targets if isinstance(t, ast.Name)]
            if any(t in names and t.isupper() for t in tg):
                consts.append("\n".join(lines[n.lineno - 1:n.end_lineno]))
    return "### 用到的模块常量\n```python\n" + "\n".join(consts) + "\n```\n\n### build 函数\n```python\n" + body + "\n```"


def build(batch: str) -> tuple[str, pathlib.Path]:
    d = sorted(p for p in (ROOT / "experiments").glob(f"{batch}_*") if p.is_dir())
    if len(d) != 1:
        raise SystemExit(f"experiments/{batch}_* missing or ambiguous")
    d = d[0]
    parts = [f"# 审查包：{d.name}\n", "生成自仓库 HEAD 的工作区；审查者是另一个模型，只读本文件，不读其他代码。\n"]
    for f in ("proposal.md", "approval.md"):
        if (d / f).exists():
            parts.append(f"## {f}\n\n" + (d / f).read_text(encoding="utf-8", errors="replace") + "\n")
    parts.append("## gates.py\n\n```python\n" + (d / "gates.py").read_text(encoding="utf-8", errors="replace") + "\n```\n")
    parts.append(f"## v2/stage_db.py 里的 build_{batch}\n\n" + builder_source(batch) + "\n")
    if (d / "rows.json").exists():
        rows = json.loads((d / "rows.json").read_text(encoding="utf-8"))
        parts.append("## rows.json\n\n```json\n" + json.dumps(rows, ensure_ascii=False, indent=1)[:4000] + "\n```\n")
    facts = ROOT / "ops" / "facts.json"
    if facts.exists():
        parts.append("## ops/facts.json\n\n```json\n" + facts.read_text(encoding="utf-8") + "\n```\n")
    parts.append(CHECKLIST)
    return "\n".join(parts), d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    text, d = build(a.batch)
    out = pathlib.Path(a.out) if a.out else d / "_packet" / "packet.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    print(f"{out} ({len(text)} chars) sha256 {sha[:16]}; write the findings to {d / 'review.md'} from experiments/_template/review.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
