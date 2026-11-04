#!/bin/bash
# 短柄网格失败：界面网格 h_int 1.94（S 类椭圆实际用的）能否让圆 / 非对称建成
cd ~/mobo_toy_v2/code
run() { ( ulimit -v 12000000; ~/mobo_toy_v2/run.sh ../adhoc/plc_probe.py "$@" 2>&1 | grep "^==" ); echo "exit $? for $*"; }
run 25 1.0 - 1.94
run 25 1.0 - 1.94 asym
run 25 1.0 - 1.9
run 25 1.0 - 1.9 asym
run 25 1.0 - 2.06
