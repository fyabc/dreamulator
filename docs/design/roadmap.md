# 开发路线图

> 最后更新：2026-08-06（v0.16.0；地理锚定 + 板块偏态化 + 测试 CI）
> 长期愿景与设计哲学见 [vision.md](vision.md)；竞品分析见 [competitor-analysis.md](competitor-analysis.md)；
> 文明层详细设计见 [civilization-layer.md](civilization-layer.md)。

---

## 一、当前状态快照（v0.16.0）

| 维度 | 状态 |
|------|------|
| 层级管线 | physics → chemistry → astronomy → geological → climate 全链路打通；ecology / civilization 为半结构化 input + LLM narrate |
| 性能 | gaia-m（100k 节点）全量构建 532 s → **98 s**（Numba JIT 噪声内核 + 全面向量化）；`build_profile.json` 仪表 + pytest-benchmark CI（`perf-dashboard` 分支） |
| 确定性 | 种子化 RNG + crc32 校验和，跨进程可复现 |
| 气候精度 | Köppen 群组准确率 53.9%（vs Beck 2018；A 类 33.3%、D 类 48.3%）；降水 RMSE 493 mm/yr |
| 样板世界 | gaia-m：100k 节点、72% 海洋、13 个 Köppen 类；均温 12.7 °C（v0.16.0 地理锚定重建，见 §六）；26 板 CV=0.97（偏态化）、海洋最深 −10484 m |
| 网格规模决策 | 保持 100k 节点（≈76 km/胞，已达世界构建工具上限、中分辨率 GCM 水平）；优先投入模型保真度而非分辨率 |

---

## 二、Phase 总览

| Phase | 主题 | 状态 | 说明 |
|-------|------|------|------|
| 1 | 核心脚手架 | ✅ v0.1.0 | 数据模型、CLI、世界管理 + 分支、天文学引擎、前端骨架；见 §三 |
| 2 | 前端可视化 | ✅ v0.2.0–0.6.0 | 地图系统（栅格+Voronoi）、3D 恒星系、CivMap、3D 球面地球；见 §三 |
| 2.5 | 地形真实感增强 | ✅ v0.7.0–0.8.0 | 板块剖分（Cortial 2019）、地形合成、海岸线、噪声标定；见 §三 |
| 3A | 气候与流体引擎 | 🚧 | 核心已合并（v0.9.0），调优进行中；见 §四 |
| 3B | 侵蚀与河流生成 | 📋 | D8 流向 / 流量累积 / 水力侵蚀 / 沉积物搬运（`river_generator.py`、`erosion.py` 为占位） |
| 3C | 文明层半格式化管理 | 📋 | 事件溯源 + 状态机，设计见 [civilization-layer.md](civilization-layer.md) |
| 3D | 世界线合并可视化 Diff | 📋 | DAG 影响半径分析 / Lyapunov 混沌预警 / 蒙特卡洛不确定性 |
| 3E | LLM 叙事引擎 | 🚧 | 基础 `narrate` 已实现；史诗叙事桥（`narrative_bridge.py`）未做 |

---

## 三、Phase 1–2.5 已完成历程（2026-08-04 补录）

> 本节重建 Phase 2.5 之前的开发记录。原 roadmap 文件自 2026-07-24 创建时从
> Phase 2.5 起笔，此前阶段的划分沿用 v0.2.0 时期 README 路线图（Phase 1 脚手架
> → Phase 2 前端可视化），细节散见 CHANGELOG。

### Phase 1 — 核心脚手架（v0.1.0，2026-05-30）✅

| 模块 | 交付 |
|------|------|
| 项目骨架 | Python 后端（uv + hatchling）+ TypeScript 前端（Vite + React） |
| 数据模型 | Pydantic 层级架构（physics → chemistry → astronomy → geological → climate → ecology → civilization） |
| CLI | init / list / info / validate / build / branch / schema / serve |
| 世界管理 | CRUD + 分支系统（层分叉 + 继承） |
| 引擎 | 天文学引擎：恒星物理（质量/光度/温度/寿命）+ 轨道力学 |
| 服务 | FastAPI + Vite 代理开发模式；GitHub Pages 静态部署；学科知识库文档框架 |

