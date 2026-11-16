# 地质学知识库

## 已有文档

- `cvt_mesh.md` — CVT 球面网格生成（Fibonacci 螺旋、Lloyd 松弛、球形 Voronoi）
- `plate_tectonics.md` — 板块构造（欧拉极运动学、洪水填充、边界分类；earth 真实数据导入 PB2002 + OCB）
- `terrain_synthesis.md` — 地形合成（双峰基准、构造效应、fBm 噪声）
- `orogen_topography.md` — 造山带与海沟的格子平均地形：亚格子起伏标定、留存缩短量与 Airy 增厚、力平衡平均高程上限、翼部坡度、有限山带端部的数值延拓、断板海沟挠曲、明确板块对极性与年代来源、弧前楔与地球体积检验（技术债 43，2026-10）
- `mountain_belt_morphology.md` — 山系与裂谷的空间组织：喜马拉雅的山前分支、安第斯山脉与高原、阿巴拉契亚长山脊及东非分段盆地；区分山带联系、剖面变化和局地起伏。
- `mid_ocean_ridge_morphology.md` 说明扩张速率与轴部高地、中央裂谷及超慢速洋脊的关系。文档区分现行速率分档与年龄—水深路径，说明轴部残差的参照、格均标定和海陆回归要求。
- `abyssal_seafloor_texture.md` — 深海底 1 到 20 km 频段：Goff–Jordan 各向异性深海丘陵随机场（走向平行古洋脊、起伏随扩张速率减小、按沉积削减）、SYNBATH 的高斯海山与合成频段做法、破碎带年龄台阶与深海平原；说明 TD 海底精度低是 ETOPO1 训练数据的结构性缺陷，纹理合成的前提是运动学回溯的洋底年龄与形成速率字段（2026-11）
- `thermal_regimes_and_metamorphism.md` — 温压体制作为构造背景到岩性的换算标尺：两条相变界线（10–11 与 25–35 °C/km）切出阿尔卑斯型/巴罗型/巴肯型三相系、四元动力学与热力反馈回路、主动与被动俯冲的产物差异（含陆壳是否增生）、碰撞连续谱与岩石圈拆沉、两类陆内造山与隐性张裂；本库暂不建模，定位为知识储备
- `plate_force_budget.md` — 板块速度从逐板块净力矩平衡解出（Forsyth & Uyeda 1975：板片上的力主导且强一个数量级）、力的清单与线性求解结构（不需要地幔流场），以及远场应力传递：对侧边界重组使张应力增加 5–10 MPa（Gianni 等 2026）
- `isostasy_elevation_limits.md` — 地壳均衡与高程极限（Airy/Pratt 补偿、挠曲海沟、重力标度；2026-08）
- `cortial_2019_notes.md` — Cortial et al. 2019 论文解读（自 geological-pipeline.md 附录 D 上浮）
- `tidal_plate_speed.md` — 内热与板块速度的关系（v ∝ q^β 标度律与争论、金星悖论；热管体制下板块只排出传导部分，板块排热按半空间冷却 ∝ √v）
- `supercontinent_cycle.md` — 超大陆旋回周期的标度估算（T ∝ R/v、阶段比例、裂谷沿古缝合带张开；nacrea 约 0.3–2.5 亿年；2026-10）
- `hydrology.md` 说明全球网格的洼地与封闭盆地，以及画布链的汇流、方向诊断、径流加权河网和湖泊水收支。D∞ 介绍包含四步流程、三角面几何、分流算例和原文的 D8 填洼及平地路由；连续流线部分解释样条新低点、三角面跨边事件、谷底沿边下降，以及排水连通与方向偏差的区别。扩大邻域部分说明两圈路由的双线性下降、水体首触、交叉拒绝与单接收格水量账本，画布部分说明独立的整数平地距离、跨块拓扑顺序、固定行列顺序的分带交叉检查，以及高程量化对坡度的影响与亚米级存储。
- `surface_transport.md` — 坡面输运的物理扩散系数、有限体积交换与海洋边界体积收支，以及均匀格网的河流侵蚀量纲。
- `volcanic_geometry.md` — 火山目录的当前背景、固定建成翼坡、出水面积和连续锥体体积，原粗格载荷与球面查询分别计账。
- `inland_water_classification.md` — 内陆水体分类学：water_class × is_lake 二维语义矩阵、尺寸分界依据、各层湖语义与不变式（2026-10）
- `coastal_geomorphology.md` — 海岸侵蚀/堆积地貌分类、潮差控制律（Davies/Hayes/Dalrymple）、44 m 巨潮差外推与 ~50 km 分辨率可表达性（2026-08）
- `continental_margins.md` — 大陆边缘：陆架即淹没陆壳、坡折深度与低海面和浪基面的关系、陆缘类型与宽度、陆坡坡度；俯冲陆缘的作用域、连续岸坡与海面位移、同等约 50 km 输入的地球陆架对照、局部宽度来源及地貌曲线的连接和剖面。
- `ice_sheets.md` — 极地冰盖物理学：初始冰量、高程语义、物质平衡、积累柱热诊断、约化全球体积估算、共享球面冰流、亚格子冰面响应与海洋输出、保持零冰厚的数值体积校正、平床与有坡度基岩上的塑性剖面、连通外海与静水接地的海洋边界，以及冰体与基岩侵蚀的响应时间。

## 关键参考

- Cortial, Y., Peytavie, A., Galin, E., & Guérin, E. (2019). *Procedural Tectonic Planets*. Computer Graphics Forum, 38(2).（`tectonic_simulator.py` 的算法来源）
- Frank, F. (1968). *Curvature of Island Arcs*. Nature.（海沟小圆弧涌现机制）
- Tovish, A., & Schubert, G. (1978). *Island Arc Curvature, Subducting Slab Dip*.（弧矢标定）
- Zheng, Y.-F. 等 (2026). *Structure, composition and dynamics of divergent and convergent plate margins*. Geoscience Frontiers 17(6).（温压体制框架；见 `thermal_regimes_and_metamorphism.md`）
- Gianni, G. M. 等 (2026). *Western Pacific double subduction drives Gulf of California rifting*. Science 394(6823).（远场应力传递；见 `plate_force_budget.md`）
