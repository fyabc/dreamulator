# 项目文档

本目录包含 dreamulator 项目的所有文档，分为四个子目录：

```
docs/
├── knowledge/       # 学科知识库（天体物理、地质、气候等真实科学知识）
├── worldbuilding/   # 架空世界创建思路与方法论
├── usage/           # 项目用法指南（CLI、API、前端操作说明）
└── design/          # 架构设计文档（面向开发者，含设计决策记录）
```

## knowledge/ — 学科知识库

存放各学科的真实科学参考文档，为世界推演提供科学依据。

LLM 编写世界 input 文件时应参考这些文档确保物理合理性；开发者实现模拟引擎时参考其中的公式和参数。

详见 `knowledge/CLAUDE.md`。

## worldbuilding/ — 世界创建指南

存放架空世界设定的方法论、设计思路和最佳实践。包括：

- 如何从恒星参数出发逐步构建一个自洽的世界
- 各层面设定之间的因果关系和约束
- 常见架空世界设计模式和反模式
- 创意决策的指导原则

详见 `worldbuilding/CLAUDE.md`。

## usage/ — 项目用法指南

存放 dreamulator 工具本身的使用说明（面向用户的操作指南）。包括：

- CLI 命令参考（`cli.md`）
- 地图工作流指南（`map-workflow.md`）
- 文明地图使用指南（`civmap-guide.md`）
- 3D 恒星系可视化器操作（`frontend-3d-viewer.md`）

详见 `usage/CLAUDE.md`。

## design/ — 架构设计文档

存放面向开发者的架构与设计文档。分三类：

- **根目录**：项目架构（`architecture.md`）、路线图（`roadmap.md`）、竞品分析（`competitor-analysis.md`）、审计计划（`audit-plan.md`）
- **`pipelines/`（已实现管线技术参考）**：世界生成管线总览（`world-generation-pipeline.md`）、地质层（`geological-pipeline.md`）、地图系统（`map-system.md`）、气候层（`climate-pipeline.md`）及其验证（`climate-validation.md`）、Gaea 精细化（`gaea-refinement.md`）
- **`proposals/`（设计提案 + 方法论）**：愿景（`vision.md`）、守护轴（`harness.md`）、层级控制模型（`layer-control-model.md`）、生态层（`ecology-layer.md`）、文明层（`civilization-layer.md`）、语言谱系（`language-phylogeny.md`）、神话层积（`myth-strata.md`）、AI CLI（`ai-cli-commands.md`）、Moltke 引擎（`moltke-engine.md`）
- 早期架构决策记录（`design/archive/`，已归档）

详见 `design/CLAUDE.md`。
