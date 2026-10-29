# 地质学知识库

## 已有文档

- `cvt_mesh.md` — CVT 球面网格生成（Fibonacci 螺旋、Lloyd 松弛、球形 Voronoi）
- `plate_tectonics.md` — 板块构造（欧拉极运动学、洪水填充、边界分类；earth 真实数据导入 PB2002 + OCB）
- `terrain_synthesis.md` — 地形合成（双峰基准、构造效应、fBm 噪声）
- `orogen_topography.md` — 造山带与海沟的格子平均地形：亚格子起伏标定、留存缩短量与 Airy 增厚、力平衡平均高程上限、翼部坡度、有限山带端部的数值延拓、断板海沟挠曲、明确板块对极性与年代来源、弧前楔与地球体积检验（技术债 43，2026-10）
- `mountain_belt_morphology.md` — 山系与裂谷的空间组织：喜马拉雅的山前分支、安第斯山脉与高原、阿巴拉契亚长山脊及东非分段盆地；区分山带联系、剖面变化和局地起伏。
- `isostasy_elevation_limits.md` — 地壳均衡与高程极限（Airy/Pratt 补偿、挠曲海沟、重力标度；2026-08）
- `cortial_2019_notes.md` — Cortial et al. 2019 论文解读（自 geological-pipeline.md 附录 D 上浮）
- `tidal_plate_speed.md` — 内热与板块速度的关系（v ∝ q^β 标度律与争论、金星悖论；热管体制下板块只排出传导部分，板块排热按半空间冷却 ∝ √v）
- `supercontinent_cycle.md` — 超大陆旋回周期的标度估算（T ∝ R/v、阶段比例、裂谷沿古缝合带张开；nacrea 约 0.3–2.5 亿年；2026-10）
- `hydrology.md` — 全球网格只做洼地填平与封闭盆地湖泊（不做汇流的尺度理由）；画布链的 D8 汇流、径流加权河网、终点湖水收支与月度情相
- `surface_transport.md` — 坡面输运的物理扩散系数、有限体积交换与海洋边界体积收支，以及均匀格网的河流侵蚀量纲。
- `volcanic_geometry.md` — 火山目录的当前背景、固定建成翼坡、出水面积和连续锥体体积，原粗格载荷与球面查询分别计账。
- `inland_water_classification.md` — 内陆水体分类学：water_class × is_lake 二维语义矩阵、尺寸分界依据、各层湖语义与不变式（2026-10）
- `coastal_geomorphology.md` — 海岸侵蚀/堆积地貌分类、潮差控制律（Davies/Hayes/Dalrymple）、44 m 巨潮差外推与 ~50 km 分辨率可表达性（2026-08）
- `continental_margins.md` — 大陆边缘：陆架即淹没陆壳、坡折深度与低海面和浪基面的关系、陆缘类型与宽度、陆坡坡度；俯冲陆缘的作用域、连续岸坡与海面位移、同等约 50 km 输入的地球陆架对照、局部宽度来源及地貌曲线的连接和剖面。
- `ice_sheets.md` — 极地冰盖物理学：无量纲日照门、距海分域、完美塑性穹丘与 Bedmap2 标定，以及冰面、受载基岩和卸载基岩的高程语义与形态验收。

## 关键参考

- Cortial, Y., Peytavie, A., Galin, E., & Guérin, E. (2019). *Procedural Tectonic Planets*. Computer Graphics Forum, 38(2).（`tectonic_simulator.py` 的算法来源）
- Frank, F. (1968). *Curvature of Island Arcs*. Nature.（海沟小圆弧涌现机制）
- Tovish, A., & Schubert, G. (1978). *Island Arc Curvature, Subducting Slab Dip*.（弧矢标定）
