# 3D 恒星系可视化器（架构）

> 本文是 `frontend/src/viewers/` 恒星系查看器的**架构与设计说明**（文件结构、数据流、
> 真实比例设计、标签去重叠）。操作指南见
> [usage/frontend-3d-viewer.md](../usage/frontend-3d-viewer.md)；球面地球查看器
> （GlobeViewer）的架构在 [pipelines/map-system.md](pipelines/map-system.md)
> 「3D 球面渲染」节。

## 架构

### 文件结构

```
frontend/src/viewers/
├── StellarSystemViewer.tsx    # 主容器：Canvas + 场景组装 + HUD
├── StarMesh.tsx               # 恒星渲染（黑体颜色 + 点光源 + glow）
├── PlanetMesh.tsx             # 行星渲染（类型着色 + 大气层 + glow）
├── OrbitLine.tsx              # 轨道路径（开普勒椭圆）
├── HabitableZoneRing.tsx      # 宜居带环 + 凝结线
├── Label.tsx                  # 标注系统（dot + 引线 + 文字）
├── InfoPanel.tsx              # 选中天体的详情面板
└── utils/
    ├── starColor.ts           # 黑体温度 → RGB 转换
    └── scale.ts               # 单位换算 + 开普勒方程求解
```

### 数据流

```
API / 静态 JSON
    ↓
StellarSystemViewerPage.tsx  ──useQuery──→  systemCatalog（恒星/轨道/天体单一合并源）
    ↓
StellarSystemViewer
    ├── allBodies = planets[] + stellar.bodies[]   ← 合并行星 + 卫星/小行星（按 id 去重，planets 优先）
    ├── positionMap = resolvePositions(stars, allBodies, orbits)
    ├── StarMesh[]        ← stellar.stars[]
    ├── OrbitLine[]       ← stellar.orbits[] + parentPosition
    ├── PlanetMesh[]      ← allBodies + positionMap + declutter
    ├── HabitableZoneRing ← habitableZones
    └── InfoPanel         ← selected body state + catalog 查表（富字段分组）
```

### 组件职责

#### StellarSystemViewer

主容器组件，负责：
- `<Canvas>` 设置（`logarithmicDepthBuffer`、相机参数、色调映射）
- 容器 `h-full` 填满页面 flex 布局的剩余高度（`minHeight: calc(100vh - 140px)`
  兜底——固定 `70vh` 会在高窗口下留出底部空白条）
- 场景灯光和背景星场（drei `<Stars>`）
- `<OrbitControls>` 相机控制（maxDistance: 200 AU；minDistance 动态计算：聚焦天体时 = 1.5 × 天体真实半径，无焦点时 = 0.005 AU）
- **聚焦飞行**：`focusTargetRef` + `useFrame` 中 `controls.target.lerp()` 平滑飞向
  目标天体；`focusDollyRef` 置位时（InfoPanel「聚焦并拉近」按钮）同时把相机
  拉到 ~4× 天体真实半径，吸附容差按半径相对化（小天体精确定位）
- 组装所有子组件
- HUD 覆盖层（视距显示、图例）

#### StarMesh

渲染单颗恒星：
- **真实半径几何体**：`solarRadiiToAU(radius)` → AU
- **黑体颜色**：从有效温度通过 Tanner Helland 算法计算 RGB
- **三层渲染**：真实球体（emissive）+ 最小 glow 壳（additive）+ 外层软光晕
- **点光源**：照亮行星，强度正比于光度

#### PlanetMesh

渲染行星、卫星、小行星等所有非恒星天体：
- **真实半径几何体**：`earthRadiiToAU(radius)` → AU
- **类型着色**：terrestrial（蓝绿）、gas_giant（橙棕）、ice_giant（青蓝）等
- **大气层光晕**：有大气层的行星显示半透明外壳
- **预计算位置**：接收 `position` 属性（由 `resolvePositions` 计算），不自行求解轨道
- **标签可见性**：接收 `labelVisible` 属性（由去重叠算法控制）
- **卫星计数**：接收 `satelliteCount` 属性，在 subtitle 中显示 "· N satellite(s)"

#### Label

屏幕空间标注组件（参考 Space Engine / Celestia 的做法）：
- 使用 drei `<Html>` 将 3D 世界坐标投影到屏幕
- 结构：文字标签 → 引线 → 十字准星
- 引线长度固定 48px（不随选中状态变化，避免标签跳动影响双击定位）
- 十字准星为白色细线（Space Engine 风格），选中时略大且更亮
- 支持 subtitle 行（显示光谱类型/温度/行星类型等）
- 单击触发 `onClick`（选中天体），双击触发 `onDoubleClick`（聚焦镜头）

