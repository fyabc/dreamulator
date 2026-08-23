# 开发路线图

> 最后更新：2026-08-19（v0.32.0 地图图层 headless 导出 CLI + 配色单源化 + Seed 探索器 CLI。前次：v0.31.0 守护轴实现落地：事实上下文 / 过期检测 + guard check / ADR 台账 / 原语注册表 / 拷问编排 + /grill-world skill）
> 长期愿景与设计哲学见 [vision.md](proposals/vision.md)；竞品分析见 [competitor-analysis.md](competitor-analysis.md)；
> 文明层详细设计见 [civilization-layer.md](proposals/civilization-layer.md)；
> 生态层设计见 [ecology-layer.md](proposals/ecology-layer.md)；洋流系统设计见 [ocean-currents-model.md](archive/ocean-currents-model.md)；
> 文明种子见 `data/worlds/gaia-m/layers/civilization/input/civilizations.yaml`。

---

## 一、当前状态快照（v0.32.0）

| 维度 | 状态 |
|------|------|
| 层级管线 | physics → chemistry → astronomy → geological → climate → ecology 全链路打通；civilization 新增宜居/农业 derived 引擎（`engine/civilization.py`），3C 半格式化 Schema 与 LLM narrate 待推进 |
| 性能 | gaia-m（200k 节点）全量构建 ~391 s（地质 238s + 气候 147s + 生态 5s）；1M 节点 41 min；`build_profile.json` 仪表 + pytest-benchmark CI |
| 确定性 | 种子化 RNG + crc32 校验和，跨进程可复现 |
| 气候精度 | Köppen 分布匹配 53.6%（v0.27+，季节 EBM + s/w 修复后，vs Beck 2018，200k ETOPO1）；T2 端元复现 4 测试 + T3 物理合理性 7 测试已建 |
| 样板世界 | gaia-m：200k 节点（~51 km/cell）、~72% 海洋、均温 14.4 °C（v0.15.0+ 校准）；25 板 CV=0.87（偏态化）、海洋最深 −10484 m |
| 网格规模 | 主力分辨率 **200k**（51 km/cell，已达中分辨率 GCM 水平）；ESM 气候验证支持多数据集（Beck 2018 + ERA5 + GPCP）；JSON 浮点截断 4 位 + gzip 传输（~220→~50 MB） |

---

## 二、Phase 总览

| Phase | 主题 | 状态 | 说明 |
|-------|------|------|------|
| 1 | 核心脚手架 | ✅ v0.1.0 | 数据模型、CLI、世界管理 + 分支、天文学引擎、前端骨架；见 CHANGELOG.md |
| 2 | 前端可视化 | ✅ v0.2.0–0.6.0 | 地图系统（栅格+Voronoi）、3D 恒星系、CivMap、3D 球面地球；见 CHANGELOG.md |
| 2.5 | 地形真实感增强 | ✅ v0.7.0–0.8.0 | 板块剖分（Cortial 2019）、地形合成、海岸线、噪声标定；见 CHANGELOG.md |
| 3A | 气候与流体引擎 | 🚧 | 核心已合并（v0.9.0），调优进行中；见 三 |
| 3B | 侵蚀与河流生成 | 📋 | D8 流向 / 流量累积 / 水力侵蚀 / 沉积物搬运（`river_generator.py`、`erosion.py` 为占位） |
| 3B.5 | 生态层：气候→群系→承载力 | 🚧 | Whittaker 映射 + 代谢标度 NPP + 可驯化标签（P0 ✅ 已于 v0.20.0 实施，含前端 Whittaker 群系 / NPP / 文明摇篮三个专题图层）；区域连通物种分布（P1）；简单食物网（P2）；异星物种推演（P3 = body plan 推导 P3a → 演化树 P3b → 图像输出 P3c，推演核心留主仓、图像独立成模块，见 [ecology-layer.md](proposals/ecology-layer.md) §3.5 / 决策 #5）。数学模型见 `docs/knowledge/ecology/ecological_mathematical_models.md` |
| 3C | 文明层半格式化管理 | 📋 | 事件溯源 + 状态机，设计见 [civilization-layer.md](proposals/civilization-layer.md) |
| 3D | 世界线合并可视化 Diff | 📋 | DAG 影响半径分析 / Lyapunov 混沌预警 / 蒙特卡洛不确定性 |
| 3E | LLM 叙事引擎 | 🚧 | 基础 `narrate` 已实现；史诗叙事桥（`narrative_bridge.py`）未做 |

---

## 三、Phase 3A 气候引擎子状态

详见 [climate-pipeline.md](pipelines/climate-pipeline.md)。输出：temperature.png / precipitation.png / koppen.json / climate_metadata.json。

