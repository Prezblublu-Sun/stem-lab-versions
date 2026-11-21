#!/bin/sh
# 阶段 13 init 之后的自动链（README_p11_ops.md §8.6）：等 init 驱动结束 → G1 → init 闸门 → 起 2 目标臂 g13b → 等 READY14 → 起 3 目标臂 g14
# → 检查点报告一次。Linux 上运行（POSIX sh / dash），所有输出带时间戳写 ~/mobo_toy_v2/logs/g13_chain.log：
#   cd ~/mobo_toy_v2 && nohup sh adhoc/p11/g13_chain.sh > /dev/null 2>&1 < /dev/null &
# 停止：kill $(cat ~/mobo_toy_v2/logs/g13_chain.pid)（只停这条链；已经起来的两臂不是它的子进程，照常跑）。
#   不要用 R.stop / pkill -P：链本身没有常驻子进程，但别的工具按父进程杀会误伤。等待（sleep）中收到 TERM 立即结束；
#   G1 / 闸门 / 报告正在跑时，TERM 在那一步结束后才生效（sh 先等前台命令）。
# 步骤
#   0. 只允许一个实例：logs/g13_chain.pid 指向一个活着、命令行含 g13_chain 的进程 → 退出 4（pid 文件用 noclobber 原子创建）。
#      先查脚本、run.sh、taskset、python 都在（不在 → 2），再开始等。上一次留下的 logs/g13_chain.FAIL 改名为 .FAIL.prev。
#   1. 等 init：每 POLL_INIT 秒（300）看一次，最多 WAIT_INIT 秒（43200 = 12 h；超时 → 5）。init 驱动 = logs/g13_init.pid 的进程
#      （活着且命令行含 "--phase 13"），或任何命令行匹配 'stage_neckopt.py bo --phase 13' 的进程（pid 文件不在 / 过时也能认出）。
#      驱动不在了、且 results/neckopt_p13.json 正好有 N_INIT（32）条 round-0 记录 → 继续；驱动不在了 EXIT_GRACE 秒（120）后记录数
#      仍不对（init 崩了 / 没写出）→ 5。
#   2. G1：run.sh g1_regress.py --root BASE --src 13 --dst 14 --expect-delta 0.1 --expect-mm-limit none（taskset 4-11、nice 19、
#      OMP / MKL 2）。退出码非 0 → 3（FAIL 文件写退出码与前几条 FAIL 行；全文在 deck/p13_3406/g1/g1_latest.txt）。
#   3. 闸门：arms_gate.py init --root BASE --src 13 --dst 14 --new NEW --expect-delta 0.1 --expect-mm-limit none
#      --flag logs/arms_gate_p13.FAIL（与 g13b / g14 同一个标记文件）。不过 → 6。
#   4. 起 g13b：cd BASE && nohup sh g13b_run.sh > logs/g13b.log 2>&1 < /dev/null &（pid → logs/g13b.pid；双 fork，臂不是链的子进程）。
#      logs/g13b.pid 指向活着的进程 → 不再起第二个，照用它。SETTLE 秒（60）后它必须还活着，否则 → 7（日志里给它的 END 行 / 退出码）。
#   5. 等 READY14：arms_gate.py ready --root BASE --src 13 --dst 14，每 POLL_READY 秒（30），最多 WAIT_READY 秒（1800；超时 → 7）；
#      等的时候 g13b 死了 → 7。
#   6. 起 g14：nohup sh g14_run.sh NEW INFLIGHT（75 2），pid → logs/g14.pid（同上，已在跑就不起）。SETTLE 秒后两臂都必须活着，否则 → 7。
#   7. 报告一次：run.sh p11_report.py --root BASE --src 13 --dst 14 --label LABEL（chain_start；OMP / MKL 1）。退出码非 0 → 8（两臂照常跑，
#      不写 FAIL 文件）。
# 中止（2 / 3 / 5 / 6 / 7）写 logs/g13_chain.FAIL（时间、退出码、原因），什么都不再启动；已经起来的臂不停。
# 环境变量：MOBO_BASE（测试用）PY（默认 ~/mobo_toy_v2/.venv/bin/python，没有则 python3）GATE G1 REPORT G13B G14（默认同目录）
#   N_INIT POLL_INIT WAIT_INIT EXIT_GRACE POLL_READY WAIT_READY SETTLE NEW（75）INFLIGHT（2）LABEL（chain_start）
# 退出码：0 完成；2 前置检查；3 G1 不过；4 已有实例；5 init 等不到 / 不完整；6 闸门不过；7 臂没起来 / READY14 等不到；8 报告失败；143 信号。
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
BASE="${MOBO_BASE:-$HOME/mobo_toy_v2}"
CODE="$BASE/code"
RUN="$BASE/run.sh"
LOGS="$BASE/logs"
STATE="$BASE/results/neckopt_p13.json"
PY="${PY:-$BASE/.venv/bin/python}"
GATE="${GATE:-$HERE/arms_gate.py}"
G1="${G1:-$HERE/g1_regress.py}"
REPORT="${REPORT:-$HERE/p11_report.py}"
G13B="${G13B:-$HERE/g13b_run.sh}"
G14="${G14:-$HERE/g14_run.sh}"
N_INIT="${N_INIT:-32}"
POLL_INIT="${POLL_INIT:-300}"
WAIT_INIT="${WAIT_INIT:-43200}"
EXIT_GRACE="${EXIT_GRACE:-120}"
POLL_READY="${POLL_READY:-30}"
WAIT_READY="${WAIT_READY:-1800}"
SETTLE="${SETTLE:-60}"
NEW="${NEW:-75}"
INFLIGHT="${INFLIGHT:-2}"
LABEL="${LABEL:-chain_start}"
LOG="$LOGS/g13_chain.log"
PIDF="$LOGS/g13_chain.pid"
FAILF="$LOGS/g13_chain.FAIL"
INIT_PIDF="$LOGS/g13_init.pid"
GFLAG="$LOGS/arms_gate_p13.FAIL"
INIT_PAT='stage_neckopt\.py bo --phase 13( |$)'
RCF="$LOGS/.g13_chain.rc.$$"
CAP="$LOGS/.g13_chain.out.$$"
SLP=""

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { printf '%s\n' "[g13_chain $(ts)] $*"; }        # printf, not echo: dash's echo eats backslashes
args_of() {                                           # 进程的命令行（Linux /proc；没有就 ps）
    if [ -r "/proc/$1/cmdline" ]; then tr '\000' ' ' < "/proc/$1/cmdline"; else ps -o args= -p "$1" 2>/dev/null; fi
}

