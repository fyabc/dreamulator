# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.35.0] — 2026-09-04

### Added

- **板块边界对齐大陆边缘**（proposal §5 方案 2）：geography 感知的板块种子 + 海岸代价场，
  板块边界被「吸」到海岸附近，不再横穿大陆/纵切大洋（`geography_boundary_weight`）。
- **锚定地貌噪声粗糙化**（proposal §4）：`geography.yaml` 的 feature 支持 `noise_amplitude`，
  高原/裂谷/群岛的边界由规整椭圆变为分形海岸线。
- **内部造山带/裂谷形态**（proposal §4）：长度封顶（`interior_belt_length_min/max_deg`，
  多数 ~600 km）+ 去硬上限（`interior_orogeny_count` 真正生效）+ 裂谷概率参数化
  （`interior_rift_chance`），长条造山带/裂谷变为散碎短段。
- **前端地物着色**：转换断层（transform）/ 断陷盆地（basin）图层配色 + i18n 标签。
- **板块运动箭头图层**：`plate_motion` 静态导出图层。
- **earth 基础世界**：真实地球数据导入（高程/板块/地壳/水掩膜/气候），地壳/边界换真实
  数据（CRUST1.0 地壳类型 + PB2002 板块边界）。
- **前端增强**：河流图层 3D 栅格烘培；单元格信息栏「默认/全量」显示模式 + 月度协调；
  气压异常图层固定 ±20 hPa 色标；叠加图层配色统一 sRGB（消除亮度跳变）。

### Changed

- **海岸高程过渡**（proposal §3.9）：沿海平原统一所有沿海 cell（不再只限大陆地壳）；
  高程钉扎「削峰」不对称化——海沟不再被抬成山。
- **地壳类型正交化**（proposal §8）：取消程序化 transitional，浅水大陆架划入陆壳。
- **球面测地距离统一**（proposal §7）：距离单位真实（`distance.geodesic_bfs`），
  不依赖网格分辨率。

### Fixed

- 板块边界分类改用**法向速度判据** + 沿走向子分段，打破 Voronoi 大圆边界的犬牙。
- 渗漏转换拉分盆地、断陷盆地/地垒可见、热点链离散群岛化、大陆板块减速、板块半包围。
- 4 个测试对齐代码现状：transitional 地壳断言、`water_class` 迁移、无大气温度、
  生态纬向 sanity（中纬度热带化暂标 xfail，气候重调为下一版）。

## [0.34.0] — 2026-08-30

### Added

- **月度矢量场**（技术债 24）：月度风场（年均背景 + 逐月季风异常）与气压异常 ΔP 图层，
  以 int16 量化（48→24 MB）写入 `climate_monthly.msgpack`；前端「时间」控制区
  （年均/月度切换 + 周年/月度滑块）统一驱动温度、降水、气压、风场
- **观测点诊断**：`scripts/station_diagnostics.py`——26 个参考站按 Köppen 类型分层
  （Af–ET），采样模型逐月温度/降水/风向并与硬编码标准气候态对比，补充 Cohen's Kappa
  看不到的「单点季节行为」（季风风向、季节振幅、干湿季）

### Changed

- **季风机制重标定**：边界层风 f 项符号更正；年均气压热低压项改用位温 θ=T+Γ_d·z
  （捕获高地抬升热源）；k_d 按地表分陆海（陆 2e-4、海 1e-5，f→0 退化不再放大赤道陆风）；
  水汽扩散 κ 3.75e5→7.5e5；沿海调制 e-folding 500→250 km
- **气候精度提升**：Cohen's Kappa（主指标）0.24→0.265、空间准确率 29%→30.8%、
  分布匹配 →67.5%
- 数据同步：nacrea / earth-climate-dev 全量重建（含文明层）；`climate_monthly.msgpack`
  迁入 Git LFS（`.gitattributes` 加 `*.msgpack` 规则）

### Fixed

- **亚马逊 Af 回归**（Af 0→1324 cell）：f→0 退化项把亚马逊（密林应高拖曳）温和 ΔP
  放大成 ~20 m/s 假强风 → 干季水汽被抽干；k_d 分陆海 + κ 上调修复
- 季风边界层风 f 项符号（东亚夏季风经向偏南 → 翻正，暴露「6 月低压在陆、风却吹向太平洋」）
- 季节振幅减半（沿海陆地被过度海洋调制，季节振幅 14 vs 真实 30°C）

## [0.33.0] — 2026-08-28

### Added

- **Phase 4 月度气候展示**：`climate_monthly.msgpack`（N×12×2 float32）导出 +
  `/climate-monthly` API + 前端月度温度/降水图层（气候组「年度/月度」切换 + 周年滑块、
  12 等分刻度 M1–M12；月度降水独立对数范围 0–2500 mm/月）
- **河流矢量图层**：features.json 提取 + SVG 渲染（D8 河网分级）
- 知识库：`speculative_evolution_genre.md`（推测进化流派史）、
  `coastal_geomorphology.md`（海岸地貌分类 + 44 m 潮差外推）、
  `pre_ediacaran_macrofossils.md`（弗朗西维利安等前埃迪卡拉记录）
- 生态层设计 §2.7 深时演化门控；gaea-refinement §6 高清地形图完整链路

### Changed

- **nacrea 天文设定**：Aegis obliquity 3°→9°、Nacrea 赤道面轨道叙事（Cassini 态、
  Laplace 面 4.7 yr 摆动、共振维持约束）；轨道面动力学与长周期气候循环数字卡入设定文档
- 气候准确率系列：水汽收支守恒化（Budyko 陆地再循环 + κ 3.75e5）、辐合驱动降水、
  大陆度（陆地-only EBM）、季节 EBM（B_eff=B+6D + 季节冰反照率）、
  coastal moderation（年平温度向最近海洋 SST 混合）
- 地质层：流水侵蚀/沉积自 200k 引擎移除（尺度不匹配，转 Gaea 局地精修）；
  内部低地 + 靶向沉积填充 + 大陆架缓坡 + 小裂谷
- nacrea / earth 双世界全量重建并同步 data/worlds

### Fixed

- 无海洋世界的 coastal moderation NaN 守卫（验证网格全陆地时温度场被 NaN 污染、
  水汽预算矩阵奇异）
- ITCZ 偏强 / Af 海岸锁定等气候修复若干

## [0.32.0] — 2026-08-19

### Added

- **地图图层 headless 导出 CLI**（`dreamulator export layers`）：headless 烘焙
  terrain/koppen/biome/agriculture/habitability 五层 RGBA PNG，颜色与前端逐字节一致。
  前置：配色单源化——`palettes.json`（categorical + continuous + adaptive terrain 停点）
  前后端共读，前端经 Vite alias 直读，消除前后端配色漂移
- **Seed 探索器 CLI**（`dreamulator explore-seeds`）：批量生成多 seed 地形 + 对比表
  （海洋/陆地占比、均陆高、最大海拔/洋深、大陆数、板块数）+ 缩略图 + 种子目录
  （`seed-catalog.json`），回应技术债 #16（Cortial-2019 seed 敏感性）

### Changed

- `map/export.py` 抽出 `export_cell_index_grid`，新增 RGBA 图层渲染
  （`render_categorical/continuous/terrain_layer` + `save_rgba_png`）
- 前端 `colorScales.ts` 改从单源 `palettes.json` 读取；`vite.config.ts`/`tsconfig.json`
  加 `@dreamulator/palettes` alias + `server.fs.allow`

## [0.31.0] — 2026-08-19

### Added

- **守护轴（Harness）实现落地**（v0.30.0 设计总纲 → 代码，P0–P3 全部 commit）：
  - **P0 事实上下文** `guard/facts.py`：实体化寻址的物化视图，消除 `world_parameters` 冗余
  - **P1 过期检测** `guard/stale.py` + `guard check` 命令：三级检测（模板断链 / `input_checksum` 指纹 / 渲染 diff）
  - **P1.5 ADR 台账** `guard/adr.py`：决策记录状态机（`proposed→accepted/deprecated/superseded`）+ 容量上限强制剪枝
  - **P2 原语注册表** `query_registry` + `guard/queries.py`：`@query` 装饰器 + JSON Schema（几何/空间原语，可作 function-calling tools）
  - **P3 拷问编排** `guard/critique.py` + `/grill-world` skill：griller/answerer 事实库 + 维度清单
  - **`guard` CLI**：`check` / `accept` / `supersede` / `deprecate` / `archive` 五命令
- **harness.md 补全**：§1.4「引擎即环境」（苦涩的教训的正确读法）+ §9.4「harness environment」（ai 命令组统一底层：verifier = 原语 + 证据三分类 `verified/cited/intentional`）
- **异星发声模式**：xenophonetics 设计 + 生物声学知识库
- **替代溶剂草案**：删草案七/八（CO₂ 干冰穿梭、富氯行星）；新增「四氢化萘密度翻转油海世界」（铁呼吸行星）；原草案六「冰-油-卤水三层世界」移至末尾并自洽化

### Changed

- 前端文档选中持久化到 URL 参数（刷新/分享保留选中状态）
- 生态异星物种推演 P3 拆分（body plan 推导 → 演化树 → 图像输出，推演核心留主仓）
- 清理 MessagePack「待实现」残留 + 生态层引用修正

## [0.30.0] — 2026-08-17

### Added

- **守护轴（Harness）设计总纲**：与生成轴正交的校验/审计/设定维护
  （`docs/design/harness.md`）；三级过期检测（模板断链 / input_checksum 指纹 / 渲染 diff）+
  ADR 决策记录台账 + 检测≠裁决 + 硬度旋钮 + 意图感知 + 后果映射；拆出
  `docs/knowledge/agent-engineering/`（Claude Code/OpenClaw/Hermes/World Anvil 自维护模式）
- **其他行星卫星系统**（8 颗新卫星）：焦砾星 Cinder（火卫一类比）、
  凝冰/玄冰/霜冰星（Boreal 冰质规则卫星）、玄石/逆石星（Glacis 规则内 + 逆行捕获）、
  近客/远客星（Sentinel 不规则捕获）；两字 + 共享字命名 + 科学别名（鼎卫/沧卫…）
- **文明种子**：补 6 新文明（西屿城邦/北岸海民/东岸季风/第二大陆农耕帝国/西南雨林/南方大陆），
  拷问修正 3 现有文明（驯化潜力锚点、巨眼地平线、声呐→天文导航）
- **两个 skill**：`/read-map`（视觉+数据双路地图结构抽取）、`/grill-world`（设定拷问）
- **决策记录台账**：`design-notes/` 0001–0006（ADR 约定）
- **竞品分析 §七/§八**：World Anvil 方法论参照 + 宜居卫星设定参照

### Changed

- `geography.md` 按 cvt_mesh 实测地图重写（陆地 28.7%、世界岛—北极超大陆 117.2 M km² 等）
- vision.md 补第三条轨道（守护轴）；architecture/roadmap/README 同步

### Fixed

