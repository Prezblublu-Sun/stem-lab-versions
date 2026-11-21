"""Lane：照着跑一份选点策略。

吃一份在系统外调好的策略、目标和约束、候选池，在本机另开一个进程跑一次，产出一批点。
它只负责照着跑并记全，不评价策略，不解释目标、约束和候选池的内容，不碰有限元。

一个实验一个任务，名字叫「选点」。策略报错、返回的东西不合约定，都记成问题并存下原始报错。
同样的设置和种子，重跑得到同一批点（前提和做法见同文件夹的 说明.md）。
"""
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

from stemlab.plugins import Output, Plugin, Setting
from stemlab.record import pid_alive, sha256_path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "runner.py"
TASK = "选点"
OUTPUT = "一批点"
SEED_MAX = 2**32 - 1  # numpy 的全局种子最大到这里
PASSED_ON = ("目标和约束", "候选池", "预测器", "已有数据")  # 原样交给策略的设置

# 这个操作台进程自己启动的策略进程。别的操作台进程启动的，这里没有，靠进程号看它还在不在。
_PROCS: dict = {}


class Refused(Exception):
    """设置不对，或策略返回的东西不合约定。消息是给人看的。"""


def normalise(returned, n: int) -> tuple[list[dict], list[str]]:
    """把策略返回的东西整理成一批点。返回 (点, 要记下的问题)。不合约定就抛 Refused。"""
    if not isinstance(returned, list):
        raise Refused(f"select 要返回一个列表，收到的是 {type(returned).__name__}")
    if not returned:
        raise Refused("策略一个点都没有选出来")
    if len(returned) > n:
        raise Refused(f"要 {n} 个点，策略给了 {len(returned)} 个。插件不替策略决定去掉哪几个")
    width = max(2, len(str(len(returned))))
    points, seen = [], set()
    for i, item in enumerate(returned, start=1):
        if not isinstance(item, dict):
            raise Refused(f"第 {i} 个点不是一个对象")
        if "设计" not in item:
            raise Refused(f"第 {i} 个点没有「设计」")
        reason = item.get("理由")
        if not isinstance(reason, str) or not reason.strip():
            raise Refused(f"第 {i} 个点没有写「理由」")
        name = item.get("名字", f"p{i:0{width}d}")
        if not isinstance(name, str) or not name:
            raise Refused(f"第 {i} 个点的「名字」要是一段文字")
        if name in seen:
            raise Refused(f"点的名字重了：{name}")
        seen.add(name)
        point = {"名字": name, "设计": item["设计"], "条件": item.get("条件", {}), "理由": reason}
        point.update({k: v for k, v in item.items() if k not in point})  # 策略另给的字段原样留着
        points.append(point)
    notes = []
    if len(points) < n:
        notes.append(f"要 {n} 个点，策略只给了 {len(points)} 个。给出的点照常产出")
    return points, notes