| 功能 | 状态 | 说明 |
|------|------|------|
| 能量平衡模型（EBM） | ✅ | `climate_physics.py:equilibrium_temperature()` |
| 纬度 + 海拔温度修正 | ✅ | 1D EBM 谱解（North 1975 / climlab）+ 大陆度 + 湿度绝热直减率 |
| Hadley/Ferrel/Polar 风带 | ✅ | v0.19.0：经向分量 + Ω^(-1/3) 标度 (Hill 2019)；`climate_physics.py:hadley_cell_wind()` |
| 地形降水 + 雨影 | ✅ | 风偏图扩散水汽传输 + 辐合驱动三层降水 |
| 陆地蒸散循环 | ✅ | 土壤+植被蒸发回收 |
| ITCZ 对流降水 | ✅ | 热带辐合带 + 局地热对流 |
| Köppen 气候分类 | ✅ | 分布匹配 53.6%（v0.27+，季节 EBM + s/w 修复后，200k，vs Beck 2018；v0.26.0 为 55.0%） |
| ETOPO1 真实地球验证 | ✅ | `earth/climate-dev` 分支 + `scripts/validate_climate.py` |
| 热带降水修正（3A.1） | ✅ | v0.11.0：ITCZ 增强、热带对流 ×2、降水底线 |
| 季节变化（3A.2） | ✅ | **季节能量平衡模型** `T_amp=ΔQ_ω(1−α)/√(B_eff²+(ωC)²)`（North & Coakley 1979，`B_eff=B+6D` 显式热输送）+ 季节冰反照率 + ITCZ 迁移月度降水 + s/w 判别季节感知 |
| 洋流 + 温度精细化（3A.3） | ✅ | Stommel + GMRES；冰盖反照率（M dwarf 修正）；可变直减率（Γ(T), 热带高地 +3.5°C）；上升流 SST 冷却；~~云反馈~~（SW/LW 抵消→跳过） |
| 慢自转经向输送（3A.3a） | ✅ | v0.19.0：Ω^(-1/3) 风速标度 (Hill 2019) + 经向风分量；v0.24+：1D EBM 显式经向扩散 D（Ω^0.3 标度） |
| 空间格局精细化（3A.4） | ✅ | 辐合驱动干带（∇·u 自然涌现，无纬度硬编码）；内陆干旱梯度；海岸不对称；Föhn（C-C 方程，零自由参数） |
| 海洋气候分区（3A.5，Longhurst） | 📋 | 海洋省份分类 |
| 恒星/轨道参数查找（3A.6） | ✅ | v0.14.0：`engine/physical_inputs.py` 统一解析（卫星感知的恒星查找 + 开普勒轨道周期），替换旧硬编码 1.0 AU / 1.0 L☉ |
| 潮汐锁定经度效应（3A.7） | ✅ | v0.19.0：cos 暖化参数化；v0.24+：子星体对流增强（高斯锚定经纬度，振幅 ∝ ΔT_sub），潮汐锁定/卫星/双星通用 |

> **诊断结论（2026-08）**：Köppen 两条线要分开——**BWk（冷荒漠）→ C/D 靠「增湿」**
> （`moisture_advection_steps` 提高把水汽送进内陆），**ET（苔原）→ C/D 靠「增温」**
> （t_hot 过 10°C 林线）。ET 主体是「温和但干」（年均 ~5°C、降水中位 ~33mm），增湿
> 不改其温度、暖化不改其干旱，二者不可互替。gaia-m 调参：`evaporation_base_mm` 2000→1850
> （近地球值）、`moisture_advection_steps` auto17→27（Ω^(−1/3) 经验标度 ±50% 内）。

## 四、Phase 3B–3E 要点

- **3B 侵蚀与河流**：D8 流向 → 流量累积（集水面积→河宽）→ 水力侵蚀（河道下切+坡面）→ 沉积物搬运（三角洲）。

  **架构决策（2026-08-09）**：侵蚀属于 geological 层，但完整水力侵蚀需要降水数据，而气候是 geological 的下游（geological → climate）。直接读 climate 层会形成循环依赖，破坏 DAG。
  
  **方案**：地质层内部使用**地貌降水代理**（geomorphic precipitation proxy），不读气候引擎输出：
  - 代理场 = 纬度带基底水汽 + 线性地形雨/雨影（Smith & Barstad 2004，傅里叶域求解）
  - 纯函数 `(地形, 纬度, 行星参数)` → 降水强迫场，DAG 不破
  - 气候引擎仍从最终（侵蚀后）地形算权威气候（供生态/文明），两者是"强迫 vs 精细化"关系
  
  **管线位置**：`terrain_config.yaml` 新增 `surface_evolution_steps`（层内时间循环，接在 tectonic_steps 之后）+ `climate_coupling: none | proxy | full`（默认 proxy）。
- **3C 文明层**：三层半格式化架构（实体修饰器 / 事件流 / LLM 渲染层）+ 策略模式建模（HANDY / SDT / Tainter / 标签驱动），见 [civilization-layer.md](proposals/civilization-layer.md)。
- **3D 世界线 Diff**：地理热力图 + 文明状态对比；DAG 影响半径、混沌预警、蒙特卡洛置信区间。
- **3E 叙事引擎**：`narrative_bridge.py` — LLM 读取 YAML/JSON 数据变动，生成符合逻辑的世界线编年史。

---

## 五、近期工作：gaia-m 样板世界改造（2026 Q3）

目标：把 gaia-m 打造成物理自洽、内容丰富、可支撑 B 站系列视频的样板世界。

