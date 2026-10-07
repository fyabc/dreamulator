# 内陆水体 refine：湖命运的 P−E 判决（未实现提案）

> 状态：提案（2026-10 立案，随内陆水体语义闭合轮降级方案一并登记——本轮只修
> (a) 生态文明消费与 (b) 前端显示，本提案描述完整闭环的后续实现）。
> 语义基础见 [knowledge/geology/inland_water_classification.md](../../knowledge/geology/inland_water_classification.md)。

## 为什么要做

语义闭合轮之后，湖格的下游语义已经一致（biome=lake、湖滨红利、前端着色），
但**每个湖的命运是静态的**：所有湖一律按「常年水面」处理。物理上湖有四种
结局，取决于流域水量收支（汇水面积 × 净降水 vs 湖面蒸发）：

1. **溢流（exorheic）** — 入流超过湖盆容量，湖水从 rim 鞍口溢出成外流河。
   地球原型：的的喀喀湖（溢流入 Amazon 支系）、贝加尔湖（Angara 外流）。
   此时的「河止于湖」是错的——河应穿过湖从溢流点继续下行。
2. **常年湖（terminal lake）** — 收支平衡于水面蒸发，湖面稳定在盆内某高度。
   地球原型：里海（零海平面以下但水面稳定）。
3. **盐沼干湖（playa）** — 蒸发远超入流，湖面只在雨季短暂存在，平时是盐壳
   干湖床。地球原型：咸海（正在变成 playa）、大盐湖边缘、Death Valley 的
   Racetrack。生态/显示语义应为陆地 + 盐壳，而非水面。
4. **沉积填平** — 长期尺度上湖盆被沉积物填满变成陆地。地球原型：华北平原
   上的古湖沼。Myr 尺度过程，v1 可不做。

实证驱动案例（nacrea，用户 10-07 报告）：cell #50225 半干旱内陆海（当前终点
成立）vs #95577 热带内陆海（P≫E，物理上应填满溢出而非维持稳定湖面）——静态
湖语义对两类格子无法区分。

## 方案：气候层后置的水文 refine 子步

新增独立引擎 `HydroRefineEngine`（DAG 落位 = ECOLOGY 层、排在 EcologyEngine
之前，`requires = ["climate", "geological"]`；参照 EcologyEngine 模板：
无独立 input_files、加载共享 cvt_mesh、写回 mesh + YAML summary）。独立引擎
而非气候内部子步的理由：refine 不改温度/降水场，`--only` 可单独重跑且不触发
整个气候重建。

```
geological → climate → hydro refine → ecology → civilization
```

核心函数 `refine_inland_water(mesh, climate_fields)`（纯函数，无 RNG）：

1. **逐封闭盆地聚合**：对每个 is_lake 连通盆地，汇水面积 = 盆地面积 + 按流向
   （flow_direction 已经算好）反推的全部上游汇水区面积（flow_accumulation
   已是每格上游面积，直接求和即可）。
2. **水量收支**：入流 I = Σ(上游格 P)（mm/yr × 面积）；支出 E_lake = 湖面
  蒸发，用现成 Hamon PET（`climate_physics.potential_evapotranspiration_hamon`，
   湖面实际蒸发 ≈ PET × 湖面系数 ~1.0，可标定）。
3. **判决四类**（阈值待标定，Earth 湖泊对照集校准）：
   - I > E_lake 且盆地存在溢流鞍口 → **溢流**；
   - |I − E_lake| 在平衡带内 → **常年湖**；
   - I ≪ E_lake → **playa**（盐壳干湖）。
4. **溢流接通河网**：溢流点（rim 最低鞍口）作为伪源点，river_id / river_order
   从该点向下游延伸接通既有河网——「河穿湖」的最低成本实现。

### 需要新增的字段（现状缺失）

- `lake_state`（枚举：overflow / perennial / playa，挂在 VoronoiCell，写进
  `STATIC_CELL_COLUMNS` 或 `DYNAMIC_CELL_FIELDS`——由气候后处理产生，归
  DYNAMIC；`tests/test_map/test_export.py` 的 registry 覆盖测试强制同步）。
- **rim/spill 高度不落盘**是当前硬缺口：`priority_flood_fill` 的 spill level
  只在临时数组（`hydrology.py`），`_apply_deposition_fill` 的湖深也不输出。
  refine 需要每盆地的 rim 鞍口位置与高度，地形管线导出阶段需新增盆地级
  元数据（放 features.json 或独立 lakes.json，避免动 cell 模型）。

### v1 边界（明确不做）

- **不动高程**：只写标签 + 河网连通，不改 elevation（湖面高度反馈给地形的
  闭环归 climate-steady-coupling 提案）。
- **不反馈气候**：湖面蒸发不从大气水汽预算里扣（预算内核不动，符合引擎
  纪律 6「守恒账本先于新机制」——refine 是判决不是新物理源）。
- 沉积填平不做（Myr 尺度）。

## 一致性风险清单（实现时必须守）

- refine **不得改 `water_class`**（湖结局写独立 `lake_state`；water_class 是
  气候层已消费的权威划分，改它会级联重跑气候）。
- `distance_to_coast` 不受溢流影响（BFS 语义保持现状；溢流河不是海岸线）。
- 生态/文明引擎天然在 refine 之后（DAG 顺序保证），playa 格按陆地语义处理
  （biome 走 Whittaker，无 NPP 例外）——refine 需在 ecology 消费前写好标签。
- 前端：playa 显示为陆地色 + 盐壳纹理（新着色分支），溢流河按普通河流着色。
- earth 对照：GSHHG 导入的湖（level 2）没有 flow_accumulation 之上的判决
  输入差异，refine 对 earth 应近似复现真实湖分布（里海 perennial、咸海
  接近 playa、的的喀喀溢流）——这本身就是标定验收集。

## 已否证/排除的方向

- **在气候引擎内部做湖面蒸发反馈**（湖从水汽预算取水）：违反「每轮只新增
  一个闭合假设」纪律，且湖面蒸发是分布参数化弱点，先做判决再做反馈。
- **用湖面高度迭代求平衡（implicit lake level）**：需要 rim 剖面 + 高程反馈，
  v1 用 P−E 阈值判决 + 分类标签足够表达四类结局，迭代平衡留给
  climate-steady-coupling。