### Phase 2 — 前端可视化（v0.2.0–v0.6.0，2026-06-29 → 07-24）✅

| 版本 | 里程碑 |
|------|--------|
| v0.2.0 | 地图系统（栅格高度图 2048×1024 + Voronoi 语义网络 ~5000 cells）、全页地图编辑器、WebGPU/WebGL 渲染、圆柱投影无限环绕、3D 恒星系视图（R3F 轨道动画）、conlang 工具、AI narrate（Claude API 流式）、`_inherit` 分支合并 |
| v0.3.0 | CivMap 文明地图（真实地球行政区划 + 架空领土涂色，Leaflet + GeoJSON/LFS）、文明层 Markdown 文档系统、ERE-if 架空历史分支 |
| v0.4.0 | 多投影（等距圆柱/Mollweide/Robinson）、GPU 地形渲染、坐标系统重构（mapCenter + zoom）、KD-tree 命中测试、Cell-ID 调色板图层提速、NOAA/ESRI 混合配色 |
| v0.5.0 | 3D 球面地球视图（GlobeViewer：纹理贴球 + 大气辉光壳 + 缩小过渡特效）、恒星系行星真实纹理 |
| v0.6.0 | 球面多边形高亮/选中、四图层透明度叠加、海岸线自动检测、经纬网格与极轴、LUT 1024 级配色 |

### Phase 2.5 — 地形真实感增强（v0.7.0–v0.8.0，2026-07-25 → 27）✅

**背景**：CVT 管线虽能生成基本海陆分布，但与真实地球差异明显，需先修复底层
问题再进入气候推演（3A），否则错误地形会级联放大到气候/文明层。

| 子任务 | 结果 |
|--------|------|
| 2.5a 大陆形状与分布 | ✅ Cortial 2019 Voronoi + Euler 极旋转 + 时间演化（替代洪水填充）；中低纬大陆更大、极区以海洋为主；可选超大陆初始态模板再自动裂解 |
| 2.5b 山脉与地形特征 | ✅ 热点火山链 + 地壳穹隆（不再局限于板块边界）；不对称剖面（迎风坡陡/背风坡缓）+ 更高峰谷比；汇聚/离散/转换边界典型地貌组合；高纬/高海拔冰川地貌（U 形谷、冰斗、角峰） |
| 2.5c 海岸线与大陆架 | ✅ 指数衰减大陆架深度剖面；河流出口 + 潮差参数的峡湾/溺谷/三角洲；汇聚边界外岛弧 + 海沟对 |
| 2.5d 噪声参数标定 | ✅ 对比真实 DEM（ETOPO1/GEBCO）功率谱标定 amplitude/persistence；各向异性噪声（沿构造走向拉伸）；高程直方图双峰性/粗糙度-尺度/流域统计 |
| 2.5e 标准测试世界 | ✅ seed=42, num_nodes=32768，每次改动对比快照 |

> 自动化地形质量检查（CI 集成、噪声功率谱验证等）暂不实施——地形效果稳定前
> 难以定义有效的定量指标。实际工期约 3–4 周。

---

## 四、Phase 3A 气候引擎子状态

详见 [climate-engine.md](climate-engine.md)。输出：temperature.png / precipitation.png / koppen.json / climate_metadata.json。

