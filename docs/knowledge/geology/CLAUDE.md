# 地质学知识库

## 已有文档

- `cvt_mesh.md` — CVT 球面网格生成（Fibonacci 螺旋、Lloyd 松弛、球形 Voronoi）
- `plate_tectonics.md` — 板块构造（欧拉极运动学、洪水填充、边界分类；earth 真实数据导入 PB2002 + OCB）
- `terrain_synthesis.md` — 地形合成（双峰基准、构造效应、fBm 噪声）
- `isostasy_elevation_limits.md` — 地壳均衡与高程极限（Airy/Pratt 补偿、挠曲海沟、重力标度；2026-08）
- `cortial_2019_notes.md` — Cortial et al. 2019 论文解读（自 geological-pipeline.md 附录 D 上浮）
- `tidal_plate_speed.md` — 潮汐加热→板块速度标度律（v ∝ q^β、Valencia vs O'Neill&Lenardic 争论、金星悖论；2026-08）
- `hydrology.md` — D8 流向 / priority-flood 洼地填平 / 流量累积 / 河网分级（2026-08）
- `coastal_geomorphology.md` — 海岸侵蚀/堆积地貌分类、潮差控制律（Davies/Hayes/Dalrymple）、44 m 巨潮差外推与 ~50 km 分辨率可表达性（2026-08）

## 关键参考

- Cortial, Y., Peytavie, A., Galin, E., & Guérin, E. (2019). *Procedural Tectonic Planets*. Computer Graphics Forum, 38(2).（`tectonic_simulator.py` 的算法来源）
- Frank, F. (1968). *Curvature of Island Arcs*. Nature.（海沟小圆弧涌现机制）
- Tovish, A., & Schubert, G. (1978). *Island Arc Curvature, Subducting Slab Dip*.（弧矢标定）