| 项目 | 内容 | 状态 |
|------|------|------|
| 天文：卫星系统 | 新增 4:2:1 拉普拉斯共振卫星链（Cadence/Vigil），为 e_m=0.0025 提供 60 亿年尺度的共振泵浦机制（此前设定无泵浦源） | ✅ v0.15.0 |
| 天文：轨道校准 | Aegis 内移 0.2795 → 0.2722 AU（混合变暖路径），Boreal/Glacis 随共振链同步缩放 | ✅ v0.15.0 |
| 地质：海陆分布翻案 | 潮汐物理要求向星/背星点为深海、侧点/极点偏陆；旧设定（大潮点大陆）被推翻，改为不对称混合案 | ✅ 地形引擎已按新设定生成：`geography.yaml` 地理锚定（大陆锚点/陆地偏置场 + 全局阈值 + 构造后重锚定），见 geological-pipeline.md §3.5；海岸线平直为已知限制 |
| 气候：温度校准 | 温室 72 → 75 K（保留 3 K 给次行星半球加温）；lat_gradient_c 与 Hadley 边界参数化，均温 9.2 → 14.4 °C | ✅ v0.24+（ΔT(Ω) + 扩散热输送 + 冰反照率 + 可变直减率 + 子星体对流增强全链路完成） |
| 气候：文档校验 | 按引擎实际输出重写 `layers/climate/input/*.md`（200k seed=42） | ✅ v0.24.0 |
| 数据：200k 迁移 | gaia-m 网格 100k→200k（71→51 km/cell），数据已提交 | ✅ v0.24.0 |
| 文明：种子设计 | civilizations.yaml 填充（3 文明 + 地理锚点 + 双语言叙事，2026-08 由 seed_discovery 候选区锚定）；大事年表 / conlang 待推进 | ✅（已填 3 种子） |
| 视频素材 | 板块漂移/气候/文明 timelapse、3D 自动旋转、纯净视图模式 | 📋 |

---

## 六、实施优先级

### 已完成（摘要）

- **守护轴**（校验/审计/设定维护，v0.31.0）；**回归测试基建**；**前端加载性能优化**（JSON 截断 + gzip + MessagePack）。
- **地图图层 headless 导出 CLI**；**气候诊断脚本四件套**；**Seed 探索器 CLI**；**文明宜居/农业图层**；**全球温度/降水图层**；**单元格信息面板重构**；**3D 球体拖动修复**；**前端气候可视化**（风场箭头）；**文档 200k 更新**。
- **气候 3A**：3A.3a 慢自转输送 / 3A.3 温度精细化 / 3A.7 潮汐锁定 / 3A.4 空间格局；**洋流系统**（Stommel 流函数 + SST 平流 + 涌升）。
- **生态层 P0**（Whittaker + NPP + 可驯化标签）；**潮汐加热显式化**；**CLI 精简**（移除 `terrain generate`）；**gaia-m 迁移 200k + 气候文档校验**。

### 待办

