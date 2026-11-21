"""定时值守：隔一会儿叫一次所有运行中实验的插件报任务状态。

放在操作台这一边，仪表盘不做这件事。
它自己不认识任何插件，只是定时叫操作台的「刷新」。

一个 home 同一时刻只有一处在值守：谁先拿到 experiments/.watch 这把锁谁做，
别处的值守等着，那一处退出后自己接上。
"""
from __future__ import annotations

import threading

from .record import Busy, now


class Watch:
    def __init__(self, get_desk, every: float = 15.0):
        """get_desk：每次值守时取现在的操作台（操作台重新读插件后会换一个）。"""
        self.get_desk = get_desk
        self.every = float(every)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._held = None  # 拿到的值守锁
        self._guard = threading.Lock()
        self._state = {
            "on": False,  # 值守有没有在跑
            "every": self.every,
            "holding": False,  # 这一处有没有拿到值守锁
            "elsewhere": None,  # 别处在值守时，那个进程的进程号
            "rounds": 0,
            "last_time": "",
            "last_seen": [],  # 上一次看过的实验
            "last_error": "",
            "unreadable": {},  # 上一次读不了记录的实验
        }

    # ---- 状态 ---------------------------------------------------------

    def status(self) -> dict:
        with self._guard:
            return dict(self._state)

    def _set(self, **items) -> None:
        with self._guard:
            self._state.update(items)

    # ---- 值守锁 -------------------------------------------------------

    def _hold(self) -> bool:
        if self._held:
            return True
        store = self.get_desk().store
        if not store.root.exists():  # 还没有任何实验，没有东西要看
            self._set(holding=False, elsewhere=None)
            return False
        lock = store.watch_lock()
        try:
            lock.__enter__()
        except Busy:
            self._set(holding=False, elsewhere=lock.holder())
            return False
        self._held = lock
        self._set(holding=True, elsewhere=None)
        return True

    def _release(self) -> None:
        if self._held:
            self._held.__exit__(None, None, None)
            self._held = None
        self._set(holding=False)

    # ---- 值守 ---------------------------------------------------------

    def round(self) -> list[str] | None:
        """值守一次。返回看过的实验；别处在值守、或还没有实验时返回 None。"""
        if not self._hold():
            return None
        desk = self.get_desk()
        try:
            seen, error = desk.refresh(), ""
        except Exception as err:  # 出问题是正常的：记下，下一次接着看
            seen, error = [], f"{type(err).__name__}: {err}"
        with self._guard:
            self._state.update(
                rounds=self._state["rounds"] + 1,
                last_time=now(),
                last_seen=seen,
                last_error=error,
                unreadable=dict(getattr(desk, "refresh_errors", {})),
            )
        return seen

    def run(self, on_round=None, rounds: int | None = None) -> None:
        """一直值守，直到 stop() 或做满 rounds 次。每次之后叫 on_round(状态)。"""
        self._set(on=True)
        try:
            done = 0
            while True:
                self.round()
                done += 1
                if on_round:
                    on_round(self.status())
                if rounds is not None and done >= rounds:
                    break
                if self._stop.wait(self.every):
                    break
        finally:
            self._release()
            self._set(on=False)

    def start(self) -> None:
        """在后台值守。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name="stemlab-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=120)
            self._thread = None
        self._release()
