"""【冻结】fea.run 的输入：柄空间包（可以不填，不填就是无植入物）、有限元包、推导量定义，和照它们的声明写的几份设定。

核心启动时已经照声明核过每一份设定自己（第 1 到 5、7、9 条）。这里核它们和这个实验的输入对不对得上：
    照对了声明    放置设定照这个柄空间包的 placement，有限元设定照这个有限元包的 fem，
                 推导量设定照这个推导量定义的 derive（它没声明就不填），运行设定照 fea.run 自己的 run
    第 6 条      每个点的设计项照柄空间包的 design 写全；条件、放置、推导量三组照三份设定里写了“每个点给”的项。
                 无植入物时设计、放置两组是空的；没有推导量设定时推导量那一组是空的
    第 8 条      名字引用照骨模型和柄的模型里有的名字核。柄的模型跑的时候才有：启动前照柄空间包清单里的 names 核，
                 跑的时候再核交出的柄的模型（stem_wrong），不合的作业归成出错
    数据说明      设计项、三组每个点给的项（role 都是 condition）、柄空间包和有限元包的产出、推导量，列名不重复。
                 每个点给的项要写进数据的行，只能是数、整数、是否、几选一、文字

交给包的 job.json 也在这里拼（ask、derive_ask）：包拿到的设定就是登记的那几份，加上这个点给的，没有隐含的默认值。
自由代码照它写 job.json。作业结束以后，冻结的代码照登记的输入再核一遍，自由代码交上来的说法不作数。
"""
from __future__ import annotations

import json
from pathlib import Path

from stemlab import hooks

TYPE = "fea.run"
MANIFEST = "manifest.json"
MODEL = "model"                                 # 柄空间包把柄的模型写在它输出文件夹的这个子文件夹里
STEM_MODES, FEM_MODES = ("model",), ("build", "post")
STEM_ROLES, FEM_ROLES = ("pre",), ("pre", "label", "field")
SCALAR = ("number", "integer", "bool", "choice", "text")       # 能写进数据的行：设计项、每个点给的项只能是这几种
NAME_PARTS = ("region", "faces", "feature", "axis")            # 柄空间包清单里 names 的四类，名字引用写成 stem.<类>.<名字>
ROLE_ORDER = ("design", "condition", "pre", "label", "field", "derived")
# 三组每个点给的取值：点里的哪一组，哪一样设定输入，它照哪一样包输入的哪份声明，说给人听叫什么
GROUPS = (("conditions", "fem_setting", "fem", "fem", "有限元设定"),
          ("placement", "placement", "stem", "placement", "放置设定"),
          ("derive", "derive_setting", "derive", "derive", "推导量设定"))
_MAX_PROBLEMS = 20


def _manifest(folder) -> dict:
    return json.loads((Path(folder) / MANIFEST).read_bytes())


def _decl(listed, name: str):
    return hooks.find_declaration(listed.get("declarations"), name) if isinstance(listed, dict) else None


def read(handle) -> dict:
    """这一次调用里要反复用的几样：三个包的清单、几份设定、它们照的声明、名字引用能用的名字。读不出清单报 ValueError。"""
    try:
        stem = handle.input("stem")
        listed = {"stem": _manifest(stem) if stem is not None else None,
                  "fem": _manifest(handle.input("fem")), "derive": _manifest(handle.input("derive"))}
        bone = _manifest(handle.input("bone"))
    except (OSError, ValueError) as error:
        raise ValueError(f"读不出包或骨模型的清单：{error}") from None
    settings = {name: handle.input(name) for name in ("placement", "fem_setting", "derive_setting", "run")}
    declared = {setting: _decl(listed[package], decl) for _, setting, package, decl, _ in GROUPS}
    names = {**hooks.bone_names(bone), **promised(listed["stem"])}
    return {"listed": listed, "settings": settings, "design": _decl(listed["stem"], "design"), "declared": declared,
            "names": names, "implant": stem is not None}


def promised(stem_listed) -> dict:
    """柄空间包在清单里说它交出的柄的模型里一定有的名字：{"stem.region": {…}, …}。无植入物都是空的。"""
    said = stem_listed.get("names") if isinstance(stem_listed, dict) else None
    return {f"stem.{part}": set(said.get(part) or []) if isinstance(said, dict) and isinstance(said.get(part), list) else set()
            for part in NAME_PARTS}


