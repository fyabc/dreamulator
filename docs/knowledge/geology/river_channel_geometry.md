# 河槽宽深与河口泥沙

## 河线、河槽与河谷

地图上的河线是水系位置的表示，线宽可以随显示比例改变。河槽是实际容纳水流的断面，它有以米为单位的宽度和深度。河谷还包含河槽两侧的坡面与泛滥平原，不能用河槽宽度代替整个谷地的宽度。

全球网格和高清画布承担不同尺度的任务。无法在网格中分辨的河槽应保留为矢量或独立的断面信息；把一条窄河强行刻成一个整像素宽的凹槽，会改变其宽度和搬运体积。在约 90 m 的画布上，大河可能达到一个或多个像素，支流则经常仍属于亚像素结构。

## 流量统计必须对应断面状态

流量 $Q$ 表示每秒通过断面的水体积，单位为 m³/s。年均流量、某个月的平均流量和洪水峰值描述不同的水文状态。满岸流量是河水刚好充满河槽时的流量；年均流量不能自动替代它，月平均值也不能提供短时洪峰。

Leopold 与 Maddock（1953）分别研究同一断面随流量变化的关系，以及沿河向下游、在相同流量统计下比较不同断面的关系。这两种关系的指数不同。原文第 16 页给出的下游平均指数，在年均流量对应的状态下约为：

$$W = aQ^{0.5}, \qquad D = cQ^{0.4}, \qquad Q = W D U.$$

$W$ 是水面宽度，$D$ 是断面的平均水深，$U$ 是平均流速。宽深乘积是有水断面的面积。$a$ 与 $c$ 是观测拟合系数，它们的数值依赖采用的单位和样本域；流速可由连续性关系 $U=Q/(WD)$ 求得。这里的连续性关系属于体积守恒，宽深幂律属于观测拟合。

系数需要用同一流量统计的观测标定，并在其他流域检验。仅有年均流量时，可以检验年均状态下的宽深粗估，但不能据此生成洪水水面或满岸断面。河岸的黏性、岩性、河床坡度、粗糙度和输沙状态都会影响实际断面。地球上的拟合关系用于其他重力或其他流体条件时，还需要检验其外推范围。

USGS 原文附录 A（第 54 页）给出年均流量对应的河宽与平均水深。表中的英尺乘以 0.3048 可换成米，立方英尺每秒乘以 $0.3048^3$ 可换成 m³/s。原文标注受水坝或混凝土岸壁影响的断面，应单独登记，避免把工程约束当作天然河槽的普遍规律。

本库的研究助手位于 `scripts/geology/channel_geometry.py`，观测转录表位于 `scripts/geology/data/usgs_mean_channel_geometry.csv`。助手固定采用上述公开指数，只拟合系数，明确标记流量超出标定范围的样本。它估算年均状态下的尺度，没有进入正式河槽雕刻。

## 从汇流量换算流量

本库画布河网以参考径流归一化后的累积格数保存流量。按现行管线的投影像素面积口径，换算式为：

$$Q = \frac{A_{\rm ref}\,R_0\,\Delta x^2}{T_{\rm yr}}.$$

$A_{\rm ref}$ 是参考径流格数，$R_0$ 是每地球年的参考径流深度，以米计；$\Delta x$ 是投影像素间距，以米计；$T_{\rm yr}=365.25\times86400$ s。本库参考径流为每地球年 300 mm。它不是当前世界的平均径流，也不能随窗口裁切重新归一化。该式复用现有投影面积口径；球面面积的修正属于上游汇流口径，需要另行处理。

## 河口库存需要记录实际出口

侵蚀模型移走的地形体积，一部分在河道和湖盆中沉积，另一部分离开当前计算域。计算域边框、不可侵蚀表面、失去接收格的路径，以及非陆地基准面都可能形成输出。非陆地基准面也可能是内陆水体，因此总输出量不能直接称为入海泥沙量。

河口沉积首先需要保存每步实际出口及其体积，再核对出口是否进入连通外海。一次历史模拟的累计输出是库存；要获得输沙率，还需要相应的时间区间。地形等效体积也不能直接充当松散沉积物体积：若输入已经换算为固体颗粒体积 $V_s$，孔隙率为 $\phi$ 的沉积物总体积才是 $V_s/(1-\phi)$。当前地形体积账本没有提供这项换算的全部输入。

三角洲形态还取决于水流携沙能力、颗粒沉降、海浪、潮汐与岸流的再搬运。DeltaRCM 将水流和泥沙的路由相互反馈，并区分砂和泥；它不是把所有河口画成同一张扇形平原。较简单的方案也应先满足库存守恒与明确的岸线变化范围，再检查形态。局部窗口截断的上游供应不能由窗口内的侵蚀量补齐。

本库累计出口诊断由 `run_surface_process` 的 `track_sediment_exports` 选项提供，实现接口见[画布管线的二次侵蚀阶段](../../design/pipelines/canvas-chain.md#29-二次侵蚀与沉积surface_process)。Landlab 的 ErosionDeposition 组件同样从侵蚀与搬运总量的质量平衡出发，再决定局地沉积。

## 参考资料

- Leopold, L. B. 与 Maddock, T.（1953）。[The Hydraulic Geometry of Stream Channels and Some Physiographic Implications](https://pubs.usgs.gov/pp/0252/report.pdf)。USGS Professional Paper 252，第 16 页和第 54 页。
- Lin 等（2020）。[Global Estimates of Reach-Level Bankfull River Width Leveraging Big Data Geospatial Analysis](https://doi.org/10.1029/2019GL086405)。该文研究满岸河宽，可用于核对其流量统计与年均断面的区别。
- Liang 等（2015）。[A reduced-complexity model for river delta formation, Part 1](https://esurf.copernicus.org/articles/3/67/2015/)。介绍 DeltaRCM 的水沙路由与河道反馈。
- Landlab。[ErosionDeposition 组件](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.erosion_deposition.erosion_deposition.html)。介绍 Davy 与 Lague（2009）的侵蚀、输运和沉积账本。
- pyDeltaRCM。[泥沙路由实现](https://github.com/DeltaRCM/pyDeltaRCM/blob/develop/pyDeltaRCM/sed_tools.py)。可以核对砂泥分类、泥沙输入和地形反馈。
