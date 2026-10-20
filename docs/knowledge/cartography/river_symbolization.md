# 河流符号化（线宽、单双线、流量分级）

地形图上的河流是**符号**，不是按比例的平面：真实河道宽从数米（溪）到
数公里（亚马逊），而图上统一用单线/双线/渐宽线表达。本文汇总线宽规范
与分级依据，供 `carto_render` 的河流渲染对齐业界惯例。

## 线宽规范

**惯例区间：0.1–0.7 mm（图上）**，与比例尺基本无关（符号尺寸围绕人眼
分辨极限 ~0.1 mm 设计，不随比例尺缩放——这就是符号与实地的区别）。

依据：Natural Earth 河流数据集为渲染目的专门分配 `strokeweig` 属性
（值域约 0–5），官方 QGIS 教程（baharmon.github.io 的 Cartography in
QGIS）把它经 data-defined assistant 映射到 **0.1–0.7 mm** 输出线宽；
GRASS 等价用法 `d.vect width_column=strokeweig width_scale=2`。
Geoscience Australia 的国家地形图符号词典同样以 0.1–0.5 mm 量级规定
水系线宽。

换算到我们的图（12 in 幅面 @ 300 DPI，pt = 1/72 in）：
0.1 mm = 0.28 pt，0.7 mm = 1.98 pt。**本库定版：细支流 0.25 pt 起，
干流上限 1.4 pt（0.49 mm）**——落在惯例区间的中低段（1:180 万全景图
不抢戏）。

## 单线 vs 双线

USGS/各国规范通行判据：实地河道宽度在成图比例尺下**超过约 0.5 mm**
（即 w 实地 > 0.5 mm × 分母）时从单线转双线（画两岸轮廓，中间留白或
填充）。例：1:25000 图上约 12.5 m 宽以上用双线。1:180 万全景图上双线
门槛 ≈ 900 m 实地宽——只有亚马逊/长江级干流够格；本库 MVP 全部单线
渐宽，双线留待大比例尺图（城市/区域详图）再启用。

## 宽度分级（流量→线宽）

**水力几何（hydraulic geometry, Leopold & Maddock 1953）**：下游沿程
w ∝ Q^0.5（河宽随流量平方根增长；经典指数 0.5，观测区间 0.4–0.6）。
以汇流累积（上游格数）为 Q 的代理，线宽取

```
width = w_min + (w_max − w_min) · (A / A_max)^0.5
```

**A 取逐段值**（2026-10-16 起）：河链提取把每格汇流累积作为第三坐标
随链插值，每段的 A 是其两端插值的均值——宽度沿链向下游渐变，支流汇
入处平滑衔接；此前整条链共用链末流量常数，汇合点线宽跳变一档，读作
断线/粘接痕。注意河口段（append 的出水格 A≈0）单调钳制到上游末格，
避免河口收窄。

注意这是**符号化借用**物理律（让上下游与汇入关系一眼可读），不是地形
按比例还原——按比例还原的 1:180 万图上，1 km 宽的大河只有 0.56 mm，
与符号区间同数量级，因此平方根分级不会产生「画笔感」（超粗干流）；
若线性映射或指数取 1，干流会到 2–3 mm，明显脱离惯例。

## 常流与非常流符号

US Topo 的水系规范用蓝色实线表示常流河，用同色的点划虚线表示间歇河；
线型表达季节情相，不改变水色。本库沿用这条双色同线的原则，但产品只
分常流与非常流两类，因为月度气候资料不能可靠地区分严格的间歇河与
事件尺度暂时河。图例列出图内实际出现的类别，避免读者把不同线型误解
为流量或咸淡差异。

两类线共用 `RIVER_COLOR`，流量的平方根线宽律也保持不变。常流河使用
实线和圆角端点；非常流河使用平头端点，避免圆形点划读作小湖。非常流
河使用 `RIVER_LS_NON_PERENNIAL = (0, (12.0, 2.4, 1.8, 2.4, 1.8,
2.4))`，即一段长划后接两个短划，数值以 pt 为单位。加长点划和改用
平头都是为了消除圆珠串般的湖面错觉。两类线由 `_river_collections`
分成至多两个 `LineCollection`，carto 与 biome 两种图共用同一实现，
因此不会出现同一条河在不同图种里线型不一致；`_river_regime_legend`
用同一套笔划生成图例样线。

非常流线不能交给 Matplotlib 按提取短段分别画 dash：Chaikin 平滑后的
河段中位长度不足 0.1 pt，逐段重起 dash 会把虚线画成实线，给逐段补偿
dash offset 又会形成不规则蓝色碎块。实现改为沿原河链在显示点坐标中
裁切连续笔划；每个笔划是一条可含多个原始顶点的折线，平头端点只出现
在真实笔划两端。笔划线宽取内部源段按长度加权的平均值，因此下游渐变
保留，而同一笔划内没有密集封口和宽度碎变。

## 常见错误（本库踩过）

1. **线宽跨度失控**（0.7→3.9 pt）：干流成「画笔粗细」——超惯例上限
   约 3 倍，读作涂鸦不读作地图。根因是只想着分级对比度，忘了符号
   尺寸的人眼/印刷约束。
2. **掩膜等值线渲染**：对河网掩膜画 contour，1 px 河带的等值线边界
   沿格向直行——产生 45°/90° 直线河（详见 drainage_cartography.md）。
3. 细线（<0.3 pt）在高 DPI 抗锯齿下视觉断续——0.25 pt @300 DPI ≈
   1 px，是可靠下限。

## 源码与参考

- 实现：`src/dreamulator/media/carto_render.py` 的
  `_river_collections`（流量线宽与情相线型），
  `src/dreamulator/map/prog_erosion.py` 的 `river_segments`（河段情相）
- Natural Earth rivers：https://www.naturalearthdata.com/downloads/
  10m-physical-vectors/10m-rivers-lake-centerlines（strokeweig 字段）
- QGIS 官方教程用法：https://baharmon.github.io/cartography-in-qgis
- Leopold & Maddock (1953), USGS Professional Paper 252
- USGS. *US Topo Cartographic Specifications: Hydrography* — 常流实线、
  间歇点划虚线与统一水色的官方规范：
  https://www.usgs.gov/ngp-standards-and-specifications/us-topo-cartographic-specifications-hydrography
