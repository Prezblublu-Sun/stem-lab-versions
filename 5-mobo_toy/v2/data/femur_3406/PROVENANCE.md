# v2/data/femur_3406 来源与变换（烘焙于 2026-10-23 17:05:22，gmsh 4.15.2）

| 输出 | 来源 | 来源 SHA256 | 输出 SHA256 |
|---|---|---|---|
| `3406R_cortical.STEP` | `H:\projects\application\research-log\sawbone_3406_2026-10-23\churun_uncut_export\Cortical_AP214.STEP` | `63bac3ce9cf8a8cbda031420df6d34ba72b15f907a2b980b6d3c755748597752` | `9b1bf9494728c3533c9cd04db8669008c97dd88701ffea56cd7e12e6bd8cab1f` |
| `3406R_cancellous.STEP` | `H:\projects\application\research-log\sawbone_3406_2026-10-23\churun_uncut_export\Cancellou_AP214.STEP` | `416aba5430afabd5e13ecee189e912cf7ffa6994926eb9b4870824af801094f2` | `f478e1b4b5e79c2b52046ae578d377210a9f4e23efa0a1da0444d7c531969318` |

- 来源：Churun Lin 的未切割 Sawbones 3406（左股骨）Parasolid → 本机 SolidWorks 2025 转 STEP AP214（2026-10-23，见
  `H:/projects/application/research-log/sawbone_3406_2026-10-23/README_3406模型来源与核对_2026-10-23.md` 与 `churun_uncut_export/convert_log.txt`）。
- 变换：**只把 z 取反**，S = diag(1, 1, −1)，用 `gmsh.model.occ.affineTransform`；原生系 x 内侧、y 后方、z 远端（左股骨）
  ⇒ 烘焙后 x 内侧、y 后方、z 近端，并且左→右镜像。
- 为什么不用 README 的 A 系（x, −y, −z）：A 系是绕 x 转 180°，保持左股骨手性、+y 变成前方。计入哈希的代码假定
  右股骨且 +y 后方：`femur_real.landmarks` 取 argmax(y) 为后髁、前倾角符号 = −(u·ey)、`RealFemur.ant = (0, −1, 0)`，
  `model3d_v2.load_vector` 的 Bergmann → 模型符号也写死了 +y 后方（model3d_m1 按名导入同一函数）。A 系会让髁检测和载荷符号都错。
- 验收（重新导入）：皮质 271529.5 mm³ / 869 面，
  松质 128493.8 mm³ / 159 面；
  fragment(皮质, 松质) → 共享面 147 个（松质 159 面中），
  体积不变（271529.9 / 128493.8 mm³）。
  目标：271 529 / 127 952 mm³（±0.01 %）、869 / 155 面、147 个共享面。
- 原生体积：皮质 271529.4，松质 127956.2 mm³
  （gmsh 对裁剪 B 样条体积偏低约 4 %，与 SolidWorks 的 271.5 / 127.9 cm³ 一致）。
- 皮质壳是**开放**的（远端横销孔连通髓腔），无封闭的内膜空腔；松质芯（含头、颈）与皮质在同一坐标系，界面共形。
- **松质芯原件里有一条导针孔**（2026-10-23 发现）：半径 ≈ 2.29 mm、
  长 96.9 mm 的贯通孔，沿颈部从外侧皮质界面穿到头部芯表面
  （烘焙坐标 bbox [-14.5, -0.2, 71.0] …
  [71.4, 4.2, 122.2]，轴向
  [0.869, 0.007, 0.495] ⇒ 颈干角 ≈ 120°、前倾 ≈ 0°、离头心约 2 mm），
  由两张 97 × 4.4 mm 的条带面和两端的环面组成（gmsh 面号 [1, 153, 154, 155]）。
  泡沫芯没有这种孔：留着它，距离场在颈部多一道"墙"（模板化判穿透）、网格在柄旁留薄片。烘焙时在孔内并入一根圆柱
  （半径 2.49 mm，两端各退 0.3 mm 不伸进皮质）：
  松质体积 127951.9 → 128493.8 mm³
  （孔体积 542 mm³），
  面数 155 → 159；两端在皮质内表面下各留一个 ≤ 3 mm 深的盲窝（开口是斜的）。原件未动（research-log 里）。
- 数据不进 git（`.gitignore: v2/data/**/*.STEP`）；校验和在 `SHA256SUMS.txt`，`femur_3406.py` 的配置里也写死同样的 SHA256。
- 完整报告：`bake_report.json`。
