# 世界生成管线总览

> 本文档是「行星地图生成」的顶层管线目录（阶段 1–12），把每个阶段映射到对应的层级
> pipeline 文档。各阶段的技术细节在对应文档中，此处只给顺序、依赖与指针。

---

## 阶段目录

| 阶段 | 名称 | 层级 | 文档 |
|------|------|------|------|
| 1 | 球面 CVT 网格生成 | 地质 | [geological-pipeline.md](geological-pipeline.md) §2 |
| 2 | 构造板块 | 地质 | 同 §3 |
| 3 | 欧拉极与板块运动学 | 地质 | 同 §4 |
| 4 | 边界检测与分类 | 地质 | 同 §5 |
| 5 | 地形合成 | 地质 | 同 §6 |
| 6 | 海平面与基础分类 | 地质 | 同 §7 |
| 7 | 气候模拟 | **气候** | [climate-pipeline.md](climate-pipeline.md) |
| 8 | 河流与水文 | 地质 | [geological-pipeline.md](geological-pipeline.md) §8 |
| 9 | 地表演化侵蚀 | 地质 | 同 §9 |
| 10 | 植被与生态 | **生态** | [ecology-layer.md](../proposals/ecology-layer.md) |
| 11 | 数据导出与可视化 | —（输出） | [geological-pipeline.md](geological-pipeline.md) §10 |
| 12 | Gaea 局部精细化 | —（区域后处理） | [gaea-refinement.md](gaea-refinement.md) |

> **编号说明**：本表的「阶段 1–12」是**全局管线**编号（含气候/生态/Gaea）。
> `geological-pipeline.md` 内部只含地质层 9 个阶段（§2–§10），编号已按地质层重排
> （其「阶段 7」= 水文，不同于本表的全局「阶段 7」= 气候）。

## 层级映射

- **地质层**（全局阶段 1–6、8–9、11）：CVT 网格 + 板块构造 + 地形合成 + 水文 + 侵蚀 + 导出
  → [geological-pipeline.md](geological-pipeline.md)
- **气候层**（全局阶段 7）：温度 / 降水 / Köppen → [climate-pipeline.md](climate-pipeline.md)
- **生态层**（全局阶段 10）：Whittaker 群系 / NPP / 可驯化标签 → [ecology-layer.md](../proposals/ecology-layer.md)
- **区域后处理**（全局阶段 12）：Gaea 局部精细化（跑完生态层拿到地形/气候/土壤/植被后选固定区域细化）
  → [gaea-refinement.md](gaea-refinement.md)

## 与 DAG 层级的关系

完整世界推演的 DAG 是：

```
physics → chemistry → astronomy → geological → climate → ecology → civilization
```

本管线（阶段 1–12）覆盖的是中间的**地图生成段**（geological → climate → ecology +
导出 + Gaea）。上游 physics/chemistry/astronomy 提供恒星/轨道/行星物理参数（作为
各阶段输入），下游 civilization 消费地图输出（地形/气候/生态作为文明推演的底图）。

## 数据流

```
stellar/planets 参数 (astronomy 上游)
      │
      ▼
[阶段 1-6]  地质层：CVT 网格 + 板块 + 地形 + 海平面
      │  elevation / crust / plates
      ▼
[阶段 7]    气候层：温度 / 降水 / Köppen
      │  temperature / precipitation / koppen
      ▼
[阶段 8-9]  地质层：水文（河流/湖泊）+ 侵蚀
      │
      ▼
[阶段 10]   生态层：Whittaker 群系 / NPP
      │
      ▼
[阶段 11]   导出：栅格图层 + JSON
      │
      ▼
[阶段 12]   Gaea 局部精细化（可选）：选定区域高分辨率细化
```

## 分支与增量重建

每个分支只重跑受影响的阶段（如改海平面只重跑阶段 6+），而非重新生成整个地图——
分支系统见 [layer-control-model.md](../proposals/layer-control-model.md) 与
[geological-pipeline.md](geological-pipeline.md) §12.4。
