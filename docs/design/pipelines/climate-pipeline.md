# 气候引擎实现架构

> 本文档描述 dreamulator 气候引擎的模块职责、执行顺序、各阶段物理细节与输出格式。
> 组织方式：§1 模块与调用方 → §2 按真实执行顺序的总流程 → §3–§8 各阶段细节
> （温度/气压/风场/洋流/降水/Köppen）→ §9–§11 集成与导出 → §12–§14 验证/限制/后续。
> 对应源码：`src/dreamulator/engine/climate_physics.py`、`climate_seasonality.py`、
> `monsoon_circulation.py`、`src/dreamulator/map/climate_simulator.py`、`ocean_circulation.py`。
> 物理公式见 [knowledge/climatology/energy_balance.md](../../knowledge/climatology/energy_balance.md)
> （EBM/水汽收支）与 [knowledge/climatology/ocean_currents.md](../../knowledge/climatology/ocean_currents.md)（Stommel）。

---

## 目录

1. [架构总览](#1-架构总览)
2. [执行顺序](#2-执行顺序)
3. [温度](#3-温度)
4. [气压（季风强迫）](#4-气压季风强迫)
5. [风场](#5-风场)
6. [洋流](#6-洋流)
7. [降水](#7-降水)
8. [Köppen 分类](#8-köppen-分类)
9. [DAG 引擎封装 `climate.py`](#9-dag-引擎封装-climatepy)
10. [地形管线集成](#10-地形管线集成)
11. [图层导出与输出格式](#11-图层导出与输出格式)
12. [验证方法](#12-验证方法)
13. [已知限制与调优方向](#13-已知限制与调优方向)
14. [GCM 与参数化管线的定位、后续开发](#14-gcm-与参数化管线的定位后续开发)

---

## 1. 架构总览

### 时间基准约定（M2-A0④ 审计，2026-09-18）

气候引擎同时使用两种时间基准，**每个量的基准如下表固定**；比率类量（AI、Köppen
比）的分子分母必须同窗：

| 量 | 时间基准 | 说明 |
|----|---------|------|
| 水汽预算全部通量（E、P、W/τ、κ 扩散） | **率 / 365.25 天参考年** | 单位约定而非物理年长——`mm/yr` 始终指「365.25 天当量的率」；物理时间尺度（τ=9 天驻留、平流 e 折长度 u·τ）用真实秒 |
| 月度场（`climate_monthly.msgpack` 的 T/P/ΔP/风） | 参考年月（30.44 天当量） | 年率的 /12 切片；nacrea「月」≠ 当地历法月（当地月 = 轨道年/12 = 8.33 天），跨世界比较见 UCC 提案 |
| PET（沉降干旱门 `potential_evapotranspiration_hamon`） | **率 / 365.25 天参考年**（`_DAYS_PER_REFERENCE_MONTH`） | M2-A0④ 修复：此前喂轨道月（`orbital_period/12`）使 PET 变成轨道年累计，AI = P(参考年率)/PET(轨道年累计) 混窗——Earth 无感（两基重合），nacrea（100 天年）AI 偏湿 ×3.65 |
| Budyko 陆地再循环 `E_land = E_pot·P/(E_pot+P)` | 率 / 参考年 | E_pot 走 `evaporation_rate`（同预算基）✓ 内部一致 |
| 土壤水桶（`soil_bucket_monthly`） | mm / 参考月（P 与 E_pot 同为年率/12） | 桶内 P、E、R、S 全部同月基——容量 C（mm）是绝对储量，与月基通量直接可比 |
| 太阳几何/季节（赤纬、年内日序、季节 EBM 相位、ITCZ 迁移） | **当地轨道时间**（`orbital_period_days`） | 物理量，随世界变化 ✓ |
| Köppen 阈值（mm/yr、mm/月经验线） | Earth 校准应用于参考年率 P | 声明为 Earth 惯例分类（Earth 校准值本就是地球年总量，与参考年率基对 Earth 重合）；异星当地年累计归 UCC |
| 生态 Miami NPP / Whittaker（消费 P） | 同 Köppen 惯例 | Earth 年校准 + 参考年率基；当地年口径待生态线复核 |

修复后 AI 在所有世界同窗比较；Earth 逐位不变（其轨道年 = 参考年）。

**模块清单**（三个纯函数库 + 一个编排器 + 两个挂载件 + 三个入口/出口件）：

- `engine/climate_physics.py` — 纯物理函数库：温度链（辐射平衡/温室/直减率）、风场输入
  （三圈环流、地形阻挡、Coriolis）、蒸发（Clausius–Clapeyron）、Köppen 分类器。无 I/O、
  无 RNG，全部函数接收 numpy 数组、系数经参数传入。
- `engine/climate_seasonality.py` — 辐照季节模型 + 一维能量平衡模型（North 1975 Legendre
  谱方法）+ Held-Hou（1980）单圈剖面 + 季节 EBM（显式热输送）。
- `engine/monsoon_circulation.py` — 季风链纯函数：月度纬向平均基准、海陆热力对比气压
  异常、边界层动量平衡风、跨赤道季风西风带。
- `map/climate_simulator.py` — 主编排器 `simulate_climate()`：在 CVT mesh 上按 §2 的
  Stage 顺序执行全链并把结果写回 `VoronoiCell` 字段。
- `map/ocean_circulation.py` — 洋流三步（Stommel 流函数、SST 平流、涌升），在 Stage 2.5
  挂载；也提供风场分解（东/北分量基）等切空间工具。
- `map/stationary_wave.py` — ④ 定常波响应 v1 求解器（roadmap ④，已否证保留）：默认
  关闭的已接线组件，见 §5.6。
- `map/stationary_wave_two_level.py` — ④ v2 两层 Gill 响应（Lee-Wang-Mapes 2009 两模态
  模型，k-块对角带状求解 + 下沉干燥门消费），见 §5.6。
- `map/climate_config.py` — 世界气候配置加载（`terrain_config.yaml` + 行星物理参数解析），
  是诊断脚本的统一配置入口（`load_climate_config`）。
- `engine/climate.py` — DAG 引擎封装 `ClimateEngine`：`dreamulator build` 气候层的
  独立入口（§9）。
- `map/export.py` — 图层导出（PNG / koppen.json / metadata / 月度 msgpack，§11）。

**调用方**：

| 调用方 | 入口 | 场景 |
|--------|------|------|
| 地形管线 | `terrain_pipeline.py:433`（Stage 6） | `dreamulator build <world>` 主路径：geological 层在管线内顺跑气候 |
| DAG 引擎 | `ClimateEngine.run()`（`climate.py:155`） | 独立重建气候层（`--only climate` / 分支气候分叉） |
| 验证器 | `src/dreamulator/validate_climate.py` | 内存重建后逐格对观测基准 |
| 诊断脚本 | `scripts/climate/diagnose_*.py` | 经 `climate_config.load_climate_config` 加载与构建完全相同的配置 |

无论从哪个入口进来，调参文件都是同一个 `terrain_config.yaml`（climate 分支的在
`layers/geological/input/` 下，随 `find_input` 沿层级链向上继承）——独立气候构建与地形
管线因此不会分叉（`climate.py:100-115` 注释）。

---

## 2. 执行顺序

`simulate_climate(mesh, config)`（`climate_simulator.py:82`）是一个单遍函数，按下列顺序
执行。行号是 `climate_simulator.py` 的锚点；每步的物理细节在 §3–§8 展开。控制台输出按
6 个相位显示进度（`1/6`–`6/6`）。

1. **准备**：从 `mesh.cells` 提取 elevation / 纬度 / 海陆掩码 / 3D 节点。海陆判定用
   地质管线的 `water_class`（连通性洪泛写入；裸 `elevation >= 0` 会把低于海平面的内流
   盆地误判为海洋，`climate_simulator.py:122-131`）；大洋级内陆湖（`is_lake`）单列
   （:139）。
2. **Stage 1 温度**（相位 1/6，:150）——产出年平温度场 `t_mean_C`：
   辐射平衡 + 温室 → 全球均温锚点（:154-160）→ 年平纬向剖面（1D EBM 或 Held-Hou 单圈，
   :173-238；副热带下沉增温以「存档增量」形式记在 `_dt_subsidence` 上，:225）→ 年均冰
   反照率反馈（:280）→ 海洋按 SST 剖面覆写、季节冰湖保留陆地温度（:287-309）→ 沿海
   调节（:311-331）→ 年平向风海洋平流 4.1-B（:339-357）→ 海拔直减率（:359-381）→
   向星半球增温（:384-389）。细节 §3.1–§3.5。
3. **季节块**（无相位号，:391-449）——产出月度温度 `t_monthly_C`：地表热容量（海/陆/
   沿海/湖分型，:394-406）→ `compute_seasonal_climate` 解季节 EBM（:407）→ **B0c 数据
   契约**：月度序列以 Stage-1 年平场重新定水平（EBM 的振幅保留、水平值换成含直减率/
   平流/SST 的年平场，:439）→ 季节冰湖 0 °C 冰点钳（:447）。细节 §3.6。
4. **Stage 2 风场**（相位 2/6，:452）——产出月度风 `wind_monthly[12]` 与年风 `wind`：
   三圈环流背景（ITCZ 位置年均，:486）→ 月度气压异常 ΔP（B2 海陆对比，:502）→
   500 km 尺度分离平滑（:517）→ 图上最小二乘梯度（:520）→ 边界层动量平衡月度风异常
   （:530）→ 组装 `wind_monthly = 背景 + 跨赤道西风带 + 季风异常`（:564）→ 逐月地形
   阻挡（:568）→ **年风 = 12 个月度场的矢量平均**（B0b 契约，:585）→ 写回 cell 的
   年风东/北分量（:601-603）→ 月度 4.1-B 海洋调节（距平式，修改 `t_monthly_C` 的季节
   形状、保年均水平，:617-630）。
   有向边表与邻域平均算子在此建一次、后续共用（:460-471）。细节 §4、§5。
5. **Stage 2.5 洋流**（相位 3/6，:633，`ocean_currents_enabled` 门控）——SST 修正后的
   `t_mean_C` 回流给后续蒸发与 Köppen：风应力（镜像约定，:662-663）→ 逐海盆 Stommel
   流函数（< 20 cell 的小盆跳过，:686）→ semi-Lagrangian SST 平流（:711）→ 洋流/距平
   写回 cell（:723-727）→ 涌升 SST 修正（:731）→ 洋向陆温度距平平流（:744-761）。
   细节 §6。
6. **Stage 3 降水**（相位 4/6，:764）——产出年降水 `precipitation_mm` 与月度
   `p_monthly`：`_compute_precipitation_monthly_budget` 逐月质量守恒水汽收支（:770）。
   若 `stationary_wave_enabled`（默认 false），在此追加 ④ 两趟定点回路：pass-1 降水 →
   定常波 ΔSLP → 重解风场 → 重解水汽收支（:799-872）。细节 §7、§5.6。
7. **Stage 4 Köppen 分类**（相位 5/6，:882）——产出 `koppen_codes`：先做分类所需的
   月度极值预计算（最干/最湿月、暖/冷半降水，:894-900）→ **Stage 3.5 下沉增温的干旱
   度门控释放**（降水已知后从 `t_monthly_C` 扣回，:902-936）→ **单一温度权威终聚合**
   （湖冰钳 → 年温/极值从月序导出，:947-952）→ 月度场暂存到 mesh 私有属性供导出
   （:958-974）→ `koppen_classify`（:976-993）。细节 §3.7、§3.8、§8。
8. **写回**（相位 6/6，:995-1005）：逐 cell 写 `temperature_C` / `precipitation_mm` /
   `koppen_class` / 月度极值 / `distance_to_coast_km` 等 `VoronoiCell` 字段。

风向/洋流的下游消费者：年风场写回 `wind_east_m_s` / `wind_north_m_s`（:601-603），
洋流写回 `ocean_current_east_m_s` / `ocean_current_north_m_s` / `sst_anomaly_c`
（:723-727），经 `cvt_mesh.json` 进入前端。

---

## 3. 温度

### 3.1 全球锚点与年平纬向剖面

`equilibrium_temperature` 从恒星光度/轨道距离/反照率算黑体平衡温度，
`surface_temperature` 加温室效应得到全球均温 `t_surf_C`——一切温度场的绝对水平由它
锚定（:154-160）。太阳常数按光度与距离缩放后共享给 EBM 与季节模型（:164）。

年平纬向剖面按 `ebm_1d` 分三路（:173-277）：

- **`ebm_1d=true` + `hadley_extent_deg ≥ 90`（单圈体制，慢自转）**：`solve_held_hou_temperature`
  解 Held & Hou (1980) 四次方剖面（平坦副热带 + 极冠），温差 ΔT ∝ Ω²。翻转环流把陆海
  均质化，无单独的陆地扩散率。**E1（2026-09-16）**：其后接 `apply_eddy_relaxation`——
  HH 是无涡旋轴对称极限，慢自转涡旋残差（nacrea Ω=0.318 处 ≈ 地球峰值的 50%，
  Kaspi & Showman 2015 Fig 8b）把剖面进一步向全球均温弛豫：Legendre 模态衰减
  `θ_n → θ_n/(1 + D_eddy·n(n+1)/B)`（n≥1，n=0 不动保均值；与 EBM 同机器），
  `D_eddy = 0.69·D_land·min(1,Ω)^0.6`（0.69 与 α=0.6 均从 Fig 8b 推导；
  交叉佐证 = design-notes 0008 的斜压 onset 超临界性 a/L_R 2.4 vs 7.8）。
  nacrea 走这条路（其 terrain_config.yaml 设 `ebm_1d: true` +
  `hadley_extent_deg: 90`）。
- **`ebm_1d=true` + 三圈体制（类地）**：`solve_1d_ebm_temperature` 解 North (1975) 谱
  方法一维 EBM——`0 = D d/dx[(1−x²)dT/dx] + Q(x)(1−α) − (A+B·T)`，x = sin φ，Legendre
  模态闭式解 `T_n = [Q_n(1−α) − A δ_n0] / [B + D n(n+1)]`
  （`climate_seasonality.py:276`）。倾角/偏心率/近日点进辐照项。陆地用大气份额扩散率
  `ebm_diffusion_land_wm2k`（默认 0.28 ≈ 0.8× 总输送 0.35）并乘 Ω^0.3 标度
  （Kaspi & Showman 2015，:196-208）——更暖的副热带 + 更冷的极地 = **大陆度**。
  副热带下沉增温（`subsidence_warming_c`，:219-233）：扩散 EBM 的经向输运纯降梯度，
  会把副热带扩散冷；真实 Hadley 环流的下沉支反而加热它。把 Hadley 胞内向胞面积加权
  均温弛豫（胞缘 ~8° 过渡带），**增量先存档在 `_dt_subsidence`**，待 Stage 3.5 按干旱
  度门控释放（§3.7）——下沉增温物理上只属于干燥下沉支。earth 走这条路（其
  terrain_config.yaml 设 `ebm_1d: true` + `hadley_extent_deg: 30` 观测锚定）。
- **`ebm_1d=false`（legacy，无世界在用）**：`latitude_temperature` sin² 剖面 +
  `diffuse_heat_graph` 图扩散（可选 `lat_gradient_from_omega` 自动梯度），函数保留仅为
  兼容（:239-277）。

**Hadley 边界的确定（P3，2026-09-16）**：`hadley_extent_deg = 0`（默认）= 从
Held-Hou 热罗斯贝数定律推导 `φ_H ≈ R_t^{1/2}`（`hadley_extent_from_rotation`，
R_t = 2gHΔ_H/(Ω²a²)，Δ_H 由 `radiative_equilibrium_contrast` 从世界自身日射推出；
Guendelman & Kaspi 2019）。地球推导 23.3°、nacrea 恰好打满 90° 上限——但推导值贴
体制悬崖（R_t=2.49 对阈值 2.467），两世界均显式钉住（earth 30 = 观测锚，
nacrea 90 = GCM PoC mass-streamfunction 证据），推导值作新世界默认。极胞起点被钳到
≥ Hadley 边界（防重叠）。

年均冰反照率反馈（`ice_albedo_feedback`，:280）在剖面上追加，默认 earth 配置走季节版
（§3.6）。**E2（2026-09-16）**：冰增量 `_t_ice_increment` 在此归档——斜压带（§7）
读「最终场 − 冰增量」（陆格），风暴带不再追冰缘跑（反馈是响应不是强迫）。

### 3.2 海洋与内陆湖下垫面

海洋 cell 被 `_ocean_surface_temperature` 的「阻尼纬向梯度剖面」覆写——剖面
锚定在行星全球均温上：地球强迫下重现地球 SST 剖面，恒星强迫/温室变化时整体 1:1 平移
（:287-294）。**E4（2026-09-16）过程化世界偏差**：锚定形状是地球*观测*（内含地球
OHT），照搬到异星是隐式地球标定——传入 `config` 时叠加过程化偏差

`T_world = anchor(lat) + [EBM_OHT(world; D_OHT) − EBM_OHT(earth_ref; D=0.37)]`

其中柱扩散 `D_OHT = 0.37 × [0.65 + 0.35·P^0.3]`（海洋份额 0.65 风驱不随 Ω 标度 +
大气份额 Ω^−0.3，Trenberth & Caron 2001 分解）；地球强迫下偏差恒为零（同参数自消，
零回归风险），两个 EBM 解都锚定同一 `t_surf_c`（偏差不带全球均值漂移）。nacrea
效果：极地海温 +5~7°C、赤道 −3~4°C（其 9° 倾角的 n=2 辐射四极模比地球弱 23%，
赤道相对均温抬升更小——真实物理）。

大洋级内陆湖（`water_class == "ocean"` 且 `is_lake`，如里海/五大湖）不是深海洋热库：
**季节冰湖**（年平陆地温度 ≥ 0 °C）保留陆地 EBM 温度 + 陆地热容量 + 冬季 0 °C 冰点钳
——淡水湖与大陆气温平衡，五大湖冬天 ~0 °C 而不是纬向海温剖面的 +12 °C；**永冻湖**
（年平 < 0 °C）保留开阔洋 SST——海冰面已是正确的冻结表面（:295-309）。

### 3.3 海洋影响向内陆的输送（两道）

- **沿海调节**（各向同性）：海平面陆地温度向最近海洋 SST 弛豫，内陆按
  `coastal_moderation_scale_km`（默认 500 km）指数衰减；在直减率**之前**施加，高冰盖仍
  冷；冰覆海洋 SST ~−2 °C 使其自动冰感知（:311-331，距离场来自
  `_graph_distance_to_coast` :1318）。
- **年平向风海洋平流 4.1-B**（方向性）：陆地年温向**上风向**海洋的 SST 弛豫，按
  `maritime_advection_scale_km`（默认 1500 km，气团 e 折长度，Berg 1944）衰减——盛行
  西风把海洋暖量送进中纬大陆。冰门：年温 < −10 °C 的极地冰盖不参与（避免被冷洋面
  「加热」，:339-357）。**月度孪生 = 距平式**（Stage 2 末尾，§5.4、:617-630）：把陆地
  季节距平向上风向海洋的距平阻尼——年均水平严格不变（年水平的职权属于带冰门的年平
  版，两孪生不双重计费），形状效应 = 深内陆冬暖/夏凉（莫斯科型冬季过冷的解法），
  同时阻尼陆地过大的季节振幅（§13 振幅族的技术债同向受益）。

### 3.4 海拔直减率

仅陆地、仅海平面以上（低于海平地的「陆地」cell——冰盖基岩、内流盆地、中心落在陆架
上的岛 cell——钳到 h = 0，避免把 −2.9 km 洋底采样外推成 +19 °C 热点，:370-381）。
`variable_lapse_rate=true`（默认）时直减率随温度分型：湿绝热——暖空气释放潜热 → 热带
高原 ~4.7 °C/km，极地冰盖 ~6.5 °C/km（`moist_lapse_rate`，:359-369）。

### 3.5 向星半球增温

潮汐锁定卫星（nacrea 的 Aegis 红外 + 反射光）的向星面加热：以 `sub_planet_longitude_deg`
为中心的余弦衰减，幅度 `sub_planet_warming_c`（:384-389）。

### 3.6 季节块（月度温度）

1. **地表热容量** `seasonal_heat_capacity`（:394-406）：陆地/海洋分型 + 沿海过渡
   （`seasonal_coastal_scale_km`）；季节冰湖换成湖面热容量（~10 m 温跃层——大陆振幅
   被水的惯性缓和）。
2. **季节 EBM** `compute_seasonal_climate`（:407，实现在 `climate_seasonality.py`）：
   月度辐照驱动 + 冰反照率开关。季节振幅
   `T_amp = ΔQ_ω(1−α) / √(B_eff² + (ωC)²)`，其中 `B_eff = B + 6D`
   （`climate_seasonality.py:511`）——显式热输送在主导季节模态（四极模 n=2，n(n+1)=6）
   上的阻尼，取代旧标定常数；相位滞后 `tan φ = ωC/B_eff`。夏季冻结 cell 保留冰反照率
   → 振幅缩小，区分冰盖（EF）与副极地（Dfc）。**E1（2026-09-16）**：D 与年 EBM 调用方
   同源 Ω 标度（`0.35 × P^0.3`，地球 P=1 不变；慢自转大胞更快抹平季节距平）。
3. **B0c 交接**（:430-442）：季节 EBM 自带辐射/热容量循环但**没有海拔维**——高原
   cell 会落在海平面等效的纬向温度上（安第斯 4 km：月均 +16 °C vs 年平 −3.3 °C），毒化
   t_hot/t_cold、月度蒸发与月度展示层。契约：**月度序列的形状/振幅取 EBM，水平值平移
   到 Stage-1 年平场**（`t_monthly += t_mean − mean(t_monthly)`，均匀平移使 min/max 重推
   是精确变换，:439-442）。这是年平链给月序定水平的**唯一**位置——交接之后月度序列
   是唯一权威，导出年温由终聚合重新导出（§3.8）。
4. **湖冰钳**（:447-449）：淡水湖冬季表面停在冰点（冰盖封住辐射失热），不跟大陆的
   零下循环——物理常数，非地球标定。

### 3.7 下沉增温的干旱度门控释放（Stage 3.5，执行于降水之后）

Stage 1 存档的 `_dt_subsidence`（§3.1）在降水已知后释放（:902-936）：下沉增温物理上
属于干燥下沉支——在湿润的副热带边缘会被湿对流与蒸发冷却抵消。**只有 Köppen 干旱比
与 UNEP P/PET（Hamon，`potential_evapotranspiration_hamon`）双判据都判湿润的低地才
释放**（`subsidence_aridity_gate`，结点钉在 Köppen BW/BS 与干湿边界上，无新增调参
量）；高地 ≥ 1.5 km 恒保留；赤道上升支的负增量（湿对流性质）不释放。均匀平移保持
季节振幅与暖/冷半月排序，Köppen 预计算数组仍有效。

单遍近似：Stage 2–3 消费的是释放前温度——这正是 T↔P 定点耦合要移除的不自洽
（`climate_simulator.py:913-915` 自引；见
[proposals/climate-steady-coupling.md](../proposals/climate-steady-coupling.md) 与 §14）。

### 3.8 单一温度权威：终聚合（切片 6，astra §2.2 目标架构）

导出的年温场是**导出量**：季节湖冰钳先作用于月序，然后
`t_mean_C = ⟨t_monthly_C⟩`、`t_cold/t_hot = 月序 min/max`——月度序列是温度的唯一
权威，恒等式 ⟨t_monthly⟩ ≡ `temperature_C` 由构造成立（**含湖 cell**，旧的
「终重定心 → 再冰钳」顺序在湖 cell 上破坏恒等式），与风场 B0b 契约（§5.4）同规则。

B0c 交接（§3.6）之后的修正分两类：

1. **双场水平对齐**（CLIM-01 同步平移）——Stage 2.5 洋流三步（SST 平流/涌升/洋向陆
   距平平流）与 Stage 3.5 下沉释放：年场与月序同加一个增量，恒等式逐阶段保持，
   Stage 3 的年/月消费方看到同一水平。
2. **仅作用月序**——湖冰钳（冬季月抬到 0 °C，净为正）与月度 4.1-B 海洋调节（§3.3，
   **距平式**——由构造严格保均值，只改季节形状不产生净漂移）。湖冰钳的净效应经终
   聚合**流入**年温，不再被重定心从月序反向抹除（旧顺序把漂移量从每个月扣回）。
   4.1-B 月度孪生曾是水平式弛豫——与 Stage 1 年平版构成双重计费（同一弛豫施加两次，
   净增温经聚合流入年温），距平式和解终结了这个矛盾（孪生和解，2026-09-19）。

Stage 3.5 释放只作用月序（年温与极值由本节聚合重新导出，无手工簿记）。降水（Stage 3）
在本聚合**之前**完成——年温的变化不回灌 P/ET，T↔P 的双向一致性归
[proposals/climate-steady-coupling.md](../proposals/climate-steady-coupling.md)。

---

## 4. 气压（季风强迫）

季风的驱动场是**月度海陆热力对比气压异常 ΔP**（技术债 23 / M4 链，纯函数在
`engine/monsoon_circulation.py`）。

> **正典 ΔP 定义（M2-A0③，2026-09-18）**：任何「月度气压异常」字段
> （引擎 `pressure_monthly`、obs 导入器、前端 `spatialReference` 的 ΔSLP）一律 =
> **该月 SLP − 同月·同纬 5° 带·海洋格点平均**（海陆对比语义、含年平结构）。单一
> 实现于 `import_earth_climate.ocean_band_anomaly_monthly`（obs 侧共用）；引擎侧
> `pressure_anomaly_monthly` 的 ΔT 参考即此语义（B2 海洋参照）。2026-09-18 前的
> obs 侧另有两套不一致定义：导入器减本地年均、spatialReference 减全经度平均——
> 已废弃。

链条四步（执行于 Stage 2 内）：

1. **纬向平均基准**（`zonal_mean_monthly`，`monsoon_circulation.py:188`）：逐月、按
   符号纬度带（5°）求纬向平均温度。
2. **气压异常**（`pressure_anomaly_monthly`，:247，调用在
   `climate_simulator.py:502`）：ΔT = 细胞温度 − 同纬度纬向平均（**B2 海洋参照**：
   按符号分带使南北半球不互染；**全值含年平**——B0b 契约不扣年平，月度 ΔP 全海陆
   对比 → 月度风 → 矢量平均 = 年风，年风因此携带定常海陆结构——冬季西伯利亚高压 ≫
   夏季热低压）。静力响应：ΔP = −P_sfc·E·ΔT/T̄，E ≈ 0.10（边界层投影因子 r=0.6 ×
   线性衰减积分 3.2 km）。地球检验：ΔT = +5 K → −4.3 hPa，与亚洲夏季热低压同量级。
3. **尺度分离平滑**（`_smooth_graph` :1038，调用 :517）：51 km 网格的海陆镶嵌让原始
   异常场的梯度被海岸线噪声主导——气压异常在天气尺度（Rossby 变形半径，O(500 km)）
   上静力/地转调整。Jacobi 平滑到 `_MONSOON_PRESSURE_SMOOTHING_KM` = 500 km
   （:1564；pass 数 = 2·(500/cell_km)²，每 pass 是一步惰性随机游走）；大陆热低压
   （1000–4000 km 宽）存活，镶嵌噪声不存活。**未平滑的 raw 场保留**：④ 定常波分量
   在平滑前叠加（§5.6）。
4. **梯度**（`_graph_least_squares_gradient` :1066，调用 :520）：逐 cell 最小二乘拟
   合、单位「每弧度」除以行星半径换算 Pa/m——不用加权差分（幅度依赖网格间距）。

---

## 5. 风场

### 5.1 背景：三圈环流（年均）

`_seasonal_mean_cell_wind`（:1159，调用 :486）给出完整的地表纬向风场（信风/中纬西风/
极地东风），胞界是行星参数（慢自转得到扩张的 Hadley 胞），环流跟随 ITCZ 的**年均**
位置。地转（热成）风分量已移除：模型没有动力副热带高压，θ 热成风在所有纬度都是东风、
只会削弱 Ferrel 西风，而裸地表气压梯度（测高 exp(−h/H)）在陆上加 ~30 m/s 的地形噪声
（:475-485）。

### 5.2 跨赤道季风西风带（月度）

`cross_equatorial_monsoon_wind`（`monsoon_circulation.py`，调用 :549-563）：量级用可
推广标度 ε·Ωa·sin(φ_itcz_max)（D/F 子项 2，替换 f·v_n/k_d 的地球特调），随 ITCZ 逐月。
在跨赤道带内**只替换背景纬向风**为西风、保留背景经向辐合结构——恢复索马里急流/几内亚
湾西风的水汽通道而不移动辐合带。这是**唯一保留逐月的胞圈项**：胞圈本身的逐月迁移
（每用自己的 ITCZ 偏移环流）会把辐合带锐化成扫掠雨带、使副热带过度季节化（Csa/Dsb
膨胀），v1 不含（技术债 24；经向支 + 季风槽北移已否证，见 proposal §5）。

### 5.3 边界层动量平衡（月度异常）

`monsoon_boundary_layer_wind`（`monsoon_circulation.py:331`，调用 :530）：对 §4 的
ΔP 梯度解

```
0 = −∇ΔP/ρ − f k̂×v − k_d·v
```

局地东/北分量闭式解。两个极限：f→0（赤道）退化为沿梯度直流——跨赤道季风气流的涌现
机制；k_d→0 退化为地转风（北半球低压在风向左侧，Buys-Ballot）。拖曳率按地表分型
（`monsoon_circulation.py:130-131`）：水面 `_DRAG_RATE_S` = 1e-5 s⁻¹（C_D ≈ 1.3e-3）、
粗糙植被 `_DRAG_RATE_LAND_S` = 2e-4 s⁻¹（~20× 水面；k_d = C_D·|U|/h_BL，可推导量）。
陆面拖曳防止 f→0 退化 v = G/k_d 在赤道陆地上把风放大到 ~20 m/s（亚马逊 ~1 m/s，见
[atmospheric_circulation.md](../../knowledge/climatology/atmospheric_circulation.md) §4.5）。

### 5.4 月度组装与年风契约（B0b）

```
wind_monthly[m] = 三圈背景 + 跨赤道西风带[m] + 季风异常[m]   (:564)
wind_monthly[m] ← 地形阻挡（逐 cell 标量缩放，线性）           (:568)
wind = wind_monthly.mean(axis=0)                              (:585)
```

年风 = 12 个月度场的**矢量平均**——观测定义本身（NCEP 年气候态就是月风的矢量平均）。
B0b 契约（技术债 24）：**月度场是主、年场是导出**，恒等式由构造保证。所有年消费方
（cell 存储、Stommel 链、4.1-B 平流、年水汽预算、海岸不对称步）读这同一个源
（:575-585）。

组装后紧接：年风东/北分量写回 cell（:599-603，切空间基 `east_north_basis`）；
**月度 4.1-B 平流**（:617-630）——陆地月度温度向上风向海洋的**月度**温度弛豫（同
§3.3 的年平版，衰减长度同 `maritime_advection_scale_km`），暖化深大陆冬季。

### 5.5 风向约定（镜像）

引擎内部风场统一**物理约定**（真东基 = 经度增加方向，对 NCEP 校验；技术债 24 根部
统一）。唯一例外：**标定过的洋流链**（Stommel/涌升/距平平流）吃的是 legacy 镜像约定
——根部翻转会连锁打反整链符号，故在 Stage 2.5 入口做一次 `_to_physical_wind`
involution 换回镜像（:653-662、:1965、:2050-2058）。

### 5.6 ④ 定常波两趟回路（v1 默认关；v2 两层 Gill 已实施，默认关）

**v1**：`stationary_wave_enabled = false`。开启时在 Stage 3 内跑两趟定点
（`climate_simulator.py` ④ 块）：pass-1 降水 → 柱潜热 → 定常线性正压涡度方程
（`map/stationary_wave.py::compute_slp_wave_anomaly`，Sardeshmukh & Hoskins 1988 /
Rodwell & Hoskins 2001）→ ΔSLP_wave 叠加到 raw ΔP 上重过「平滑 → 梯度 → 边界层风」链
→ 重解水汽收支。趟间欠松弛（`stationary_wave_relaxation` = 0.5）。v1 保真度不足（地表
温度热成风基本态代理），机器保留待 v2（真高层基本态），细节见
[proposals/climate-layer-improvement.md](../proposals/climate-layer-improvement.md) §2
「定常波响应」。

**v2（2026-09-17，与 v1 互斥）**：`stationary_wave_v2_enabled = false`
（`pipeline_types.py`）。开启时走 Lee-Wang-Mapes 2009 两模态模型
（`map/stationary_wave_two_level.py::compute_omega_wave_anomaly`）：pass-1 P → Q̇
（`precip_to_heating`）→ 扣纬向环均值 → k-块对角带状求解（zonal 平均基本态 → 经度
rFFT 后按 wavenumber 块对角，0.16 s/月）→ 中层 w = −p_m∇²χ̂/(ρ_m·g) → **陆地
k_rain 下沉干燥门**（`climate_physics.subsidence_rainout_gate`，质量守恒乘性调制，
与 storm/SST 门在 `_compute_precipitation_monthly_budget` 的 `omega_gate_monthly`
钩子复合）→ 重解水汽收支。**风场保持 pass-1**（v1 的 ΔSLP→BL 风 1/f 放大路径不
再消费）。求解器全验证（Case-1 退化 Matsuno-Gill/Case-4 反气旋对/R&H ω 签名三基本
态不变号/慢自转波导加宽，`tests/test_stationary_wave_two_level.py` 14 项）；消费门
2026-09-17 标定无信号（强迫自引用——模型沙漠湿偏差加热淹没 R&H 下沉），结点保守
弱斜率，待供给端沙漠 P 偏差修复后重标定（`diagnose_desert_wetness --wave-gate`，
存档驱动）。

---

## 6. 洋流

> 详细物理（Ekman / Sverdrup / Stommel / 海峡闸门）见
> [knowledge/climatology/ocean_currents.md](../../knowledge/climatology/ocean_currents.md)。

Stage 2.5 挂载（风场之后、降水之前），单向单遍——不做 SST↔风的迭代回耦合。
`ocean_currents_enabled` 门控（:639）。三步（`map/ocean_circulation.py`）：

1. **Stommel 流函数解**（`solve_ocean_gyre`，调用 :695）：风应力（镜像风，:662-663）→
   旋度（`compute_curl_z`）→ 对每个海盆（`detect_ocean_basins`，< 20 cell 的小盆跳过
   ：686-693）解 β 平面摩擦涡度方程，西边界强化（WBC）作为摩擦边界层**自然涌现**
   （不手贴 ×3 系数）。流函数形式在赤道无 1/f 奇点（β = 2Ωcosφ/a 在赤道最大）——
   nacrea 慢自转（Ω=0.31Ω⊕）下地转求逆会除零，流函数是唯一全程良态的极小模型。
   **E4 亚网格 WBC 增速**（`apply_subgrid_wbc_boost`，:705-708）：解析急流速度
   `u_jet = ψ_max/(R/β)`（Stommel 边界层宽 δ=R/β——地球 ~62 km / nacrea ~165 km，
   均 ≲ 3 格）注入强化核（|ψ| ≥ 0.9·ψ_max，方向不变、封顶 25×）——图拉普拉斯数值
   粘性把边界层摊过数格，解析值恢复真实急流量级（观测湾流/黑潮 100–250 cm/s）。
   喂 SST 平流与存储/显示场；Sverdrup 内区不动（增幅下限 1）。
2. **SST 沿流平流修正**（`advect_sst_semilagrangian`，:711）：semi-Lagrangian 沿流溯源
   弛豫（时间尺度 `ocean_sst_advection_days`），暖流增温/寒流降温；修正后的 SST 写回
   `t_mean_C`，进入 Stage 3 蒸发与 Stage 4 Köppen（:721）。
3. **涌升**（`compute_upwelling_index` + `apply_upwelling_sst_correction`，:731-734）：
   风应力旋度 → 沿岸上升流 → 东边界冷舌（`ocean_upwelling_enabled` 门控）。

之后**洋向陆温度距平平流**（`advect_temperature_anomaly`，:744-761）：SST 距平（含涌
升）沿盛行风向平流到下风向海岸（带符号：暖的西边界流暖化下风向海岸，冷的东边界流冷
化），取代旧的各向同性图扩散耦合。

逐 cell 洋流字段（`ocean_current_east_m_s` / `ocean_current_north_m_s` / `sst_anomaly_c`）
写入 `VoronoiCell`（:723-727），经气候回写进入 `cvt_mesh.json`，前端本地烘焙流线。

**配置**（`TerrainPipelineConfig` 的 `Ocean` 小节）：`ocean_currents_enabled`、
`ocean_drag_coefficient`、`ocean_mixed_layer_depth_m`（H_ml）、`ocean_bottom_friction_s`
（Stommel R，调 WBC 比）、`ocean_sst_advection_days`（τ）、
`ocean_temperature_diffusivity`（D₀）、`ocean_coastal_influence_km`、
`ocean_upwelling_enabled`。

**已知局限**（极向热输送弱 / 西边界流急流被网格抹平 / SST 距平结构偏弱 / 半封闭海）
单一事实源 = [proposals/climate-layer-improvement.md](../proposals/climate-layer-improvement.md) §4。

---

## 7. 降水

`_compute_precipitation_monthly_budget`（:1988，调用 :770）——**逐月质量守恒的柱水汽
收支方程**（`_solve_moisture_budget` :1599，公式见 energy_balance.md §8），逐月求解
12 次（月度风场 + 月度温度驱动的蒸发与对流雨出），年降水为 12 个月之和：

```
∇·((1−φ)·W u) + k_rain(x)·W − ∇·(κ∇W) = E          （柱水汽稳态收支）
P = k_rain(x)·W + P_oro + P_route                     （格点年降水率）
k_rain(x) = (1/τ)·(1+storm)·gate(ΔSST)·pickup(W/W_sat)·coastal·subplanet ,  τ = 9 d
φ = 1 − exp(−max(Δz − z_LCL, 0)/H_cc)                 （上坡边的地形凝结份额）
H_cc = R_v·T² / (L_v·Γ) ≈ 2.0–2.6 km                  （CC 抬升干燥尺度）
P_oro[i] = Σ_{e: 上坡入流边→i} φ_e·|c_e|·W[上游格]     （迎风地形凝结雨）
P_route[i] = Σ_{i 的入流边} share·k·(W_j − W_sat_j)⁺   （冷阱超额的上风路由雨）
```

各项含义：**W** = 柱水汽（可降水量，mm）；**u** = 地表风（m/s）；**E** = 蒸发源
（mm/yr：海洋格能量限制、陆地格土壤桶或 Budyko 再循环）；**k_rain** = 雨出率
（1/yr），基底 1/τ（τ = 9 天水汽驻留时间）乘五个空间调制因子——storm = 斜压风暴
路径增强、gate(ΔSST) = §5-α SST 对流门、pickup = §5-β 对流临界门（默认关）、
coastal = 海岸辐合调制（切片 3）、subplanet = 向星对流锚（切片 4，nacrea 专用）；
**κ** = 湍流水汽扩散率（m²/s）；**φ** = 空气跨上坡边抬升 Δz 后按 Clausius–Clapeyron
凝结的水汽份额，z_LCL = 800 m 抬升凝结高度偏移、Δz = 边两端地形高差（海平面基准
max(elev,0)）；**R_v** = 水汽气体常数 461 J/(kg·K)、**L_v** = 凝结潜热 2.5×10⁶ J/kg、
**Γ** = 湿绝热直减率（`moist_lapse_rate`，4.5–6.5 °C/km）；**c_e** = 边平流系数
（迎风有限体积离散，1/yr）；**P_route** = 冷阱（W ≤ W_sat 钳制）截断的雨出率沿入流
边按到达通量份额路由回上风暖区的部分（share ∝ |c|·W上游，切片 2）；**W_sat(T)** =
CC 饱和柱水汽（`column_water_saturation`）。

**守恒恒等式**：地形衰减使通量项不再完全 telescope，残差恰为 Σ P_oro；冷阱路由把
截断量原额转回上风——因此面积加权的 **Σ A·P = Σ A·E 精确成立**（浮点精度内），
唯一例外是收敛哨兵的裁剪（数值稳定化，账本如实记账并 warning）。

其中 gate = **§5-α SST 对流门**（`sst_convection_gate`，2026-09-16）：WTG 下冷距平
洋面（上升流/东边界流）雨出效率坍缩、水汽输出到暖池再雨出——两分支分段线性 ramp
（热带/外热带结点 = GPCP 海洋格标定），ΔSST = SST − 符号化 5° 带海洋格 cos 加权均值
（逐月随 t_m 场），正距平 f≡1（暖池/WBC 走廊结构安全）、f_min = 0.2（层积云 drizzle
尾）、仅海洋格；config `sst_convection_gate_enabled`。触发覆盖现状与残余 → proposal
§5-α/§4（ΔSST 结构窄：冷舌缺失）。

pickup = **§5-β 对流临界雨出门**（`convective_pickup_gate`，2026-09-17，
config `convective_pickup_gate_enabled`）：降水是柱水汽的临界现象（Neelin-Peters-
Hales 2009——临界值以下雨出趋于零、95% 降水在 0.8 w_c 以上），观测的雨出效率
τ = W/P 在深沙漠（约 150 天）与对流区（7-10 天）之间差 15-20 倍，而引擎基底是全局
均匀的 9 天。门把 k_rain 乘上 f(W/W_sat)（W_sat 用冷阱同一个
`column_water_saturation`，所以冷区 x≈1 自动豁免、暖池 x=1 不动）。门作用于
**陆+洋全域**：过境洋面（孟加拉湾这类）被适度压制后柱水汽回升，更多水汽得以输送到
季风陆地，陆地柱水汽越过临界值后门打开、雨在那里落下——这个「自释放」回路要求
陆洋统一处理，只做陆地会切断供给。

**iterate-twice 求解结构**（每次求解保持线性）：年和每个月都先用基底 k_rain 解一遍
得到 W₀，由 W₀ 算出门，带着门重解得到 W₁，再在 W₁ 上重算门、再解一次。第二步不可
省——单次迭代把门钉在未门控的 W₀ 上，恒河这类被饿死的柱子永远等不到门重开（首轮
验收实测：恒河降水掉到 0.35×，正是这个结构性缺陷）。两次迭代是对 k(W) 真非线性
不动点的 Picard 逼近，物理上对应对流在日尺度上随柱水汽调整、月平均闭合取其平衡。
结点与 f_min = 9d/150d 是 `climate_physics` 的模块常数（标定模式
`diagnose_desert_wetness --pickup-gate`），不是 config 旋钮。

迎风有限体积（边平均风速保证成对边通量反对称）+ 湍流扩散 κ∇²W（κ 为 config 字段
`moisture_diffusivity_m2s`，默认 1e6 m²/s）+ 直接稀疏 LU 求解。质量守恒逐月由构造
保证（见上方守恒恒等式），年总量因而也守恒；ITCZ / 副热带干带从风场自然涌现。

**雨出率空间调制**：`k_rain(x)` 非常数——风暴路径等增强机制当作**雨出效率的空间调
制**（τ 更短 → 雨出更高效），而非加法降水项。这保证全球 ΣP = ΣE（Held & Soden
2006：降水受地表/辐射能量预算约束，只能从平流来的柱水汽中析出，不能凭空加）。

**月度风场**：`wind_monthly[m] = 背景 + 跨赤道西风带 + 季风异常`（§5.4）。月度降水直
接来自逐月预算，Köppen 第三字母（s/w/f）用真实月度值。

**执行步骤**：

1. **年预算先行**：Budyko 再循环曲线 `E_land = E_pot·P/(E_pot+P)` 是**年水量平衡**关系
   （Budyko 1974），先在年场上解固定点（`_LAND_RECYCLING_*` 松弛迭代）得到收敛的陆地
   蒸散。Budyko 的角色 = **长期统计参照 + 月度第一遍的水分限制**（若逐月直接套曲线，
   Jensen 不等式会系统性低估陆地蒸散，实测 490 → 319 mm/yr）——跨月记忆由下一步的
   土壤桶提供。
2. **逐月水汽收支**（×12，第一遍）：海洋蒸发送月度温度（能量限制 ~3%/°C，基准
   `evaporation_base_mm` = 1000 mm/yr @15 °C）；风暴路径增强用年场（急流季节摆动为二阶
   效应），与 §5-α SST 门复合为公共 k_rain 因子（逐月门随 t_m 场）。有向边表建一次
   复用。
2b. **土壤水桶**（`soil_bucket_enabled`，CLIM-02 bucket / astra §2.3）：第一遍月降水
   驱动 Manabe (1969) 单层桶至**周期稳态**（`soil_bucket_monthly` 纯函数：
   `E_m = min(E_pot_m, S+P_m)`、`R_m = 溢流`、逐 cell 逐月 `P = E + R + ΔS` 精确闭合），
   桶 ET 替换无记忆的 Budyko 月估计、**重解 12 个月**（第二遍）。截断两遍定点——
   pass-2 的 ΔE 残差打印在构建日志（console `soil bucket:` 行），不静默当收敛。
   容量 `soil_water_capacity_mm`（默认 150 = Manabe 经典值）是作者可调的世界参数
   （根区有效持水量）；v1 无积雪库（全部 P 按液态入桶——雪季补给的时机偏移是下一个
   闭合假设，不在本轮）。径流 R 不回灌海洋预算（海洋 E 能量限制、水量上无感）。
3. **地形抬升凝结**（求解器内，CLIM-02 切片 1）：空气跨上坡边抬升 Δz 冷却 Γ·Δz，
   CC 饱和比湿按 exp(−Δz/H_cc) 下降（`cc_lift_drying_scale`，H_cc = R_v·T²/(L·Γ) ≈
   2.0–2.6 km，零自由参数）——入流通量系数衰减为 (1−φ)·c，凝结的 φ 份额在迎风
   （上坡）格雨出为 `P_oro`。**一个守恒机制同时给出迎风地形雨与背风雨影**（到达背风
   的气柱已被削耗），取代旧的两处账本外后处理（迎风凭空加雨 + föhn 乘法删雨，均
   2026-09-18 退役）。稳态守恒预算下迎风总降水只是温和抬升（凝结多为「重标记」本地
   本要下的雨），主信号在背风亏损——与旧「凭空加水」机制的迎风大包有本质区别。
   Budyko 固定点与年/月两条求解路径自动消费同一机制。
4. **斜压风暴路径**（年场，:2077）：雨出率增强 `_storm_enhance`——幅度 ∝ 自身场赤道-
   极差 × Ω^0.3 × 蒸发，作为 `k_rain` 调制而非加法项；`_eddy_enhance` 同比例增强涡旋
   水汽扩散 κ。带位置由 `_baroclinic_band`（:1901）从纬向平均温度的经向梯度推导
   （Eady 不稳定性跟随 ∇T）：中心取 |dT/dφ| 峰值纬度（限制在 20° 以上），σ 取半峰全宽
   /2.355（钳制 5–20°）；第三返回值 = 剖面自身的赤道-极差，作风暴幅度的**自身场**归一化
   基准（E2，2026-09-16：取代 config/auto `lat_gradient` 双轨，杀同物理裂缝）。带输入 =
   「最终场 − 冰反照率增量」（陆格，`ice_increment_c` 穿参）——冰缘梯度是反馈不是强迫，
   风暴带不追冰缘跑（nacrea 冰缘 58-72° 曾吸走 ∇T 峰值、把风暴增强错投中纬之外）。
   梯度推导让单圈行星也得到弱而真实的斜压带——旧的胞圈边界方案（φ=(φ_H+φ_P)/2）
   在单圈行星退化为零宽，但慢自转 GCM 表明瞬变涡旋「减弱而不为零」（Gnanaraj et al.
   2025; Showman & Kaspi 2010）。
5. **海岸不对称雨出调制**（CLIM-02 切片 3，求解器内 k_rain 场）：向岸风携带洋面水汽
   → 海岸辐合抬升本地雨出效率、离岸（陆地源）风抑制，f = 1 ± ε·ρ_air·|U_zonal|·
   q_sat(T)·s_per_year/P_bg（ε 与 [0.5,1.5] 截断 = 观测拟合类常数，纪律 #9；通量形式
   ρ·|U|·q_sat 为物理量纲）。与 storm/SST/ω 门同乘复合进 k_rain——守恒（任意 k 场
   ΣP=ΣE），且不再虚假缩放地形凝结/冷阱路由雨。西风带季节性未建模，同一场作用于
   全部 12 个月与年解。
6. **次行星对流锚雨出调制**（CLIM-02 切片 4，求解器内 k_rain 场）：潮汐锁定天体的
   宿主永悬向星点上空 → 稳定加热锚定该处对流（次星对流锚），以向星点为中心的高斯
   雨出效率增强 `1 + warming_c·200/P_ref · exp(−(Δang/15°)²/2)` 复合进 k_rain——守恒
   （取代旧加法增雨的凭空造水）。`sub_planet_warming_c=0` 禁用（Earth）。σ=15° 与
   200 mm/yr/°C 幅度 = 待文献锚的作者启发式（纪律 #9 已标注，向星对流锚真实强度归
   阶段 D）。
7. **冷陷阱**（`_apply_cold_trap`，求解器末端，CLIM-02 切片 2）：冷空气柱装不下超过
   饱和量的水汽，解出的 W 钳制到 W_sat(T)；但被钳掉的雨出率 k·(W−W_sat)⁺ **不删除**，
   而是沿该格的入流边按到达通量份额（share ∝ |c|·W上游）路由回上风暖格雨出——物理上
   这部分水汽本来就会在空气还暖的上游（如南极海岸而非高原腹地）凝结落下。公式见本节
   顶部主方程的 P_route 项；路由后冷阱环节不再破坏 ΣA·P = ΣA·E。
8. **收敛哨兵**（`_convergence_sentinel`，CLIM-02 切片 5）：逐 cell 年降水帽 =
   α·k_rain·W_sat(max(T, 0°C))，α=8（地球最强地形 funnel 实测 ~5-7× 本地柱处理量，
   观测拟合类，纪律 #9）。世界无关、温度自适应：暖低地宽松（Cherrapunji 11,871 通过）、
   冷高地收紧（切片 1 per-edge φ 在陡峭地形的过浓伪影所在——pre-sentinel 达地球纪录
   10-16×）、0°C 地板代理冷区平流供给（南极海岸 200-800 mm/yr 不误伤）。取代旧固定
   11000 mm 封顶（地球站点纪录作异星帽，astra §2.1）。数值稳定化类闭合：咬合时
   logger.warning 响亮报告（不再静默删水），账本 sentinel 段如实记账；per-edge φ
   过浓的根治归阶段 D W 场供给路线。按月度值等比例封顶保持季节形状。

**关键设计**：ITCZ、副热带干带、极锋全部从水汽收支的 ∇·(W u) 自然涌现，**无纬度硬
编码**——对 Earth 三圈环流与 nacrea 单圈环流（`hadley_extent=90`）同一套代码自动适配
（见 `scripts/climate/diagnose_wind_divergence.py`）。

**区域诊断**：`scripts/climate/diagnose_monsoon_regional.py` 读已构建地图的月度数据，
对比关键季风区/对照区的月度降水与观测气候态并给出各区 Köppen 构成。

**守恒约束与文献参照**：

- **Held & Soden (2006)**：全球降水受能量预算约束（ΣP = ΣE），`P = W/τ` 即其雨出弛豫
  形式；雨出效率空间可变（风暴路径 τ 短、副热带 τ 长）。
- **Trenberth et al. (2007)**：海洋 E−P = +40×10³ km³/yr（净源）、陆地 P−E = +40
  （净汇），海洋→陆地输送 ≈ +110 mm/yr（海洋均值）；模型标定目标。
- **climlab**（Betts-Miller 对流 + LargeScaleCondensation）：降水是「已有湿度/柱水汽
  的汇」（弛豫/凝结），从不凭空加法——与本文件 `k_rain(x)·W` 同构。
- **PlaSim/ExoPlaSim**（Kuo 对流）：对流降水 ∝ 水汽辐合，天然守恒。
- **WAM-2layers**（van der Ent 2014）：水汽标记追踪；~40% 陆地降水来自陆地再蒸发，
  作再循环率标定目标。
- **Savenije (1995) / van der Ent & Savenije (2011)**：内陆降水沿水汽轨迹指数衰减
  `P = P₀·exp(−x/λ)`，但再循环长度 λ 区域依赖（热带 500–2000 km、沙漠 >7000 km），
  由当地 E/P 决定而非距海距离——这是 Budyko 再循环取代距离衰减的依据。

**诊断辅助**：`_surface_divergence`（:1855）有限体积逐 cell 散度，供
`diagnose_wind_divergence.py` 使用。

---

## 8. Köppen 分类

`koppen_classify`（`climate_physics.py`，调用 :976）吃月度真值：

- **极值预计算**（:894-900，`warm_cold_half_precip` / `seasonal_precip_extremes`）：
  最干/最湿月、暖季/冷季降水、夏干/冬湿/冬干/夏湿四个对立量——第三字母 s/w/f 的判据
  全部来自水汽收支的真实月度值。
- **b/c 第三字母**（B0d，Kottek 2006）：≥ 10 °C 的月数（`t_months_ge10`，:992）——
  B0c 交接让 t_monthly 与年平场水平一致后这个门槛才有意义。
- 只对陆地 cell 分类（`is_land`），海洋 cell 置 None。

---

## 9. DAG 引擎封装 `climate.py`

```python
class ClimateEngine(BaseEngine):
    name = "climate"
    layer = Layer.CLIMATE
    requires = ["astronomy", "geological"]
    input_files = ["stellar.yaml", "stellar_derived.yaml", "planets.yaml"]
    output_files = ["climate_summary.yaml", "maps/{planet_id}/temperature.png", ...]
```

执行链（`engine/climate.py`）：

1. 读 planets.yaml 取第一颗类地行星；恒星光度/轨道距离来自天文层（卫星对宿主恒星解
   析），行星物理（倾角/自转/半径/温室）来自 planets.yaml。
2. `terrain_config.yaml`（经 `find_input` 沿层级链继承）加载 `TerrainPipelineConfig`
   ——与地形管线同源，调参不分叉；随后 `resolve_and_apply_physical_parameters` 用
   正典物理量（光度/距离/倾角/自转/温室）覆写 config 中的任何同名值
   （`climate.py:100-135`）。
3. 从 geological 层派生目录加载带海拔的 CVT mesh（`_load_cvt_mesh_from_geological`）；
   缺 mesh 则引擎失败返回。
4. `simulate_climate(mesh, config)`（:155）→ 写回 `cvt_mesh.json` →
   `export_climate_layers(mesh, export_dir, config)`（:168）。

诊断脚本侧的对应物是 `map/climate_config.py::load_climate_config`——同一套
terrain_config + 物理参数解析，保证诊断与构建读同样的配置。

---

## 10. 地形管线集成

地形管线（`map/terrain_pipeline.py`）中气候的位置：

- **Stage 6 Climate**（:426-439）：`simulate_climate(result.mesh, config)` 在地形合成
  （Stage 5）之后原地执行；配置与 DAG 引擎同源（同一 terrain_config.yaml）。
- **Stage 7 Rivers**（:441-468）：河流生成**消费气候输出**（降水 → 径流），并抽取
  `features.json` 河流折线。
- **Stage 8 Export**（:469 起）：全图层导出；导出前把大河型内流湖（里海类比）升级为
  气候意义上的洋（`upgrade_large_endorheic_lakes`）——放在河流之后，因为河流标记的
  「河流终结型内流湖」才是气候相关的内陆海。

数据流：`terrain_config.yaml → terrain_pipeline → simulate_climate(mesh) → 写回
cvt_mesh.json + export_climate_layers → maps/{planet}/temperature.png / precipitation.png /
koppen.json / climate_monthly.msgpack`。

---

## 11. 图层导出与输出格式

`export_climate_layers(mesh, output_dir, config)`（`export.py:581`）的产物：

| 文件 | 格式 | 内容 |
|------|------|------|
| `temperature.png` | 16-bit 单通道 PNG | 年平温度，范围记录于 metadata（标称 [−40, +50] °C） |
| `precipitation.png` | 16-bit 单通道 PNG | 年降水（标称 [0, 6000] mm/yr） |
| `koppen.json` | JSON | per-cell 分类 + 统计汇总 |
| `climate_metadata.json` | JSON | 量化范围、类目表、导出分辨率 |
| `climate_monthly.msgpack` | MessagePack | N×12 月度场（见下） |
| `climate_yearly.msgpack` | MessagePack | N 个 per-cell UCC 连续描述量（见下） |

PNG 与 elevation.png 同编码，前端解码：

```typescript
const temperature = tMin + (pixelValue / 65535) * (tMax - tMin);  // from climate_metadata.json
```

`koppen.json`：

```json
{
  "cells": { "0": "Cfa", "1": "Aw", ... },
  "summary": { "Cfa": 3200, "Aw": 1500, "BWh": 4800, ... },
  "num_cells": 200000
}
```

`climate_monthly.msgpack`：月度场**不进 `cvt_mesh.json`**（N×12 数组会使 mesh 体积翻
倍），而是 `simulate_climate` 把它们暂存在 mesh 私有属性上（`_t_monthly_c` /
`_p_monthly_mm` / `_wind_east_monthly` / `_wind_north_monthly` / `_pressure_monthly`，
:958-974），导出时读出、int16 量化后写入单独的紧凑文件（`export.py` 读
`getattr(mesh, "_t_monthly_c", None)` 等）。API 侧 `GET /maps/{world}/climate-monthly`
直接吐这个文件（`api_routes/maps.py:190`）。

`climate_yearly.msgpack`：UCC-01 的年度尺度气候量容器，首批内容 = UCC 连续描述量
（ucc-review §4.2，计算见 `map/ucc.py` 的 `compute_descriptors`）。导出时从月度序列
逐 cell 现算，月度参考需求来自 `potential_evapotranspiration_hamon_monthly`
（`engine/climate_physics.py`，与 aridity gate 的年值 Hamon 共享同一日率核心，
月度和 ≡ 年值）。数值字段为 raw float32，未定义值存 NaN、原因由 uint8 状态数组
（`ai_status` / `deficit_status`，取值见文件内 `status_codes` 枚举）表达；元数据内嵌
`result_metadata()`（format_version + 参考年/月时间约定）+ `demand_model` +
`freeze_threshold_c`。时间基准 = 12 个等长参考月：`p_total_mm` 为每参考年 mm，
AI 为窗口不变量。该文件定位为「年度尺度气候量」的通用容器，后续年度量（如年风应力、
年辐射）也归入此文件。API 侧 `GET /maps/{world}/climate-yearly`
（`api_routes/maps.py` 的 `get_climate_yearly`）。

同一文件还带 **UCC 分类字段**（UCC-01 第四步，profile 见 `map/ucc.py` 的
`classify_v0` 与 `PROFILE_V0`）：`profile`（版本标识）、`thermal_bands` /
`supply_bands`（码 → 名枚举）、`ucc_thermal`（uint8 热量带码）、`ucc_supply`
（uint8 供需档码，255 = 不适用——海洋或 AI 非 valid）、`ucc_supply_status`（uint8，
复用 `status_codes`）、`ucc_modifiers`（uint8 位掩码：bit0 = continental、
bit1 = water_stress）。分类在导出层一次性算好，前端只读码不重新分类（阈值共享由
构造保证）；无这些字段的旧导出在前端降级为透明图层。

---

## 12. 验证方法

验证设计（数据源、指标、多线证据策略）单一事实源 =
[climate-validation.md](climate-validation.md)。方式：ETOPO1 真实高程输入
（earth/climate-dev 分支，200k cells）对比 Beck 2018 Köppen / ERA5 温度 / GPCP 降水；
诊断脚本区分「引擎 bug」vs「参数微调」。

**当前基线**（earth/climate-dev，2026-09-14 M4/B0b 轮；完整表与逐格残余见
[proposals/climate-layer-improvement.md](../proposals/climate-layer-improvement.md) §0）：
温度纬向 R² 0.992 / 逐格 RMSE 4.23 °C；降水纬向 R² 0.724；Köppen 分布匹配 61.2%、
逐 30 类 accuracy 32.1%、5 群 kappa 0.538；风场逐格 |U| R² −0.492（年平定常结构已
给，逐格 skill 仍负 = 定常涡旋仍缺）。M4 四项验收判据（分布 >55% / 群 kappa >0.45 /
逐类 ≥30% / 纬向 corr >0.9）全部达标。

```bash
uv run python scripts/climate/diagnose_koppen_confusion.py     # 逐类 precision/recall/F1 + 混淆矩阵
uv run python scripts/climate/diagnose_latitudinal_profile.py  # 海陆分离 T/P 纬向剖面
uv run python scripts/climate/diagnose_koppen_spatial.py       # 空间准确率热图
uv run python scripts/climate/diagnose_wind_divergence.py      # 风场辐合/辐散纬向剖面
```

---

## 13. 已知限制与调优方向

### 当前状态

| 机制 | 状态 |
|------|------|
| 温度（年平） | ✅ 1D EBM 正式求解 + 大陆度（`ebm_diffusion_land_wm2k`）+ 单圈 Held-Hou 分支 + E1 eddy relaxation；导出年温 = 月温终聚合（§3.8） |
| 温度（季节） | ✅ 显式热输送（B+6D，Ω 标度）+ 季节冰反照率 + B0c 交接 + 单一温度权威（§3.8） |
| 气压 | ✅ B2 海洋参照月度 ΔP（全值，含年平）+ 500 km 尺度分离 |
| 风场 | ✅ 三圈背景 + 跨赤道西风带（可推广标度）+ 季风异常月度风场；年风 = 月矢量平均 |
| 洋流 | ✅ Stommel 环流 + E4 亚网格 WBC 增速 + SST 平流 + 涌升 + 洋向陆距平平流 + E4 过程化 OHT 偏差 |
| 降水 | ✅ 质量守恒逐月水汽收支 + 雨出率空间调制（E2 冰缘脱钩 + 自身场幅度 + §5-α SST 对流门）+ Budyko 陆地再循环 |
| ④ 定常波 | ⚪ 求解器 + 两趟回路已接线，默认关（v1 保真度不足，待 v2 真高层基本态） |

### 已知局限

残余偏差清单与实现顺序的单一事实源 =
[proposals/climate-layer-improvement.md](../proposals/climate-layer-improvement.md) §7
（已登记不主动项：D 群崩溃/沿海振幅/半封闭海/风场规则性/卫星特有光照；单圈世界
E1-E4 已实施——E3 已否证（Faulk 2017 细读方向反转）、E1/E2/E4 ✅、φ_H 从 Ω 推导 ✅）。
本文仅保留结论：

- **季风残余**：ΔP 框架只能给「大陆热低压」向岸流，覆盖不了「海洋高压西缘」（百慕大
  高压型 = 动力下沉）；LLJ 垂直结构与季风槽北移超出单层引擎，归架构升级
  （steady-coupling / 双层 Gill / 简化 GCM）。
- **单圈残余**：宽 Af 带 = 单圈无副热带下沉干带 + 低倾角无干季的正当物理（E3 已否证，
  不修）；nacrea 洋流 ψ 本身偏弱（信风单调 → 风应力旋度小），WBC 增速受其上限约束；
  §5-α SST 对流门已具备前置（距平结构复活待地球侧验证）。

### 地球标定的方案常数（影响异星保真度）

| 参数 | 默认 | 说明 |
|------|------|------|
| `ebm_diffusion_wm2k` | 0.35 | 总经向热输送 D，Earth ΔT≈41°C 标定 |
| `ebm_diffusion_land_wm2k` | 0.28 | 陆地（大气）输送，≈0.8×总输送 |
| `moisture_diffusivity_m2s` | 1e6 | 柱水汽湍流扩散 κ，大标定轮标定 |
| `storm_track_amplitude_mm` | 900.0 | 斜压风暴路径幅度 |
| `evaporation_base_mm` | 1000.0 | 15 °C 洋面年蒸发基准（能量限制 ~3%/°C） |
| `coastal_moderation_scale_km` | 500 | 沿海调节 e 折长度 |
| `maritime_advection_scale_km` | 1500 | 4.1-B 向风海洋平流 e 折长度（Berg 1944 气团尺度） |

> 其余水汽收支/季风物理常数在代码内（非 config，所有世界共享）：驻留时间
> `_MOISTURE_RESIDENCE_DAYS` = 9 天（:1545）、陆地蒸散基准因子
> `_LAND_EVAPOTRANSPIRATION_FRACTION` ≈ 0.55（:1555）+ Budyko 再循环参数
> （`_LAND_RECYCLING_*` :1575-1577）、季风气压平滑 `_MONSOON_PRESSURE_SMOOTHING_KM`
> = 500 km（:1564）、边界层拖曳 `_DRAG_RATE_S`/`_DRAG_RATE_LAND_S`（水面/植被，
> `monsoon_circulation.py:130-131`）、E4 海洋柱输送 `_OHT_COLUMN_WM2K` = 0.37 +
> `_OHT_OCEAN_SHARE` = 0.65（TC2001 分解，`climate_simulator.py`）、E1 涡旋标度
> `_EDDY_SHARE_EARTH` = 0.69 / `_EDDY_OMEGA_EXPONENT` = 0.6（Kaspi 2015 Fig 8b，
> `climate_seasonality.py`）、§5-α 门结点（GPCP 标定 + `_SST_GATE_F_MIN` = 0.2，
> `climate_physics.sst_convection_gate`）。

---

## 14. GCM 与参数化管线的定位、后续开发

### 结论

GCM（求解原始方程）技术上能取代参数化管线，但**不适合做主干**——计算量差 3–4 个数量级
（ExoPlaSim 一个案例数小时 vs 管线 ~2 分钟），且 GCM 的次网格参数化同样有几十个地球
标定的「补丁」，用到 nacrea 需重新标定。

### 定位

「参数化 vs GCM」不是对立，而是「参数是否物理自洽」。逐项打补丁暴露的问题（速度单位、
随意 λ）是**参数不物理**，不是参数化模型的原罪。把「纬度高斯补丁」替换为「从风场/辐射
第一性推导的物理量」是正确方向。

### 后续开发计划（指针）

- **远期备选：全动力学 GCM** — [proposals/climate-gcm-plan.md](../proposals/climate-gcm-plan.md)：
  涌现 vs 高效的关键取舍、GPU 加速杠杆、与现有 DAG 的关系；本地 ExoPlaSim PoC
  （`private/external-projects/exoplasim_poc`，结论已入该文档）作为对标先导。
- **中间态：稳态耦合** — [proposals/climate-steady-coupling.md](../proposals/climate-steady-coupling.md)：
  在 DAG 的某一步内做 T↔P 耦合定点求解，介于单向 DAG 与瞬态 GCM 之间——§3.7 的
  「Stage 2–3 消费释放前温度」单遍近似残余正是它要移除的不自洽。
- **近期主动项：单圈体制包（E1-E4）** — roadmap §六 P0 +
  [proposals/climate-layer-improvement.md](../proposals/climate-layer-improvement.md) §7：
  慢自转世界的涡旋热/水汽输送参数化、斜压带脱离冰缘、ITCZ 宽度随 Ω 收窄、极向 OHT。