mkdir -p "$LOGS" || { echo "g13_chain: cannot create $LOGS" >&2; exit 2; }

# ---------------------------------------------------------------- 0. 只允许一个实例
claim() { ( set -C; echo "$$" > "$PIDF" ) 2>/dev/null; }
if ! claim; then
    old=$(cat "$PIDF" 2>/dev/null)
    if [ -n "$old" ] && [ "$old" != "$$" ] && kill -0 "$old" 2>/dev/null && args_of "$old" | grep -q 'g13_chain'; then
        msg="[g13_chain $(ts)] another g13_chain is running (pid $old, $PIDF); not starting a second one"
        printf '%s\n' "$msg" >> "$LOG"
        printf '%s\n' "$msg" >&2
        exit 4
    fi
    rm -f "$PIDF"                                     # 过时的 pid 文件（进程不在了，或 pid 被别的进程重用）
    if ! claim; then
        msg="[g13_chain $(ts)] could not create $PIDF (another g13_chain starting at the same moment?); not starting"
        printf '%s\n' "$msg" >> "$LOG"
        printf '%s\n' "$msg" >&2
        exit 4
    fi
fi
exec >> "$LOG" 2>&1

finish() {                                            # finish <退出码> <说明>
    rc=$1; shift
    log "END g13_chain.sh exit $rc: $*"
    [ "$(cat "$PIDF" 2>/dev/null)" = "$$" ] && rm -f "$PIDF"
    rm -f "$RCF" "$CAP"
    exit "$rc"
}
fail() {                                              # fail <退出码> <原因>：写 FAIL 文件、结束（已经起来的臂不动）
    rc=$1; shift
    printf '%s\n' "$(ts) exit $rc: $*" > "$FAILF.tmp" && mv -f "$FAILF.tmp" "$FAILF"
    log "FAIL: $*"
    finish "$rc" "aborted; reason in $FAILF"
}
on_signal() {
    [ -n "$SLP" ] && kill "$SLP" 2>/dev/null
    finish 143 "stopped by signal (arms that were already started are not children of the chain and keep running)"
}
trap on_signal TERM INT
nap() { sleep "$1" & SLP=$!; wait "$SLP"; SLP=""; }  # 后台 sleep + wait：收到信号时立即处理

