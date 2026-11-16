"""从 M1-3406-v1 拆出来的 Abaqus 有限元包的声明（fem）。拆内核 4b 写的，4d 打包时放进包的清单。

照 Abaqus 分组：材料和截面、网格、相互作用、分析步、边界条件、载荷、初始条件、输出、作业和求解控制（约束这一组 M1 没有用到）。
照的是原项目在 3406 上生产时的设定（原项目只读：H:\\projects\\Femoral implant generation\\sandbox\\mobo_toy）：
    原来的 8 个条件     external/kernel_m1_3406/build.py 的 conditions：每个点能变（per_point 是 true）。测试轮的取值是旧内核的基线
                       （main.py 的 _baseline_conditions），和设计 A 在旧数据库里用的条件一样（tests/science/test_fea.py 的 CONDITIONS）
    写死的建模、求解设置  v2/model3d_m1.py（单元、接触、分析步、输出）、v2/config_v2a.yaml（载荷、网格、界面），
                       和 main.py（FIXED 里的 fric_only、罚摩擦的弹性滑移、Abaqus 的核数）。各项的 test_source 写了是哪一处
原来写在导出设定里的几项：slip_tol 改写成弹性滑移 elastic_slip_um（原来不写就是 0.00025 × 2 / h，即弹性滑移约 0.5 µm）；
abaqus.cpus 是这里的 cpus；abaqus.timeout_s 和 Abaqus 启动器放在哪，只管怎么跑，不在这里（见 plugins/fea/running.py 和机器清单）。

柄和骨的材料来自柄的模型和骨模型，不在这里；E_canc_MPa 是研究里每个点覆盖骨模型某个区域的模量（原来的条件）。
原项目里写死的那几项没有上下限。声明里给它们的范围是放宽了的、物理上说得通的界，只用来拦明显写错的值。

不写进声明、算作这个有限元包本身的（换了这些就是另一个有限元包）：
    M1 的界面做法：界面节点复制一份给柄侧，摩擦模型用孪生节点加接触对（v2/model3d_m1.py）；与皮质相邻的节点不施过盈。
"""
from __future__ import annotations

MODEL = "v2/model3d_m1.py"
CONFIG = "v2/config_v2a.yaml"
BASELINE = "external/kernel_m1_3406/main.py 的 _baseline_conditions（设计 A 在旧数据库里用的也是这一组）"
BERGMANN = "Bergmann et al. 2016（PLoS One 11:e0155612，Table 5）上楼 AVER75 峰值时的方向角，写在 v2/config_v2a.yaml load"


def _item(name, label, meaning, group, kind, test, source, per_point=False, required=True, **more):
    return {"name": name, "label": label, "meaning": meaning, "group": group, "type": kind, "per_point": per_point,
            "required": required, "test": test, "test_source": source, **more}


def _choices(*pairs):
    return [{"value": value, "label": label} for value, label in pairs]


