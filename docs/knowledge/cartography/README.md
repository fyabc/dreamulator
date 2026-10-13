# 制图学知识库

面向地形视频链（`docs/usage/terrain-chain.md`、`gaea-video-chain.md`）
的制图学依据：符号规范、水文要素制图处理、地形图设计惯例。数字都有
来源（官方规范/权威数据集/教科书），制图选择的标注与物理常量分开。

## 已有文档

- `river_symbolization.md` — 河流符号化：线宽规范（Natural Earth
  strokeweig 惯例 0.1–0.7 mm）、单双线判据、水力几何分级（2026-10）
- `drainage_cartography.md` — 制图用途的水文后处理：洼地语义二分
  （fill 产湖 / breach 凿谷）、河链聚合与平滑、湖的最小面积阈值
  （2026-10）
- `terrain_diffusion.md` — terrain-diffusion 学习式地形细化器：条件
  扩散机制、实测能力边界（确定性/海岸线漂移/不管水文）、与 SPL 链
  的分工（2026-10）

## 关键参考

- Barnes, R., Lehman, C., & Mulla, D. (2014). *Priority-Flood: An Optimal
  Depression-Filling and Watershed-Labeling Algorithm*. IEEE TGARS 52(1).
  （Δ处理算法的一手来源；ε 变体与 breach 变体均出自此文）
- Natural Earth 数据集（naturalearthdata.com，公共领域）——河流
  `strokeweig` 属性与官方 QGIS 教程的 0.1–0.7 mm 映射惯例
- Leopold, L. B., & Maddock, T. (1953). *Hydraulic Geometry of Stream
  Channels*（河宽-流量 w ∝ Q^0.5 律的来源）