run_logged() {                                        # run_logged <标签> <命令…>：输出逐行带时间戳进日志（并存到 $CAP），退出码 → $RC
    tag=$1; shift
    rm -f "$RCF" "$CAP"
    : > "$CAP"
    log "RUN $tag: $*"
    { "$@"; echo "$?" > "$RCF"; } 2>&1 | while IFS= read -r line || [ -n "$line" ]; do
        log "  $tag: $line"
        printf '%s\n' "$line" >> "$CAP"
    done
    RC=$(cat "$RCF" 2>/dev/null)
    RC=${RC:-255}
    log "END $tag: exit $RC"
}
with_threads() {                                      # with_threads <n> <命令…>：OMP / MKL n 线程、不写 .pyc、不缓冲，在子 shell 里 exec（不外泄）
    ( OMP_NUM_THREADS=$1 MKL_NUM_THREADS=$1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
      export OMP_NUM_THREADS MKL_NUM_THREADS PYTHONDONTWRITEBYTECODE PYTHONUNBUFFERED
      shift
      exec "$@" )
}

arm_pid() { cat "$LOGS/$1.pid" 2>/dev/null; }
arm_alive() { p=$(arm_pid "$1"); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
arm_end() {                                           # 臂的启动日志里最后一行 END（g11b_run.sh / g12_run.sh 的 finish 写的）
    grep 'END g1[0-9]*b*_run\.sh exit' "$LOGS/$1.log" 2>/dev/null | tail -n 1
}
arm_dead() {                                          # arm_dead <名字>：臂不在了 → 7，带它的退出码与日志末尾
    e=$(arm_end "$1")
    tail -n 8 "$LOGS/$1.log" 2>/dev/null | while IFS= read -r line || [ -n "$line" ]; do log "  $1.log: $line"; done
    fail 7 "the $1 arm is not running (${e:-no END line in logs/$1.log}); see logs/$1.log"
}
start_arm() {                                         # start_arm <名字> <脚本> [参数…]：双 fork 起臂，pid → logs/<名字>.pid
    name=$1; shift
    pf="$LOGS/$name.pid"
    old=$(cat "$pf" 2>/dev/null)
    if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
        log "$name is already running (pid $old, $pf): not starting a second one"
        return 0
    fi
    ( cd "$BASE" || exit 1
      nohup sh "$@" > "$LOGS/$name.log" 2>&1 < /dev/null &
      echo "$!" > "$pf" )
    log "started $name: pid $(cat "$pf" 2>/dev/null) (cd $BASE && nohup sh $* > $LOGS/$name.log)"
}

log "START g13_chain.sh pid $$ on $(hostname): BASE=$BASE N_INIT=$N_INIT POLL_INIT=$POLL_INIT WAIT_INIT=$WAIT_INIT EXIT_GRACE=$EXIT_GRACE POLL_READY=$POLL_READY WAIT_READY=$WAIT_READY SETTLE=$SETTLE NEW=$NEW INFLIGHT=$INFLIGHT LABEL=$LABEL"
if [ -f "$FAILF" ]; then
    log "previous $FAILF ($(cat "$FAILF")) moved to $FAILF.prev"
    mv -f "$FAILF" "$FAILF.prev"
fi

# ---------------------------------------------------------------- 前置检查（等 12 h 之前先查）
for v in N_INIT POLL_INIT WAIT_INIT EXIT_GRACE POLL_READY WAIT_READY SETTLE NEW INFLIGHT; do
    eval "val=\$$v"
    case "$val" in ''|*[!0-9]*) fail 2 "$v=$val is not a non-negative integer";; esac
