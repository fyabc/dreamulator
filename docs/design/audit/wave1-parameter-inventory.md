# 审计第一波 T3：自由参数清点造册

> 日期：2026-08-15 · 方法：枚举引擎配置字段（`TerrainPipelineConfig` 为主 + 生态物理常量）
> **只清点、不处置**。分类标准见 audit-plan §三：
> **A 可推导**（有严格/经验公式可从上游物理量推出，应替换为计算而非旋钮）、
> **B 创意旋钮**（世界构建工具的合法创意控制，保留并文档化）、
> **C 经验常数**（文献经验取值，保留并补文献）。
> 本表是第二波（物理审计）"自由参数处置"的直接输入。

---

## 一、TerrainPipelineConfig（`src/dreamulator/map/pipeline_types.py`）

### 1.1 行星基本参数（planet）

| 字段 | 默认 | 分类 | 备注 |
|---|---|---|---|
| seed | 42 | B | 可复现性 |
| radius_km | 6371.0 | A | 从 planets.yaml 解析 |
| rotation_period_days | 1.0 | A | 从 planets.yaml 解析 |
| albedo | 0.306 | C | Bond 反照率（地球≈0.306） |
| orbital_period_days | 365.25 | A | 从轨道解析 |
| surface_pressure_hpa | 1013.25 | C | 地球海平面气压 |

### 1.2 CVT 网格（terrain）

| 字段 | 默认 | 分类 | 备注 |
|---|---|---|---|
| num_nodes | 100_000 | B | 分辨率旋钮（nacrea 用 200k） |
| jitter_sigma | 0.3 | C | 扰动强度 |
| lloyd_iterations | 8 | C | Lloyd 松弛次数 |

### 1.3 板块（plates / tidal）

| 字段 | 默认 | 分类 | 备注 |
|---|---|---|---|
| num_plates | 20 | B | 板块数旋钮 |
| plate_speed_range_cm_yr | (1.0, 10.0) | C | 地球板块速度量级 |
| tidal_plate_speed_enabled | False | A | 从潮汐加热推导（`tidal_physics.py`） |
| tidal_plate_speed_beta | 1.0 | C | 经验幂律指数 |
| tidal_plate_speed_v_ref_cm_yr | 5.0 | C | 参考速度 |
| tidal_spreading_ratio | 0.4 | C | 经验 |
| plate_algorithm | "cortial2019" | B | 算法选择 |
| boundary_noise | 0.10 | C | 边界噪声 |
| boundary_warp | 0.0 | C | 低频 fBm 扭曲 |
| trench_arc | 1.0 | C | 小圆弧涌现强度 |
| continental_fraction_min/max | 0.28 / 0.36 | B | 大陆覆盖率旋钮 |
| lat_bias | 0.7 | B | 大陆纬度分布旋钮 |

### 1.4 地理锚定（geography，创意旋钮集中区）

| 字段 | 默认 | 分类 | 备注 |
|---|---|---|---|
| sea_level_auto | True | B | 海平面自动校准 |
| target_land_fraction | 0.29 | B | 目标陆地占比 |
| sea_level_offset_m | 0.0 | B | 海平面旋钮（冰期/海峡实验） |
| anchor_weight | 0.6 | C | 锚定强度 |
| boundary_uplift_noise | 0.6 | C | 经验 |

### 1.5 地形合成（terrain）