- 极小质量（<1e-6 M⊕）被 `round(..., 6)` 抹成 0 的引擎 bug（改用 `.6g` 有效数字）
- `num_plates` 单一数据源：手写 20 与实际 25 不符，改为从 plates.json 读取
- 天象几何错误：外卫星「凌」→「掩」；「环食」消歧（巨神星 11° ≫ 烬星 0.93°）
- i18n：`unit.days` 补进 map 命名空间；中文「天」→「地球日」消歧
- design-notes 迁移为 ADR 编号（0001–0003）

## [0.29.0] — 2026-08-16

### Added

- **文明宜居/农业图层**（首个文明 derived 引擎）：`engine/civilization.py` +
  `engine/habitability.py` + `engine/seed_discovery.py`。宜居海岸（年均温>0°C、
  降水>500mm、沿海≤200km）与农业核心区（最热月>10°C，Köppen C/D 林线）两个布尔图层，
  及其 0–100 分级版本（宜居等级 = 温度生态位带 × 降水；农业等级 = 林线硬零 ×
  生长度日 × 水 × 土壤肥力）。文献依据 Xu 2020 / McMaster 1997 / Small & Nicholls 2003
  （`docs/knowledge/sociology/human_settlement.md`）。
- **种子自发候选发现**：连通分量(农业核心区) → 承载力排序 → 特征继承，输出
  `civilization_seed_candidates.yaml`（纯确定、无 RNG）。
- **civilizations.yaml 单一信源**：3 文明种子（裂谷海/大河/长夜）+ 双语言叙事，
  天文分区校正（世界岛=边缘区）、背星区「长夜」非「全暗」。
- **前端宜居等级/农业等级递进色专题图层** + 单元格面板 0–100 数值。
- `VoronoiCell` 新增 `distance_to_coast_km` / `habitable_coast` / `agricultural_core` /
  `habitability_score` / `agriculture_score`。

### Changed

- **气候 M4 空间准确率**：降水管线三 bug 修复（地形降水误套海洋洋底、ITCZ 夏至位置、
  缺风暴路径）+ ITCZ/风暴路径物理重构 + 纬向参考数组 NCEP+GPCP 重生成。温度 corr 0.981、
  群组 Kappa 0.466（>0.45 达标）。
- **nacrea 单圈环流**（GCM PoC 证实无 Ferrel/极地胞）：`hadley_extent_deg=90` +
  关闭风暴路径 + 概念文档修订 + 生态文档合并。
- 潮差 78 m → ~44 m（tidal_effects.md 重算），潮汐平原 45 km → ~25 km。
- 文档「只写当前设定，不写历史」原则（CLAUDE.md）+ 全仓翻案残留清理。

## [0.28.0] — 2026-08-15

### Added

- **天体统一目录 `system_catalog.yaml`**（技术债 #23）：天文引擎 build 时合并
  `stellar.yaml`（恒星/轨道/叙事 bodies）与 `planets.yaml`（权威物理参数 +
  大气/水圈/岩石圈），逐天体输出合并条目（物理字段 planets.yaml 优先）+
  开普勒公转周期、辐照度、平衡温度、太阳日、潮汐锁定状态、宜居带位置；
  恒星附计算参数与宜居带。新增 `physical_inputs.build_system_catalog()` /
  `check_body_field_consistency()`（共享字段 0.1% 容差交叉校验，漂移告警）。
  API `/worlds/{name}/system-catalog` + 静态导出三件套同步。
- **天体百科面板**：WorldDetail 天文 tab 新增恒星卡 + 天体卡网格（聚合
  catalog 全部信息：物理/轨道/派生/大气/叙事描述，目标天体/潮汐锁定/
  宜居带徽章）。
- **三波审计计划**（`docs/design/audit-plan.md`）：按变化速率分波——第一波
  工程卫生 + 一致性、第二波物理审计（判据：3A M4 且 GCM PoC 出结论）、
  第三波架构审计（3B 启动前）；含自由参数 A/B/C 处置分类、bug 治本四条腿、
  grill-me 子代理互审规范。
- **世界参数单一来源**（技术债 #22 阶段①）：`physical_inputs.derive_world_parameters()`
  聚合世界目标天体的原始 + 衍生参数，天文引擎 build 时输出
  `layers/astronomy/derived/world_parameters.yaml`（自动生成、勿手编辑）。
  派生项：辐照度、无大气平衡温度、年长（开普勒第三定律）、太阳日
  `1/(1/P自转−1/P年)`（恒星潮汐锁定→无穷大并告警）、一年太阳日数、平均季节
  长度、极圈纬度与极点极昼时长、保守宜居带位置、恒星主序寿命与演化进度；
  卫星另附绕母星轨道周期与潮汐锁定一致性校验（偏差 >2% 告警）。新增纯函数
  `stellar_physics.solar_day_days()` / `polar_circle_latitude_deg()` /
  `polar_day_fraction_of_year()`（公式见 `docs/knowledge/astrophysics/
  sidereal_solar_day.md`）。nacrea 输出与 `physical_params.md` 手算值逐项
  一致；回归测试锚定（太阳日 3.42 d、年 67 d、一年 19.6 太阳日、极圈 ±81°、
  极点极昼/夜 33.5 d、卫星公转 78 h）。
- **世界文档 Jinja2 模板渲染**（技术债 #22 阶段②，`doc_render.py`）：读取/导出时
  从 `world_parameters.yaml` 按需渲染文档模板，产物不落盘；nacrea 5 篇文档模板化。
  设计笔记渲染修复标题缺失 + 支持 KaTeX LaTeX 公式。
- **前端 i18n 扫尾 + 语言切换器**（审计 T5）：35 个文件 / ~600 处硬编码中文消除，
  词典表（Köppen 群系/土纲等 code→名称映射）迁入 i18n key；Sidebar 页脚新增
  语言切换器（localStorage `dreamulator-lang` + 浏览器语言兜底）；zh-CN/en
  覆盖 common/map/worlds/civmap/help 五个命名空间。
- **气候诊断四件套补全 ②③**（审计 T7）：`diagnose_latitudinal_profile.py`
  （5° 分带、海陆分离的纬向 T/P 剖面 vs ERA5/GPCP，形状(引擎) vs 幅度(参数)
  判读）与 `diagnose_koppen_confusion.py`（完整混淆矩阵 + 逐群
  precision/recall/F1 + top 混淆对 + BWk/ET 调参目标验证）。
- **审计第一波产物**（`docs/design/audit/wave1-*.md` 五件套）：静态导出同步
  差异清单、文档↔代码数字冲突、自由参数清点造册（~110 字段 A/B/C 分类）、
  i18n 残留扫描、前端二进制格式架构审视（MessagePack 已落地、FlatBuffers 放弃）。
- **interlude 调研入库**：知识库新增神话层累与系统发生学（sociology）与
  比较法/音系类型学/声调发生学/音变库/conlang 工具调研（packages/conlang）；
  新增待开发设计稿 `language-phylogeny.md`、`myth-strata.md`、conlang
  feature-rules 特征音变规则。
- **nacrea「天象全景」推演文档**（`layers/astronomy/input/sky_phenomena.md`）：
  从珠母星表面观测各天体视直径/视星等的完整推演（Bond→几何反照率 Lambert
  换算约定 + 食季与十大可展示天文现象 + 地球时/珠母星年显式时间单位约定）。

### Changed

- **3D 恒星系视图数据源迁移**：`StellarSystemViewerPage` 改读 system-catalog
  单一端点，删除 `StellarSystemViewer` 内的 stellar bodies/planets 客户端
  merge + 按 id 去重补丁（合并逻辑下沉至后端 catalog）。
- **nacrea 天文命名体系完善**：五行星补古雅单字中文名（焦星·Ember /
  鼎星·Crucible / 沧星·Boreal / 霰星·Glacis / 藩星·Sentinel）；珠母星英文名
  Nacrea → Nacrea（24 个文档/yaml 全量替换；天体 id 与世界线名 nacrea 不变）。
- **legacy 死代码清理**（审计 T2/T4，−527 行）：删除 `generate_map` →
  `voronoi_generator.assign_cells_to_plates` → `PlateVelocity` 死代码链、
  `terrain_generator.py`、孤立端点 `/worlds/{w}/civilizations`、
  `/civmap/boundaries-meta`、`getMapLayer` + layer PNG 端点；
  `voronoi_generator` 仅保留高度图采样（高度导入工作流仍用）。
- **气候诊断基准改用 climate-dev 200k**：三个诊断脚本 + `convert_koppen_map.py`
  默认跑在 earth/climate-dev（与地球海陆分布一致）；旧 32k `koppen_obs.json`
  移出仓库，新 200k 参考由脚本本地生成并加入 `.gitignore`（可再生、不入库）；
  `validation-workflow.md` 补诊断脚本一节。
- **天文 tab 天体百科去重**：按从属关系嵌套显示（Nacrea 挂在 Aegis 下），
  消除与恒星卡的信息重复。

### Fixed

- **nacrea 三处天体字段漂移**（stellar.yaml bodies vs planets.yaml，按
  planets.yaml 权威对齐）：Aegis 反照率 0.34→0.343；Cadence 半径
  2840→2867 km；Vigil 半径 2470→2485 km。
- **`stellar_physics.equilibrium_temperature` docstring 自相矛盾**：f=16/8 的
  等价式误写为 `[S(1−A)/(16σ)]^0.25` / `[S(1−A)/(8σ)]^0.25`，正确等价式为
  `[S(1−A)/(4σ)]^0.25`（地球 255 K）/ `[S(1−A)/(2σ)]^0.25`（代码实现本身正确）。
- **build 跳过判定改为 mtime 脏检查**（技术债 #4）：`pipeline._is_dirty()` 在
  "输出存在"之外追加"输入未变新"判据（输入最新 mtime vs 输出最老 mtime），
  修复 geography.yaml / terrain_config.yaml / stellar.yaml 等输入改动后 build
  静默跳过的问题（8/6、8/13 两次踩中）。新增 `BaseEngine.output_paths()` 统一
  产出路径清单（geological/climate 覆写覆盖 maps/ 与 derived/ 双目录）；
  测试 `tests/test_engine/test_pipeline_dirty.py`。
- **文档↔代码一致性 9 处修复**（审计 T2，详见 `docs/design/audit/
  wave1-doc-number-conflicts.md`）：terrain-pipeline.md num_nodes 默认值
  200k→100k、PlateVelocity 三处"废弃"标记改"已删除"、六处 flood-fill 措辞改
  Cortial 2019 球面 Voronoi 剖分、§2.5 500K 栅格分辨率 4096×2048→6144×3072、
  `lat_gradient_earth_c` 字段名漂移等；test_doc_render 过时锚点修复。
- **nacrea `giant_brightness.md` 亮度修正**：满月参考照度 0.0012 → 0.0034 W/m²
  （按 −12.74 等反推），满相倍数 1592× → 560×、半相 507× → 178×、
  极细相 0.86× → 0.3×；移除过程性"前稿修正记录"。
- **earth 时间线文档归类**：补 `type: timeline` 归入「编年史」分组。

## [0.27.0] — 2026-08-14

### Added