done
[ "$POLL_INIT" -ge 1 ] && [ "$POLL_READY" -ge 1 ] || fail 2 "POLL_INIT and POLL_READY must be >= 1"
case "$LABEL" in ''|*[!A-Za-z0-9_.-]*) fail 2 "LABEL=$LABEL: use letters, digits, _ . - only";; esac
cd "$CODE" 2>/dev/null || fail 2 "no code directory $CODE"
[ -f "$CODE/v2/stage_neckopt.py" ] || fail 2 "no $CODE/v2/stage_neckopt.py"
[ -x "$RUN" ] || fail 2 "$RUN is not executable"
for f in "$GATE" "$G1" "$REPORT" "$G13B" "$G14" "$HERE/g11b_run.sh" "$HERE/g12_run.sh"; do
    [ -f "$f" ] || fail 2 "missing $f"
done
command -v taskset >/dev/null 2>&1 || fail 2 "taskset not found"
[ -x "$PY" ] || PY=python3
command -v "$PY" >/dev/null 2>&1 || fail 2 "no python ($PY)"
if [ -f "$CODE/VERSION" ]; then log "code VERSION: $(tr '\n' ' ' < "$CODE/VERSION")"; else log "code VERSION: (missing)"; fi

# ---------------------------------------------------------------- 1. 等阶段 13 的 init 驱动结束、状态文件有 N_INIT 条 round-0 记录
init_pid=$(cat "$INIT_PIDF" 2>/dev/null)
case "$init_pid" in
    ''|*[!0-9]*) log "warning: $INIT_PIDF missing or not a pid ('$init_pid'); the init driver is recognised by its command line only"
                 init_pid="" ;;
    *) log "init driver pid file: $init_pid ($(args_of "$init_pid" | cut -c1-200))" ;;
esac
driver_alive() {
    if [ -n "$init_pid" ] && kill -0 "$init_pid" 2>/dev/null && args_of "$init_pid" | grep -q -- '--phase 13'; then
        return 0
    fi
    pgrep -f "$INIT_PAT" >/dev/null 2>&1
}
count_r0() {                                          # neckopt_p13.json 的 round-0 记录数；missing / unreadable
    "$PY" -c 'import json, sys
try:
    st = json.load(open(sys.argv[1]))
    print(sum(1 for r in st.get("records", []) if isinstance(r, dict) and r.get("round") == 0))
except FileNotFoundError:
    print("missing")
except Exception:
    print("unreadable")' "$STATE" 2>/dev/null || echo "unreadable"
}
t0=$(date +%s)
gone=""
while :; do
    n=$(count_r0 | tr -d '\r ')                       # tr：Windows 上的 python 打印 \r\n（本机测试）；Linux 上无影响
    if driver_alive; then
        what="running"
        gone=""
    else
        what="not running"
        if [ "$n" = "$N_INIT" ]; then
            log "the phase-13 init driver has exited and $STATE has $n round-0 records"
            break
        fi
        [ -n "$gone" ] || gone=$(date +%s)
        if [ $(( $(date +%s) - gone )) -ge "$EXIT_GRACE" ]; then
            fail 5 "the phase-13 init driver is not running (pid ${init_pid:-none}) but $STATE has $n round-0 records, expected $N_INIT (init crashed, or not started?)"
        fi
    fi
    if [ $(( $(date +%s) - t0 )) -ge "$WAIT_INIT" ]; then
        fail 5 "timeout: still waiting for the phase-13 init after $WAIT_INIT s (driver $what, round-0 records $n of $N_INIT)"
    fi
    log "waiting for the phase-13 init: driver $what, round-0 records in neckopt_p13.json: $n of $N_INIT"
    nap "$POLL_INIT"
