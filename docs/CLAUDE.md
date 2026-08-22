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

存放面向开发者的架构与设计文档。包括：

- 项目架构（`architecture.md`）：目录结构、模块职责、核心设计概念
- 项目愿景（`vision.md`）、开发路线图（`roadmap.md`）、竞品分析（`competitor-analysis.md`）、文明层设计（`civilization-layer.md`）
- 子系统设计文档与技术参考：世界生成管线总览（`world-generation-pipeline.md`）、地质层（`geological-pipeline.md`）、地图系统（`map-system.md`）、气候层（`climate-pipeline.md`）及其验证（`climate-validation.md`）、Gaea 精细化（`gaea-refinement.md`）
- 早期架构决策记录（`design/archive/map_system_design.md`，已归档）

详见 `design/CLAUDE.md`。
