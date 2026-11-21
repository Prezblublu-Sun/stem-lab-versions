"""选点策略共用的几样东西。打包时抄进每个包的 code/ 里：包只用自己带的代码，外加 numpy 和 scipy。

    read_job(文件夹)               读 job.json。里面有什么，写在 stemlab/contract/formats/package.py 里
    write_result(文件夹, 选的, 模型)
    allowed(候选, 目标和约束)      这个候选能不能选：候选池里记着可行，并且满足“不做 FE 就判得了的约束”。
                                   和系统事后拦的是同一条规矩；这里先筛掉，免得白占一个名额
    Space(一批设计)                把设计变成 0 到 1 之间的一组数：数值项按范围缩放，只取几个值的项一个值一列
    tried(job, 骨)                 数据里已经算过的设计（同一根骨、条件和这次选点的条件默认相同）
    observed(job, 列, 骨)          其中这几列都有数的：[(设计, [各列的数])]
    spread(候选的坐标, 已有的坐标, 个数, 次序)   逐个挑离已有的点最远的
    Gp                             高斯过程：Matern 5/2，每一项各一个长度，带噪声项；给均值和标准差
    expected_improvement(...)      期望改进（往小里优化）
"""
from __future__ import annotations

import json
import math
import pathlib

import numpy as np
from scipy.linalg import cho_solve, cholesky, solve_triangular
from scipy.optimize import minimize
from scipy.spatial.distance import cdist
from scipy.stats import norm

OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
SQRT5 = math.sqrt(5.0)


def read_job(folder) -> dict:
    return json.loads((pathlib.Path(folder) / "job.json").read_text(encoding="utf-8"))


def write_result(folder, chosen: list, model) -> None:
    body = json.dumps({"chosen": chosen, "model": model}, ensure_ascii=False)
    (pathlib.Path(folder) / "result.json").write_text(body, encoding="utf-8")


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def key(design: dict) -> str:
    """一个设计的写法固定的名字：两个设计一样不一样，比它。"""
    return json.dumps(design, sort_keys=True, ensure_ascii=False)


def allowed(candidate: dict, objective: dict) -> bool:
    if candidate.get("feasible") is not True:
        return False
    for limit in objective.get("constraints", []):
        value = (candidate.get(limit["on"]) or {}).get(limit["column"])
        try:
            if value is None or not OPS[limit["op"]](value, limit["limit"]):
                return False
        except TypeError:
            return False
    return True


def shown(value: float) -> str:
    """给人看的一个数：四位有效数字。"""
    return f"{value:.4g}"


# ---------------------------------------------------------------- 设计变成坐标

class Space:
    """一批设计张成的空间。数值项缩放到 0 到 1；只取几个值的项一个值一列，两个不同的值之间算相距 1。

    一批设计里从头到尾没变过的项不占坐标：它分不开任何两个设计。
    """

    def __init__(self, designs: list):
        names = sorted({name for design in designs for name in design})
        self.numeric, self.listed = [], []
        for name in names:
            values = [design.get(name) for design in designs]
            if all(is_number(value) for value in values):
                low, high = min(values), max(values)
                if high > low:
                    self.numeric.append((name, float(low), float(high)))
            else:
                kinds = sorted({json.dumps(value, sort_keys=True, ensure_ascii=False) for value in values})
                if len(kinds) > 1:
                    self.listed.append((name, kinds))
        self.width = len(self.numeric) + sum(len(kinds) for _, kinds in self.listed)

    def encode(self, design: dict) -> list:
        row = [(design[name] - low) / (high - low) for name, low, high in self.numeric]
        for name, kinds in self.listed:
            mine = json.dumps(design.get(name), sort_keys=True, ensure_ascii=False)
            row += [math.sqrt(0.5) if kind == mine else 0.0 for kind in kinds]
        return row

    def matrix(self, designs: list) -> np.ndarray:
        return np.array([self.encode(design) for design in designs], dtype=float).reshape(len(designs), self.width)


# ---------------------------------------------------------------- 读数据

