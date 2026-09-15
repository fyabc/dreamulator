# 全库体检与瘦身审计（wave4，2026-09-15）

> 范围：全库体检——docs/ 组织与年久失修、pipelines/ 内容级忠实性、过时代码与死代码、
> private/ 清理盘点。方法：`scripts/dev/check_doc_refs.py`（符号级，pipelines 0 失效）
> + 三个并行只读子审计 + 人工 spot check。**本文件是诊断快照**；处置分批进行，
> 修复状态在各条末尾标注。完整背景与 private/ 盘点见 `private/plans/repo-audit-2026-09-15.md`
> （不入库）。本审计沿用「证据锚定」原则：每条发现附 文件:行号。
> 规模：docs/ 共 96 个 md、21,296 行（knowledge 42/5,977、worldbuilding 9/1,698、
> usage 9/2,485、design 35/11,084）。

## 一、pipelines/ 内容级忠实性（本审计的主战场）

符号级（`check_doc_refs.py` 的 file:line + 反引号符号）0 失效；以下为内容级漂移。

### geological-pipeline.md — 明显失修【已修复 2026-09-15】

| 发现 | 证据 |
|------|------|
| §11「数据模型变更」整节是 2026-07-21 设计快照冒充 as-built：`cvt_models.py`（CVTNode/CVTMeshData 等）不存在，实际模型在 `models.py`（VoronoiCell :121、CVTMesh :457） | `ls src/dreamulator/map/` 无 cvt_models.py |
| §11 声称 VoronoiCell/VoronoiNetwork「废弃」——VoronoiCell 是现行核心模型，VoronoiNetwork 仍在（`models.py:381`）；附录 B 同两行错误 | `models.py:121,381` |
| §11.3 模块名全错：cvt_generator.py（实 cvt_mesh.py）、euler_kinematics.py、boundary_classifier.py（实 boundary_detector.py）、terrain_synth.py（实 terrain_synthesizer.py）、climate_engine.py/hydrology_engine.py（实 map/climate_simulator.py、map/hydrology.py）；`scripts/migrate_voronoi_to_cvt.py` 不存在 | 对照 `src/dreamulator/map/` |
| §11 MapProjection 声称有 HAMMER/LAMBERT_AZ——实际枚举仅 EQUIRECTANGULAR；MapLayerType 声称有 FLOW_ACCUMULATION/WIND/KOPPEN——实际无 | `models.py:46-49,561-575` |
| §13 限制 6「板块固定，时间演化在 §17 中规划」与本文 §14（时间演化）及 `tectonic_simulator.py`（50 步演化：`_subduction_uplift:163`、`_collision_orogeny:227`、`_rift_plates:1053`）矛盾；「§17」引用本身不存在（全文仅 14 节）；§4:620-621、§5:663 也引用幽灵 §17 | `geological-pipeline.md:1814-1815` vs `tectonic_simulator.py` |
| §13 限制 7「无热点：不生成火山岛链」与 §6.1 热点链步骤、`terrain_synthesizer.py:826`、nacrea `hotspot_count: 9` 矛盾 | `geological-pipeline.md:1816-1818` |
| §13 未来工作 8「天体物理集成」已实现（`resolve_and_apply_physical_parameters`） | `geological-pipeline.md:1837-1838` |
| §6.1「hotspot_count 默认 9」(:701) vs 代码默认 3（9 是 nacrea 覆写值，文档把世界特调当成默认值） | `pipeline_types.py:305` |
| §10.2 宣称支持 Lambert/Hammer (:1413-1436) vs 前端实际 Mollweide/Robinson（`helpContent.ts` PROJECTION_HELP）+ 后端枚举仅 EQUIRECTANGULAR | 双边证据 |
| §10.1 伪代码 `scipy griddata(method="cubic")` vs 实际 cKDTree 最近邻 cell 映射 | `export.py:24-55` |
| 头部「状态: 设计草案 · 2026-07-21」(:3) 与 pipelines/「已实现技术参考」定位矛盾 | :3 |

