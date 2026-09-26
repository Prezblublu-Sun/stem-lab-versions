"""Abaqus .inp 文本生成（上级 CLAUDE.md §5.1：文本模板为主路径，不用 CAE Python API）。

扁平格式（无 *PART/*ASSEMBLY）：Abaqus 自动建实例 PART-1-1，节点与单元号保持不变，
odb_export 导出的编号可直接对回本网格。单位 mm / N / MPa。

双模型规则（CLAUDE.md §5.2，不可违反）：
* `_bond`：*TIE 必须 ADJUST=NO；单步加载。
* `_fric`：摩擦接触；压配（*CONTACT INTERFERENCE, SHRINK）与外载分两个分析步。
* 骨为从面、柄为主面；间隙区表面不加任何约束。
"""
from __future__ import annotations

import pathlib
from typing import Iterable, Sequence

import numpy as np


def _chunks(seq: Sequence, n: int = 16):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _f(x: float) -> str:
    return f"{float(x):.9g}"


class Inp:
    def __init__(self, heading: str):
        self.lines: list[str] = ["*HEADING", heading, "** units: mm, N, MPa, t, s"]

    def raw(self, text: str) -> None:
        self.lines += text.strip("\n").splitlines()

    def comment(self, text: str) -> None:
        self.lines.append(f"** {text}")

    def nodes(self, labels: Iterable[int], xy: np.ndarray, nset: str | None = None) -> None:
        self.lines.append("*NODE" + (f", NSET={nset}" if nset else ""))
        self.lines += [f"{int(l)}, {_f(p[0])}, {_f(p[1])}" for l, p in zip(labels, xy)]

    def elements(self, etype: str, elset: str, labels: Iterable[int], conn: np.ndarray) -> None:
        self.lines.append(f"*ELEMENT, TYPE={etype}, ELSET={elset}")
        self.lines += [f"{int(l)}, " + ", ".join(str(int(n)) for n in c) for l, c in zip(labels, conn)]

    def nset(self, name: str, labels: Iterable[int]) -> None:
        labs = sorted({int(x) for x in labels})
        if not labs:
            raise ValueError(f"节点集 {name} 为空")
        self.lines.append(f"*NSET, NSET={name}")
        self.lines += [", ".join(map(str, c)) for c in _chunks(labs)]

    def elset(self, name: str, labels: Iterable, generate_from: Sequence[str] | None = None) -> None:
        self.lines.append(f"*ELSET, ELSET={name}")
        if generate_from:
            self.lines.append(", ".join(generate_from))
            return
        labs = sorted({int(x) for x in labels})
        if not labs:
            raise ValueError(f"单元集 {name} 为空")
        self.lines += [", ".join(map(str, c)) for c in _chunks(labs)]

    def element_surface(self, name: str, faces: Iterable[tuple[int, int]]) -> None:
        """faces: (单元号, 面号 1–3)。按面号分组建单元集。"""
        by_face: dict[int, list[int]] = {}
        for el, fc in faces:
            by_face.setdefault(int(fc), []).append(int(el))
        if not by_face:
            raise ValueError(f"面 {name} 为空")
        for fc, els in sorted(by_face.items()):
            self.elset(f"{name}_S{fc}", els)
        self.lines.append(f"*SURFACE, TYPE=ELEMENT, NAME={name}")
        self.lines += [f"{name}_S{fc}, S{fc}" for fc in sorted(by_face)]

    def node_surface(self, name: str, nset: str) -> None:
        self.lines += [f"*SURFACE, TYPE=NODE, NAME={name}", f"{nset}, 1."]

    def material(self, name: str, E: float, nu: float) -> None:
        self.lines += [f"*MATERIAL, NAME={name}", "*ELASTIC", f"{_f(E)}, {_f(nu)}"]

    def solid_section(self, elset: str, material: str, thickness: float) -> None:
        self.lines += [f"*SOLID SECTION, ELSET={elset}, MATERIAL={material}", f"{_f(thickness)},"]

    def ref_node(self, label: int, xy: Sequence[float], nset: str) -> None:
        self.nodes([label], np.asarray([xy]), nset=nset)

    def distributing_coupling(self, name: str, ref_nset: str, surface: str) -> None:
        self.lines += [f"*COUPLING, CONSTRAINT NAME={name}, REF NODE={ref_nset}, SURFACE={surface}",
                       "*DISTRIBUTING, WEIGHTING METHOD=UNIFORM", "1, 2"]

    def write(self, path: pathlib.Path) -> pathlib.Path:
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines) + "\n", encoding="ascii")
        return path


FIELD_OUTPUT = """*OUTPUT, FIELD
*NODE OUTPUT
U, RF
*ELEMENT OUTPUT
S, ELSE, EVOL"""

CONTACT_OUTPUT = """*CONTACT OUTPUT
CSTRESS, CDISP, CSTATUS"""


# --------------------------------------------------------------------------- cantilever（S0）
def write_cantilever(mesh, path: pathlib.Path, *, L: float, h: float, E: float, nu: float,
                     thickness: float, P: float) -> pathlib.Path:
    """悬臂梁：x=0 端全固支，x=L 端经分布耦合在参考点加 -P（z 向）。"""
    inp = Inp(f"mobo_toy S0 cantilever L={L} h={h} n_elem={mesh.n_elems}")
    inp.nodes(mesh.node_labels, mesh.nodes)
    for r in mesh.elems:
        inp.elements("CPS6M", r.upper(), mesh.elem_labels[r], mesh.elems[r])
    x = mesh.nodes[:, 0]
    inp.nset("CLAMP", mesh.node_labels[np.isclose(x, 0.0, atol=1e-6)])
    inp.nset("TIP", mesh.node_labels[np.isclose(x, L, atol=1e-6)])
    rp = int(mesh.node_labels.max()) + 1
    inp.ref_node(rp, (L, 0.0), "RP")
    inp.node_surface("S_TIP", "TIP")
    inp.distributing_coupling("TIPCPL", "RP", "S_TIP")
    inp.material("TI", E, nu)
    for r in mesh.elems:
        inp.solid_section(r.upper(), "TI", thickness)
    inp.raw(f"""
*STEP, NAME=LOAD
*STATIC
1., 1., 1e-05, 1.
*BOUNDARY
CLAMP, 1, 2
*CLOAD
RP, 2, {_f(-P)}
{FIELD_OUTPUT}
*END STEP""")
    return inp.write(path)
