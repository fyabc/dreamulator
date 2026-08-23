---
description: 审计文档↔代码一致性（file:line 引用、反引号符号、参数字段是否仍存在），产出失效清单并记入 docs/design/audit/。当需要检查某文档/某层是否忠实反映当前实现时使用（如 /audit-doc geological-pipeline）。
---

# audit-doc — 文档↔代码一致性审计

> 与 `/grill-world`（审设定自洽）不同：本 skill 审「文档是否忠实反映代码」——引用是否失效、
> 字段是否改名/删除、参数值是否漂移。设计依据 `docs/design/audit-plan.md` 第一波
> 「文档↔代码数值一致性扫描」。

## 角色

你是一个**文档审计员**：逐条核对文档里的代码引用（`file:line`、反引号符号、参数表字段）
是否仍指向当前代码。每条失效必须附 `文件:行号` 证据，给不出出处的分歧标记 **OPEN** 升级用户。

## 范围：只审「已实现」文档

- **审** `docs/design/pipelines/`（已实现管线技术参考）——引用必须对齐当前代码
- **跳过** `docs/design/proposals/`（设计提案/方法论，未来字段/设计词汇是合法的前向引用）
- **跳过** `docs/design/archive/`、`docs/design/audit/`（历史快照，本就该过期）

## 工具（防幻觉，先跑工具再人工核对）

- `scripts/check_doc_refs.py` —— 自动扫 file:line 引用 + 反引号 snake_case 符号，报出
  `FILE_NOT_FOUND` / `LINE_OUT_OF_RANGE` / `NOT_IN_CODE`。先跑它拿候选清单。
- `grep -rn "<符号>" src/` —— 逐个核对符号是否真的存在、当前叫什么
- 参数表字段 → 对照 `map/pipeline_types.py`（`TerrainPipelineConfig`）等配置类的 `model_fields`

## 工作流

① 跑 `check_doc_refs.py` 拿候选清单 → ② 逐个分类（改名 / 已移除 / 前向引用 / 误报）
→ ③ 查当前代码确认每个改名的正确新名 → ④ 写审计发现 `docs/design/audit/waveN-<slug>.md`
（映射表 + `文件:行号` 证据）→ ⑤ 修文档 → ⑥ 重跑工具确认归零（允许残留「计划中」前向引用）

## 判定分类

| 类别 | 判据 | 处置 |
|---|---|---|
| 改名 | 旧名不在代码、新名能对应上 | 文档换新名 |
| 已移除 | 功能整个没了 | 删段落/行 |
| 前向引用 | 文档标注「计划中/留第二批」 | 保留，注明计划中 |
| 误报 | 概念术语/设计词汇（非代码符号） | 不加 skip-list，靠范围限定排除 |

## 入库

- 审计发现 → `docs/design/audit/waveN-<slug>.md`（映射表 + 证据 + 处置）
- 修复 → 改文档 + 重跑 `check_doc_refs.py` 确认
- 反复出现的「这类漂移」→ 沉淀为新的检查维度（改进环，同 `/grill-world`）

## 首例参照

`docs/design/audit/wave1-geological-pipeline-drift.md`：`geological-pipeline.md` 20 个过时字段
（`speed_range`→`plate_speed_range_cm_yr`、`ridge_depth_m`→`ocean_ridge_depth_m` 等），
经 `check_doc_refs.py` 发现、逐字段对照 `pipeline_types.py` 确认后修复。
