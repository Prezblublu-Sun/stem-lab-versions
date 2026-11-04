#!/bin/sh
# 目标阶段的 3 目标臂（转动 ↓ × 完全接触面积 ↑ × 去骨量 ↓，metric v4；去骨量确定、不建 GP）= 并行两臂里的 3 目标臂。阶段号由环境变量给：
# DST（默认 12，本臂）/ SRC（默认 11，冻结热启动的来源阶段 = 2 目标臂）。默认值 = 阶段 12 臂（计算计划_50h_2026-10-24.md §7 修订 1；
# 审查 wf_6f8fbde1 第 1 条），行为与从前相同；阶段 14 臂（δ 0.10、微动不作约束，用户 2026-10-24 12:20）用 g14_run.sh
# （= SRC=13 DST=14 EXPECT_DELTA=0.1、默认预算 75 再调本脚本）。与来源阶段臂（g11b_run.sh / g13b_run.sh）同时跑，各 inflight 2、各 BUDGET 个
# 自有提交。Linux 上从 ~/mobo_toy_v2/code 运行；CPU 4–11、nice 19、OMP / MKL 2。用法：sh g12_run.sh [BUDGET [INFLIGHT]]（默认 95 2）。
# 启动见 README_p11_ops.md：
#   cd ~/mobo_toy_v2 && nohup sh adhoc/p11/g12_run.sh 95 2 > logs/g12.log 2>&1 < /dev/null & echo $! > logs/g12.pid
# 热启动 = 冻结集（PHASES[DST]["warm_from"] = 阶段 SRC 的 init 记录 + 收编的冒烟作业）：第一次启动时驱动从 neckopt_p<SRC>.json 取、
#   按阶段 DST 的设置（v4；阶段 14 还有 mm_limit None）重打分，id 存进 neckopt_p<DST>.json 的 warm_start_ids；续跑只用存的 id。
#   --warm 对 warm_from 阶段无效（驱动忽略它并在日志里写明）；这里照计划写 --warm family。
#   预算只数阶段 DST 自己的 sb<DST>_* 作业（热启动行不计）：BUDGET 95 = 95 个自有提交。
# 步骤
#   1. 前置检查：logs/<NAME>.pid 另一实例活着 → 4；阶段 DST 驱动活着 → 4；同步的 stage_neckopt.py 里 PHASES[DST] 没有
#      "warm_from": {"phase": SRC → 6（代码没同步）。
#   2. 闸门：同一个 arms_gate.py init --src SRC --dst DST（两臂从同一个段 A 出发：段 A 不过，本臂也不启动）→ 3（写 logs/<FLAG>）/ 5。
#      EXPECT_MM 设了 → 闸门另带 --expect-mm-limit（状态文件的微动上限不符 → 3）；EXPECT_MM=none 时第 1 步另查同步的代码：PHASES[SRC] 那一行
#      要有 "mm_limit": None，PHASES[DST] 那一行要么也写 "mm_limit": None、要么不提 mm_limit 且继承 {**PHASES[SRC], …}，否则 → 2。
#   3. 等来源阶段臂收编冒烟作业：轮询 arms_gate.py ready --src SRC --dst DST（只读）直到 READY，每 POLL 秒（30），最多 WAIT_P11 秒（1800）；超时 → 8。
#      READY = neckopt_p<DST>.json 里已有冻结集（续跑），或 neckopt_p<SRC>.json 有 round-0 记录、队列里没有阶段 SRC 还没收编的 sb<SRC>_*、
#      阶段 SRC 没有收编后仍在算的作业（驱动在同样情况下也会拒绝冻结）。先启动来源阶段臂，它第一次保存后这里就 READY。
#   4. async --phase DST --budget BUDGET --inflight INFLIGHT --pool 16384 --seed 0 --refresh 32 --refresh-rad 0.08 --warm family --workers 4
#      --pool / --seed 与来源阶段相同时直接用同一个池文件（pool_phase 11），段 A 的 init 点在池上、标为已用。
#      驱动的输出写 logs/<NAME>.driver.log（每次启动重写），同时用 tail --pid 实时转进本脚本的日志。
#   5. 竞态重试（审查 wcc2j2fj4 rev 第 4 条）：第 3 步 READY 之后、驱动自己的严格检查之前，来源阶段可能刚 J.submit 了一个新选点
#      （spec.json 已写、save() 还没记进 pending），驱动就会把它当成"还没收编"而拒绝。驱动在 RETRY_WINDOW 秒（120）内退出、
#      退出码非 0、且它的日志里有 'cannot freeze the warm start' → 等 RETRY_SLEEP 秒（10）回到第 3 步重新轮询，最多 MAX_RETRY 次（3）；
#      还不行 → 9。其他退出照旧（退出码 = async 的）。
# 环境变量：SRC DST POOL SEED WORKERS REFRESH REFRESH_RAD MAX_FAIL ALLOW_INFEASIBLE EXPECT_DELTA EXPECT_MM WAIT_P11 POLL EXPECT_GIT PY GATE MOBO_BASE
#   （同 g11b_run.sh）RETRY_WINDOW（120）RETRY_SLEEP（10）MAX_RETRY（3）。名字随 DST：NAME g12 / g14（logs/<NAME>.pid、.child.pid、.driver.log）；
#   标记文件 logs/arms_gate.FAIL（SRC 11）/ logs/arms_gate_p<SRC>.FAIL（与来源阶段臂共用同一个 init 闸门的标记）。
# 退出码：0 正常结束；2 参数 / 前置检查失败；3 闸门不过；4 已有实例 / 阶段 DST 驱动在跑；5 状态文件读不了；6 PHASES[DST] 没有来自 SRC 的 warm_from；
#   8 冻结热启动等不到 READY；9 驱动重试 MAX_RETRY 次后仍拒绝冻结热启动；143 收到信号；其他 = async 的退出码。
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
BASE="${MOBO_BASE:-$HOME/mobo_toy_v2}"
CODE="$BASE/code"
RUN="$BASE/run.sh"
LOGS="$BASE/logs"
PY="${PY:-$BASE/.venv/bin/python}"
GATE="${GATE:-$HERE/arms_gate.py}"
SRC="${SRC:-11}"
DST="${DST:-12}"
BUDGET="${1:-95}"
INFLIGHT="${2:-2}"
POOL="${POOL:-16384}"
SEED="${SEED:-0}"
WORKERS="${WORKERS:-4}"
REFRESH="${REFRESH:-32}"
REFRESH_RAD="${REFRESH_RAD:-0.08}"
MAX_FAIL="${MAX_FAIL:-0.15}"
EXPECT_DELTA="${EXPECT_DELTA:-}"
EXPECT_MM="${EXPECT_MM:-}"
AI=""                                       # ALLOW_INFEASIBLE=1 -> arms_gate.py --allow-infeasible (zero feasible init designs do not block)
[ "${ALLOW_INFEASIBLE:-0}" = 1 ] && AI="--allow-infeasible"
WAIT_P11="${WAIT_P11:-1800}"
POLL="${POLL:-30}"
RETRY_WINDOW="${RETRY_WINDOW:-120}"
RETRY_SLEEP="${RETRY_SLEEP:-10}"
MAX_RETRY="${MAX_RETRY:-3}"
case "$SRC" in ''|*[!0-9]*) echo "SRC=$SRC is not a phase number"; exit 2;; esac
case "$DST" in ''|*[!0-9]*) echo "DST=$DST is not a phase number"; exit 2;; esac
[ "$SRC" != "$DST" ] || { echo "SRC and DST are the same phase ($SRC)"; exit 2; }
NAME="g$DST"
if [ "$SRC" = 11 ]; then FLAGN=arms_gate.FAIL; else FLAGN="arms_gate_p${SRC}.FAIL"; fi
PIDF="$LOGS/$NAME.pid"
CHILDF="$LOGS/$NAME.child.pid"
DRVLOG="$LOGS/$NAME.driver.log"
FLAG="$LOGS/$FLAGN"
PATD="stage_neckopt\\.py (bo|async) --phase $DST( |\$)"
PATS="stage_neckopt\\.py (bo|async) --phase $SRC( |\$)"
CHILD=""
TAILP=""
DRV_ELAPSED=0
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2

