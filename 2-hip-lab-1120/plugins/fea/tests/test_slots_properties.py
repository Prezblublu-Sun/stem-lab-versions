"""求解槽的属性测试（《修改目标》02）。属性测试是什么，见 tests/properties.py。

run.py 怎么占槽、起进程、交接、放槽，放在一个替身的世界里试：进程是一张表（在不在、是哪一步起的、杀不杀得掉），
时间是一只拨得快的钟，“操作台”是在槽上签名的那个进程。真的文件锁、真的槽文件、真的 state.json 都照常读写。

随机生成一串事：某个实验往前推一遍、每个实验都推一遍、停止某个实验（可能做到一半操作台断掉）、
某个进程算完了（偶尔是自己崩了）、某一步的进程一齐算完、时间过去几个小时、某个进程杀不掉。
每一件事之后都看：同时在跑的建模不超过建模槽，求解不超过求解槽。

《修改目标》02 查出过三处漏洞，2026-11-16 改好了。随机的那几台各自专碰一处（会断的、杀不掉的、后处理算槽的），
另外每处都写了固定的情形（不靠随机碰），守着它们不再回来：
    交接以前断开     起来以后、交接以前操作台断掉，槽看起来是空的，别的作业能占走它
    收进程不确认     超时、停止时收进程没确认真的收掉了，进程还在，槽已经放掉了
    后处理不占槽     build_slots 管同时建模、后处理的作业最多几个，后处理起进程时却不占槽
还有一条“求解器自己结束了、它起的子进程还在算”（注释审查 中 4）。最后一条拿真的进程把交接以前断掉那一处再演一遍。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time as real_time
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule, run_state_machine_as_test

from plugins.fea import run
from stemlab import hooks
from tests import properties  # noqa: F401  载入 Hypothesis 的设置

REPO = Path(__file__).resolve().parents[3]
EXPLORE = os.environ.get("STEMLAB_HYPOTHESIS") == "explore"
STATEFUL = settings(max_examples=600 if EXPLORE else 60, stateful_step_count=40 if EXPLORE else 30, deadline=None)
EXPERIMENTS = ("E0001", "E0002")
TASKS = ("a", "b")


class DeskCrash(BaseException):
    """操作台在这里断掉了：进程被杀、机器断电。不是 Exception，run.py 里接 Exception 的地方接不住它，和真的断掉一样。"""


class World:
    """替身的世界：进程表、钟、操作台。patch 把 run.py 用到的这几样换成它，unpatch 换回来。"""

    def __init__(self, root: Path, solve_slots: int, build_slots: int):
        self.root, self.solve_slots, self.build_slots = Path(root), solve_slots, build_slots
        self.clock = 1_000_000.0
        self.table: dict[int, dict] = {}            # 进程号 -> stage、folder、alive、stubborn、created
        self.next_pid = 100
        self.crash_in = None                        # 再落几次盘就断；None 是不断
        self.cut_before_handover = False            # 起来以后、交接以前断
        self.desk = self.start("desk", None)
        self.setting = {"build_slots": build_slots, "build_timeout_s": 3600, "solve_timeout_s": 21600}
        self.saved: dict = {}
        self.said: list[tuple] = []                 # run.py 经 handle.problem 说出来的：（任务，说了什么）

    # ---- 进程表
    def start(self, stage: str, folder) -> dict:
        self.next_pid += 1
        self.table[self.next_pid] = {"stage": stage, "folder": folder, "alive": True, "stubborn": False, "created": self.clock}
        return {"pid": self.next_pid, "created": self.clock}

    def alive(self, process) -> bool:
        found = self.table.get(process.get("pid")) if isinstance(process, dict) else None
        return bool(found and found["alive"] and found["created"] == process.get("created"))

    def kill(self, process) -> None:
        found = self.table.get(process.get("pid")) if isinstance(process, dict) else None
        if found and found["created"] == process.get("created") and not found["stubborn"]:
            found["alive"] = False

    def running(self, *stages) -> list[int]:
        return sorted(pid for pid, found in self.table.items() if found["alive"] and found["stage"] in stages)

    def end(self, pid: int, with_result: bool = True) -> None:
        """一个进程结束了。建模、后处理算完了留下结果；with_result 是 False 就是它自己崩了，什么都没留下。"""
        found = self.table[pid]
        if with_result and found["stage"] in ("build", "post"):
            where = found["folder"] / found["stage"]
            where.mkdir(parents=True, exist_ok=True)
            said = {"status": "built", "solve": {"command": ["{python}", "-c", "pass"]}} if found["stage"] == "build" else {"status": "ok"}
            (where / "result.json").write_bytes(json.dumps(said).encode("utf-8"))
        found["alive"] = False

    # ---- 起进程：建模和后处理经 run_kernel，求解经 spawn
    def tick(self) -> None:
        """又落了一次盘、又起了一个进程。到了该断的时候就断。"""
        if self.crash_in is not None:
            self.crash_in -= 1
            if self.crash_in <= 0:
                self.crash_in = None
                raise DeskCrash

    def run_kernel(self, kernel_id, ask, out, wait=False) -> dict:
        process = self.start(Path(out).name, Path(out).parent)
        self.tick()
        return process

    def spawn(self, command, cwd=None, env=None, log=None) -> dict:
        process = self.start("solve", Path(env[run.MARK]))
        self.tick()
        return process

    def desk_run(self, action, cut=None) -> None:
        """操作台做一件事。cut 说在哪里断掉：一个数是第几次落盘之后，"handover" 是起来以后、交接以前；None 是不断。
        断了，操作台这个进程就没了，换一个新的接着来。"""
        self.crash_in = cut if isinstance(cut, int) else None
        self.cut_before_handover = cut == "handover"
        try:
            action()
        except DeskCrash:
            self.table[self.desk["pid"]]["alive"] = False
            self.desk = self.start("desk", None)
        finally:
            self.crash_in, self.cut_before_handover = None, False

    # ---- 实验
    def handle(self, experiment: str):
        inputs = {"export": self.setting, "bone": str(self.root / "bone")}
        return SimpleNamespace(experiment=experiment, work_dir=self.root / "work" / experiment, round=SimpleNamespace(number=1),
                               input=inputs.__getitem__, input_info=lambda name: SimpleNamespace(id="R0001"),
                               machines=(SimpleNamespace(name="desk", role="desk", slots=self.solve_slots),),
                               problem=lambda error, task=None, raw=None: self.said.append((task, error)))

    @staticmethod
    def jobs(*tasks) -> list[dict]:
        return [{"task": task, "point": {"name": task, "bone_id": "femur042", "design": {}, "conditions": {}}} for task in tasks]

    # ---- 换上、换回
    def patch(self) -> None:
        names = ("hooks", "_me", "time", "psutil", "_save", "_write", "_strays", "_hold")
        self.saved = {name: getattr(run, name) for name in names}
        save, write, hold = run._save, run._write, run._hold

        def held(slot, process, note):
            if self.cut_before_handover:
                self.cut_before_handover = False
                raise DeskCrash
            hold(slot, process, note)

        run.hooks = SimpleNamespace(alive=self.alive, kill=self.kill, spawn=self.spawn, run_kernel=self.run_kernel)
        run._me = lambda: dict(self.desk)
        run.time = SimpleNamespace(time=lambda: self.clock, monotonic=real_time.monotonic, sleep=real_time.sleep)
        run.psutil = SimpleNamespace(wait_procs=lambda found, timeout=None: ([], []), boot_time=lambda: 0.0, Error=Exception)
        run._save = lambda folder, state: (save(folder, state), self.tick())[0]
        run._write = lambda path, body: (write(path, body), self.tick())[0]
        run._strays = lambda folder, stage, root=None: [SimpleNamespace(pid=pid, kill=lambda pid=pid: self.kill(
            {"pid": pid, "created": self.table[pid]["created"]})) for pid in self.running(stage) if self.table[pid]["folder"] == folder]
        run._hold = held

    def unpatch(self) -> None:
        for name, value in self.saved.items():
            setattr(run, name, value)


# ---------------------------------------------------------------- 随机的一串事

CUTS = st.none() | st.just("handover") | st.integers(1, 8)        # 不断；起来以后、交接以前断；第几次落盘之后断


class Slots(RuleBasedStateMachine):
    """两个实验各两个作业，共用一组槽。子类决定会出哪些岔子、看哪几句话；槽数要写死的，子类换一个 setup。"""
    crashes = False         # 操作台会不会做到一半断掉
    stubborn = False        # 会不会有杀不掉的进程
    count_post = False      # 后处理算不算在建模槽里

    def __init__(self):
        super().__init__()
        self.root = Path(tempfile.mkdtemp(prefix="stemlab-slots-"))
        self.kept = os.environ.get("STEMLAB_SLOTS")
        os.environ["STEMLAB_SLOTS"] = str(self.root / "slots")
        self.world = None

    @initialize(solve=st.integers(1, 2), build=st.integers(1, 2))
    def setup(self, solve, build):
        self.world = World(self.root, solve, build)
        self.world.patch()
        self.handles = {name: self.world.handle(name) for name in EXPERIMENTS}
        for handle in self.handles.values():
            run.begin(handle, World.jobs(*TASKS))

    def teardown(self):
        if self.world is not None:
            self.world.unpatch()
        if self.kept is None:
            os.environ.pop("STEMLAB_SLOTS", None)
        else:
            os.environ["STEMLAB_SLOTS"] = self.kept
        shutil.rmtree(self.root, ignore_errors=True)

    def busy(self) -> list[int]:
        return self.world.running("build", "solve", "post") if self.world is not None else []

    @rule(which=st.sampled_from(EXPERIMENTS), cut=CUTS)
    def push(self, which, cut):
        self.world.desk_run(lambda: run.advance(self.handles[which], World.jobs(*TASKS)), cut if self.crashes else None)

    @rule(cut=CUTS)
    def push_every_experiment(self, cut):
        """值守看一遍：每个实验往前推一遍。cut 只用在第一个实验上：断掉之后，换上来的操作台接着推后面的。"""
        for which in EXPERIMENTS:
            here = cut if self.crashes and which == EXPERIMENTS[0] else None
            self.world.desk_run(lambda which=which: run.advance(self.handles[which], World.jobs(*TASKS)), here)

    @rule(which=st.sampled_from(EXPERIMENTS), cut=CUTS)
    def stop(self, which, cut):
        self.world.desk_run(lambda: run.halt(self.handles[which], World.jobs(*TASKS)), cut if self.crashes else None)

    @precondition(lambda self: bool(self.busy()))
    @rule(data=st.data(), with_result=st.sampled_from((True, True, True, False)))     # 多半是算完了，偶尔是自己崩了
    def a_process_ends(self, data, with_result):
        self.world.end(data.draw(st.sampled_from(self.busy())), with_result)

    @precondition(lambda self: bool(self.busy()))
    @rule(stage=st.sampled_from(("build", "solve", "post")))
    def every_process_of_a_stage_ends(self, stage):
        """这一步在跑的进程一齐算完，都留下结果。"""
        for pid in self.world.running(stage):
            self.world.end(pid)

    @precondition(lambda self: self.stubborn and bool(self.busy()))
    @rule(data=st.data())
    def a_process_cannot_be_killed(self, data):
        self.world.table[data.draw(st.sampled_from(self.busy()))]["stubborn"] = True

    @rule(hours=st.sampled_from((1, 2, 7)))
    def time_passes(self, hours):
        self.world.clock += hours * 3600.0

    @invariant()
    def never_more_running_than_slots(self):
        if self.world is None:
            return
        world = self.world
        assert len(world.running("solve")) <= world.solve_slots, f"求解：{len(world.running('solve'))} 个在跑，{world.solve_slots} 个槽"
        assert len(world.running("build")) <= world.build_slots, f"建模：{len(world.running('build'))} 个在跑，{world.build_slots} 个槽"
        if self.count_post:
            together = len(world.running("build", "post"))
            assert together <= world.build_slots, f"建模加后处理：{together} 个在跑，{world.build_slots} 个槽"


class WithoutTrouble(Slots):
    pass


class PostCounted(Slots):
    count_post = True

    @initialize(solve=st.just(2), build=st.just(1))     # 两个求解槽、一个建模槽：两个作业一起求解完，就一起进后处理
    def setup(self, solve, build):
        super().setup(solve, build)


class CrashingDesk(Slots):
    crashes = True

    @initialize(solve=st.just(1), build=st.integers(1, 2))      # 一个求解槽：交接以前断掉，别的作业一占就多出一个
    def setup(self, solve, build):
        super().setup(solve, build)


class StubbornProcesses(Slots):
    stubborn = True


def test_without_trouble_running_processes_never_outnumber_the_slots():
    run_state_machine_as_test(WithoutTrouble, settings=STATEFUL)


def test_post_processing_counts_against_the_build_slots():
    run_state_machine_as_test(PostCounted, settings=STATEFUL)


def test_a_desk_dying_anywhere_never_lets_more_processes_run_than_slots():
    run_state_machine_as_test(CrashingDesk, settings=STATEFUL)


def test_processes_that_cannot_be_killed_never_lose_their_slot():
    run_state_machine_as_test(StubbornProcesses, settings=STATEFUL)


# ---------------------------------------------------------------- 已经知道的几处，写死的情形

@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("STEMLAB_SLOTS", str(tmp_path / "slots"))
    made = World(tmp_path, solve_slots=1, build_slots=2)
    made.patch()
    yield made
    made.unpatch()


def built(world: World, *pairs) -> None:
    """几个作业各自建好模：往前推一遍起建模，建模算完。pairs 是（实验，作业）。"""
    for experiment, task in pairs:
        run.begin(world.handle(experiment), World.jobs(task))
        world.desk_run(lambda experiment=experiment, task=task: run.advance(world.handle(experiment), World.jobs(task)))
    for pid in world.running("build"):
        world.end(pid)


def arranged(condition: bool, what: str) -> None:
    """情形本身的前提。没成是情形没搭起来，不是要证明的那一处：用 pytest.fail，xfail(raises=AssertionError) 不把它当成预料之中。"""
    if not condition:
        pytest.fail(f"情形没搭起来：{what}")


def test_a_desk_dying_between_launch_and_handover_lets_no_second_solve_in(world):
    """槽文件里记的还是断掉的操作台，a 的求解却在跑：认得出是 a 起的，槽照占着算。"""
    built(world, ("E0001", "a"), ("E0002", "b"))
    world.desk_run(lambda: run.advance(world.handle("E0001"), World.jobs("a")), "handover")     # a 的求解起来了，交接以前操作台断了
    arranged(len(world.running("solve")) == 1, "a 的求解起来了")
    world.desk_run(lambda: run.advance(world.handle("E0002"), World.jobs("b")))         # 新的操作台推 b：槽看起来是空的
    assert len(world.running("solve")) <= 1, "一个求解槽，两个求解进程同时在跑"


@pytest.mark.parametrize("how", ["timeout", "stop"])
def test_a_solve_that_cannot_be_ended_keeps_its_slot(world, how):
    """超时、停止都要确认收掉了才放槽。收不掉的槽不放，并且说出来。"""
    built(world, ("E0001", "a"), ("E0002", "b"))
    world.desk_run(lambda: run.advance(world.handle("E0001"), World.jobs("a")))
    (pid,) = world.running("solve")
    world.table[pid]["stubborn"] = True
    if how == "timeout":
        world.clock += 7 * 3600.0                                                       # 超过求解的时限（6 小时）
        world.desk_run(lambda: run.advance(world.handle("E0001"), World.jobs("a")))
    else:
        world.desk_run(lambda: run.halt(world.handle("E0001"), World.jobs("a")))
    world.desk_run(lambda: run.advance(world.handle("E0002"), World.jobs("b")))
    assert len(world.running("solve")) <= 1, "杀不掉的那个还在跑，它的槽已经给了别人"
    assert [task for task, _ in world.said] == ["a"], f"收不掉要说出来，只说一次：{world.said}"


def test_a_solve_whose_own_process_ended_while_its_child_still_runs_keeps_its_slot(world):
    """求解器自己结束了，它起的子进程（比如 Abaqus）还在算，带着作业的标记：槽不放，也不进后处理。"""
    built(world, ("E0001", "a"), ("E0002", "b"))
    world.desk_run(lambda: run.advance(world.handle("E0001"), World.jobs("a")))
    (root,) = world.running("solve")
    child = world.start("solve", world.table[root]["folder"])["pid"]       # 求解器起的子进程
    world.end(root)
    world.desk_run(lambda: run.advance(world.handle("E0001"), World.jobs("a")))
    world.desk_run(lambda: run.advance(world.handle("E0002"), World.jobs("b")))
    assert world.running("solve") == [child], "a 的子进程还在算，b 的求解不能起"
    assert not world.running("post"), "a 的求解还没算完，不进后处理"
    world.end(child)
    world.desk_run(lambda: run.advance(world.handle("E0001"), World.jobs("a")))
    assert len(world.running("post")) == 1, "子进程也算完了，a 进后处理"


def test_two_post_processings_do_not_run_on_one_build_slot(tmp_path, monkeypatch):
    """后处理和建模共用建模槽：一个建模槽，两个作业一起求解完，后处理也只能一个一个来。"""
    monkeypatch.setenv("STEMLAB_SLOTS", str(tmp_path / "slots"))
    world = World(tmp_path, solve_slots=2, build_slots=1)
    world.patch()
    try:
        for experiment, task in (("E0001", "a"), ("E0002", "b")):          # 一个建模槽：轮流建模
            run.begin(world.handle(experiment), World.jobs(task))
            world.desk_run(lambda experiment=experiment, task=task: run.advance(world.handle(experiment), World.jobs(task)))
            for pid in world.running("build"):
                world.end(pid)
        for experiment, task in (("E0001", "a"), ("E0002", "b")):          # 两个都去求解（两个求解槽）
            world.desk_run(lambda experiment=experiment, task=task: run.advance(world.handle(experiment), World.jobs(task)))
        for pid in world.running("solve"):
            world.end(pid)
        for experiment, task in (("E0001", "a"), ("E0002", "b")):          # 两个都进后处理
            world.desk_run(lambda experiment=experiment, task=task: run.advance(world.handle(experiment), World.jobs(task)))
        assert len(world.running("build", "post")) <= 1, "一个建模槽，两个后处理同时在跑"
    finally:
        world.unpatch()


# ---------------------------------------------------------------- 真的进程

CUT = """
import os, sys
from plugins.fea import run
from stemlab import hooks
folder, sleeper = sys.argv[1], sys.argv[2]
slot = run._claim("solve", 1, {"experiment": "E0001", "task": "a", "folder": folder, "stage": "solve"})    # 照 run.py 占槽
process = hooks.spawn([sys.executable, "-c", sleeper], env=dict(os.environ, **{run.MARK: folder}))
print(f"{process['pid']} {process['created']!r}", flush=True)
os._exit(9)                                     # 起来以后、交接以前断掉
"""


def test_with_real_processes_a_desk_dying_before_handover_lets_no_second_solve_in(tmp_path, monkeypatch):
    slots = tmp_path / "slots"
    monkeypatch.setenv("STEMLAB_SLOTS", str(slots))
    sleeper = "import time; time.sleep(120)"
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", STEMLAB_SLOTS=str(slots))
    done = subprocess.run([sys.executable, "-c", CUT, str(tmp_path / "a"), sleeper], cwd=REPO, env=env, capture_output=True, timeout=120)
    arranged(done.returncode == 9, "起进程的那个操作台在交接以前断掉了：" + done.stderr.decode("utf-8", "replace"))
    pid, created = done.stdout.decode("utf-8").split()
    started = [{"pid": int(pid), "created": float(created)}]
    try:
        if run._claim("solve", 1, {"experiment": "E0002", "task": "b"}):          # 这台操作台接着来：槽看起来是空的
            started.append(hooks.spawn([sys.executable, "-c", sleeper]))
        assert len([one for one in started if hooks.alive(one)]) <= 1, "一个求解槽，两个求解进程同时在跑"
    finally:
        for one in started:
            hooks.kill(one)
