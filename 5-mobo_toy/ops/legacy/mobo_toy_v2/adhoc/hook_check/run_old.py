import sys, types, pathlib
sys.path.insert(0, "v2")
V2 = pathlib.Path("v2").resolve()
m = types.ModuleType("jobs"); m.__file__ = str(V2 / "jobs.py"); sys.modules["jobs"] = m
exec(compile(open(sys.argv[1]).read(), "jobs_old", "exec"), m.__dict__)
m.QROOT = pathlib.Path(sys.argv[2])
print(m.prep("WS_copy"))