### map-system.md — 明显失修【已修复 2026-09-15】

| 发现 | 证据 |
|------|------|
| 架构前提是前 CVT 语境：「栅格高度图作为核心可编辑数据 + Voronoi ~10 万」(:25-26,36-43)——现行 CVT 一等公民、栅格派生、标准 200k（geological-pipeline.md:8-10） | 双边证据 |
| 「栅格编辑直观（画笔工具）」(:37)、「在地图编辑器中点击导入高度图」(:296)、「多频率高斯噪声生成基础海陆分布」(:300)——编辑器工作流已随 ADR-001 废弃（`map_design_guide.md:4`），现行 geography.yaml 锚定 + CVT 管线；相关 API 端点（POST /elevation、/import-elevation、/generate）仍在 `api_routes/maps.py:216-347`，非全盘失实 | 双边证据 |
| 「半分辨率 cell 贴图（~4 px/cell）」(:62) → 已全分辨率烘焙（~8 px/cell） | `layerBakes.ts:18-21` |
| features 端点标「（预留）」(:192) → 已实现（`api_routes/maps.py:131` + features.json）；API 表缺 `GET /climate-monthly`（`api_routes/maps.py:182`） | 双边证据 |
| 「PNG 高度图使用 git-lfs 管理」(:169) → 2026-08-23 后构建产物已 gitignore，不入 LFS | `.gitignore` + CHANGELOG |
| 「UI 组织四个面板组」(:282) → 现行五组（terrain/climate/ecology/civilization/dev）；「着色模式（地形/海拔/海陆/坡度）」(:304)——坡度图层不存在 | `helpContent.ts:53-59, LAYER_HELP` |
| :313 与 :131 分支地图路径自相矛盾（:313 是旧路径） | 文内矛盾 |
| 「计划中 Phase 3A 气候引擎 / 3B 侵蚀河流」(:334-339)——3A 已完成，3B 河流已落地（features.json） | 双边证据 |

### world-generation-pipeline.md — 轻微漂移【已修复 2026-09-15】

- 阶段编号自相矛盾：阶段表生态=9/导出=10/Gaea=11（:20-22）vs 层级映射生态=10/Gaea=12（:33-34）vs 数据流图 10/11/12（:64-70）；:3「阶段 1–12」vs :24「阶段 1–11」。
- 数据流图把水文（阶段 8）画在气候（阶段 7）之后（:61），与 DAG（geological 整体先于 climate）不符。

### climate-pipeline.md — 轻微漂移【已修复 2026-09-15】

核心机制（水汽收支、季风链、跨赤道西风带、_baroclinic_band σ 钳、E≈0.10、k_d、_EPS_U）逐项验证与代码一致。漂移：
- `ebm_diffusion_land_wm2k` 写 0.2（:103,386）vs 代码 0.28（`pipeline_types.py:474`；D_land 标定未同步文档）；:386「≈0.6×」应为 0.8×。
- **κ 叙事反转**：:154-155、:390-393 说 κ 是「代码内常量 3.75e5 m²/s，从 1e6 下调」——实际 κ 已是 config 字段 `moisture_diffusivity_m2s = 1e6`（`pipeline_types.py:526`），方向是标定到 1e6，文档把反向改动记成现状。
- 「nacrea 走 legacy 路径」(:83-85,379) vs `nacrea/terrain_config.yaml:161` 已 `ebm_1d: true`。
- 执行流程漏 Stage 3.5（aridity-gated subsidence warming，`climate_simulator.py:902`）。

### climate-validation.md — 轻微漂移【已修复 2026-09-15】

- §6 已知限制 4 条被实现推翻：Beck 逐 cell 验证（:150）、逐月验证（:151，`diagnose_monthly_validation.py`）、SODA 洋流（:152）、「32K cell ≈ 200 km」→ 现行 200k ≈ 51 km（:153）。
- :125 调优表引用 `_MOISTURE_DIFFUSIVITY_M2S` 代码内常量——同 κ staleness。
- :194「8 tests: 5 pass + 3 xfail」→ 实际 4 xfail。

