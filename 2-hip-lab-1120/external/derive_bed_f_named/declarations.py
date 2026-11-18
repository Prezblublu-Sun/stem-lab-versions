"""床支撑 F 的推导量设定的声明（derive）。拆内核 4e 写的，打包时放进包的清单（external/derive_bed_f_named/build.py）。

床支撑 F = 对柄身（不在领上）的界面节点里落在支撑区内的那些，求 面积 / max(泡沫厚度, 下限) 之和，单位 mm。
支撑区在哪，用名字引用指柄的模型和骨模型里有名字的点和轴；区的大小是数。

照的是旧系统在 3406 上的那一套（旧系统只读：H:\\projects\\Femoral implant generation\\sandbox\\mobo_toy）：
    tools/db_export.py 的 BED_F 和 bed_support，ops/facts.json 的 bed_F_*，b28 起各批判定文件里的 mesh_F；
    external/derive_bed_f/bed_f.json 是同一组数（给参照包那条用的旧的包）。
旧常数都写在旧系统的“模型坐标”里（原点在骨干轴上小转子那一层，z 沿干轴，x 由后髁连线定）。它们各是什么：
    cref     设计 A 的截骨中心：股骨头心沿颈轴往远端 16 mm（v2/femur_real.py：C03 = H − cut_from_head_mm·u3，A 的截骨高度是 16）。
             旧系统里所有设计都用这一个点，不跟着各自的截骨面走
    u_neck   颈轴，指向头（research-log geometry.json 的 neck_axis.u，留了 5 位小数）
    n3       远端方向投到颈截面上、指向股骨距一侧（femur_real.py 的 n3，留了 3 位小数）。算的时候再投到垂直柄轴的面上，当 0 度的方向。
             柄轴、颈轴、n3 都在颈平面里，所以它投出来就是柄的内侧方向（femur_real.pose 的 e_ml），和颈轴投出来的是同一个方向
    P0、ax   柄的位姿（肩部中心、柄轴），旧系统从点云里拿

和旧写法不一样的一处：旧代码里 90 度的方向用的是旧模型坐标的 y 轴（后方，由后髁连线定），它和 0 度的方向不垂直
（设计 A 上夹角 87.3°），所以旧的支撑区整个往前偏了约 1.4°。骨模型第 1 版没有后髁的标志点，这个方向没有名字可指；
这里量的是绕 angle_axis 的几何角度。同一份点云上，设计 A 的 F 因此大 0.4% 到 1.0%。

范围是放宽了的、几何上说得通的界，只用来拦明显写错的值；不是研究过的范围。
"""
from __future__ import annotations

OLD = "external/derive_bed_f/bed_f.json（旧系统 tools/db_export.py 的 BED_F、ops/facts.json 的 bed_F_*）"
POSE = "旧系统 tools/db_export.py 的 bed_support：柄的位姿 P0（肩部中心）、ax（柄轴）取自点云；拆开以后从柄的模型拿"


def _item(name, label, meaning, group, kind, test, source, per_point=False, **more):
    return {"name": name, "label": label, "meaning": meaning, "group": group, "type": kind, "per_point": per_point,
            "required": True, "test": test, "test_source": source, **more}


DERIVE = {
    "name": "derive",
    "groups": ["支撑区的深度", "支撑区绕柄轴的范围", "泡沫厚度"],
    "items": [
        # ---- 支撑区的深度
        _item("zone_from", "深度从哪个点量起", "支撑区的深度从这个点起、沿 depth_axis 往远端量。这个点先沿 depth_axis 往远端挪 zone_offset_mm，"
              "挪到的地方是参照点", "支撑区的深度", "ref", {"ref": "bone.landmark.head_center"},
              f"{OLD} 的 cref：设计 A 的截骨中心，就是股骨头心沿颈轴往远端 16 mm；旧系统里所有设计都用这一个点。"
              "要参照点跟着每个点自己的截骨面走，写 stem.feature.neck_base，zone_offset_mm 写 0",
              refers=["bone.landmark", "stem.feature"]),
        _item("zone_offset_mm", "参照点往远端挪多少", "zone_from 那个点沿 depth_axis 往远端挪这么多，才是量深度的参照点", "支撑区的深度",
              "number", 16.0, f"{OLD} 的 cref = 头心 − 16·颈轴：16 mm 是设计 A 的截骨高度，也是放置设定里去骨量的截骨参照 ref_cut_mm",
              per_point=True, unit="mm", range={"min": 0.0, "max": 100.0}),
        _item("depth_axis", "深度沿哪根轴量", "深度逆着这根轴的方向量。颈轴从颈底指向头，所以往远端是正的", "支撑区的深度", "ref",
              {"ref": "stem.axis.neck_axis"},
              f"{OLD} 的 u_neck：颈轴，指向头。就是柄空间包放柄、截骨用的那根颈轴，也是截骨面的法向", refers=["stem.axis"]),
        _item("zeta_max_mm", "支撑区多深", "参照点以下（逆着 depth_axis）不超过这么深的节点才算", "支撑区的深度", "number", 15.0,
              f"{OLD} 的 zeta_max_mm", per_point=True, unit="mm", range={"min": 0.0, "max": 200.0, "min_open": True}),
        # ---- 支撑区绕柄轴的范围
        _item("angle_axis", "角度绕哪根轴量", "节点绕这根轴的角度，从 angle_from 定的 0 度方向量起；这根轴过的那个点是量角的中心",
              "支撑区绕柄轴的范围", "ref", {"ref": "stem.axis.stem_axis"}, POSE, refers=["stem.axis"]),
        _item("angle_from", "0 度朝哪", "这根轴的方向投到垂直 angle_axis 的面上，是 0 度的方向。颈轴投出来朝内侧，就是股骨距那一边",
              "支撑区绕柄轴的范围", "ref", {"ref": "stem.axis.neck_axis"},
              f"{OLD} 的 n3：远端方向投到颈截面上、指向股骨距一侧，再投到垂直柄轴的面上当 0 度。柄轴、颈轴、n3 都在颈平面里，"
              "所以它和颈轴投出来的是同一个方向（柄的内侧）", refers=["stem.axis"]),
        _item("theta_max_deg", "支撑区多宽", "0 度两侧各这么多度以内的节点才算", "支撑区绕柄轴的范围", "number", 45.0,
              f"{OLD} 的 theta_max_deg", per_point=True, unit="deg", range={"min": 0.0, "max": 180.0, "min_open": True}),
        # ---- 泡沫厚度
        _item("t_floor_mm", "泡沫厚度的下限", "柄面到髓腔壁的泡沫比它薄的，按它算：免得贴着皮质的几个节点把和撑爆", "泡沫厚度", "number", 0.25,
              f"{OLD} 的 t_floor_mm", per_point=True, unit="mm", range={"min": 0.0, "max": 10.0, "min_open": True}),
    ],
}

DECLARATIONS = [DERIVE]
