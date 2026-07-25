# 板块构造模型

> 从 `src/dreamulator/map/plate_generator.py` 和 `boundary_detector.py` 抽取。  
> 详细算法参考：`docs/usage/terrain-pipeline.md` §3–4

---

## 欧拉极运动学

刚体球面运动由欧拉极（旋转轴）和角速度描述：

$$\mathbf{v}(P) = \boldsymbol{\omega} \times \mathbf{P}$$

其中 $\mathbf{P}$ 为球面上一点（单位向量），$\boldsymbol{\omega}$ 为角速度向量。

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

$$\mathbf{v}_{rel} = \mathbf{v}_A(P) - \mathbf{v}_B(P), \quad v_n = \mathbf{v}_{rel} \cdot \hat{\mathbf{n}}, \quad v_t = |\mathbf{v}_{rel} - v_n\hat{\mathbf{n}}|$$

| 边界类型 | 判定条件 |
|----------|---------|
| **convergent**（汇聚） | $v_n > 0.5$ cm/yr |
| **divergent**（离散） | $v_n < -0.5$ cm/yr |
| **transform**（转换） | $v_t / v_{total} > 0.7$（切向主导） |

**到边界距离**：多源 BFS 沿邻接图传播（球面距离 = 角距离 × 半径）。

---

## 欧拉极分配

- 随机旋转轴（球面均匀分布）
- 角速度：$\omega = v / (R \cdot 10^5)$ rad/yr（$v$ 为 cm/yr）
- 板块质心 × 运动方向 = 欧拉轴

---

## 参考资料

- Cox, A., & Hart, R. B. (1986). *Plate Tectonics: How It Works*. Blackwell.
- `src/dreamulator/map/plate_generator.py` — `assign_euler_poles()`
- `src/dreamulator/map/boundary_detector.py` — `classify_boundary()`