| 字段 | 默认 | 分类 | 备注 |
|---|---|---|---|
| continental_undulation_m | 600.0 | C | 板内起伏 |
| crust_plate_floor | 0.10 | C | 经验 |
| tectonic_algorithm | "cortial2019" | B | 算法选择 |
| tectonic_steps / tectonic_dt_my | 0 / 0.0 | B | 时间演化步数 |
| rift_base_rate | 0.01 | C | 经验 |
| rift_min/max_pieces | 2 / 3 | B | 裂解碎片数旋钮 |
| terrain_algorithm | "cortial2019_asymmetric" | B | 算法选择 |
| continental_elevation_m | 850.0 | C | 地球陆均高量级 |
| oceanic_elevation_m | -3800.0 | C | 洋均深量级 |
| boundary_influence_km | 500.0 | C | 边界效应范围 |
| boundary_ridge_sigma_km | 80.0 | C | 山脊半宽 |
| boundary_shoulder_strength | 0.3 | C | 肩部强度 |
| convergent_uplift_m / divergent_depth_m | 4000 / 2000 | C | 汇聚/离散地貌 |
| plate_elevation_spread_m | 1500.0 | C | 板内高程差 |
| mountain_asymmetry | 0.4 | C | 迎风/背风坡 |
| hotspot_count | 3 | B | 热点火山链数 |
| shelf_width_km / coastal_plain_width_km | 150 / 80 | C | 大陆架/海岸平原 |
| coastal_plain_max_elevation_m | 500.0 | C | 经验 |
| island_arc_height_m | 1500.0 | C | 岛弧高度 |
| interior_orogeny_count | 2 | B | 内部造山带数 |
| interior_basin_chance / depth_max | 0.25 / 600.0 | B/C | 内部盆地 |
| interior_height_variation | 0.7 | C | 经验 |

### 1.6 噪声（noise，fBm）

| 字段 | 默认 | 分类 |
|---|---|---|
| noise_scale / octaves / persistence / lacunarity | 2.0 / 6 / 0.5 / 2.0 | C（fBm 标定） |
| noise_anisotropy | 0.3 | C |
| noise_amplitude_land_m / ocean_m | 900.0 / 450.0 | C |
| regional_noise_scale | 0.5 | C |
| regional_noise_amplitude_land_m / ocean_m | 1800.0 / 1200.0 | C |

### 1.7 气候（climate）

| 字段 | 默认 | 分类 | 备注 |
|---|---|---|---|
| stellar_luminosity_sol / orbital_distance_au | 1.0 / 1.0 | A | 从 stellar.yaml 解析 |
| axial_tilt_deg | 23.44 | A | 从 planets.yaml 解析 |
| atmosphere_factor | 1.0 | C | 温室乘数 |
| lapse_rate_c_km | 6.5 | C | 湿绝热直减率 |
| variable_lapse_rate | False | A | T 依赖直减率（Γ(T)） |
| lat_gradient_c | 40.0 | C | 赤道-极地温差（手动模式） |
| hadley_extent_deg / polar_cell_start_deg | 30.0 / 60.0 | C | 环流边界 |
| auto_lat_gradient | False | A | 从 Ω 推导（Kaspi 2015） |
| lat_gradient_earth_c | 40.0 | C | 地球参考 ΔT（标定值） |
| diffusive_heat_transport | False | A | 图拉普拉斯扩散 |
| ice_albedo_feedback | False | A | 冰反照率物理 |
| ice_albedo_max_cooling_c / threshold_c | 8.0 / -5.0 | C | 冰反照率参数 |
| wind_blocking_height_m | 3000.0 | C | 地形挡风阈值 |
| evaporation_base_mm | 2000.0 | C | 热带洋面蒸发（地球） |
| moisture_advection_steps | 0 | A | 自动从 Ω（0=auto） |
| moisture_diffusivity | 5.0 | C | 图扩散 D₀ |
| orographic_efficiency | 0.5 | C | 地形降水效率 |
| itcz_lag_days | 30 | C | ITCZ 热惯性滞后 |
| sub_planet_warming_c / lon / lat | 0.0 / 0.0 / 0.0 | A | 潮汐锁定次行星加温 |

### 1.8 季节（seasonal，North & Coakley 1979）

| 字段 | 默认 | 分类 | 备注 |
|---|---|---|---|
| seasonal_damping_b | 10.0 | C | 辐射阻尼（W/m²/K） |
| seasonal_land/ocean_heat_capacity | 2.0e7 / 2.0e8 | C | 表面热容量（J/m²/K） |
| seasonal_coastal_scale_km | 500.0 | C | 海洋调节 e 折长度 |
| eccentricity / perihelion_day | 0.0 / 0.0 | A | 从轨道解析 |

