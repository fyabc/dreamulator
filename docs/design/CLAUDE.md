# 架构设计文档

本目录存放面向开发者的架构与设计文档。操作类指南见 [`../usage/`](../usage/)。

## 目录结构

- **根目录** — 总览、路线图、竞品分析、审计计划
- [`pipelines/`](pipelines/) — **已实现管线技术参考**（`scripts/dev/check_doc_refs.py` 的审计对象）
- [`proposals/`](proposals/) — **设计提案 + 方法论**（未来子系统、未实现）
- [`audit/`](audit/) — 审计结果。最新的 [wave7](audit/wave7-proposal-hygiene.md) 检查设计提案的公开整洁度；wave6 核查 GCM 与气候引擎，wave5 核查对外设定文案。

## 文档列表

### 根目录

- `architecture.md` — 项目架构：目录结构、模块职责、核心设计概念（层级架构、分支系统、input/derived 分离、可复现性）
- `frontend-3d-viewer.md` — 3D 恒星系可视化器架构（真实比例设计、层级轨道解算、标签去重叠）
- `roadmap.md` — 开发路线图（Phase 状态、优先级、技术债务）
- `competitor-analysis.md` — 竞品分析（护城河定位与参考链接）
- `audit-plan.md` — 三波审计计划（按变化速率分波，各有启动判据与审计产物）
- `web-gcm-and-frontend.md` — 浏览器内 GCM 与前端调研（web-exoplasim：把 ExoPlaSim 重写为 TypeScript 加 WGSL 而非仅编译 Fortran；GPU 路径在集成显卡上每步 10.3 ms，同为 20 分钟步长下比本机 16 核（20.1 ms）快约 2 倍，按各自默认步长的物理时间吞吐量几乎相同；§2.1 为本机强扩展曲线（16 rank 为工作点、单核与并行效率不逊于原生基准、认证跑可缩到 20 个模式年）；§4 记作者实跑与正典的逐项对比：全局量对得上，陆地偏干已判为动态植被所致，洋面云量差一成与植被和轨道均无关而待追，另发现它的 Köppen 按模式月长累加降水，短年世界上干旱区虚高到陆地的三分之二；可借鉴的是工程纪律三条、迭代过程可见、参数面板即文档、以及共享内存 Worker 推翻了「浏览器只能串行」的前提；GPL-2.0 不抄码）
- `profiling.md` — 性能剖析工作流（build_profile.json、py-spy 火焰图、CI 基准测试、前端 React Profiler、跨版本对比）
- `performance-optimizations.md` — 性能优化记录（基线数据、改动内容、效果对比、待优化清单）

### pipelines/ — 已实现管线技术参考

- `world-generation-pipeline.md` — 世界生成管线总览（阶段 1–12 目录 + 层级映射 + Gaea 指针）
- `geological-pipeline.md` — 地质层生成管线技术参考（CVT 网格、板块构造、地形合成、封闭盆地湖泊、极地冰盖、导出）
- `map-system.md` — 地图子系统（球面 CVT 网格、板块构造、地形、气候、导出）
- `climate-pipeline.md` — 气候层实现架构与参数，包含 GCM 球面统计、有限面积长期降水、高频状态与 TD 气候消费。
- `ecology-pipeline.md` — 生态层 pipeline（海陆判据、Whittaker 群系含湖泊哨兵、Miami NPP、可驯化标签、土纲、生物地理分区）
- `civilization-pipeline.md` — 文明层 pipeline（宜居/农业分类与评分、湖滨淡水修正、摇篮候选发现）
- `climate-validation.md` — 气候验证设计（数据源清单、指标、多线证据策略）
- `earth-real-data.md` — 真实地球数据导入（ETOPO1/PB2002/GSHHG/NCEP-GPCP-Beck-SODA 的来源、流程与字段）
- `canvas-chain.md` — 全球画布链，包含连续地质来源、接受统计准备、气候反馈、两档高清图及外存水文接口。
- `orbital-weather-globe.md` — 太空俯瞰星球媒体链：L2 云纹理、L3 气旋模板、L5 单次散射大气、L1 接口与后续
- `gcm-weather-pack.md` — GCM 气象图层包（L1）：高频瞬时快照、ISCCP 云量分层与云顶、测高公式高度、TempestExtremes 式气旋检测与追踪、包结构与读取

