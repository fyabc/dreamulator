# 世界生成管线总览

> 本文档是完整世界推演的**引擎目录**：每个引擎（层级）一行——依赖、产出、技术参考
> 指针。地图生成段的内部结构（geological 引擎内嵌的 8 相位地形管线）以嵌套小表表达。
> 各引擎的技术细节在对应文档，此处只给结构、依赖与指针。

---

## 引擎 DAG

完整世界推演按学科层级组织，`dreamulator build` 由 `engine/pipeline.py` 拓扑排序后
逐引擎执行（引擎经 `discover_engines()` 自动发现）：

```
physics → chemistry → astronomy → geological → climate → ecology → civilization
（无引擎）  （无引擎）   AstronomyEngine  GeologicalEngine*  ClimateEngine  EcologyEngine  CivilizationEngine
```

- **physics / chemistry 无引擎**：这两层的 input 为空即标准物理/化学，derived 无内容。
- **geological 是复合引擎**：内部跑地形管线 8 相位（见下表），气候模拟嵌在其中
  6/8 相位；climate 层因此既被 geological 内嵌顺跑、也有独立引擎
  （`--only climate` 增量重建）。
- **climate 的 geological 依赖走 maps 不走 DAG**（`climate.py:48`）：气候引擎从
  `maps/{planet}/` 读 geological 的 mesh 产物，而非层级 derived 文件。

## 引擎目录

| 引擎 | 层级 | requires | 产出 | 技术参考 |
|------|------|----------|------|---------|
| `AstronomyEngine` | astronomy | — | 恒星/行星派生参数、`system_catalog.yaml` 天体目录 | 无 pipeline 文档（缺口已登记 roadmap §七-2）；纯函数见 `engine/stellar_physics.py`、`satellite_dynamics.py` |
| `GeologicalEngine` | geological | astronomy | `maps/{planet}/`（cvt_mesh.json、elevation.png、plates.json、图层导出） | [geological-pipeline.md](geological-pipeline.md) |
| `ClimateEngine` | climate | astronomy, geological | 温度/降水/Köppen/风/洋流/月度场，写回 mesh | [climate-pipeline.md](climate-pipeline.md) |
| `EcologyEngine` | ecology | climate, geological | 群系/NPP/可驯化/土纲/生物地理省图层 | [ecology-pipeline.md](ecology-pipeline.md)；设计动机见 [ecology-layer.md](../proposals/ecology-layer.md) |
| `CivilizationEngine` | civilization | ecology, climate, geological | 文明层 derived（消费 mesh 上的气候/生态字段） | [civilization-pipeline.md](civilization-pipeline.md)；Phase 3C 半结构化设计见 [civilization-layer.md](../proposals/civilization-layer.md) |

**地形管线 8 相位**（`GeologicalEngine` 内部，`map/terrain_pipeline.py:189-716`，
配置 = `terrain_config.yaml`；每相位有内容指纹缓存，详见 geological-pipeline）：

| 相位 | 名称 | 行号 | 细节 |
|------|------|------|------|
| 1/8 | CVT 网格 | `:235` | geological-pipeline §CVT |
| 2/8 | 板块剖分 | `:280` | 同 §板块（欧拉极分配在此相位的字段分配里，不单列） |
| 3/8 | 构造时间演化 | `:325` | 同 §时间演化（Cortial 2019） |
| 4/8 | 边界检测 | `:424` | 同 §边界 |
| 5/8 | 地形合成 | `:465` | 同 §地形（海陆分类 water_class 在本相位末尾写入） |
| 6/8 | 气候模拟 | `:615` | `GeologicalEngine` 默认跳过此相位，气候由 `ClimateEngine` 构建；委托 [climate-pipeline.md](climate-pipeline.md) §10 |
| 7/8 | 极地冰盖 | `:638` | 同 §8 极地冰盖（相位开始前先标记封闭盆地湖泊，见 §9） |
| 8/8 | 导出 | `:650` | 同 §导出（大内流湖升级在本相位开头） |

全球网格上不做河网汇流；渲染用的汇流、河流与湖泊在高分辨率画布链上计算，见
[canvas-chain.md](canvas-chain.md)。

区域后处理（管线之外）：**Gaea 局部精细化**——跑完全管线拿到地形/气候/土壤/植被后
选固定区域高分辨率细化，未实现，见 [gaea-refinement.md](../proposals/gaea-refinement.md)。

## 数据流

```
stellar/planets 参数（astronomy）
      │  luminosity / orbit / tilt / rotation / greenhouse
      ▼
GeologicalEngine ── terrain_pipeline 8 相位（默认跳过 6/8 气候）
      │  maps/{planet}/: elevation / crust / plates / lakes / ice
      ▼
ClimateEngine ── 写回 mesh 气候字段
      ▼
EcologyEngine ── 群系 / NPP（消费 mesh 上的 T/P）
      ▼
CivilizationEngine ── 文明推演（消费地形/气候/生态底图）
```

## 分支与增量重建

每个分支只重跑受影响的层（如 geological 层分叉只重跑地图段），引擎输出按层落在
分支目录；子相位缓存按输入内容指纹失效（改 geography.yaml 不需要 `--force`）。
分支系统见 [layer-control-model.md](../proposals/layer-control-model.md) 与
[geological-pipeline.md](geological-pipeline.md)。
