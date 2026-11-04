"""批次 G 进度（Linux，只读）：各部分作业的状态计数、阶段 7 优化日志末尾。"""
import collections
import json
import pathlib
import subprocess

HOME = pathlib.Path.home() / "mobo_toy_v2"
Q = HOME / "queue"


def state(d):
    for m, s in (("DONE", "DONE"), ("FAILED.json", "FAILED"), ("SOLVED", "SOLVED"), ("CLAIMED", "CLAIMED"), ("READY", "READY")):
        if (d / m).exists():
            return s
    return "NEW"


out = {}
for p in ("diag_e", "load_ref", "load_dir", "remesh_noise", "neck7"):
    out[p] = dict(collections.Counter(state(d) for d in Q.glob(p + "_*") if d.is_dir()))
print(json.dumps(out))
log = HOME / "logs" / "g4_p7.log"
if log.exists():
    lines = [ln for ln in log.read_text(errors="replace").splitlines() if "warn" not in ln.lower()]
    print("\n".join(lines[-6:]))
pid = HOME / "logs" / "g4_p7.pid"
if pid.exists():
    r = subprocess.run(["ps", "-o", "pid,ni,etime,rss,args", "--ppid", pid.read_text().strip(), "-p", pid.read_text().strip()], capture_output=True, text=True)
    print(r.stdout.strip())
print(subprocess.run(["date"], capture_output=True, text=True).stdout.strip(), "| free GB",
      subprocess.run(["sh", "-c", "free -g | awk '/Mem/{print $7}'"], capture_output=True, text=True).stdout.strip())
