#!/usr/bin/env bash
# Read only: state of the b28 rows and the micromotion of the finished ones, against the prediction and the A family curve (fast F is not shown; mesh F needs the export).
cd ~/mobo_toy_v2 || exit 1
echo "$(date -u +%H:%M) watchers $(pgrep -fc '[w]atch_b28')"
python3 - <<'EOF'
import json, math, os
Q = os.path.expanduser("~/mobo_toy_v2/queue/")
m = json.load(open(os.path.expanduser("~/mobo_toy_v2/results/db_manifest_b28.json")))
rows = m.get("rows", m)
pred = {"0b": 1.49570, "0o": 1.79919, "0x": 1.99791, "1b": 1.51031, "1o": 2.07760, "1x": 1.84483, "2b": 1.31186, "2o": 1.19463, "2x": 1.87355, "3b": 1.38344, "3o": 1.30816, "3x": 2.06277, "4b": 1.61493, "4o": 1.68003, "4x": 1.85927}
curve = {"0b": 26.3, "0o": 29.1, "0x": 32.8, "1b": 26.5, "1o": 37.4, "1x": 22.3, "2b": 17.0, "2o": 12.9, "2x": 37.6, "3b": 25.8, "3o": 14.2, "3x": 23.4, "4b": 29.9, "4o": 34.0, "4x": 28.7}
for k, r in sorted(rows.items()):
    if not isinstance(r, dict):
        continue
    j = r.get("id") or r.get("expected_id")
    d = Q + str(j)
    s = "-" if not os.path.isdir(d) else ("DONE" if os.path.exists(d + "/DONE") else "FAILED" if os.path.exists(d + "/FAILED.json") else "CLAIMED" if os.path.exists(d + "/CLAIMED") else "READY" if os.path.exists(d + "/READY") else "NEW")
    line = f"{s:7s} {k:10s}"
    if s == "DONE":
        f1 = json.load(open(d + "/result.json")).get("f1_p95_um")
        lab = k.replace("FAM1_", "")
        if lab in pred:
            line += f" f1 {f1:7.2f} pred {10 ** pred[lab]:6.1f} (FE-pred {math.log10(f1) - pred[lab]:+.3f} dex)  A curve {curve[lab]:5.1f}  x{f1 / curve[lab]:.2f}"
        else:
            line += f" f1 {f1:7.2f}"
    print(line)
EOF
