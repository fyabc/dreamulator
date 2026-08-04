# 开发路线图

> 最后更新：2026-08-04（v0.14.0；gaia-m 样板世界改造进行中）
> 长期愿景与设计哲学见 [vision.md](vision.md)；竞品分析见 [competitor-analysis.md](competitor-analysis.md)；
> 文明层详细设计见 [civilization-layer.md](civilization-layer.md)。

---

## 一、当前状态快照（v0.14.0）

| 维度 | 状态 |
|------|------|
| 层级管线 | physics → chemistry → astronomy → geological → climate 全链路打通；ecology / civilization 为半结构化 input + LLM narrate |
| 性能 | gaia-m（100k 节点）全量构建 532 s → **98 s**（Numba JIT 噪声内核 + 全面向量化）；`build_profile.json` 仪表 + pytest-benchmark CI（`perf-dashboard` 分支） |
| 确定性 | 种子化 RNG + crc32 校验和，跨进程可复现 |
| 气候精度 | Köppen 群组准确率 53.9%（vs Beck 2018；A 类 33.3%、D 类 48.3%）；降水 RMSE 493 mm/yr |
| 样板世界 | gaia-m：100k 节点、72% 海洋、13 个 Köppen 类；均温 14.4 °C（v0.15-dev 校准后，见 §五） |
| 网格规模决策 | 保持 100k 节点（≈76 km/胞，已达世界构建工具上限、中分辨率 GCM 水平）；优先投入模型保真度而非分辨率 |

---

## 二、Phase 总览

| Phase | 主题 | 状态 | 说明 |
|-------|------|------|------|
| 2.5 | 地形真实感增强 | ✅ v0.7.0–0.8.0 | 板块剖分（Cortial 2019）、地形合成、海岸线、噪声标定；详见 CHANGELOG |
| 3A | 气候与流体引擎 | 🚧 | 核心已合并（v0.9.0），调优进行中；见 §三 |
| 3B | 侵蚀与河流生成 | 📋 | D8 流向 / 流量累积 / 水力侵蚀 / 沉积物搬运（`river_generator.py`、`erosion.py` 为占位） |
| 3C | 文明层半格式化管理 | 📋 | 事件溯源 + 状态机，设计见 [civilization-layer.md](civilization-layer.md) |
| 3D | 世界线合并可视化 Diff | 📋 | DAG 影响半径分析 / Lyapunov 混沌预警 / 蒙特卡洛不确定性 |
| 3E | LLM 叙事引擎 | 🚧 | 基础 `narrate` 已实现；史诗叙事桥（`narrative_bridge.py`）未做 |

---

## 三、Phase 3A 气候引擎子状态

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

## 四、Phase 3B–3E 要点

- **3B 侵蚀与河流**：D8 流向 → 流量累积（集水面积→河宽）→ 水力侵蚀（河道下切+坡面）→ 沉积物搬运（三角洲）。
- **3C 文明层**：三层半格式化架构（实体修饰器 / 事件流 / LLM 渲染层）+ 策略模式建模（HANDY / SDT / Tainter / 标签驱动），见 [civilization-layer.md](civilization-layer.md)。
- **3D 世界线 Diff**：地理热力图 + 文明状态对比；DAG 影响半径、混沌预警、蒙特卡洛置信区间。
- **3E 叙事引擎**：`narrative_bridge.py` — LLM 读取 YAML/JSON 数据变动，生成符合逻辑的世界线编年史。

---

## 五、近期工作：gaia-m 样板世界改造（2026 Q3）

目标：把 gaia-m 打造成物理自洽、内容丰富、可支撑 B 站系列视频（见
`private/plans/video/bilibili-video-plan.md`）的样板世界。

| 项目 | 内容 | 状态 |
|------|------|------|
| 天文：卫星系统 | 新增 4:2:1 拉普拉斯共振卫星链，为 e_m=0.0025 提供 60 亿年尺度的共振泵浦机制（此前设定无泵浦源） | 🚧 |
| 天文：轨道校准 | Aegis 内移 0.2795 → 0.2722 AU（混合变暖路径），Boreal/Glacis 随共振链同步缩放 | 🚧 |
| 地质：海陆分布翻案 | 潮汐物理要求向星/背星点为深海、侧点/极点偏陆；旧设定（大潮点大陆）被推翻，改为不对称混合案 | 🚧 |
| 气候：温度校准 | 温室 72 → 75 K（保留 3 K 给次行星半球加温）；lat_gradient_c 与 Hadley 边界参数化（3A.3a 短期） | 🚧 |
| 文明：种子设计 | civilizations.yaml 填充（2–3 文明 + 地理锚点 + 大事年表），依赖新海陆分布 | 📋 |
| 视频素材 | 板块漂移/气候/文明 timelapse、3D 自动旋转、纯净视图模式 | 📋 |

---

## 六、实施优先级