| 功能 | 状态 | 说明 |
|------|------|------|
| 能量平衡模型（EBM） | ✅ | `climate_physics.py:equilibrium_temperature()` |
| 纬度 + 海拔温度修正 | ✅ | sin²(φ) 纬度剖面 + 湿度绝热直减率 |
| Hadley/Ferrel/Polar 风带 | ✅ | `climate_physics.py:hadley_cell_wind()`（边界硬编码 30°/60°，待 3A.3a） |
| 地形降水 + 雨影 | ✅ | BFS 水汽传输，降水 RMSE 493 mm/yr |
| 陆地蒸散循环 | ✅ | 土壤+植被蒸发回收 |
| ITCZ 对流降水 | ✅ | 热带辐合带 + 局地热对流 |
| Köppen 气候分类 | ✅ | 群组准确率 53.9%（v0.11.0，vs Beck 2018） |
| ETOPO1 真实地球验证 | ✅ | `earth/climate-dev` 分支 + `scripts/validate_climate.py` |
| 热带降水修正（3A.1） | ✅ | v0.11.0：ITCZ 增强、热带对流 ×2、降水底线 |
| 季节变化（3A.2） | 🚧 | 简化季节项已生效（倾角驱动，`climate_simulator` 内置）；v0.11.0 的全光照驱动模块为零引用孤儿，已于 v0.14.0 删除；D 类群组准确率 48.3%（离线验证） |
| 洋流 + 温度精细化（3A.3） | 📋 | 风生洋流 / 冰盖反照率 / 云反馈 |
| 慢自转经向输送（3A.3a） | 🚧 | **新增（2026-08）**：ΔT_lat 为地球标定 40 °C，与自转无关；科氏力只进入地转风、不影响温度场。慢自转行星（gaia-m Ω=0.31 Ω⊕）经向输送更强，ΔT 应更低、Hadley 胞应扩展（~Ω⁻¹/² 标度）。✅ 短期已完成：`lat_gradient_c` / `hadley_extent_deg` / `polar_cell_start_deg` 参数化 + gaia-m 调参（30/55/75，均温 9.2→14.4 °C）；中期：ΔT(Ω) 参数化 + 扩散经向热输送 |
| 空间格局精细化（3A.4） | 📋 | 西岸/东岸不对称、雨影精确化、内陆干旱梯度 |
| 海洋气候分区（3A.5，Longhurst） | 📋 | 海洋省份分类 |
| 恒星/轨道参数查找（3A.6） | ✅ | v0.14.0：`engine/physical_inputs.py` 统一解析（卫星感知的恒星查找 + 开普勒轨道周期），替换旧硬编码 1.0 AU / 1.0 L☉ |
| 潮汐锁定经度效应（3A.7） | 📋 | 次恒星点热源 / 经度不对称。gaia-m 温室预算已为此预留 +3 K（次行星半球加温预期 +2–4 K） |

**竞品对比**：当用户问"如果自转反向会怎样"，Azgaar 无法回答，Dreamulator 可精确模拟。

---

## 五、Phase 3B–3E 要点

- **3B 侵蚀与河流**：D8 流向 → 流量累积（集水面积→河宽）→ 水力侵蚀（河道下切+坡面）→ 沉积物搬运（三角洲）。
- **3C 文明层**：三层半格式化架构（实体修饰器 / 事件流 / LLM 渲染层）+ 策略模式建模（HANDY / SDT / Tainter / 标签驱动），见 [civilization-layer.md](civilization-layer.md)。
- **3D 世界线 Diff**：地理热力图 + 文明状态对比；DAG 影响半径、混沌预警、蒙特卡洛置信区间。
- **3E 叙事引擎**：`narrative_bridge.py` — LLM 读取 YAML/JSON 数据变动，生成符合逻辑的世界线编年史。

---

## 六、近期工作：gaia-m 样板世界改造（2026 Q3）

目标：把 gaia-m 打造成物理自洽、内容丰富、可支撑 B 站系列视频（见
`private/plans/video/bilibili-video-plan.md`）的样板世界。

