# 地形合成

> 从 `src/dreamulator/map/terrain_synthesizer.py` 抽取。  
> 详细算法参考：`docs/usage/terrain-pipeline.md` §6

---

## 管线流程

```
双峰基准 → 板块随机偏移 → 构造边界效应 (高斯衰减) → fBm 噪声 → 海陆重分类
```

---

## 1. 双峰基准高程

| 地壳类型 | 默认高程 |
|----------|---------|
| continental | 850 m |
| oceanic | -3800 m |

每板块叠加随机偏移：均匀分布 $[-1500, +1500]$ m。

---

## 2. 构造边界效应

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