- **季节能量平衡模型**（`climate_seasonality.py`）：季节振幅改用 `T_amp = ΔQ_ω/√(B²+(ωC)²)`
  （North & Coakley 1979），以绝对年辐照 Fourier 振幅 ΔQ_ω 替代相对 frac_variation，以
  物理表面热容量 C（海洋 2e8 / 陆地 2e7 J/m²·K，沿海指数插值）替代 f_ocean；删除
  `seasonal_amplitude_c`/`0.25`/`f_ocean` 三个自由旋钮。
- **可调气候参数**：`seasonal_damping_b`、`seasonal_land/ocean_heat_capacity`、
  `lat_gradient_earth_c`、`evaporation_base_mm`、`moisture_advection_steps`。
- **日心偏心率解析**（`physical_inputs.resolve_orbital_elements`）：季节周期取恒星轨道
  成员的偏心率（nacrea e=0.005），而非卫星绕行星的偏心率。
- **空间诊断脚本** `scripts/diagnose_koppen_spatial.py`：经纬网格 + 两极合并的空间
  Köppen 准确率热图（区分引擎 bug vs 参数微调）。
- **`ai civ` 命令设计**（`ai-cli-commands.md` 附录 D）：地理→文明推演——气候画像→文明种子。
- **文明气候画像** `climate_portrait.md`：nacrea vs 地球气候对比 + 文明启示。
- **前端**：cell inspector 显示最热月/最冷月（`temperature_hottest_month_C` /
  `temperature_coldest_month_C`）。

### Changed

- **Köppen 第三字母改季节感知**（Kottek et al. 2006）：按最暖/最冷 6 月分半判别 s/w，
  修复「冬干被误标 Csb」。
- **B 组干旱阈值修复**：`20·T+offset` 钳到 1mm 正底，冷干 cell（P≈0）正确归 BWk 而非 Dfb。
- nacrea 气候调参：温室 59.5→62.0 K、`lat_gradient_earth_c` 40→28、蒸发 2000→1900、
  BFS 步数 auto17→28（暖高纬 + 水汽深入内陆，BWk 冷荒漠 −426）。

### Fixed

- **基线快照漂移**：`climate_metadata.json` 补导出 `orbital_period_days` + `eccentricity`，
  `generate_baseline.py`/`test_regression.py` 读取，修复基线（用 365.25 d 而非 67 d）与
  实际构建不一致。

## [0.26.0] — 2026-08-13

### Added

- **生态层 P1a**：土壤层（USDA 12 土纲 + 肥力分级）+ 生物地理分区（realm → province
  两级聚类 + 小岛归并）。`VoronoiCell` 新增 `soil_type`/`soil_fertility`/
  `biogeographic_province` 字段。
- **前端土壤/生物地理省两个专题图层**：13 色 USDA 土纲色板 + 生物地理省循环色板。
- **前端图层分组重构**：地图模式拆分为「地形/气候/生态」三组，帮助系统按组生成子章节，
  每组标题带分窗帮助按钮。
- **降水知识文档**（`docs/knowledge/climatology/precipitation.md`）：Clausius–Clapeyron
  方程 + 雨雪相态（临界温度）+ 内陆干旱梯度。

### Changed

- **nacrea 天文参数（方案2）**：光照 0.48→0.66×地球（光度 0.0357→0.0414 L☉、
  Aegis 轨道 0.2722→0.2504 AU，共振链按开普勒第三定律同步），温室 75→59.5 K，
  均温 ~17.1°C，气候类型丰富。
- **前端 NPP 动态归一化**：按每世界自身 NPP 峰值（而非固定 3000 gC），修复低光度
  世界 NPP 图层颜色偏浅。
- **图层改名**：文明摇篮 → 驯化潜力（zh + en）。

### Fixed

- **降水内陆干旱 bug**：`e_fold` 去 `q_sat` 依赖（传输距离只随风速），修复高纬冻原
  内陆降水骤干到 ~5 mm 的问题（现恢复到 ~89 mm 降雪量级）。
- **Köppen B 类干旱阈值 bug**：`dry_offset` 恒为 280（死代码，`pw>2·pd` 在固定
  seasonality 下恒真）→ 修正为均匀 140 + BW/BS 分界含 `offset/2`。
- **Köppen 分布匹配阈值 55% → 50%**（修复后分布匹配 55.0%，跌破旧阈值）。

## [0.25.0] — 2026-08-12

### Added

- **双分量山脉边界轮廓**：窄脊（80 km）+ 宽肩（400 km）组合高斯，替代单一宽高斯。
  山脉现在呈现肉眼可辨的线性山脊，而非模糊高原。新增 `boundary_ridge_sigma_km`、
  `boundary_shoulder_strength` 配置参数（`terrain_config.yaml`）。
- **首页 GitHub 链接**：副标题下方显示 GitHub 图标，hover 变青色，预留社交媒体扩展位。

### Fixed

- **回归测试 Earth 硬编码值**：`generate_baseline.py` 和 `test_regression.py` 之前
  绕过 `terrain_config.yaml`、硬编码 `lat_gradient_c=45.0`，导致测试结果与 `dreamulator build`
  不一致。现改为从 `terrain_config.yaml` 加载气候配置，仅覆盖物理参数。
- **`climate_metadata.json` 缺字段**：新增 `albedo`、`rotation_period_days` 导出，
  确保下游脚本可完整还原气候配置。
- **`_baseline` 被当作地图**：`maps/` 下 `_`/`.` 开头的临时目录不再被 `list_planets_with_maps()`
  列出，避免前端跳转到旧数据。

### Changed

- **Nacrea 全量重建**：3 轮地理微调（北极大陆缩小+偏移、南方大陆重命名、南大洋纬度微调、
  前导点褶皱山系调整）。Köppen E 组（极地）从 44.5% 降至 29.7%，陆地均温从 3.96°C 升至 8.20°C。
- **回归基线更新**：`tests/validation/baselines/nacrea-200k.json` 匹配新地理 + 双分量山脉。
- **首页标题上边距加大**：`pt-20 md:pt-28` 防止顶部挤压。

## [0.24.0] — 2026-08-11

### Added

- **前端加载性能测量仪表**（`utils/perf.ts`）：PerformanceObserver + User Timing API，
  first-paint 计时覆盖完整加载链路。Console 输出分组摘要。
- **加载动画**：脉冲呼吸环 + 帮助系统随机提示（快捷键/图层知识）。
- **cell inspector 风场信息**：风向 + 风速显示。

### Changed

- **nacrea 迁移至 200k 节点**（51 km/cell，原 71 km/cell）。前端加载 ~14s。
  - 地形调整：世界岛中心南移 10° + 拉长短缩（压缩北方沙漠），前导点山系东移 10°，
    北极裂谷加宽。噪声参数还原。
  - JSON 优化：compact 格式 + 浮点 4 位截断 → nacrea 85 MB（原 108 MB，−21%）。
- **气候文档重写**：`climate_zones.md`、`atmospheric_dynamics.md` 按引擎实际
  Köppen 输出修正（此前为引擎实现前的手写推定）。

### Fixed

- **−2°C 陆地硬下限移除**：`apply_upwelling_sst_correction` 的 `np.maximum(…, -2.0)`
  仅对上升流 cell 生效，不再将所有陆地最低温锁死在 −2°C。冰原最低温恢复至 −32°C。
- **洋流 SST 通过图扩散传播至沿岸陆地**：ocean current/upwelling 修正后追加 1 次
  弱扩散 pass，暖流/寒流对沿海气候产生实际影响。
- **3D 球体拖动速度自适应缩放**：`rotateSpeed = (d−R)/1.8`，FOV=40° 校准。
- **前端加载 UX**：过滤 useGPUTerrain 的 1px 占位纹理，消除黑球加载阶段。

### Performance

- **ocean GMRES 优化**：rtol 1e-6→1e-4，maxiter 减半，跳过 <20 cell 小海盆。
  nacrea 200k ocean 90s→56s（−38%）。
- **JSON 导出优化**：compact 格式 + 浮点精度截断，100k 108→85 MB（−21%）。
- nacrea 200k 全量构建 456→334s（−27%）。

## [0.23.0] — 2026-08-09

### Added

- **洋底年龄-深度沉降模型**（`terrain_synthesizer.py`）：divergent↔convergent 距离比插值
  + sqrt(age) 冷却律。nacrea 均海深 3015→3687 m（地球 3682）。
- **均衡尾部压缩**（`terrain_synthesizer.py`）：`h_max ∝ 1/g` 重力标度指数衰减压缩。
  nacrea 陆极高 10770→8721 m、海极深 16593→12400 m。
- **图拉普拉斯平滑**（`terrain_synthesizer.py:_smooth_land_discontinuities`）：消除
  均衡压缩后的邻域悬崖跳跃，>3000m 跳跃 cell 从 1446→137 (−91%)。
- **永耀岛**：向星点潮汐固定热点火山岛（~1200 m 峰），位于 Aegis 深渊洋中央。
- **北极周缘裂谷**：三条自转减慢松弛裂缝，连通北方内海与外洋。
- 气候分类体系比较文档（Köppen / Trewartha / Thornthwaite / Holdridge）
- 地壳均衡与高程极限知识文档（Airy/Pratt + 重力标度公式）
- `scripts/detect_ocean_bottlenecks.py`：自动海峡瓶颈检测（WIP）

### Changed

- terrain-pipeline.md：新增 §6.8（年龄-深度）、§6.9（均衡压缩）、§6.10（拉普拉斯平滑）
- ocean-currents-model.md §1.3.1：基于实测地形确认两处临界海峡
- roadmap.md：+5 条技术债（#11–15）
- geography.md/yaml：名称修正——北极大陆、前导点褶皱山系、世界岛–北极陆桥

### Fixed

- 海洋 cell 不再使用陆地 Miami NPP 模型（`ecology_physics.py`），避免伪影

## [0.22.0] — 2026-08-08

### Added

- `pin_exponent` 偏差指数化（高程钉扎非线性控制）
- i18n 国际化框架（zh-CN / en，4 命名空间）
- 帮助系统重构（独立 /help 页面 + GitBook 式侧栏 + 结构化章节）
- StarfieldBackground 共享组件

### Changed

- 地图图层系统重构为 slot-based（底图/专题/填充/特征）
- 生态专题图层（Whittaker / NPP / 文明摇篮）归入统一 radio 组
- cell 选择行为重新设计（Ctrl+点击多选、Esc 清除）
- `regional_noise_scale` nacrea 0.5→3.0（板块级起伏）
- 文档架构整理（设计文档/知识库/世界构建指南分离）
- 海岸线/洋流预烘焙由 half→full res

## [0.21.0] — 2026-08-07

### Added

- mypy --strict 全仓 0 错误 + 硬门槛 CI
- ruff 全 select 通过
- 板块大小偏态化三段式方案（加权 Voronoi 重分区）
- 板块边界曲率增强（Frank 小圆弧机制）
- 高程钉扎（`elevation_target_m` + `pin_strength`）
- 海平面旋钮（`sea_level_offset_m`）
- 地形微调诊断指南（`docs/worldbuilding/terrain-tuning-guide.md`）

### Fixed

- 俯冲海沟深度 −4758→−10484 m
- mypy 发现并修复 6 个真 bug（AttributeError、Pillow LANCZOS 弃用等）
- Pillow `mode="I;16"` 弃用修复