| 项目 | 内容 | 状态 |
|------|------|------|
| 天文：卫星系统 | 新增 4:2:1 拉普拉斯共振卫星链（Cadence/Vigil），为 e_m=0.0025 提供 60 亿年尺度的共振泵浦机制（此前设定无泵浦源） | ✅ v0.15.0 |
| 天文：轨道校准 | Aegis 内移 0.2795 → 0.2722 AU（混合变暖路径），Boreal/Glacis 随共振链同步缩放 | ✅ v0.15.0 |
| 地质：海陆分布翻案 | 潮汐物理要求向星/背星点为深海、侧点/极点偏陆；旧设定（大潮点大陆）被推翻，改为不对称混合案 | ✅ 地形引擎已按新设定生成：`geography.yaml` 地理锚定（大陆锚点/陆地偏置场 + 全局阈值 + 构造后重锚定），见 terrain-pipeline.md §3.5；海岸线平直为已知限制 |
| 气候：温度校准 | 温室 72 → 75 K（保留 3 K 给次行星半球加温）；lat_gradient_c 与 Hadley 边界参数化（3A.3a 短期），均温 9.2 → 14.4 °C | ✅ v0.15.0 |
| 文明：种子设计 | civilizations.yaml 填充（2–3 文明 + 地理锚点 + 大事年表）；新海陆分布已就绪（可作为锚点） | 📋 |
| 视频素材 | 板块漂移/气候/文明 timelapse、3D 自动旋转、纯净视图模式 | 📋 |

---

## 七、实施优先级

| 优先级 | 模块 | 预计工作量 | 关键性 |
|--------|------|-----------|--------|
| **P0** | gaia-m 样板世界改造（§六） | 进行中 | ★★★★★ |
| **P0** | 气候 3A.3a：慢自转经向输送参数化 | 短期 0.5–1 周 / 中期 2–3 周 | ★★★★★ |
| P0 | 气候 3A.3：温度精细化（冰盖/云/洋流） | 2 周 | ★★★★ |
| P1 | 气候 3A.7：潮汐锁定经度效应（次行星半球加温） | 1–2 周 | ★★★★ |
| P1 | 气候 3A.4：空间格局精细化 | 1.5–2 周 | ★★★★ |
| P1 | 文明层半格式化 Schema（3C） | 1–2 周 | ★★★★ |
| P1 | 前端气候可视化补全（风场箭头） | 1 周 | ★★★★ |
| ~~地图图层系统重构~~ | ✅ 已完成（2026-08-05）：kind z 序合成 + 分组多选面板（底图/专题 radio + 填充/特征多选）+ 烘焙-显示分离（每层独立 DataTexture，透明度=uniform 零重烘；无叠加层时直采底图与旧管线逐字节一致）。含加载去重（KD-tree/烘焙缓存共享、海岸线单 pass），见 `private/plans/map-layer-refactor.md` | — | ★★★★★ |
| P1 | 视频素材功能（timelapse / 自动旋转 / 纯净视图） | 2–3 周 | ★★★★ |
| P1 | LLM 叙事桥（3E 史诗叙事） | 2 周 | ★★★★ |
| P2 | 水力侵蚀 + 河流（3B） | 2–3 周 | ★★★ |
| P2 | 地质时间轴可视化（板块漂移回放） | 3–4 周 | ★★★ |
| P2 | 世界线 Diff 可视化（3D） | 2 周 | ★★★ |
| ~~海岸线渲染性能~~ | ✅ 已由图层重构化解：旧问题为每次图层变化 CPU 全量合成 ~6s 首帧；现图层烘焙一次并跨路由缓存，透明度仅 GPU uniform，无叠加层时免合成 | — | — |
| P3 | AI 顾问模式 / 实时协作 / 世界导出包 | 见 vision.md §9 | ★★ |

---

## 八、已知技术债务

2026-08-04 更新（v0.14.0 后）。按"功能性 → 工程卫生"排序。

### 功能性

1. **潮汐锁定经度效应缺失**（Phase 3A.7）— 无昼夜半球 / 次恒星点热源 / 经度
   不对称，潮汐锁定世界只能产出纬向对称近似气候。gaia-m 温室预算已预留 +3 K
   等待该效应落地。
2. ~~`dreamulator terrain generate` 旧版输出路径~~ → ✅ 已修复（2026-08-06）。
   两处问题：(a) 输出写 legacy `layers/geological/input/maps/`，与顶层 `maps/`
   布局不一致；(b) **不加载 geography.yaml**——只有 geological 引擎
   （`engine/geological.py`）加载，绕过 DAG 的生成会静默丢失全部命名海陆锚定
   （2026-08-06 实际踩中：直接调 `run_terrain_pipeline` 重建 gaia-m 后地理特征
   全部丢失）。现 `_load_terrain_config` 与引擎同源加载 geography.yaml，输出改
   顶层 `maps/`（branch 同理）。
