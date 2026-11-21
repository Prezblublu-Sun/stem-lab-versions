"""批次 E 汇总（Linux）：领的新规则 wrap_fit 与现行规则的对比 → ~/mobo_toy_v2/deck/E_rule/compare.json，并导出新规则下的柄 / 皮质 STL
（渲染用）。现行规则的对照：FI、R1、J1、R2、B2、LA 用批次 B 的 demo 作业（领共节点 + 接触），P2、T2 用原优化作业（只有共节点）。"""
from __future__ import annotations

import json
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2")); sys.path.insert(0, str(HOME / "adhoc"))
import numpy as np  # noqa: E402

import deck_B_export as BX  # noqa: E402
import deck_master as D  # noqa: E402
import jobs as J  # noqa: E402

KEYS = ("A0_shoulder_mm2", "entry_offset_e", "collar_w", "f1_p95_um", "f1_all_p95_um", "f1_all_closed_p95_um", "area_frac_gt40",
        "collar_force_share_load2", "collar_open_frac_load2", "collar_closed_frac_load2", "sed_chg_pct", "band_res06_pct", "vm_p99",
        "resected_mm3", "reamed_mm3", "bone_removed_mm3")


def metrics(full: str, contact: str | None) -> dict:
    r = D.row_of(full)
    out = {k: r.get(k) for k in KEYS}
    prep = json.loads((J.QROOT / full / "prep.json").read_text())
    c = prep.get("collar") or {}
    out.update(collar_area_mm2=c.get("area_mm2"), collar_ring_mm2=c.get("ring_mm2"), collar_ring_cortex_frac=c.get("ring_cortex_frac"), job=full)
    if contact and J.state(J.QROOT / contact) == "DONE":
        rc = D.row_of(contact)
        out.update(sed_chg_pct_contact=rc.get("sed_chg_pct"), band_res06_pct_contact=rc.get("band_res06_pct"))
    return out


def export_surfaces(code: str, j: str):
    d = J.QROOT / j
    m = dict(np.load(d / "mesh3d.npz"))
    lab, X = m["node_labels"], m["nodes"]
    lut = np.full(int(lab.max()) + 1, -1); lut[lab] = np.arange(len(lab))
    out = HOME / "deck" / "E_rule" / code
    out.mkdir(parents=True, exist_ok=True)
    for name, conn in (("stem", m["stem_conn_bond"]), ("femur_cut_cortex", m["cortex_conn"])):
        P, T, _ = BX.compact(X, lut, BX.boundary_tris(conn[:, :4]))
        BX.write_stl(out / f"{name}.stl", P, T, f"{code} {name} (collar rule wrap_fit)")


def main():
    E = json.loads((J.RESULTS / "deck_E_ids.json").read_text())["jobs"]
    B = json.loads((J.RESULTS / "deck_B_ids.json").read_text())["jobs"]
    orig = {"P2": "neck3_a48_f9ed1d41", "T2": "neck1_init_3d14a026"}
    rep = {}
    for code in ("FI", "R1", "J1", "R2", "B2", "LA", "P2", "T2"):
        old = metrics(B[code], B.get(f"{code}_contact")) if code in B else metrics(orig[code], None)
        new = metrics(E[code], E.get(f"{code}_contact"))
        rep[code] = {"old": old, "new": new}
        export_surfaces(code, E[code])
        f = lambda x: round(x, 2) if isinstance(x, float) else x  # noqa: E731
        print(code, "OLD", {k: f(old.get(k)) for k in ("A0_shoulder_mm2", "collar_w", "f1_p95_um", "collar_force_share_load2", "sed_chg_pct", "bone_removed_mm3")},
              "NEW", {k: f(new.get(k)) for k in ("A0_shoulder_mm2", "collar_w", "f1_p95_um", "collar_force_share_load2", "sed_chg_pct", "bone_removed_mm3")}, flush=True)
    (HOME / "deck" / "E_rule" / "compare.json").write_text(json.dumps(rep, indent=1, default=float))


if __name__ == "__main__":
    main()
