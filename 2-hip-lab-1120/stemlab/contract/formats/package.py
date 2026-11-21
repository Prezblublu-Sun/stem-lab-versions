"""带代码的包：内核、策略、推导量定义、预测器，和 2026-11-16 加的柄空间、有限元、重建方法、代理模型。都是同一种格式。

包是一个文件夹：清单、code/（代码）、data/（权重、表、自检样本）。清单另带：

    entry      入口：一条命令的各个参数，在包的文件夹里跑。{python} 换成跑它的那个解释器
    requires   依赖：一组写给人和环境看的字符串，比如 "numpy>=2"、"abaqus 2023"
    selftest   一组自检样本，每个是 {"name", "input", "expected"}：
               input 是包里的一个文件夹，expected 是包里的一个 JSON 文件
    tolerance  自检时数值允许差多少：{"rel": 相对, "abs": 绝对}
    range      预测器另加：适用范围。别的不带

第 2 版另加六段（《设定的声明和包的清单》第六节）。新的四种（NEW_KINDS）必写；原来的四种可以写，也可以不写：
    programs      用到的外部程序和确切的版本：[{"name", "version"}]，比如 {"name": "abaqus", "version": "2025"}。
                  只写要哪个、哪一版，不写装在哪：装在哪是机器的事，写在机器清单里（contract/machines.py 的 programs）
    declarations  声明的设定：[声明, …]，写法和规矩见 declaration.py，一个包里不重名。各种包至少要有的几份见 DECLARED
    modes         能做的事：MODES 里这一种包的那几样，不重复
    inputs        对输入的要求：{输入名: {…}}。里面具体写什么，由用它的冻结代码核。
                  对骨模型的要求（bone）有固定的写法，见 bone_model.py：要哪些角色的区域、哪种几何文件、哪些材料模型、
                  哪些标志点、覆盖范围、坐标系的定法；用它的冻结代码拿 check_wanted、lacking 核。没写就是不挑
    outputs       产出的列：[{"name", "unit", "meaning", "role"}]，和数据的列一样写；交出的不是列（比如预测器）就写 []
    test_round    测试轮用的参照输入：{"inputs": {输入名: {"folder": 包里的文件夹} 或 {"item": 登记的编号}}}
第 1 版的清单读成第 2 版时只改版本号：新的几段原来都没有。

怎么跑由核心定（hooks/entry.py）：命令后面跟上输入文件夹和输出文件夹两个参数；
包读输入文件夹，把结果写进输出文件夹，其中必须有一个 result.json；退出码是 0 才算成。
自检就是拿样本的 input 跑一遍，把 result.json 和 expected 比，数值在 tolerance 之内算相同。

包不 import plugins，所以插件重写之后旧的包照样能跑。

各种包和叫它的那一方的约定。契约不核这些：清单里另加的项、输入输出里的内容，由用它的冻结文件核，
不符就在启动的检查里说出原因。写在这里，是为了包和叫它的一方只有这一处可对。
输入文件夹里都有一个 job.json，说这一次要它做什么；列的说明都写成 {"name", "unit", "meaning"}。
包清单的 programs 里写了外部程序的，叫它的一方照名字和版本在要跑它的那台机器的清单里找位置，
放进 job.json 的 programs：{名字: 位置}。包不自己去找（不看环境变量、不留自己的默认位置）；job 里没有，就当这台机器没装。
现在照这样带的是 fea.run 交给柄空间包、有限元包、推导量定义的 job（plugins/fea/given.py），启动前也核操作台都装了。

骨模型交给包的时候是两样（2026-11-19，第 5 步的 5b）：
    bone_model   骨模型的文件夹。几何文件从这里拿
    bone         骨模型的清单，叫包的一方已经读成现在这一版的样子（bone_model.read：盘上是旧版本的照样读，
                 旧版本没有的几样是 null）。直接写在 job.json 里
包读 bone，不自己打开文件夹里的 manifest.json，也就不用认旧版本。找区域照角色（role）找，不照名字找；
名字引用（bone.region.<名字>）指的还是名字：照名字找到那个区域，再看它的角色。
包对骨模型的要求写在清单 inputs 的 bone 里。叫它的一方启动前照它核：要求自己写得不对，或者这根骨缺哪一样，就不启动，
说出是哪个包、缺哪一样。叫的一方自己不挑骨：收不收某种骨，只照包写的要求。要求里写不出的限制
（比如只认某两个文件），由包在跑的时候自己核，说出原因。
现在照这样带、照这样核的是 fea.run 交给柄空间包、有限元包、推导量定义的 job（plugins/fea/given.py）；
5c 起另有重建定稿交给方法包的 job（带 bone，是候选的清单），和检查门冒烟时交给柄空间包 template 的 job：
冒烟用的柄空间包写的要求，定稿启动前照候选核（plugins/recon/plugin.py、gate.py）。
内核（参照包那条）的 job 不带 bone：它是登记后不改的旧代码，自己读文件夹里的清单。

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
    预测器（predictor）    清单另加 columns（它预测的各列的说明，另带 role）、level（区间的名义覆盖率）；
                         预测场的再加 shapes（各个场的形状）
                         job：points [{hash, bone_id, design, conditions}]
                         result：rows [{point, values, lower, upper}]。预测场的，每行另带 fields {场的名字: 输出文件夹里的文件}，
                         文件里是值、下界、上界摞在一起的数组

拆内核以后的两种（2026-11-16，第 4 步）。设定都照包自己的声明写；job 里的 settings 是这个点的取值：
设定里写的，加上这个点给的（declaration.merged）。名字引用原样交过去，由包自己去骨模型、柄的模型里找。

    柄空间（stem_space）  设计项（design 声明）每一项都由一批点逐个给：per_point、required 都是 true。
                         清单另加 names：它交出的柄的模型里一定有的名字，{"region", "faces", "feature", "axis"} 各一个名字列表。
                         启动前，设定里的名字引用照它核；跑的时候再核交出的柄的模型里真的有。
                         outputs 是模板化算出的量（role 都是 pre）
        template         job：bone_model、bone、bone_id、designs [{name, design}]、settings（放置设定的取值）
                         result：designs [{name, feasible, info}]。只模板化，不出柄的模型。优化取候选时用
        model            job：bone_model、bone、bone_id、point {name, hash, design}、settings（这个点的放置设定）、programs
                         result：status（ok、misfit、env、error）、reason、pre {模板化算出的量}。
                         status 是 ok 的，柄的模型（stem_model.py 的格式）写在输出文件夹的 model/ 里，design 原样抄这个点的
    有限元（fem）         outputs 是它给出的量：role 是 pre（建模时就有的）、label（标量）、field（场）
        build            job：bone_model、bone、bone_id、stem_model（柄的模型的文件夹，无植入物是 null）、point {name, hash}、
                         settings（这个点的有限元设定）、job（求解用的文件夹）、programs
                         result：status（built、mesh_failed、env、error）、reason、pre {…}、
                         solve {"command": 求解命令的各个参数，在 job 文件夹里跑，跑完才返回; 可另带 "timeout_s"}
        post             job：同 build。求解已经结束，结果在 job 文件夹里。result 同内核的 post
    推导量定义在拆内核以后的那条路上，job 另带 bone_model、bone、stem_model（无植入物是 null）、
    settings（这个点的推导量设定，没有推导量设定是 null）、programs，pre 是柄空间包和有限元包两次给的合起来

重建方法（recon_method，2026-11-19，第 5 步的 5c）。叫它的是 recon.draft、recon.finalize 的骨架（plugins/recon/plugin.py）。
重建设定照它声明的 rebuild 写，不能有每个点给的项（重建没有一批点）；job 里的 settings 是这份设定的取值。
outputs 是它会量出的数，role 都写 label。检查门的线只能拿这些、和骨架自己记的三个（stem_smoke、stem_smoke_reason、
anteversion_deg）来比，这三个名字包不能用。清单另加 kept：定稿时重做不了的量（outputs 里的名字），可以不写。
现在的方法包都不用外部程序，job 里不带 programs。

    draft            job：source（骨源的文件夹）、bone_id、settings
                     result：status（ok、error、env）、reason。ok 的另带骨模型的几段，照第 2 版的写法（bone_model.py）：
                     how、side、bone_type、coverage、regions、landmarks、history；frame 只写 file（几何文件自己的坐标是怎么来的），
                     只有近端一段的另写 anteversion_deg（照重建设定）：原点和三个轴由叫它的一方照标志点算（bone_model.frame）。
                     regions 的几何文件写绝对路径（骨源里的、候选里的、人工修改里的，或它输出文件夹里的），叫它的一方原样复制进骨模型。
                     另带 measures（量出来的数）、todo（待检查清单 [{item, doubt, why}]）；可另带 timings、mesh_quality、neck_loop，给图表用
    finalize         job：draft（候选骨模型的文件夹）、bone（候选的清单，读成现在这一版）、edits（人工修改的文件夹，没有是 null）、
                     bone_id、settings。人工修改是文件夹里的 edits.json：{"by": 谁改的, "landmarks": {名字: {"xyz", "why"}},
                     "solids": {区域名: {"file": 这个文件夹里换上的文件, "why"}}}，叫它的一方启动前核过写法（plugins/recon/review.py）
                     result：同 draft，不带 todo；另带 kept：这一次沿用候选的哪几个数，只许清单 kept 里的，
                     值由叫它的一方从候选的 measures 里抄，包自己不给。用了人工修改的，改了哪里写进 history
"""
from __future__ import annotations

