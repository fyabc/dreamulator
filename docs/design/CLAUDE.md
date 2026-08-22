# 架构设计文档

本目录存放面向开发者的架构与设计文档。操作类指南见 [`../usage/`](../usage/)。

## 文档列表

- `architecture.md` — 项目架构：目录结构、模块职责、核心设计概念（层级架构、分支系统、input/derived 分离、可复现性）
- `vision.md` — 项目长期愿景与设计哲学（Fantasy Harness、粗粒化、硬度光谱）
- `harness.md` — 守护轴总纲：校验/审计/设定维护（与生成轴正交；守护引擎 + 守护世界两对象；三级过期检测；决策记录台账）
- `roadmap.md` — 开发路线图（Phase 状态、优先级、技术债务）
- `layer-control-model.md` — 层级控制模型：四层架构（约束/引擎/校验/覆写）+ 七层逐层设计
- `ai-cli-commands.md` — AI CLI 命令组设计（ai narrate/imagine/assist/tavern 等；含 LLM Agent 八角色 + 地图可视化）
- `moltke-engine.md` — Moltke Engine 独立实体引擎设计概要（ECS + 差分数据流 + 增量分支计算）
- `competitor-analysis.md` — 竞品分析（护城河定位与参考链接，2026-08 从 roadmap 拆出）
- `civilization-layer.md` — 文明层半格式化管理设计（Phase 3C 详细提案，2026-08 从 roadmap 拆出）
- `world-generation-pipeline.md` — 世界生成管线总览（阶段 1–12 目录 + 层级映射 + Gaea 指针）
- `geological-pipeline.md` — 地质层生成管线技术参考（CVT 网格、板块构造、地形合成、水文、侵蚀）
- `climate-pipeline.md` — 气候层 pipeline（温度/降水/Köppen 实现架构与参数；路线图已收敛至 `roadmap.md` §4）
- `climate-validation.md` — 气候验证设计（数据源清单、指标、§7 多线证据策略；操作步骤见 `../usage/validation-workflow.md`）
- `ecology-layer.md` — 生态层设计（Whittaker 群系 / NPP / 可驯化标签）
- `gaea-refinement.md` — Gaea 局部精细化（全局管线之后的区域后处理：投影、Gaea 处理、回导）

## 写作原则

- 本目录文档回答"为什么这样设计 / 如何实现"；`../usage/` 回答"如何使用"
- 引入新设计模式时同步更新 `../worldbuilding/design_patterns.md`；引入新学科知识时同步 `../knowledge/<discipline>/`
- 路线图或架构变更时更新 `roadmap.md` 与 `architecture.md`
