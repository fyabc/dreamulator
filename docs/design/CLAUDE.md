# 架构设计文档

本目录存放面向开发者的架构与设计文档。操作类指南见 [`../usage/`](../usage/)。

## 文档列表

- `architecture.md` — 项目架构：目录结构、模块职责、核心设计概念（层级架构、分支系统、input/derived 分离、可复现性）
- `vision.md` — 项目长期愿景与设计哲学（Fantasy Harness、粗粒化、硬度光谱）
- `roadmap.md` — 开发路线图（Phase 状态、优先级、技术债务）
- `competitor-analysis.md` — 竞品分析（护城河定位与参考链接，2026-08 从 roadmap 拆出）
- `civilization-layer.md` — 文明层半格式化管理设计（Phase 3C 详细提案，2026-08 从 roadmap 拆出）
- `terrain-pipeline.md` — 行星地形生成管线技术参考（12 阶段算法、数学公式、Cortial 2019 论文解读）
- `map-system.md` — 地图系统架构（栅格 + Voronoi 混合、多投影 GPU 渲染、API 端点）
- `climate-engine.md` — 气候引擎实现架构（模块职责、数据流、输出格式、Phase 3A 改进路线图）
- `climate-validation.md` — 气候引擎验证指南（ETOPO1 / Beck 2018 / ERA5 数据下载与验证脚本；§7 多线证据验证策略与反过拟合分层计划）
- `map_system_design.md` — 早期架构决策记录（ADR-001–004，已归档，不再维护）

## 写作原则

- 本目录文档回答"为什么这样设计 / 如何实现"；`../usage/` 回答"如何使用"
- 引入新设计模式时同步更新 `../worldbuilding/design_patterns.md`；引入新学科知识时同步 `../knowledge/<discipline>/`
- 路线图或架构变更时更新 `roadmap.md` 与 `architecture.md`
