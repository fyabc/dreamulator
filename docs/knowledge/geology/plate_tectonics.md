# 板块构造模型

> 从 `src/dreamulator/map/plate_generator.py` 和 `boundary_detector.py` 抽取。  
> 详细算法参考：`docs/design/geological-pipeline.md` §3–4

---

## 欧拉极运动学

刚体球面运动由欧拉极（旋转轴）和角速度描述：

$$\mathbf{v}(P) = \boldsymbol{\omega} \times \mathbf{P}$$

其中 $\mathbf{P}$ 为球面上一点（单位向量），$\boldsymbol{\omega} = \omega\,\hat{\mathbf{e}}$
为角速度矢量（$\hat{\mathbf{e}}$ 为欧拉极方向）。在半径 $R$ 的球面上速度单位为
m/yr 时写作 $\mathbf{v}(P) = \boldsymbol{\omega} \times \mathbf{P} \cdot R$。

**速度大小**随 P 到欧拉极的角距离变化（自 design/geological-pipeline.md §4.3 与
附录 A.3 上浮，2026-08）：

$$|\mathbf{v}(P)| = \omega R \sin\alpha, \qquad \alpha = \arccos(\hat{\mathbf{e}} \cdot \mathbf{P})$$

欧拉极处速度为零，90° 处最大。

**角速度-线速度换算**（自 design/geological-pipeline.md §4.2 上浮，2026-08）：

$$\omega = v / R$$

地球板块运动速度约 1–10 cm/yr：

| 速度 (cm/yr) | ω (rad/yr) | 描述 |
|--------------|------------|------|
| 1.0 | 1.57 × 10⁻⁹ | 慢速（如非洲板块） |
| 5.0 | 7.85 × 10⁻⁹ | 中等（如北美板块） |
| 10.0 | 1.57 × 10⁻⁸ | 快速（如太平洋板块） |

**无净旋转参考系**（no-net-rotation frame）：可选减去按 cell 面积加权的全球
平均速度，使岩石圈净角动量为零（与地球物理学的 NNR 参考系同理）。

**参数**：`plate_speed_range_cm_yr = (1.0, 10.0)` — 板块移动速度（cm/年）。  
地球参考：太平洋板块 ~10 cm/yr，大西洋中脊 ~2 cm/yr。

---

## 板块生成（球面 Voronoi 剖分）

