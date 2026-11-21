"""0 FE, Linux, writes only under adhoc/hook_check. (1) a spec without the new keys builds byte-identically to the queue job; (2) torsion rows: mesh equal to the baseline, m_fric.inp differs only in the loaded *CLOAD blocks, the written forces give the target moment;
(3) pose rows build; (4) Z2: 8 poses x the candidates, penetration and overhang. usage: run.sh check_hooks_linux.py (from ~/mobo_toy_v2/code/v2)."""
import copy, json, pathlib, re, shutil, subprocess, sys, time
sys.path[:0] = [".", ".."]
import numpy as np
import jobs as J
import stage_db as DB
import pose_fixed as PF
import torsion_load as TL
import tpl_record as TR
import geom3d as G
import collar_rule as CR

ROOT = pathlib.Path.home() / "mobo_toy_v2/adhoc/hook_check"
if ROOT.exists():
    raise SystemExit(f"{ROOT} exists")
ROOT.mkdir()
Q = J.QROOT
WS = "db_ws_p13_a105_91e458e3_m1_2a79b613"
spec0 = json.load(open(Q / WS / "spec.json"))
b = DB.build("b24")
assert not b["problems"], b["problems"]
rows = {r["key"]: r for r in b["rows"]}
JOBS = {"WS_copy": spec0, "TA_e0": rows["TQ1S_A_e0"]["spec"], "TB_e0": rows["TQ1S_B_e0"]["spec"], "TA_e2.5": rows["TQ1S_A_e+2.5"]["spec"],
        "PF_de-1": rows["PF1S_e0_de-1"]["spec"], "PF_de+1": rows["PF1S_e0_de+1"]["spec"], "PF15_de+1": rows["PF1S_e+1.5_de+1"]["spec"]}
for lab, pf in (("PF_ds+1", {"ds": 1.0}), ("PF_rot+3", {"rot_deg": 3.0}), ("PF_da+3", {"dalpha_deg": 3.0}), ("PF_ds-1", {"ds": -1.0}), ("PF_da-3", {"dalpha_deg": -3.0})):
    s = copy.deepcopy(rows["PF1S_e0_de-1"]["spec"]); s["pose_fixed"] = pf
    JOBS[lab] = s
PY = "import sys, pathlib; sys.path.insert(0, 'v2'); import jobs as J; J.QROOT = pathlib.Path(sys.argv[2]); print(J.prep(sys.argv[1]))"
for lab, s in JOBS.items():
    (ROOT / lab).mkdir()
    (ROOT / lab / "spec.json").write_text(json.dumps(s, indent=1, default=float))
running, t0 = {}, time.time()
todo = list(JOBS)
while todo or running:
    while todo and len(running) < 5:
        lab = todo.pop(0)
        running[lab] = subprocess.Popen([sys.executable, "-c", PY, lab, str(ROOT)], cwd=str(pathlib.Path.cwd().parent), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for lab, p in list(running.items()):
        if p.poll() is not None:
            print(f"{time.time() - t0:.0f}s {lab}: {p.stdout.read().strip()[-200:]}", flush=True)
            del running[lab]
    time.sleep(1)

print("== (1) no new keys: byte identity against the queue job", WS)
d0, d1 = Q / WS, ROOT / "WS_copy"
for f in ("m_fric.inp", "m_bond.inp", "keep.json"):
    print(f" {f}: {'identical' if (d0 / f).exists() and (d1 / f).read_bytes() == (d0 / f).read_bytes() else 'DIFFERENT or absent in the queue'}" if (d0 / f).exists() else f" {f}: not kept in the queue job")
a, c = np.load(d0 / "mesh3d.npz"), np.load(d1 / "mesh3d.npz")
print(" mesh3d.npz arrays identical:", all(np.array_equal(a[k], c[k]) for k in a.files) and set(a.files) == set(c.files), len(a.files))
pa, pc = json.load(open(d0 / "prep.json")), json.load(open(d1 / "prep.json"))
print(" prep.json keys differing:", [k for k in sorted(set(pa) | set(pc)) if pa.get(k) != pc.get(k)])
ma, mc = (d0 / "model3d.json").read_bytes(), (d1 / "model3d.json").read_bytes()
print(" model3d.json:", "identical" if ma == mc else "DIFFERENT")

print("== (2) torsion rows")
for lab, base in (("TA_e0", "WS_copy"), ("TB_e0", "WS_copy")):
    d, d_b = ROOT / lab, ROOT / base
    a, c = np.load(d_b / "mesh3d.npz"), np.load(d / "mesh3d.npz")
    print(f" {lab}: mesh identical to the baseline: {all(np.array_equal(a[k], c[k]) for k in a.files)}; m_bond.inp removed: {not (d / 'm_bond.inp').exists()}; state {J.state(d)}")
    t = (d / "m_fric.inp").read_text(); tb = (d_b / "m_fric.inp").read_text()
    head = lambda s: s.split("*STEP, NAME=LOAD,")[0]    # noqa: E731
    h1, h2 = head(t), head(tb)
    print("   text up to the LOAD step: same except the heading line:", h1.split("\n", 2)[2:] == h2.split("\n", 2)[2:] or h1.split("\n")[3:] == h2.split("\n")[3:])
    pr = json.load(open(d / "prep.json"))
    tq = pr["torsion"]
    print("   record", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in tq.items() if k not in ("axis", "M_Nmm", "head_centroid")}, "axis", np.round(tq["axis"], 4).tolist(), "load_N", np.round(pr["load_N"], 1).tolist(), "n_head", pr["n_head"])
    # the written forces in the file, step LOAD and LOAD2
    z = c
    labs = z["node_labels"].astype(int); idx = {int(n): i for i, n in enumerate(labs)}
    for stp in ("LOAD", "LOAD2"):
        body = t.split(f"*STEP, NAME={stp},")[1].split("*END STEP")[0]
        rows_ = re.findall(r"^(\d+), ([123]), (\S+)$", body, re.M)
        F = {}
        for n_, k_, v_ in rows_:
            F.setdefault(int(n_), [0.0, 0.0, 0.0])[int(k_) - 1] = float(v_)
        nn = sorted(F); X = z["nodes"][[idx[n] for n in nn]]; Fa = np.array([F[n] for n in nn])
        r = X - X.mean(0)
        M_ = np.cross(r, Fa).sum(0)
        print(f"   {stp}: {len(nn)} nodes, net force {np.round(Fa.sum(0), 3).tolist()} vs load_N, |moment about centroid - target| {np.linalg.norm(M_ - np.array(tq['M_Nmm'])):.4f} N*mm of {np.linalg.norm(tq['M_Nmm']):.0f}")
    print("   UNLOAD block untouched:", "HEADN, 1, 0." in t.split("*STEP, NAME=UNLOAD,")[1].split("*END STEP")[0])