FEM = {
    "name": "fem",
    "groups": ["材料和截面", "网格", "相互作用", "分析步", "边界条件", "载荷", "初始条件", "输出", "作业和求解控制"],
    "items": [
        # ---- 材料和截面
        _item("E_canc_MPa", "松质的模量", "覆盖骨模型里 override_region 那个区域的弹性模量（3406 是泡沫芯）", "材料和截面", "number", 155.0,
              f"{BASELINE}：Sawbones 第四代 PCF 20 泡沫的厂家值", per_point=True, unit="MPa",
              range={"min": 0.0, "max": 30000.0, "min_open": True}, abaqus="*ELASTIC（这个区域的材料）"),
        _item("override_region", "覆盖模量的区域", "E_canc_MPa 盖掉的是骨模型里的哪个区域", "材料和截面", "ref",
              {"ref": "bone.region.cancellous"}, f"{MODEL}：E_canc 改的是松质（CANC）那一块", refers=["bone.region"]),
        # ---- 网格
        _item("element", "单元类型", "骨和柄都用这种单元", "网格", "choice", "C3D10", f"{MODEL}：inp.elements(\"C3D10\", …)",
              choices=_choices(("C3D10", "十节点二次四面体")), abaqus="*ELEMENT, TYPE=C3D10"),
        _item("h_int_mm", "界面处的网格尺寸", "柄和骨的界面上单元多大", "网格", "number", 2.0,
              f"{BASELINE}；{CONFIG} mesh.h_int_mm（生产网格由 S2′ 收敛研究定）", per_point=True, unit="mm",
              range={"min": 0.0, "max": 10.0, "min_open": True}),
        _item("h_far_mm", "远处的网格尺寸", "离界面远的地方单元多大", "网格", "number", 6.0, f"{CONFIG} mesh.h_far_mm", unit="mm",
              range={"min": 0.0, "max": 30.0, "min_open": True}),
        _item("dist_min_mm", "过渡开始的距离", "离界面这么近以内用界面处的尺寸", "网格", "number", 0.5, f"{CONFIG} mesh.dist_min_mm",
              unit="mm", range={"min": 0.0, "max": 50.0}),
        _item("dist_max_mm", "过渡结束的距离", "离界面这么远以外用远处的尺寸，中间逐渐变大", "网格", "number", 15.0,
              f"{CONFIG} mesh.dist_max_mm", unit="mm", range={"min": 0.0, "max": 100.0, "min_open": True}),
        # ---- 相互作用
        _item("models", "解哪几个模型", "只解柄和骨之间带摩擦的那个模型（3406 批次的做法）；原项目另有界面粘接的模型，这个包还不做", "相互作用",
              "choice", "friction", "external/kernel_m1_3406/main.py 的 FIXED fric_only（阶段 11 起只有五分之一的设计带粘接模型）",
              choices=_choices(("friction", "只解摩擦的模型"))),
        _item("contact_faces", "柄上接触的面", "柄的模型里和骨接触的那一组面", "相互作用", "ref", {"ref": "stem.faces.interface"},
              f"{MODEL}：柄侧的接触面 S_STEM（柄身截骨面以下的表面）", refers=["stem.faces"]),
        _item("normal", "法向行为", "法向是硬接触：接触上就不许穿透，分开就没有力", "相互作用", "choice", "hard",
              f"{MODEL} 的 contact_block", choices=_choices(("hard", "硬接触"))),
        _item("sliding", "滑动的写法", "界面上的相对滑动按小滑动算", "相互作用", "choice", "small", f"{MODEL} 的 contact_block",
              choices=_choices(("small", "小滑动"))),
        _item("tangential", "切向行为", "摩擦怎么算：罚摩擦允许一点弹性滑移，拉格朗日不许", "相互作用", "choice", "penalty",
              f"{MODEL} 的 DEFAULTS（lagrange 是 False）", choices=_choices(("penalty", "罚摩擦"), ("lagrange", "拉格朗日"))),
        _item("mu", "摩擦系数", "柄和骨之间的库仑摩擦系数", "相互作用", "number", 0.3, f"{BASELINE}；{CONFIG} interface.mu",
              per_point=True, unit="1", range={"min": 0.0, "max": 1.0}, abaqus="*FRICTION 的摩擦系数"),
        _item("elastic_slip_um", "弹性滑移", "罚摩擦允许的弹性滑移。Abaqus 的 SLIP TOLERANCE 取它除以界面处的网格尺寸", "相互作用", "number",
              0.5, "external/kernel_m1_3406/main.py 的 SLIP_TOL_AT_H2 = 0.00025，界面网格 2 mm 时就是 0.5 µm，网格变了照比例换",
              unit="um", range={"min": 0.0, "max": 10.0, "min_open": True}, when={"tangential": ["penalty"]},
              abaqus="*FRICTION, SLIP TOLERANCE"),
        # ---- 分析步
        _item("cycles", "加载循环数", "消过盈、释放之后，加载、卸载交替几次：2 次就是 LOAD、UNLOAD、LOAD2", "分析步", "integer", 2,
              f"{BASELINE}；{MODEL} 的 build 默认 2", per_point=True, range={"min": 1, "max": 10},
              abaqus="*STEP 的序列：PRESSFIT、RELEASE、LOAD、UNLOAD、LOAD2……"),
        _item("nlgeom", "几何非线性", "分析步里算不算几何非线性", "分析步", "bool", False,
              f"{MODEL} 的 *STEP 没写 NLGEOM，Abaqus/Standard 默认关", abaqus="*STEP, NLGEOM"),
        _item("max_increments", "每步最多几个增量", "一个分析步里最多试多少个增量", "分析步", "integer", 1000, f"{MODEL}：*STEP, INC=1000",
              range={"min": 1, "max": 100000}, abaqus="*STEP, INC"),
        _item("initial_increment", "起始的增量", "每一步的第一个增量占这一步的多少", "分析步", "number", 0.25,
              f"{MODEL}：*STATIC 0.25, 1., 1e-08, 1.", unit="1", range={"min": 0.0, "max": 1.0, "min_open": True},
              abaqus="*STATIC 的第 1 个数"),
        _item("min_increment", "最小的增量", "增量缩到比它小还不收敛，这一步就算失败", "分析步", "number", 1e-08,
              f"{MODEL}：*STATIC 0.25, 1., 1e-08, 1.", unit="1", range={"min": 0.0, "max": 1.0, "min_open": True},
              abaqus="*STATIC 的第 3 个数"),
        _item("max_increment", "最大的增量", "一个增量最多占这一步的多少", "分析步", "number", 1.0, f"{MODEL}：*STATIC 0.25, 1., 1e-08, 1.",
              unit="1", range={"min": 0.0, "max": 1.0, "min_open": True}, abaqus="*STATIC 的第 4 个数"),
        # ---- 边界条件
        _item("distal", "远端怎么约束", "骨在远端截断，截断面上的节点三个方向都固定", "边界条件", "choice", "fixed",
              f"{MODEL}：*BOUNDARY FIXED, 1, 3", choices=_choices(("fixed", "远端截断面固定"))),
        # ---- 载荷
        _item("load_N", "关节力的大小", "加在头上的合力", "载荷", "number", 2391.0,
              f"{BASELINE}；{CONFIG} load.resultant_N（v1 的合力，介于 Bergmann 2016 AVER75 2232 N 和 HIGH100 3606 N 之间）",
              per_point=True, unit="N", range={"min": 0.0, "max": 20000.0, "min_open": True}, abaqus="*CLOAD"),
        _item("load_front_deg", "冠状面的倾角", "合力在冠状面里和干轴的夹角", "载荷", "number", 20.0, f"{BASELINE}；{BERGMANN}",
              per_point=True, unit="deg", range={"min": -90.0, "max": 90.0}),
        _item("load_sagit_deg", "矢状面的倾角", "合力在矢状面里和干轴的夹角", "载荷", "number", 18.0, f"{BASELINE}；{BERGMANN}",
              per_point=True, unit="deg", range={"min": -90.0, "max": 90.0}),
        _item("load_point", "关节力打在哪", "合力的作用点。头心复位：假体头心就是股骨头心", "载荷", "ref", {"ref": "bone.landmark.head_center"},
              f"{MODEL}：HEADN 是柄上离股骨头心 head_coupling_radius_mm 以内的节点", refers=["bone.landmark", "stem.feature"]),
        _item("load_spread_mm", "关节力分到多大范围", "合力平均分到柄上离作用点这么远以内的节点上", "载荷", "number", 14.0,
              f"{CONFIG} load.head_coupling_radius_mm（和假体头的半径相同）", unit="mm", range={"min": 0.0, "max": 50.0, "min_open": True},
              abaqus="*CLOAD 加在节点集 HEADN 上"),
        # ---- 初始条件
        _item("delta_mm", "松质界面的过盈", "柄和松质之间的径向过盈：压配的程度", "初始条件", "number", 0.10,
              f"{BASELINE}；原项目阶段 13 定的（v2/stage_neckopt.py PHASES[13]）；{CONFIG} interface.delta_mm", per_point=True,
              unit="mm", range={"min": 0.0, "max": 1.0}, abaqus="*CLEARANCE 给初始过盈，*CONTACT INTERFERENCE, SHRINK 在 PRESSFIT 步里消掉"),
        _item("interference_method", "过盈怎么给", "clearance 是几何不动、逐节点给初始过盈；offset 是把柄侧节点沿法向挪出去", "初始条件", "choice",
              "clearance", f"{MODEL} 的 DEFAULTS（2026-09-29 Lamé 对照选的 clearance：界面法向位移更均匀）",
              choices=_choices(("clearance", "逐节点给初始过盈"), ("offset", "柄侧节点沿法向挪出去"))),
        # ---- 输出
        _item("field_outputs", "场输出", "每一步要哪些节点和单元的量", "输出", "choices", ["U", "RF", "S", "E", "ELSE", "EVOL"],
              f"{MODEL} 的 FIELD_M1", choices=_choices(("U", "位移"), ("RF", "反力"), ("S", "应力"), ("E", "应变"), ("ELSE", "单元应变能"),
                                                       ("EVOL", "单元体积")), abaqus="*NODE OUTPUT、*ELEMENT OUTPUT"),
        _item("contact_outputs", "接触输出", "每一步要哪些接触的量", "输出", "choices", ["CSTRESS", "CDISP", "CSTATUS", "CFORCE", "CNAREA"],
              f"{MODEL} 的 CONTACT_M1",
              choices=_choices(("CSTRESS", "接触应力"), ("CDISP", "接触位移"), ("CSTATUS", "接触状态"), ("CFORCE", "接触力"),
                               ("CNAREA", "接触面积")), abaqus="*CONTACT OUTPUT"),
        # ---- 作业和求解控制
        _item("cpus", "核数", "一次求解用几个核", "作业和求解控制", "integer", 5,
              "external/kernel_m1_3406/main.py 的 _solve_command 默认 5（原项目在这台 8 核 16 线程上开 3 个求解槽、各 5 核）",
              range={"min": 1, "max": 64}, abaqus="abaqus job=… cpus="),
    ],
    "relations": [{"less": "dist_min_mm", "than": "dist_max_mm"}, {"less": "h_int_mm", "than": "h_far_mm"},
                  {"less": "min_increment", "than": "initial_increment"}],
}

DECLARATIONS = [FEM]
