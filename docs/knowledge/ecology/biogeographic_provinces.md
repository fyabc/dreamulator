# 生物地理分区（Biogeographic Provinces）

> 为 dreamulator 生态引擎的生物地理分区提供参考。生物地理分区把陆域划分为
> 嵌套的"大区 → 省"层级，是生态层与文明层（civmap 领土锚定）的空间接口。

---

## 一、三大标准（可互相对照）

| 标准 | 层级 | 划分依据 | 量级 |
|------|------|---------|------|
| **Wallace 区系**（Holt et al. 2013） | realm → region | 系统发育独特性（21,037 种两栖/鸟/哺乳类的分布+谱系） | 11 realm / 20 region |
| **Udvardy 生物地理省**（Udvardy 1975） | realm → province → biome | 区系相似性 + 植被 | 8 realm / 193 province / 14 biome |
| **WWF 陆域生态区**（Olson et al. 2001） | realm → biome → ecoregion | 物种组合 + 生态过程 | 8 realm / 14 biome / 825 ecoregion |

三者的共同逻辑：**最上层是"海洋隔离的大区（realm）"，下层是区内连续或相似的
生态单元**。Wallace 的 11 realm 与 Udvardy/WWF 的 8 realm 差异主要在
"过渡带"（Saharo-Arabian、Sino-Japanese、Panamanian）是否独立成区（Kreft & Jetz 有争议）。

---

## 二、dreamulator 的分区算法（`partition_biogeographic_provinces`）

引擎用**两级嵌套 + 小岛归并**，落在 CVT mesh 上（上层决定下层——cvt_mesh 是
架空世界分区的唯一权威，GeoJSON 只是导出视图）：

```
realm    = 陆域连通分量（elevation ≥ 0 的相邻 cell，BFS）——"海洋隔离"的直觉
province = realm 内连续同 biome 区域（同 biome 的相邻 cell 连通分量）
           → 合并：每 realm 合并到 target_provinces_per_realm 个省（默认 1）
           → 小岛归并：< min_province_cells（默认 20）的省归入最近的大省
```

**关键设计**（`map/biogeography.py`）：

1. **realm 是硬边界**——合并只在 realm 内进行，跨 realm（海洋隔开）永不合并。
2. **小岛归并**——1-cell 小岛（~51 km）作为独立"省"太细；Udvardy/Wallace 处理
   的是"群岛"而非单个小岛。故 < 20 cell 的省按球面质心距离归入最近的大省。
3. **稳定 ID**——省 ID 形如 `"realm.province"`（1-based），未来 civmap 可直接引用。

**参数**：`target_provinces_per_realm`（每 realm 目标省数，默认 1）、
`min_province_cells`（小岛归并阈值，默认 20 cell）。

**与 civmap 的承接**：`VoronoiCell.biogeographic_province`（生态区划）与
`province_id`（真实地球行政区划，geoBoundaries）语义不同、命名已解耦；未来
civmap 架空世界模式可用生态分区作为领土锚定（详见 `docs/design/ecology-layer.md` §2.4）。

---

## 三、参考来源

- Holt, B. G. et al. (2013). "An Update of Wallace's Zoogeographic Regions of the World." *Science* 339:74–78 — https://www.science.org/doi/abs/10.1126/science.1228282
- Udvardy, M. D. F. (1975). "A Classification of the Biogeographical Provinces of the World." *IUCN Occasional Paper* 18.
- Olson, D. M. et al. (2001). "Terrestrial Ecoregions of the World: A New Map of Life on Earth." *BioScience* 51:933–938 — https://academic.oup.com/bioscience/article/51/11/933/227116
- Wallace, A. R. (1876). *The Geographical Distribution of Animals*.

## 相关文档

- `soil_orders.md` — 土壤（province 的植被/肥力基础）
- `../climatology/` — Whittaker/Köppen（province 的 biome 来源）
- `docs/design/ecology-layer.md` §2.4 — civmap 承接性
