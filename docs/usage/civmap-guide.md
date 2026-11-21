# 文明地图（CivMap）使用指南

本文档介绍 dreamulator 文明地图的使用方法。文明地图用于在真实地球行政区划底图上绘制架空国家的疆界。

## 概述

文明地图是 dreamulator 的第三个地图子系统（另外两个是程序化行星地图和 3D 恒星系可视化器），专门为**文明层分支**设计：

- **程序化行星地图** (`src/dreamulator/map/`)：为架空行星生成地形、Voronoi 网格
- **文明地图** (`src/dreamulator/civmap/`)：在真实地球行政区划上涂色，绘制架空国家疆界

两者的数据模型完全不同（Voronoi 网格 vs GeoJSON 多边形），但在分支继承体系中共存。

## 前置准备

### 1. 下载底图数据

首次使用前需要下载真实世界的行政区划 GeoJSON 数据：

```bash
# 默认下载 Natural Earth 的 ADM0（国界）和 ADM1（省/州级）
uv run python scripts/dev/prepare_civmap_data.py

# 可选：只下载特定层级
uv run python scripts/dev/prepare_civmap_data.py --level adm0
uv run python scripts/dev/prepare_civmap_data.py --level adm0 adm1

# 可选：使用 geoBoundaries 数据（CC BY 4.0，更精细）
uv run python scripts/dev/prepare_civmap_data.py --source geoboundaries --level adm1

# 可选：简化几何以减小文件体积（需要 geopandas）
uv run python scripts/dev/prepare_civmap_data.py --simplify 0.01
```

数据默认存储在 `data/worlds/earth/maps/earth_reference/`，约 45 MB，不纳入 Git。旧的 `layers/geological/input/maps/earth_reference/` 也可读取。同一个世界的分支共享这份参考数据。

### 2. 创建文明层分支

文明地图需要一个在文明层（civilization）分叉的分支：

```bash
uv run dreamulator branch create earth my-history --at civilization
```

## 进入文明地图

### 方式一：从世界详情页

在世界详情页选中要浏览的分支，打开「文明」页签，点击文档前的「打开文明地图」。地图在独立页面显示，世界详情页不加载行政边界。

### 方式二：直接输入 URL

```
http://localhost:8000/worlds/<世界名>/civmap/<分支名>
```

例如：`http://localhost:8000/worlds/earth/civmap/ERE-if`

> 端口：`dreamulator serve`（API + 前端一体）是 **8000**；前端独立开发模式
> （`cd frontend && npm run dev`）是 Vite 的 **5173**，二者同一套路由。
> 开发模式使用 BrowserRouter，URL 中**不需要** `#`。

## 基本操作

### 界面布局

桌面上，左栏管理绘图工具、架空国家和时间快照，地图位于中间，右栏显示指向的省区及统计。窄屏时，点页首的「工具栏」打开左栏。
页首的返回按钮会回到原分支的「文明」页签。本机打开地图时默认锁定编辑，仍可平移、缩放和切换边界。需要修改时，点击「编辑已锁定」解锁；完成后点击「编辑中」重新锁定。静态站只能查看已发布的数据，不能解锁编辑。

地图默认只显示行政边界和领土。需要地理背景时，可以打开页首的「背景底图」。背景加载失败时会自动关闭，不影响查看或编辑领土。
如果页面提示没有省级边界，请按前置步骤准备 ADM1 数据，再点「重新加载」。静态站只能读取已发布的边界；缺少数据时需要重新导出并发布站点。

### 创建架空国家

1. 点击左栏国家区域的 **「+ 新增」**
2. 系统自动分配颜色
3. 点击国家旁的 ✏️ 按钮编辑：
   - **名称**：架空国家名（如 "东罗马帝国"）
   - **颜色**：地图填色（取色器或 hex 输入）
   - **描述**：简要说明

### 创建时间快照

时间快照代表一个历史时间点（如 "公元 500 年"），每个快照有独立的领土分配。

1. 点击左栏快照区域的 **「+ 新增」**
2. 点击快照旁的 ✏️ 按钮编辑：
   - **年份**：历史年份（可选）
   - **描述**：如 "查士丁尼一世收复意大利"

> ⚠️ 必须先创建至少一个快照才能开始涂色。

### 涂色

1. 从调色板中选择一个架空国家（高亮显示）
2. 解锁编辑后，选择「涂色」或「擦除」。
3. 在地图上点击省区进行涂色