### proposals/ — 设计提案 + 方法论

- `vision.md` — 项目长期愿景与设计哲学（Fantasy Harness、粗粒化、硬度光谱）
- `harness.md` — 守护轴总纲：校验/审计/设定维护（与生成轴正交；守护引擎 + 守护世界两对象）
- `layer-control-model.md` — 层级控制模型：四层架构（约束/引擎/校验/覆写）+ 七层逐层设计
- `ecology-layer.md` — 生态层设计（Whittaker 群系 / NPP / 可驯化标签）
- `civilization-layer.md` — 文明层半格式化管理设计（Phase 3C 详细提案）
- `language-phylogeny.md` — 语言谱系推演设计
- `myth-strata.md` — 神话层积与母题变异设计
- `ai-cli-commands.md` — AI CLI 命令组设计（ai narrate/imagine/assist 等）
- `moltke-engine.md` — Moltke Engine 独立实体引擎设计概要（ECS + 差分数据流）
- `gaea-refinement.md` — Gaea 局部精细化（全局管线之后的区域后处理；提案，未实现）
- `blender-render-pipeline.md` — Blender 高清渲染链（区域数据包 `dreamulator export region` + bpy 脚本重建场景；MVP 已实现，路线节登记扩展）
- `sky-ephemeris.md` — 天球星历查询（任意观测点的天球位置/视直径/相位/升落；catalog 驱动的两体星历 + CLI/API，渲染与 FUI 共用 JSON，前端天球视图后续；提案，2026-11-01 立项）
- `monthly-climate-display.md` — 月度温度/降水展示（Phase 4 前端延伸；SunControl 周年滑杆驱动月度图层；提案，未实现）
- `nonspecialist-entry.md` — 非专业用户入口（前端 UI 提案与「非专业用户导入」合并）：现状核查发现导入链的高程语义在归一化与米之间未定、`sample_heightmap` 的米制参数是死参数，所以阶段 A 先定契约，再做导入面板即文档（两个数字 + 可选掩膜 + 写盘前预览陆地占比 + 长宽比与位深警告）、计算过程可见（已有阶段划分与逐月场当时间轴，不做流式渲染）与入口放出；2026-11-04 立项
- `browser-playground.md` — 浏览器气候实验台（Gate D 温度首图原型：拖放高度图 → 年均/逐月温度；规则 180×90 网格、只算温度；2026-10-23 原型落地，完整气候待引擎加速）
- `geology-layer-improvement.md` — 地质层改进方案（§1–§8 已实现，技术参考见 geological-pipeline.md；未实现 proposal：裂谷海宽度分段、板块从 geography 派生）
- `evolution-mode.md` — 演化模式提案（新建世界：geography.yaml 作为演化目标，逆向规划超大陆后正向运动学模拟出现状，时间轴为副产品；未实现，2026-10 立案）
- `geological-timeline.md` — 地质时间轴提案（大陆块为主体，整段历史作为带约束的求解问题：陆壳守恒为硬约束，速度、重组稀疏、净旋转为先验，合并与切开由焊接关系表示；板块与边界由大陆块运动推出；时刻分支接气候与生态；2026-10 立案，10-18 重构）
- `orogen-topography.md` — 造山带地形与地形极值的格子平均语义（技术债 43，并入 37）：✅ 已实现（2026-10-21），只保留设计理由、未完成与移交项、已否证方向与作者裁决；物理与标定在 `knowledge/geology/orogen_topography.md`，实现在 `pipelines/geological-pipeline.md`
- `island-catalog.md` — 亚格子岛屿目录（技术债 44）：热点链、热管火山省（按潮汐加热采样）、岛弧、海山与环礁按成因生成目录，格子只记汇总字段；提案，2026-10 立案
- `history-contract.md` — 历史契约（roadmap P2）：地形合成从板块历史读取的量（洋底年龄、陆缘类型与年龄、汇聚边界段的碰撞年龄与积分汇聚量、缝合带）的定义、来源（作者 `plate_history.yaml`、地质时间轴、演化模式、缺省值）与一致性校验；造山带部分先于技术债 43 落地；2026-10 立案
- `canvas-conditioning-structure.md` — 画布条件场的总体需求与设计依据，包含连续山带、海岸地貌、气候尺度传递及候选方案的验收范围。
- `terrain-morphology-gap.md` — 山系形态与地球的差距（2026-11-06 调研立项）：海岸线与总起伏已与地球相当，缺的是窄长的山带（nacrea 最大长宽比约 3.5，地球安第斯 15）、高原内部结构（一半高原格钉在平均高程上限上）、老造山带的宽度规则与分段，以及 25–150 km 的顺走向山脊；汇聚边界本身的弯曲与地球相当。按尺度分工：约 150 km 以上的平均场归地质引擎，25–150 km 的组织与纹理归画布，排入下一次全层重建
- `canvas-glacial-landforms.md` — 画布的覆冰与冰川地貌：现今冰面、气候物质平衡、热流驱动的约化碳响应与全球冰量历史、基底热状态，以及后续基岩侵蚀与地球验证方案。
- `inland-water-refine.md` — 内陆水体 refine 提案（湖命运 P−E 判决四类结局、溢流河网接通、rim/spill 字段缺口；未实现，2026-10 立案）
- `surface-wind-from-pressure.md` — 由气压场推地面风：绝对气压场已实现，技术参考由气候管线维护；背景风替换未通过前置检验，保留物理依据、分阶段验收和已否证方向，柱长波与云顶结构仍是上游缺口。
- `column-radiation-field.md` — 柱辐射场的物理依据、输入限制与验收：热带柱长波需要云顶或分层云量，总云量与降水代理均未通过检验；快速模式复用 GCM 云顶结构仍是未决候选，提案未实现。2026-11-03 立项。
- `moist-static-energy-convergence.md` — 湿静力能辐合闭合的终止说明：局地闭合在阶段 0 未通过再分析规定输入检验，未进入实现；保留主张、否证依据与数据限制，湿槽维持三轮停止点，Lindzen–Nigam 模型仅作补充候选。2026-11-02 立项并终止。
- `seasonal-heat-capacity-closure.md` — 季节热容量闭合在地球标定域之外的适用性（单层 C 把大气柱并入地表，短年世界上成为主导项；地球振幅与相位双重标定的证据、判决规则与三条候选路线）
- `climate-engine-round.md` — 气候迭代的收口结论，记录已完成工作、路线判决和专项提案指针；技术参考由气候管线维护，首份评分卡保存在气候验证指南的文首历史块。
- `climate-layer-improvement.md` — 气候层改进方案（按要素+DAG 组织：§1 温度、§2 气压、§3 风场、§4 洋流、§5 降水、§6 分类；含已否证方向清单，不堆积实验记录）
- `climate-gcm-plan.md` — 气候层 GCM 方案（远期备选，全动力学替代诊断式 DAG，关注涌现 vs 高效的平衡 + GPU 加速杠杆）
- `climate-steady-coupling.md` — 气候层稳态耦合中间态（远期提案：DAG 某一步 T↔P 耦合解定点，介于单向 DAG 与瞬态 GCM 之间，先关 T↔P 干旱度反馈）
- ~~`unified-climate-taxonomy.md`~~ — **已迁出（2026-09-24 UCC 文档收拢）**：跨世界统一气候分类 UCC 现居 `docs/ucc/`（规格书 `specification.md` + 设计锚点 `design-anchors.md` + 例证 `examples/` + 评审研究 `research/`）

## 写作原则

- **设计决策原则（硬门槛）**：每个方案/引擎决策都要有「物理第一性」（从物理推导）、「地球真实参考」
  （观测数据）或「业界成熟方案」（论文/源码）三者至少其一的支撑；同物理（所有世界同一套引擎，
  只差输入参数）；第一性 > 启发式（不接受「为让结果像一点」的裸调）。与根 `../../CLAUDE.md` 的
  「引擎设计纪律」「竞品参照」同源。
- 本目录文档回答"为什么这样设计 / 如何实现"；`../usage/` 回答"如何使用"
- **已实现子系统**的文档放 `pipelines/`，**未实现 / 方法论**放 `proposals/`——这也是
  `scripts/dev/check_doc_refs.py` 只审计 `pipelines/` 的分类依据
- 引入新设计模式时同步更新 `../worldbuilding/design_patterns.md`；引入新学科知识时同步 `../knowledge/<discipline>/`
- 路线图或架构变更时更新 `roadmap.md` 与 `architecture.md`
