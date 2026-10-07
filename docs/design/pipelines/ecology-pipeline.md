# 生态引擎实现架构

> 本文档描述 dreamulator 生态引擎（EcologyEngine）的计算方式：海陆判据、Whittaker
> 群系分类（含湖泊哨兵）、Miami 净初级生产力、可驯化标签、USDA 土壤分类与生物地理
> 分区，以及输出的 summary 格式。
> 对应源码：`src/dreamulator/engine/ecology.py`（引擎封装）、
> `engine/ecology_physics.py`（纯函数库）、`src/dreamulator/map/biogeography.py`
>（分区算法）、`src/dreamulator/map/water_bodies.py`（海陆判据）。
> 知识背景见 [knowledge/ecology/ecological_mathematical_models.md](../../knowledge/ecology/ecological_mathematical_models.md)
>（Miami 模型）、[soil_orders.md](../../knowledge/ecology/soil_orders.md)、
> [biogeographic_provinces.md](../../knowledge/ecology/biogeographic_provinces.md)。

---

## 1. 在 DAG 中的位置与数据流

EcologyEngine 声明 `requires = ["climate", "geological"]`：地质层提供 CVT 网格
（`maps/<planet>/cvt_mesh.msgpack.gz`），气候层把 `temperature_C`、
`precipitation_mm` 等字段写回同一网格。生态引擎加载该网格，逐格计算生态字段后
原样写回，并输出 `layers/ecology/derived/ecology_summary.yaml`。生态引擎不产生
新几何，所有输出都是网格上的逐格属性。

引擎运行前校验气候数据在场（任一格有温度与降水），否则返回失败并提示先跑
气候引擎。恒星辐照经 `resolve_stellar_forcing` 解析为 PAR 比
（`par_ratio` = 光度 / 距离²，地球默认 1.0），供 Miami NPP 修正非太阳恒星。

## 2. 海陆判据（权威口径）

生态引擎使用 `resolve_land_mask`（`water_bodies.py`）作为海陆判据的唯一入口：
优先读 `water_class`（地形管线或 GSHHG 导入时写入的权威海陆划分），若网格上
没有任何一格标记为陆地（旧网格未写过该字段，反序列化后全为默认值 "ocean"），
则回退到连通性洪水填充（`compute_land_mask`）。生态引擎**不使用**裸海拔符号
（`elevation < 0` 会把吐鲁番式低于海平面的干盆地误判为海洋），也**不使用**
`crust_type`（那是板块地壳类型划分， continental/oceanic/transitional，与地表
水陆划分是两个正交概念——湖泊位于大陆地壳之上，用地壳类型判断会把湖面判成陆地）。

湖泊格（`is_lake=True`，无论 `water_class` 是 land 还是 ocean）在生态层有专门的
哨兵语义，见下节。

## 3. 逐格分类（classify_cell_ecology）

对每个格子，引擎按以下顺序短路：

1. **湖泊格**（`is_lake=True`）：直接返回 `WhittakerBiome.LAKE`。湖面没有陆地
   植被与土壤，不落在 Whittaker 温度-降水平面上；水生净初级生产力（湖产）留待
   后续轮次，当前为 `None`。可驯化标签查 `_DOMESTICATION_TABLE` 的 LAKE 行
   （三项全 low）。
2. **海洋格**（`water_class == "ocean"` 且非湖）：返回 `WhittakerBiome.OCEAN`
   哨兵，NPP 为 `None`（海洋 NPP 依赖上升流/营养盐/光照，与海面降水无关，
   Longhurst 海洋分区方案留待 Phase 3A.5）。
3. **陆地格**：`classify_whittaker_biome` 按年均温选热带（>18 °C）/温带
   （5–18 °C）/寒带（≤5 °C）热量带，带内按年降水量查表定群系；年均温 ≤−10 °C
   时无论降水多少均为冰原。Miami 模型（Lieth 1975）取温度限制与降水限制的
  较小者估算 NPP（gC/m²/yr），再乘 `par_ratio`。

下游消费不变式：`water_class=land` 且非湖的格子必须得到陆地群系与非空的
NPP/土壤值（测试 `tests/test_engine/test_inland_water_semantics.py` 钉死）。

## 4. 土壤分类（classify_soil）

土壤同样按湖泊/海洋短路（返回 `(None, None)`），且只有 `crust_type ==
"continental"` 的格子才发育土壤——这里用地壳类型是物理正确的：土壤需要风化的
母岩，大洋地壳上是深海沉积而非土壤。气候驱动的土纲查表（`ecology_physics.py`
的 `classify_soil`）按年均温与年降水定 USDA 12 土纲中的 9 个（entisol/histosol/
andisol 需要坡度/湿地/火山活动标志，留待后续），并给出肥力分级
（high/medium/low）。查表细节见 [soil_orders.md](../../knowledge/ecology/soil_orders.md)。

## 5. 生物地理分区（partition_biogeographic_provinces）

分区只用陆地格（`resolve_land_mask` 为真**且** `is_lake=False`——湖是被陆地
包围的盆地，排除湖面不会断开大陆连通性，湖两岸的陆地仍属同一个 realm）。
realm = 连通陆地分量（对应 Wallace 的界），province = realm 内连通同群系区域
（对应 Udvardy 的省），过碎的省向同 realm 邻省合并、孤岛小省并入最近大省。
算法细节见 [biogeographic_provinces.md](../../knowledge/ecology/biogeographic_provinces.md)。

## 6. 可驯化标签

`get_domesticable_profile` 按 Whittaker 群系查 Diamond（1997）框架表，输出三项
标签（`large_herbivores_*`、`staple_crops_*`、`draft_animals_*`，档位
high/moderate/low）。温带草原三项全高（文明摇篮群系），热带雨林大动物与役畜低
（疾病压力、缺乏碳水主粮驯化种）。纯规则查表，无 RNG。

## 7. 输出

- **网格字段**（写回 cvt_mesh，经 `DYNAMIC_CELL_FIELDS` 导出给前端）：
  `biome`、`npp_gc_m2_yr`、`domesticable_tags`、`soil_type`、`soil_fertility`、
  `biogeographic_province`。
- **ecology_summary.yaml**：水陆口径统计按 `resolve_land_mask`（非
  `crust_type`）——`n_land`（非湖陆地格）、`n_ocean`（非湖海洋格）、`n_lake`
  （湖泊格单列）、`biome_counts`（含 lake 条目）、陆地 NPP 统计、土纲分布、
  realm/province 计数、可驯化亮点计数。