# ---------------------------------------------------------------- 启动前

def problems(handle) -> list[str]:
    """启动的第 5 步里冻结的那部分。返回哪里不行；空列表就是行。"""
    try:
        given = read(handle)
    except ValueError as error:
        return [str(error)]
    found = _package_problems(given)
    found += _setting_problems(handle, given)
    if found:
        return found
    found = _point_problems(handle, given)
    if found:
        return found[:_MAX_PROBLEMS] + (["……还有更多，先改上面这些"] if len(found) > _MAX_PROBLEMS else [])
    names = [column["name"] for column in columns(given)]
    return [f"数据的列名重复了：{name}" for name in sorted({name for name in names if names.count(name) > 1})]


def _names_ok(said) -> bool:
    return isinstance(said, dict) and set(said) == set(NAME_PARTS) and all(
        isinstance(listed, list) and all(isinstance(name, str) and name.strip() for name in listed)
        and len(set(listed)) == len(listed) for listed in said.values())


def _described(listed) -> bool:
    return isinstance(listed, list) and all(
        isinstance(column, dict) and all(isinstance(column.get(key), str) and column[key].strip() for key in ("name", "unit", "meaning"))
        for column in listed)


def _package_problems(given: dict) -> list[str]:
    """三个包能不能干 FEA 要的活、清单写清楚了没有。"""
    stem, fem, derive = (given["listed"][name] for name in ("stem", "fem", "derive"))
    found = []
    if stem is not None:
        if not set(STEM_MODES) <= set(stem.get("modes") or []):
            found.append(f"这个柄空间包不会 {list(STEM_MODES)}：FEA 要它交出柄的模型（model）")
        if not _names_ok(stem.get("names")):
            found.append(f"柄空间包的清单要带 names：它交出的柄的模型里一定有的名字，{list(NAME_PARTS)} 各一个名字列表")
        if any(column.get("role") not in STEM_ROLES for column in stem.get("outputs") or []):
            found.append(f"柄空间包的产出只能是模板化算出的量（role 是 {list(STEM_ROLES)}）")
    if not set(FEM_MODES) <= set(fem.get("modes") or []):
        found.append(f"这个有限元包不会 {[m for m in FEM_MODES if m not in (fem.get('modes') or [])]}：FEA 要它会建模（build）和后处理（post）")
    if any(column.get("role") not in FEM_ROLES for column in fem.get("outputs") or []):
        found.append(f"有限元包的产出只能是 {list(FEM_ROLES)} 这几种")
    if not _described(derive.get("columns")) or not derive.get("columns"):
        found.append("推导量定义的清单要带 columns：它算出的各个量的说明（name、unit、meaning）")
    offered = {column.get("name") for column in fem.get("outputs") or [] if column.get("role") == "field"}
    lacking = sorted(set(derive.get("needs") or []) - offered)
    if lacking:
        found.append(f"推导量定义要的场 {lacking}，这个有限元包不给")
    return found


def _setting_problems(handle, given: dict) -> list[str]:
    """几份设定都照声明写，照的就是该照的那一份；该填的填了，不该填的没填。名字引用照输入里有的名字核（第 8 条）。"""
    settings, found = given["settings"], []
    wanted = {"run": (TYPE, "run", "运行设定")}
    for _, setting, package, decl, label in GROUPS:
        info = handle.input_info(package)
        if info is None or (package == "derive" and given["declared"][setting] is None):
            if settings[setting] is not None:
                found.append(f"{label}不该填：" + ("没有填柄空间包（无植入物）" if package == "stem" else "推导量定义没有声明 derive"))
            continue
        wanted[setting] = (info.id, decl, label)
    for setting, (of, decl, label) in wanted.items():
        value = settings[setting]
        if value is None:
            found.append(f"{label}要填：照 {of} 的 {decl} 声明写")
        elif not hooks.is_declared(value):
            found.append(f"{label}要照声明写（带 format 和 declaration），这里是老写法")
        elif not isinstance(value["declaration"], dict) or (value["declaration"].get("of"), value["declaration"].get("name")) != (of, decl):
            found.append(f"{label}照的是 {value['declaration']!r}，要照 {of} 的 {decl} 声明")
        elif setting != "run":
            found += [f"{label}：{text}" for text in hooks.check_setting(value, given["declared"][setting], names=given["names"])]
    if found:
        return found
    if given["implant"]:
        found += [f"柄空间包的设计项 {item['name']!r} 是 {item['type']}：设计项要写进数据的行，只能是 {list(SCALAR)}"
                  for item in given["design"]["items"] if item["type"] not in SCALAR]
    for _, setting, _, _, label in GROUPS:
        value, declaration = settings[setting], given["declared"].get(setting)
        if value is None or declaration is None:
            continue
        by_name = {item["name"]: item for item in declaration["items"]}
        found += [f"{label}里每个点给的 {name!r} 是 {by_name[name]['type']}：它要写进数据的行，只能是 {list(SCALAR)}"
                  for name in hooks.per_point_items(value) if by_name[name]["type"] not in SCALAR]
    return found


