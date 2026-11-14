"""示范插件报的类型。相当于真插件里冻结的 plugin.py：三张表和动作都写在这里，怎么算在 free.py。"""
from stemlab.hooks import Chart, Input, Kind, Outcome, Output
from tests.plugins.demo import free

SETTING = Input("setting", ("setting",), label="设定")
EXTRA = Input("extra", ("report", "edits", "bone_source"), many=True, required=False, label="附带的")
OUTCOMES = (
    Outcome("finished", "ok", "算完"),
    Outcome("misfit", "conclusion", "放不进去"),
    Outcome("env", "retryable", "环境问题"),
    Outcome("diverged", "unclear", "不收敛"),
)

KINDS = [
    Kind(
        name="demo.echo",
        label="示范：在调用里直接做完",
        inputs=(SETTING, EXTRA),
        outputs=(Output("report", "report", "报告"), Output("second", "report", "第二份报告")),
        outcomes=OUTCOMES,
        check=free.check, start=free.start, poll=free.poll, stop=free.stop,
        charts=(Chart("tasks", "table", "各任务"),), chart=free.chart,
    ),
    Kind(
        name="demo.quiet",
        label="示范：没有写停止的类型，它自己会结束",
        inputs=(SETTING, EXTRA),
        outputs=(Output("report", "report", "报告"), Output("second", "report", "第二份报告")),
        outcomes=OUTCOMES,
        check=free.check, start=free.start, poll=free.poll,
    ),
    Kind(
        name="demo.pack",
        label="示范：跑一个带代码的包",
        inputs=(SETTING, Input("tool", ("kernel", "strategy", "derive_def", "predictor"), label="带代码的包")),
        outputs=(Output("report", "report", "报告"),),
        outcomes=OUTCOMES,
        check=free.sleep_check, start=free.pack_start, poll=free.pack_poll,
    ),
    Kind(
        name="demo.remote",
        label="示范：把活派到远端的 worker",
        inputs=(SETTING,),
        outputs=(Output("report", "report", "报告"),),
        outcomes=OUTCOMES,
        check=free.sleep_check, start=free.remote_start, poll=free.remote_poll, stop=free.remote_stop,
        where="worker",
    ),
    Kind(
        name="demo.sleep",
        label="示范：把活派给一个脱离出去的本机进程",
        inputs=(SETTING,),
        outputs=(Output("report", "report", "报告"),),
        outcomes=OUTCOMES,
        check=free.sleep_check, start=free.sleep_start, poll=free.sleep_poll, stop=free.sleep_stop,
    ),
]