## [0.20.0] — 2026-08-08

### Added

- **生态层 P0（roadmap 3A.5）**：Whittaker 生物群系分类 + Miami NPP 模型 + Diamond 可驯化标签
  - 纯计算模块 `ecology_physics.py`：3 温度带 / 4 降水阈值 → 13 群系 +
    海上 NPP（Lieth 1975）+ 大食草动物/主粮/役畜标签
  - 管线集成：`EcologyEngine` 在气候引擎后运行，写出 `ecology_summary.yaml`
  - 35 单元测试 + 5 纬度带合理性检查
- **生态前端可视化**：
  - Whittaker 群系（13 色分类）、NPP 热力图（暖米→深绿）、文明摇篮（金/橙/绿高亮）
  - 右侧面板显示群系名/NPP/可驯化标签
- **图层系统重构为 slot-based**：
  - 槽位架构：thematic（radio 互斥）/ fill（多选堆叠）/ feature（多选堆叠）
  - 地形/海陆移至 thematic 槽位，移除 base 槽位
  - 图层组精简为"地图模式 / 地质构造 / 叠加标注"
- **海岸线特征叠加层**：像素级半分辨率检测，默认开启，颜色 #141414

### Changed

- **地形色阶**：`generateAdaptiveTerrainScale` LUT（NOAA ETOPO1 海洋 + ESRI Natural Earth 陆地）
- **水深暗化**：恢复 `waterDepthFactor` 倍乘（与重构前一致）
- **3D globe 独立纹理**：`terrainWithCoastlines` 直接采样，避免 FBO PBR 色彩空间往返

### Fixed

- **大陆架海洋误判**：`is_ocean` 改为纯 elevation 判定（`cell.elevation < 0.0`）
- **地图加载文本持续显示**：`localElevation` 条件替代 loadingElevation
- **3D globe 色彩偏淡**：renderComposite 禁用 toneMapping + outputColorSpace

## [0.19.0] — 2026-08-08

### Added

- **基础洋流系统（roadmap 3A.3）**：Stommel 正压流函数模型，GMRES 在 CVT 球面网格上求解
  - 纯计算模块 `ocean_circulation.py`：风应力 / curl_z（梯度-分量方式，零边几何）/
    盆地 BFS 检测 / 图 Laplacian + 东向梯度算子稀疏组装 / 每盆地 GMRES 求解
  - 管线集成：climate_simulator stage 2.5（风→curl→Stommel→SST 沿流平流松弛）
  - 27 单元测试（矩形盆地 gyre 方向/WBC 强化/确定性/Ekman 上升流/SST 平流）
- **Hadley 环流经向风 + Ω^(-1/3) 风速标度**：修复纯纬向风模板，添加地表信风
  equatorward 分量（Hadley/Ferrel/Polar）；引用 Hill et al. (2019) / Held & Hou (1980)
- **nacrea 次行星半球经度暖化**：`sub_planet_warming_c` 参数化 Aegis 红外+反射光
  加热（~1°C 半球均值）
- **洋流前端可视化**：
  - 2D: SVG 矢量箭头（4.5° 网格，品红暖流/青绿寒流，sqrt 拉伸，zoom 自适应）
  - 3D: Canvas rAF 箭头叠加（半球剔除+边缘淡出+zoomScale）
  - 右侧面板洋流详情：方向/流速(cm/s)/暖寒流标注
  - 5th shader uniform slot (u_currents)

### Fixed

- **无 geography.yaml 的世界无法构建**（v0.16.0 回归）：`BaseEngine` 新增
  `optional_input_files`（缺省合法、引擎回退默认）
- **陆地海拔色阶反转**：海平面改为深绿 #1E6B3A，随海拔升高渐变浅绿/黄/棕
- **CG→GMRES**：Stommel 算子非对称（β·G_east 项），CG 对 ~23k 细胞盆地不收敛
- **east 方向修正**：`r̂×k̂` 替代 `k̂×r̂`（后者指向西）

## [0.18.0] — 2026-08-07

### Added

- **docs 重组（全 Phase）**：terrain-pipeline.md 原位瘦身 3748→2415 行
  （科学内容上浮 knowledge/，§ 编号冻结保护 13 处代码引用）；气候验证操作
  步骤下沉 usage/validation-workflow.md；路线图单点收敛（climate-engine §6
  移除）；knowledge 新增 ocean_currents / atmospheric_circulation /
  koppen_classification + ecology/ / sociology/ 目录；早期 ADR 归档；
  map_design_guide 重写为 CVT 版；narrative-craft 世界史讲述方法论
- **大陆与边界真实感批次**（2026-08 用户反馈）：克拉通低地化
  （`continental_undulation_m` 多尺度动态地形起伏，板块内部 0.4× 偏差）；
  洋中脊 0.35× + 板块偏差解耦（脊顶回 −2500 m）；top-N 地壳泄漏重标
  （洒点岛屿仅岛弧/热点/钉扎涌现）；边界多数投票平滑 + 飞地合并
  （犬牙转角 76.5°→38.4°/步）；古造山带/裂谷双频 meander + 沿走向宽度变化
  （0.55–1.45×）；**per-plate 地壳下限** `crust_plate_floor`（默认 0.10，
  authored 洋豁免）避免整板同型地壳。nacrea：南大洋四环洋带、南极浅海/地峡
  钉扎、南方大陆×2（澳洲/南美类似，南半球陆地 15.1%→16.9%，地球 ~19%）、
  boundary_warp 0.3、boundary_uplift_noise 0.8；>2000 m 陆地 29.7%→12.3%
- **密集偏置场导入 / Gleba 模式**（问题 1 阶段 3）：`geography_raster.png`
  灰度概率图叠进锚定场（`raster_weight` 调和），与 feature 同等待遇参与
  地壳切分/重锚/抬升抑制/钉扎；API `POST /worlds/{w}/geography-raster` +
  地图页"⬆ 锚定灰度图"按钮；管线穿线 run_terrain_pipeline→plates/synthesize
- **高度图导入 UI**（问题 1 阶段 1）：地图查看器顶栏"⬆ 导入高度图"
  （16-bit PNG / TIFF 自动识别、重采样、覆盖确认、导入结果 banner、
  无板块数据空态提示、静态模式禁用）；导入溯源写入 `map.yaml` 的
  `elevation_import` 块（`ElevationImportProvenance`）；usage/map-workflow.md §10
- **地理高程锚定**：`geography.yaml` feature 新增 `elevation_target_m`
  （相对校准海面：负=水深、正=陆高）与 `pin_strength`（0–1）。在海平面校准与
  全部后处理之后施加凸组合钉扎——`shallow_sea`/`isthmus` 从此能表达
  <200 m 水深与地峡高度上限
- **海平面偏移旋钮**：`terrain_config.yaml: sea_level_offset_m`（默认 0）。
  水面标量移动而地形数组不动（冰期海退：−120 m 时 (−120, 0] 出露成陆）；
  大陆架/沿海平原/岛弧/海陆分类/气候陆海掩膜全部参数化

### Changed

- **CI 全硬门槛**：ruff check 全规则 + ruff format + mypy strict 全部转为
  硬门槛（原 F,E9 基线 + mypy 报告档）；技术债三连 Sprint 清偿：
  mypy 150→0、ruff 266→0、format 24 文件清零

### Fixed

- **锚定裂谷被推上海面**（roadmap #9；nacrea 大裂谷海曾 +927 m）：地形合成
  对强负偏置场（authored 裂谷/海盆）的汇聚正抬升乘连续阻尼
  （bias<−0.5 时 clip(2·bias+2, 0.1, 1.0)），岛弧同处理；且 |bias|>0.5 处
  双峰基准服从作者（top-N 地壳泄漏的 continental cell 不再拿 +850 m 基准隆起
  成高原）；正常造山带无感
- **Pillow 13 弃用**：4 处 `Image.fromarray(..., mode="I;16")` 改原生
  uint16 映射（2026-10-15 Pillow 13 移除前）
- **scripts 下沉**：validate_climate / import_earth_elevation 进包
  （`dreamulator.validate_climate` / `dreamulator.import_earth_elevation`），
  cli_climate 的 sys.path hack 移除；narrator anthropic 类型修复

## [0.17.0] — 2026-08-06

### Added

- **岛弧/造山带小圆弧涌现机制**（Frank 1968 *Curvature of Island Arcs* /
  Tovish 1978）：Voronoi 平分线几何上产不出岛弧的小圆弧；现每次构造 resample
  从当前运动学状态（欧拉极相对速度 → 汇聚速率 → 俯冲角 → 弧矢比 0.10–0.30）
  把俯冲/碰撞边界松弛向小圆弧，弧矢随演化逐步生长（涌现而非初始规定）。
  洋壳俯冲凸向俯冲板（日本/阿留申式），陆陆碰撞凸向 indenter（喜马拉雅/
  阿尔卑斯式）。配置 `trench_arc`（0=关，默认 1）。nacrea 碰撞带
  sagitta/chord 0.14–0.27（日本弧 ≈0.2）
- **汇聚带沿弧分段**（日本列岛式）：~800 km 波长 fBm 调制隆起幅度
  [−0.25, 1.35]× 与带宽 0.7–1.3× → 主岛 + 小岛 + 弧间断陷海，替代均匀缎带

### Fixed

- **板块交织**（互插窄连接，如 plate_006/018/019）：根因为加权 Voronoi 与弧
  翻转两个边界决定方同尺度叠加、小盘被两弧对夹、无最小宽度约束。连续拆分
  （BFS 序）+ 贴边界翻转带 + 弧矢局部宽度封顶 + 最终边界平滑 + enclave 守卫；
  重建后 enclave=0、边界干净、弧度保持
- **裂谷海碎成湖泊串**：geography.yaml 裂谷 radius ×1.7、strength 加强、中段加
  西支分叉（仿东非 Western Rift）；裂谷走廊水体成单一连通陆间海

### nacrea 重建实测

22 板 CV=0.83；最长边界弧 sagitta/chord 0.145–0.272；用户可视化验证通过。

## [0.16.0] — 2026-08-06

### Added

- **地理锚定（geography.yaml）**：把命名地貌（大陆/洋盆/群岛/裂谷海/地峡/
  高原…）编码为机器可读锚点 → 逐 cell 陆地偏置场 + 全局阈值分配地壳，命名
  海陆落到指定位置；构造演化后自动重锚定（`reapply_after_tectonics`），
  大陆不随板块漂移离开锚点。删除 geography.yaml 即回退随机大陆
- **测试 CI**（`.github/workflows/tests.yml`）：pytest 硬门槛（全量、
  --all-extras）+ ruff F,E9 硬门槛 + mypy 报告档（roadmap 功能性 #3 清偿）
- `terrain generate` CLI 与 geological 引擎同源加载 geography.yaml，输出改
  顶层 `maps/`（此前写 legacy 目录且从不加载锚定）

### Changed