3. ~~无测试 CI~~ → ✅ 已修复（2026-08-06）。新增 `.github/workflows/tests.yml`：
   pytest 硬门槛（全量、--all-extras）+ ruff 硬门槛（F,E9 基线，先清完 19 个
   F 类存量使门槛可立）+ mypy 报告档（~140 项注解债务清偿后转硬门槛，见工程
   卫生 #2）。触发：src/tests/pyproject/uv.lock 变更的 PR 与 main 推送。
4. **热带高地温度偏冷（直减率标定）** — 6.5 °C/km 全球统一，赤道 2500 m
   即算出 ET（gaia-m cell #50021 实例）；地球同位置为 Cfb/Cwb（基多 2850 m
   13.5 °C），热带有效直减率仅 ~4.4–5 °C/km（潜热释放），ET 边界实际在
   3500–4000 m。模型把热带苔原线压低约 1200 m。方向：纬度/湿度依赖的有效
   直减率，或按自由大气廓线修正；另无近海海洋性温度调节（距海远近不影响温度）。
5. **海岸线过于平直** — 海陆判定在 cell 粒度（~76 km @ 100k cells），海岸线
   沿 cell 边延伸、缺乏分形细节（用户反馈，2026-08）。方向（任选/组合）：
   更高 cell 密度；海岸带高频噪声扰动（沿海岸对陆/海判定做 sub-cell 噪声阈值）；
   或在导出栅格时对海岸线做分形细分。与地理锚定（§3.5）兼容——锚定给出宏观
   格局，此改进只增海岸微观粗糙度。
5. **地形：均匀高原** — `terrain_synthesizer` 每板块叠加
   [−1500,+1500] m **均匀**偏移（plate_elevation_spread_m），高偏移板块成为
   整板 2000 m+ 的平坦高原（gaia-m 实测：大陆板块均值 2100–2290 m，
   56–71% 陆地 >2000 m）；需板内空间变化的偏移/更强侵蚀塑造真实大陆
   （低地为主 + 盾地/造山带）。
6. **板块大小分布偏态化（已完成）** — ✅ 2026-08-06。三段式方案：
   (a) `select_plate_seeds` 可变密度采样（对数均匀 size-factor e^{U(±0.8)}），
   初始剖分偏态（CV≈0.44、max/min≈6.9）；(b) `_partition_cells` 裂解改加权
   Dijkstra（对数均匀生长权重），碎片不等大；(c) **乘法加权 Voronoi 重分区**
   （关键）——无权重的"质心→最近种子"重采样是 Lloyd 迭代，吸引子为等面积
   CVT，会把偏态洗掉（此前 50 步后 CV 0.44→0.22）；现每个板块以出生面积为
   持久权重（`plate_weight`，随裂解/清理同步），重分区波前代价 cost/wᵢ，
   面积比 ∝ 权重比；规定权重的 Lloyd 型迭代吸引子是加权 CVT，偏态得以保持。
   最终 boundary warp 同传权重，避免末次重分区再均匀化。
   gaia-m 实测：25 板，演化后 CV 0.22→**0.87**（地球主板块 ≈0.9），
   max/min 3.1→**1818**（去除 6-cell 微板块 ≈100；地球主板块 ≈100×、
   含微板块 ≈8000×）；最大板 10909 cell（~2.7× 均值）+ 完整小板尾
   （1969→6 cell；6 cell≈3.5 万 km²，复活节岛微板块尺度）。
   若需更强偏律：加大种子 size-factor / 裂解权重范围，或直接按截断幂律抽取
   出生权重——机制已就位，只差参数（见 terrain-pipeline.md §3.2、§D.11）。
7. **板块边界曲率增强（已完成）** — ✅ 已修复（2026-08-06）。板块边界原是
   Voronoi 测地边（长而平直）；现 boundary_warp 用**低频 fBm**（波长≈板块尺度）
   扭曲距离度量（`build_cell_cost`），边界弯曲成岛弧状弧形而非细碎锯齿
   （gaia-m boundary_warp=0.9）。（注：板块数过少 bug 已修——重分区命名错配 +
   needs_resample 每步触发，修后 6→25 板。）