def tail(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_bytes()[-limit:].decode("utf-8", errors="replace")
    except OSError:
        return ""


class Lane(Plugin):
    name = "Lane"
    version = "0.1"
    category = "优化"
    what = "照着跑一份选点策略，产出一批点。只在本机跑，不评价策略，不碰有限元"

    settings = [
        Setting("策略", True, "一个 Python 文件，或一个带 strategy.py 的文件夹，里面有函数 select(inputs)。用「复制文件」填，原文存一份"),
        Setting("目标和约束", True, "原样交给策略，插件不解释。一个值，或一个文件"),
        Setting("候选池", True, "一份候选点，原样交给策略。一个值，或一个文件"),
        Setting("预测器", False, "原样交给策略。一般是另一个实验的产出"),
        Setting("已有数据", False, "原样交给策略。起点用哪些已有的点"),
        Setting("选几个点", True, "一个正整数。策略最多给这么多个"),
        Setting("随机种子", True, f"0 到 {SEED_MAX} 的整数。同样的设置和种子，重跑得到同一批点"),
    ]
    outputs = [
        Output(OUTPUT, "JSON 列表，一个点一项：名字、设计、条件、理由；策略另给的字段原样留着"),
    ]

    # ---- 启动、报任务状态、停止、重试 ------------------------------------

    def start(self, ctx):
        ctx.task(TASK, "排队")
        self._launch(ctx)

    def poll(self, ctx):
        task = ctx.tasks().get(TASK)
        if task is None:
            return
        if task["state"] != "运行":  # 没有在跑的东西：让实验结束，不要一直停在运行中
            ctx.finish()
            return
        run_dir = self._runs(ctx)[-1]
        if (run_dir / "done.json").exists():
            self._collect(ctx, run_dir)
        elif not self._alive(run_dir):
            if (run_dir / "done.json").exists():  # 正好在两次看之间写完退出的
                self._collect(ctx, run_dir)
            else:
                self._fail(
                    ctx, run_dir, "策略的进程没有留下结果就退出了",
                    "策略的进程退出了，但没有写 done.json。它的标准错误输出（末尾）：\n" + tail(run_dir / "stderr.txt"),
                )

    def stop(self, ctx):
        task = ctx.tasks().get(TASK)
        if task is None or task["state"] not in ("排队", "运行"):
            return
        runs = self._runs(ctx)
        if runs:
            (runs[-1] / "stop").write_text("", encoding="ascii")  # 运行器看到这个文件就自己退出
            proc = _PROCS.pop(str(runs[-1]), None)
            if proc is not None:
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        ctx.task(TASK, "停止")

    def retry(self, ctx):
        task = ctx.tasks().get(TASK)
        if task is not None and task["state"] == "完成":
            ctx.finish()  # 已经有一批点了，没有要重做的
            return
        ctx.task(TASK, "排队")
        self._launch(ctx)

    # ---- 里面的做法 ------------------------------------------------------

    def _runs(self, ctx) -> list[Path]:
        if not ctx.private_dir.is_dir():
            return []
        return sorted(p for p in ctx.private_dir.iterdir() if p.is_dir() and p.name.startswith("run_"))

    def _job(self, ctx, run_dir: Path) -> dict:
        """查设置，把策略复制到这一次运行的文件夹里，返回交给运行器的那一份。"""
        n, seed = ctx.setting("选几个点"), ctx.setting("随机种子")
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise Refused(f"设置「选几个点」要是一个正整数，填的是：{n!r}")
        if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= SEED_MAX:
            raise Refused(f"设置「随机种子」要是 0 到 {SEED_MAX} 的整数，填的是：{seed!r}")
        source = ctx.setting("策略")
        if not isinstance(source, Path):
            raise Refused("设置「策略」要是一个文件或文件夹，不能是一个值")
        if not source.exists():
            raise Refused(f"设置「策略」的文件找不到：{source}")

        # 跑的是这一份复制件：存定的那一份不会被策略碰到，只记了位置的策略也有原文留下
        copy = run_dir / "策略" / source.name
        if source.is_dir():
            shutil.copytree(source, copy, ignore=shutil.ignore_patterns("__pycache__"))
            entry = copy / "strategy.py"
            if not entry.is_file():
                raise Refused("设置「策略」是一个文件夹时，里面要有 strategy.py")
        else:
            copy.parent.mkdir(parents=True)
            shutil.copy2(source, copy)
            entry = copy

        inputs = {}
        for name in PASSED_ON:
            value = ctx.setting(name)
            if value is None:
                inputs[name] = None
            elif isinstance(value, Path):
                inputs[name] = {"file": str(value)}
            else:
                inputs[name] = {"value": value}
        inputs["选几个点"] = {"value": n}
        inputs["随机种子"] = {"value": seed}
        return {"entry": str(entry), "seed": seed, "inputs": inputs, "strategy_sha256": sha256_path(copy)}

    def _launch(self, ctx) -> None:
        number = len(self._runs(ctx)) + 1
        run_dir = ctx.private_dir / f"run_{number:02d}"
        try:
            (run_dir / "work").mkdir(parents=True)
            job = self._job(ctx, run_dir)
            (run_dir / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
            env = dict(os.environ, PYTHONUTF8="1", PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
            extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
            with open(run_dir / "stdout.txt", "wb") as out, open(run_dir / "stderr.txt", "wb") as err:
                proc = subprocess.Popen(
                    [sys.executable, str(RUNNER), str(run_dir)],
                    cwd=run_dir / "work", stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env, **extra,
                )
        except Refused as err:
            self._fail(ctx, run_dir, str(err), f"Lane 没有启动策略：{err}")
            return
        except Exception as err:
            self._fail(ctx, run_dir, f"Lane 没能启动策略：{type(err).__name__}: {err}", traceback.format_exc())
            return
        (run_dir / "pid.txt").write_text(str(proc.pid), encoding="ascii")
        _PROCS[str(run_dir)] = proc
        ctx.task(TASK, "运行", stage="策略在跑")
        ctx.provenance(策略进程={
            "第几次运行": number,
            "python": sys.executable,
            "策略哈希": job["strategy_sha256"],
            "运行文件夹": f"plugin_state/{run_dir.name}",
        })

    def _alive(self, run_dir: Path) -> bool:
        proc = _PROCS.get(str(run_dir))
        if proc is not None:
            return proc.poll() is None
        try:
            return pid_alive(int((run_dir / "pid.txt").read_text(encoding="ascii")))
        except (OSError, ValueError):
            return False

    def _collect(self, ctx, run_dir: Path) -> None:
        proc = _PROCS.pop(str(run_dir), None)
        if proc is not None:
            proc.poll()
        done = json.loads((run_dir / "done.json").read_text(encoding="utf-8"))
        if not done["ok"]:
            raw = done["raw"]
            said = tail(run_dir / "stderr.txt")
            if said.strip():
                raw += "\n策略的标准错误输出（末尾）：\n" + said
            self._fail(ctx, run_dir, f"策略出错：{done['error']}", raw)
            return
        n = ctx.setting("选几个点")
        try:
            points, notes = normalise(done["returned"], n)
        except Refused as err:
            got = json.dumps(done["returned"], ensure_ascii=False)
            self._fail(ctx, run_dir, f"策略返回的东西不合约定：{err}", f"{err}\nselect 返回的是（开头）：\n{got[:4000]}")
            return
        ctx.outputs_dir.mkdir(parents=True, exist_ok=True)
        path = ctx.outputs_dir / f"{OUTPUT}.json"
        # 文件里只有点，没有时间和编号：同样的设置和种子重跑，这个文件逐字节相同，哈希也相同
        path.write_bytes((json.dumps(points, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        ctx.output(OUTPUT, path, what=f"{len(points)} 个点，种子 {ctx.setting('随机种子')}")
        for note in notes:
            ctx.problem(note, task=TASK, raw=note)
        ctx.provenance(策略跑完={"用时秒": done["seconds"], "包和版本": done["packages"]})
        ctx.task(TASK, "完成")
        ctx.finish()

    def _fail(self, ctx, run_dir: Path, error: str, raw: str) -> None:
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "原始报错.txt").write_text(raw, encoding="utf-8")
        except OSError:
            pass
        ctx.task(TASK, "失败")
        ctx.problem(error, task=TASK, raw=raw)
        ctx.finish()


PLUGIN = Lane()