| 优先级 | 模块 | 预计工作量 | 关键性 |
|--------|------|-----------|--------|
| **P1** | **局部地形精细化管线**（桥接 dreamulator 全球输出 → 专业工具局部高精度地图。含：① `export-region`/`import-region` CLI 命令（立体投影区域导出 + 羽化回贴）——`map-workflow.md` §6 已纸面设计但未实现；② GeoTIFF 导出支持（带地理参考，QGIS 直接打开）；③ Gaea/World Machine 侵蚀节点图模板；④ QGIS 矢量化脚本（栅格→等高线+河流+政区边界）；⑤ Photoshop 配色/标注模板。目标自动化程度：dreamulator→PNG/GeoTIFF 自动；Gaea/QGIS 半自动（模板+脚本）；Photoshop 手动） | 设计 0.5 周 + 实现 1–2 周 | ★★★★ |
| **P0** | gaia-m 样板世界改造（五） | 进行中。天文/地质/气候三大层已就绪；文明种子设计 + 视频素材待推进 | ★★★★★ |
| P1 | 文明层半格式化 Schema（3C） | 1–2 周 | ★★★★ |
| P1 | 视频素材功能（timelapse / 自动旋转 / 纯净视图） | 2–3 周 | ★★★★ |
| P1 | LLM 叙事桥（3E 史诗叙事） | 2 周 | ★★★★ |
| P2 | 水力侵蚀 + 河流（3B） | 2–3 周 | ★★★ |
| P2 | **海岸侵蚀·潮汐冲刷主导**（并入 3B）：潮汐锁定卫星的海岸侵蚀以潮汐冲刷（tidal scour）而非波浪为主导，需潮差输入（来自 astronomy 上游，无 DAG 循环）；地貌降水代理仅用于河流侵蚀，潮差输入更干净 | 1–2 周 | ★★★ |
| P2 | **生态层海洋模块**（3B.5）：潮间带宽度、海洋 NPP 潮汐混合因子、深海热泉密度——当前生态层全陆相 Whittaker 映射，零海洋 | 1–2 周 | ★★★ |
| P2 | 地质时间轴可视化（板块漂移回放） | 3–4 周 | ★★★ |
| P2 | 世界线 Diff 可视化（3D） | 2 周 | ★★★ |
| P2 | Entity ID 系统（UUIDv7 + slug 双主键，为 DAG 精确寻址铺路） | 1 周（低风险渐进迁移） | ★★★ |
| P2 | `ai` CLI 命令组（narrate/imagine/assist/trace/mythologize/tavern 等；`ai assist` 为世界设计助手——自然语言→结构化编辑；`ai civ` 为地理→文明推演——气候画像→文明种子，衔接 civilizations.yaml。设计见 [ai-cli-commands.md](proposals/ai-cli-commands.md)。**注**：`ai critique`/`ai trace`/`ai reconcile` 已并入守护轴 [harness.md](proposals/harness.md) P0，不在本条目内） | 2–3 周 | ★★★ |
| P1 | **增量重建细化**（`--only terrain` 粒度：改 geography.yaml 后跳过板块构造） | 0.5 周 | ★★★★ |
| **P0** | **前端加载性能优化**（① JSON 截断 ✅ ② gzip ✅ ③ MessagePack ✅ 已落地；④ 纹理分辨率匹配 cell 密度待做） | 1–2 周 | ★★★★★ |
| P1 | **几何/气候数据分离存储**（静态网格（x,y,z,neighbors,plate_id）只加载一次；气候/生态字段增量更新。200k 下几何 ~80 MB、气候 ~90 MB，总计 ~170 MB 可接受） | 0.5 周 | ★★★★ |
| P2 | **geography.yaml 编辑原语补全**（`elevation_bias` 区域性海拔乘数、`lock_region` 锁定区域、`lake`/`inland_sea` 内陆水体定义；**注意**：geography.yaml 约束随机生成过程，seed 无关；逐 cell 后处理覆写属 edits.json 层） | 1–2 周 | ★★★ |
| P2 | **edits.json 逐 cell 编辑系统**（方案 B：管线后处理叠加层，seed 绑定。支持逐 cell elevation/land_sea 覆写。Phase 1: 点击编辑；Phase 2: 画笔工具；Phase 3: 地形笔刷。换 seed 时标记 stale 并支持最近邻迁移） | 1–2 周（Phase 1: ~2 天） | ★★★ |
| P2 | **分辨率独立性验证**（确保 geography.yaml 锚定特征在 100k/200k/500k 下一致；已发现 sub-cell 特征如北方内海连通性对分辨率敏感，需文档化边界） | 0.5 周 | ★★★ |
| P3 | **外部编辑往返协议**（mesh ↔ 高分辨率栅格 ↔ 外部工具编辑 ↔ 回贴 cell，用于 Gaea/World Machine 集成）。**注**：P1 "局部地形精细化管线" 为此项的 MVP 先行版——先打通实用工作流，远期再做全自动往返协议 | 远期 | ★★ |
| P3 | AI 顾问模式 / 实时协作 / 世界导出包 | 见 vision.md §9 | ★★ |
| P3 | Moltke Engine — 独立实体引擎（ECS + 差分数据流 + 增量分支计算） | 远期，设计概要见 [moltke-engine.md](proposals/moltke-engine.md) | ★★ |
| P3 | SDE 文明建模（Euler-Maruyama / Milstein / Jump-Euler + 泊松跳跃冲击） | 远期，依赖 Entity ID + Modifier 系统 | ★★ |
| P3 | **harness environment 统一底层**（ai 命令组统一跑在「事实上下文 + 原语/verifier 注册表 + 证据三分类」上；`query_registry` 补 `context=None` 物理/化学 verifier 原语——配平、密度-温度、能量预算等，作 `ai critique` 确定性取证底座。见 [harness.md](proposals/harness.md) §9.4） | 内核 0.5 周，随 `ai` 命令组（P2）推进 | ★★ |

---

## 七、已知技术债务

2026-08-04 更新（v0.14.0 后）。按"功能性 → 工程卫生"排序。

### 功能性

1. **潮汐锁定经度效应缺失**（Phase 3A.7）— 无昼夜半球 / 次恒星点热源 / 经度
   不对称，潮汐锁定世界只能产出纬向对称近似气候。gaia-m 温室预算已预留 +3 K
   等待该效应落地。
2. **海岸线过于平直** — 海陆判定在 cell 粒度（~51 km @ 200k cells），海岸线
   沿 cell 边延伸、缺乏分形细节（用户反馈，2026-08）。方向（任选/组合）：
   更高 cell 密度；海岸带高频噪声扰动（沿海岸对陆/海判定做 sub-cell 噪声阈值）；
   或在导出栅格时对海岸线做分形细分。与地理锚定（§3.5）兼容——锚定给出宏观
   格局，此改进只增海岸微观粗糙度。
3. **大裂谷海过于对齐经线、边界平直** — 当前用单个拉长偏置场（elongation=11、
   bearing=0），产生笔直经向裂谷。应似东非大裂谷/红海：蜿蜒走向、不规则边界、
   局部断块隆起/异常塌陷。已用"多段错列偏置场"初步缓解（见 gaia-m
   geography.yaml）；彻底方案需 geography 逻辑支持"弯曲裂谷带"原语。
   **~~另一脆弱机制~~** → ✅ 已修复（2026-08-07，feat/geography-elevation-anchor）：
   地形合成对强负偏置场（authored 裂谷/海盆）的汇聚抬升乘连续阻尼
   （bias<−0.5 时 clip(2·bias+2, 0.1, 1.0)，岛弧同处理）；gaia-m 重建核对
   大裂谷海支持区 max elevation <0 m。同批新增 `elevation_target_m`/`pin_strength`
   高程钉扎（浅海/地峡水深控制）与 `sea_level_offset_m` 海平面旋钮
   （冰期/临界海峡实验），见 geological-pipeline.md §3.5。
   **蜿蜒裂谷原语**仍 open（上段）。
