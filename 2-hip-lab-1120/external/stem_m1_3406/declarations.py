"""从 M1-3406-v1 拆出来的柄空间包的两份声明：设计项（design）和放置设定（placement）。拆内核 4b 写的，4c 打包时放进包的清单。

照的是原项目在 3406 上生产时的设定（原项目只读：H:\\projects\\Femoral implant generation\\sandbox\\mobo_toy）：
    设计项的范围    v2/stage_neckopt.py 的 PHASES[11]（阶段 13 沿用）的 vars：3406 上的设计空间
    测试轮的取值    设计 A：旧数据库 v0.14 里的 sb13_a105_91e458e3（tests/science/test_fea.py 的 A）
    放置的规则      external/kernel_m1_3406/main.py 的 FIXED（旧系统 3406 批次的写法），v2/geom3d.py、v2/collar_rule.py、
                   v2/config_v2a.yaml 里的常数，各项的 test_source 写了是哪一处

原内核的 14 个设计项里，h_cut（截骨面到头心的距离）和 e（入口偏移）挪到了放置设定里：
《设定的声明和包的清单》第六节把“截骨面的高低”“入口”写在放置设定里。剩下 12 个是柄的形状，都由一批点逐个给。
原来 e 可以写一个数，也可以写 "rule"（由生产规则在九档里选）。拆开以后写成两项：entry 选怎么定，entry 是 fixed 时才有 e。

原项目里写死的那几项（放置的规则、选号的界）没有上下限。声明里给它们的范围是放宽了的、物理上说得通的界，
只用来拦明显写错的值；不是研究过的可行范围。

4c 打包时改了两处（2026-11-18）：
    去掉了 penetration_tol_mm（允许的皮质穿透 0.25 mm）。它照的是 v2/geom3d.py 的 TOL，但那个量只用在没有距离场的解析股骨上；
    3406 带距离场，模板化里用的是写死的 0.05 mm 数值容差，柄面离内膜面多远由设计项 m（皮质余量）管。声明了也用不上，所以不留。
    加了 section_points（柄截面取几个点）。它只管交出的柄的实体怎么分片：原项目划不成网格时会换它重建柄再试（40、24、72），
    拆开以后柄的实体由柄空间包定，所以这一项归这里，可以每个点给。

不写进声明、算作这个柄空间本身的（换了这些就是另一个柄空间包）：
    平端的帽高 1.5 mm（main.py 的 CAP_H）；无领（阶段 9 起 collar_w 固定为 0）；截面是四象限超椭圆加楔形（geom3d.py）；
    放得下的数值容差 0.05 mm（geom3d.template）；假体颈底面伸出柄的截口不超过 2 mm² 才算落在截口里（collar_rule.py）；
    假体头的半径 14 mm、柄的材料 Ti6Al4V（E 110 GPa，ν 0.3）：v2/config_v2a.yaml 的 prosthesis.head_radius_mm、materials.titanium。
"""
from __future__ import annotations

PHASES = "原项目 v2/stage_neckopt.py PHASES[11] 的 vars（3406 上的设计空间，阶段 13 沿用）"
DESIGN_A = "设计 A：旧数据库 v0.14 的 sb13_a105_91e458e3"
FIXED = "external/kernel_m1_3406/main.py 的 FIXED（旧系统 3406 批次的写法）"

# 设计 A 的 12 个形状项（tests/science/test_fea.py 的 A）
A = {"L": 43.06123448163271, "rho_tip": 0.21170926745980978, "q": 2.9987468989565968, "lam": 1.118611091375351,
     "g_ml": 0.5421065539121628, "g_ap": 0.4619918614625931, "n_a": 4.55768808722496, "n_p": 2.8643375262618065,
     "tau_a": -0.3, "tau_p": -0.24825596250593662, "alpha": 44.35368996113539, "m": 0.5}


def _shape(name, label, meaning, group, low, high, unit="1"):
    return {"name": name, "label": label, "meaning": meaning, "group": group, "type": "number", "unit": unit,
            "range": {"min": low, "max": high}, "per_point": True, "required": True, "test": A[name],
            "test_source": f"{DESIGN_A}；范围：{PHASES}"}