8. ~~缺少俯冲海沟，海洋最大深度偏低~~ → ✅ 已修复（2026-08-05）。原
   `_asymmetric_boundary_effects` 海沟仅 −1400 m 且未限定洋壳；现改为仅洋壳、
   俯冲侧 ~7 km 减压（`_TRENCH_RELIEF_M`），gaia-m 海洋最深 −4758 → −10484 m
   （地球海沟 −8~−11 km 区间）。
9. **大裂谷海过于对齐经线、边界平直** — 当前用单个拉长偏置场（elongation=11、
   bearing=0），产生笔直经向裂谷。应似东非大裂谷/红海：蜿蜒走向、不规则边界、
   局部断块隆起/异常塌陷。已用"多段错列偏置场"初步缓解（见 gaia-m
   geography.yaml）；彻底方案需 geography 逻辑支持"弯曲裂谷带"原语。
   **另一脆弱机制（2026-08-06 实测）**：锚定只钉住地壳类型，地形合成阶段的
   汇聚边界造山抬升可叠加在锚定的海洋/裂谷 cell 上——gaia-m 重建中大裂谷海
   中南段恰有汇聚边界横穿（距 78 km、汇聚 5.9 cm/yr），+4000 m 级抬升把裂谷
   推上海面（+927 m）。方向：地形合成对强负偏置场（authored 裂谷/海盆）抑制
   汇聚抬升，让锚定贯通到高程而不仅是地壳类型。

### 工程卫生

1. **全仓 ruff 存量 266 项**（ruff 0.15.15）— 以风格类为主：N806(51)、B904(48)、
   B008(29)、E501(29)、UP*(36)、TC*(26)、SIM*(21)。注意：**UP042 改变
   `__str__` 语义**（Python 3.12 StrEnum），不可批量自动修；B008 多为框架惯用法
   误报，宜按规则配置 per-file ignore 而非逐处改码。
   **2026-08-06 进展**：F 类（未用变量/导入、F541）19 项已清零，tests.yml 以
   `--select F,E9` 立硬门槛防回潮；下一步可按 E501→SIM→TC 顺序逐族清偿并
   收紧门槛。
2. **mypy 存量 147 项 / 30 文件** — 热点：terrain_synthesizer.py(27)、
   narrator.py(13)、engine/climate.py(13)、cli.py(9)、api_routes/worlds.py(9)。
   补齐 `CVTMesh` / mesh 加载辅助函数的类型注解可消除大部分。
3. **build 跳过判定只看输出存在** — `pipeline._outputs_exist` 不校验输入指纹
   （terrain_config.yaml / geography.yaml / 代码变更均不触发失效），输入变化后
   输出不会自动重生，必须 `--force`。`ComputationManifest` 模型已定义但未接入
   跳过判定。2026-08-06 实际踩中：手动重建地图后 build 把 geological 跳过，
   气候引擎在错误地图上运行。

### 已清偿（v0.14.0）

- ~~气候引擎恒星/轨道参数硬编码（3A.6）~~ → `engine/physical_inputs.py`
  卫星感知统一解析。
- ~~`climate_seasonality.py` 孤儿模块（3A.2）~~ → 已删除。

---

## 九、内部文档链接

- `docs/design/architecture.md` — 项目架构（层级架构与分支管理）
- `docs/design/terrain-pipeline.md` — 地形生成管线技术参考
- `docs/design/map-system.md` — 地图系统架构
- `docs/design/climate-engine.md` — 气候引擎实现架构
- `docs/design/climate-validation.md` — 气候引擎验证指南
- `docs/usage/map-workflow.md` — 地图工作流指南
- `docs/usage/civmap-guide.md` — 文明地图使用指南
- `docs/usage/profiling.md` — 性能剖析与基准测试指南
- `docs/design/map_system_design.md` — 早期 ADR（已归档）

---

*此文档将随开发进展持续更新。*
