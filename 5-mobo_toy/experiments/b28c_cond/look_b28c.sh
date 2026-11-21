#!/usr/bin/env bash
# Read only: the b28c rows and how far each moved from its b28 main row (micromotion), and the sit-to-stand rotation.
cd ~/mobo_toy_v2 || exit 1
echo "$(date -u +%H:%M) watchers $(pgrep -fc '[w]atch_cond')"
python3 - <<'EOF'
import json, math, os
m = json.load(open("results/db_manifest_b28c.json"))
rows = m.get("rows", m)
main = {"3b": 21.73, "1b": 28.35, "0b": 29.29}
for k, r in sorted(rows.items()):
    if not isinstance(r, dict):
        continue
    j = r.get("id") or r.get("expected_id")
    d = "queue/" + str(j)
    s = "DONE" if os.path.exists(d + "/DONE") else "FAILED" if os.path.exists(d + "/FAILED.json") else "CLAIMED" if os.path.exists(d + "/CLAIMED") else "READY" if os.path.exists(d + "/READY") else "NEW"
    line = f"{s:7s} {k:10s}"
    if s == "DONE":
        res = json.load(open(d + "/result.json"))
        f1 = res.get("f1_p95_um")
        lab = k.split("_")[1]
        line += f"  f1 {f1:7.2f}  main {main[lab]:6.2f}  ({math.log10(f1 / main[lab]):+.4f} dex)"
        rot = next((res[x] for x in res if x.startswith("rot") and "first" in x and isinstance(res[x], (int, float))), None)
        if rot is not None:
            line += f"  rot {rot:.4f}"
    if s == "FAILED":
        line += "  " + open(d + "/FAILED.json").read()[:200]
    print(line)
EOF