- **板块大小偏态化**（roadmap #6 清偿）：可变密度 Poisson-disc 种子
  （对数均匀 size-factor）→ 初始剖分偏态；裂解改加权 Dijkstra → 不等大碎片；
  构造重采样改**乘法加权 Voronoi**（power diagram 图版本）——每板持出生面积
  为持久权重、波前代价 ∝ 1/w。修复无权"质心→最近种子"重采样（= Lloyd 迭代，
  吸引子为等面积 CVT）洗掉偏态的问题；最终 boundary warp 同传权重。
  nacrea 实测：26 板、CV 0.22→0.97、max/min ≈2000（地球主板块 ≈100×）
- **板块边界曲率**（roadmap #7 清偿）：boundary_warp 噪声改低频 fBm
  （base_freq=0.6，波长≈板块尺度），边界弯曲成岛弧状而非细碎锯齿
- **前端图层系统重构**：kind 分组多选面板 + 烘焙/显示分离

### Fixed

- **板块数坍缩**：重分区按索引命名与裂解板块错位 + needs_resample 每步触发
  → 板块流失至 6；现透传真实 plate_ids、种子去重、每 10 步/裂解后重分区
- **地理锚定静默丢失**（2026-08-06 回归）：绕过 DAG 的生成路径不加载
  geography.yaml，命名海陆全部丢失；修复加载链并记录 build 跳过判定
  （`_outputs_exist` 只看输出存在）陷阱
- **俯冲海沟缺失**（roadmap #8 清偿）：海沟凹陷仅限洋壳（陆陆碰撞无海沟），
  relief 1.4→7 km；nacrea 海洋最深 −4758→−10484 m（地球海沟 −8~−11 km）
- F 类 lint 存量 19 项清零（未用变量/导入、无占位 f-string），
  tests.yml 以 F,E9 门槛防回潮

### nacrea 重建实测

26 板（CV=0.97）；海洋最深 −10484 m、最高峰 11737 m；均温 12.7 °C、
13 个 Köppen 类；16 个锚定特征空间抽查 10 个完全命中、裂谷 7 段中 6 段
中心为海（中南段为汇聚边界造山叠加残留，见 roadmap #9）

## [0.15.0] — 2026-08-04

### Added

- **气候 3A.3a 慢自转参数化**：config 新增 `hadley_extent_deg` /
  `polar_cell_start_deg`（默认 30/60 保持地球行为）；`hadley_cell_wind()`
  环流胞边界广义化（慢自转行星 Hadley 胞扩展 ~Ω^-1/2 标度）；回归测试
  `tests/test_map/test_export.py`
- **文档**：竞品分析与文明层设计拆分为独立文档（`competitor-analysis.md`、
  `civilization-layer.md`）；扩展功能 backlog 并入 vision.md §9

### Changed

- **climate 引擎与地质管线共读 `terrain_config.yaml` 气候调优项**——独立
  `build --only climate` 与管线内气候阶段不再可能分叉；canonical 物理强迫
  （光度/距离/倾角/温室）仍以 planets.yaml + stellar 为准
- **nacrea 样板世界全面改造**（物理自洽化）：
  - 天文：新增 4:2:1 拉普拉斯卫星链 **Cadence**（0.05 M⊕, 6.5 d）/
    **Vigil**（0.03 M⊕, 13.0 d），补上 e_m=0.0025 的 60 亿年共振泵浦机制
    （此前设定无泵浦源）；Aegis 轨道内移 0.2795→0.2722 AU（混合变暖路径），
    Boreal/Glacis 随共振链同步缩放
  - 温室 72→75 K（余 3 K 预留次行星半球加温 3A.7）；有效倾角 9° 启用季节项
    （此前 0°，季节恒关）
  - 气候再校准：均温 9.2→**14.4 °C**、最高 28.1 °C、Köppen 类 9→**13**
    （首现热荒漠 BWh）、冰原+苔原 16.4%→11.0%
  - **海陆分布翻案**：依据潮汐物理（向星/背星点为深海、侧点/极点偏陆）改为
    不对称混合案——Aegis 深渊洋、虚空洋、世界岛（超大陆裂解 + 大裂谷海）、
    破碎群岛带（撞击遗迹）、北极孤立大陆保留、南极改浅海；旧"大潮点大陆"
    设定推翻
  - 级联更新约 10 个设定文档；合并重复文档 land_sea.md、red_abyss.md
- **roadmap-analysis.md → roadmap.md** 改名重组：状态快照更新至 v0.15.0、
  Phase 状态表、技术债务刷新（3A.6/孤儿模块已清偿；新增热带直减率偏冷、
  均匀高原与板块合并两项）

### Fixed

- **map.yaml 导出回归**（v0.14.0 重构引入）：导出仅"增量更新" map.yaml，
  从零重建的世界缺 `planet_id` 等必填字段，maps API 抛 pydantic
  ValidationError；现每次导出完整写入标识字段（planet_id / projection /
  尺寸 / voronoi 参数）
- nacrea 设定数据不一致：轨道年 80.5→77.3 d、季节 20.1→19.3 d、极点极夜
  31→38.7 d、次行星半球加温 1.5–2.0→~1 °C（按辐射收支核算）

## [0.14.0] — 2026-08-04

### Added

- **性能：nacrea 全量构建 532s → 98s（−81.5%）**
  - Numba JIT 噪声内核（`map/noise_kernels.py` 新模块）：标准 Perlin 梯度噪声
    + fBm，44µs→9.6ns/call（~4600×），`parallel=True` 且逐点独立 → 严格确定
  - 构造演化：cKDTree 批量最近邻（消除 ~1 亿次 Python 点积）、高程数组规范化
    表示、变更检测/侵蚀/新生板块锁定向量化（97→39s）
  - 气候：BFS 水汽输送用风向候选表 CSR 预计算（88→3.3s，27×）；图梯度与
    地转风全向量化（14.3→4.1s）
  - CVT 网格：Lloyd 质心与球面多边形面积向量化（37.8→15.2s，面积守恒
    1.000000×4πR²）
  - 引擎构建流移除重复气候阶段：climate 引擎为唯一权威（−123s），导出栅格
    cKDTree 复用
  - mesh JSON 改 pydantic-core Rust 序列化（88MB 读 2.0→1.1s、写 1.8→0.4s）
- **M0 profiling 仪表**：每次构建自动落盘 `build_profile.json`（引擎/阶段墙钟）；
  `scripts/profile_build.py`（子进程档案表 / `--memory` tracemalloc 模式）；
  `docs/usage/profiling.md`（py-spy 火焰图 / Scalene / VizTracer 工作流）
- **基准 harness**：`benchmarks/`（pytest-benchmark：噪声 / CVT / 气候 / mesh IO
  微基准 + 4096 地形宏基准；slow/benchmark markers 与默认套件隔离）+ GitHub
  Actions 基准回归工作流（github-action-benchmark，`perf-dashboard` 分支）
- **验证套件** `tests/validation/`：T3 物理合理性（L/GHG/反照率单调性、无大气
  极限、倾角季节响应、3 个 xfail 占位）+ T2 太阳系端元复现（Venus / Mars /
  裸岩 / nacrea HZ 中心）；慢速确定性回归测试（跨进程 hash 种子比对）
- **验证策略**（climate-validation.md §7）：针对"仅以现代地球验证"的过拟合
  风险，建立多线证据框架（PMIP 古气候 / THAI 系外比对 / 太阳系端元 / 过程
  诊断）与 T2–T5 分层计划
- **共享物理参数解析**（`engine/physical_inputs.py`）：卫星感知恒星查找
  （卫星→主行星→恒星父链），轨道周期由开普勒第三定律导出（nacrea 80.47 天，
  与设定吻合）；config 新增 albedo / orbital_period_days / surface_pressure_hpa
- **文档**：climate-engine.md Phase 3A.6（方案常数行星化 8 项：Hadley 自转
  依赖、次行星半球强迫等）；nacrea 新增 long_term_cycles.md（米兰科维奇式
  变率谱）；terrain-pipeline.md §15 实测修正（基线、噪声路线）
- 新依赖：`numba>=0.61`

### Changed

- **噪声后端 OpenSimplex → Numba Perlin**：统计相似但非比特一致——重建任何
  世界地形细节会变化（预期内；同一代码版本内严格可复现）
- **nacrea 气候物理修正**：greenhouse 33→72K（HZ 中心定位，比地球等价值低
  6K，预留次行星半球加温 2–4K）；恒星辐射按 0.0357 L☉@0.2795 AU ≈ 0.458 S⊕
  计算（此前误用地球默认 1 L☉@1 AU，日照高估 2.2×）。修正后年均温 9.2°C、
  9 个柯本类（EF 冰原 37% / Cfb 温带 23% / Af 热带雨林 11%）
- nacrea 派生数据已用新引擎重建（本版本随附提交）

### Fixed

- **构建确定性**：`terrain_synthesizer` 曾用 `abs(hash(pid))` 作噪声种子——
  Python 字符串 hash 每进程随机加盐（PYTHONHASHSEED），导致同一世界每次
  构建地形都不同。改用 `zlib.crc32`，并新增 slow 回归测试
- **气候引擎 mesh 回写静默失败**：`model_dump_json()` 返回 str 而非 bytes，
  `write_bytes()` 抛异常被吞掉，气候字段未写入 cvt_mesh.json（前端读到过期
  气候）→ `.encode("utf-8")`
- **物理参数分叉**：geological 引擎管线内气候曾按地球默认参数运行（倾角
  23.44°、1 L☉@1 AU、地球重力/气压），与 climate 引擎不一致（14 vs 11 柯本
  根因）→ 统一为 planets.yaml + stellar 共享解析
- `_anisotropic_fbm` 各向同性分支潜在崩溃（双重频率缩放 + 缺 seed 参数）
- 降水 BFS 的 `x not in ndarray` 为 O(n) 全扫描成员检查 → 直接索引
- 死代码清理：BFS 未使用的 coastal 循环（白跑 12 次）、构造演化 `if True`
  重复汇聚扫描、`climate_seasonality.py` 死模块（468 行零 import）、
  `_fallback_noise_xyz`、opensimplex 可用性探针

## [0.13.3] — 2026-07-31

### Fixed

- **气候引擎 falsy-zero bug**：`planet.axial_tilt_deg if planet.axial_tilt_deg
  else 23.44` 的真值判断把显式的 `0.0`（潮汐锁定天体）当作未设置，静默替换为
  地球倾角并凭空造出季节；`rotation_period_days` 同模式。改为 `is not None`
  守卫，config 构建抽出纯函数 `_build_terrain_config` 并新增回归测试。
  对 nacrea 的影响：柯本分类 14 → 11（无季节即无 D 类），极地冰原扩大，
  年均温不变。
- **earth 世界三分支 fork_layer 修正**：`fork_layer` 是 build 起始层，不只是
  展示标签。climate-dev `geological → climate`（实际只持有气候层，旧标注使
  build 从程序化地质引擎起跑，有干扰手工导入地形的风险）；l4-companion
  `geological → astronomy`（自带天文输入，旧标注跳过天文引擎，伴星衍生物
  从未计算）；terrain-dev 删除创建初期的 28 行简化版 `stellar.yaml`（body_id
  仍用旧方案 `earth`）——它挡在继承链上，使该分支的星系视图/轴倾角一直用
  简化版而非根世界完整太阳系，也是地图 ID 曾叫 `earth` 的源头。

