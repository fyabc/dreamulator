# 行星物理参数模型

> 从 `src/dreamulator/models/planet.py` 抽取。

---

## 行星类型

| Type | 中文 | 特征 |
|------|------|------|
| `terrestrial` | 类地行星 | 岩石表面，可能有水 |
| `gas_giant` | 气态巨行星 | 以氢氦为主，无固体表面 |
| `ice_giant` | 冰巨行星 | 水/氨/甲烷冰 + 岩石核 |
| `ocean_world` | 海洋世界 | 全球性海洋覆盖 |
| `dwarf` | 矮行星 | 质量不足以清除轨道 |

---

## 大气层模型

**源码**：`planet.py::Atmosphere`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `surface_pressure_atm` | 1.0 | 地表气压（atm），地球基准 |
| `composition` | N₂:0.78, O₂:0.21, Ar:0.01 | 摩尔分数，须和为 1.0 ± 0.05 |
| `scale_height_km` | — | 大气标高（引擎计算） |
| `greenhouse_factor` | 0.0 K | 额外温室升温 |

---

## 水圈模型

**源码**：`planet.py::Hydrosphere`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `water_coverage` | 0.71 | 海洋覆盖率（地球） |
| `salinity_ppt` | 35.0 | 平均盐度（千分比） |
| `ocean_depth_km` | 3.7 | 平均海洋深度 |

---

## 岩石圈模型

**源码**：`planet.py::Lithosphere`

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| `has_plate_tectonics` | True | — | 是否存在活跃板块构造 |
| `num_plates` | 15 | 1–50 | 构造板块数量 |
| `volcanic_activity` | 1.0 | ≥0 | 相对地球的火山活动指数 |

---

## 行星基本参数

**源码**：`planet.py::Planet`

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| `mass` | 必需 | >0 | 地球质量 (M⊕) |
| `radius` | 必需 | >0 | 地球半径 (R⊕) |
| `rotation_period_days` | 1.0 | — | 恒星自转周期 |
| `axial_tilt_deg` | 23.4 | 0–90 | 自转轴倾角（地球=23.4°） |
| `albedo` | 0.3 | 0–1 | Bond 反照率 |

---

## 平衡温度

**源码**：`stellar_physics.py::equilibrium_temperature()`
**参考**：Seager (2010), *Exoplanet Atmospheres*

$$T_{\text{eq}} = \left[\frac{L_\odot \cdot L \cdot (1-A)}{f \cdot \pi \cdot \sigma \cdot d^2}\right]^{1/4}$$

- $f = 16$：均匀温度（完整再分配，辐射面积 $4\pi R^2$）
- $f = 8$：仅昼面再分配（辐射面积 $2\pi R^2$）
- 默认 Bond 反照率 $A = 0.3$

---

## 轨道天体（卫星/小行星）

**源码**：`stellar.py::OrbitingBody`

| 参数 | 说明 |
|------|------|
| `body_type` | natural_satellite / asteroid / comet / dwarf_planet |
| `mass_earth` | 地球质量 |
| `radius_km` | 千米半径 |
| `albedo` | 几何反照率 |

## 参考资料

- Seager, S. (2010). *Exoplanet Atmospheres*. Princeton University Press.
- Prša, A., et al. (2016). IAU 2015 Resolution B3. *AJ*, 151(5), 123.