#### InfoPanel

选中天体的详情面板（右下角 HTML overlay，`w-80` + `max-h-[70vh]` 滚动）。
字段分组参照业界惯例（2026-09-23 调研：NASA Eyes "vital statistics" 的
物理分组与 day/year/moons/atmosphere、Stellarium 天体信息窗的轨道根数 +
物理星历、Celestia HUD 的半径/质量/恒星日/温度/光度读出）：

| 分组 | 字段（有则显示） | 来源 |
|------|-----------------|------|
| 概览 | 类型、质量、半径（R⊕ + km）、反照率、卫星数 | PlanetData + catalog |
| 轨道 | 绕行天体、半长轴（AU + Mkm/km）、偏心率、倾角、公转周期 | catalog `orbit` |
| 物理 | 表面重力（m/s² + g）、磁场（µT） | catalog `physical` |
| 自转与季节 | 自转周期、潮汐锁定、太阳日、轴倾角、年长度、季节长度、极圈纬度 | catalog `derived` |
| 大气与水文 | 气压、温室增温、成分 top-3、水覆盖率、盐度、平均海深 | catalog `atmosphere`/`hydrosphere` |
| 辐照与温度 | 恒星辐照（W/m² + ×Earth）、平衡温度、宜居带归属 | catalog `derived` |
| 岩石圈 | 板块构造、板块数、火山活动 | catalog `lithosphere` |
| 🌍 地形数据 | 海陆比、面积、高程范围、板块/网格数（折叠） | CVT mesh |
| 动作 | 🎯 聚焦并拉近 / 🌐 3D 球面 / 🗺️ 2D 地图 | — |

恒星面板：光谱型、温度、半径、光度、质量 + 演化分组（年龄、主序寿命、
演化进度）+ 宜居带分组（范围、中心）。

#### 工具模块

**`utils/starColor.ts`**：
- `temperatureToColor(K)` — Tanner Helland 黑体辐射算法，~30 行
- `luminosityToGlowIntensity(L)` — 对数映射到 [0.5, 3.0]

**`utils/scale.ts`**：
- `solarRadiiToAU(R☉)` — 太阳半径 → AU（× 696340 / 149597870.7）
- `earthRadiiToAU(R⊕)` — 地球半径 → AU（× 6371 / 149597870.7）
- `MIN_VISUAL_RADIUS_AU` — 0.008 AU 最小可见半径
- `computeOrbitalPosition(elements)` — Newton-Raphson 求解开普勒方程
- `computeOrbitPath(elements, segments)` — 生成轨道路径点

## 真实比例设计说明

### 为什么选择真实比例

早期版本使用对数距离缩放（`log10(1 + au × 10) × 8`）和平方根半径缩放。这虽然让所有天体在同一视图中可见，但严重扭曲了相对关系：
- 0.28 AU 的轨道和 1.0 AU 的轨道看起来差距不大
- 气态巨行星和类地行星的大小关系失真

改为真实比例后，用户可以通过缩放自由探索真实的尺度关系。

### 尺度参考

| 对象 | 半径 (AU) | 说明 |
|------|----------|------|
| Sol | 0.00465 | 696,340 km |
| Earth | 0.0000426 | 6,371 km |
| Jupiter | 0.000477 | 71,492 km |
| Earth 轨道 | 1.0 | 149,597,871 km |
| Ignis | 0.00197 | M 型红矮星 |
| Aegis 轨道 | 0.2795 | 宜居带内 |

在 1 AU 距离观察 Sol，视角约 0.53° — 仅约 1 像素。这是物理正确的，Space Engine 和 Universe Sandbox 行为一致。

### 可见性策略

| 技术 | 参考来源 | 作用 |
|------|---------|------|
| Leader line 标注 | Celestia, Space Engine | dot + 引线 + 文字，任意缩放级别可见 |
| 最小 glow 壳（仅恒星） | Universe Sandbox | 0.008 AU 的 additive blending 球体 |
| 外层软光晕 | Space Engine | 2.5× 最小半径的 BackSide 渲染 |
| `logarithmicDepthBuffer` | Three.js best practice | 处理 near=0.00001 / far=5000 的极端比 |
| 动态缩放范围 | Space Engine | 1.5× 天体半径 – 200 AU，minDistance 随聚焦目标自适应 |
| 视距 HUD | Space Engine | 实时显示当前观察距离（AU/km 自适应） |
| 标签去重叠 | Space Engine, Universe Sandbox | 角大小阈值隐藏子天体标签，父天体显示聚合计数 |

## 卫星与层级轨道

### 数据模型