4. **气候分类体系扩展**（2026-08-09）— 当前仅 Köppen–Geiger 一种分类。建议新增：① **Trewartha**（更好的中纬度区分 + 亚热带独立主群——对 gaia-m 慢自转 Hadley 扩展后的中纬度过渡带尤其有用）；② **Holdridge Life Zones**（基于植物生理而非地球植被经验——系外行星通用、直接桥接生态层 Whittaker 映射）。两种均复用现有 T/P 数据，零新增数据需求。见 `docs/knowledge/climatology/climate_classification_comparison.md`。优先级 P2。
5. **年均温 / 年降水诊断图层缺失**（2026-08-09）— `temperature_C` 和 `precipitation_mm` 是逐 cell 字段，但无对应的地图专题图层。世界构建者调试气候参数时需要直接看原始场而非经过分类"滤镜"的 Köppen。实现成本极低（连续色标 pseudo-color 烘焙，管线已有），优先级 P2。建议随洋流图层 P4 面板重构一并加入。
6. **自动国界 / 行政区划生成**（2026-08-09）— Azgaar's FMG 具有基于地形自动剖分的 burgs/states/provinces 系统，dreamulator 目前无对应模块。roadmap 3C 文明层的当前设计以人工锚定种子 + 事件流程序化填充为主，自动领土剖分是远期扩展项。登记为 P3 技术债，不阻塞 3C 推进。前期调研：Azgaar 的自动国界算法（基于流域 + 距离衰减 + 军事/文化权重）值得参考但不应移植。
7. **北方内海封堵**（2026-08-09 诊断）— gaia-m cell #7244 (elev=49m) 和 #7155 (elev=20m) 处于 ~59°N, 12–13°E，将北方内海与外洋隔断。邻接 cell 有海拔 −107m 的海洋，但这两个低陆 cell 构成"堤坝"。应在高程均衡上限（#11）+ 侵蚀（3B）实施后自然解决（低陆被消减或水道被下切）。如不解决，需在 geography.yaml 加小型 `shallow_sea` feature 强行切开。
8. **Cortial 2019 算法对 seed 高度敏感**（2026-08-10 诊断）— 多 seed 对比（42/123/456 @100k）发现：海陆空间一致率仅 74%、海岸线 IoU 仅 8%、海拔相关性 r=0.25、Köppen 空间一致率仅 44%。不同 seed 产生的是**完全不同的星球**，而非同一星球的不同变体。geography.yaml 锚定系统是唯一约束机制，但当前仅覆盖命名地貌，其余区域完全随机。需要 seed 探索器 + 种子目录作为补充工具链。见 六 P1 新增条目。
9. **气候对网格分辨率敏感**（2026-08-10 诊断）— 100k vs 200k 对比发现 Af（热带雨林）质心偏移 37° 经度、北方内海在 200k 下封闭。全局汇总统计（均温、Köppen 比例）稳定（<3%），但空间分布对分辨率敏感。属于 EBM 级别引擎的已知局限，需在气候验证中建立分辨率敏感度基线。
10. **JSON 格式是前端可扩展性硬上限**（2026-08-10 诊断）— 500k cells 的 cvt_mesh.json 达 570 MB，浏览器 `JSON.parse()` 直接 OOM（堆内存需求 ~2 GB 超出 V8 限制）。200k（~220 MB, gzip ~50 MB）已验证可用。根本原因：JSON 逐字段文本编码，每 cell ~1 KB；解析后 JS 对象堆膨胀 3–4×。**已缓解**：MessagePack 二进制 + Web Worker 解析已落地（传输 -50%、解析不阻塞主线程，见 六 P0 ③✅）；但解析后的 JS 堆膨胀（3–4×）仍存在，500k 的 OOM 上限只是推迟而非消除。
11. **后端构建性能缩放数据**（2026-08-10）— 多分辨率基准测试（seed=42，同一 geography.yaml）：

| 阶段 | 100k | 200k | 500k | 1M | 1M/100k | 缩放类型 |
|------|------|------|------|-----|---------|---------|
| mesh | ~19s | 31s | 77s | 176s | 9.3× | O(N log N) |
| plates | ~3s | 5s | 11s | 28s | 9.3× | O(N) |
| tectonics | ~36s | 85s | 178s | 455s | 12.6× | O(N^1.5) |
| terrain | ~59s | 104s | 296s | 737s | 12.5× | O(N^1.5) |
| **地质合计** | **~126s** | **238s** | **583s** | **1434s** | **11.4×** | |
| temperature | 2.6s | 6.0s | 14.5s | 28.7s | 11.0× | O(N) |
| wind | 4.5s | 8.2s | 20.5s | 40.7s | 9.0× | O(N) |
| **ocean** | **32.1s** | **87.6s** | **356.4s** | **764.2s** | **23.8×** | **O(N^1.7)** |
| precipitation | 13.2s | 25.8s | 64.3s | 128.2s | 9.7× | O(N) |
| **气候合计** | **68.4s** | **147.1s** | **482.4s** | **1002.9s** | **14.7×** | |
| ecology | ~3s | 5s | 13s | 27s | 9× | O(N) |
| **总计** | **~200s** | **391s** | **1079s** | **2464s** | **12.3×** | |