log() { printf '%s\n' "[$NAME $(date '+%Y-%m-%d %H:%M:%S')] $*"; }   # printf, not echo: dash's echo eats backslashes

finish() {
    rc=$1; shift
    log "END $(basename "$0") exit $rc: $*"
    [ "$(cat "$PIDF" 2>/dev/null)" = "$$" ] && rm -f "$PIDF"
    rm -f "$CHILDF"
    exit "$rc"
}

descendants() {                            # 子进程树（run.sh 若不 exec python，python 与池进程在下面一两层）
    for c in $(pgrep -P "$1" 2>/dev/null); do
        echo "$c"
        descendants "$c"
    done
}

on_signal() {
    log "signal received; stopping child ${CHILD:-none}"
    if [ -n "$CHILD" ]; then
        tree="$CHILD $(descendants "$CHILD" | tr '\n' ' ')"   # 先收齐整棵树再一起发 TERM：先杀父进程会让孙进程成孤儿
        log "  TERM -> $tree"
        kill -TERM $tree 2>/dev/null
    fi
    [ -n "$TAILP" ] && kill "$TAILP" 2>/dev/null
    finish 143 "stopped by signal (submitted jobs keep solving; a restart resumes from neckopt_p$DST.json with the frozen warm start)"
}
trap on_signal TERM INT

