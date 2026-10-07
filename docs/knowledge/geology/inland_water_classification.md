# 内陆水体分类学：water_class × is_lake 的二维语义

> 实现：`src/dreamulator/map/water_bodies.py`（分类）、`src/dreamulator/engine/ecology.py`
> 与 `civilization.py`（下游消费）、`src/dreamulator/map/climate_simulator.py`（湖面
> 温度机制）。管线细节见
> [ecology-pipeline.md](../../design/pipelines/ecology-pipeline.md) 与
> [civilization-pipeline.md](../../design/pipelines/civilization-pipeline.md)；
> 湖命运的 P−E 判决提案见
> [inland-water-refine.md](../../design/proposals/inland-water-refine.md)。

梦想机的地表水划分用**两个正交字段**表达，缺一不可：

- **`water_class`**（"ocean" / "land"）— 海陆划分的权威口径：该格在气候意义上
  是海洋性还是大陆性表面。由地形管线的连通性洪水填充（只有与全局大洋连通的
  水域才算 ocean）或真实地球 GSHHG 导入写入；气候层、前端底图、生态/文明层
  的海陆判断一律以此为准。
- **`is_lake`**（bool）— 内陆水体标志：该格是一个与全局大洋不连通的湖泊/
  内陆海水面，无论其 water_class 是什么。

二者组合出四类语义，各有地球原型：

| water_class | is_lake | 语义 | 地球原型 | 生态层 | 文明层 |
|---|---|---|---|---|---|
| land | false | 陆地（含低于海平面的干盆地） | 吐鲁番（−154 m）、卡塔拉洼地、死谷 | Whittaker 群系 | 正常评分 |
| land | true | 小内陆湖（气候上可忽略） | 死海（605 km²）、大盐湖 | biome=lake 哨兵 | 湖面归零，湖滨淡水红利 ×1.15 |
| ocean | false | 全局大洋 | 太平洋 | biome=ocean | 归零 |
| ocean | true | 大内陆海（气候上类洋） | 里海（371 000 km²）、黑海、五大湖 | biome=lake 哨兵 | 湖面归零，湖滨淡水红利 ×1.15 |

## 尺寸分界的物理依据

大内陆海升级为 ocean-class 的面积阈值是 6×10⁴ km²（`_MIN_OCEAN_LAKE_KM2`，
= 海洋性调节尺度 250 km 的平方）。一片水体至少要有这么宽，其对周边气候的
调节（热容量、内部蒸发源、可能的环流）才能超出自身范围。里海（371k km²）/
红海（438k）/黑海（436k）通过，死海（605 km²）差两个数量级不通过——阈值
不敏感。生成世界由 `upgrade_large_endorheic_lakes` 执行同一分界：封闭
低于海平面的盆地，连通面积过阈值且湖格占比过半才整体升级；干盆地（无湖格）
无论多大都不升级。

## 各层的湖语义（2026-10 语义闭合轮确立）

- **气候层**：湖格（is_lake & ocean-class）走大陆性温度机制——陆地 EBM 温度 +
  湖面热容量（4×10⁷ J/m²/K，≈10 m 混合层）+ 0 °C 冻结钳，而不是开阔海洋的
  SST 剖面。年均温 ≥0 °C 的湖保留陆地温度（夏季融冰的季节湖），<0 °C 的
  永冻湖保留海洋 SST 覆盖。
- **生态层**：湖格无论 water_class 都是 `biome=lake` 哨兵（湖面没有陆地植被，
  不落在 Whittaker 温度-降水平面上），NPP/土壤为 `None`，生物地理分区排除
  湖面（湖是被陆地包围的盆地，排除不断开 realm 连通性）。
- **文明层**：湖面不宜居不可耕（评分归零）；与湖相邻的陆地格获淡水红利
  （habitability ×1.15，观测拟合类参数，见 civilization-pipeline §3）。
- **前端**：底图（terrain/landsea）湖面画浅青色（冰湖浅灰蓝，判据 = 年均温
  <0 °C，与引擎季节湖口径一致）；flow 专题层湖面同色；Whittaker 专题层 lake
  有独立色。小湖不产生海岸线（距海 BFS 以海陆掩膜为种子），湖岸由淡水红利
  而非 coastal 语义承载。

## 关键不变式（tests/test_engine/test_inland_water_semantics.py 钉死）

1. `water_class=land` 且非湖的格子必须有陆地群系与非空 NPP/土壤（有气候数据时）。
2. `is_lake=True` 的格子 biome 必为 "lake"、habitability 必为 0。
3. 湖两岸陆地属同一生物地理 realm。
4. `resolve_land_mask` 在网格未写 water_class 时回退连通性，不会全判海洋。

## 参考

- GSHHG（Global Self-consistent, Hierarchical, High-resolution Geography
  Database）level 1（陆地）/ level 2（湖泊）多边形层级——真实地球两条
  water_class 写入路径之一的来源。
- Mason, I. M. et al. (1994) 与 Birkett, C. M. (1995) 关于封闭湖水位与流域
  水收支的测高研究——湖面 P−E 判决（提案）的观测背景。