卫星（月球、小行星等）定义在天文学层的 `stellar.yaml` 中，与行星的地质层分离：

- **`StellarSystem.orbits[]`**：所有轨道力学数据（行星绕恒星、卫星绕行星），通过 `parent_id` 建立层级关系
- **`StellarSystem.bodies[]`**：非恒星天体的物理属性（`OrbitingBody` 模型）
- **`Planet.satellite_ids`**：地质层中的引用列表，指向天文学层的卫星 ID

### 单位归一化

`OrbitingBody` 使用适合小球体的单位（`mass_earth`、`radius_km`），而前端 `PlanetMesh` 期望地球单位（`mass` M⊕、`radius` R⊕）。API 端点和静态导出脚本在返回数据前进行归一化：

| 原始字段 | 归一化字段 | 换算 |
|----------|-----------|------|
| `mass_earth` | `mass` | 直接使用（已是 M⊕） |
| `radius_km` | `radius` | ÷ 6371.0 km → R⊕ |
| `body_type` | `planet_type` | 字段重命名 |
| orbit `parent_id` | `orbits` | 从轨道表查找 |

### 层级位置解算

`resolvePositions()` 使用递归算法计算所有天体的绝对 3D 位置：

1. **种子**：恒星位置（来自 `star.position`，通常为 `[0, 0, 0]`）
2. **递归**：对每个天体，先递归解算父天体位置，再叠加 `computeOrbitalPosition()` 的相对偏移
3. **记忆化**：`positions: Map<string, Vec3>` 缓存已解算的位置，避免重复计算
4. **循环检测**：`visited: Set<string>` 防止循环引用

```
star_sol [0, 0, 0]
  └── planet_earth = star_pos + earth_orbit ≈ [−0.18, 0, 0.97] AU
        └── satellite_moon = earth_pos + moon_orbit ≈ [−0.18, 0.0002, 0.97] AU
```

### OrbitLine 父天体平移

轨道线路径由 `computeOrbitPath()` 在原点周围生成。对于绕行星运行的卫星，整个路径需要平移到父天体的绝对位置：

```tsx
// OrbitLine.tsx
const path = computeOrbitPath(orbit, 128)
if (parentPosition) {
  return path.map(([x, y, z]) => [
    x + parentPosition[0], y + parentPosition[1], z + parentPosition[2],
  ])
}
```

## 标签去重叠（Label Decluttering）

### 问题

真实比例下，地月距离（0.00257 AU）远小于日地距离（1.0 AU）。在系统尺度观察时，月球标签与地球标签在屏幕上几乎重合，难以点击。

### 方案

采用 **角大小阈值** 方案（参考 Space Engine / Universe Sandbox）：

每帧计算每个子天体（卫星）相对于父天体的角大小。当角大小低于阈值时，隐藏子天体标签，在父天体 subtitle 中显示卫星计数。

```
angularSize = orbit.semi_major_axis_au / cameraDistanceToParent
```

| 缩放级别 | 地月角大小 | 行为 |
|---------|-----------|------|
| 系统全景（~2 AU） | ~0.001 rad | 月球标签隐藏，地球显示 "· 1 satellite" |
| 中等距离（~0.1 AU） | ~0.026 rad | 月球标签仍隐藏 |
| 近距离（~0.05 AU） | ~0.051 rad | 月球标签显示（超过阈值 0.04） |

### 实现细节

- **阈值**：`DECLUTTER_THRESHOLD = 0.04` rad（约 2.3°，50° FOV 的 ~4.6%）
- **位置**：Scene 组件内的 `useFrame` 钩子，每帧计算
- **性能**：使用 ref 比较（`prevVisRef`），仅在可见性状态实际变化时调用 `setState`，避免不必要的重渲染
- **聚合标签**：父天体 subtitle 动态显示 `N satellite(s)` 计数，无论子标签是否可见

### 各引擎对比

| 引擎 | 去重叠方案 |
|------|-----------|
| Space Engine | 层级 LOD + 信息面板卫星列表 |
| Universe Sandbox | 像素距离裁剪 |
| Celestia | 视星等过滤 |
| dreamulator | 角大小阈值 + 聚合 subtitle |

## 天体表面纹理（Route C）

有地图数据的天体在球面上显示真实地形着色（取代 `PlanetMesh` 的程序色）：

`StellarSystemViewerPage` 批量加载各天体的 `elevation.png`（16 位归一化高程）→
`generatePlanetTexture`（`imageCodec.ts`）按自适应高程 LUT 降采样烘焙为
equirectangular DataTexture → `PlanetMesh.terrainTexture`。

