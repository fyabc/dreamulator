# 地形合成

> 从 `src/dreamulator/map/terrain_synthesizer.py` 抽取。  
> 详细算法参考：`docs/usage/terrain-pipeline.md` §6

---

## 策略接口

通过 `terrain_algorithm` 配置选择算法。各算法共享双峰基准 + 板块偏移 + fBm 噪声管线，
仅在边界效应和特殊地貌处理上有差异。

| 算法 | 边界剖面 | 热点链 | 参考文献 |
|------|---------|--------|---------|
| `cortial2019_gaussian` | 对称高斯 | 无 | Cortial et al. (2019) §4 |
| `cortial2019_asymmetric` | 非对称 (windward/leeward) | Wilson (1963) 热点链 | Cortial + Willett (1999) + Wilson (1963) |

---

## 1. 双峰基准高程

| 地壳类型 | 默认高程 |
|----------|---------|
| continental | 850 m |
| oceanic | -3800 m |

每板块叠加随机偏移：均匀分布 $[-1500, +1500]$ m。

---

## 2. 构造边界效应

### `cortial2019_gaussian` — 对称高斯

高斯衰减模型：

$$\Delta H = A \cdot \exp\left(-\frac{d^2}{2\sigma^2}\right) \cdot \min\left(\frac{|v_n|}{10}, 1\right)$$

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `convergent_uplift_m` | 4000 | 汇聚边界抬升 |
| `divergent_depth_m` | 2000 | 离散边界下沉 |
| `boundary_influence_km` | 500 | σ = 影响半径 |
| 有效范围 | ~3σ = 1500 km | |

---

## 3. fBm 噪声（分形布朗运动）

3D Simplex 噪声在球面 CVT 节点处采样：

$$H(x) = \sum_{i=0}^{N-1} \text{amplitude}_i \cdot \text{noise}(x \cdot \text{frequency}_i)$$

每倍频程：amplitude ×= persistence, frequency ×= lacunarity。

**区域噪声（低频，3 octaves）**：

| 参数 | 值 |
|------|-----|
| scale | 0.5 |
| amplitude_land | 1200 m |
| amplitude_ocean | 800 m |
| persistence | 0.6 |

**细节噪声（高频，6 octaves）**：

| 参数 | 值 |
|------|-----|
| scale | 2.0 |
| amplitude_land | 600 m |
| amplitude_ocean | 300 m |
| persistence | 0.5 |

距边界距离调制：`interior_factor = 1.0 + 0.5·exp(-d²/2σ²)`（板块内部噪声更强）。

---

## 4. `cortial2019_asymmetric` — 非对称边界 + 热点链

### 4.1 非对称山脉剖面

参考 [Willett (1999)](https://doi.org/10.1029/1999JB900248) 的造山带非对称侵蚀理论：
迎风坡降水多、侵蚀快 → 坡面更陡；背风坡干燥 → 坡面更缓。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `mountain_asymmetry` | 0.4 | 0 = 对称；1 = 极强不对称 |
| `convergent_uplift_m` × 1.3 | ~5200 m | 陆-陆碰撞 (C-C) |
| `convergent_uplift_m` × 0.6 | ~2400 m | 洋-洋俯冲 (O-O, 岛弧) |

- 峰顶向俯冲板块方向偏移 `asymmetry × σ × 0.3`
- 前坡（迎风面）：`σ_front = σ × (1 - asymmetry × 0.5)`
- 后坡（背风面）：`σ_back = σ × (1 + asymmetry × 1.0)`
- 海沟在俯冲侧：深度约 `divergent_depth × 0.8`

### 4.2 热点火山链

参考 [Wilson (1963)](https://doi.org/10.1139/p63-094) 的热点假说：
板块在地幔固定热点上移动，形成年龄递进的线状火山链。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `hotspot_count` | 3 | 热点数量（0 = 关闭） |
| 初始高度 | 3000 m | 活火山高程 |
| 衰减率 | 0.85/cell | 指数衰减（~1350 km 链长） |

热点链方向由板块欧拉极运动方向自动确定。

---

## 4. 海陆重分类

| 条件 | 重分类 |
|------|--------|
| 海拔 > 0 + oceanic crust | → `transitional`（岛屿/海山） |
| 海拔 < 0 + continental crust | → `transitional`（陆架/海底峡谷） |

---

## 完整配置参数

**源码**：`pipeline_types.py::TerrainPipelineConfig`

| 参数 | 默认值 | 类别 |
|------|--------|------|
| `continental_elevation_m` | 850 | 基准 |
| `oceanic_elevation_m` | -3800 | 基准 |
| `plate_elevation_spread_m` | 1500 | 随机偏移 |
| `boundary_influence_km` | 500 | 构造 |
| `convergent_uplift_m` | 4000 | 构造 |
| `divergent_depth_m` | 2000 | 构造 |
| `noise_octaves` | 6 | 噪声 |
| `noise_persistence` | 0.5 | 噪声 |
| `noise_lacunarity` | 2.0 | 噪声 |
| `noise_amplitude_land_m` | 600 | 噪声 |
| `noise_amplitude_ocean_m` | 300 | 噪声 |
| `sea_level_m` | 0.0 | 海平面 |

---

## 参考资料

- Musgrave, F. K. (1993). *Methods for Realistic Landscape Imaging*.（fBm 地形基础）
- opensimplex 库文档（3D Simplex 噪声）