### earth-real-data.md — 轻微漂移【已修复 2026-09-15】

- **:85 与代码直接矛盾**：「SST 异常 / 洋流是引擎模拟专属，保持 None」——earth 已导入 SODA v3.15.2 观测洋流（`src/dreamulator/import_earth_climate.py` docstring）；:22 输出表缺洋流字段。
- 实现已从 `scripts/earth/import_earth_climate.py` 迁到 `src/dreamulator/import_earth_climate.py`（scripts 侧 355 字节薄壳）未记录。
- **索引遗漏**：design/CLAUDE.md 与 docs/CLAUDE.md 均未列本文档。

## 二、docs/ 组织与年久失修

### 索引双向一致性

- knowledge 9 个学科、worldbuilding（含 drafts/）、usage 文件清单、design/proposals 16 个：全部双向一致。
- **F1** `docs/design/CLAUDE.md:22-28` 与 `docs/CLAUDE.md:48` 漏列 `pipelines/earth-real-data.md`。
- **F2** `docs/CLAUDE.md:49` proposals 只列 10/16（漏 monthly-climate-display、geology-layer-improvement、climate-layer-improvement、climate-gcm-plan、climate-steady-coupling、unified-climate-taxonomy）；usage 节只列 4/8（有兜底指针，轻微）。

### 内容级失修

- **F3** `usage/skills.md`（08-25）：`.claude/commands/` 实际 5 技能，文档列 3（漏 /audit-doc、/diagnose-climate）；:19 引用旧路径 `../design/harness.md`。
- **F6** `usage/performance-optimizations.md`（08-25）：P1 scipy 稀疏 BFS 未勾选但 `tectonic_simulator.py:790` 已实现；累计表 317.0s vs roadmap v0.36.0 基线 ~391s（版本口径未注明）；`noise_kernels.py` Numba 优化组 + numba 依赖漏记。
- **F7** `design/audit-plan.md`（08-23）：第一波 6/7 交付物已有 wave1-*.md 报告 + `_is_dirty()` 已实现（`pipeline.py:295`），表格未回填；第二波未启动合理（M4 判据未达）；第三波已标 ✅。
- 轻微：`layer-control-model.md` 无落地状态标注；`geological-pipeline.md` 头部「设计草案」。

### 组织合理性

- **F8（最大一类）17+ 处旧路径断链**（08-23 design/ 重组建立 pipelines/、proposals/ 子目录后，散落引用未同步）：`roadmap.md:587-597`（且同文 :44 新路径 vs :589-592 旧路径混用）、`usage/CLAUDE.md:21-24`、`skills.md:19`、`cli.md:213`、`map-workflow.md:5,7,514,738`、`map_design_guide.md:7,57`、`design_patterns.md:174,256,404`、`knowledge/geology/`（cvt_mesh.md:4、cortial_2019_notes.md:11,14,285、hydrology.md:3、terrain_synthesis.md:4、plate_tectonics.md:4）、`climatology/ocean_currents.md:93`、`sociology/`（CLAUDE.md:5、myth-phylogenetics.md:141,145）、`linguistics/`（language-design-guide.md:13、xenophonetics.md:4-5）、`agent-engineering/`（CLAUDE.md:4,28,30、self-maintenance-patterns.md:3）、`ecology/biogeographic_provinces.md:46,61`。根因：重组只改索引没改散落引用；`check_doc_refs.py` 默认只扫 pipelines，覆盖不到出链。
- **F9** `usage/CLAUDE.md:18-24`「相关设计文档」列表与 design/CLAUDE.md 重复维护且 4 条已过期 → 建议收敛为单指针。
- **F10** 命名风格混用（snake_case vs kebab-case），knowledge/CLAUDE.md:23 自规 snake_case 但 alternative-solvents.md、myth-phylogenetics.md 违反——低优先。
- **F11** 未发现放错位置的文档；无重复主题文档。