明细（1M=41 min）：地质 23m53s（58%）、气候 16m43s（41%）、生态 27s（1%）。

**ocean (GMRES) 缩放非线性但非爆炸性**：100k→200k 2.75×、200k→500k 4.05×、500k→1M 2.15×。其中 200k→500k 最差（2.5× nodes 但 4.05× 耗时），可能因海盆切分阈值在该区间触发了不同数量的独立 GMRES 求解。1M 有 126 个海盆（500k 约 71 个），最大单盆 680k cells。整体 1M/100k=23.8× 偏离理想 10×，是唯一需要算法优化的阶段。

**地质层缩放健康**：tectonics 和 terrain 均为 O(N^1.5) 预期，mesh 为 O(N log N)，均无意外。
12. **四层控制模型**（2026-08-11 设计决策）— 将地质层的两层编辑架构（#20）泛化为适用于所有 DAG 层级的统一框架。详见 [layer-control-model.md](proposals/layer-control-model.md)。核心设计：

| 层级 | 载体 | 职责 |
|------|------|------|
| 约束层 | 各层 `*_constraints.yaml` | 语义化宏观控制，seed 无关 |
| 引擎层 | DAG Pipeline | 物理/数学计算 |
| 校验层 | `conflict_resolution.yaml` | 一致性守卫 |
| 覆写层 | 各层 `edits.json` / `overrides` | 逐实体强制值，seed 绑定 |

约束类型分级：Hard（必须满足，违反则拒绝）/ Soft（尽量满足，违反则警告）/ Preference（倾向性，记录日志）/ Override（直接覆写，跳过引擎）。

| 层级 | 文件 | seed 依赖 | 粒度 | 示例 |
|------|------|----------|------|------|
| 约束层 | geography.yaml | 无关 | 命名地貌 | "这里要有裂谷海" |
| 覆写层 | edits.json | **绑定** | 逐 cell | "#7244 elevation −20m" |

管线位置：geography.yaml 在 plates/terrain 阶段生效，edits.json 在 terrain synthesis 之后作为后处理叠加。换 seed 时 edits.json 标记 stale，支持最近邻迁移（尽力而为）或丢弃重编辑。详见 六 P2 条目。

13. **生态 NPP 光谱匹配缺失**（2026-08-13）— 当前 `par_ratio = L/d²`
   （`ecology.py`）是**总辐射通量比**（标量），未按恒星光谱类型修正光合
   有效辐射（PAR，400–700 nm）。M 矮星（gaia-m `star_ignis` 0.036 L☉）辐射峰
   在近红外（NIR），可见光/PAR 比例低 → 用总通量会**高估**叶绿素型植物的
   NPP；反之若植物演化出 NIR 吸收色素，可利用红外辐射，NPP 可能不降反升。
   缺失的修正链：`恒星光谱类型 → 光合色素吸收谱 → 有效 PAR → par_ratio`。
   当前 `physical_inputs` 只解析 `stellar_luminosity_sol`（总光度），未读恒星
   有效温度/光谱型。优先级 **P2**（类地球世界不受影响，仅影响 M/K 矮星异星
   生态的真实性）。配套：新增 `docs/knowledge/ecology/photosynthesis_spectra.md`
   （光合吸收谱 + 恒星光谱匹配，含 C3/C4 效率上限与 NIR 色素的参考）。

14. **世界参数单一来源缺失**（2026-08-13）— 参数（光度、轨道、温室等）散落在
   `stellar.yaml`/`planets.yaml` 之外，还被**手工抄写**进多个 Markdown 文档
   （`physical_params.md`、`orbital_dynamics.md`、`giant_brightness.md`、
   `stellar_decisions.md` 参数表、`long_term_cycles.md` 等），且衍生值
   （辐照度 `L/4πa²`、太阳日 `1/(1/P自转−1/P公转)`、日照比 `L/a²`、年长/每季/
   一年日数/极昼极夜/寿命/演化进度）需**手算**。方案2 参数调整时手动同步了 7+
   文档、20+ 处数值，仍遗漏 `long_term_cycles.md` 两处。修复方向（两阶段）：
   ① **衍生参数汇总** ✅（2026-08-15）：`physical_inputs.derive_world_parameters()`
   聚合原始 + 衍生参数（辐照度/日照比/平衡温度/年长/太阳日/一年日数/季节长度/
   极圈与极点极昼时长/恒星寿命与演化进度/宜居带位置/卫星轨道周期与锁定状态），
   天文引擎 build 时输出 `layers/astronomy/derived/world_parameters.yaml`（优先用
   本次构建的内存恒星计算值，首次构建无需回读 stellar_derived.yaml）；gaia-m 输出
   与 `physical_params.md` 手算值逐项一致（g=10.28、太阳日 3.42 d、年 67 d、
   一年 19.6 太阳日、极圈 ±81°、极点极昼/夜 33.5 d、卫星公转 78 h），回归测试
   锚定这些值（`test_physical_inputs.py`）。② **文档模板渲染** ✅（2026-08-15）：
   新增 `doc_render.py`（SandboxedEnvironment + `SourceUndefined` 缺参源码回显 +
   `round0/1/2`、`hours`、`pct` filter）。参数表类文档写 Jinja2 占位符，在**读取时**
   （API `layer-documents`/`design-documents` 端点）与**静态导出时**从
   `world_parameters.yaml` 渲染——渲染产物不落盘、不进 git（纯函数缓存，非引擎产物）；
   分支沿继承链取自己的参数，覆写天文 input 未构建的分支不回退根世界参数而是降级。
   响应/导出 JSON 带 `rendered` 标志，缺参时前端显示横幅提示。gaia-m 5 个文档已模板化，
   锚定值渲染后与手写一致（`test_doc_render.py`），并顺带修正 `long_term_cycles.md`
   两处方案2 遗漏漂移（日照 656→899 W/m²）与 `giant_brightness.md` 898 截断（→899）。
   叙事类文档保留手写 + 局部引用。两阶段均完成，P1 关闭。

