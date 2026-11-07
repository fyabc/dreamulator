# 第七波审计：设计提案的公开整洁度（2026-11-06）

> 对象：`docs/design/proposals/` 的 34 份提案（共 10,597 行）。目的：让公开的提案只承载设计决策与理由，过程记录回到
> git、`CHANGELOG.md` 与私有实验目录。整理本身作为待办执行，本文是清单与判据，执行后逐项勾掉。
>
> 第 2 节保留审查时的发现与行号，处理后的当前状态见第 4 节。

## 1 判据

根 `CLAUDE.md`「任务文档分工」已经规定了提案的内容：物理第一性推理、文献、当前方案、已否证方向各一行；不堆积实验
记录，不写「已修正、旧值」叙事；实现后技术参考移到 `pipelines/`，提案只留「为什么」与已否证方向。本次按这些规定加
三条可检查的判据：

1. **只写结论**：方案、依据、验收指标和已否证方向入库；逐轮试验数字、调参过程、带日期的诊断小节不入库。
2. **不写私有信息**：不出现私有目录路径（`private/…`、本地数据缓存目录）与机器分工（服务器、Windows、本机的硬件）。
3. **有状态头**：文首写明状态（草案、已接受、部分实现、已实现、已否证终止）与立项日期，历史只留在「更新历史」块。

## 2 发现

### 2.1 已实现部分仍以实施日志留在提案里（移到 pipelines，提案压缩）

| 提案 | 位置与规模 | 处置 |
|---|---|---|
| `canvas-conditioning-structure.md` | §4.2 第 5 步「连续重建」815 行，内容是已进入生产的连续地形来源的实施细节与逐项验收 | 技术参考并入 `pipelines/canvas-chain.md`；提案保留问题、依据、步骤状态表与已否证方向，目标 300 行以内 |
| `canvas-glacial-landforms.md` | §6.1.1–6.1.3 冰缘锥度的第一轮、第二轮与冰缘定义（约 140 行），已实现 | 实现并入 `pipelines/canvas-chain.md`；第一轮的错误定义留一行在已否证方向 |
| `climate-layer-improvement.md` | 带日期的「审计实锤」「镜像约定 bug」「SST 对流门 ✅」等小节，95 处日期 | 已实现项移到 `pipelines/climate-pipeline.md`，修复史删去（在 git 中），否证项并入已否证列表 |
| `island-catalog.md`、`sky-ephemeris.md`、`blender-render-pipeline.md` | 状态为部分已实现 | 已实现部分的接口与参数核对是否已在 `pipelines/` 或 `usage/`，缺的补齐后提案只留未实现部分 |

### 2.2 整份是日志体（收口后改写为结论）

| 提案 | 情况 | 处置 |
|---|---|---|
| `climate-engine-round.md` | §5 全部是带日期的轮次小节（§5.1–5.8），无状态头；这一轮已于 2026-11-03 收口 | 改写为收口总结：目标、结论、各路线的判决一行、留下的技术债指针；评分卡基线留在 `pipelines/climate-validation.md` |
| `surface-wind-from-pressure.md` | §3.1、§4.2–§4.4.3 是逐日检验，含三次否证 | 保留物理依据与分阶段方案；检验结论每条一行，细节移出 |
| `moist-static-energy-convergence.md` | 阶段 0 否证，提案终止 | 压缩为一页终止说明（主张、否证依据一段、指针），或并入 `climate-layer-improvement.md` 的已否证方向后删除 |
| `column-radiation-field.md`、`seasonal-heat-capacity-closure.md` | 各有带日期的诊断小节 | 同上，结论留一行 |

### 2.3 私有信息出现在公开文本

| 提案 | 行 | 内容 |
|---|---|---|
| `climate-engine-round.md` | 80、201、533、565、591、628 | 私有实验目录路径、本机外部项目副本、「服务器与命令行」 |
| `moist-static-energy-convergence.md` | 200、232 | 私有实验目录与本地观测缓存路径 |
| `surface-wind-from-pressure.md` | 280、344、377 | 私有实验目录路径 |
| `column-radiation-field.md` | 129、178 | 私有实验目录路径 |
| `canvas-glacial-landforms.md` | 325、355、393 | 机器分工（Windows 渲染与接入）与私有实验目录路径 |
| `climate-gcm-plan.md` | 15、63、89、103–119 | 本机硬件、服务器配额与 Windows 依赖细节 |
| `gaea-refinement.md` | 219 | 本机 GPU |
| `blender-render-pipeline.md`、`ecology-layer.md` | 111、348–351 | 开发机硬件 |

处置：私有路径改为「复现脚本另存」或删除；硬件与机器分工改为与机器无关的资源描述（例如「多卡 GPU 环境」），
确需保留的性能数字只写配置，不写是谁的机器。

### 2.4 归属不对

- Nacrea 辐照重标定属于单一世界的定稿裁决，已回写正典。记录位于
  [设计笔记 0022](../../../data/worlds/nacrea/design-notes/0022-insolation-recalibration.md)，提案目录不再保留副本。

### 2.5 缺状态头

`ai-cli-commands.md`、`civilization-layer.md`、`climate-engine-round.md`、`layer-control-model.md`、`moltke-engine.md`、
`nonspecialist-entry.md`、`seasonal-heat-capacity-closure.md`、`surface-wind-from-pressure.md`：按判据 3 补状态与立项日期。

