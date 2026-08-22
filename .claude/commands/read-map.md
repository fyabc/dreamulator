---
description: 用视觉模型 + 数据交叉校验读取世界地图图层，抽取海陆/气候/生态/文明结构。用于「设定 vs 地图」审计、geography 重写、ai civ 文明锚点核查。
---

# read-map — 地图结构的双路抽取

> 目的：把「看地图」变成可复现的流程。**视觉路**给形状/拓扑/位置，**数据路**给面积/占比/连通性，
> 两路交叉后才落笔。单一来源原则：数值以 cvt_mesh 为准，视觉只用于定性。

## 前置

1. **必须用带视觉能力的模型**。纯文本模型读图返回 `[Unsupported Image]`——若当前模型不支持，
   先提醒用户 `/model` 切换，再继续。
2. 图层来源（优先级）：
   1. `dreamulator export layers <world> --planet <id>`（headless 直出，含 30° 经纬网；CLI 待建，见下）
   2. `data/worlds/<w>/maps/<planet>/`：elevation.png / temperature.png / precipitation.png（build 已产出）
   3. 用户手动截图（如 `private/tmp/images/`）
3. 中文文件名在 Windows 下会因控制台编码（gbk）崩脚本——先复制成 ASCII 名再处理。

## 第 1 步：投影与坐标换算

等距圆柱（equirectangular）：`lon = (x/W − 0.5)×360`，`lat = (0.5 − y/H)×180`。
导出图**必须带 30° 经纬网**（视觉定位的唯一锚）。前端截图通常有网格；自建导出时加 `--grid`。

## 第 2 步：视觉路（定性）

读图只描述：大陆轮廓与连通性、内海 vs 海峡、岛弧、裂谷走向、山系位置。
**不目测面积/百分比/精确坐标**——那些是数据路的活。

## 第 3 步：数据路（定量）

对 `cvt_mesh.json` 做连通分量 + 面积加权统计。核心脚本模式（可存 /tmp 运行，
注意 `sys.stdout` 包 UTF-8 防 gbk 崩）：

```python
import json, numpy as np, io, sys
from collections import deque
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
cells = json.load(open(MESH, encoding='utf-8'))['cells']
elev = np.array([c['elevation'] for c in cells]); is_land = elev >= 0
area = np.array([c['area_km2'] for c in cells]); lon = np.array([c['lon'] for c in cells]); lat = np.array([c['lat'] for c in cells])
nbrs = [c['neighbors'] for c in cells]
# BFS 连通分量（陆块 or 从向星点起的开放洋）
def bfs(pred, pool):
    s = next(i for i in range(len(cells)) if pred(i)); comp={s}; q=deque([s])
    while q:
        for nb in nbrs[q.popleft()]:
            if nb in pool and nb not in comp: comp.add(nb); q.append(nb)
    return comp
# 指标：陆地占比、半球/纬度带/经度带占比、top-N 陆块(面积/质心/纬度跨度)、
# 开放洋连通性(封闭内海检测)、命名地貌 bbox 陆地占比
```

必算清单：
- 陆地占比 vs `target_land_fraction`；北半球陆地占比
- top-N 连通陆块（面积、面积加权质心、纬度跨度）→ 对照「世界岛/第二大陆/…」
- 从向星点 BFS 开放洋 → 识别封闭内海（验证「北方内海连通」这类断言）
- 命名地貌 bbox 的陆地/水体占比（验证锚点是否落地）

## 第 4 步：交叉校验与落笔

- 两路一致 → 把**实测值**写进设定文档（只写当前设定，不写历史）。
- 视觉与数据冲突 → **以数据为准**（视觉只可信形状）。
- 数据与设定文档冲突 → 按守护轴产出矛盾/决策记录（`design-notes/00NN-*.md`），
  不静默改设定。

## ai civ 适配

- 对 `civilizations.yaml` 每个 anchor，用 `cell_facts(lon, lat)` 读 koppen / 驯化潜力
  （domesticable_tags）/ 农业 / 宜居图层，逐条核对叙事（如「锚点驯化全黑 → 文明应起源自内陆」）。
- 文明层图层目前无后端 PNG 导出；用数据路直接按 cell 统计（农业核心区/宜居海岸计数）。

## 待建 CLI（设计）

`dreamulator export layers <world> --planet <id> --layers terrain,koppen,biome,agriculture,habitability --grid`
headless 烘焙各层 PNG（复用 `map/export.py::export_equirectangular`；配色与前端共享单一来源
——把 `KOPPEN_COLORS` 等 LUT 抽成后端/前端共读的调色板规格）。理由：免除前端 + 手动截图，
使本 skill、ai civ、CI 审计都能自动取图。