DESIGN = {
    "name": "design",
    "groups": ["长度", "面积沿柄的变化", "截面形状", "插入角", "皮质余量"],
    "items": [
        _shape("L", "柄长", "肩部到尖端的长度", "长度", 20.0, 45.0, "mm"),
        _shape("rho_tip", "尖端面积比", "尖端和肩部的截面积之比：截面积沿柄降低多少", "面积沿柄的变化", 0.10, 0.50),
        _shape("q", "面积降低指数", "截面积沿柄递减的曲线形状：大于 1 近端先快速收小，小于 1 保持粗壮到远端才收", "面积沿柄的变化", 0.5, 3.0),
        _shape("lam", "宽厚比", "截面的内外侧宽和前后厚之比", "截面形状", 1.0, 2.2),
        _shape("g_ml", "内侧占宽的比例", "截面内侧半宽占内外侧宽的比例", "截面形状", 0.35, 0.65),
        _shape("g_ap", "前方占厚的比例", "截面前半厚占前后厚的比例", "截面形状", 0.35, 0.65),
        _shape("n_a", "前半的超椭圆指数", "截面前半的方正程度：2 圆润，6 方正", "截面形状", 2.0, 6.0),
        _shape("n_p", "后半的超椭圆指数", "截面后半的方正程度：2 圆润，6 方正", "截面形状", 2.0, 6.0),
        _shape("tau_a", "前半的楔形斜度", "截面前半的厚度随内外侧线性变化：正的是内侧厚", "截面形状", -0.30, 0.30),
        _shape("tau_p", "后半的楔形斜度", "截面后半的厚度随内外侧线性变化：正的是内侧厚", "截面形状", -0.30, 0.30),
        _shape("alpha", "插入角", "冠状面内柄轴和股骨干轴的夹角，正的是远端偏外侧；头心复位时等于假体颈干角减 130°", "插入角", 15.0, 45.0,
               "deg"),
        _shape("m", "皮质余量", "柄面到内膜面的最小距离，选号时取满足它的最大号；负的是允许压入皮质", "皮质余量", 0.5, 2.0, "mm"),
    ],
}


def _rule(name, label, meaning, group, kind, test, source, **more):
    return {"name": name, "label": label, "meaning": meaning, "group": group, "type": kind, "per_point": False, "required": True,
            "test": test, "test_source": source, **more}


def _choices(*pairs):
    return [{"value": value, "label": label} for value, label in pairs]