run_driver() {                             # 驱动输出写 $DRVLOG（竞态重试要 grep 它），tail --pid 实时转进本日志；记开始 / 结束行与退出码
    label=$1; shift
    log "START $label: taskset -c 4-11 nice -n 19 $RUN $* (driver output also in $DRVLOG)"
    t0=$(date +%s)
    : > "$DRVLOG"
    taskset -c 4-11 nice -n 19 "$RUN" "$@" > "$DRVLOG" 2>&1 &
    CHILD=$!
    echo "$CHILD" > "$CHILDF"
    tail -n +1 -f --pid="$CHILD" "$DRVLOG" &   # 驱动退出后 tail 把剩下的读完再自己退出
    TAILP=$!
    wait "$CHILD"
    rc=$?
    CHILD=""
    rm -f "$CHILDF"
    wait "$TAILP" 2>/dev/null
    TAILP=""
    DRV_ELAPSED=$(( $(date +%s) - t0 ))
    log "END $label: exit $rc after $DRV_ELAPSED s"
    return "$rc"
}

# ---------------------------------------------------------------- 1. 前置检查
mkdir -p "$LOGS" || { echo "cannot create $LOGS"; exit 2; }
if [ -f "$PIDF" ]; then
    old=$(cat "$PIDF" 2>/dev/null)
    if [ -n "$old" ] && [ "$old" != "$$" ] && kill -0 "$old" 2>/dev/null; then
        log "another $NAME launcher is running (pid $old, $PIDF); not starting"
        exit 4
    fi
fi
echo "$$" > "$PIDF"
log "START $(basename "$0") pid $$ on $(hostname): SRC=$SRC DST=$DST BUDGET=$BUDGET INFLIGHT=$INFLIGHT POOL=$POOL SEED=$SEED WORKERS=$WORKERS REFRESH=$REFRESH REFRESH_RAD=$REFRESH_RAD MAX_FAIL=$MAX_FAIL EXPECT_DELTA=${EXPECT_DELTA:-none} EXPECT_MM=${EXPECT_MM:-unchecked} WAIT_P11=$WAIT_P11"
for v in BUDGET INFLIGHT POOL SEED WORKERS REFRESH WAIT_P11 POLL RETRY_WINDOW RETRY_SLEEP MAX_RETRY; do
    eval "val=\$$v"
    case "$val" in ''|*[!0-9]*) finish 2 "$v=$val is not a non-negative integer (usage: sh $(basename "$0") [BUDGET [INFLIGHT]])";; esac