## 3 执行顺序

1. 私有信息（2.3）：改动小、风险最高，先做。
2. 归属（2.4）与状态头（2.5）。
3. 日志体改写（2.2），从已收口的 `climate-engine-round.md` 开始。
4. 已实现部分迁移（2.1），从 `canvas-conditioning-structure.md` §4.2 开始；每迁一处跑 `check_doc_refs.py`，
   并检查跨文档锚点链接。

每一步单独提交，提交信息写明移到了哪里，过程细节由 git 保留。

## 4 当前执行状态

- [x] 清理第 2.3 节列出的 9 份提案中的私有路径、机器分工与资源库存，并保留性能测量的配置和技术平台要求。
- [x] 全目录复查后，补清 `canvas-conditioning-structure.md` 和 `climate-layer-improvement.md` 中两处“本机”措辞。
- [x] 为第 2.5 节的 8 份提案补齐状态头，状态以正文和已实现代码为依据。日期优先使用原文立项日期；
  `layer-control-model.md` 的原记录只到月份，因此保留 2026-08，未编造具体日期。
- [x] 将 Nacrea 辐照重标定迁入[设计笔记 0022](../../../data/worlds/nacrea/design-notes/0022-insolation-recalibration.md)，更新索引与引用；现行定标引用 0012，历史候选与实施预案保存在文首历史块。
- [x] 将 `climate-engine-round.md` 改写为收口结论；已实现机制并入气候管线，首份评分卡放入验证指南的文首历史块，并同步小节引用。
- [x] 将 `surface-wind-from-pressure.md` 改写为现行方案与路线判决，绝对气压的实现归入气候管线；明确背景风替换的前置检验未通过，并同步索引与小节引用。
- [x] 将 `moist-static-energy-convergence.md` 压缩为阶段 0 终止说明，保留局地闭合的否证依据、再分析数据限制和 Lindzen–Nigam 补充候选的边界，并同步索引与引用。
- [x] 将 `column-radiation-field.md` 整理为物理依据、输入限制、候选与验收，统一云诊断方案与否证结论，明确 GCM 云顶复用仍未裁决，并同步索引与小节回链。
- [x] 将 `seasonal-heat-capacity-closure.md` 整理为结构问题、候选与验收边界；现行热容量参数、周期缩放与谐波响应由气候管线维护，海冰试验保留否证结论，并同步索引和验收回链。
- [x] 将 `canvas-conditioning-structure.md` 第 4.2 节压缩为来源状态表、归因结论、候选与否证结论；画布链补齐生产采用表、差额细化的覆盖与收敛门、坡面输运接口和 TD 编码限制，并改正整高程来源入口的求积说明。提案全文由 1148 行减到约 530 行，第 4.1 节的线性地形雨原型（`gcm/orographic.py`）与份额投影（`gcm/precipitation_shares.py`）尚无管线参考，留待气候层迁移一并处理。
- [ ] 将 `canvas-glacial-landforms.md` 的已实现冰缘定义与锥度参考归入 `canvas-chain.md`，保留错误定义的否证结论。
- [ ] 将 `climate-layer-improvement.md` 的已实现参考归入气候管线，并将日志体改写为当前结论与否证列表。
- [ ] 核对 `island-catalog.md` 的已实现接口与参数，补齐管线参考后压缩提案。
- [x] 新建[天球星历管线参考](../pipelines/sky-ephemeris.md)，收录模块分工、自转轴阶梯、升落与快路径、命令行与端点缓存及背景天球派生；提案由 119 行压到 41 行，保留设计选择、未实现的 M4 与开放问题，并改正命令行示例中的世界参数写法。
- [x] 新建[区域数据包管线参考](../pipelines/region-pack.md)，按现行代码补齐包内文件与 `meta.json` 契约（含全球高程范围、年径流与湖冰月数，两种掩膜为 16 位），收录窗口、取样、对齐口径与 Blender 静帧；提案由 138 行压到 46 行，保留定位、设计选择与路线，并把用法、知识库、脚本注释和 Gaea 提案的契约引用改指管线参考。

本批文档链接与管线实现引用检查通过。

## 5 下一阶段的迁移计划

下一项是[冰川地貌提案](../proposals/canvas-glacial-landforms.md)第 6.1.1 至 6.1.3 节的冰缘锥度与冰缘定义。
画布链第 2.5.5 至 2.5.10 节已有覆冰更新、海洋边界与冰面延拓的参考，迁移前先核对其覆盖范围。

1. 保存原稿，逐项核对提案、管线与当前代码，区分现装 v7 采用的定义与已否证的第一轮定义。
2. 将管线缺少的冰缘判据、锥度带宽、冰量变化口径与封闭无冰区处理补齐，避免重复已有参考。
3. 压缩提案，保留物理依据、未实现的冰川侵蚀与地球验证方案和否证结论；逐轮实验数字另存。
4. 同步索引与回链，检查 Markdown 文件与锚点链接并运行 `check_doc_refs.py`，作为独立文档批次提交。

本项只迁移文档，不改变冰面产物、冰量或生产参数，也不重新生成画布。