PLACEMENT = {
    "name": "placement",
    "groups": ["截骨", "颈轴", "入口", "选号", "柄的实体"],
    "items": [
        {"name": "h_cut", "label": "截骨高度", "meaning": "截骨面到股骨头心的距离，沿颈轴量。原内核里它是设计项", "group": "截骨",
         "type": "number", "unit": "mm", "range": {"min": 16.0, "max": 32.0}, "per_point": True, "required": True, "test": 16.0,
         "test_source": f"{DESIGN_A}；范围：{PHASES}（用户 2026-10-23 定从头心下 16 mm 起搜索）"},
        _rule("ref_cut_mm", "去骨量的截骨参照", "算截掉的骨时从这个高度算起：截骨面比它浅的记 0，只数它和截骨面之间的骨", "截骨",
              "number", 16.0, f"{FIXED}；阶段 11 定的", unit="mm", range={"min": 0.0, "max": 60.0}),
        _rule("neck_axis", "颈轴怎么定", "放柄、截骨都沿颈轴。isthmus 是从头心到颈最细截面的质心，迭代到截面垂直于轴", "颈轴", "choice",
              "isthmus", f"{FIXED}；v2/femur_3406.py 的 DEFAULT_NECK_AXIS（用户 2026-10-24 采纳）",
              choices=_choices(("isthmus", "头心到颈最细截面的质心"), ("detector", "检测器给的轴"), ("readme", "模型骨说明书上的轴"),
                               ("silhouette", "冠状面投影轮廓的最窄弦中点"))),
        _rule("entry", "入口怎么定", "肩部中心在截骨面上偏离截骨中心多少：rule 是在几档偏移里选放得下的最大号，fixed 是照 e", "入口",
              "choice", "rule", f"{DESIGN_A}（e 写的是 rule）",
              choices=_choices(("rule", "在几档偏移里选"), ("fixed", "固定在 e"))),
        {"name": "e", "label": "入口偏移", "meaning": "肩部中心偏离截骨中心多少，沿截骨面内指向内下", "group": "入口", "type": "number",
         "unit": "mm", "range": {"min": -8.0, "max": 8.0}, "when": {"entry": ["fixed"]}, "per_point": True, "required": True,
         "test": 0.0, "test_source": "v2/config_v2a.yaml templating.offsets_mm 的中间一档；范围是那几档的两头"},
        _rule("offset_min_mm", "偏移最小的一档", "entry 是 rule 时，在几档偏移里选：最小的一档", "入口", "number", -8.0,
              "v2/config_v2a.yaml templating.offsets_mm；v2/collar_rule.py 的 np.arange(-8.0, 8.1, 2.0)", unit="mm",
              range={"min": -20.0, "max": 20.0}, when={"entry": ["rule"]}),
        _rule("offset_max_mm", "偏移最大的一档", "entry 是 rule 时，在几档偏移里选：最大的一档", "入口", "number", 8.0,
              "同上", unit="mm", range={"min": -20.0, "max": 20.0}, when={"entry": ["rule"]}),
        _rule("offset_step_mm", "偏移的档距", "entry 是 rule 时，相邻两档偏移差多少。-8 到 8 每 2 mm 一档，就是九档", "入口", "number", 2.0,
              "同上", unit="mm", range={"min": 0.0, "max": 20.0, "min_open": True}, when={"entry": ["rule"]}),
        _rule("collar_rule", "选号的规则", "无领：假体颈的底面要整个落在柄的截口里，放不下就换号或换入口偏移", "选号", "choice",
              "neck_in_shoulder", f"{FIXED}；v2/collar_rule.py（用户 2026-10-07 定）",
              choices=_choices(("neck_in_shoulder", "假体颈底面落在柄的截口里"))),
        _rule("neck_radius_mm", "假体颈的半径", "肩部截面至少要 π·r² 才放得下假体颈；比这小判放不进去", "选号", "number", 7.0,
              f"v2/config_v2a.yaml prosthesis.neck_radius_mm；{FIXED} 的 min_A0 = π·7²", unit="mm",
              range={"min": 0.0, "max": 20.0, "min_open": True}),
        _rule("margin_check", "皮质余量查得多密", "dense 是截骨面下每 0.25 mm 一环的严格检查；sparse 是原来稀的那种", "选号", "choice",
              "dense", f"{FIXED}；用户 2026-10-24 采纳（B1 重放：候选池 1750 → 1542）",
              choices=_choices(("dense", "截骨面下每 0.25 mm 一环"), ("sparse", "原来的稀疏取样"))),
        _rule("area_min_mm2", "肩部面积的下界", "选号时在这个面积区间里二分，取放得下的最大号：下界", "选号", "number", 20.0,
              "v2/geom3d.py 的 A_BOUNDS[0]", unit="mm2", range={"min": 0.0, "max": 5000.0, "min_open": True}),
        _rule("area_max_mm2", "肩部面积的上界", "选号时二分的上界。3406 的髓腔截口大，上界 900 会判“髓腔比最大号还大”", "选号", "number",
              2000.0, f"{FIXED} 的 a_bounds_max（阶段 11 定的）", unit="mm2", range={"min": 0.0, "max": 5000.0, "min_open": True}),
        _rule("bisection_iters", "二分几次", "选号时肩部面积二分的次数", "选号", "integer", 14, "v2/geom3d.py template 的 iters",
              range={"min": 1, "max": 40}),
        _rule("min_tip_area_mm2", "尖端的最小面积", "尖端截面积比它小判“太细”（约 Ø 3.9 mm）", "选号", "number", 12.0,
              "v2/geom3d.py 的 MIN_TIP_AREA", unit="mm2", range={"min": 0.0, "max": 200.0}),
        {"name": "section_points", "label": "柄截面取几个点", "meaning": "交出的柄的实体是过各截面上这么多个点的曲线放样出来的。"
         "点数只改实体怎么分片，不改模板化的结果；划不成网格时可以换一个再试", "group": "柄的实体", "type": "integer",
         "range": {"min": 12, "max": 144}, "per_point": True, "required": True, "test": 40,
         "test_source": "v2/model3d_m1.py build 的 attempts：第一次用 40，划不成网格时换 24、72 重建柄再试"},
    ],
    "relations": [{"less": "offset_min_mm", "than": "offset_max_mm"}, {"less": "area_min_mm2", "than": "area_max_mm2"}],
}

DECLARATIONS = [DESIGN, PLACEMENT]
