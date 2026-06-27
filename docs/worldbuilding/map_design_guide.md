# 地图设计指导

本文档为架空世界的地图设计提供科学指导和工作流建议。

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

- **行星参数约束**：行星的 `water_coverage`（水圈）决定了海陆比例；`num_plates`（岩石圈）决定板块数量
- **恒星光照约束**：宜居带位置影响温度分布（后续气候层）
- **自转/倾角约束**：`axial_tilt_deg` 影响季节性和纬度温差

### 自底向上

遵循层级架构的设计哲学：

```
天文学参数 → 地质地图 → 气候推演 → 生态分布 → 文明布局
```

先确定海陆分布和板块构造，再推演气候和生态，最后设定文明要素。

## 地质层地图设计

### 海陆分布

- **水陆比例**：参考 `hydrosphere.water_coverage`（地球约 71%）
- **大陆形状**：自然大陆有不规则的海岸线和大陆架
- **大陆位置**：赤道附近大陆更宽，高纬度地区更窄碎

### 板块构造

> 参考：[USGS Plate Tectonics](https://pubs.usgs.gov/gip/dynamic/tectonic.html)；[Azgaar](https://github.com/Azgaar/Fantasy-Map-Generator) 的 plate system

- **板块数量**：参考 `lithosphere.num_plates`（地球约 15 个）
- **板块类型**：
  - 大洋板块（oceanic）：低海拔、高密度
  - 大陆板块（continental）：高海拔、低密度
  - 混合板块（mixed）：含大陆和海洋部分
- **板块边界**：
  - 汇聚边界 → 山脉、海沟
  - 离散边界 → 洋中脊、裂谷
  - 转换边界 → 断层线

### 地形特征

- **山脉**：通常位于板块碰撞带，呈线性分布
- **平原**：大陆内部或板块中心区域
- **高原**：大面积隆起，可能与地幔柱有关
- **海沟**：大洋板块俯冲带
- **火山**：板块边界或热点

## 气候层预期

地图编辑完成后，气候引擎将基于以下因素自动推演：

- **纬度**：赤道热、极地冷
- **海拔**：每升高 1000m 降温约 6.5°C
- **海陆分布**：海洋性气候 vs 大陆性气候
- **洋流**：暖流增温增湿，寒流降温减湿
- **风带**：信风、西风带、极地东风

柯本气候分类将自动映射到每个 Voronoi cell。

## 生态层预期

基于温度和降水，[Whittaker 生物群系分类](https://en.wikipedia.org/wiki/Biome#Whittaker)（参考 [Azgaar](https://github.com/Azgaar/Fantasy-Map-Generator) 的 biome 分配逻辑）：

| 温度 | 高降水 | 中降水 | 低降水 |
|------|--------|--------|--------|
| 热带 | 热带雨林 | 热带季雨林 | 热带草原 |
| 温带 | 温带雨林 | 温带森林 | 温带草原 |
| 寒带 | 针叶林 | 苔原 | 极地冰盖 |

## 文明层指导

> 参考：[Paradox EU4](https://eu4.paradoxwikis.com/Map_modding) 的 province/development 系统；[CK3](https://ck3.paradoxwikis.com/Map_modding) 的 holding/county 系统

文明布局受地理约束：

### 城市选址

优先选择以下地理条件的 Voronoi cell：

- **河流交汇处**：交通便利、水源充足
- **海岸港湾**：贸易港口
- **平原中心**：农业腹地
- **山口/关隘**：军事要塞

### 政治边界

- 自然边界：山脉、河流、海岸
- 文化边界：语言、宗教分界线
- 历史边界：战争、条约结果

### 资源分布

- 矿产：山脉附近（金属矿）
- 农田：平原、河谷（冲积平原）
- 渔场：大陆架浅海区域
- 木材：森林覆盖区域

## 工具使用建议

### 程序化生成

1. 先用 "🌍 生成地形" 创建基础地形
2. 调整参数（大陆数、山脉度、板块数）多次生成，直到满意
3. 生成结果会自动创建 Voronoi 网络和板块分配

### 手动编辑

1. 使用升起/降低工具调整局部地形
2. 使用平滑工具消除突兀的高程变化
3. 使用平坦工具创建平原和高原
4. 编辑后记得保存

### 迭代优化

1. 查看板块分配是否合理
2. 检查板块边界是否对应山脉位置
3. 确认海陆比例与行星参数一致
4. 反复调整直到地质设定自洽
