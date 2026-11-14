"""科学验收用的算例和线。只写在这一处；每条后面写着它是哪来的，完整的理由和文献在 docs/四样的决定.md。

这些是照文献和旧项目的实测先定下的，等你看过、改过才算数。
"""

# ---------------------------------------------------------------- FEA

LAME = {"h": 2.0, "delta": 0.10, "mu": 0.0}     # 对照算例：厚壁圆筒压配，r 8、R 20 mm，松质 400 MPa，过盈 0.10 mm
LAME_ANALYTIC_MPA = 2.970                        # 这个算例的解析解（Lamé）。写在这里是为了发现算例本身被改了
LAME_REL = 0.03                                  # 反推的界面压力和解析解的相对差。旧项目自己的线是 5%，实测 −0.2%

FORCE_BALANCE = 1e-3                             # 界面上骨侧接触力之和对外载的相对差。文献里常用 0.5%，实测 2e-6
LOAD_N = 2391.0                                  # 加上去的合力大小（旧项目的工况：约 3 倍体重）
LOAD_REL = 1e-6

# 设计 A（旧数据库 v0.14 里的 sb13_a105_91e458e3）和旧系统的同一行比。差用 log10 算（dex）。
# 同一个设计重划一次网格，这几个量的差大约 0.012 dex：线定在它的两到三倍
LEGACY_JOB = "sb13_a105_91e458e3"
VS_LEGACY_DEX = {"rot_first_deg": 0.03, "rot_rev_deg": 0.03, "f1_p95_um": 0.04, "f1_first_p95_um": 0.04}
VS_LEGACY_REL = {"bone_total_mm3": 0.001}

# ---------------------------------------------------------------- 重建（3406，CAD 骨源）

# 参考值：旧系统在这根骨上的结果，你在旧项目里核过的那一套（femur_3406 的烤进去的坐标系和检测器）
RECON_REFERENCE = {
    "head_center": (50.66, 1.67, 109.13), "head_radius_mm": 25.76,
    "neck_axis": (0.91390, 0.06263, 0.40108), "shaft_axis": (-0.0225, 0.0197, 0.9996),
    "neck_shaft_angle_deg": 112.43, "lesser_trochanter_below_head_mm": 48.0,
    "neck_isthmus_area_mm2": 904.0, "neck_isthmus_from_head_mm": 23.3,
}
# 线：CAD 骨源比 CT 分割干净，所以比文献里 CT 上的重复性收得紧（Fischer 2020、Cerveri 2010、Sangeux 2015）
RECON = {
    "head_center_mm": 0.5, "head_diameter_mm": 1.0, "neck_axis_deg": 2.0, "shaft_axis_deg": 1.0,
    "neck_shaft_angle_deg": 2.0, "lesser_trochanter_mm": 5.0, "isthmus_area_rel": 0.02, "isthmus_position_mm": 1.5,
}
# 合理范围：出了范围多半是几何有破口、或者标志点的定义不对
RECON_SANE = {
    "neck_wall_mm": (0.3, 5.0),                  # 股骨颈处皮质的厚度（Treece 等的 CT 皮质厚度图）
    "neck_shaft_angle_deg": (110.0, 145.0),      # 成人的颈干角
    "mesh_volume_error": 0.01,                   # 表面三角网围出的体积和实体自己报的体积的相对差
    "bone_volume_cm3": (300.0, 900.0),           # 皮质加松质：成人股骨整根的体积
}

# ---------------------------------------------------------------- 代理

# 留出误差用 log10 上的均方根差（dex）。FE 自己的噪声底大约 0.012 dex，再准也准不过它
SURROGATE = {
    "rmse_good": 0.05,            # 不超过它：好
    "rmse_usable": 0.10,          # 不超过它：能用，下结论要拿 FE 复核
    "rmse_unusable": 0.15,        # 超过它：不能用
    "r2_good": 0.90, "r2_usable": 0.80,
    "coverage": (0.90, 0.99),     # 名义 95% 的区间，实际覆盖率该落在这里
    "outside_ok": 0.10,           # 往外推的那一组：不超过它算能往外推
    "outside_limited": 0.20,      # 不超过它：有限度地往外推，要 FE 确认；再大就不行
}
