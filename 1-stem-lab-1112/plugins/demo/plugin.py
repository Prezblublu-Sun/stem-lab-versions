"""示范插件：什么都不算，只用来走通地基。

吃一批点，每个点一个任务。每叫一次 poll，每个任务往前走一格：
排队 → 运行 → 完成。写在「出错的点」里的点会失败，别的点照常完成。
全部结束后产出一份「点清单」，里面是完成了的点。
"""
import json
from pathlib import Path

from stemlab.plugins import Output, Plugin, Setting


class Demo(Plugin):
    name = "demo"
    version = "0.1"
    category = "示范"
    what = "什么都不算，只用来走通地基"

    settings = [
        Setting("点", required=True, what="一批点：一个名字的列表，或一个内容是这种列表的 JSON 文件"),
        Setting("出错的点", required=False, what="哪些点要故意失败：一个名字的列表"),
    ]
    outputs = [Output("点清单", what="完成了的点，JSON 列表")]

    def _points(self, ctx) -> list[str]:
        points = ctx.setting("点")
        if isinstance(points, Path):
            points = json.loads(points.read_text(encoding="utf-8"))
        return [str(p) for p in points]

    def start(self, ctx):
        ctx.provenance(示范插件说="这一条是插件自己加的来历")
        for point in self._points(ctx):
            ctx.task(point, "排队")

    def poll(self, ctx):
        bad = [str(p) for p in (ctx.setting("出错的点") or [])]
        for name, t in ctx.tasks().items():
            if t["state"] == "排队":
                ctx.task(name, "运行", stage="假装在算")
            elif t["state"] == "运行":
                if name in bad:
                    ctx.task(name, "失败", stage="假装在算")
                    ctx.problem("这个点被设成故意失败", task=name, raw="demo: point listed in 出错的点")
                else:
                    ctx.task(name, "完成")
        tasks = ctx.tasks()
        if all(t["state"] in ("完成", "失败", "停止") for t in tasks.values()):
            done = [name for name, t in tasks.items() if t["state"] == "完成"]
            ctx.outputs_dir.mkdir(parents=True, exist_ok=True)
            path = ctx.outputs_dir / "点清单.json"
            path.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
            ctx.output("点清单", path, what=f"完成了 {len(done)} 个点")
            ctx.finish()

    def stop(self, ctx):
        for name, t in ctx.tasks().items():
            if t["state"] in ("排队", "运行"):
                ctx.task(name, "停止")

    def retry(self, ctx):
        for name, t in ctx.tasks().items():
            if t["state"] in ("失败", "停止"):
                ctx.task(name, "排队")


PLUGIN = Demo()