def _point_problems(handle, given: dict) -> list[str]:
    """第 6 条：每个点给的项。名字引用（第 8 条）也照输入里的名字核。"""
    bone_id, names, settings = handle.input_info("bone").bone_id, given["names"], given["settings"]
    found = []
    for point in hooks.read_points(handle.input("points")):
        title = f"点 {point.get('name')!r}"
        if point.get("bone_id") != bone_id:
            found.append(f"{title}的骨标识是 {point.get('bone_id')!r}，骨模型是 {bone_id}")
        if given["implant"]:
            found += [f"{title}的设计项：{text}" for text in hooks.check_design(point.get("design"), given["design"], names)]
        elif point.get("design"):
            found.append(f"{title}写了设计项 {sorted(point['design'])}：无植入物，设计项要是空的")
        for group, setting, _, _, label in GROUPS:
            values = point.get(group) or {}
            if settings[setting] is None:
                if values:
                    found.append(f"{title}的 {group} 写了 {sorted(values)}：没有{label}，这一组要是空的")
                continue
            found += [f"{title}的 {group}（{label}）：{text}"
                      for text in hooks.check_point(values, settings[setting], given["declared"][setting], names)]
        if len(found) > _MAX_PROBLEMS:
            break
    return found


# ---------------------------------------------------------------- 数据说明、made_by

def _column(item: dict, role: str) -> dict:
    return {"name": item["name"], "unit": item.get("unit") or "1", "meaning": item["meaning"], "role": role}


def columns(given: dict) -> list[dict]:
    """数据说明：每列的名字、单位、含义、role。照 role 排：设计、条件、建模时就有的、标量、场、推导量。"""
    listed = [_column(item, "design") for item in given["design"]["items"]] if given["implant"] else []
    for _, setting, _, _, _ in GROUPS:
        value, declaration = given["settings"][setting], given["declared"].get(setting)
        if value is not None and declaration is not None:
            by_name = {item["name"]: item for item in declaration["items"]}
            listed += [_column(by_name[name], "condition") for name in hooks.per_point_items(value)]
    for package in ("stem", "fem"):
        listed += [dict(column) for column in (given["listed"][package] or {}).get("outputs") or []]
    listed += [{"name": column["name"], "unit": column["unit"], "meaning": column["meaning"], "role": "derived"}
               for column in given["listed"]["derive"]["columns"]]
    return sorted(listed, key=lambda column: ROLE_ORDER.index(column["role"]) if column["role"] in ROLE_ORDER else len(ROLE_ORDER))


def _common(setting) -> dict | None:
    """一份设定里所有点都一样的那部分。没有这份设定是 None。"""
    if setting is None:
        return None
    each = set(hooks.per_point_items(setting))
    return {name: value for name, value in setting["values"].items() if name not in each}


def maker(handle, given: dict) -> dict:
    """这份数据是怎么算出来的（made_by 第 2 版，拆内核以后的写法）：柄空间包（无植入物写 "none"）、有限元包、推导量定义，
    三份设定里所有点都一样的那部分，这根骨用的是哪一版骨模型。运行设定只管怎么跑，不进来。"""
    bone, stem = handle.input_info("bone"), handle.input_info("stem")
    settings = given["settings"]
    return hooks.made_by_split(stem.hash if stem is not None else None, handle.input_info("fem").hash,
                               handle.input_info("derive").hash, bones={bone.bone_id: {"id": bone.id, "hash": bone.hash}},
                               settings={"placement": _common(settings["placement"]), "fem": _common(settings["fem_setting"]),
                                         "derive": _common(settings["derive_setting"])})


