"""【冻结】一个作业结束后归到哪个结局名。

    结局名          类别        什么时候
    finished        ok          算完，推导量也算出来了
    misfit          conclusion  放不进去：建模之前的模板化就判定这个设计在这根骨上放不下
    unstable        conclusion  不收敛，而且求解停下之前柄已经明显松动（内核给得出证据）
    not_converged   unclear     不收敛，没有松动的证据
    mesh_failed     unclear     网格失败：内核把它自己的几档备选设置都试过了
    env             retryable   环境问题：许可、机器重启这类和点无关的偶发问题
    error           unclear     内核自己出错、超时、结果读不出来

“不收敛”和“网格失败”为什么归待查（2026-11-13 定，依据见 docs/四样的决定.md）：
    这两样都能原样复现，但它们是“这个点 × 这一份数值设置”的性质，不是设计在力学上不可行的证据。
    类别 conclusion 的意思是优化可以把它当不可行的证据，所以不能直接归过去：
    网格失败和力学无关，而且会落在最优区旁边；不收敛可能只是接触迭代的数值问题。
    只有一种不收敛算结论：求解是在加载步里停下的，而且停下之前界面的相对位移已经超过
    骨长入的失败阈值。载荷还没加满就已经松到这个程度，加满只会更松，这个设计的结论不依赖数值收敛。
    这一条由内核判断并给出证据，报成 unstable。

类别对应的任务状态和进不进数据，是契约定的：ok 和 conclusion 是完成、进数据；另两类是失败、不进。
"""
from stemlab.hooks import Outcome

OUTCOMES = (
    Outcome("finished", "ok", "算完"),
    Outcome("misfit", "conclusion", "放不进去"),
    Outcome("unstable", "conclusion", "不收敛，停下之前柄已经松动"),
    Outcome("not_converged", "unclear", "不收敛"),
    Outcome("mesh_failed", "unclear", "网格失败"),
    Outcome("env", "retryable", "环境问题"),
    Outcome("error", "unclear", "内核出错"),
)
CATEGORY = {row.name: row.category for row in OUTCOMES}
LABEL = {row.name: row.label for row in OUTCOMES}
TASK_STATE = {"ok": "done", "conclusion": "done", "retryable": "failed", "unclear": "failed"}     # 类别 -> 任务的状态
IN_DATA = ("ok", "conclusion")                                                                    # 进数据的类别

# 内核报的 status -> 结局名。表里没有的 status 一律是 error
FROM_BUILD = {"misfit": "misfit", "mesh_failed": "mesh_failed", "env": "env"}
FROM_POST = {"ok": "finished", "unstable": "unstable", "not_converged": "not_converged", "env": "env"}
LOST = {"restart": ("env", "机器重启过，这个作业的进程没了"),
        "timeout": ("error", "超过了内核给的时限，已经把它结束了"),
        "crashed": ("error", "进程结束了，却没有留下结果")}

NUMERICAL = ("not_converged", "mesh_failed")    # 数值上没算出来的两种。占比高了要先查模型，不是绕着走
RATE_LINE = 0.05                                # 一轮里它们占到多少就提醒
RATE_COUNT = 2                                  # 而且至少有几个


def classify(result: dict) -> tuple[str, str]:
    """一个结束了的作业归到哪个结局名。返回（结局名，原因）。

    result 是自由代码交上来的：build、post 是内核两次的 result（没走到就是 None），
    derived 是推导量（没算出来就是 None），lost 说这个作业的进程是怎么没的（没有这回事就是 None）。
    """
    if result.get("lost"):
        return LOST.get(result["lost"], ("error", f"作业没了：{result['lost']}"))
    build = result.get("build")
    if not isinstance(build, dict):
        return "error", "内核建模没有留下结果"
    if build.get("status") != "built":
        return FROM_BUILD.get(build.get("status"), "error"), _reason(build, "建模")
    post = result.get("post")
    if not isinstance(post, dict):
        return "error", "内核后处理没有留下结果"
    name = FROM_POST.get(post.get("status"), "error")
    if name == "finished" and not isinstance(result.get("derived"), dict):
        return "error", "FE 算完了，但推导量没有算出来"
    return name, _reason(post, "后处理")


def _reason(said: dict, stage: str) -> str:
    text = said.get("reason")
    return text if isinstance(text, str) and text.strip() else f"内核{stage}报的是 {said.get('status')!r}，没有说原因"


def task_state(name: str) -> str:
    """带这个结局的任务是什么状态。"""
    return TASK_STATE[CATEGORY[name]]


def in_data(name) -> bool:
    """带这个结局的任务进不进数据。"""
    return CATEGORY.get(name) in IN_DATA


def too_many_numerical(names) -> str | None:
    """这一轮里数值上没算出来的作业是不是多到该先查模型了。是就返回一句提醒，不是返回 None。"""
    names = list(names)
    failed = [name for name in names if name in NUMERICAL]
    if len(failed) >= RATE_COUNT and len(failed) > RATE_LINE * len(names):
        return (f"这一轮 {len(names)} 个作业里有 {len(failed)} 个是不收敛或网格失败（{len(failed) / len(names):.0%}，"
                f"线是 {RATE_LINE:.0%}）。先查模型和设置，别让选点只是绕着这些点走")
    return None