import math

from stemlab.contract.formats import declaration
from stemlab.contract.formats.data import check_columns
from stemlab.contract.layout import is_item_id, is_label

RESULT = "result.json"

NEW_KINDS = ("stem_space", "fem", "recon_method", "surrogate_model")
SECTIONS = ("programs", "declarations", "modes", "inputs", "outputs", "test_round")
# 每种包能做的事
MODES = {"kernel": ("template", "build", "post"), "strategy": ("select",), "derive_def": ("derive",),
         "predictor": ("predict",), "stem_space": ("template", "model"), "fem": ("build", "post"),
         "recon_method": ("draft", "finalize"), "surrogate_model": ("train",)}
# 每种包至少要声明的几份设定。名字不用插件的名字（核心不认得哪个插件），所以重建方法的叫 rebuild
DECLARED = {"stem_space": ("design", "placement"), "fem": ("fem",), "recon_method": ("rebuild",), "surrogate_model": ("hyper",)}


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
    return problems + _sections(kind, manifest, files)


def _sections(kind: str, manifest: dict, files: set) -> list[str]:
    """第 2 版加的六段。新的四种必写，原来的四种写了就核。"""
    problems = [f"{kind} 的清单缺 {key}" for key in SECTIONS if kind in NEW_KINDS and key not in manifest]
    if problems:
        return problems
    if "programs" in manifest:
        programs = manifest["programs"]
        if not isinstance(programs, list) or not all(
                isinstance(p, dict) and set(p) == {"name", "version"} and all(isinstance(v, str) and v.strip() for v in p.values())
                for p in programs):
            problems.append('programs 要写成 [{"name": 程序, "version": 确切的版本}]')
        elif len({p["name"] for p in programs}) != len(programs):
            problems.append("programs 里有重名的程序")
    if "declarations" in manifest:
        problems += _declarations(kind, manifest["declarations"])
    if "modes" in manifest:
        modes, allowed = manifest["modes"], MODES[kind]
        if not isinstance(modes, list) or not modes or any(mode not in allowed for mode in modes) or len(set(modes)) != len(modes):
            problems.append(f"modes 要从 {list(allowed)} 里选，不重复，至少一样：{modes!r}")
    if "inputs" in manifest:
        inputs = manifest["inputs"]
        if not isinstance(inputs, dict) or not all(is_label(name) and isinstance(want, dict) for name, want in inputs.items()):
            problems.append("inputs 要写成 {输入名: {对它的要求}}")
    if "outputs" in manifest and manifest["outputs"] != []:        # 交出的不是列（比如代理模型交出预测器）就写空列表
        problems += [f"outputs：{text}" for text in check_columns("data", {"columns": manifest["outputs"]})]
    if "test_round" in manifest:
        problems += _test_round(manifest["test_round"], files)
    return problems


