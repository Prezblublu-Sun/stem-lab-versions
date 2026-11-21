"""在设计范围里取设计的几种取法。自由的测试：取法换了，这里跟着换。"""
from __future__ import annotations

import numpy as np
from scipy.stats import qmc

from plugins.opt import feasible, pool

SPACE = {"design": {"length": [20.0, 80.0], "width": [1.0, 3.0], "behave": {"values": ["ok", "odd"]}}, "count": 64, "seed": 5}
CENTER = {"length": 50.0, "width": 2.9, "behave": "odd"}


def unit(made: list, space: dict = SPACE) -> np.ndarray:
    """取出来的设计里两个数值项，各缩放到 0 到 1。"""
    return np.array([[(one["design"][name] - space["design"][name][0]) / (space["design"][name][1] - space["design"][name][0])
                      for name in ("length", "width")] for one in made])


def test_every_way_of_drawing_stays_inside_the_range_and_repeats_with_the_seed():
    for method in pool.METHODS:
        space = dict(SPACE, method=method, centers=[CENTER], spread=0.2)
        assert pool.problems(space) == [] and feasible.range_problems(space) == []
        made = pool.designs(space)
        assert [one["name"] for one in made] == [f"c{number:04d}" for number in range(1, 65)]
        assert all(feasible.inside(one["design"], space) is None for one in made), f"{method} 取出了范围外面的设计"
        assert pool.designs(space) == made, f"{method}：同一份范围、同一个种子，取出来的是同一批"
        assert pool.designs(dict(space, seed=6)) != made, f"{method}：换一个种子是另一批"


def test_not_writing_the_method_is_the_latin_hypercube_and_it_puts_one_design_in_every_slice():
    made = pool.designs(SPACE)
    assert made == pool.designs(dict(SPACE, method="lhs"))
    cells = np.floor(unit(made) * 64).astype(int)
    assert sorted(cells[:, 0]) == list(range(64)) and sorted(cells[:, 1]) == list(range(64)), "每一项上 64 段各有一个"


def test_sobol_covers_the_square_more_evenly_than_drawing_at_random():
    wide = dict(SPACE, count=256)
    even = qmc.discrepancy(unit(pool.designs(dict(wide, method="sobol")), wide))
    loose = np.mean([qmc.discrepancy(unit(pool.designs(dict(wide, method="random", seed=seed)), wide)) for seed in range(1, 6)])
    assert even < 0.5 * loose, (even, loose)


def test_around_keeps_to_the_neighbourhood_of_the_centers_and_lists_them_first():
    other = {"length": 22.0, "width": 1.5, "behave": "ok"}
    made = pool.designs(dict(SPACE, method="around", centers=[CENTER, other], spread=0.1, count=41))
    assert made[0]["design"] == CENTER and made[1]["design"] == other, "中心自己排在最前面，也进候选池"
    for number, one in enumerate(made[2:]):
        center = (CENTER, other)[number % 2]
        assert one["design"]["behave"] == center["behave"], "只取几个值的项照中心的"
        assert abs(one["design"]["length"] - center["length"]) <= 6.0 + 1e-9 and abs(one["design"]["width"] - center["width"]) <= 0.2 + 1e-9
        assert 20.0 <= one["design"]["length"] <= 80.0 and 1.0 <= one["design"]["width"] <= 3.0, "出了范围的截回来"
    assert max(one["design"]["width"] for one in made) <= 3.0 and any(one["design"]["width"] > 2.9 for one in made[2::2])
    assert [one["design"] for one in pool.designs(dict(SPACE, method="around", centers=[CENTER, other], count=1))] == [CENTER]


def test_a_way_of_drawing_that_is_written_wrong_is_said_before_anything_starts():
    assert "method 只有" in pool.problems(dict(SPACE, method="grid"))[0]
    assert "要写 centers" in pool.problems(dict(SPACE, method="around"))[0]
    wrong = pool.problems(dict(SPACE, method="around", spread=3, centers=[{"length": 50.0}, dict(CENTER, length=99.0), dict(CENTER, behave="no")]))
    assert len(wrong) == 4 and "spread" in wrong[0] and "第 1 个" in wrong[1] and "length=99.0" in wrong[2] and "behave='no'" in wrong[3], wrong
