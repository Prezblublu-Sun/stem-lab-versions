"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_foam_refine.py
Local only, no femur, no FE: a toy model in gmsh (a cortex box, a cancellous box inside it, a cylinder 'stem' pushed into both), fragmented and
grouped the way model3d_m1 does it, then meshed with the production size field (model3d_v2._size_field) with and without the F5 wrapper.

A. validate: defaults, bad keys, h out of range, distances out of order.
B. install replaces model3d_m1._size_field only, a second install does not stack wrappers.
C. on the toy model: the wrapper finds the stem-bone interface faces; the production Threshold is still there; the background field is the Min;
   bone tets within 1 mm of the interface are about h, not h_int; tets inside the stem far from its surface and bone tets far from the stem
   keep the production size.
D. fail closed: no physical groups -> error; a production field without a Threshold -> error.
"""
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import gmsh  # noqa: E402

import foam_refine as FRF  # noqa: E402
import model3d_m1 as M1  # noqa: E402
import model3d_v2 as M2  # noqa: E402

T0 = time.perf_counter()
checks = []
CFG = {"mesh": {"dist_min_mm": 0.5, "dist_max_mm": 15.0}}
H_INT, H_FAR, H = 2.0, 6.0, 0.5
STEM_X, STEM_R = 12.0, 8.0


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T0:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


def raises(fn, *a):
    try:
        fn(*a)
    except (ValueError, RuntimeError):
        return True
    return False


def toy(size_field, groups=True):
    """Mesh the toy model; returns {group: (centroids, mean edge)} and the field list."""
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        occ = gmsh.model.occ
        cort = occ.addBox(0, 0, 0, 30, 30, 40)
        canc = occ.addBox(5, 5, 0, 20, 20, 40)
        stem = occ.addCylinder(STEM_X, 15, 10, 0, 0, 40, STEM_R)          # crosses x = 5 into the cortex, like a stem that touches the wall
        cort2, _ = occ.cut([(3, cort)], [(3, canc)], removeTool=False)
        bone, _ = occ.cut(cort2, [(3, stem)], removeObject=True, removeTool=False)
        canc2, _ = occ.cut([(3, canc)], [(3, stem)], removeObject=True, removeTool=False)
        frag, fmap = occ.fragment(bone + canc2, [(3, stem)])
        occ.synchronize()
        nb = len(bone)
        cv = sorted({t for dt in fmap[:nb] for d, t in dt if d == 3})
        kv = sorted({t for dt in fmap[nb:nb + len(canc2)] for d, t in dt if d == 3})
        sv = sorted({t for dt in fmap[nb + len(canc2):] for d, t in dt if d == 3})
        if groups:
            gmsh.model.addPhysicalGroup(3, cv, name="cortex")
            gmsh.model.addPhysicalGroup(3, kv, name="cancellous")
            gmsh.model.addPhysicalGroup(3, sv, name="stem")
        surfs = sorted({t for v in sv for d, t in gmsh.model.getBoundary([(3, v)], oriented=False) if d == 2})
        size_field(gmsh, surfs, CFG, H_INT, H_FAR)
        fields = {t: gmsh.model.mesh.field.getType(t) for t in gmsh.model.mesh.field.list()}
        for k, v in M2.MESH_OPTS:
            gmsh.option.setNumber(k, v)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.model.mesh.generate(3)
        out = {}
        for g, vols in (("cortex", cv), ("cancellous", kv), ("stem", sv)):
            cen, edge = [], []
            for v in vols:
                _, tags, nodes = gmsh.model.mesh.getElements(3, v)
                if not len(tags):
                    continue
                conn = np.asarray(nodes[0], int).reshape(-1, 4)
                ntag, xyz, _ = gmsh.model.mesh.getNodes()
                pos = dict(zip(ntag.tolist(), xyz.reshape(-1, 3)))
                P = np.array([[pos[n] for n in tet] for tet in conn])
                cen.append(P.mean(1))
                edge.append(np.mean([np.linalg.norm(P[:, i] - P[:, j], axis=1) for i, j in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))], axis=0))
            out[g] = (np.vstack(cen), np.concatenate(edge))
        return out, fields
    finally:
        gmsh.finalize()


def dist_to_stem(c):
    """Distance of points to the toy stem (cylinder STEM_R about x = STEM_X, y = 15, z from 10 up)."""
    r = np.hypot(c[:, 0] - STEM_X, c[:, 1] - 15)
    side = np.abs(r - STEM_R)
    bottom = np.where(r <= STEM_R, np.abs(c[:, 2] - 10), np.hypot(r - STEM_R, c[:, 2] - 10))
    return np.where(c[:, 2] >= 10, side, bottom)


try:
    # A
    p = FRF.validate({"h": 0.7}, 2.0)
    ok("A: defaults dist_min 1.5, dist_max 4.0", p == {"h": 0.7, "dist_min": 1.5, "dist_max": 4.0})
    ok("A: bad inputs raise", all(raises(FRF.validate, x, 2.0) for x in ({}, {"h": 0.2}, {"h": 2.0}, {"h": 0.7, "x": 1}, {"h": 0.7, "dist_min": 4, "dist_max": 3},
                                                                       {"h": 0.7, "dist_max": 12}, {"h": True}, {"h": "0.7"}, [0.7])))
    # B
    orig = M1._size_field
    FRF.install({"h": 0.7}, 2.0)
    w1 = M1._size_field
    FRF.install({"h": 0.5}, 2.0)
    w2 = M1._size_field
    ok("B: install wraps model3d_m1._size_field, keeps the original, does not stack", w1 is not orig and w2._foam_orig is orig and w1._foam_orig is orig and M2._size_field is orig)
    M1._size_field = orig
    # C
    base, f0 = toy(M2._size_field)
    FRF.INFO.clear()
    fine, f1 = toy(FRF.make_size_field(M2._size_field, FRF.validate({"h": H, "dist_min": 1.5, "dist_max": 4.0}, H_INT)))
    info = dict(FRF.INFO)
    ok("C: production fields unchanged, plus Distance, Threshold, Restrict, Min", sorted(f0.values()) == ["Distance", "Threshold"]
       and sorted(f1.values()) == ["Distance", "Distance", "Min", "Restrict", "Threshold", "Threshold"], str(f1))
    ok("C: interface faces found (cylinder side, its cap, inside both bone volumes)", info.get("n_interface_surfaces", 0) >= 2 and info.get("n_bone_volumes") == 2, str(info))

    def near(g, out, lo, hi):
        c, e = out[g]
        m = (dist_to_stem(c) >= lo) & (dist_to_stem(c) < hi)
        return float(np.median(e[m])) if m.any() else float("nan"), int(m.sum())
    for g in ("cancellous", "cortex"):
        b0, n0 = near(g, base, 0, 1.0)
        b1, n1 = near(g, fine, 0, 1.0)
        ok(f"C: {g} tets within 1 mm of the stem: median edge {b0:.2f} -> {b1:.2f} mm, count {n0} -> {n1}", b1 < 0.75 * H_INT * 0.6 and n1 > 3 * n0 and b1 < b0)
    # inside the stem the mesh grades down from the fine interface faces (gmsh), so it is finer than production; the Restrict keeps it coarser
    # than the bone band (without the Restrict the toy stem has 3.5 x the tets and 0.65 mm edges, measured 11-08)
    s_in = np.median(fine["stem"][1][dist_to_stem(fine["stem"][0]) < 1.0])
    b_out = np.median(fine["cancellous"][1][dist_to_stem(fine["cancellous"][0]) < 1.0])
    ok(f"C: stem tets within 1 mm inside are coarser than bone tets within 1 mm outside: {s_in:.2f} vs {b_out:.2f} mm (Restrict works)", s_in > 1.2 * b_out)
    n0, n1 = sum(len(x[1]) for x in base.values()), sum(len(x[1]) for x in fine.values())
    print(f"     toy model tets: production {n0}, h {H:g} {n1} ({n1 / n0:.1f} x)")
    c0 = np.median(base["cortex"][1][dist_to_stem(base["cortex"][0]) > 8])
    c1 = np.median(fine["cortex"][1][dist_to_stem(fine["cortex"][0]) > 8])
    ok(f"C: cortex tets more than 8 mm from the stem: median edge {c0:.2f} vs {c1:.2f} mm (within 10 %)", abs(c1 - c0) <= 0.10 * c0)
    # D
    ok("D: no physical groups -> error", raises(lambda: toy(FRF.make_size_field(M2._size_field, FRF.validate({"h": H}, H_INT)), groups=False)))

    def no_threshold(gmsh_, surfs, cfg, h_int, h_far):
        fd = gmsh_.model.mesh.field.add("Distance")
        gmsh_.model.mesh.field.setNumbers(fd, "SurfacesList", surfs)
        gmsh_.model.mesh.field.setAsBackgroundMesh(fd)
    ok("D: a production field without a Threshold -> error", raises(lambda: toy(FRF.make_size_field(no_threshold, FRF.validate({"h": H}, H_INT)))))
    # E: jobs.prep paths with stand-ins for the femur, templating and model build (no gmsh, no femur); M1._size_field is restored after each
    import json
    import shutil
    import tempfile
    import inspect
    import jobs as J

    class _SkipE(Exception):
        pass
    HOOKED = "foam_refine" in inspect.getsource(J.prep)          # 11-08: jobs.py restored to f2e5fbe on purpose while b29-b31 feed
    real = {k: getattr(J, k) for k in ("femur_for", "QROOT")}
    real_G = {k: getattr(J.G, k) for k in ("Stem3D", "template")}
    real_build = M1.build
    q = pathlib.Path(tempfile.mkdtemp(prefix="foam_refine_prep_"))
    try:
        if not HOOKED:
            raise _SkipE
        J.QROOT = q
        J.femur_for = lambda spec: type("FM", (), {"cut_from_head_mm": 16.0, "resected_volume": lambda self, **k: 0.0, "cfg": {}})()
        J.G.Stem3D = lambda **k: object()
        J.G.template = lambda st, fem, alphas=None, offsets=None, iters=14, margin=None: {"fit": True, "A0": 500.0, "alpha": 44.0, "e": 0.0, "contact": 0.0,
                                                                                        "s_bind": 1.0, "volume": 1.0, "margin": 1.0}

        def prep(name, spec):
            d = q / name
            d.mkdir()
            (d / "spec.json").write_text(json.dumps(spec))
            st = J.prep(name)
            fj = d / "FAILED.json"
            return st, (json.loads(fj.read_text()) if fj.exists() else {})
        base = {"kind": "variant", "model": "m1", "design": {}, "h_int": 2.0, "fric_only": True, "foam_refine": {"h": 0.7}}
        st, fj = prep("intact", {**base, "kind": "intact"})
        ok("E: foam_refine on an intact job -> FAILED L1 before any femur work", st == "FAILED" and fj.get("level") == "L1" and "foam_refine" in json.dumps(fj), str(fj)[:160])
        st, fj = prep("notm1", {**base, "model": "v2", "fric_only": False})
        ok("E: foam_refine without model m1 -> FAILED L1 (the foam_refine check)", st == "FAILED" and fj.get("level") == "L1" and "foam_refine needs model m1" in fj.get("reason", ""),
           str(fj)[:160])

        def boom(*a, **k):
            raise RuntimeError("stand-in build failed")
        M1.build = boom
        st, fj = prep("boom", base)
        ok("E: build fails after the hook is installed -> FAILED, and model3d_m1._size_field is the production one again",
           st == "FAILED" and M1._size_field is M2._size_field, str(fj)[:160])
        M1.build = lambda *a, **k: {"n_nodes": 1}                       # never calls the size field
        plain = {k: v for k, v in base.items() if k not in ("foam_refine", "fric_only")}
        st, fj = prep("plain", plain)
        pj = json.loads((q / "plain" / "prep.json").read_text()) if (q / "plain" / "prep.json").exists() else {}
        ok("E: a job without foam_refine -> READY, no foam_refine in prep.json, size field never touched (review N6)",
           st == "READY" and "foam_refine" not in pj and M1._size_field is M2._size_field and not hasattr(M1._size_field, "_foam_orig"), str(fj or pj)[:160])
        FRF.INFO.clear()
        st, fj = prep("nocall", base)
        ok("E: the size field hook never called -> FAILED L3, and the size field restored", st == "FAILED" and fj.get("level") == "L3" and "not called" in json.dumps(fj)
           and M1._size_field is M2._size_field, str(fj)[:160])
    except _SkipE:
        print("SKIP E: v2/jobs.py has no F5 hook now (restored to the f2e5fbe version while b29-b31 feed, 2026-11-08); E runs again once the hook is back", flush=True)
    finally:
        M1.build = real_build
        for k, v in real.items():
            setattr(J, k, v)
        for k, v in real_G.items():
            setattr(J.G, k, v)
        M1._size_field = M2._size_field
        shutil.rmtree(q, ignore_errors=True)
finally:
    pass

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