| 优先级 | 模块 | 预计工作量 | 关键性 |
|--------|------|-----------|--------|
| **P0** | gaia-m 样板世界改造（§五） | 进行中 | ★★★★★ |
| **P0** | 气候 3A.3a：慢自转经向输送参数化 | 短期 0.5–1 周 / 中期 2–3 周 | ★★★★★ |
| P0 | 气候 3A.3：温度精细化（冰盖/云/洋流） | 2 周 | ★★★★ |
| P1 | 气候 3A.7：潮汐锁定经度效应（次行星半球加温） | 1–2 周 | ★★★★ |
| P1 | 气候 3A.4：空间格局精细化 | 1.5–2 周 | ★★★★ |
| P1 | 文明层半格式化 Schema（3C） | 1–2 周 | ★★★★ |
| P1 | 前端气候可视化补全（风场箭头） | 1 周 | ★★★★ |
| P1 | 视频素材功能（timelapse / 自动旋转 / 纯净视图） | 2–3 周 | ★★★★ |
| P1 | LLM 叙事桥（3E 史诗叙事） | 2 周 | ★★★★ |
| P2 | 水力侵蚀 + 河流（3B） | 2–3 周 | ★★★ |
| P2 | 地质时间轴可视化（板块漂移回放） | 3–4 周 | ★★★ |
| P2 | 世界线 Diff 可视化（3D） | 2 周 | ★★★ |
| P2 | 海岸线渲染性能（2M 像素 compositing ~6s 首帧） | 待调研 | ★★ |
| P3 | AI 顾问模式 / 实时协作 / 世界导出包 | 见 vision.md §9 | ★★ |

---

## 七、已知技术债务

2026-08-04 更新（v0.14.0 后）。按"功能性 → 工程卫生"排序。

### 功能性

1. **潮汐锁定经度效应缺失**（Phase 3A.7）— 无昼夜半球 / 次恒星点热源 / 经度
   不对称，潮汐锁定世界只能产出纬向对称近似气候。gaia-m 温室预算已预留 +3 K
   等待该效应落地。
2. **`dreamulator terrain generate` 旧版输出路径** — CLI 仍写
   `layers/geological/input/maps/`（cli.py），与 v0.10.0 统一的顶层 `maps/`
   布局不一致，会产出与正式数据不混用的重复副本。补气候数据请用
   `dreamulator build <world> --only climate`，勿用此命令。
3. **无测试 CI** — pytest 仅本地运行；CI 只有 benchmarks.yml 与 deploy-pages.yml。
   建议新增 tests.yml（pytest + ruff + mypy）。
4. **热带高地温度偏冷（直减率标定）** — 6.5 °C/km 全球统一，赤道 2500 m
   即算出 ET（gaia-m cell #50021 实例）；地球同位置为 Cfb/Cwb（基多 2850 m
   13.5 °C），热带有效直减率仅 ~4.4–5 °C/km（潜热释放），ET 边界实际在
   3500–4000 m。模型把热带苔原线压低约 1200 m。方向：纬度/湿度依赖的有效
   直减率，或按自由大气廓线修正；另无近海海洋性温度调节（距海远近不影响温度）。
5. **地形：均匀高原与板块过度合并** — (a) `terrain_synthesizer` 每板块叠加
   [−1500,+1500] m **均匀**偏移（plate_elevation_spread_m），高偏移板块成为
   整板 2000 m+ 的平坦高原（gaia-m 实测：大陆板块均值 2100–2290 m，
   56–71% 陆地 >2000 m）；需板内空间变化的偏移/更强侵蚀塑造真实大陆
   （低地为主 + 盾地/造山带）。(b) `tectonic_steps: 50`（preview 档）+
   3–15 cm/yr 板块速度 → 20 初始板块吞并合并到只剩 6 个；需限制合并速率
   或提高步数/缩小 dt。附带：map.yaml `num_plates` 应记录演化后实际数量。

### 工程卫生

1. **全仓 ruff 存量 266 项**（ruff 0.15.15）— 以风格类为主：N806(51)、B904(48)、
   B008(29)、E501(29)、UP*(36)、TC*(26)、SIM*(21)。注意：**UP042 改变
   `__str__` 语义**（Python 3.12 StrEnum），不可批量自动修；B008 多为框架惯用法
   误报，宜按规则配置 per-file ignore 而非逐处改码。
2. **mypy 存量 147 项 / 30 文件** — 热点：terrain_synthesizer.py(27)、
   narrator.py(13)、engine/climate.py(13)、cli.py(9)、api_routes/worlds.py(9)。
   补齐 `CVTMesh` / mesh 加载辅助函数的类型注解可消除大部分。

### 已清偿（v0.14.0）

- ~~气候引擎恒星/轨道参数硬编码（3A.6）~~ → `engine/physical_inputs.py`
  卫星感知统一解析。
- ~~`climate_seasonality.py` 孤儿模块（3A.2）~~ → 已删除。

---

## 八、内部文档链接

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
