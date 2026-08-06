# 地图设计指导

本文档为架空世界的地图设计提供科学指导与工作流建议（CVT 管线时代版，
2026-08 重写；旧版"内置编辑器"工作流已随 ADR-001 废弃）。

操作层面的完整流程见 [`../usage/map-workflow.md`](../usage/map-workflow.md)；
算法原理见 [`../design/terrain-pipeline.md`](../design/terrain-pipeline.md)。

## 参考资源

| 资源 | 类型 | 适用场景 |
|------|------|----------|
| [Azgaar's Fantasy Map Generator](https://azgaar.github.io/Fantasy-Map-Generator/) | 在线工具 | 快速原型验证、Voronoi 地图实验 |
| [Red Blob Games — Voronoi Maps](https://www.redblobgames.com/x/2022-voronoi-maps-tutorial/) | 技术教程 | Voronoi 地图生成原理 |
| [Red Blob Games — Terrain Generation](https://www.redblobgames.com/maps/terrain/) | 技术教程 | 程序化地形生成方法论 |
| [EU4 Map Modding Wiki](https://eu4.paradoxwikis.com/Map_modding) | Modding 文档 | Paradox 风格省份地图设计 |
| [CK3 Map Modding Wiki](https://ck3.paradoxwikis.com/Map_modding) | Modding 文档 | 高度图 + 地形纹理设计 |
| [Whittaker Biome Classification](https://en.wikipedia.org/wiki/Biome#Whittaker) | 科学分类 | 温度-降水-生态群系映射 |
| [Plate Tectonics (USGS)](https://pubs.usgs.gov/gip/dynamic/tectonic.html) | 科学参考 | 板块构造理论 |

## 设计原则

### 物理一致性

地图数据应与天文学和地质学层保持一致：

- **行星参数约束**：`planets.yaml` 的半径/重力/水圈设定决定高程标度与海陆预算；
  板块数量由 `terrain_config.yaml: num_plates` 给出（地球主板块 ~15）
- **恒星光照约束**：宜居带位置与光度影响温度分布（气候层消费）
- **自转/倾角约束**：`axial_tilt_deg` 与自转周期影响季节、纬度温差与
  Hadley 胞宽度（慢自转行星环流圈显著加宽，见
  `../knowledge/climatology/atmospheric_circulation.md`）

### 自底向上

```
天文学参数 → 地质地图（geography 锚定 + 构造演化）→ 气候推演 → 生态分布 → 文明布局
```

先确定海陆分布和板块构造，再推演气候和生态，最后设定文明要素。

## 地质层地图设计

### 海陆分布：配置化锚定

当前管线的"画笔"是 `geography.yaml` 的 feature 列表（椭圆余弦核偏置场），
而非逐像素绘制：

- **水陆比例**：`land_fraction_target`（地球 ~0.29 露出陆地）
- **大陆/海盆/裂谷/地峡**：`features` 的 kind（continent / ocean_basin /
  rift_sea / isthmus / shallow_sea / archipelago / plateau）+ lon/lat/radius/
  strength/elongation/bearing
- **半球不对称**：`hemisphere_land_bias`
- 锚定只钉地壳类型；构造演化后可按 `reapply_after_tectonics` 重锚。
  **已知限制**：锚定不钉高程（汇聚抬升可盖过锚定裂谷）、浅海深度控制待补——
  见 `../design/roadmap.md` 功能性 #9 与
  `private/plans/heightmap-import-vs-geography-config.md`

需要"手绘形状"时，走高度图导入模式（外部灰度图 → 偏置场或最终高程），
同一份计划文档给出了双模式谱系。

### 板块构造

> 参考：[USGS Plate Tectonics](https://pubs.usgs.gov/gip/dynamic/tectonic.html)；
> Cortial et al. (2019)（管线实现，见 `../knowledge/geology/plate_tectonics.md`）

- **板块数量与大小**：偏态分布是真实特征（地球主板块面积 CV≈0.9）——
  管线已内置裂解 + 加权重分区机制，不要追求等大面积
- **板块类型**：oceanic（低海拔、高密度）/ continental（高海拔、低密度）
- **边界地貌组合**：汇聚 → 山脉+海沟（洋壳俯冲侧）；离散 → 洋中脊+裂谷；
  转换 → 断层谷地。岛弧小圆弧会随演化涌现（Frank 1968 机制）

### 地形特征检查单

- 山脉线性分布于碰撞带；高原与地幔柱/古造山带关联
- 海沟仅出现在洋壳俯冲侧（~−7 km 减压，地球海沟 −8~−11 km）
- 热点火山链年龄递变（夏威夷型）；大陆架指数衰减剖面

## 气候层预期

地图定稿后气候引擎自动推演（EBM + 三胞环流 + BFS 水汽 + Köppen，见
`../knowledge/climatology/` 各篇）。设计地图时可预判：

- **纬度**：赤道热、极地冷；**海拔**：~6.5°C/km（热带有效直减率更低，
  当前模型把热带苔原线压低 ~1200 m——已知限制）
- **雨影**：>3000 m 山脉背风侧干旱（安第斯型东西坡分异）
- **洋流**（3A.3 落地后）：西边界暖流增温增湿、东边界寒流降温减湿、
  上升流沿岸干冷
- **临界地理**：窄浅海峡（<200 m）是气候临界态的天然开关——
  冰期海平面、火山岛、沉积都可触发"开/合"跃迁
  （科学机制见 `../knowledge/climatology/ocean_currents.md` §3）

## 生态层预期

基于温度和降水的 Whittaker 群系映射（ecology 引擎未实现，当前为 input 设定；
规划见 `../knowledge/ecology/CLAUDE.md`）：

| 温度 | 高降水 | 中降水 | 低降水 |
|------|--------|--------|--------|
| 热带 | 热带雨林 | 热带季雨林 | 热带草原 |
| 温带 | 温带雨林 | 温带森林 | 温带草原 |
| 寒带 | 针叶林 | 苔原 | 极地冰盖 |

特殊生态位值得为剧情设计：潮间带巨进退带（大潮世界）、雨影荒漠的
refugia（气候振荡期的物种蓄水池）。

## 文明层指导

> 参考：[EU4 province 系统](https://eu4.paradoxwikis.com/Map_modding)；
> 动力学模型见 `../knowledge/sociology/CLAUDE.md`（HANDY/SDT/Tainter）

### 城市选址

优先选择以下地理条件的 cell：河流交汇处（交通+水源）、海岸港湾（贸易）、
平原中心（农业腹地）、山口关隘（军事）。文明起源锚点应与气候带耦合
（季风河谷农业、群岛航海、极地游牧等生态位分化）。

### 政治边界

自然边界（山脉、河流、海岸）> 文化边界（语言、宗教）> 历史边界（战争、条约）。
"曼荼罗式"松散圈层政体适合前现代东南亚型设定。

### 资源分布

矿产近山脉、农田在河谷冲积平原、渔场在大陆架浅海、木材随森林带。

## 命名与呈现（世界内真实感）

- **按"谁命名的"分域选风格**：自然地理用中文意译（大裂谷海、破碎群岛带），
  西方地域用合成词音译，体制/工程用编号功能名（第二留守区、微分一号），
  天体用神话典故——命名本身在做世界观
- **机构化包装**：地图导出为"世界内机构出版物"（附件编号、钢印、落款、
  界内纪年），真实感远高于裸地图
- 详见 `narrative-craft.md` 与 `private/plans/video/leyi-ajax-map-presentation-analysis.md`

## 工作流（CVT 时代）

1. **配置生成**：`dreamulator terrain generate`（或 `build --only geological`），
   编辑 `terrain_config.yaml` + `geography.yaml` 迭代海陆格局
2. **检查**：MapViewer 看板块/边界/高程图层；对照本文检查单
3. **气候联调**：`build --only climate` 后看 Köppen 分布是否符合直觉
4. **可选精细化**：Gaea 局部往返（design/terrain-pipeline.md §13，纸面阶段）
   或高度图导入模式
5. **定稿入库**：地图产物 LFS 入库；定稿才进 `data/worlds/`（提交纪律，
   见 `private/plans/lfs-history-optimization.md`）