print("== (3) pose rows: record from prep.json")
for lab in [k for k in JOBS if k.startswith("PF")]:
    d = ROOT / lab
    if J.state(d) != "READY":
        print(f" {lab}: state {J.state(d)}", (d / "FAILED.json").read_text()[:300] if (d / "FAILED.json").exists() else "")
        continue
    pr = json.load(open(d / "prep.json")); r = pr["pose_fixed"]; t = pr["templating"]
    print(f" {lab}: e {t['e']:+.1f} alpha {t['alpha']:.2f} A0 {t['A0']:.1f} s_bind {t['s_bind']:.1f} | pen_vs_m {r['penetration_vs_margin_mm']:.3f} pen_vs_endo {r['penetration_vs_endosteum_mm']:.3f} overhang {r['neck_overhang_mm2']:.2f} | n_pairs_cortex {pr['n_pairs_cortex']} cortex_frac {pr['cortex_area_frac']:.4f} area {pr['interface_area_mm2']:.0f} tets {pr['n_tet']['stem']}")

print("== (4) Z2: size fixed, 8 poses, default tolerances. foam_min = m - pen_vs_m; into cortex if pen_vs_endo > 0")
POSES = [{"de": -1.0}, {"de": 1.0}, {"ds": -1.0}, {"ds": 1.0}, {"rot_deg": -3.0}, {"rot_deg": 3.0}, {"dalpha_deg": -3.0}, {"dalpha_deg": 3.0}]
CANDS = {"A m0.5": "sb13_a105_91e458e3", "WS_m1": WS, "WL_L44": "db_ws_p13_a105_91e458e3_wl_m1_L44_08f4c01a"}
for e_ in ("+1", "+1.5", "+2", "+2.5"):
    CANDS[f"e{e_}"] = next(pathlib.Path(x).name for x in sorted((str(p) for p in Q.glob(f"db_ws_p13_a105_91e458e3_ow_m1_e{e_}_*"))))
print("cand | " + " | ".join(",".join(f"{k}{v:+g}" for k, v in p.items()) for p in POSES))
for lab, j in CANDS.items():
    sp = json.load(open(Q / j / "spec.json"))
    rule = TR.spec_rule(sp)
    fm = TR.base_femur(rule.femur_id, rule.neck_axis)
    if sp.get("h_cut") is not None:
        fm = fm.with_cut(float(sp["h_cut"]))
    st = G.Stem3D(**sp["design"])
    t = json.load(open(Q / j / "prep.json"))["templating"]
    pl = {"alpha": t["alpha"], "e": t["e"], "A0": t["A0"], "margin": t["margin"], "pose": fm.pose(t["alpha"], t["e"])}
    cells = []
    for p in POSES:
        n = PF.apply(st, fm, pl, p); r = n["pose_fixed"]
        cells.append(f"{t['margin'] - r['penetration_vs_margin_mm']:+.2f}/{r['penetration_vs_endosteum_mm']:.2f}/{r['neck_overhang_mm2']:.1f}")
    print(f"{lab:8s} A0 {t['A0']:.1f} m {t['margin']:.2f} | " + " | ".join(cells), flush=True)
print("cells: foam_min mm / into cortex mm / neck overhang mm2")