遵循 [Cortial et al. (2019)](https://doi.org/10.1111/cgf.13614) *Procedural Tectonic Planets* 的方法：

1. **种子选取**：Poisson-disc 采样，随机选 `num_plates` 个 cell，最小角距 ≥ 平均间距 × 0.3
2. **同步多源 BFS（球面 Voronoi 剖分）**：所有种子等速逐层扩展，每 cell 归属先到达的 wavefront
   - Voronoi 区域在图上天然凸 → 板块永不包围
   - CVT 网格的不规则拓扑天然提供有机边界，无需额外噪声扭曲
3. 板块面积由 Poisson-disc 种子分布和球面 Voronoi 几何自然决定

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `num_plates` | 20 | 板块数量 |

**参考实现**：[weigert/SimpleTectonics](https://github.com/weigert/SimpleTectonics) — Poisson disc + GPU Voronoi

---

## 地壳类型分配

每板块随机 `continental_fraction ∈ [0.1, 0.9]`。  
按绝对纬度排序（中纬度大陆偏好），前 `fraction × N` 个 cell 为大陆。

| 类型 | 判定 |
|------|------|
| `continental` | 大陆比例 > 2/3 |
| `oceanic` | 海洋比例 > 2/3 |
| `mixed` | 其他 |

---

## 边界检测与分类

对每个边界 cell 计算邻接板块的相对速度：

$$\mathbf{v}_{rel}(P) = \mathbf{v}_A(P) - \mathbf{v}_B(P) = (\boldsymbol{\Omega}_A - \boldsymbol{\Omega}_B) \times \mathbf{P} \cdot R$$

$$v_n = \mathbf{v}_{rel} \cdot \hat{\mathbf{n}} \quad (\text{法向，汇聚为正}), \qquad v_t = |\mathbf{v}_{rel} - v_n\hat{\mathbf{n}}| \quad (\text{切向，走滑})$$

其中 $\hat{\mathbf{n}}$ 为切平面内从 plate_A 指向 plate_B 的边界法向。

| 边界类型 | 判定条件 |
|----------|---------|
| **convergent**（汇聚） | $v_n > 0.5$ cm/yr |
| **divergent**（离散） | $v_n < -0.5$ cm/yr |
| **transform**（转换） | $v_t / v_{total} > 0.7$（切向主导） |
| **inactive**（非活动） | $|v_n|$、$v_t$ 均 ≤ 阈值（默认 0.5 cm/yr） |

**各类型的地质效应**（自 design/geological-pipeline.md §5.4 上浮，2026-08）：

| 边界类型 | 地质效应 |
|----------|----------|
| Convergent（汇聚） | 山脉、海沟、火山弧 |
| Divergent（离散） | 洋中脊、裂谷 |
| Transform（转换） | 走滑断层 |
| Inactive（非活动） | 无明显效应 |

**汇聚边界子类型**：

| 板块组合 | 子类型 | 典型地貌 |
|----------|--------|----------|
| 大陆-大陆 | Continental collision | 高原（喜马拉雅） |
| 大洋-大洋 | Oceanic subduction | 岛弧 + 海沟（日本） |
| 大陆-大洋 | Andean subduction | 海岸山脉 + 海沟（安第斯） |

**到边界距离**：多源 BFS 沿邻接图传播（球面距离 = 角距离 × 半径）。

---

## 欧拉极分配

- 随机旋转轴（球面均匀分布）
- 角速度：$\omega = v / (R \cdot 10^5)$ rad/yr（$v$ 为 cm/yr）
- 板块质心 × 运动方向 = 欧拉轴

---

## 真实地球板块数据导入（earth 主世界）

earth 验证世界不走合成管线，而是导入真实数据（`src/dreamulator/import_earth_tectonics.py`）：

- **板块边界**：PB2002（Bird 2003）——全球板块边界标准数字模型，52 个板块，
  含板块轮廓、边界线段与欧拉极。数据来源：
  [doi:10.1029/2001GC000252](https://doi.org/10.1029/2001GC000252)
  （Geochemistry, Geophysics, Geosystems, 4(3), 1027）。
- **地壳类型**：由 ETOPO1 水深经**洋-陆边界（OCB）** 判定。PB2002 本身对
  「洋壳」的定义是：海底年龄 < 180 Ma（[Mueller et al. 1997]）**或** 水深 >
  2000 m（ETOPO5）。因此 2000 m 是被动大陆边缘大陆/大洋地壳的物理分界。

地壳类型三段划分（阈值即 PB2002 的洋壳判据）：

| 类型 | 高程判据 | 地质含义 |
|------|----------|----------|
| `continental` | ≥ −2000 m | 陆地 + 大陆架 + 上陆坡（≈ 41%） |
| `transitional` | −3000 m ~ −2000 m | 大陆坡（洋-陆过渡带） |
| `oceanic` | < −3000 m | 深海洋壳（≈ 59%） |

板块欧拉极来自 `PB2002_poles.dat`（极纬度 / 极经度 / 度每百万年 CCW），换算为
单位旋转轴 + `omega_rad_yr`。板块类型（oceanic/continental/mixed）由面积加权的
大陆地壳比例推出（> 0.6 大陆、< 0.4 大洋、其余混合）。边界类型（convergent/
divergent/transform）复用 `boundary_detector.detect_boundaries`，从真实欧拉极的
相对运动推导（与合成管线同一套第一性路径）。

## 参考资料

- Cox, A., & Hart, R. B. (1986). *Plate Tectonics: How It Works*. Blackwell.
- Bird, P. (2003). *An updated digital model of plate boundaries*. Geochemistry,
  Geophysics, Geosystems, 4(3), 1027. [doi:10.1029/2001GC000252](https://doi.org/10.1029/2001GC000252)
- `src/dreamulator/map/plate_generator.py` — `assign_euler_poles()`
- `src/dreamulator/map/boundary_detector.py` — `classify_boundary()`
- `src/dreamulator/import_earth_tectonics.py` — earth 真实板块/地壳导入
