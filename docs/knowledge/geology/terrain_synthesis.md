# 地形合成

> 从 `src/dreamulator/map/terrain_synthesizer.py` 抽取。  
> 详细算法参考：`docs/design/terrain-pipeline.md` §6

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

**地球物理依据**（自 design/terrain-pipeline.md §6.1 上浮，2026-08）：
地球高程呈**双峰分布**（hypsometric curve）——陆面平均 ~840 m、海底平均
~−3800 m。双峰源于陆壳（长英质，~2.7 g/cm³）与洋壳（镁铁质，~3.0 g/cm³）
的密度差导致的地壳均衡：两种地壳"漂浮"在不同均衡补偿深度上，中间过渡带狭窄。
这是把基准高程按地壳类型做双峰高斯分配（continental ~850±200 m、
oceanic ~−3800±500 m）的观测依据。

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

### 2.1 三类边界剖面公式（设计参考）

（自 design/terrain-pipeline.md §6.2 上浮，2026-08。以下为管线设计阶段的示意
公式；现行实现以上文 cortial2019 策略及 `terrain_synthesizer.py` 源码为准）

**汇聚边界**——上覆板侧山脉 + 俯冲板侧海沟（d 为到边界的有符号距离，上盘为正）：

```
rate_factor = min(v_n / 5.0, 2.5)
mountain = 2500 m · rate_factor · exp(−(max(d, 0) / 250 km)²)   # 陆-陆碰撞再 ×1.6
trench   = −3500 m · rate_factor · exp(−(max(−d, 0) / 150 km)²)
```

**离散边界**——中央裂谷 + 两翼山脊：

```
rate_factor = min(|v_n| / 3.0, 2.0)
rift  = −1000 m · rate_factor · exp(−(d / 100 km)²)
ridge = +1000 m · rate_factor · exp(−((|d| − 200 km) / 200 km)²)
```

**转换边界**——无显著高程效应，仅将地形粗糙度放大至 2×（σ = 200 km）。

**效应汇总**：

| 边界类型 | 正效应 | 负效应 | σ (km) | 速率因子 |
|----------|--------|--------|--------|----------|
| Convergent (C-C) | +4000m 山脉 | −5000m 海沟 | 250/150 | v_n/5.0 × 1.6 |
| Convergent (O-O) | +2500m 岛弧 | −3500m 海沟 | 250/150 | v_n/5.0 |
| Convergent (C-O) | +3000m 海岸山 | −4000m 海沟 | 250/150 | v_n/5.0 |
| Divergent | +1500m 山脊 | −1500m 裂谷 | 200/100 | \|v_n\|/3.0 |
| Transform | — | — | 200 | 粗糙度 ×2.0 |

**距边界粗糙度调制**（自 design/terrain-pipeline.md §6.3 上浮，2026-08）：

```
roughness = base × (1 + A · exp(−d / λ))    A = 1.0, λ = 300 km
```

边界附近地形更崎岖（近边界处调制因子最高 1+A），远离边界时 → 1。

---

## 3. fBm 噪声（分形布朗运动）

3D Simplex 噪声在球面 CVT 节点处采样：

$$H(x) = \sum_{i=0}^{N-1} \text{amplitude}_i \cdot \text{noise}(x \cdot \text{frequency}_i)$$

每倍频程：amplitude ×= persistence, frequency ×= lacunarity。
归一化：fBm /= max(|fBm|) → 值域 ≈ [−1, 1]，再乘振幅配置。

**Octave 物理尺度对照**（自 design/terrain-pipeline.md §6.4 上浮，2026-08；
设计阶段参数：振幅基准 1000 m、persistence 0.5、lacunarity 2.0）：

| Octave | 频率 f | 振幅 A (m) | 累积振幅 | 物理含义 |
|--------|--------|-----------|----------|----------|
| 1 | 1.0 | 1000.0 | 1000.0 | 大区域起伏（~6000 km） |
| 2 | 2.0 | 500.0 | 1500.0 | 次大陆起伏（~3000 km） |
| 3 | 4.0 | 250.0 | 1750.0 | 山脉尺度（~1500 km） |
| 4 | 8.0 | 125.0 | 1875.0 | 山岭尺度（~750 km） |
| 5 | 16.0 | 62.5 | 1937.5 | 丘陵尺度（~375 km） |
| 6 | 32.0 | 31.25 | 1968.75 | 细节起伏（~190 km） |

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