配色由 `palettes.json` 单一事实源给出，**按天体有无水面分两套**（判别 =
catalog body 的 `hydrosphere.water_coverage`，缺省或 <0.5% = 无水）：

- `adaptive_terrain` — NOAA ETOPO1 海洋 + ESRI Natural Earth 陆地混合板
  （水面世界：Earth、nacrea 各行星）；
- `adaptive_terrain_land` — 无水高程板（干旱色调，基准面以下为深盆地而非
  海洋蓝；Mars / Moon / Venus / Titan——2026-09-23 修复：此前全部天体共用
  ETOPO 板，Hellas 盆地/月海等低地被染成海洋蓝）。

## 后端 API 端点

3D 视图需要以下 API 端点（均已实现）：

| 端点 | 用途 | 支持分支 |
|------|------|---------|
| `GET /api/worlds/{name}/stellar` | 恒星系数据（input + derived 合并） | ✅ `?branch=` |
| `GET /api/worlds/{name}/planets` | 行星定义列表 | ✅ `?branch=` |
| `GET /api/worlds/{name}/habitable-zones` | 宜居带 + 凝结线数据 | ✅ `?branch=` |

在静态模式下，这些端点由 `frontend/public/data/` 中预导出的 JSON 文件提供（通过 `scripts/release/export_static.py` 生成）。

## 选中 / 聚焦与 URL 状态同步

- **单击** = 选中天体（弹 InfoPanel）+ 镜头飞向居中；选中态写入 URL 的
  `?focus=<body_id>`（`replace` 不污染历史），取消选中则删除——刷新/分享
  链接可回到同一聚焦视野（`?focus=` 同时驱动 Scene 的自动聚焦 effect，
  恒星 id 也合法）。
- **双击** = 立即居中（不改变缩放距离）；与单击的飞行同路径
  （`focusTargetRef`）。
- **InfoPanel 🎯 按钮** = 居中 + 拉近（`focusDollyRef` → 相机 lerp 到
  ~4× 天体真实半径），替代滚轮从系统尺度逐级缩放。
- 页首天体下拉以 optgroup 列出恒星与全部天体；选中项始终与 `?focus=`
  一致，且**所有条目统一为聚焦并拉近**（`focusRequest` 命令式请求 →
  `focusBody(id, dolly=true)`，与 InfoPanel 按钮同路径）；🌐 后缀仅标记
  有地图数据，进入球面/地图走 InfoPanel 按钮。

## 角落控件候选清单（设计盘点，未实现）

参照 Celestia / Stellarium / NASA Eyes / Space Engine 的常用角落控件盘点，
实现优先级待议（与「时间动画」扩展方向强相关者依赖时间系统）：

| 候选控件 | 参照 | 依赖 | 备注 |
|---------|------|------|------|
| 时间控制条（播放/暂停/倍速/日期） | NASA Eyes、Celestia | 时间动画 | 天体轨道运动（现仅 epoch 位置）|
| 回全景 / 回主星按钮 | Celestia（GoTo）、NASA Eyes | 无 | 一键回到系统概览或恒星 |
| 轨道线开关 | Celestia、Stellarium | 无 | 密集系统（卫星/小行星）降噪 |
| 标签开关 / 阈值滑杆 | Space Engine、Stellarium | 无 | 标签全隐藏或调整去重叠阈值 |
| 宜居带/凝结线开关 | — | 无 | 现仅图例，无开关 |
| 黄道网格 / 天球坐标网格 | Stellarium、Celestia | 无 | 轨道倾角的直观参照 |
| 天体目录/搜索面板 | Celestia Solar Browser、Stellarium 搜索 | 无 | 大系统（太阳系 16+ 天体）导航 |
| 截图导出 | Stellarium、Celestia | 无 | Canvas `toDataURL` 即可 |
| 全屏切换 | 通用 | 无 | 浏览器 F11 之外的应用内按钮 |
| 视距标尺（AU 比例尺） | NASA Eyes | 无 | 现有视距 HUD 的图形化 |

## 扩展方向

- **多恒星系统**：当前已支持多星渲染（`stellar.stars[]`），但轨道力学仅处理行星绕单星
- **~~卫星~~**：✅ 已实现 — `StellarSystem.bodies[]` + 层级位置解算 + 标签去重叠
- **时间动画**：轨道运动动画（当前只显示 epoch 位置）；也是时间控制条控件的前置
- **大气光谱**：根据大气成分渲染行星大气层颜色
- **~~表面纹理~~**：✅ 已实现（Route C，见「天体表面纹理」节）——真实高程
  烘焙 + 水/无水双配色板；程序化水/陆/冰分布不再是方向
