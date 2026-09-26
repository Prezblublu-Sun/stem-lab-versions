# -*- coding: utf-8 -*-
"""在 Abaqus 内置 Python 下运行（CLAUDE.md §5.4）：只用标准库 + odbAccess，只导出，不分析。

用法：abq2025 python odb_export.py <job.odb> <out_dir>

每个分析步取最后一帧，写：
  <step>_U.csv        node, u1, u2                     （全部节点）
  <step>_S.csv        elem, mises, s11, s22, s12        （单元形心）
  <step>_ENER.csv     elem, else, evol                  （整单元量）
  <step>_CONTACT.csv  field, node, value                （CPRESS / CSLIP1 / CSTATUS / COPEN / CSHEAR1）
  odb_meta.json       分析步、帧数、最后帧时间、字段清单
"""
import csv
import json
import os
import sys

from abaqusConstants import CENTROID
from odbAccess import openOdb

CONTACT_PREFIX = ("CPRESS", "CSLIP1", "CSTATUS", "COPEN", "CSHEAR1")


def _write(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def main(odb_path, out_dir):
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    odb = openOdb(odb_path, readOnly=True)
    meta = {"odb": odb_path, "steps": []}
    try:
        for sname in odb.steps.keys():
            step = odb.steps[sname]
            if len(step.frames) == 0:
                meta["steps"].append({"name": sname, "n_frames": 0})
                continue
            fr = step.frames[-1]
            fo = fr.fieldOutputs
            info = {"name": sname, "n_frames": len(step.frames), "last_frame_value": fr.frameValue,
                    "time_period": step.timePeriod, "fields": sorted(fo.keys())}
            if "U" in fo.keys():
                _write(os.path.join(out_dir, sname + "_U.csv"), ["node", "u1", "u2"],
                       [(v.nodeLabel, repr(float(v.data[0])), repr(float(v.data[1]))) for v in fo["U"].values])
            if "S" in fo.keys():
                sc = fo["S"].getSubset(position=CENTROID)
                _write(os.path.join(out_dir, sname + "_S.csv"), ["elem", "mises", "s11", "s22", "s12"],
                       [(v.elementLabel, repr(float(v.mises)), repr(float(v.data[0])), repr(float(v.data[1])),
                         repr(float(v.data[3])) if len(v.data) > 3 else repr(float(v.data[2]))) for v in sc.values])
            if "ELSE" in fo.keys() and "EVOL" in fo.keys():
                ev = dict((v.elementLabel, float(v.data)) for v in fo["EVOL"].values)
                _write(os.path.join(out_dir, sname + "_ENER.csv"), ["elem", "else", "evol"],
                       [(v.elementLabel, repr(float(v.data)), repr(ev.get(v.elementLabel, float("nan"))))
                        for v in fo["ELSE"].values])
            rows = []
            for key in fo.keys():
                if key.split()[0] in CONTACT_PREFIX:
                    for v in fo[key].values:
                        rows.append((key.split()[0], v.nodeLabel, repr(float(v.data))))
            if rows:
                _write(os.path.join(out_dir, sname + "_CONTACT.csv"), ["field", "node", "value"], rows)
            meta["steps"].append(info)
    finally:
        odb.close()
    with open(os.path.join(out_dir, "odb_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
