"""标量预测器的训练插件：用一份标签表训练标量预测器，出误差报告。只在本机 CPU 上算。

启动时把设置写成一份 job.json，起一个后台进程（worker.py）去算，马上返回。
之后每次 poll 读后台进程写的 status.json，把走到哪一步报进实验记录。
做完时登记两样产出：预测器、误差报告。

场预测器（整体应变场）不在这个插件里，没有做。
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
TASK = "训练"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def as_value(x):
    """一项设置可以是手填的值，也可以是一个内容是 JSON 的文件。"""
    if isinstance(x, Path):
        return json.loads(x.read_text(encoding="utf-8-sig"))
    return x


class ScalarTrain(Plugin):
    name = "scalar-train"
    version = "0.1"
    category = "代理"
    what = "用一份标签表训练标量预测器（高斯过程或随机森林），出误差报告。本机 CPU"

    settings = [
        Setting("训练数据", what="一份标签表：平的 CSV，一行一个 FE 作业。用「只记位置」填，记位置和哈希，不复制"),
        Setting(
            "数据怎么读",
            what='用哪些行、哪几列是骨、设计、条件。例：{"行的名字": "row_id", "行的筛选": {"status": "DONE", "kind": "design", '
            '"has_fric_model": "true"}, "最多用几行": null, "骨": "femur_id", "设计": ["L", "alpha", "h_cut", "m", "rho_tip", "q", '
            '"lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p"], "条件": ["delta_mm"]}',
        ),
        Setting(
            "预测目标",
            what='预测哪几列（标量）。例：[{"列": "rot_first_deg", "变换": "log10"}, "contact_area_load2_mm2"]。变换只有 log10 或不写',
        ),
        Setting(
            "模型和训练配置",
            what='例：{"模型种类": "高斯过程", "核": "Matern52", "重启次数": 3} 或 {"模型种类": "随机森林", "树的棵数": 300}。'
            '可以加 "误差指标": ["R2", "RMSE", "MAE", "相对误差", "秩相关"]，不写就全算',
        ),
        Setting(
            "划分",
            what='训练和留出怎么分。三种：{"种类": "留出", "留出比例": 0.2, "分组列": "design_key"}；'
            '{"种类": "k 折", "折数": 5, "分组列": "design_key"}；{"种类": "按列", "列": "split", "留出的值": ["test"]}。'
            "留出的行不进训练。k 折报的是交叉验证误差，不是留出误差",
        ),
        Setting("随机种子", what="一个不小于 0 的整数。同设置同种子重跑，误差报告逐数相同"),
    ]
    outputs = [
        Output("预测器", what="一个 zip 文件：说明、模型、哈希。给出预测插件当设置"),
        Output("误差报告", what="JSON：用的哪种划分、哪些指标、数据哈希、训练行、每个目标的误差、逐行的预测"),
    ]

    # ---- 每启动或重试一次是一「次」，各有自己的文件夹，互不覆盖 ----

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
            data = ctx.setting("训练数据")
            if not isinstance(data, Path):
                raise ValueError("「训练数据」要是一个文件（用「只记位置」或「复制文件」填），不是一个值。")
            job = {
                "attempt_dir": str(attempt),
                "out_dir": str(ctx.outputs_dir / str(n)),
                "data": {"path": str(data), "expected_sha256": sha256_file(data)},
                "read": as_value(ctx.setting("数据怎么读")),
                "targets": as_value(ctx.setting("预测目标")),
                "model": as_value(ctx.setting("模型和训练配置")),
                "split": as_value(ctx.setting("划分")),
                "seed": as_value(ctx.setting("随机种子")),
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
        except Exception as err:  # 起不来也是一种结局：记下来，这个实验结束
            self._fail(ctx, f"第 {n} 次没能启动：{type(err).__name__}: {err}")

    def _fail(self, ctx, error: str, raw: str = "") -> None:
        ctx.task(TASK, "失败")
        ctx.problem(error, task=TASK, raw=raw)
        ctx.finish()

    # ---- 挂点 ----

    def start(self, ctx):
        self._launch(ctx)

    def retry(self, ctx):
        """设置不变，重新算一次。上一次的产出留着，新的写进新的文件夹。"""
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
            ctx.output("预测器", r["predictor"], what=f"{r['model_kind']}，目标：{'、'.join(r['targets'])}，用 {r['n_train']} 行训练")
            ctx.output("误差报告", r["report"], what=f"{r['error_name']}，划分：{r['split_kind']}，{r['n_held']} 行")
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
        """进程刚退出的那一下再读一次，免得把「刚写完结果就退出」看成「没留下结果」。"""
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

    # 暂停和继续用默认的：暂停期间操作台不来看，后台进程照常算；继续之后接着报。


PLUGIN = ScalarTrain()
