# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
  文档），校验零断链。纯文档变更，不涉及行为变化，不 bump 版本。

---

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
- **GeologicalEngine planet_id**：自动从 planets.yaml 检测，不再硬编码 "earth"（修复 gaia-m 等非地球世界的 build 输出路径）
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
- gaia-m 完整构建 6m44s 全部通过

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
- gaia-m 星球 ID 修正 + 3D 球面实时缩放显示
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
- gaia-m: `lat_bias=0.33`, earth/terrain-dev: `lat_bias=0.7`
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
- gaia-m 高程范围 `[-11000, 9000]` → `[-11000, 11632]`,修复 +1000m 以上陆地渲染为海洋的问题
- earth/terrain-dev 高程范围 `[-11000, 9000]` → `[-11000, 9802]`

**YAML 配置修复**
- gaia-m `terrain_config.yaml` 合并三个重复的 `terrain:` 键 (YAML 键覆盖导致参数丢失)

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
