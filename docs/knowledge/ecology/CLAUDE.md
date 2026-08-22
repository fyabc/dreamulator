# 生态学知识库

目录于 2026-08 docs 重组时建立（knowledge/CLAUDE.md 结构图早已宣称本目录）。
ecology 层 P0（Whittaker 群系 + NPP + 可驯化标签）与 P1a（土壤层 + 生物地理分区）
已实施（v0.20.0 / 2026-08）；物种层（功能群/食物网/实例化器）为 P1b。

## 已有文档

- `ecological_mathematical_models.md` — 生态学数学模型参考（种群动力学、物种相互作用、代谢标度理论、食物网、群落生态学、生态系统级、演化动力学；含 dreamulator 生态引擎方程体系设计）
- `soil_orders.md` — USDA 12 土纲 + 肥力分级 + `classify_soil` 简化查表（P1a 土壤层）
- `biogeographic_provinces.md` — Wallace/Udvardy/WWF 分区标准 + `partition_biogeographic_provinces` 算法（P1a 生物地理分区）

## 规划中的文档

- `whittaker_biomes.md` — Whittaker 温度-降水生物群系图（与 Köppen 的映射是
  天然接口：`koppen_classification.md` 的 (T, P) 输入即 Whittaker 坐标轴）
- `intertidal_ecology.md` — 潮间带生态位（gaia-m ~25 km 进退带：固着滤食者、
  快速穴居者、两栖迁徙类；呼吸潮节律写入基因的世界构建案例）
- `refugia_broad_spectrum.md` — 避难所（refugia）与广谱革命：气候振荡期的
  物种/文化蓄水池机制（视频赏析中乐意 Ajax 世界的"蓄水池"文明形态同源）
- `domestication_geography.md` — 动植物驯化的地理条件（Diamond *Guns, Germs, and Steel* 框架）
- `evolution_trees.md` — 物种形成与人属演化树的表达方法（多 *Homo* 种并存、
  分子钟断代；远期，无引擎计划）

## 与其他学科的关联

- 气候 → 生态：`../climatology/koppen_classification.md`、`ocean_provinces.md`
  （海洋版 Köppen = 海洋生态分区）
- 地质 → 生态：土壤层（母岩 × 气候 → 土纲，见 `soil_orders.md`）、岛屿生物地理学（前导点褶皱山系的种-面积关系）

## 写作准则

遵循 `../CLAUDE.md` 知识积累准则：无来源不写入；不确定即标注待查证。
