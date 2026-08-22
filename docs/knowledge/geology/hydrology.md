# 水文学：D8 流向与汇水面积

> 实现：`src/dreamulator/map/hydrology.py` · 设计：`docs/design/geological-pipeline.md` §9

球面 CVT 网格上的河流网络生成，是**侵蚀后地形**的一次性水文学产品：洼地填平 →
D8 流向 → 流量累积 → 河网分级/提取，填入 `VoronoiCell` 的
`flow_direction` / `flow_accumulation` / `river_id` / `river_order`。侵蚀循环
（erosion.py）每次迭代复用同一套纯函数，避免两套水文逻辑漂移。

---

## 1. 洼地填平（priority-flood）

CVT 地形合成会产出大量局部洼地（pit）：直接跑 D8 会在每个洼地得到一个 sink、
河网破碎。用 **priority-flood**（Barnes et al. 2014，O(N log N)）填平：

1. 从海洋 cell（`elevation < sea_level`）出发，用最小堆按高程向外扩张；
2. 每个陆 cell 的临时标高推到 `max(elevation, spill)`（spill = 已填邻居的标高）；
3. 填平只在**临时数组**上进行，**不写回** `cell.elevation`——最终河网提取仍在真实
   （已侵蚀）地形上做；
4. 内流盆地（无通海出口）在连通球面上不存在（priority-flood 从海洋可达全部 cell），
   完整的湖泊/内流水收支留后续。

`priority_flood_fill(elevation, is_land, neighbors) -> (filled, connected)`：
`filled` 是填平后的标高，`connected` 标记海洋可达的 cell（连通球面上恒全真）。

## 2. D8 流向（最陡下降）

每个陆 cell 的流向是其**最陡下降**邻居：

```
gradient(i→j) = (h_i − h_j) / d_ij
flow_dir[i] = argmax_j gradient(i→j)    # 无下坡邻居 → −1
```

`d_ij` 是大圆距离。D8 只用相对梯度比较，单位（km/m）不影响方向。

## 3. 平区路由（flat routing）

填平后的表面上，溢流台地（spill flat）的 cell 没有严格下坡邻居（`flow_dir=−1`）。
从所有「已解析」cell（海洋 + 已持有下坡方向的 cell）做多源 BFS，把未解析陆 cell
路由到**非上坡**的父 cell（`filled[parent] ≤ filled[child]`）——否则上游山脊 cell
会把平地水导向坡上（已由单元测试覆盖）。

## 4. 流量累积（拓扑排序）

Kahn 拓扑排序，从源头到河口累加上游汇水面积：

```
accum(i) = area(i) + Σ accum(j)   (j ∈ upstream(i))
accum(ocean) = 0                  # 海洋不累积；河口陆 cell 持全流域
```

`flow_accumulation` 单位 **km²**（非 cell 数）。海洋 cell 保持 0，河口陆 cell 的
累积即整条河的流域面积（径流量可在河口读取）。

## 5. 河流分级与河网提取

- `classify_rivers`：按累积面积阈值分级 `{100, 1000, 10000, 100000}`（单位「cell
  数」）→ `river_order` 1–4。阈值按 `cell_area_km2`（平均 cell 面积）缩放，使分级
  **分辨率无关**——order 1 ≈ 100 个 cell、order 4 ≈ 10 万个 cell，与网格精度无关。
- `assign_river_ids`：从河口（流入海洋、累积 ≥ 阈值的陆 cell）逆流追溯，每步跟随
  最大支流，给干流 cell 打 `river_id`；阈值同样按 `cell_area_km2` 缩放。

## 6. 闭合内陆湖（endorheic basin）

`detect_closed_basins`：低于海平面但不连通全球海洋（最大连通分量）的闭合盆地，
标记为 `VoronoiCell.is_lake = True`——即里海/死海/大盐湖型的内陆湖。它们仍是排水
终点（sink），只是分类上区别于海洋；完整的湖泊水收支（§9.5）留后续。

## 参考

- Barnes, R., Lehman, C., & Mulla, D. (2014). Priority-flood: An optimal
  depression-filling and watershed-labeling algorithm for digital elevation
  models. *Computers & Geosciences*, 62, 117–127.
- O'Callaghan, J. F., & Mark, D. M. (1984). The extraction of drainage networks
  from digital elevation data. *Computer Vision, Graphics, and Image Processing*,
  28(3), 323–344.（D8 流向）