def _rows(job: dict, source):
    """给的每一份数据的每一行，连同那份数据里各列是什么（设计、条件……）。"""
    for folder in job.get("data") or []:
        folder = pathlib.Path(folder)
        if not folder.is_absolute() and source is not None:
            folder = pathlib.Path(source) / folder
        listed = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        roles = {column["name"]: column["role"] for column in listed["columns"]}
        for line in (folder / "rows.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield roles, json.loads(line)


def _same(found, wanted) -> bool:
    if is_number(found) and is_number(wanted):
        return math.isclose(found, wanted, rel_tol=1e-9, abs_tol=1e-12)
    return found == wanted


def _here(job: dict, bone, source):
    """数据里和这次选点比得了的行：同一根骨，条件和条件默认逐项相同。给出（设计，这一行的各个数）。"""
    for roles, row in _rows(job, source):
        values = row.get("values") or {}
        if bone is not None and row.get("bone_id") != bone:
            continue
        if any(not _same(values.get(name), wanted) for name, wanted in job["conditions"].items()):
            continue
        yield {name: values.get(name) for name, role in roles.items() if role == "design"}, values


def tried(job: dict, bone, source=None) -> list:
    """已经算过的设计，不管算没算出来：再选它等于重算一遍。"""
    found, seen = [], set()
    for design, _ in _here(job, bone, source):
        if key(design) not in seen:
            seen.add(key(design))
            found.append(design)
    return found


def observed(job: dict, columns: list, bone, source=None) -> list:
    """算过、并且这几列都有数的：[(设计, [各列的数])]。同一个设计出现几次，用最先见到的那一行。"""
    found, seen = [], set()
    for design, values in _here(job, bone, source):
        numbers = [values.get(name) for name in columns]
        if key(design) not in seen and all(is_number(number) for number in numbers):
            seen.add(key(design))
            found.append((design, [float(number) for number in numbers]))
    return found


# ---------------------------------------------------------------- 铺开

def spread(points: np.ndarray, taken: np.ndarray, count: int, order: list) -> list:
    """逐个挑：每次挑离“已有的点”最远的那个候选，挑中的也算进已有的。返回 [(候选的下标, 它离已有的点多远)]。

    已有的点一个都没有时，第一个挑 order 里排最前的，它的距离记成 None。距离一样时照 order 的先后。
    """
    left = list(order)
    place = {index: number for number, index in enumerate(order)}
    nearest = np.full(len(points), np.inf)
    if len(taken):
        nearest = cdist(points, taken).min(axis=1)
    picked = []
    while left and len(picked) < count:
        if not picked and not len(taken):
            best, far = left[0], None
        else:
            best = max(left, key=lambda index: (round(float(nearest[index]), 12), -place[index]))
            far = float(nearest[best])
        picked.append((best, far))
        left.remove(best)
        nearest = np.minimum(nearest, np.linalg.norm(points - points[best], axis=1))
    return picked


# ---------------------------------------------------------------- 高斯过程

class Gp:
    """高斯过程回归。数据先减均值、除标准差；核是 Matern 5/2，每一项各一个长度，另加一个噪声项。

    长度和噪声照边际似然定（信号的方差有解析解，代进去之后只剩长度和噪声要找）；
    从几个起点各找一次，取似然最大的。起点里随机的那几个只用给的种子，所以同样的数据拟合出同样的模型。
    """

    def __init__(self, x, y, seed: int = 0, starts: int = 3):
        self.x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        self.mean = float(y.mean())
        self.scale = float(y.std()) or 1.0
        self.z = (y - self.mean) / self.scale
        width = self.x.shape[1]
        bounds = [(math.log(0.05), math.log(20.0))] * width + [(math.log(1e-6), math.log(1.0))]
        rng = np.random.default_rng(seed)
        tries = [np.array([0.0] * width + [math.log(1e-2)])]
        tries += [np.array([rng.uniform(low, high) for low, high in bounds]) for _ in range(max(0, starts - 1))]
        best = None
        for start in tries:
            done = minimize(self._loss, start, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 80})
            if best is None or done.fun < best.fun:
                best = done
        self.lengths, self.noise = np.exp(best.x[:width]), float(math.exp(best.x[width]))
        self.signal = float(self._solve()) / len(self.z)        # 信号的方差（在标准化了的数上）

    def _kernel(self, a, b):
        r = cdist(a / self.lengths, b / self.lengths)
        return (1.0 + SQRT5 * r + 5.0 * r * r / 3.0) * np.exp(-SQRT5 * r)

    def _solve(self) -> float:
        cover = self._kernel(self.x, self.x) + self.noise * np.eye(len(self.x))
        self.lower = cholesky(cover, lower=True)
        self.alpha = cho_solve((self.lower, True), self.z)
        return float(self.z @ self.alpha)

    def _loss(self, theta):
        """负的对数边际似然（信号的方差已经代进去），和它对各个参数的导数。"""
        width, count = self.x.shape[1], len(self.z)
        lengths, noise = np.exp(theta[:width]), math.exp(theta[width])
        scaled = self.x / lengths
        r = cdist(scaled, scaled)
        decay = np.exp(-SQRT5 * r)
        cover = (1.0 + SQRT5 * r + 5.0 * r * r / 3.0) * decay + noise * np.eye(count)
        try:
            lower = cholesky(cover, lower=True)
        except np.linalg.LinAlgError:
            return 1e25, np.zeros_like(theta)
        alpha = cho_solve((lower, True), self.z)
        fit = float(self.z @ alpha)
        value = 0.5 * count * math.log(fit / count) + float(np.log(np.diag(lower)).sum())
        inverse = cho_solve((lower, True), np.eye(count))
        weight = 0.5 * inverse - (0.5 * count / fit) * np.outer(alpha, alpha)       # 损失对核矩阵每一格的导数
        part = weight * (5.0 / 3.0) * (1.0 + SQRT5 * r) * decay                       # 再乘上 核 对 (差/长度)² 的导数
        grad = np.empty_like(theta)
        grad[:width] = 2.0 * ((scaled * scaled).T @ part.sum(axis=1)) - 2.0 * (scaled * (part @ scaled)).sum(axis=0)
        grad[width] = noise * float(np.trace(weight))
        return value, grad

    def predict(self, points) -> tuple:
        """各点的均值和标准差（函数本身的，不含噪声），都换回原来的单位。"""
        points = np.asarray(points, dtype=float)
        cross = self._kernel(points, self.x)
        mean = cross @ self.alpha
        back = solve_triangular(self.lower, cross.T, lower=True)
        spread_ = self.signal * np.maximum(1.0 - (back * back).sum(axis=0), 1e-12)
        return self.mean + self.scale * mean, self.scale * np.sqrt(spread_)

    def add(self, point, value: float) -> None:
        """把一个点连同给它的数加进来，长度、噪声、信号的方差都不重新找。一批里逐个选点时，选中的先当它算出了预测的均值。"""
        self.x = np.vstack([self.x, np.asarray(point, dtype=float)[None, :]])
        self.z = np.append(self.z, (value - self.mean) / self.scale)
        self._solve()


def expected_improvement(mean, deviation, best: float):
    """往小里优化时的期望改进：比现在最好的 best 还小多少，按预测的分布取平均。"""
    mean, deviation = np.asarray(mean, dtype=float), np.maximum(np.asarray(deviation, dtype=float), 1e-12)
    gap = (best - mean) / deviation
    return (best - mean) * norm.cdf(gap) + deviation * norm.pdf(gap)
