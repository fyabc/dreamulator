# 地图工作流指南

本文档是 dreamulator 地图子系统的**操作手册**：如何生成地图、在查看器中查看与迭代、
导入外部高度图。算法原理与配置字段全表的技术参考在
[geological-pipeline.md](../design/pipelines/geological-pipeline.md)（管线）与
[map-system.md](../design/pipelines/map-system.md)（系统架构）；本文不复述。

> **相关文档**：[地图系统架构](../design/pipelines/map-system.md) ·
> [文明地图使用指南](civmap-guide.md) · [地形微调诊断](../worldbuilding/terrain_tuning_guide.md)

---

## 目录

1. [概述](#1-概述)
2. [快速开始](#2-快速开始)
3. [配置参数](#3-配置参数)
4. [在查看器中查看](#4-在查看器中查看)
5. [迭代与分支](#5-迭代与分支)
6. [数据存储](#6-数据存储)
7. [导入外部高度图](#7-导入外部高度图)
8. [常见问题](#8-常见问题)

---

## 1. 概述

dreamulator 的地图系统采用**球面质心 Voronoi 镶嵌（Spherical CVT）**作为核心数据
结构：标准 20 万 cell（~51 km/cell），板块构造、地形合成、气候模拟、河流汇水全部
直接在球面网格上完成，最终投影为 4096×2048 等距圆柱栅格用于渲染与外部交换。

地形生成**没有独立的 `map` 命令**——它由 `dreamulator build` 的 geological 层统一
驱动（`terrain_config.yaml` + `geography.yaml` 配置），管线内部按固定顺序执行 8 个
相位（CVT 网格 → 板块 → 构造演化 → 边界 → 地形 → **气候** → 河流 → 导出），每个
相位按输入内容指纹缓存，改动只重跑受影响的部分。全管线（200k，含气候）基线
~391 s（v0.36.0 口径；性能剖析见 [design/profiling.md](../design/profiling.md)）。

各相位的算法原理（Cortial 2019 板块演化、边界效应地形、fBm、海陆判定、河流
汇水）见 [geological-pipeline.md](../design/pipelines/geological-pipeline.md)。

---

## 2. 快速开始

### 2.1 CLI 生成（标准路径）

```bash
# 初始化世界（模板自带合理默认配置）
uv run dreamulator init myworld --template earthlike

# 构建：按层级 DAG 顺序执行，geological 层内跑地形管线 8 相位（含气候）
uv run dreamulator build myworld

# 强制全量重建（跳过指纹缓存）
uv run dreamulator build myworld --force
```

构建进度按相位实时显示（`1/8 CVT Mesh` … `8/8 Export`），完成后所有数据文件写入
行星的地图目录（见[第 6 节](#6-数据存储)）。

### 2.2 API 生成（自动化/前端）

后端运行时（`dreamulator serve`）可通过 REST 端点触发生成：

```bash
curl -X POST "http://localhost:8000/api/worlds/myworld/maps/planet_x/generate"
```

端点的完整参数与响应见自动生成的 OpenAPI 交互文档（serve 后访问
`http://localhost:8000/docs`）。前端地图查看器顶栏的生成按钮走同一端点。

### 2.3 查看结果

```bash
uv run dreamulator serve --open
```

浏览器自动打开 → 进入目标世界 → 选择行星 → 地图查看器（2D）或球面查看器（3D）。
操作见[第 4 节](#4-在查看器中查看)。

---

## 3. 配置参数

地图生成的配置文件是 `layers/geological/input/terrain_config.yaml`（分支中可覆盖），
完整字段表见 [geological-pipeline.md](../design/pipelines/geological-pipeline.md) 与
`TerrainPipelineConfig`（`src/dreamulator/map/pipeline_types.py`，字段注释即文档）。
海陆分布的「创意设定」不在此文件——用 `geography.yaml` 地理锚定（大陆锚点 + 陆地
偏置场，见 [design_patterns.md](../worldbuilding/design_patterns.md) 模式 9）。

**常用参数速查**（真实字段名；默认值取自 `pipeline_types.py`）：

| 参数 | 默认 | 说明 |
|------|------|------|
| `seed` | 42 | 随机种子——相同种子 + 相同配置 = 相同结果 |
| `num_nodes` | 100,000 | CVT 网格节点数（现行标准 200k） |
| `num_plates` | 20 | 构造板块数量 |
| `sea_level_auto` | true | 按目标陆地比例自动校准海平面 |
| `sea_level_offset_m` | 0 | 海平面偏移（auto 关闭时的手动海平面） |
| `convergent_uplift_m` | 4000 | 汇聚边界（造山带）基准抬升 |
| `divergent_depth_m` | 2000 | 张裂边界（裂谷/洋脊）基准深度 |
| `noise_octaves` / `noise_persistence` / `noise_lacunarity` | 6 / 0.5 / 2.0 | fBm 噪声三层参数 |
| `regional_noise_scale` | 0.5 | 大尺度区域噪声（大陆内部起伏） |
| `export_width` / `export_height` | 4096 / 2048 | 栅格导出分辨率 |

**气候参数不在地形配置里**：温度/降水由气候引擎从恒星强迫（光度/轨道/倾角/温室）
第一性推导，调气候请改 `stellar.yaml` / `planets.yaml` 或 climate 小节的物理旋钮
（见 [climate-pipeline.md](../design/pipelines/climate-pipeline.md) §13 常数表）。

---

## 4. 在查看器中查看

### 4.1 启动与导航

```bash
uv run dreamulator serve --open      # 后端 + 前端，默认 http://localhost:8000
```

进入世界 → 行星 → 地图查看器。**导航**：按住鼠标左键拖拽平移、滚轮缩放、移动鼠标
查看底栏属性、单击选中单元格。

### 4.2 图层面板

图层按渲染语义分四个**槽位**（slot），合成顺序固定为底图 → 专题 → 填充 → 特征；
UI 按学科组织为五个面板组（**地形 / 气候 / 生态 / 文明 / 开发**，开发组为诊断偏差层，
仅 Earth + 开发者模式显示）：

| 槽位 | 选择方式 | 包含图层（示例） |
|------|---------|-----------------|
| **底图** | radio（恰好 1 个） | 地形（默认）、海陆 |
| **专题着色** | radio（0 或 1 个） | Köppen、温度、降水、气压、Whittaker 群系、NPP、宜居/农业、诊断偏差热力层 |
| **分类填充** | 多选叠加 | 板块 |
| **特征标注** | 多选叠加（永远置顶） | 地壳边界、洋流、风场、海岸线、河流、风/洋流偏差箭头 |

专题着色一次只激活一个「地图模式」（仿 Azgaar 的 Style 下拉 / Paradox 的 map
mode），避免两个全表面涂色叠加的视觉混乱；可用透明度滑块透视底图。月度模式下
温度/降水/气压/风场切换为当月值（月份滑杆）。

> 地形配色采用 NOAA ETOPO1 + ESRI Natural Earth 混合 hypsometric tint 方案，自适应
> 行星高程范围。各图层纹理按数据变化烘焙并缓存；拖动透明度仅更新 GPU uniform，
> 不触发重烘。

### 4.3 投影切换

右上角下拉菜单支持 3 种投影：

| 投影 | 类型 | 特点 | 适合场景 |
|------|------|------|---------|
| **等距圆柱** (Equirectangular) | 圆柱投影 | 2:1 矩形，水平环绕，经纬线正交 | 默认视图，GPU 渲染，全面概览 |
| **Mollweide** | 伪圆柱（等积） | 2:1 椭圆外形，面积准确但形状畸变 | 面积分析（海陆比例、气候带） |
| **Robinson** | 伪圆柱（折中） | 约 2.66:1，曲线边缘，视觉美观 | 展示用途 |

三种投影共享同一套**地理坐标级**平移/缩放模型（`mapCenter.lon/lat` + `zoom`），
投影仅在坐标变换层产生差异。伪圆柱投影边缘的透明区域保留（QGIS/ArcGIS 标准行为），
想填满视口就切回等距圆柱。

**2D 昼夜光照**：URL 参数 `?sun=<经度>`（太阳直射经度）、`?season=<角度>`（0=春分…
驱动赤纬）、`?night=1`（开启昼夜叠加）；与 3D 视图经 URL 同步、可分享。

### 4.4 单元格详情（右面板）

**未选中时 — 行星摘要**：行星名 + seed、海陆比例、高程范围、板块数、网格节点数。

**悬停/选中时 — 单元格属性**（按学科分组）：

| 属性 | 说明 |
|------|------|
| 经度 / 纬度 | 地理坐标（度） |
| 海拔 | 米 |
| 地壳类型 | oceanic / continental / transitional |
| 板块 / 边界类型 | 所属板块 ID；convergent / divergent / transform / 无 |
| 汇聚速率 / 距边界距离 | cm/yr；km |
| 气候 | 温度、降水、Köppen 分类（+ 月度极值） |
| 面积 | km² |

### 4.5 性能

地图查看器使用 KD-tree 数学命中测试替代 SVG polygon hit-test：hover 延迟 ~5ms
（O(log n) 查找）、DOM 仅 1-2 个高亮 polygon、rAF 节流。cvt-mesh 端点默认
MessagePack 传输（200k cell 网格 ~31.6 MB gzip，前端透明解压）。

---

## 5. 迭代与分支

### 5.1 种子与参数迭代

```bash
# 换种子（在 terrain_config.yaml 改 seed 后重建）
uv run dreamulator build myworld --force
```

> 即使种子不变，修改任何参数也会改变地形——管线各阶段的输入变了。种子只保证
> 「相同配置 = 相同结果」。参数效果速查见[第 3 节](#3-配置参数)与
> [terrain_tuning_guide.md](../worldbuilding/terrain_tuning_guide.md)（海拔诊断链
> 与噪声换算）。

增量重建无需 `--force`：子阶段缓存按输入内容指纹自动失效（例如只改 `geography.yaml`
只重跑地理锚定之后的相位）。

### 5.2 分支工作流

分支系统允许在同一世界的不同地质方案之间并行探索，不覆盖主线：

```bash
# 在 geological 层分叉
uv run dreamulator branch create myworld pangea --at geological

# 分支上改 terrain_config.yaml / geography.yaml 后构建
uv run dreamulator build myworld --branch pangea

# 前端切换分支下拉菜单对比查看
uv run dreamulator serve --open
```

**典型分支策略**：

| 分支场景 | 分叉层 | 配置差异 |
|----------|--------|---------|
| 盘古大陆 | geological | geography.yaml 大陆锚点合并 + 低海平面 |
| 冰河时期 | climate | 行星物理（温室/倾角）调整，地质不动 |
| 海洋世界 | geological | 高海平面（目标陆地比例下调） |

### 5.3 控制海陆分布（替代「手动板块」）

板块分布由管线自动生成，**手动指定板块的机制是 `geography.yaml` 地理锚定**——大陆
锚点（位置/半径/强度）+ 陆地偏置场控制哪里该是陆，板块剖分在其上叠加地壳类型与
运动学。写法见 [design_patterns.md](../worldbuilding/design_patterns.md) 模式 9 与
[map_design_guide.md](../worldbuilding/map_design_guide.md)；「形状手绘、地貌物理
补全」的路线见[第 7 节](#7-导入外部高度图)的锚定灰度图。

---

## 6. 数据存储

### 目录结构（`map/manager.py` 的规范路径）

```
<world>/maps/<planet_id>/              # 主世界地图
├── map.yaml                # MapMetadata（CVT 参数、生成时间、投影、导入溯源）
├── cvt_mesh.json           # CVT 网格（gzip 压缩，主要数据：cell 坐标/邻居/属性）
├── elevation.png           # 16-bit 等距圆柱高度图（渲染 + 外部交换）
├── plates.json             # 板块定义（名称、类型、cell 列表、欧拉极）
├── features.json           # 线性特征（河流折线）
├── temperature.png / precipitation.png / koppen.json / climate_metadata.json
├── climate_monthly.msgpack # N×12 月度场（温度/降水/气压/风）
└── registry.yaml           # 图层依赖追踪（标记哪些下游层需要重算）

<world>/branches/<name>/maps/<planet_id>/    # 分支地图（覆盖主地图，缺省沿继承链向上取）
```

> `layers/geological/` 下的旧地图路径仅作向后兼容 fallback，新数据一律写顶层
> `maps/`。

### 产物管理（重要）

`maps/` 与 `layers/*/derived/` 是「input + 代码 + seed」的**确定性构建产物，不入
git、不走 LFS**（`.gitignore` 已忽略）。发版由
`uv run python scripts/release/publish_world_data.py` 一条命令完成构建 + 打包 +
上传（GitHub Releases 的 `worlds-data` tag），GitHub Pages 从 release 做静态导出。

### 文件大小参考（200k cell，nacrea 实测）

| 文件 | 典型大小 |
|------|----------|
| `cvt_mesh.json`（gzip） | ~32 MB |
| `climate_monthly.msgpack` | ~23 MB |
| `koppen.json` | ~4 MB |
| `plates.json` | ~3 MB |
| `elevation.png`（4096×2048 16-bit） | ~3 MB |
| `features.json` | ~0.1 MB |

---

## 7. 导入外部高度图

地图查看器顶栏的 **⬆ 导入高度图** 按钮（仅 API 模式）接受外部工具的
高度图：16-bit PNG、16-bit TIFF、32-bit float TIFF（自动识别），按当前地图
元数据分辨率重采样后覆盖 `elevation.png` 并重采样 Voronoi 网络。

- 导入会记录溯源到 `map.yaml` 的 `elevation_import` 块（来源格式/分辨率/
  是否重采样/备注/时间），并在 `registry.yaml` 把 elevation 标为 `imported`、
  下游图层（气候等）标为 stale——导入后请按提示重建气候层。
- **导入的高度图不含板块构造数据**：plates 图层为空（左栏有提示），
  boundaries 图层回落到地壳底色。需要构造叙事时，用 geography 锚定 +
  管线生成，或把导入图当作"最终高程"接受无板块设定。
- **earth 验证世界是特例**：它的真实板块 + 地壳由专用脚本导入（PB2002 板块 +
  ETOPO1 水深判大陆架），不依赖上面的通用导入按钮：
  ```bash
  uv run python scripts/earth/import_earth_elevation.py \
      --output-dir <world>/maps/planet_earth --skip-download
  uv run python scripts/earth/import_earth_tectonics.py \
      --output-dir <world>/maps/planet_earth
  ```
  之后在 `terrain_config.yaml` 设 `elevation_source: imported`，地质引擎就会
  跳过合成管线、不覆盖已导入数据。
- 想"形状手绘、地貌物理补全"的中间路线：顶栏"⬆ 锚定灰度图"上传灰度概率图
  （存 `geography_raster.png`，白=陆/黑=海/中灰=中立），下次生成时与
  geography.yaml 叠加（`raster_weight` 调和）——形状是你的，地貌细节是物理的。
- 静态模式（GitHub Pages）为只读，按钮禁用。

### 锚定灰度图格式规范

**投影与朝向**：等距圆柱（equirectangular）。左缘 = −180°、右缘 = +180°、
上缘 = 90°N、下缘 = 90°S；像素中心按 `x = (lon+180)/360·W`、
`y = (90−lat)/180·H` 取用。±180° 缝合线两侧由作者自行保持连续
（管线按经度逐 cell 取像素，不会自动 wrap 混合）。

**分辨率**：任意。管线按每个 CVT cell 的中心**最近像素**采样，不重采样；
推荐 ≥ 2048×1024（低于网格密度时相邻 cell 共享像素，形状呈块状）。

**支持格式**（魔数自动识别）：

| 格式 | 说明 |
|------|------|
| 16-bit PNG（推荐） | 全精度 65536 级 |
| 16-bit TIFF（含 BigTIFF） | Gaea / World Machine 原生导出 |
| 32-bit float TIFF | 值应在 [0,1]；越界自动 min-max 归一 |
| 8-bit PNG | 接受但仅 256 级精度（日志警告） |
| 多通道 | 取第一通道（日志警告） |

**灰度语义**（归一后 0–1 → 偏置 −1–+1）：

| 灰度 | 偏置 | 语义 |
|------|------|------|
| 1.0（白） | +1 | 最强陆地锚定 |
| 0.5（中灰） | 0 | 中立，交给 feature/fBm |
| 0.0（黑） | −1 | 最强海洋锚定（抑制抬升+基准服从） |

**存储与生效条件**：上传后统一重编码为 16-bit PNG 存
`layers/geological/input/geography_raster.png`；仅当世界存在
`geography.yaml` 时生效（features 可为空列表，文件须在）；混合权重
`raster_weight` 写在 geography.yaml（默认 1.0，0=禁用）；带 `?branch=` 上传
存分支 geological input，未上传分支沿继承链向上取。

---

## 8. 常见问题

**Q: 生成太慢了，能加速吗？**

A: 降低 `num_nodes` 是最有效的加速手段（50k 约为 200k 的 1/4 计算量），适合快速
迭代；确定满意的配置后再用 200k 生成最终版本。性能剖析工作流见
[design/profiling.md](../design/profiling.md)。

**Q: 大陆形状太圆/太规则？**

A: 用 geography.yaml 锚定调整海陆分布（见 5.3），或上传锚定灰度图（见第 7 节）；
增大 `noise_persistence` 让海岸线更曲折。

**Q: 河流没有流入海洋？**

A: 河流算法保证水从高处流向低处并最终到达海洋或内陆洼地（内流湖是合法终点）。
「河流消失」通常是内陆盆地（低于海平面但不与海洋连通）——这是真实地貌
（里海型），不是 bug。

**Q: 极地地区看起来不对？**

A: 等距圆柱投影在极地附近有水平拉伸。管线在球面 CVT 网格上运行，极地 cell 的
面积和邻居关系是正确的——切到 Mollweide（等积）或 3D 球面视图查看真实比例。

**Q: 导出的高度图和查看器里看到的不一样？**

A: 查看器的「地形」着色包含山体阴影（hillshading），导出的 PNG 是纯海拔数据。

**Q: `num_nodes` 设太大（> 500K）会怎样？**

A: 生成时间与后续阶段计算量与 cell 数成正比；cvt_mesh 文件体积与前端解析内存
也随之膨胀（JS 堆 ~3–4× 原始体积是实际上限）。建议日常 200k。

**Q: 修改了 geography.yaml 需要重建整个地图吗？**

A: 不需要 `--force`——子阶段缓存按输入指纹自动失效，只重跑地理锚定之后的相位。
`--force` 只用于强制全量重建。

---

## 参考资料

- **技术论文**: Cortial et al. 2019 *Procedural Tectonic Planets*（解读见
  [geological-pipeline.md 附录](../design/pipelines/geological-pipeline.md)）
- **科普视频**: [Fractal Philosophy — *Maps: Fractals, Tectonics and the Fourth Dimension*](https://www.bilibili.com/video/BV1n2i7BrEmq)（B站中字）— 分形几何、板块动力学与高维空间映射的可视化讲解