### 1.9 洋流（ocean，Stommel）

| 字段 | 默认 | 分类 | 备注 |
|---|---|---|---|
| ocean_currents_enabled | True | B | 开关 |
| ocean_drag_coefficient | 1.2e-3 | C | 表面拖曳 C_D |
| ocean_mixed_layer_depth_m | 50.0 | C | 混合层深度 |
| ocean_bottom_friction_s | 1e-6 | C | Stommel R |
| ocean_sst_advection_days | 70.0 | C | SST 调整时间 |
| ocean_temperature_diffusivity | 5.0 | C | 图扩散 |
| ocean_coastal_influence_km | 500.0 | C | 沿岸影响 |
| ocean_upwelling_enabled | True | B | 开关 |

### 1.10 均衡 / 洋底年龄 / 导出

| 字段 | 默认 | 分类 | 备注 |
|---|---|---|---|
| isostasy_enabled | False | A | 均衡物理 |
| isostasy_max_continental_elevation_m | 9000.0 | C | 地球 ~8848 |
| isostasy_max_ocean_depth_m | 11500.0 | C | 地球 ~11034 |
| ocean_age_depth_enabled | False | A | 板块冷却模型 |
| ocean_spreading_rate_cm_yr | 5.0 | C | 半速，地球 1–5 |
| ocean_ridge_depth_m / subsidence_coeff | 2500 / 350 | C | sqrt(age) 沉降 |
| ocean_max_age_myr / depth_m | 100 / 5500 | C | 稳态年龄/深度 |
| export_width / height | 4096 / 2048 | B | 导出分辨率 |

## 二、生态物理常量（`engine/ecology_physics.py`）

| 常量 | 分类 | 备注 |
|---|---|---|
| Whittaker 群系阈值表（温度带 × 降水范围） | C | Whittaker 1975 |
| Miami NPP 模型参数（温度/降水生产力函数） | C | Lieth 1975 |
| PAR 比率修正（`par_ratio = L/d²`） | A | 从恒星光度/轨道推导 |

> 生态层参数基本是**文献分类/经验值**（C 类），且已从 `par_ratio` 硬编码 1.0 改为
> 推导（技术债 #21 已登记，P2 待做的是"光谱类型 → 光合色素吸收谱 → 有效 PAR"
> 的完整修正链）。

## 三、其他配置类（非世界构建旋钮）

| 类 | 位置 | 说明 |
|---|---|---|
| `CacheConfig` | `map/terrain_cache.py` | 内部缓存开关（enabled/geography_hash），非旋钮 |
| `WorldConfig` | `models/world.py` | 世界元数据（name/seed/template），非引擎旋钮 |
| `_ApiConfig` | `narrator.py` | 叙述 API 配置，非世界构建旋钮 |

## 四、初步统计

- **总字段数**：约 110（TerrainPipelineConfig）+ 生态常量若干。
- **A 可推导**：约 20（从 stellar.yaml/planets.yaml 解析的恒星/轨道/倾角参数、auto_lat_gradient、variable_lapse_rate、冰反照率、均衡、洋底冷却、PAR 比率等）——多数已有 `physical_inputs` 解析，少数是"开关 + 待推导"。
- **B 创意旋钮**：约 25（分辨率、板块数、大陆覆盖率/纬度分布、地理锚定、算法选择、开关、导出分辨率等）——世界构建的合法控制面。
- **C 经验常数**：约 65（fBm 标定、地貌高度/宽度、气候/洋流/季节的标定值）——占大头，多为"地球量级"的经验值，是 Wave 2 处置（替换/文档化/补文献）的主要对象。

> 本表是**清点快照**；第二波将按 A/B/C 逐旋钮裁决（A → 替换、B → 文档化范围、C → 补文献）。
