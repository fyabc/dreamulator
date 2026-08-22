# CVT 球面网格生成

> 从 `src/dreamulator/map/cvt_mesh.py` 抽取。  
> 详细算法参考：`docs/design/geological-pipeline.md` §2

---

## 算法流程

```
Fibonacci 球面螺旋 → 随机扰动 → Lloyd 松弛 (迭代) → SphericalVoronoi → 邻接图
```

---

## Fibonacci 球面螺旋

使用黄金比例 $\Phi = (1+\sqrt{5})/2$ 在单位球面上均匀分布 N 个点：

$$\varphi_k = \arccos\left(1 - \frac{2(k+0.5)}{N}\right), \quad \theta_k = \frac{2\pi k}{\Phi}$$

其中 $\varphi$ 为余纬（极角），$\theta$ 为经度，$k = 0, 1, \dots, N-1$。
笛卡尔坐标（y 轴朝北极）见下文坐标转换。

**优点**：确定性（无需 RNG）、O(N) 生成、面积近似均匀（每点约 $4\pi/N$
球面度）、无极点聚集。

---

## 随机扰动

切向高斯位移：$\sigma = jitter\_sigma \cdot \sqrt{4\pi/N}$

其中 $\sqrt{4\pi/N}$ 为平均 cell 间距。扰动后重新投影到单位球面。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `jitter_sigma` | 0.3 | 0 = 无扰动（纯 Fibonacci），越大越随机 |

---

## Lloyd 松弛

每轮迭代：计算 SphericalVoronoi → 欧氏质心 → 投影回球面。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `lloyd_iterations` | 8 | 迭代次数，越多 cell 越均匀 |

---

## SphericalVoronoi

`scipy.spatial.SphericalVoronoi(points, radius=1.0, center=[0,0,0])`

- 输入：单位球面上的 N 个 3D 点
- 输出：每个 cell 的 Voronoi 顶点和区域索引
- `sort_vertices_of_regions()` 确保多边形顶点顺时针排列

---

## 邻接图

Delaunay 对偶：构建 vertex→cells 映射，共享 ≥ 2 个 Voronoi 顶点的 cell 为边邻接。

---

## Cell 面积（球面多边形）

使用 L'Huilier 定理的三角扇区求和：

$$\Omega = \sum_i 2\arctan\left(\frac{\mathbf{n} \cdot (\mathbf{v}_i \times \mathbf{v}_{i+1})}{1 + \mathbf{n}\cdot\mathbf{v}_i + \mathbf{v}_i\cdot\mathbf{v}_{i+1} + \mathbf{n}\cdot\mathbf{v}_{i+1}}\right)$$

面积 = $|\Omega| \cdot R^2$（R = 行星半径 km）

**等价形式（球面角盈 / spherical excess）**（自 design/geological-pipeline.md 附录 A.7
上浮，2026-08）：

$$A = \left|\sum_{i=1}^{n}\theta_i - (n-2)\pi\right| \cdot R^2$$

其中 $\theta_i$ 为第 $i$ 个顶点的球面内角，$n$ 为顶点数；
立体角 $\Omega = A / R^2$（steradians）。

---

## 坐标转换

**源码**：`pipeline_types.py`

$$\begin{aligned} (x,y,z) &= (r\cos\phi\cos\theta,\; r\sin\phi,\; r\cos\phi\sin\theta) \\ (\phi,\theta) &= (\arcsin(y/r),\; \arctan2(z,x)) \end{aligned}$$

角距离：$\Delta\alpha = \arccos(\mathbf{p}_1 \cdot \mathbf{p}_2)$

---

## 角距离（Haversine）

（自 design/geological-pipeline.md 附录 A.1 上浮，2026-08）

$$d(\varphi_1,\lambda_1,\varphi_2,\lambda_2) = 2\arcsin\sqrt{\sin^2\frac{\Delta\varphi}{2} + \cos\varphi_1\cos\varphi_2\,\sin^2\frac{\Delta\lambda}{2}}$$

其中 $\Delta\varphi = \varphi_2 - \varphi_1$，$\Delta\lambda = \lambda_2 - \lambda_1$。
单位球面上 $d$ 即角距离（rad），乘行星半径得大圆距离。
Haversine 形式在小距离下比 $\arccos(\mathbf{p}_1\cdot\mathbf{p}_2)$ 数值更稳定。

---

## 性能参考

| nodes | Lloyd | 耗时 |
|-------|-------|------|
| 4,096 | 5 | ~7s |
| 50,000 | 8 | ~40s |
| 100,000 | 8 | ~70s |

---

## 参考资料

- Du, Q., Faber, V., & Gunzburger, M. (1999). *SIAM Review*, 41(4), 637-676.（CVT 理论基础）
- scipy.spatial.SphericalVoronoi 文档
