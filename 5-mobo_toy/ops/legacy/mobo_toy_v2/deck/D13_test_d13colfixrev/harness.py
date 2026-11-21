"""Review (d13colfixrev): run the collector main() with optional injected failures. Usage:
harness.py <mode> -- <collector args>; mode: none | rowfail (stab_of raises for one job; job_info raises for another inside safe_row)."""
import importlib.util
import pathlib
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("collector_rev2", HERE / "deck_D13_collect.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
mode = sys.argv[1]
args = sys.argv[sys.argv.index("--") + 1:]
if mode == "rowfail":
    orig_stab, orig_info = C.stab_of, C.job_info
    def stab_of(job):
        if job == "load_dir_FI_sag9_70da3ca5":
            raise RuntimeError("injected stab failure (d13colfixrev)")
        return orig_stab(job)
    calls = {"n": 0}
    def job_info(job):
        if job == "neck1_r10_54b67b13":
            calls["n"] += 1
            if calls["n"] > 1:          # first call in d13_row succeeds, the retry inside safe_row also fails
                raise KeyError("injected job_info failure (d13colfixrev)")
            raise ValueError("injected first job_info failure (d13colfixrev)")
        return orig_info(job)
    C.stab_of, C.job_info = stab_of, job_info
sys.argv = ["deck_D13_collect.py"] + args
C.main()