**地幔柱/超级隆起设计参考**（自 design/terrain-pipeline.md §6.5 上浮，2026-08）：
地幔柱（mantle plume）从深部地幔上升，在地表产生火山热点；大型地幔上涌可产生
直径数千公里的隆起区域（mantle superswell，参考 Gleba 的 mantle superswells
设计），叠加可选的中央破火山口凹陷：

```
uplift(d) = A · exp(−(d / σ)²)                        # 宽尺度高斯隆起
uplift −= D_caldera · exp(−(d / σ_caldera)²)          # 可选中央破火山口凹陷
```

其中 d 为到热点中心的大圆距离，σ 为热点半径。

### 4.3 内陆古造山带与裂谷

[Şengör (1990)](https://doi.org/10.1016/0012-8252(90)90082-3) 将造山带分为多种类型，
指出古缝合线可远离活跃板块边界。板块碰撞后漂移分离，残留的造山带
（如乌拉尔山脉、阿巴拉契亚山脉）作为线状高地保留在大陆内部。
[Burke & Dewey (1973)](https://doi.org/10.1086/627930) 的三联点演化理论
解释了拗拉槽（failed rift arm）的形成——裂谷未能发展成洋盆而保留为内陆凹陷。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `interior_orogeny_count` | 2 | 每大陆板块内陆造山带数量（0 = 关闭） |
| 造山带幅度 | 500–1500 m | 随机高斯隆起 |
| 造山带宽度 | 80–200 km | 高斯 sigma |
| 裂谷概率 | 30%/板块 | 随机线状凹陷 300–800 m |

每板块随机方向放置线状隆起，沿走向增加噪声扰动以模拟自然形态。

**沿走向高度调制与山间盆地**（自 design/terrain-pipeline.md §6.7 上浮，2026-08）：

均匀 Gaussian 脊线不符合真实造山带——后者沿走向有显著的高度变化
（Allen et al. 1995; Kröner 1981）。设计上每条 belt 用 1D simplex 噪声沿大圆弧
采样调制各段振幅（∈ [base × 0.3, base × 1.7]），造山带中出现高峰与鞍部而非
均匀脊线。当沿走向噪声值低于阈值时，该段成为**断陷盆地**而非山脊——模拟
拉分盆地和断块差异沉降，实例：

- 吐鲁番盆地（天山内部，−154 m）——周围山体 3000–5000 m
- 费尔干纳盆地（天山-帕米尔）——断块差异运动
- Basin and Range（美国西部）——伸展环境地堑

裂谷臂同样使用沿走向深度调制（深 300–800 m，σ = 40–100 km）。

> 参考文献：
> - Allen, M.B., Şengör, A.M.C., & Natal'in, B.A. (1995). "Junggar, Turpan and
>   Alakol basins as Late Permian to Early Triassic extensional structures."
>   *Journal of the Geological Society*, 152, 327–338.
> - Kröner, A. (1981). "Precambrian plate tectonics." Elsevier.

---

## 5. 海陆重分类

| 条件 | 重分类 |
|------|--------|
| 海拔 > 0 + oceanic crust | → `transitional`（岛屿/海山） |
| 海拔 < 0 + continental crust | → `transitional`（陆架/海底峡谷） |

---

## 6. 高程合成叠加

（自 design/terrain-pipeline.md §6.6 上浮，2026-08）

最终节点高程为各贡献项之和：

```
elevation = base_elev + boundary_effect + hotspot_uplift
          + fBm × amplitude × interior_factor (+ tidal)
```

- `interior_factor`：板块内部噪声稍大（大陆内部高原/盆地）。设计稿取
  `1.0 + 0.3 × (dist_to_boundary / max_dist)`；现行实现的内部调制公式见 §3。
- `tidal`：潮汐形变项（P₂ Legendre），仅潮汐锁定天体。

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