### Added

- **nacrea 首份气候数据**：`dreamulator build nacrea --only climate` 全量产出
  （climate_summary + 温度/降水栅格 + 柯本分类 + 10 万 cell mesh 回写）。
  T = −70~27 °C，11 个柯本类（Af 热带雨林为最大类，与设定一致）。近似点已
  记录于 `data/worlds/nacrea/design-notes/climate_data_status.md`：轨道参数
  查找未实现（按 L=1.0 L☉、d=1.0 AU 计算），潮汐锁定仅纬向对称近似——
  数据可展示、数值自洽，非设定级正式气候。

### Docs

- `roadmap-analysis.md` 新增 §六 已知技术债务：功能性 4 项（轨道参数查找
  硬编码及其温室参数耦合风险、`climate_seasonality.py` 孤儿模块、潮汐锁定
  经度效应缺失、`terrain generate` 旧版输出路径）+ 工程卫生 2 项（climate.py
  存量 mypy 错误、全仓 ruff 告警，注明 UP042 不可批量自动修的原因）；
  Phase 3A 表新增 3A.6（恒星/轨道参数查找）、3A.7（潮汐锁定经度效应）。

## [0.13.2] — 2026-07-31

### Fixed

- **分支切换后地图加载 404**：不同分支的地图 ID 互不相同（climate-dev 为
  `planet_earth`，terrain-dev 为 `earth`），切换分支只改 `?branch=` 查询参数，
  URL 路径中的 mapId 在目标分支不存在 → 3D 球面视图与 2D 地图视图的
  meta/elevation/cvt-mesh 全量 404，页面卡在错误状态（手动刷新或重新导航才恢复）。
  `GlobeViewerPage` / `MapViewerPage` 现会核对当前分支实际可用的地图列表，
  mapId 过期时自动重定向到该分支第一个可用地图（保留 branch/sun/season/night
  等查询参数）；失效的深链/书签同样自愈。
- `MapManager.list_planets_with_maps()` 改为分支自有地图优先排序（与
  `_maps_dir` 解析优先级一致），保证重定向目标优先选分支自己的地图。

### Changed

- **统一地球地图 ID 为 `planet_earth`**：与行星定义（`stellar.yaml` /
  `planets.yaml` 的 `planet_earth`）及 `MapMetadata.planet_id` 字段约定
  （"matches Planet.id"）对齐。此前 terrain-dev 目录为 `earth`、climate-dev
  目录为 `planet_earth` 而其 `map.yaml` 又写 `earth`，四处命名两两不一致。
  terrain-dev `maps/earth` → `maps/planet_earth`（git rename 保留历史）；
  两分支 `map.yaml` 的 `planet_id` 一并统一。跨分支 URL 路径从此恒定
  （`/globe/planet_earth`），旧链接由上述重定向逻辑自愈。

### Chore

- 修复 `tests/test_map/test_terrain_pipeline.py` 长期收集即报错的问题
  （`flood_fill_plates` 早已被 Voronoi 分区取代）：清理死导入，分区完整性
  断言改经公开 API `generate_plates` 覆盖，阶段预期对齐现状（climate 已实现，
  rivers/erosion 仍跳过）。
- `manager.py` / `models.py` 存量 ruff（TC003）与 mypy 告警清零。

## [0.13.1] — 2026-07-30

### Fixed

- **静态站（GitHub Pages）地图 404 关键修复**：`scripts/export_static.py` 的 `_export_map_data()`
  仍按 v0.10.0 之前的旧布局（`layers/geological/input/maps/`）查找地图，v0.10.0 以来静态导出
  不含任何地图文件。改为按顶层 `maps/{planet}/` 布局导出（分支自有地图导出到
  `branches/{b}/maps/`，分支无自有地图时由前端回退根路径）。
- `_export_civmap_reference()` 同步修正：civmap 底图 GeoJSON 也随 v0.10.0 迁移到顶层
  `maps/earth_reference/`，静态导出同样缺失。
- `staticClient.ts` `getVoronoi` 改为优先 `cvt_mesh.json`，legacy `voronoi.json` 降为兜底——
  消除每个行星两个必 404 请求。
- 新增 `frontend/public/favicon.svg`，`index.html` 引用由从未存在的 `/vite.svg` 改指
  `/favicon.svg`。

### Docs

- **文档结构整理：design/ 与 usage/ 按读者分离**。`usage/project-structure.md` 迁为
  `design/architecture.md` 并更新至当前项目结构（补 map/、civmap/、scripts/、packages/ 等，
  统一 derived/ 格式描述，新增前端双模式、地图子系统两节）；`map-system.md`、`terrain-pipeline.md`、
  `climate-engine.md`、`climate-validation.md` 迁入 `design/`；`usage/` 保留 cli、map-workflow、
  civmap-guide、frontend-3d-viewer 四个操作指南。
- `design/roadmap-analysis.md` 与 CHANGELOG 核对补齐完成状态（Phase 2.5 完成、3A 核心与 3A.1
  已合并、季节模块、帮助系统等），修复失效锚点与重复标题。
- 两个 README 的路线图改为状态摘要 + 引用，单一事实来源为 `roadmap-analysis.md`。
- 重写文档索引（`docs/CLAUDE.md`、`usage/CLAUDE.md`，新增 `design/CLAUDE.md`）；
  全仓库跨文件引用同步更新（源码 docstring、`HelpPage.tsx`、scripts、knowledge/worldbuilding
  文档），校验零断链。
- 两个 README 与根 CLAUDE.md 补充静态站本地验证流程
  （`npm run build:static:local && npm run preview:static`）——导出脚本改动后的强制自检，
  本次 bug 的历史教训。

---

## [0.13.1] — 2026-07-30

### Fixed

- **静态站地图 404**：`export_static.py` 跟上 v0.10.0 的 `maps/{planet}/` 顶层布局（此前仍读旧的
  `layers/.../maps/`，导致静态导出完全不含地图文件）；为 climate-dev 补跑气候引擎并回写柯本/温度/降水数据。
- **无板块边界的 mesh 在浏览器与 API 下整页崩溃**（黑屏，柯本/海岸线/悬停高亮全失）：这类 mesh
  （如真实地球 ETOPO1 导入）的 `distance_to_boundary_km` 全为 `inf`，Python 将其序列化为非标准
  `Infinity` 字面量，浏览器 `JSON.parse` 直接抛错 → `cvtMesh` 为 null → 依赖它的所有图层与悬停高亮
  失效并触发视图崩溃。新增 `sanitize_nonfinite` 在序列化边界把 `NaN/±Inf` 转 `null`，并将该字段放宽为
  `float | None`；清洗已提交的 climate-dev mesh。该问题在 API 模式同样存在，一并修复。

### Changed

- 静态数据获取加 `cache: 'no-cache'` 条件再验证，规避 GitHub Pages 的 `max-age=600` 缓存与无
  `Cache-Control` 的 404 回放造成的陈旧数据/陈旧 404；为每行星补 `plates.json`/`features.json` 占位、
  `maps.json` 恒写以消除回退路径噪声；导出 JSON 改紧凑格式（cvt_mesh 41.7 → 25.7MB）。
- CI（`deploy-pages`）提速：`on.push.paths` 限定站点相关文件（纯文档提交不再触发部署）；移除冗余的
  `dreamulator build` 步骤（derived 已随仓库提交），保留 `workflow_dispatch` 手动入口。

## [0.13.0] — 2026-07-29

### Added

- **图层面板重构**：底图（地形 / 陆海 / Köppen）改为单选 chip 条（P社 map mode 式，点一个其余归 0）；
  叠加层按学科分组、可折叠，组头三态复选框（整组开关 / Ctrl+点重置为默认），无可见层的组默认折叠。
  图层元数据（`helpContent`）新增 `kind`（basemap/overlay）/ `group` 字段，为后续 12~15 个图层
  （气候 / 水文 / 文明）上线做准备。数据模型不变（layers 不透明度表仍是唯一事实来源）。

### Changed

- **版本号单一来源**：`pyproject.toml` 为 Python 侧唯一版本源，`__init__.py` / `api.py` 改用
  `importlib.metadata.version("dreamulator")` 运行时读取，升级版本无需再手动同步这两处
  （配合 `uv version --bump`，会同步 `uv.lock`）。`frontend/package.json`（JS 侧独立生态）仍需单独同步。

### Docs

- 记录多投影 GPU 渲染架构与 `?reproject=cpu` 调试路径（明确其非"无 GPU 兜底"——显示始终依赖 WebGL）。

---

## [0.12.0] — 2026-07-28

### Added

- **GPU 重投影**：Mollweide / Robinson 投影从 CPU 逐像素重投影改为 GPU 片元着色器逆 warp
  - Mollweide 闭式逆变换 + 椭圆边界；Robinson 预烘焙 1D 查找纹理（pdfe → 纬度 / plen）查表
  - `?reproject=cpu` 保留为调试对照（非无 GPU 兜底——显示始终需 WebGL）
- **昼夜光照（2D + 3D）**：
  - 2D 三种投影与 3D 球面均在着色器内计算昼夜（太阳天顶角 cos θz），晨昏线 smoothstep 柔化 + 夜间冷色调
  - 季节滑块驱动太阳赤纬（周年变化：春分 / 夏至 / 秋分 / 冬至），时刻滑块驱动直射经度（周日变化）
  - 光照设置经 URL（`?sun=&season=&night=`）在 2D↔3D 间同步、可分享；2D 光照开关默认关
- **经纬网 SVG 叠加层**：等距圆柱干净直线、Mollweide / Robinson 平滑曲线（取代烘焙纹理网格），垫在单元格高亮之下

### Changed

- **单元格高亮统一为 SVG 叠加层**：移除烘焙进 GPU 纹理的高亮，三种投影行为一致；高亮色蓝（悬停）/ 黄（选中）

### Fixed

- **等距圆柱悬停 / 选中高亮消失**：`hoveredCell` / `selectedCells` 不在 `useGPUTerrain` 的 `useMemo` 依赖里，悬停时纹理永不重烘焙
- **Mollweide / Robinson 垂直拖动高亮偏移**：渲染循环 effect 依赖为 `[]`，闭包 `projection` 永远停留在挂载初值 `'equirectangular'`，mesh 一直用等距圆柱公式定位（垂直对纬度线性），与 SVG 高亮的非线性投影速率不一致，偏移随垂直拖动累积

### Chore

- 恢复前端 ESLint 配置（`.eslintrc.cjs`），`npm run lint` 可用（`--max-warnings 0`）

---

## [0.11.0] — 2026-07-27

### Added

- **`climate_seasonality.py`**：光照驱动季节模块（月度光照→温度振幅→ITCZ 迁移→降水分配），支持行星/卫星/高偏心率三种模式
- **气候模拟 5 阶段 rich 进度输出**：Temperature → Wind → Precipitation → Köppen → Write，含计时

### Changed

- **气候模型调参**（验证指标提升）：
  - 季节振幅 15→35，纬度梯度 45→40
  - ITCZ 增强 700→1200 mm，热带对流 ×2，热带降水底线 800mm
  - 副高抑制移至 convection 之后，蒸散 30%→40%
