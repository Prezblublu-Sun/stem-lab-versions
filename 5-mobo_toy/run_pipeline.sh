#!/usr/bin/env bash
# 顺序运行 S2（最终模型）→ S4 → S5 → S7 → R7，每步生成报告；任一步失败即停止。
set -e
cd "$(dirname "$0")"
PY=".venv-mobo/Scripts/python.exe"
export PYTHONUTF8=1 PYTHONUNBUFFERED=1
log() { echo "[pipeline $(date '+%F %T')] $*"; }

log "S2 start";  $PY stage_s2.py > runs/pipe_s2.log 2>&1;  $PY report.py --stage S2 || true;  log "S2 done"
log "S4 start";  $PY stage_s4.py > runs/pipe_s4.log 2>&1;  $PY report.py --stage S4 || true;  log "S4 done"
log "S5 start";  $PY stage_s5.py > runs/pipe_s5.log 2>&1;  $PY report.py --stage S5 || true;  log "S5 done"
log "S7 start";  $PY stage_s7.py > runs/pipe_s7.log 2>&1;  $PY report.py --stage S7 || true;  log "S7 done"
log "R7 start";  $PY stage_r7.py > runs/pipe_r7.log 2>&1;  $PY report.py --stage close || true; log "R7 done"
log "ALL DONE"