def _declarations(kind: str, declarations) -> list[str]:
    if not isinstance(declarations, list) or not all(isinstance(one, dict) for one in declarations):
        return ["declarations 要是声明的列表"]
    problems = [text for one in declarations for text in declaration.check_declaration(one)]
    names = [one.get("name") for one in declarations]
    if len(set(map(str, names))) != len(names):
        problems.append(f"declarations 里有重名的声明：{names}")
    problems += [f"{kind} 要声明 {name}" for name in DECLARED.get(kind, ()) if name not in names]
    design = declaration.find(declarations, "design") if kind == "stem_space" else None
    if isinstance(design, dict) and isinstance(design.get("items"), list):
        loose = [item.get("name") for item in design["items"]
                 if isinstance(item, dict) and not (item.get("per_point") is True and item.get("required") is True)]
        if loose:
            problems.append(f"柄空间的设计项每一项都由一批点逐个给，per_point、required 都要是 true：{loose}")
    return problems


def _test_round(test_round, files: set) -> list[str]:
    inputs = test_round.get("inputs") if isinstance(test_round, dict) and set(test_round) == {"inputs"} else None
    if not isinstance(inputs, dict) or not all(is_label(name) for name in inputs):
        return ['test_round 要写成 {"inputs": {输入名: 参照输入}}']
    problems = []
    for name, source in inputs.items():
        if isinstance(source, dict) and set(source) == {"folder"} and isinstance(source["folder"], str):
            if not any(rel.startswith(source["folder"].rstrip("/") + "/") for rel in files):
                problems.append(f"测试轮的输入 {name!r}：{source['folder']!r} 不是包里的一个文件夹")
        elif not (isinstance(source, dict) and set(source) == {"item"} and is_item_id(source["item"])):
            problems.append(f'测试轮的输入 {name!r} 要写成 {{"folder": 包里的文件夹}} 或 {{"item": 登记的编号}}')
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