done

# ---------------------------------------------------------------- 2. G1（只读回归）
run_logged g1 with_threads 2 taskset -c 4-11 nice -n 19 \
    "$RUN" "$G1" --root "$BASE" --src 13 --dst 14 --expect-delta 0.1 --expect-mm-limit none
if [ "$RC" != 0 ]; then
    rows=$(grep '^FAIL' "$CAP" 2>/dev/null | head -n 3 | tr '\n' ';' | cut -c1-600)
    fail 3 "G1 (g1_regress.py --src 13 --dst 14 --expect-delta 0.1 --expect-mm-limit none) exit $RC: ${rows:-no FAIL rows printed}; full report deck/p13_3406/g1/g1_latest.txt"
fi

# ---------------------------------------------------------------- 3. init 闸门
run_logged gate "$PY" "$GATE" init --root "$BASE" --src 13 --dst 14 --new "$NEW" --expect-delta 0.1 --expect-mm-limit none --flag "$GFLAG"
if [ "$RC" != 0 ]; then
    v=$(grep -E '^(FAIL|PASS) ' "$CAP" 2>/dev/null | tail -n 1 | cut -c1-600)
    fail 6 "arms_gate.py init --src 13 --dst 14 --expect-mm-limit none exit $RC: ${v:-no verdict line} ($GFLAG)"
fi

# ---------------------------------------------------------------- 4. 2 目标臂 g13b
start_arm g13b "$G13B"
nap "$SETTLE"
arm_alive g13b || arm_dead g13b
log "g13b alive (pid $(arm_pid g13b))"

# ---------------------------------------------------------------- 5. 等阶段 14 的冻结热启动能建（READY14）
t1=$(date +%s)
last=0
while :; do
    rout=$("$PY" "$GATE" ready --root "$BASE" --src 13 --dst 14 2>&1)
    rrc=$?
    if [ "$rrc" = 0 ] && printf '%s\n' "$rout" | grep -q '^READY14=1$'; then
        printf '%s\n' "$rout" | while IFS= read -r line || [ -n "$line" ]; do log "  ready: $line"; done
        break
    fi
    arm_alive g13b || arm_dead g13b
    now=$(date +%s)
    if [ $(( now - last )) -ge 300 ]; then
        printf '%s\n' "$rout" | grep -E 'not ready|READY14=|unreadable' | while IFS= read -r line || [ -n "$line" ]; do log "  ready: $line"; done
        last=$now
    fi
    if [ $(( now - t1 )) -ge "$WAIT_READY" ]; then
        why=$(printf '%s\n' "$rout" | grep 'not ready' | head -n 2 | tr '\n' ';' | cut -c1-500)
        fail 7 "READY14 not reached within $WAIT_READY s (arms_gate ready exit $rrc: ${why:-see the log}); g13b keeps running, g14 not started"
    fi
    nap "$POLL_READY"
done

# ---------------------------------------------------------------- 6. 3 目标臂 g14
start_arm g14 "$G14" "$NEW" "$INFLIGHT"
nap "$SETTLE"
arm_alive g14 || arm_dead g14
arm_alive g13b || arm_dead g13b
log "both arms alive: g13b pid $(arm_pid g13b), g14 pid $(arm_pid g14)"

# ---------------------------------------------------------------- 7. 检查点报告（一次）
run_logged report with_threads 1 taskset -c 4-11 nice -n 19 \
    "$RUN" "$REPORT" --root "$BASE" --src 13 --dst 14 --label "$LABEL"
if [ "$RC" != 0 ]; then
    finish 8 "p11_report.py exit $RC (the arms keep running; re-run the report by hand, README section 8.7)"
fi
finish 0 "chain complete: arms g13b (pid $(arm_pid g13b)) and g14 (pid $(arm_pid g14)) running; report in $BASE/deck/p13_3406/"
