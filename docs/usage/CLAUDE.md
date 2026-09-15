# 项目用法指南

本目录存放 dreamulator 工具本身的使用说明（面向最终用户的操作指南）。
架构设计、算法技术参考等面向开发者的文档位于 [`../design/`](../design/)
（2026-07-29 文档整理时迁入）。

## 文档列表

- `cli.md` — CLI 命令参考（init、list、info、validate、schema、delete、branch、conlang、terrain、build、climate、narrate、guard、export、explore-seeds、serve）
- `skills.md` — Claude Code 技能速查（/grill-world 拷问、/read-map 读图、/narrate 叙述、/audit-doc 文档审计、/diagnose-climate 气候诊断）
- `map-workflow.md` — 地图工作流指南（CVT 网格地形生成 → 查看器检查 → 可选 Gaea 精细化的完整流程）
- `climate-validation-workflow.md` — 气候验证工作流（真实高程导入、参考数据下载、运行验证、保存报告）
- `profiling.md` — 性能分析工作流（build_profile.json、py-spy 火焰图、Scalene、基准测试）
- `performance-optimizations.md` — 性能优化记录（基线数据、改动内容、效果对比、待优化清单）
- `civmap-guide.md` — 文明地图使用指南（真实地球底图、架空国家涂色、时间快照）
- `frontend-3d-viewer.md` — 3D 恒星系可视化器（操作指南 + 架构设计说明）

## 相关设计文档

架构设计、管线技术参考与提案见 [`../design/CLAUDE.md`](../design/CLAUDE.md)。