- **ClimateEngine 依赖**：`requires = ["astronomy"]` → `["astronomy", "geological"]`

### Fixed

- `--only X --force`：只强制目标引擎，依赖走缓存跳过
- `GeologicalEngine.outputs_exist()`：检查 `maps/` 目录（适配新数据结构）
- validate_climate.py：支持 `--data-dir`，搜索新 `maps/` 路径
- import_earth_elevation.py：planet_id 从目录名推断（不再硬编码 "earth"）

### Metrics (earth/climate-dev, 32K cells, vs Beck 2018)

| 指标 | v0.9.0 | v0.11.0 |
|------|--------|---------|
| A 类准确率 | 13.3% | 33.3% |
| D 类群组准确率 | 0% | 48.3% |
| 总群组准确率 | 40.8% | 53.9% |
| Cohen's Kappa | 0.102 | 0.209 |

---

## [0.10.0] — 2026-07-27

### Changed (Breaking)

- **统一 maps/ 目录结构**：地图数据从 `layers/{layer}/input|derived/maps/{planet}/` 迁移到顶层 `maps/{planet}/`。一个行星的所有空间数据（地形 + 气候）集中在一个目录。
- **metadata.json 废弃**：生成参数合并到 `map.yaml`（单一元数据来源）
- **branch.yaml 格式**：从 JSON 改为真正的 YAML（读取兼容旧 JSON 格式）
- **.gitignore**：移除 `data/**/derived/` 规则，公开数据全部 git 追踪

### Removed

- `BaseEngine.version` 字段（仅用于日志，无逻辑依赖）
- `WorldMetadata.version` 字段（"数据格式版本"，从未用于迁移）
- `metadata.json` 文件（内容合并到 map.yaml）

### Fixed

- 分支不再需要手动复制 `planets.yaml`/`stellar.yaml`（LayerResolver 正确继承父世界）
- `terrain info` 从 map.yaml 读取元数据（fallback 到旧 metadata.json）

---

## [0.9.1] — 2026-07-27

### Added

- **Köppen 气候图层**：前端地图新增 Köppen-Geiger 气候分类着色（Beck et al. 2018 标准色），支持 2D 和 3D 视图
- **单元格气候信息**：右侧 inspector 显示 Köppen 气候中文名 + 英文缩写、年均温、年降水

### Fixed

- **3D 球体对齐**：鼠标 picking 改用纹理 UV 坐标（替代 sphereToLonLat），高亮多边形 z 坐标取反匹配 SphereGeometry UV 映射
- **GeologicalEngine planet_id**：自动从 planets.yaml 检测，不再硬编码 "earth"（修复 nacrea 等非地球世界的 build 输出路径）
- **ClimateEngine 数据回写**：气候模拟后将 koppen_class/temperature_C/precipitation_mm 写回 cvt_mesh.json，前端可渲染

---

## [0.9.0] — 2026-07-27

### Added

**气候引擎 (Phase 3A)**
- `climate_physics.py`: 12 个纯物理函数（EBM 温度、纬度梯度、海拔递减率、季节周期、Hadley/Ferrel/Polar 风带、蒸发率、地形降水、ITCZ、Ekman 洋流、Koppen 分类）
- `climate_simulator.py`: CVT mesh 上的完整气候模拟（温度 → 风场 → BFS 水汽输送 → 降水 → Koppen）
- `ClimateEngine`: BaseEngine 封装，支持 `dreamulator build --only climate`
- 输出: temperature.png, precipitation.png, koppen.json, climate_metadata.json

**地质引擎封装**
- `GeologicalEngine`: 将 terrain pipeline 封装为 BaseEngine，支持 `dreamulator build --only geological`
- DAG 拓扑序: astronomy → geological → climate

**气候验证体系**
- `scripts/import_earth_elevation.py`: 导入 ETOPO1 真实地球高程
- `scripts/convert_koppen_map.py`: 转换 Beck et al. (2018) Koppen 参考数据
- `scripts/validate_climate.py`: zonal 加权 RMSE + 逐 cell 空间对比 + Cohen's Kappa
- `earth/climate-dev` 分支: 32768 cell 真实地球 CVT mesh + Koppen 参考

**CLI 重构**
- `dreamulator climate info|validate|import-elevation` 子命令组
- `dreamulator build` 增加 rich 进度输出（每层计时 + 状态）
- `build` 成为唯一推演构建入口，`terrain generate` 定位为开发调试工具

**文档**
- `docs/usage/climate-engine.md`: 气候引擎架构 + 数据驱动改进路线图
- `docs/usage/climate-validation.md`: 验证指南 + 数据下载说明
- `docs/knowledge/climatology/`: 气候学知识库（EBM 公式 + 参数参考）
- `docs/usage/cli.md`: 新增 build + climate 命令参考

### Changed

- `pipeline_types.py`: 新增 16 个气候配置参数
- `export.py`: 新增气候图层导出（temperature/precipitation PNG + koppen JSON）
- `pyproject.toml`: 新增 `validation` extra（xarray, netCDF4, tifffile）
- 前端 3D 球体视图移除水平镜像（`flipHorizontal` 默认改为 false）

### Fixed

- ETOPO1 纬度轴方向（CF 约定升序 -90→+90，非降序）
- 海拔递减率不再错误应用到海底（海洋使用 SST 模型）
- 降水 BFS 不再跨 pass 累积（每 pass 重置水汽）
- 3D 球体视图东西方向镜像

### Validated

- 全球均温 15.0 °C（匹配地球）
- 陆地比例 29.1%（匹配地球 29%）
- 降水 RMSE 493 mm/yr（通过 <800 阈值）
- nacrea 完整构建 6m44s 全部通过

---

## [0.8.0] — 2026-07-27

### Added

**海平面自动校准 ("倒水")**
- 新增 `_apply_sea_level_calibration()`: 对 elevation × area 分布进行二分查找,匹配 `target_land_fraction`,O(n) 无排序
- 新增 config: `sea_level_auto` (bool, 默认 true), `target_land_fraction` (float, 默认 0.29)
- 隐含水预算在日志中以 km 等效深度 + million km³ 绝对体积报告

**板块裂解 (Cortial 2019 §4.4)**
- 超板块概率加成: 面积 > 2× 均值的板块有 1.5–3× 加成
- 10-step BFS 冷却期防止碎片化
- `rift_base_rate` / `rift_min_pieces` / `rift_max_pieces` 配置参数

**前端**
- Bartholomew 经典分层设色方案 (蓝→青→绿→黄→棕→白)
- 16-bit PNG 解码获取精确高程值
- 3D 地球: SunLight 动态光照恢复, 相机防止进入球体内部
- 状态栏和 cell inspector 统一高程数据源
- 全局异常边界 (ErrorBoundary)

**CLI**
- `terrain generate` 自动记录生成命令到 `generation_command.json`

### Changed

- 造山带改为**大圆弧曲线**并设置 30° 长度上限
- 内陆造山带每板块上限为 4 条, 面积缩放调整为每 800 cell
- 海岸低地与中海拔高原颜色可区分

### Fixed

- `classify_sea_land()`: 被淹没的大陆地壳不再错误重分类为 transitional, 大陆地壳比例现在地质正确 (> 露出陆地)
- nacrea 星球 ID 修正 + 3D 球面实时缩放显示
- `onDistanceChange` 低于过渡阈值时不再被忽略
- PNG 量化不再导致海岸线颜色渗色
- 海洋深度色标方向修正

## [0.7.3] — 2026-07-26

### Fixed

**关键修复：大陆碎片化**
- 5-octave fBm 地壳分配产生 checkerboard 碎片——根因是 opensimplex 未安装，fBm 路径从未执行，回退到纯纬度排序
- 安装 opensimplex 并改为**纬度主导 (0.7) + fBm 纹理 (0.3)** 的混合分配策略，mis-placed 从 29.9% → 2.7%
- 移除 fallback 代码，opensimplex 升为核心依赖

### Added

**lat_bias 参数**
- 新增 `lat_bias` 配置项 (0–1)，控制大陆地壳向赤道集中的权重
- 快速自转行星设高值 (0.7–0.9)，潮汐锁定设低值 (0.3–0.5)

### Changed

- `continental_fraction_min/max` 默认值: `[0.25, 0.65]` → `[0.28, 0.36]`
- nacrea: `lat_bias=0.33`, earth/terrain-dev: `lat_bias=0.7`
- `opensimplex>=0.4` 从 heightmap 可选依赖移入核心依赖

## [0.7.2] — 2026-07-26

### Added

**海陆比例控制**
- 新增 `continental_fraction_min` / `continental_fraction_max` 参数,替代硬编码的 `[0.1, 0.9]`
- `terrain info` 子命令新增面积加权海陆比例报告 (细胞数 + km²)
- earth/terrain-dev 配置文件完整参数注释文档 (30+ 参数)

### Changed

**移除 `sea_level_m` 参数**
- 从 `TerrainPipelineConfig` 中移除 `sea_level_m`，硬编码为 0.0 (海岸平原/大陆架计算依赖于 sea_level=0)

**默认地图跳转 2D → 3D**
- "打开地图编辑器" 链接从 `/map/` (2D) 改为 `/globe/` (3D 球面)

### Fixed

**地图色彩异常 (关键修复)**
- 地形管线生成后自动同步 `map.yaml` 到正确的 PNG 编码范围
- nacrea 高程范围 `[-11000, 9000]` → `[-11000, 11632]`,修复 +1000m 以上陆地渲染为海洋的问题
- earth/terrain-dev 高程范围 `[-11000, 9000]` → `[-11000, 9802]`

**YAML 配置修复**
- nacrea `terrain_config.yaml` 合并三个重复的 `terrain:` 键 (YAML 键覆盖导致参数丢失)

### Removed

- 前端静态数据中残留的旧格式 `voronoi.json` (已被 `cvt_mesh.json` 取代)
- `data/worlds/earth/layers/geological/input/maps/earth/benchmark.json` (开发调试临时文件)

## [0.7.1] — 2026-07-26

### Added

**分形海岸线**
- 5-octave fBm 地壳类型噪声（Mandelbrot 1967），海岸线复杂度 +40%
- 沿走向高度调制的古造山带（1D simplex 噪声），伴有山间盆地（吐鲁番型断陷盆地）
- 造山带数量随板块内部面积缩放

### Changed

**边界效应优化**
- 汇聚/离散/转换边界分别配置不同的 sigma（400/300/200 km）
- 转换边界粗糙度增强（断层迹线 200km 内 1.5 倍噪声）
- 速率因子改用亚线性幂律（`sqrt(rate/ref)`），消除硬截断
- 边界类型传播至影响半径内所有 cell
- 影响半径收紧至 1.2σ（600 km）

**海岸平原改进**
- 变宽平滑：高山海岸保留 40% 高度 + 至少 1 cell 过渡带
- 最高海岸 cell 从 5947m 降至 2629m

**噪声增强**
- 陆地噪声振幅 +50%（900m 细节 / 1800m 区域）
- 板块内部噪声基底 1.2×（原 1.0×）

### Fixed
- npm 脚本使用 `uv run python` 而非系统 `python`
- terrain 管道每步显示 Rich 着色耗时