### proposals 老提案

vision / harness / moltke-engine / myth-strata / language-phylogeny / ai-cli-commands /
layer-control-model 全部被 roadmap 吸收或自带状态标注，**无一需归档**。harness.md
维护最好（P0–P2 ✅ v0.31.0 自带状态表 :576-579）。

## 三、过时代码与死代码

### 确认死代码（零引用，已验证）【已删除 2026-09-15】

| # | 对象 | 证据 |
|---|------|------|
| D1 | `frontend/src/stores/worldStore.ts` | zustand store 全前端仅自引用；Sidebar 的 currentWorld 从 URL match 派生（`Sidebar.tsx:27`） |
| D2 | `frontend/src/viewers/map/utils/projections.ts`（复数） | 零 import；活模块是单数 `projection.ts`（6 处 import）——改名遗留旧副本 |
| D3 | `frontend/src/pages/WorldInfo.tsx` | `App.tsx:36` 已把路由重定向到 /worlds；共享件已抽到 LayerDag/StarfieldBackground |
| D4 | `pyproject.toml:22` 运行时依赖 `jsonschema>=4.23` | 全库零 `import jsonschema` |
| D5 | `VoronoiCell.moisture` 字段（`models.py:335`，注释自标 legacy） | 全库零消费方 |
| D6 | `tectonic_simulator.py` 的 `_classify_step_boundaries`（68 行）/ `_spawn_oceanic_crust`（99 行）/ `_consume_small_plates`（106 行） | 全库零调用点（pipelines 重写 fork 顺带发现，2026-09-16 删除）——是全威尔逊循环的**写好未接线**实现；§14 未实现设计余量仍有完整设计描述，重启时对照当时代码重推导 |

### stale 标记/注释待清【已修复 2026-09-15】

- S1 `src/dreamulator/import_earth_climate.py:264-270` 注释引用已消失的「FIXME at climate_simulator.py:517」+ 描述 Stage A 前的镜像基机制（改注释时需顺带复核符号锚定——Stommel 链仍吃 wind_mirror，`climate_simulator.py:656-661`）。
- S2 `models.py:198`「temperature_C — TODO」过期（climate_simulator 早已填充）。
- S3 `models.py:640`「flow_accumulation — TODO」过期（river_generator 已实现）。
- S4 `scripts/README.md:3`「43 个脚本」实际 48；climate 组「25 个」实际 28。

### stale 脚本（方法论已被 B0b「逐月契约」取代）【已删除 2026-09-16：改写价值评估后全部删除】

- O1 `scripts/climate/diagnose_pressure_anomaly.py`——确认 stale（年平地转风方法），替代 = `diagnose_monsoon_dp_shape.py`。
- O2 `scripts/climate/diagnose_subtropical_high.py`、O3 `scripts/climate/diagnose_winter_pressure.py`——同族前提（annual-mean contrast dropped），方法与结论需重估；`diagnose_winter_monsoon.py` 与 O3 配套复核。
- O4 `private/tmp/probe_*.py` 7 个一次性探针（成果已落地 scripts/climate/）。

### schemas/ 与杂项

- `schemas/` 9 个 .schema.json 当前未漂移（SCHEMA_MODELS 覆盖的 models 最后提交同为 08-23）但**无同步机制**（CI 无新鲜度检查）；`map/models.py` 不在覆盖范围；库内无消费方（定位 = LLM/外部作者参考）。待裁决：CI 新鲜度检查 or 移除。
- `perf-dashboard` 分支（benchmarks.yml 的 dashboard 数据分支）——**裁决保留**（2026-09-16）。
- 健康面：后端 100 个 py 模块零孤儿；前端零 FIXME/TODO；66 个后端端点全部有消费（无 API 错位）；可选依赖组全部在用；`scripts/climate/validate_climate.py` 是**有意薄壳委托**（实现在 `src/dreamulator/validate_climate.py`，非双份）；`stationary_wave.py` 按既定「默认关但保留」遗产处理。