15. **天体数据双文件分裂与字段重复**（2026-08-15）— 天体信息分散在
    `astronomy/input/stellar.yaml`（stars/orbits/bodies 叙事）与
    `geological/input/planets.yaml`（权威物理参数 + 大气/水圈/岩石圈）两处：
    5 个物理字段 × 每个天体重复维护（单位还不同：radius_km vs R⊕），已发现
    3 处漂移（gaia-m：Aegis 反照率 0.34/0.343、Cadence 半径 2840/2867 km、
    Vigil 半径 2470/2485 km，均已按 planets.yaml 权威对齐修复）；前端被迫在
    `StellarSystemViewer` 里 merge + 按 id 去重、API 里有 `_normalize_body`
    单位换算补丁。**分裂本身保留**（分支系统依赖：l4-companion 在天文层覆写
    stellar.yaml、climate-dev/terrain-dev 在地质层覆写 planets.yaml），
    **重复用派生目录化解**：
    ① ✅ `physical_inputs.build_system_catalog()` + `check_body_field_consistency()`
    （0.1% 容差交叉校验，漂移告警），天文引擎 build 时输出
    `layers/astronomy/derived/system_catalog.yaml`（stars + orbits 透传 +
    逐天体合并条目：物理参数 planets.yaml 优先，附开普勒周期/辐照度/平衡
    温度/太阳日/潮汐锁定/宜居带位置；目标天体内嵌 `world_parameters`）；
    ② ✅ API `/worlds/{name}/system-catalog` + 静态导出三件套同步；
    3D 视图改读 catalog（删除前端 merge/dedup），WorldDetail 天文 tab 新增
    天体百科卡片面板；③ 📋 创作规范：共享物理字段以 planets.yaml 为权威，
    stellar.yaml 的 bodies 仅增补叙事/分类（本条目即规范出处）；④ 📋 远期：
    `dreamulator validate` 深度模式接入一致性校验、WorldDetail i18n。
16. **气候参数 per-world 特调违反「同物理」原则**（2026-08-15）— 目标：地球与 gaia-m
    用同一套物理（同一代码路径），只差输入参数（自转/光度/倾角/温室…），不做单世界
    特调。当前 gaia-m `terrain_config.yaml` 把若干「该从物理推导」的量手调成世界专属值：
    - `lat_gradient_earth_c=28`（全局参考应为 ~45）：本应是 Ω^0.3 标度律里的「地球参考
      ΔT」全局常数，gaia-m 却拿它当自己梯度旋钮压到 28（→ ΔT≈19.7°C，比公式该给的
      31.6°C 平得多），注释自述「恢复 52°N 北方南岸 / 60°S 亚南极沿海宜居」——命名地貌
      宜居性绑定了这个特调。**已决定暂留，登记为第二波物理审计「自由参数处置」对象**
      （audit-plan §三 A 可推导类）。
    - `hadley_extent_deg=90`、`polar_cell_start_deg=90`（单圈环流，GCM 证实无 Ferrel/极地胞）：
      ExoPlaSim Ω=0.31 的 mass streamfunction 全半球同号（单 Hadley 胞直抵极地、只在赤道变号），
      `storm_track_amplitude_mm=0`（无斜压风暴路径）。残留问题：90 应走 Held-Hou 标度
      φ_H ∝ (gHΔθ)^½/(Ωa)^½ 从 Ω 推导 vs 硬编码（climate-pipeline.md §6 TODO），
      归入「自由参数处置」A 可推导类。
    - 处置方式：M4 阶段先聚焦地球温度纬向形状；这些「该推导却被手调」的旋钮统一留待
      第二波物理审计的「自由参数处置」逐项裁决，不在 M4 零散单点修。
    - 配套：`lat_gradient_earth_c` 全局默认已从 40 → 45（地球实测 ΔT）；Earth 验证诊断
      三脚本 + `climate validate` 已统一走 `build_earth_validation_config()`（单一来源），
      `auto_lat_gradient`/`diffusive_heat_transport` 默认开启（与 gaia-m 同物理），
      `--no-*` 选项显式关闭以复现 legacy 手动 45 基线。
