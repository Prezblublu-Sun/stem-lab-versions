"""带代码的包：内核、策略、推导量定义、预测器。四种是同一种格式。

包是一个文件夹：清单、code/（代码）、data/（权重、表、自检样本）。清单另带：

    entry      入口：一条命令的各个参数，在包的文件夹里跑。{python} 换成跑它的那个解释器
    requires   依赖：一组写给人和环境看的字符串，比如 "numpy>=2"、"abaqus 2023"
    selftest   一组自检样本，每个是 {"name", "input", "expected"}：
               input 是包里的一个文件夹，expected 是包里的一个 JSON 文件
    tolerance  自检时数值允许差多少：{"rel": 相对, "abs": 绝对}
    range      预测器另加：适用范围。别的三种不带

怎么跑由核心定（hooks/entry.py）：命令后面跟上输入文件夹和输出文件夹两个参数；
包读输入文件夹，把结果写进输出文件夹，其中必须有一个 result.json；退出码是 0 才算成。
自检就是拿样本的 input 跑一遍，把 result.json 和 expected 比，数值在 tolerance 之内算相同。

包不 import plugins，所以插件重写之后旧的包照样能跑。

四种包各自和叫它的那一方的约定。契约不核这些：清单里另加的项、输入输出里的内容，由用它的冻结文件核，
不符就在启动的检查里说出原因。写在这里，是为了包和叫它的一方只有这一处可对。
输入文件夹里都有一个 job.json，说这一次要它做什么；列的说明都写成 {"name", "unit", "meaning"}。

    内核（kernel）       清单另加 modes（会哪几种做法：template、build、post）、design 和 conditions
                         （一个点要带的设计项、条件项的说明）、pre / labels / fields（它给出的三类量的说明）、
                         bones（只认哪几根骨，可以不写）
        template         job：bone_model（骨模型的文件夹）、bone_id、designs [{name, design}]、settings
                         result：designs [{name, feasible, info}]。只模板化，不做 FE
        build            job：bone_model、bone_id、point {name, design, conditions}、settings、job（求解用的文件夹）
                         result：status（built、misfit、mesh_failed、env、error）、reason、pre {…}、
                         solve {"command": 求解命令的各个参数，在 job 文件夹里跑，跑完才返回}
        post             job：同 build。求解已经结束，结果在 job 文件夹里。
                         unstable 是不收敛、而且内核拿得出证据说停下之前柄已经松动；没有证据的不收敛报 not_converged
                         result：status（ok、unstable、not_converged、env、error）、reason、labels {…}、
                         fields {场的名字: 输出文件夹里的文件}、steps {"done", "total"}、
                         keep {"mesh" / "fields" / "process" / "settings": job 文件夹里要留下的文件}
    推导量定义（derive_def）  清单另加 columns（它算出的各个量的说明）、needs（要哪几个场）
                         job：fields {场的名字: 文件}、labels、pre、point；result：derived {…}
    策略（strategy）      清单另加 needs（要不要 data、predictions）
                         job：objective、candidates [{name, design, feasible, info}]、conditions（条件默认）、count、seed、
                         data [数据的文件夹…]、predictions（预测器对各候选的预测 [{name, values, lower, upper}]，或 null）
                         result：chosen [{name, score, why}]、model（用的是哪个模型）
                         同样的 job 要选出同样的点：随机只许用 job 里的 seed
    预测器（predictor）    清单另加 columns（它预测的各列的说明，另带 role）、level（区间的名义覆盖率）
                         job：points [{hash, bone_id, design, conditions}]
                         result：rows [{point, values, lower, upper}]
"""
from __future__ import annotations

import math

RESULT = "result.json"


def check(kind: str, manifest: dict, folder) -> list[str]:
    """check_format 叫的入口。清单共用的那几项、清单列的文件在不在，已经核过了。"""
    files = set(manifest["files"])
    problems = [f"包的清单缺 {key}" for key in ("entry", "requires", "selftest", "tolerance") if key not in manifest]
    if problems:
        return problems

    entry = manifest["entry"]
    if not isinstance(entry, list) or not entry or not all(isinstance(part, str) and part for part in entry):
        problems.append("entry 必须是一条命令的各个参数")
    elif not any(part in files for part in entry):
        problems.append("entry 里要有包里的一个文件，比如 code/main.py")
    if not any(rel.startswith("code/") for rel in files):
        problems.append("包里要有 code/")
    if not isinstance(manifest["requires"], list) or not all(isinstance(text, str) for text in manifest["requires"]):
        problems.append("requires 必须是字符串的列表")

    tolerance = manifest["tolerance"]
    if not isinstance(tolerance, dict) or set(tolerance) != {"rel", "abs"} or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 for value in tolerance.values()):
        problems.append('tolerance 要写成 {"rel": 相对, "abs": 绝对}，两个都不小于 0')

    samples = manifest["selftest"]
    if not isinstance(samples, list) or not samples:
        return problems + ["selftest 至少要有一个自检样本"]
    names = []
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != {"name", "input", "expected"}:
            problems.append('每个自检样本要带且只带 "name"、"input"、"expected"')
            continue
        names.append(sample["name"])
        if not isinstance(sample["input"], str) or not any(rel.startswith(sample["input"].rstrip("/") + "/") for rel in files):
            problems.append(f"自检样本 {sample['name']!r} 的 input 不是包里的一个文件夹：{sample['input']!r}")
        if sample["expected"] not in files:
            problems.append(f"自检样本 {sample['name']!r} 的 expected 不是包里的一个文件：{sample['expected']!r}")
    if len(set(map(str, names))) != len(names):
        problems.append("自检样本的名字有重复的")

    if kind == "predictor" and not isinstance(manifest.get("range"), dict):
        problems.append("预测器的清单要带 range（适用范围）")
    if kind != "predictor" and "range" in manifest:
        problems.append("只有预测器带 range")
    return problems


def differences(expected, got, tolerance: dict, where: str = "result") -> list[str]:
    """两个 JSON 值哪里不一样。数值在容差之内算相同；别的要一模一样。空列表就是相同。"""
    if isinstance(expected, bool) or isinstance(got, bool) or expected is None or got is None:
        return [] if expected is got else [f"{where}：该是 {expected!r}，实际是 {got!r}"]
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        if math.isclose(expected, got, rel_tol=tolerance["rel"], abs_tol=tolerance["abs"]):
            return []
        return [f"{where}：该是 {expected!r}，实际是 {got!r}，差得比容差大"]
    if isinstance(expected, dict) and isinstance(got, dict):
        found = [f"{where}：少了 {key!r}" for key in expected if key not in got]
        found += [f"{where}：多了 {key!r}" for key in got if key not in expected]
        for key in expected:
            if key in got:
                found += differences(expected[key], got[key], tolerance, f"{where}.{key}")
        return found
    if isinstance(expected, list) and isinstance(got, list):
        if len(expected) != len(got):
            return [f"{where}：该有 {len(expected)} 项，实际有 {len(got)} 项"]
        return [text for index, (one, other) in enumerate(zip(expected, got))
                for text in differences(one, other, tolerance, f"{where}[{index}]")]
    return [] if type(expected) is type(got) and expected == got else [f"{where}：该是 {expected!r}，实际是 {got!r}"]