误操作后，点击页首的「撤销」，也可以按 `Ctrl+Z`（在 macOS 上按 `⌘Z`）。每次撤销恢复一次点击涉及的全部省区，包括国界层级的批量涂色或擦除。当前快照最多可撤销最近 50 次已保存的领土修改；刷新或离开编辑器后不会保留撤销记录。国家和快照本身的编辑不在撤销范围内。

### 层级切换

文明地图支持两个层级：

| 层级 | 数据源 | 涂色粒度 | 视觉 |
|------|--------|---------|------|
| **省/州** (ADM1) | 4596 个省级区域 | 单个省区 | 省界细分 |
| **国界** (ADM0) | 258 个国家 | 整个国家（批量操作） | 国界粗线叠加 |

**关键设计**：
- 所有领土分配始终以**省级**粒度存储
- 国界层级只是**聚合视图**：国家的颜色由其省份决定
- 切换层级时着色保持一致，只是选择粒度变化
- 国界层级下涂色 = 一次性涂该国所有省份

### 查看信息

将鼠标悬停在地图上的省区/国家上，右栏会显示：
- 名称和类型
- 所属架空国家（如有）
- 国界层级下：已涂色省份数/总省份数

## 数据存储

文明地图的数据以 YAML 格式存储在分支的文明层输入目录中：

```
data/worlds/earth/branches/<分支名>/
└── layers/civilization/input/
    ├── civ_territory.yaml    # 架空国家 + 快照 + 领土分配
    └── ...（其他文明层文件）
```

### civ_territory.yaml 格式

```yaml
countries:
- id: ere_byzantine
  name: 东罗马帝国
  color: '#8B4513'
  description: 延续千年的罗马帝国

snapshots:
- id: snap_1341
  year: 1341
  description: 内战结束，帝国中兴

active_snapshot: snap_1341

assignments:
  snap_1341:
  - province_id: GRC-2884    # 希腊 Attiki（雅典）
    country_id: ere_byzantine
  - province_id: GRC-2990    # 希腊 Kriti（克里特）
    country_id: ere_byzantine
```

该文件可以直接用文本编辑器修改，也可以通过前端界面操作。

## API 端点

所有端点支持 `?branch=` 查询参数。

### 参考数据（只读）

| 端点 | 说明 |
|------|------|
| `GET /api/worlds/{world}/civmap/boundaries/adm0` | 国界 GeoJSON |
| `GET /api/worlds/{world}/civmap/boundaries/adm1` | 省界 GeoJSON |
| `GET /api/worlds/{world}/civmap/boundaries-mapping` | 国家→省份映射 |
| `GET /api/worlds/{world}/civmap/available-levels` | 可用层级列表 |

### 领土数据（读写）

| 端点 | 说明 |
|------|------|
| `GET /api/worlds/{world}/civmap/territory` | 完整领土数据 |
| `POST /api/worlds/{world}/civmap/territory` | 替换领土数据 |
| `GET/POST /api/worlds/{world}/civmap/countries` | 架空国家 CRUD |
| `DELETE /api/worlds/{world}/civmap/countries/{id}` | 删除国家 |
| `GET/POST /api/worlds/{world}/civmap/snapshots` | 时间快照 CRUD |
| `PATCH /api/worlds/{world}/civmap/snapshots/{id}` | 更新快照元数据 |
| `DELETE /api/worlds/{world}/civmap/snapshots/{id}` | 删除快照 |
| `GET/PATCH/PUT .../snapshots/{id}/assignments` | 领土分配 CRUD |

## 静态模式（GitHub Pages）

文明地图支持静态只读模式。运行 `npm run export` 会将 GeoJSON、映射和领土数据导出到 `frontend/public/data/`。

在静态模式下：
- 地图正常渲染，可浏览和切换层级/快照
- 涂色、创建国家/快照等写操作被禁用
- 页面顶部显示「只读」标记

## 数据源

| 数据源 | 许可 | 精度 | 说明 |
|--------|------|------|------|
| Natural Earth | 公共领域 | 省/州级 | 默认数据源，~4600 个省区 |
| geoBoundaries | CC BY 4.0 | 区/县级 | 更精细，~100 万条边界 |
| GADM v4.1 | 非商业 | 村级 | 最精细，需单独下载 |