# ---------------------------------------------------------------- 交给包的东西

def ask(handle, job: dict, mode: str, stem=None, solve=None) -> dict:
    """交给包的 job.json。mode 是 model（柄空间包出柄的模型），或 build、post（有限元包）。
    stem 是柄空间包的输出文件夹（柄的模型在它的 model/ 里），无植入物是 None；solve 是求解用的文件夹。"""
    point = job["point"]
    base = {"mode": mode, "bone_model": str(handle.input("bone")), "bone_id": point["bone_id"]}
    if mode == "model":
        return dict(base, point={"name": point["name"], "hash": point["hash"], "design": point["design"]},
                    settings=hooks.merged(handle.input("placement"), point.get("placement") or {}))
    return dict(base, stem_model=None if stem is None else str(Path(stem) / MODEL),
                point={"name": point["name"], "hash": point["hash"]},
                settings=hooks.merged(handle.input("fem_setting"), point.get("conditions") or {}),
                job=None if solve is None else str(solve))


def pre(result: dict) -> dict:
    """建模之前就知道的量：柄空间包模板化给的，加上有限元包建模给的。"""
    return {**((result.get("stem") or {}).get("pre") or {}), **((result.get("build") or {}).get("pre") or {})}


def derive_ask(handle, job: dict, result: dict) -> dict:
    """推导量定义在这条路上另拿到的：骨模型、柄的模型、这个点的推导量设定；建模时的量两次合起来。"""
    point, setting = job["point"], handle.input("derive_setting")
    folder = (result.get("dirs") or {}).get("stem")
    return {"bone_model": str(handle.input("bone")),
            "stem_model": str(Path(folder) / MODEL) if handle.input_info("stem") is not None and folder else None,
            "settings": None if setting is None else hooks.merged(setting, point.get("derive") or {}),
            "pre": pre(result)}


# ---------------------------------------------------------------- 作业结束以后

def stem_wrong(handle, job: dict, folder) -> list[str]:
    """柄空间包说它交出了柄的模型：核一遍。合格式，抄的设计项就是这个点的，清单 names 里说的名字都在。
    返回哪里不对；空列表就是对的。folder 是柄空间包的输出文件夹。自由代码可以先拿它看一眼，省得白建模。"""
    if not folder:
        return ["柄空间包没有留下输出文件夹"]
    where = Path(folder) / MODEL
    wrong = hooks.check_stem_model(where)
    if wrong:
        return ["柄的模型不合格式：" + "；".join(wrong[:5])]
    model = hooks.read_stem_model(where)
    if model["design"] != job["point"]["design"]:
        return [f"柄的模型里抄的设计项 {model['design']!r} 和这个点的 {job['point']['design']!r} 不一样"]
    have = hooks.stem_names(model)
    missing = sorted(f"{part}.{name}" for part, wanted in promised(_manifest(handle.input("stem"))).items()
                     for name in wanted - set(have.get(part, ())))
    return [f"柄的模型里没有柄空间包清单里说一定有的名字：{missing}"] if missing else []


def checked(handle, job: dict, result: dict) -> dict:
    """一个结束了的作业的结果，照登记的输入理一遍再交给 classify：有植入物的一定带 stem（柄空间包的结果，没有就是 None），
    柄的模型核过，不对的地方记在 stem_wrong；无植入物的不带 stem。自由代码交上来的 stem_wrong 不作数。"""
    result = {key: value for key, value in result.items() if key != "stem_wrong"}
    if handle.input_info("stem") is None:
        result.pop("stem", None)
        return result
    result.setdefault("stem", None)
    if isinstance(result["stem"], dict) and result["stem"].get("status") == "ok" and not result.get("lost"):
        result["stem_wrong"] = stem_wrong(handle, job, (result.get("dirs") or {}).get("stem"))
    return result


def row_sources(job: dict, result: dict) -> dict:
    """这一行里写在点里的、建模之前就知道的量各从哪来：设计项；条件、放置、推导量三组合起来；两次给的建模时的量。"""
    point = job["point"]
    given = {**(point.get("conditions") or {}), **(point.get("placement") or {}), **(point.get("derive") or {})}
    return {"design": point["design"], "condition": given, "pre": pre(result)}