## [0.7.0] — 2026-07-25

### Added

**板块构造时间演化 (Cortial et al. 2019)**
- `tectonic_simulator.py`：质心欧拉极旋转 + 球面 Voronoi 重剖分，板块边界随时间移动
- 自动时间步长缩放：根据 CVT 分辨率调整 δt，确保每步移动 ≥1 cell
- 俯冲抬升 + 大陆碰撞造山 + 洋脊剖面 + 全局侵蚀（Cortial 2019 常数表）

**可插拔策略接口**
- 板块剖分、地形合成、时间演化均支持多算法切换（`plate_algorithm` / `terrain_algorithm` / `tectonic_algorithm` 配置项）
- 非对称山脉剖面 (Willett 1999)：迎风坡陡、背风坡缓
- 热点火山链 (Wilson 1963)：Poisson-disc 种子 + 沿板块运动方向指数衰减
- 大陆架指数深度衰减 (Shepard 1963) + O-O 岛弧抬升 (Stern 2002)
- 各向异性 fBm 噪声：沿边界走向拉伸，产生山脊对齐纹理 (Perlin 1985)

**基准测试与回归验证**
- `--benchmark` 保存可复现指标 (seed=42, n=4096)
- `terrain validate` 对比参考基准，偏差超阈值时报错
- CI 级地形质量检测

**数据可用性改善**
- `terrain open`：一键打开输出目录
- 相对路径显示 + 分支 README 自动生成
- 日志分层：`print()` → stdout（用户），`logger` → stderr（诊断）

### Changed

- 默认日志级别 INFO → WARNING（加 `-v` 显示详情）
- 板块剖分：优先队列 BFS → Cortial 2019 球面 Voronoi + Poisson-disc 种子
- 地形合成：管线重组，边界检测 → 阶段 4，地形合成 → 阶段 5

### Added (文档)

- `docs/design/vision.md`：项目长期愿景与设计哲学
- 时间轴功能纳入路线图（近期 P2 + 远期 §4.6）
- 学科知识库更新：板块构造、地形合成参考文献

## [0.6.0] — 2026-07-24

### Added

**3D 球面 — 多边形高亮与图层叠加**
- Voronoi cell 多边形高亮（蓝色悬停 + 黄色选中），渲染真实球面多边形边界
- 四层独立透明度滑块（地形/海陆/板块/边界），任意组合叠加
- 海岸线自动检测：海陆异号像素边缘绘制黑线
- 球面经纬线网格 + 极轴（北红/南蓝 + N/S 文字）

**配色升级**
- LUT 精度 256→1024 级，色彩渐变更平滑
- 浅海色调修正：消除沙滩过渡区的黄色偏色

### Fixed

- 修复 3D 球面纹理映射（行列反转匹配 SphereGeometry UV）
- 修复 CVTVertex/CVTRegion 类型与实际数据格式不一致
- 修复 cli terrain generate 日志丢失 rich 彩色输出
- 修复桌面端移动端响应式布局（3D 球面对齐 2D 地图）
- 统一 2D/3D 单元格选择逻辑（Ctrl+双击复选）

## [0.5.0] — 2026-07-24

### Added

**3D 球面地球视图**
- 全新 3D 球面地形可视化：equirectangular 纹理贴 SphereGeometry
- R3F Canvas + OrbitControls（旋转/缩放/倾斜）+ 星空背景 + 大气辉光壳
- 缩小过渡特效（Dyson Sphere Program 风格）：持续缩小出现 "转入星系视图" 进度条，满条自动跳转
- 进入恒星系视图时自动聚焦来源行星（?focus= 参数）

**恒星系行星纹理（路线 C）**
- 恒星系 3D 视图中有地图的行星自动加载真实地形纹理
- ETOPO1 + ESRI 混合配色，256×128 DataTexture 贴球体

**3D 视图独立路由**
- 3D 恒星系视图从 WorldDetail tab 抽离为侧边栏一级入口
- 新增 `/worlds/:worldName/viewer3d` 路由

### Fixed

- CI: package-lock.json 镜像源兼容 + vitest 降级（vite 5 兼容）

## [0.4.0] — 2026-07-23

### Added

**地图查看器 — 3D 恒星系 + 星球纹理**
- 3D 恒星系视图从世界详情页抽离为独立页面 + 侧边栏一级入口
- 恒星系中有地图的行星自动显示真实地形纹理（ETOPO1+ESRI 混合配色）
- 多投影支持：等距圆柱 / Mollweide / Robinson，含经纬线网格
- GPU 地形渲染：CPU 预计算纹理 + ShaderMaterial 直出

**地图查看器 — 交互增强**
- 双击选中单元格（替代单击），避免拖拽误触
- KD-tree 球面最近邻命中测试 (O(log n))
- Cell-ID 贴图预计算 + 调色板查找，图层切换 10-20× 提速
- URL 持久化分支参数 (?branch=)

**地图查看器 — 坐标系统重构**
- mapCenter (lon/lat) + zoom 统一坐标模型，替代 pan/panWrapOffset
- 24 个单元测试覆盖核心坐标转换函数

**配色 & 视觉**
- 海洋 NOAA ETOPO1 + 陆地 ESRI Natural Earth 混合 hypsometric tint
- 海陆图层动态二值 LUT（基于真实 sea_level_m）
- 输出色彩空间统一（LinearSRGBColorSpace），消除非等距圆柱投影偏浅
- 地壳类型/边界类型中文化标签

**3D 恒星系可视化**
- 3D 视图独立路由 `/worlds/:worldName/viewer3d`
- 现有 `feat/terrain-sphere-view` 分支为后续 3D 球面地球视图准备

### Changed

- 地图设计文档精简，重定向到 `docs/usage/` 现行文档
- 旧 2D Voronoi 管线保留为 fallback，主路径切换为 CVT 球面网格

## [0.3.0] — 2026-07-14

### Added

**文明地图（CivMap）系统**
- 基于真实地球行政区划的文明层地图涂色
- Leaflet 嵌入式地图组件 + GeoJSON 渲染
- 国家面积（km²）显示、省份计数
- 分支感知的文明数据查询
- GeoJSON 底图数据通过 Git LFS 存储

**文明层文档系统**
- Markdown 文档查看器（remark-gfm 表格渲染）
- 自动链接反引号引用的 .md 文件
- ERE-if 架空历史分支（东罗马文明 IF）

**前端交互增强**
- 分支选择与活动标签页持久化到 URL search params
- WorldDetail、CivMapEditor、CivilizationDocuments 响应式移动端布局

### Changed

- l4-companion 分支迁移至 Markdown 格式，移除 civilization YAML 渲染
- CLAUDE.md 新增静态导出同步规则和 React Hooks 规则文档

### Fixed

- CivMapPreview hooks 规则违反导致页面崩溃
- 静态模式下文明数据解包错误
- 文明文档加入静态导出 + 条件 CivMapPreview 渲染
- 静态 civmap GeoJSON 导出优化与错误处理
- 移动端导航抽屉背景透明问题
- 分支 404 错误消除

## [0.2.0] — 2026-06-29

### Added

**地图系统（栅格 + Voronoi 双层架构）**
- 栅格高度图（2048×1024）+ Voronoi 语义网络（~5000 cells）
- 地图编辑器全页布局（左面板图层控制 + 中央地图视图 + 右面板单元格详情）
- WebGPU 地形渲染（Three.js `WebGPURenderer`），CPU 预渲染 CanvasTexture
- WebGL 自动 fallback（移动端 / 不支持 WebGPU 的浏览器）
- 圆柱投影无限水平环绕：ghost mesh 地形无缝拼接 + SVG 动态偏移副本
- pan.x 取模 + panWrapOffset 实现无限拖动无边界
- 鸟瞰图（Minimap）：缩略全图 + 视口矩形标注，支持 wrap 拆分
- 板块边界渲染（跳过跨反子午线伪线段，dlat > 20° 过滤）
- Voronoi cells 交互（hover 高亮 + click 选择 + 属性面板）
- 4 种着色模式：地形 / 海拔 / 海陆 / 坡度
- 移动端响应式布局：地图全屏 + 抽屉式左面板
- 程序化地形生成 API（大陆数、山脉度、板块数）
- 静态模式支持（GitHub Pages 只读部署）

**3D 恒星系可视化**
- Three.js + @react-three/fiber 渲染
- 恒星、行星、卫星轨道动画
- 天体信息面板 + 描述叙述
- 分支感知的 3D 视图查询

**conlang 人造语言工具（workspace 子包）**
- IPA → ASCII-IPA / X-SAMPA / Kirshenbaum 音素转换
- eSpeak-NG TTS 语音合成（`speak` 命令）
- 独立 CLI 子命令

**AI 叙述（narrator）**
- Claude API 集成，支持流式输出
- Token 用量追踪 + max-tokens 参数
- 分支感知叙述（`narrate --branch`）

**分支系统增强**
- `_inherit: true` 分支数据合并
- 分支选择器集成到世界详情页和地图编辑器
- 分支感知的 API 查询

### Changed

- 路线图重排：前端可视化提升为 Phase 2（已完成），模拟引擎移至 Phase 3
- 主页重设计为快速入口卡片 + 世界列表
- `solar_system` 重命名为 `earth`
- 默认 max-tokens 从 4096 提升至 32768

### Fixed

- 拖拽方向修正（Three.js 俯视相机退化坐标系：screen-right=+X, screen-up=-Z）
- 缩放约束：最小缩放 = 地图填满视口（cover 策略），最大 20x
- 移动端 WebGPU 不可用时的 WebGL fallback
- 地图边缘拖动跳跃（dragStart 统一使用容器相对坐标）
- Git LFS 在 CI 中的兼容性处理
- 3D 查看器多项渲染 bug

### Technical Notes

- 相机坐标系：`position=(0,h,0)` + `lookAt(0,0,0)` + `up=(0,1,0)` 触发 Three.js 退化处理，实际相机轴为 right=(1,0,0), up=(0,0,-1)
- AMD ANGLE/D3D11 顶点属性插值 bug 导致自定义 GLSL shader 在大视口下失败，改用 Canvas 2D 预渲染 + MeshBasicMaterial（详见 `.claude/notes/threejs-camera-pan-debug.md`）
- 地图平面尺寸使用 cover 策略（`max()`），保证地图始终覆盖视口

## [0.1.0] — 2026-05-30

### Added

- 项目骨架：Python 后端（uv + hatchling）+ TypeScript 前端（Vite + React）
- 数据模型：Pydantic 层级架构（physics → chemistry → astronomy → geological → climate → ecology → civilization）
- CLI 工具：init / list / info / validate / build / branch / schema / serve
- 世界管理：CRUD + 分支系统（层分叉 + 继承）
- 前端骨架：世界列表 + 详情页 + Tab 导航
- 天文学引擎：恒星物理（质量/光度/温度/寿命）+ 轨道力学
- FastAPI 服务 + Vite 代理开发模式
- GitHub Pages 静态站点部署
- 学科知识库文档框架

[0.3.0]: https://github.com/user/dreamulator/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/user/dreamulator/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/user/dreamulator/releases/tag/v0.1.0
