# 3D 恒星系可视化器

前端内置的交互式 3D 恒星系查看器，基于 Three.js（通过 `@react-three/fiber` + `@react-three/drei`），以 **真实天文比例** 渲染恒星、行星、轨道和宜居带。

## 功能概览

- **真实比例渲染**：所有距离以 AU 为单位，天体半径按真实物理尺寸
- **Leader line 标注系统**：十字准星 + 引线 + 文字标签，确保亚像素级天体可定位
- **极端缩放**：从 200 AU 系统全景到 0.001 AU 近距观察
- **宜居带可视化**：半透明绿色环 + 凝结线标记
- **天体信息面板**：点击标签查看详情（光谱类型、温度、质量等）
- **分支感知**：自动加载分支世界的恒星/行星数据
- **静态模式兼容**：GitHub Pages 上完全可用（无需后端）

## 访问方式

在世界详情页（`/worlds/:worldName`）点击 **"3D 视图"** 标签页即可进入。

## 操作指南

| 操作 | 方式 |
|------|------|
| 旋转视角 | 鼠标左键拖拽 |
| 缩放 | 鼠标滚轮 |
| 平移 | 鼠标右键拖拽 |
| 查看天体信息 | 单击标签或天体 |
| 聚焦天体 | **双击**标签或天体 — 镜头平滑飞向该天体并居中 |
| 取消选中 | 点击空白区域 |

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
WorldDetail.tsx  ──useQuery──→  stellar / planets / habitableZones
    ↓
StellarSystemViewer
    ├── allBodies = planets[] + stellar.bodies[]   ← 合并行星 + 卫星/小行星
    ├── positionMap = resolvePositions(stars, allBodies, orbits)
    ├── StarMesh[]        ← stellar.stars[]
    ├── OrbitLine[]       ← stellar.orbits[] + parentPosition
    ├── PlanetMesh[]      ← allBodies + positionMap + declutter
    ├── HabitableZoneRing ← habitableZones
    └── InfoPanel         ← selected body state
```

### 组件职责

#### StellarSystemViewer

主容器组件，负责：
- `<Canvas>` 设置（`logarithmicDepthBuffer`、相机参数、色调映射）
- 场景灯光和背景星场（drei `<Stars>`）
- `<OrbitControls>` 相机控制（minDistance: 0.001 AU, maxDistance: 200 AU）
- **双击聚焦**：`focusTargetRef` + `useFrame` 中 `controls.target.lerp()` 平滑飞向目标天体
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
- 引线长度随选中状态变化（选中 32px / 默认 48px）
- 十字准星为白色细线（Space Engine 风格），选中时略大且更亮
- 支持 subtitle 行（显示光谱类型/温度/行星类型等）
- 单击触发 `onClick`（选中天体），双击触发 `onDoubleClick`（聚焦镜头）

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
| Gaia Primary | 0.00197 | M 型红矮星 |
| Aegis 轨道 | 0.2795 | 宜居带内 |

在 1 AU 距离观察 Sol，视角约 0.53° — 仅约 1 像素。这是物理正确的，Space Engine 和 Universe Sandbox 行为一致。

### 可见性策略

| 技术 | 参考来源 | 作用 |
|------|---------|------|
| Leader line 标注 | Celestia, Space Engine | dot + 引线 + 文字，任意缩放级别可见 |
| 最小 glow 壳（仅恒星） | Universe Sandbox | 0.008 AU 的 additive blending 球体 |
| 外层软光晕 | Space Engine | 2.5× 最小半径的 BackSide 渲染 |
| `logarithmicDepthBuffer` | Three.js best practice | 处理 near=0.00001 / far=5000 的极端比 |
| 极端缩放范围 | Space Engine | 0.001–200 AU，用户可自由 zoom |
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

## 后端 API 端点

3D 视图需要以下 API 端点（均已实现）：

| 端点 | 用途 | 支持分支 |
|------|------|---------|
| `GET /api/worlds/{name}/stellar` | 恒星系数据（input + derived 合并） | ✅ `?branch=` |
| `GET /api/worlds/{name}/planets` | 行星定义列表 | ✅ `?branch=` |
| `GET /api/worlds/{name}/habitable-zones` | 宜居带 + 凝结线数据 | ✅ `?branch=` |

在静态模式下，这些端点由 `frontend/public/data/` 中预导出的 JSON 文件提供（通过 `scripts/export_static.py` 生成）。

## 扩展方向

- **多恒星系统**：当前已支持多星渲染（`stellar.stars[]`），但轨道力学仅处理行星绕单星
- **~~卫星~~**：✅ 已实现 — `StellarSystem.bodies[]` + 层级位置解算 + 标签去重叠
- **时间动画**：轨道运动动画（当前只显示 epoch 位置）
- **大气光谱**：根据大气成分渲染行星大气层颜色
- **表面纹理**：程序化生成行星表面（水/陆/冰分布）
