"""出预测插件：用一个标量预测器对一批点出预测，带不确定度。只在本机 CPU 上算。

预测器可以是训练实验的产出，也可以是一个外来的文件，但都得是「标量预测器 v0」这种 zip。
一批点和 FEA 吃的是同一种：一行就是骨、设计、条件。JSON 和平的 CSV 表两种都读。

预测器文件被改过时不出数：任务记失败，实验记一条问题。
一个点缺输入、骨没见过：这个点不出数，记进问题，别的点照常。

这个插件不调用训练插件，只认预测器文件的格式。场预测器（整体应变场）没有做。
"""
import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from stemlab.plugins import Output, Plugin, Setting
from stemlab.record import pid_alive

HERE = Path(__file__).resolve().parent
TASK = "预测"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class ScalarPredict(Plugin):
    name = "scalar-predict"
    version = "0.1"
    category = "代理"
    what = "用一个标量预测器对一批点出预测，带不确定度。本机 CPU"

    settings = [
        Setting("预测器", what="训练实验（scalar-train）的产出「预测器」，或一个外来的同样格式的文件（用「只记位置」填）"),
        Setting(
            "一批点",
            what='和 FEA 吃的是同一种，一行就是骨、设计、条件。两种都收：JSON {"格式": "一批点 v0", "点": [{"名字": "p1", '
            '"骨": "sawbone3406", "设计": {"L": 30, …}, "条件": {"delta_mm": 0.1}}]}；或平的 CSV 表，列名和标签表一样。'
            "可以是文件，也可以直接填 JSON 的值",
        ),
    ]
    outputs = [
        Output("预测", what="JSON：每个点每个目标的预测值、标准差、90% 区间；没出数的点写着原因"),
        Output("预测表", what="同一份内容的平表（CSV），一行一个点"),
    ]

    def _attempts(self, ctx) -> list[Path]:
        if not ctx.private_dir.is_dir():
            return []
        found = [p for p in ctx.private_dir.iterdir() if p.is_dir() and p.name.isdigit()]
        return sorted(found, key=lambda p: int(p.name))

    def _launch(self, ctx) -> None:
        n = len(self._attempts(ctx)) + 1
        attempt = ctx.private_dir / str(n)
        attempt.mkdir(parents=True)
        ctx.task(TASK, "排队", stage=f"第 {n} 次")
        try:
            predictor = ctx.setting("预测器")
            if not isinstance(predictor, Path):
                raise ValueError("「预测器」要是一个文件：训练实验的产出，或用「只记位置」填的文件。")
            points = ctx.setting("一批点")
            if not isinstance(points, Path):  # 直接填的值：写成文件再读，和读文件走同一条路
                if not isinstance(points, (dict, list)):
                    raise ValueError("「一批点」直接填值时要是 JSON 的对象或列表。")
                value, points = points, attempt / "一批点.json"
                points.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
            job = {
                "attempt_dir": str(attempt),
                "out_dir": str(ctx.outputs_dir / str(n)),
                "predictor": {"path": str(predictor), "expected_sha256": sha256_file(predictor)},
                "points": {"path": str(points), "expected_sha256": sha256_file(points)},
                "plugin": {"name": self.name, "version": self.version},
            }
            (attempt / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
            env = {**os.environ, "PYTHONUTF8": "1"}
            with open(attempt / "worker.log", "wb") as log:
                proc = subprocess.Popen(
                    [sys.executable, str(HERE / "worker.py"), str(attempt / "job.json")],
                    stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(attempt), env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            (attempt / "pid.txt").write_text(str(proc.pid), encoding="ascii")
        except Exception as err:
            self._fail(ctx, f"第 {n} 次没能启动：{type(err).__name__}: {err}")

    def _fail(self, ctx, error: str, raw: str = "") -> None:
        ctx.task(TASK, "失败")
        ctx.problem(error, task=TASK, raw=raw)
        ctx.finish()

    def start(self, ctx):
        self._launch(ctx)

    def retry(self, ctx):
        """设置不变，重新出一次。上一次的产出留着，新的写进新的文件夹。"""
        self._launch(ctx)

    def poll(self, ctx):
        attempts = self._attempts(ctx)
        now = ctx.tasks().get(TASK)
        if not attempts or not now or now["state"] not in ("排队", "运行"):
            return
        attempt = attempts[-1]
        status_file = attempt / "status.json"
        status = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else {}
        state = status.get("state")
        if state == "完成":
            r = status["result"]
            ctx.provenance(**r["provenance"], 第几次=int(attempt.name))
            for p in r["problems"]:  # 没出数的点：记下来，不拦别的点
                ctx.problem(p["error"], task=TASK, raw=p["raw"])
            what = f"{r['n_good']}/{r['n_points']} 个点出了数，目标：{'、'.join(r['targets'])}，不确定度：{r['uncertainty']}"
            ctx.output("预测", r["json"], what=what)
            ctx.output("预测表", r["csv"], what="同一份内容的平表")
            ctx.task(TASK, "完成")
            ctx.finish()
        elif state == "失败":
            self._fail(ctx, status.get("error", "后台进程报了失败，没写原因"), status.get("raw", ""))
        else:
            pid = int((attempt / "pid.txt").read_text(encoding="ascii")) if (attempt / "pid.txt").exists() else 0
            if not pid_alive(pid) and not self._settled(status_file):
                log = (attempt / "worker.log").read_text(encoding="utf-8", errors="replace")[-4000:] if (attempt / "worker.log").exists() else ""
                self._fail(ctx, "后台进程没了，没有留下结果", raw=log)
            elif state == "运行" and (now["state"], now["stage"]) != ("运行", status.get("stage", "")):
                ctx.task(TASK, "运行", stage=status.get("stage", ""))

    @staticmethod
    def _settled(status_file: Path) -> bool:
        try:
            return json.loads(status_file.read_text(encoding="utf-8")).get("state") in ("完成", "失败")
        except (OSError, ValueError):
            return False

    def stop(self, ctx):
        attempts = self._attempts(ctx)
        now = ctx.tasks().get(TASK)
        if not attempts or not now or now["state"] not in ("排队", "运行"):
            return
        pid_file = attempts[-1] / "pid.txt"
        pid = int(pid_file.read_text(encoding="ascii")) if pid_file.exists() else 0
        if pid_alive(pid):
            os.kill(pid, signal.SIGTERM)
        ctx.task(TASK, "停止")


PLUGIN = ScalarPredict()