done
[ "$INFLIGHT" -ge 1 ] || finish 2 "INFLIGHT must be >= 1"
[ "$POLL" -ge 1 ] || finish 2 "POLL must be >= 1"
ED=""
if [ -n "$EXPECT_DELTA" ]; then
    case "$EXPECT_DELTA" in *[!0-9.]*|.|*.*.*) finish 2 "EXPECT_DELTA=$EXPECT_DELTA is not a number";; esac
    ED="--expect-delta $EXPECT_DELTA"
fi
EM=""
if [ -n "$EXPECT_MM" ]; then
    case "$EXPECT_MM" in
        none|null) ;;
        .|*.*.*|*[!0-9.]*) finish 2 "EXPECT_MM=$EXPECT_MM is not 'none' or a number of um";;
    esac
    EM="--expect-mm-limit $EXPECT_MM"
fi
cd "$CODE" 2>/dev/null || finish 2 "no code directory $CODE"
[ -f "$CODE/v2/stage_neckopt.py" ] || finish 2 "no $CODE/v2/stage_neckopt.py"
[ -x "$RUN" ] || finish 2 "$RUN is not executable"
[ -f "$GATE" ] || finish 2 "no gate script $GATE"
command -v taskset >/dev/null 2>&1 || finish 2 "taskset not found"
tail --help 2>&1 | grep -q -- '--pid' || finish 2 "this tail has no --pid (GNU coreutils needed to stream the driver log)"
[ -x "$PY" ] || PY=python3
command -v "$PY" >/dev/null 2>&1 || finish 2 "no python for the gate ($PY)"
if [ -f "$CODE/VERSION" ]; then
    log "code VERSION: $(tr '\n' ' ' < "$CODE/VERSION")"
else
    log "code VERSION: (missing)"
fi
if [ -n "${EXPECT_GIT:-}" ]; then
    grep -q "^git=$EXPECT_GIT" "$CODE/VERSION" 2>/dev/null || finish 2 "code/VERSION git= does not start with $EXPECT_GIT"
fi
if ! grep -Eq "^PHASES\\[$DST\\][[:space:]]*=.*\"warm_from\": \\{\"phase\": $SRC," "$CODE/v2/stage_neckopt.py"; then
    finish 6 "PHASES[$DST] has no warm_from from phase $SRC in the synced stage_neckopt.py (sync the code with the frozen warm start and pass g1_regress.py first)"
fi
if [ "$EXPECT_MM" = none ] || [ "$EXPECT_MM" = null ]; then
    grep -Eq "^PHASES\[$SRC\][^#]*\"mm_limit\": None" "$CODE/v2/stage_neckopt.py" \
        || finish 2 "EXPECT_MM=none but the PHASES[$SRC] line of the synced stage_neckopt.py has no \"mm_limit\": None (stale code? sync the reviewed commit)"
    dline=$(grep -E "^PHASES\[$DST\][[:space:]]*=" "$CODE/v2/stage_neckopt.py" | tail -n 1)
    case "$dline" in
        *'"mm_limit": None'*) ;;
        *'"mm_limit"'*) finish 2 "EXPECT_MM=none but PHASES[$DST] overrides mm_limit with something other than None in the synced stage_neckopt.py" ;;
        *"{**PHASES[$SRC],"*) ;;
        *) finish 2 "EXPECT_MM=none but PHASES[$DST] neither sets \"mm_limit\": None nor inherits {**PHASES[$SRC], ...} in the synced stage_neckopt.py" ;;
    esac
fi
if pgrep -f "$PATD" >/dev/null 2>&1; then
    ps -o pid,etime,args -p "$(pgrep -d, -f "$PATD")" 2>/dev/null | sed 's/^/    /'
    finish 4 "a phase-$DST BO driver is already running; not starting a second one"
fi
if pgrep -f "$PATS" >/dev/null 2>&1; then
    log "phase-$SRC driver alive (expected: the parallel 2-objective arm): $(pgrep -f "$PATS" | tr '\n' ' ')"