17. **降水管线三处 bug 已修 + 剩余调参**（2026-08-16）— 修参考数组后温度 corr 0.981
    达标，降水曾 corr 0.762。三处 bug 已修：
    - ✅ **地形降水误套海洋洋底**：`_rain[_q_mask]` 无 `is_land` 限制，海洋按洋底地形
      错误降水（中纬海洋 +800mm 过湿）。已改 `(_upwind_q > 0.5) & is_land`。
    - ✅ **ITCZ 用夏至位置**：`itcz_latitude(period/2)` 对地球返回 ~37°N，把对流雨带
      放到副热带。已改年均位置 0°N（年均太阳直射点=赤道）。
    - ✅ **缺风暴路径**：水汽扩散到不了极区，60°+ 降水缺失。已补中纬风暴路径
      （baroclinic cyclones），位置随 Hadley 边界、幅度随 Ω 缩放（同物理）。
    结果：降水 corr 0.762→0.805、Köppen 30类 26.7%→28.3%、群组 Kappa 0.439→0.457
    （>0.45 达标）。
    剩余调参（慢慢补）：① 中纬/亚热带海洋仍偏干（bias −347mm，30–60° 缺口 500–830mm）；
    ② ITCZ 年均 0°N 缺地球 ~6°N 的 NH 陆偏（thermal-equator bias）；③ gaia-m 基线
    需随本次降水改动重生成。
18. **热带 Af 偏少（单 ITCZ 缺双 ITCZ / 季风）**（2026-08-16）— 单 ITCZ 年均模型无法
    表达亚马逊的「双 ITCZ / 南美季风」：真实亚马逊干季（6–9 月 ITCZ 北移）仍被南半球
    次级辐合带覆盖、最干月 ~60–80mm 维持 Af；模型单 ITCZ 北移后把亚马逊甩到 19–28°
    之外，干季塌到 ~54mm，判成 Aw/Am。已修：ITCZ 迁移加海洋热惯性阻尼
    （`itcz_latitude_monthly` `damping=0.6`，迁移 ±23°→±14°），群组 Kappa 0.457→0.466；
    但 Af recall 仍仅 ~0.08。根治需「双 ITCZ」（南半球夏季次级辐合带）或季风动力学
    （季节风反转 + 内陆水汽输送），属新物理机制，慢修——与 #2 季风沙漠同源（都缺
    「季节风反转 + 内陆水汽输送」的季风机制）。
19. **潮差参数未入引擎（变量渲染缺口）**（2026-08-16）— 潮差 ~44 m 是 `tidal_effects.md`
    里的手工推导（Z = (M_p/M_m)(R⁴/a³) → 平衡潮 9.5/19.0 m → 共振 2.3× → ~44 m），
    `tidal_physics.py` 只算了潮汐**加热**（Peale & Cassen → 板块速度），
    `derive_world_parameters()` / `world_parameters.yaml` 无潮差字段。后果：ecology /
    geography / climate_zones / civilization 等文档的潮差值（~44 m、~25 km 潮汐平原）
    为**写死值**，无法用 doc_render 变量渲染。修复方向：在 `tidal_physics.py` 补潮差计算
    （Z、平衡潮、共振因子；输入 k₂/h₂/Q/e/a/R/H 均已存在于 stellar/planets/physical_params），
    接入 `world_parameters.yaml`，潮汐相关文档转 Jinja2 模板。

### 工程卫生

1. **Pillow `mode="I;16"` 弃用（Pillow 13，2026-10-15 移除）** — ✅ 已修复
   （Sprint A）：`map/export.py`×2、`map/elevation_codec.py`、`map/importer.py`
   共 4 处去掉显式 mode 参数（uint16 数组原生映射 I;16），测试 253 全绿、
   往返不变。## 八、内部文档链接

- `docs/design/architecture.md` — 项目架构（层级架构与分支管理）
- `docs/design/harness.md` — 守护轴总纲（校验/审计/设定维护：与生成轴正交；两个守护对象=引擎代码+世界设定；三级过期检测；决策记录台账）
- `docs/design/audit-plan.md` — 三波审计计划（守护轴之「守护引擎」实例；工程卫生/物理/架构；启动判据与交付物）
- `docs/design/geological-pipeline.md` — 地形生成管线技术参考
- `docs/design/map-system.md` — 地图系统架构
- `docs/design/climate-pipeline.md` — 气候引擎实现架构
- `docs/design/climate-validation.md` — 气候引擎验证指南
- `docs/design/ecology-layer.md` — 生态层设计方案（Whittaker 群系 + NPP + 可驯化标签）
- `docs/design/archive/ocean-currents-model.md` — 洋流系统设计方案（Stommel 流函数 + SST 修正 + 前端双语言图层）
- `docs/design/civilization-layer.md` — 文明层详细架构设计（三层半格式化架构）
- `docs/design/language-phylogeny.md` — 语言谱系子系统设计稿（待开发；语族树 ↔ 分支系统同构、借用边、地名词源分层、Abrams-Strogatz 语言竞争、比较法往返校验）
- `docs/design/myth-strata.md` — 神话层累数据模型设计稿（待开发；母题 UUID 实体、树+网络、层累机制库、物理锚定、上帝/研究双认知视角）
- `docs/usage/map-workflow.md` — 地图工作流指南
- `docs/usage/civmap-guide.md` — 文明地图使用指南
- `docs/usage/profiling.md` — 性能剖析与基准测试指南

---

*此文档将随开发进展持续更新。*
