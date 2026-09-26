"""几何与几何门测试（R1-A3）。"""
import pathlib
import sys

import numpy as np
import pytest
from scipy.stats import qmc

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import femur2d as F  # noqa: E402
import stem2d as S  # noqa: E402


@pytest.mark.parametrize("dorr", ["A", "B", "C"])
def test_dorr_targets_hit(dorr):
    f = F.build(dorr)
    D = F.CFG["dorr"][dorr]
    assert abs(f.measured["cfi"] - D["cfi"]) <= 0.05
    assert abs(f.measured["ci"] - D["ci"]) <= 0.05
    assert F.dorr_band("cfi", f.measured["cfi"]) == dorr
    assert F.dorr_band("ci", f.measured["ci"]) == dorr


@pytest.mark.parametrize("dorr", ["A", "B", "C"])
def test_regions_valid(dorr):
    f = F.build(dorr)
    assert f.outer.is_valid and f.inner.is_valid
    assert f.outer.contains(f.inner.buffer(-1e-3))
    assert f.measured["min_cortex_mm"] >= F.FC["min_cortex"] - 0.05
    assert f.cortex.area > 0 and f.cancellous.area > 0


def test_outer_contour_identical_across_types():
    a, c = F.build("A").outer, F.build("C").outer
    assert a.symmetric_difference(c).area < 1e-9


def test_cut_and_zones():
    f = F.build("B")
    C0, u = f.cut
    H = np.array(F.FC["head_center"])
    assert np.isclose(np.linalg.norm(H - C0), F.FC["neck_cut_from_head"])
    z = f.zones()
    assert z["gruen7"].area > 100 and z["gruen1"].area > 100
    assert z["gruen7"].intersection(z["gruen1"]).area < 1e-6


def test_arc_passes_through_tip_and_is_tangent():
    st = S.make("B", S.to_physical(np.full(5, 0.5)))
    p, t, _ = st.axis(np.array([0.0, st.L]))
    assert np.allclose(p[0], st.C0, atol=1e-9)
    assert np.allclose(t[0], st.d0, atol=1e-9)
    assert np.allclose(p[1], st.tip, atol=1e-6)


def test_halfwidth_monotone_non_increasing():
    st = S.make("A", S.to_physical(np.array([0.3, 0.5, 0.9, 0.3, 0.5])))
    s = np.linspace(st.s_min, st.L, 500)
    w = st.halfwidth(s)
    assert np.all(np.diff(w) <= 1e-12)


@pytest.mark.parametrize("dorr", ["A", "C"])
def test_zero_overcut_for_passing_designs(dorr):
    U = qmc.Sobol(5, scramble=True, seed=7).random(64)
    checked = 0
    for u in U:
        st = S.make(dorr, S.to_physical(u))
        if not S.gate(st)["pass"]:
            continue
        r = st.sweep_overcut(step=0.5)
        assert r["overcut_frac"] <= 1e-3, r
        checked += 1
        if checked >= 3:
            break
    assert checked >= 1


def test_gate_rejects_out_of_range_and_accepts_moderate():
    bad = S.make("B", S.to_physical(np.full(5, 0.5)))
    bad.w_prox = 2.0
    assert S.gate(bad)["level"] == "L1"
    ok = [S.gate(S.make("A", S.to_physical(u)))["pass"] for u in qmc.Sobol(5, seed=3).random(32)]
    assert any(ok)


def test_in_bone_part_is_below_cut():
    st = S.make("B", S.to_physical(np.full(5, 0.5)))
    inb = st.in_bone()
    C0, u = st.femur.cut
    xy = np.asarray(inb.exterior.coords)
    assert np.all((xy - C0) @ u <= 1e-6)
    assert st.neck().intersection(st.femur.kept_halfplane()).area < 1e-6