else
    log "note: no phase-$SRC driver is running (the 2-objective arm should run in parallel; start its launcher)"
fi

# ---------------------------------------------------------------- 2. 闸门（与来源阶段臂同一个 init 闸门）
out=$("$PY" "$GATE" init --root "$BASE" --src "$SRC" --dst "$DST" --max-fail "$MAX_FAIL" --new "$BUDGET" --flag "$FLAG" $AI $ED $EM 2>&1)
grc=$?
printf '%s\n' "$out" | while IFS= read -r line; do log "  gate: $line"; done
case "$grc" in
    0) ;;
    3) finish 3 "init gate failed (see the numbers above and $FLAG); the phase-$DST arm is not started (MAX_FAIL=1 overrides the failure-rate limit, ALLOW_INFEASIBLE=1 the zero-feasible rule)" ;;
    5) finish 5 "neckopt_p$SRC.json is missing or unreadable (segment A has not finished?); not started" ;;
    *) finish 2 "gate script exit $grc" ;;
esac

tries=0
while :; do
    # ------------------------------------------------------------ 3. 冻结热启动能建了吗（等来源阶段臂第一次保存）
    t0=$(date +%s)
    last=0
    while :; do
        rout=$("$PY" "$GATE" ready --root "$BASE" --src "$SRC" --dst "$DST" 2>&1)
        rrc=$?
        [ "$rrc" -eq 0 ] && break
        now=$(date +%s)
        if [ $(( now - last )) -ge 300 ] || [ "$last" -eq 0 ]; then
            printf '%s\n' "$rout" | while IFS= read -r line; do log "  warm-start check: $line"; done
            last=$now
        fi
        [ "$rrc" -eq 8 ] || [ "$rrc" -eq 5 ] || finish 2 "warm-start check exit $rrc"
        if [ $(( now - t0 )) -ge "$WAIT_P11" ]; then
            finish 8 "the frozen warm start is still not ready after ${WAIT_P11} s (start the phase-$SRC arm first; see the reasons above)"
        fi
        sleep "$POLL"
    done
    printf '%s\n' "$rout" | while IFS= read -r line; do log "  warm-start check: $line"; done
    if pgrep -f "$PATD" >/dev/null 2>&1; then
        finish 4 "a phase-$DST BO driver appeared while waiting; not starting"
    fi

    # ------------------------------------------------------------ 4. 3 目标异步 BO
    run_driver "phase-$DST arm (async budget $BUDGET inflight $INFLIGHT, frozen warm start)" v2/stage_neckopt.py async --phase "$DST" --budget "$BUDGET" \
        --inflight "$INFLIGHT" --pool "$POOL" --seed "$SEED" --refresh "$REFRESH" --refresh-rad "$REFRESH_RAD" --warm family --workers "$WORKERS"
    rc=$?

    # ------------------------------------------------------------ 5. 竞态重试：驱动刚启动就拒绝冻结热启动 → 回到第 3 步
    if [ "$rc" -ne 0 ] && [ "$DRV_ELAPSED" -lt "$RETRY_WINDOW" ] && grep -q 'cannot freeze the warm start' "$DRVLOG" 2>/dev/null; then
        tries=$(( tries + 1 ))
        if [ "$tries" -gt "$MAX_RETRY" ]; then
            finish 9 "the phase-$DST driver refused to freeze the warm start again (exit $rc after $DRV_ELAPSED s; $MAX_RETRY retries used); see its ValueError above / in $DRVLOG"
        fi
        log "the driver exited $rc after $DRV_ELAPSED s (< ${RETRY_WINDOW} s) with 'cannot freeze the warm start' (a phase-$SRC submission between the readiness check and the driver's own check?): retry $tries of $MAX_RETRY in ${RETRY_SLEEP} s, back to the readiness poll"
        sleep "$RETRY_SLEEP"
        continue
    fi
    finish "$rc" "phase-$DST arm finished"
done
