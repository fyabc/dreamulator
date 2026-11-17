# 制图学知识库

面向地形视频链（`docs/usage/terrain-chain.md`、`gaea-video-chain.md`）
的制图学依据：符号规范、水文要素制图处理、地形图设计惯例。数字都有
来源（官方规范/权威数据集/教科书），制图选择的标注与物理常量分开。

## 已有文档

- `river_symbolization.md` — 河流符号化：线宽规范（Natural Earth
  strokeweig 惯例 0.1–0.7 mm）、单双线判据、水力几何分级，以及常流
  实线与非常流点划虚线的情相符号（2026-10）
- [drainage_cartography.md](drainage_cartography.md) 说明制图用途的水文后处理，包括洼地语义、河链、湖泊判定与水量收支。区域采用带约束的两圈接收图并保留原顶点；小范围平滑章节作为研究参照，解释弧长采样、半像素位置约束、水体首触和独立交叉检查。
- [terrain_diffusion.md](terrain_diffusion.md) 介绍学习式地形细化器的条件扩散机制、训练口径的高程统计、
  粗输入的分布假设、原图分频混合与排水修整的验收边界，以及它与地表过程链的分工。
- `vegetation_cartography.md` — 植被/群系可视化两路线的惯例：分类
  群系图（Olson/WWF 标杆：平色填充、海洋留白、图例只列现出类）与
  卫星遥感风（Blue Marble/Sentinel-2：色相族+长势明暗+地表纹理）
  （2026-10）

## 关键参考

- Barnes, R., Lehman, C., & Mulla, D. (2014). *Priority-Flood: An Optimal
  Depression-Filling and Watershed-Labeling Algorithm*. IEEE TGARS 52(1).
  （Δ处理算法的一手来源；ε 变体与 breach 变体均出自此文）
- Natural Earth 数据集（naturalearthdata.com，公共领域）——河流
  `strokeweig` 属性与官方 QGIS 教程的 0.1–0.7 mm 映射惯例
- Leopold, L. B., & Maddock, T. (1953). *Hydraulic Geometry of Stream
  Channels*（河宽-流量 w ∝ Q^0.5 律的来源）
