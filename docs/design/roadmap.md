# 开发路线图

> 最后更新：2026-10-21（main 新增全球画布链：S2 外存水文与 S3 区域裁窗，
> 技术参考见 [canvas-hydrology.md](pipelines/canvas-hydrology.md)；地质层重写批次待交付合并。
> v1.1.0 发版内容：程序化云纹理 `export clouds`、区域包查看页 `/packs`、
> 2D 地图收敛为等距圆柱单投影、nacrea 轨道集合收尾与两档正典（洛夫数 k₂=0.20/h₂=0.40、
> Q≈445、τ_e 9.2 Myr）、earth 板块运动 PB2002 欧拉极修正；地质时间轴研究线 G1–G3 入库
> （proposals/geological-timeline.md + `paleo_*` 模块，未接入 CLI/API/前端）。
> v1.0.x 及更早版本详情见 CHANGELOG）
> 长期愿景与设计哲学见 [vision.md](proposals/vision.md)；竞品分析见 [competitor-analysis.md](competitor-analysis.md)；
> 文明层详细设计见 [civilization-layer.md](proposals/civilization-layer.md)；
> 生态层设计见 [ecology-layer.md](proposals/ecology-layer.md)；洋流系统见 [ocean_currents.md](../knowledge/climatology/ocean_currents.md)（物理）与 [climate-pipeline.md §6](pipelines/climate-pipeline.md)（实现）；
> 文明种子见 `data/worlds/nacrea/layers/civilization/input/civilizations.yaml`。

---

## 一、当前状态快照（v1.1.0）

| 维度 | 状态 |
|------|------|
| 层级管线 | physics → chemistry → astronomy → geological → climate → ecology 全链路打通；civilization 新增宜居/农业 derived 引擎（`engine/civilization.py`），3C 半格式化 Schema 与 LLM narrate 待推进 |
| 性能 | nacrea（200k）全量 ~13 min（地质 ~230 s + 气候 ~510 s（GW6-on）+ 生态 5 s）；1M 节点 41 min；`build_profile.json` 仪表 + pytest-benchmark CI |
| 确定性 | 种子化 RNG + crc32 校验和，跨进程可复现 |
| 气候精度 | Köppen 分布匹配 **68.9%**（vs Beck 2018，GW6-on validate 口径）；逐格空间一致率 28.0%；T 纬向 RMSE 2.08 °C。三条主病均在输送场（P 逐格 R² −0.78 / 风 R² −0.43 / 洋流 6% of SODA——水汽路由/定常结构/风应力旋度），机制轮挂起、输送场全局重标定轮为下一候选 |
| 样板世界 | nacrea：200k 节点（~51 km/cell）、~72% 海洋、均温 14.4 °C（温室 62 K）；季节振幅 √P 两臂后陆地 p50 4.0 K |
| 网格规模 | 主力分辨率 **200k**；盘上 msgpack.gz + 几何/气候分离存储双文件（−41%），worker 零拷贝 + ETag/304 |
| 未发布（main） | 全球画布链 S2 外存水文与 S3 区域裁窗已并入（`887cdc1`）；地质层重写批次（造山带格子平均高程、历史契约）待交付合并，nacrea 数据冻结后再发布 |

---

## 二、Phase 总览

| Phase | 主题 | 状态 | 说明 |
|-------|------|------|------|
| 1 | 核心脚手架 | ✅ v0.1.0 | 数据模型、CLI、世界管理 + 分支、天文学引擎、前端骨架；见 CHANGELOG.md |
| 2 | 前端可视化 | ✅ v0.2.0–0.6.0 | 地图系统（栅格+Voronoi）、3D 恒星系、CivMap、3D 球面地球；见 CHANGELOG.md |
| 2.5 | 地形真实感增强 | ✅ v0.7.0–0.8.0 | 板块剖分（Cortial 2019）、地形合成、海岸线、噪声标定；见 CHANGELOG.md |
| 3A | 气候与流体引擎 | 🚧 | 核心已合并（v0.9.0），调优进行中；见 三 |
| 3B | 侵蚀与河流生成 | 🚧 | 河网已落地（D8 → `river_id`/`river_order` 矢量图层）；**流水侵蚀 2026-08-26 已从 200k 移除**（尺度不匹配，§四 3B），河谷雕刻归 Gaea 局地精修 |
| 3B.5 | 生态层：气候→群系→承载力 | 🚧 | Whittaker + NPP + 可驯化标签 ✅（v0.20.0，含三个专题图层）；区域连通物种分布（P1）、食物网（P2）、异星物种推演（P3，见 [ecology-layer.md](proposals/ecology-layer.md) §3.5） |
| 3C | 文明层半格式化管理 | 📋 | 事件溯源 + 状态机，设计见 [civilization-layer.md](proposals/civilization-layer.md) |
| 3D | 世界线合并可视化 Diff | 📋 | DAG 影响半径分析 / Lyapunov 混沌预警 / 蒙特卡洛不确定性 |
| 3E | LLM 叙事引擎 | 🚧 | 基础 `narrate` 已实现；史诗叙事桥（`narrative_bridge.py`）未做 |

---

## 三、Phase 3A 气候引擎子状态

详见 [climate-pipeline.md](pipelines/climate-pipeline.md)。实现顺序与已否证方向单一事实源 = [climate-layer-improvement.md](proposals/climate-layer-improvement.md)。

| 功能 | 状态 | 说明 |
|------|------|------|
| 能量平衡模型（EBM） | ✅ | `climate_physics.py:equilibrium_temperature()`；1D EBM 谱解 + Held-Hou 单圈分支（+E1 eddy relaxation） |
| 风场 | ✅ | 三圈/单圈背景（Ω^−1/3 标度）+ 跨赤道季风西风带 + 季风边界层风（月度）；物理东基根部统一 |
| 降水 | ✅ | 质量守恒逐月水汽预算（k_rain 空间调制族：风暴带/SST 对流门/海岸距离衰减/次星锚）+ 地形凝结 + 冷阱路由 + 收敛哨兵 |
| 季节模型 | ✅ | 季节 EBM（B+6D 显式输送）+ **√P 穿透标度两臂（09-30：热容量 C(P)=C_atm+…√P + 水平 reach ×√P）** + 季节冰反照率 + B0c/B0b 数据契约 |
| 洋流 | ✅ | Stommel + GMRES + E4 WBC 亚网格增速 + SST 平流/涌升 + 过程化 OHT 偏差；系统性偏弱 = 输送场主病③（债 20） |
| 季风动力学（3A.8） | ✅ v1 | ΔP 海陆对比 → 边界层风 → 逐月水汽预算；GW6 湿槽默认开（κ 68.9% 收口）；残余归债 24 |
| 恒星/轨道参数查找（3A.6） | ✅ | `engine/physical_inputs.py` 统一解析（卫星感知恒星查找 + 开普勒周期） |
| 潮汐锁定经度效应（3A.7） | ✅ 参数化 | cos 暖化 + 子星体对流增强；完整昼夜半球气候 = §七 1 |
| 海洋气候分区（3A.5，Longhurst） | 📋 | 海洋省份分类 |
| 月度矢量场展示（3A.9） | 📋 | 月度风场先行；见 §七 24 |

---

## 四、Phase 3B–3E 要点

- **3B 侵蚀与河流**：河网已落地；流水侵蚀（stream power + 坡面扩散 + 沉积路由）
  **2026-08-26 从 200k 移除**——51 km 网格上真实河谷全部亚网格，且 detachment-limited
  参数无解（诊断：任何 ≥1 Myr、合理 K₀ 下干流直达基准面）。河谷雕刻归 Gaea 局地
  高清精修；大陆内部低地由地形合成「内部低地」解决。DAG 约束：重启需地貌降水代理
  避免 geological→climate 环。见 `pipelines/geological-pipeline.md` §9.8。
- **3C 文明层**：三层半格式化架构（实体修饰器 / 事件流 / LLM 渲染层）+ 策略模式建模
  （HANDY / SDT / Tainter / 标签驱动），见 [civilization-layer.md](proposals/civilization-layer.md)。
- **3D 世界线 Diff**：地理热力图 + 文明状态对比；DAG 影响半径、混沌预警、蒙特卡洛置信区间。
- **3E 叙事引擎**：`narrative_bridge.py` — LLM 读取 YAML/JSON 数据变动，生成世界线编年史。

---

## 五、近期工作：nacrea 样板世界改造（2026 Q3–Q4）

目标：把 nacrea 打造成物理自洽、内容丰富、可支撑 B 站系列视频的样板世界。

| 项目 | 状态 |
|------|------|
| 天文：卫星系统（A4v 双单体逆行捕获卫 + 连珠节律 + 受迫 e 带） | ✅ 2026-09-10 终版（design-notes/0009） |
| 天文：轨道校准（Aegis a=0.3536 AU / 1:2:4 共振链 / 长周期数字卡） | ✅ 2026-09 终版（orbital_dynamics.md / long_term_cycles.md） |
| 地质：海陆分布（geography.yaml 锚定；09-30 双层结构 overlays 局部微调） | ✅（海岸线平直为已知限制，§七 2） |
| 气候：温度校准（温室 62 K；√P 季节两臂） | ✅ |
| 数据：网格 200k + 文档校验 | ✅ v0.24.0 |
| 文明：种子设计（3 文明 + 地理锚点 + 双语言叙事） | ✅ |
| 视频素材（timelapse / 自动旋转 / 纯净视图） | ✅ |

---

## 六、实施优先级

> 已完成项不在此累积：发版内容见 `CHANGELOG.md`，Phase/功能状态见 §二/§三，
> 世界设定类决策存档见各世界 `design-notes/`。每日执行顺序见内部工作记录。

### 外部审计里程碑（GPT-6-Astra 2026-09-17；M0/M1-P0/M2-A0 已收口，细节见 git 历史）

| 优先级 | 模块 | 预计工作量 | 关键性 |
|--------|------|-----------|--------|
| **P0** | **M1-P1 版本化开发数据包**（manifest/SHA-256/固定索引 + `data fetch` 拟议接口；交付顺序以数据包评估为准） | 1–2 周 | ★★★★★ |
| P1 | **GUARD-01 守护轴反例修复**（同指纹事实漂移漏检、嵌套 YAML 漏检、容量归档误标、`intentional` 过宽、缺产物显示已验证） | 3–5 天 | ★★★★ |
| P1 | **M3 结果契约与 UCC 第四步**（分类导出 + 着色 + 用途验证；前三步已收口） | ~1 周 | ★★★★ |
| P2 | **M4 有边界的世界创作扩展**（四选一真实用户任务驱动；16 份 proposal 状态整理随后） | 按所选任务 | ★★★ |
| P2 | **气候 rethinking 机制侧**（M2 实施框架 = ▶ 主线的阶段 A–E；输入契约/账本/迁移已收口，输送场主病待 GW6 域前置后的重标定轮） | 随主线 | ★★★★★ |
| P2 | **宽 Hadley 体制下副热带过干**（GCM 交叉核查：nacrea 副热带降水约为 GCM 的三分之一，地球同纬带正常，属体制外推问题；首要线索为背景信风，先做规定低层风的干预实验）→ `audit/wave6-gcm-ebm-crosscheck.md` + `proposals/climate-layer-improvement.md` §7；同处登记高纬陆地季节振幅偏弱 | 随气候层开发 | ★★★★ |

### 既有待办

| 优先级 | 模块 | 预计工作量 | 关键性 |
|--------|------|-----------|--------|
| **P1** | **局部地形精细化管线**（全球输出 → 专业工具局部高清：export/import-region CLI + 16-bit GeoTIFF + Gaea 模板 + QGIS 矢量化；export 侧首片已落地 = `dreamulator export region`，见 [blender-render-pipeline.md](proposals/blender-render-pipeline.md)；调研见 [gaea-refinement.md](proposals/gaea-refinement.md) §6） | 设计 0.5 周 + 实现 1–2 周 | ★★★★ |
| **P1** | **全球画布链 S2–S5**（每块大陆整块生成，23 km 粗格、90 m 像素；S2 外存填平·汇流·湖级联与 S3 区域裁窗已并入 main，S4 重叠窗一致性与 S5 全局概览待做；试点画布等 nacrea 数据冻结后交付）→ [canvas-hydrology.md](pipelines/canvas-hydrology.md) | S4/S5 各 1–2 周 | ★★★★ |
| P3 | ~~构造-侵蚀 Δt 耦合~~——随流水侵蚀关闭搁置，重启再评估 | — | ★★ |
| **P0** | nacrea 样板世界改造（五）：天文/地质/气候/文明种子已就绪；视频素材三件套 ✅（2026-10-02 合入）+ Blender 高清渲染链 MVP 落地（`export region` + bpy 静帧），后续 = 多图层包/相机动画/全球整球（[blender-render-pipeline.md](proposals/blender-render-pipeline.md) 路线节） | — | ★★★★★ |
| P1 | **月度矢量场展示**（§七 24；数据链已就绪，前端懒加载抽样箭头） | 1–2 周 | ★★★★ |
| P1 | 文明层半格式化 Schema（3C） | 1–2 周 | ★★★★ |
| P2 | 视频素材后续（Blender 链扩展：多图层数据包 / 相机动画 / 全球整球；见 [blender-render-pipeline.md](proposals/blender-render-pipeline.md) 路线节） | 按镜头排 | ★★★ |
| P2 | **气象图层与太空镜头链**（L2 程序化云纹理 ✅ 2026-10-18：`export clouds`，球面逐点 fBm + 流场扭曲 + 卷云拉丝；L3 参数化气旋模板 ✅ 2026-10-22；L5 单次散射大气渲染原型 ✅ 2026-10-22：恒星光谱定标、透射率表、云壳分层与云影；余 L1 GCM 图层包、L4 时间平流、L5 多次散射/夜灯/海面高光，触发 = 气象图层包） | 随图层包批 | ★★★★ |
| P3 | 高清行星系视图（类 Space Engine：真实周期轨道动画 + 高清天体渲染；原视频素材轮的轨道动画项拆出独立立项，2026-10-02） | 调研后估 | ★★ |
| P3 | **热点火山岛建设剖面**（潮汐固定热点岛的盾状对数剖面 + 裂谷拉长选项，替换锚定幂核；形态判据实测 → [geology-layer-improvement.md](proposals/geology-layer-improvement.md) §9；2026-10-05 立项，优先级低） | 3–5 天 | ★ |
| P1 | LLM 叙事桥（3E 史诗叙事） | 2 周 | ★★★★ |
| P3 | **UCC 天体区分度配套**（① 学界天体气候划分文献调研——部分已由 worldbuildingpasta 调研覆盖；② 前端天体 profile 声明显示） | 调研 1–2 天 | ★★ |
| P3 | **nullschool 式粒子流可视化**（风/洋流矢量箭头 → 粒子平流拖尾；参照 cambecc/earth） | 前端 1–2 周 | ★★ |
| P3 | **草案七转正 + Hycean 调研**（创作线） | ①1–2 天 ②周级 | ★★ |
| P2 | **earth 观测锚 1km 升级**（CHELSA/WorldClim 30″ 面积加权聚合；须在 LGM 分支之前） | 1–2 天 | ★★★ |
| P2 | **地球历史气候分支**（`earth/branches/lgm`：ICE-6G_C + CHELSA-TraCE21k；模式重建非观测真值，provenance 声明） | ~1 周级 | ★★★ |
| P2 | 河流增强（3B）：侵蚀机制重启与沉积物搬运随局地精修/未来评估 | — | ★★ |
| P2 | **内陆水体物理 refine**（湖命运 P−E 判决四类结局 + 溢流湖接通河网 + rim/spill 落盘字段；语义闭合 (a)+(b) 已于 10-08 收口）→ [inland-water-refine.md](proposals/inland-water-refine.md) | 1–2 周 | ★★★ |
| P2 | **海岸侵蚀·潮汐冲刷主导**（随侵蚀关闭搁置；大尺度指纹可在 200k 表达）→ `knowledge/geology/coastal_geomorphology.md` | 1–2 周 | ★★ |
| P2 | **生态层海洋模块**（3B.5：潮间带宽度、海洋 NPP 潮汐混合因子、深海热泉密度——生态层现全陆相） | 1–2 周 | ★★★ |
| P2 | **生物地理分区算法改进**（唯一屏障=海洋；沙漠/山脉不构成屏障、过渡带零建模）→ ① 参数侧 target_provinces_per_realm；② 扩散阻力加权分区（Holt 2013 / WWF）；③ ecology-layer §2.4 字段 | 1–2 周 | ★★★ |
| P2 | **Gleba 实测调研**（本地 gleba.exe 零实测记录：CLI/headless 试验 + 问题对比 + 层设计借鉴）→ competitor-analysis.md 新增「Gleba 实测」节 | 2–3 天 | ★★★ |
| P2 | **地质时间轴**（大陆块运动学的约束求解生成历史时刻快照，作者缝合带与关键帧为输入，时刻分支接气候与生态，前端时间滑块；现状逐格不变）→ [geological-timeline.md](proposals/geological-timeline.md)（快照的边界表示即板块拓扑层，见该文附录 A）。G1–G3 与 §4.6–4.8 已实现；下一轮候选：陆缘分段张开（拉链式破裂，§4.7）、生成段大洋板块（G4） | G4–G5 各 1–2 周 | ★★★ |
| P2 | 世界线 Diff 可视化（3D） | 2 周 | ★★★ |
| P2 | Entity ID 系统（UUIDv7 + slug 双主键，为 DAG 精确寻址铺路） | 1 周 | ★★★ |
| P2 | `ai` CLI 命令组 → [ai-cli-commands.md](proposals/ai-cli-commands.md)；critique/trace/reconcile 归 [harness.md](proposals/harness.md) | 2–3 周 | ★★★ |
| P1 | **前端加载后续**（profile 优化轮 ①–④ 已收口：globe 17.1→14.4 s；剩余 = 字段级增量更新 + bake/WebGL init 懒化 + spatialReference 资产化（§七工程 6）） | 1–2 周 | ★★★★ |
| P2 | **geography.yaml 编辑原语补全**（overlays 段已承载局部刻海/补陆（09-30）；剩余原语 = `elevation_bias` 区域乘数、`lock_region`、`lake`/`inland_sea`） | 1–2 周 | ★★★ |
| P2 | **edits.json 逐 cell 编辑系统**（管线后处理叠加层，seed 绑定；点击编辑 → 画笔 → 地形笔刷三期；设计见 [layer-control-model.md](proposals/layer-control-model.md)） | 1–2 周 | ★★★ |
| P2 | **分辨率独立性验证**（geography.yaml 锚定特征在 100k/200k/500k 一致性；sub-cell 特征如北方内海连通性对分辨率敏感，需文档化边界） | 0.5 周 | ★★★ |
| P3 | **外部编辑往返协议**（mesh ↔ 高分辨率栅格 ↔ 外部工具 ↔ 回贴 cell；P1 局部地形精细化管线为其 MVP 先行版）。**前置使能 = 地形 bake（2026-09-30 立项，设计草案待整理入库）**：精调后的全球地形冻结为直读基座（`baked_base` + manifest，类似 earth root 导入态），外部编辑不再被构建冲掉 | 远期 | ★★ |
| P3 | **构造-地表全双向耦合**（侵蚀卸载/沉积载荷反作用于板块动力学；Underworld2+Badlands ALE 方案；需先解决地理锚定与动态板块协调） | 远期 | ★★ |
| P3 | AI 顾问模式 / 实时协作 / 世界导出包 | 见 vision.md §9 | ★★ |
| P3 | Moltke Engine — 独立实体引擎（ECS + 差分数据流 + 增量分支计算）→ [moltke-engine.md](proposals/moltke-engine.md) | 远期 | ★★ |
| P3 | SDE 文明建模（Euler-Maruyama / Milstein / 泊松跳跃冲击） | 远期，依赖 Entity ID | ★★ |
| P3 | **harness environment 统一底层**（ai 命令组统一跑在「事实上下文 + 原语/verifier 注册表 + 证据三分类」上）→ [harness.md](proposals/harness.md) §9.4 | 内核 0.5 周 | ★★ |
| P2 | **基于地质时间的板块运动演化**（古造山带/裂谷随漂移-碰撞-裂解自然涌现，替代 `_apply_interior_landforms` 手动放置 → geological-pipeline §7.2）：新建世界走「演化模式」：geography.yaml 作为演化目标，逆向规划超大陆后正向运动学模拟出现状，与现行「指定模式」并存 → [evolution-mode.md](proposals/evolution-mode.md)（排在 geological-timeline M2 之后）。已有正典世界的历史时刻快照另走 [geological-timeline.md](proposals/geological-timeline.md)，不改现状管线 | E1–E4 各 1–3 周 | ★★★ |
| P3 | **地质层速度**（terrain 已 56→17 s（09-29）；剩余 = tectonics ~97 s Dijkstra 重采样；债 11 缩放数据） | 评估 0.5 周 | ★★ |
| P3 | **GCM PoC 跑通**（PoC 风场退化根因未明；定性结论已由 Kaspi & Showman 2015 兜底。升级候选（用户 09-24 间奏曲）：① ExoPlaSim baseline；② GPU 多卡 200k 节点级 GCM；③ 模拟数据训 ML 代理。前置 = ExoPlaSim GPU 化审计 + 网格-动力核匹配调研）→ [climate-gcm-plan.md](proposals/climate-gcm-plan.md) | 远期（资源到位可提级） | ★★→★★★ |
| P3 | **EBM 全球冰反照率耦合**（EBM 全球均温锚定在固定反照率 0.3 的平衡温度加温室增温上，冰反照率只做局地降温，改倾角 14.9°→19.9° 时 EBM 全球均温仅变 0.06 K；现状按定标点用 GCM 重定标，复杂度与耦合面待评估）→ `solve_1d_ebm_temperature` / `ice_albedo_feedback` + nacrea design-notes 0012 §2 | 调研后估 | ★★★ |
| P3 | **诊断缓存设计**（诊断脚本中间量落盘带版本号；已知属性：mesh 4 位小数截断致产物 vs rebuild 差 0.2pp） | 1 周 | ★★ |

---

## 七、已知技术债务

按"功能性 → 工程卫生"排序。已修复项不入此表（git/CHANGELOG 为史）。

### 功能性

1. **潮汐锁定经度效应缺失**（Phase 3A.7 参数化之外的完整版）— 无昼夜半球 /
   次恒星点热源 / 经度不对称的完整气候；nacrea 温室预算已预留 +3 K。
   与 §六 P3 GCM 线、27（时间表示通用化）同前提。
2. **海岸线过于平直**（用户反馈 2026-08）— 海陆判定在 cell 粒度（~51 km），
   缺分形细节。方向：更高 cell 密度 / 海岸带高频噪声扰动 / 导出栅格分形细分。
   与地理锚定兼容（锚定给宏观格局，只增微观粗糙度）。
3. **大裂谷海蜿蜒原语** — 多段错列偏置场已缓解（nacrea yaml）+ 09-29 边界形态
   链（宽度调制/侧向蜿蜒/断块塌陷）；彻底方案 = geography 支持"弯曲裂谷带"
   polyline 路径原语（多段椭圆链已够用，原生路径为远期；overlays 段可先做局部试错）。
6. **自动国界 / 行政区划生成**（2026-08-09）— Azgaar 式自动剖分（流域 + 距离衰减 +
   军事/文化权重）值得参考不移植；3C 当前以人工锚定种子 + 事件流填充为主，
   自动领土剖分是远期扩展，不阻塞 3C。
7. **内流盆地连通**（2026-08-26 重新定性）— 「坝路径硬编码」机制已移除（混淆
   被堵海峡与稳定内流盆地）；连通属水量平衡/海洋过程问题，若需要走该方向建模。
8. **Cortial 2019 对 seed 高度敏感**（2026-08-10）— 不同 seed = 完全不同的星球
   （海陆一致率 74%/海岸 IoU 8%）；geography.yaml 锚定是唯一约束机制。需要
   seed 探索器 + 种子目录作为补充工具链。
9. **气候对网格分辨率敏感**（2026-08-10）— Af 质心 100k vs 200k 偏移 37° 经度、
   北方内海 200k 下封闭；全局统计稳定（<3%）但空间分布敏感。需在气候验证中
   建立分辨率敏感度基线。
10. **JS 堆膨胀是前端规模上限**（2026-08-10 诊断，msgpack 已缓解传输/解析）—
   解析后对象堆 3–4×，500k 的 OOM 上限只是推迟而非消除。
11. **后端构建性能缩放数据**（2026-08-10，seed=42；§六 P3 地质速度行的依据）：

| 阶段 | 100k | 200k | 500k | 1M | 1M/100k | 缩放类型 |
|------|------|------|------|-----|---------|---------|
| mesh | ~19s | 31s | 77s | 176s | 9.3× | O(N log N) |
| plates | ~3s | 5s | 11s | 28s | 9.3× | O(N) |
| tectonics | ~36s | 85s | 178s | 455s | 12.6× | O(N^1.5) |
| terrain | ~59s | 104s | 296s | 737s | 12.5× | O(N^1.5) |
| ocean (GMRES) | 32.1s | 87.6s | 356.4s | 764.2s | 23.8× | O(N^1.7) |
| 气候合计 | ~68s | 147s | 482s | 1003s | 14.7× | |
| **总计** | **~200s** | **391s** | **1079s** | **2464s** | **12.3×** | |

13. **生态 NPP 光谱匹配缺失**（2026-08-13）— `par_ratio = L/d²` 是总辐射通量比，
    未按恒星光谱修正 PAR（M 矮星 NIR 峰 → 高估叶绿素型 NPP）。修正链 =
    恒星光谱型 → 光合色素吸收谱 → 有效 PAR；`physical_inputs` 未读恒星温度/光谱型。
    知识底座 ✅（`knowledge/ecology/photosynthesis_spectra.md`）；优先级 P2。
15. **天体数据双文件分裂的残余**（2026-08-15）— 派生目录 + API 已化解重复
    （`build_system_catalog()` + 交叉校验 ✅）；残余：③ 创作规范以 planets.yaml
    为权威（本条即出处）；④ 远期 `dreamulator validate` 深度模式接入一致性校验。
19. **潮差的残余手写值**（2026-08-16 登记，2026-10-16 更新）— 偏心率潮的共振潮差已由引擎派生为
    `entities.<id>.tidal_range_m`，对外设定统一引用。残余：1688 m 静态海洋隆起仍是文档常数；倾角潮
    （∝ ψ）的振幅与 35–38 年调制取自轨道积分，ψ 不在引擎目录，只能按范围手写；两种潮在海洋中的共振响应
    都没有计算。
20. **水汽收支标定残余**（2026-08-28；守恒化已收尾）— 开放子项：
    ① ITCZ 偏强（0° 峰值 ~+800）→ 并入 债 24 月度胞圈迁移（单点杠杆已否证）；
    ② 中纬干燥（38–62°N 偏干 −300~−470 mm/yr）= 风暴路径欠输送，标定非推导
    与 κ 有张力，**输送场全局重标定轮候选**（与 nacrea B 诊断的引擎侧结论同向）；
    ④ D 群崩溃挂起（正确方向 = 植被掩雪，需温度×生态耦合联合标定）；
    ⑤ 海洋输送占比按风生环流推导（`ebm_diffusion_land_wm2k` 地球标定）。
21. **低优先级杂项**（2026-08-24）：Whittaker 群系异星平移边界线；Aegis e 纪元选择
    （用户 09-30 裁决天文配置不动，闭合）；年度冰反照率光谱统一（待 M 矮星 GCM 数据）；
    温度源升级 ERA5/CRU TS；LGM 扩展（22ka 月度 + PMIP4 多模型）。
24. **月度矢量场：风场先行、洋流不伪造**（2026-08-28）— 核心任务 = 环流胞圈逐月
    迁移（月度风场 = 月度 ITCZ 环流 + 季风异常；锚点：刚果/亚马逊水分路由、地中海
    冬雨、东亚季风强度/高地热源项；验收 Cwa/Cfa/Am recall >40%）。数据约定与
    前端懒加载方案已定；月度洋流待季节风应力（不伪造）；月度 SST 居中。
    季风 v1 + GW6 湿槽已收口（git/proposal §2/§5 为史）。
25. **水系图层内湖终点处理**（2026-09）— 内流湖绘制/展示方案：湖泊 vs 海洋渲染
    区分、外流河→外洋 vs 内流河→内湖终点的图层/图例语义。
26. **气候层残余偏差归档** — 单一事实源 = [climate-layer-improvement.md](proposals/climate-layer-improvement.md) §0（逐格偏差 TOP）+ §7（已知局限清单）。
27. **时间表示通用化：12 bin → 世界频谱派生**（2026-09-14 调研裁决）— 「月」=
    年 12 等分是地球历法遗产；通用化 = 强迫谱（Dobrovolskis 2013 解析展开）→ 逐频
    响应 → 表示层（bin 数世界派生 / 谐波系数）。现行存储不动；与技术债 1、
    UCC Phase 3 `-L` 段同前提。原则措辞 → proposal §3「B0b 原则泛化」。
28. **洋流链左手基符号债**（2026-09-30 诊断，归输送场重标定轮）— `east_north_basis`
    切平面基为左手系（east×north=−r̂），`compute_curl_z` 赝标量随之翻转；根镜像
    `_to_physical_wind` 仅补偿纬向主项 ∂τe/∂n，∂τn/∂e 项以错号进入强迫（带均值占比
    nacrea 0.28–0.85、earth 热带 0.37–0.71 / 中纬 0.06–0.19）。修法两处协同：curl_z
    翻正 + Stage 2.5 删镜像；涌升/异常平流的镜像消费点一并核查。nacrea 单圈东风下
    低纬西/中纬东交替带状流型本身有文献先例（Zeng & Yang 2021 + 地球 NECC），非 bug。
29. **诊断脚本配置与引擎路径不等价**（2026-09-30 实锤）— A/B 与复跑脚本用
    `load_geography_spec` 覆写 `cfg.geography` 等构造差异，与引擎路径产出**不同行星**
    （引擎校准 `overlay-blind(3617 cells)+sea level −130 m` vs 脚本 `+148 m` 无
    blind；高程相关 −0.03、44% 海陆翻转）——**A/B 气候结论对真实管线无效**。修法：
    定位具体分歧字段（疑 overlay-blind 校准 flag / geography 覆写）；诊断脚本禁止
    覆写 `cfg.geography`，或引擎暴露与构建逐位等价的配置构造入口；走廊机制 A/B
    如需保留须修正后重跑。关联（未实锤但同晚验证过的潜在坑）：阶段指纹不含代码
    版本、`--only X --force` 不失效上游——语义改动必须 bump
    `_STAGE_SCHEMA_VERSIONS`（本次 clamp 已随改 bump terrain v3）。
30. **ExoPlaSim T42 短波辐射浮点异常**（2026-10-13）— T42 多年积分会在短波辐射子程序
    `swr_` 中触发 SIGFPE，单波段与双波段反照率、有无地形都会发生（712 ppm 双波段无地形第 8 年、
    712 ppm 单波段带地形第 10 年、2000 ppm 单波段带地形第 7 年），缩短步长到 30 分钟只推迟不
    根除，气候越暖越早；T21 在
    140–6000 ppm 全部稳定，上游 3.4.2 与主干均未修复。另有 T42 在 6000 ppm 时 Kuo 对流方案
    溢出。规避：打开物理滤波（`gp|exp|sp`）后 T42 多年积分稳定（地球与 nacrea 冷暖双臂最长
    40 年无异常，地球偏差与 T21 一致），T42 确认已据此完成（0012 判决五）。调试编译定位（`-ggdb -Og -finit-real=snan`）：
    陷阱在 `radmod.f90:1783` 计算水汽路径的 `SQRT(273./dt(:,jlev))`，即某格点气温已变为
    ≤ 0 K 或非法值；短波辐射只是每步第一个对气温开方和除法的地方，根源在其上游的数值发散；
    snan 初始化未在别处提前触发，可基本排除读取未初始化变量。待办：在源码副本中加逐步诊断
    （全场最低气温及其格点），追到发散的过程后修复；属于改动 Fortran，需与上游未合并修复
    （PR #62、issue #69）一并决定是否维护 ExoPlaSim fork（见
    [climate-gcm-plan.md](proposals/climate-gcm-plan.md)「上游维护状况与 fork 策略」）。
31. **地形管线跨平台残余差异**（2026-10-15）— 同一输入在不同 CPU 与数学库上构建，地形原本会
    整片分叉：地形合成在受浮点阈值控制的循环里逐格抽随机数，一个格点越过阈值就让共享随机数流
    错位。四处已改为「先按格点数抽好整组、再按格点编号取值」，造山带截断改为平滑降到零，回归
    测试为 `tests/test_map/test_terrain_simd_determinism.py`（开、关 numpy 的 AVX-512 分派各构建
    一次）。残余：极少数贴着海平面的海岸格点仍会翻转并带动局部海岸缓冲区（nacrea 200k 网格约
    10 格），逐位一致需要对海陆判定做定点化；GCM 固定字段集以带容差的网格比较兜底
    （`gcm/fields.py` 的 `MESH_TOLERANCES`）。新增随机抽取时遵守同一规则。
32. **大陆架高程按网格间距量化**（2026-10-16）— `terrain_synthesizer.py` 的
    `_apply_continental_shelf` 按格心到海岸格的距离定深，距离只能取约一个格距（nacrea 200k 网格约
    54 km）的整数倍附近，于是第一排海洋格几乎都在 −26 至 −32 m，第二排在约 −105 m。全球高程分布在
    −50 至 −20 m 之间出现约 33 M km² 的尖峰，−20 至 0 m 与 −85 至 −60 m 几乎为空；一两格宽的海峡门槛
    都被锁在这两个深度，海平面敏感性诊断（`scripts/climate/diagnose_ocean_gateways.py`）因此失真。
    修复要求：海岸线完全不动（海陆判定逐格不变），只调整陆架内部高程，例如按到海岸线而非海岸格心的
    连续距离定深，或在剖面上叠加与距离无关的起伏。修复会改变世界数据的高程，需重新发布并核对
    GCM 地表文件。
33. **构造演化的板块实际位移约为名义时长的十分之一**（2026-10-16）— `tectonic_simulator.py`
    每一步都按板块当前的格子重新求质心，再只转一个时间步；两次重采样之间格子不变，所以每 10 步
    实际只前进一步的距离，而累计汇聚量与张裂量按完整的 10 步积分。nacrea 名义演化约 8100 万年
    （50 步，每步约 1.62 Myr），板块实际只走了约 800 万年的距离；时间步公式还假设最快板块
    10 cm/yr，而 nacrea 最快约 23 cm/yr。修复会改变板块划分与造山带宽度，进而改变所有世界的
    现状地形，需与重新发布世界数据一并排期。古地理推演不依赖这条（见
    [geological-timeline.md](proposals/geological-timeline.md) §1.3）。
34. **构造演化不搬运地壳**（2026-10-16）— 演化过程中只读取地壳数组，剖分代价场全程钉在现状
    海岸线上，大陆不会离开原位；`reapply_after_tectonics` 因此重算出的是同一张掩膜。现有模拟器
    无法用于向未来推演大陆漂移，地质时间轴改用独立的地壳质点运动学。是否让现状管线也搬运地壳，
    取决于「指定/演化」双模式的裁决（§六 P2「基于地质时间的板块运动演化」；新建世界的演化模式见
    [evolution-mode.md](proposals/evolution-mode.md)，在那里由运动学模拟真正搬运地壳）。
35. **geography.yaml 文件头写有单个地物的 `sea_level_offset_m`，模型没有这个字段**（2026-10-16）—
    nacrea `geography.yaml` 第 30 行把它列为地物参数，但 `GeographyFeature` 没有定义它，写了也会
    被静默忽略。修法二选一：删掉注释，或实现局部海平面偏移并让未知字段报错。
36. **海沟弧松弛里的飞地检查广度优先搜索写错队列**（2026-10-17）— `tectonic_simulator.py` 的
    `_trench_arc_relaxation` 末尾「Enclave guard」把新格子追加进前面已清空的列表 `q`，而不是本地
    队列 `bq`，每个连通块只展开到起点的直接邻居，同一板块被切成大量 7 格以内的假碎片；其中挨着
    别的板块的会在每次重采样时翻给邻居板块，给板块边界加上一格量级的噪声。同文件收尾的
    `_merge_plate_enclaves` 写法正确。修复会改变板块边界与现状地形，需与重新发布世界数据一并排期。

37. **大陆内部系统性欠起伏**（2026-10-17，做河流水文时在 nacrea 22.5°N、100.5°E 的 550 km
    窗口发现）— 地球荒漠内部常有阿哈加尔、提贝斯提量级的 1500–3000 m 山块，nacrea 内陆则缺这类起伏。
    量化（两个世界同一套网格口径：以离海岸 400 km 以上、离板块边界 300–800 km 以上的陆地格为中心，
    取等面积的 550 km 窗口，起伏 = 窗口最高点减中位高程）：地球 ETOPO1 起伏中位数 400–450 m，起伏
    达 1000 m 的窗口占 15–25%、达 1500 m 的占 7–12%；nacrea 起伏中位数约 280 m，达 1000 m 的占
    4–5%、达 1500 m 的不到 1%。缺的主要是分布的上尾，即板内大山块。地球上这类山块多是热点穹隆加火山
    （阿哈加尔、提贝斯提、达尔富尔）与「盆地—隆起」型的板内动力地形（非洲尤为典型），尺度约 1000 km、
    隆起约 1 km，地形合成目前只有 9 个热点和区域噪声。方向：核对 `_apply_interior_landforms` 与热点数、
    穹隆幅度的标定，考虑按内热或潮汐加热推出板内隆起的数量与幅度。属于微小起伏，修复在 nacrea 现状
    约束的容差之内。

    技术债 33、34、36 的处理原则（作者裁决 2026-10-17）：nacrea 的现状约束是容差（大陆形状、关键
    地峡与海峡不变，GCM 重跑差异不大），本身也是技术债。修复以新世界的默认行为实现，用配置开关
    保留 nacrea 的旧行为；nacrea 是否切换，按上述容差验证后再定。

38. **气候求解器跨平台分支分叉**（2026-10-18）— 月度水分预算是带收敛上限与截断判据的迭代求解，
    最后几位浮点差异会被逐轮放大成宏观不同的平衡态：GitHub 的 Intel runner 激活 numpy 的
    AVX-512 内核后，同一输入算出的陆地蒸散比 AVX2 分支低约 3%、全球水账本低约 2%，§5-β 对流门
    测试里受门的三个格点翻为降水增加而断言失败；本机与 WSL 的 AMD CPU（无 AVX-512 分派）上
    一致通过。CI 在 10-15 与 10-17 共三次红、期间同代码穿插绿，是 ubuntu-latest 机队 Intel 与
    AMD 混池随机分配 runner 所致。过渡修复：该测试的比较臂改在子进程中关闭 AVX-512 分派并钉住
    OpenBLAS 内核（配方同 `tests/test_map/test_terrain_simd_determinism.py`），使断言在所有机器
    上都评测基线分支。彻底修复需要对预算迭代的阈值做地形管线式的确定性纪律，归气候批次。

### 工程卫生

2. **pipelines/ 缺 ecology 与 astronomy 技术参考**（docs 二轮体检 2026-09-16）—
   补写 `pipelines/ecology-pipeline.md` / `astronomy-pipeline.md` 待排期。
5. **engine ↔ map 双向依赖、编排/领域/mesh 契约混用**（ARCH-01/02，2026-09-17）—
   公共契约（时间/物理输入/geometry identity/产物来源/运行状态）下沉低层，先做
   气候一条切片；规模热点：terrain_synthesizer / climate_simulator / tectonic_simulator
   均 2000+ 行。归 M2 必要切片 + 远期。
6. **spatialReference.ts ~5.4 万行生成观测数据内嵌**（FE-01，2026-09-17）—
   实测 useUccLayer chunk 2.1 MB（gzip 540 KB）必载非按需；修法 = 资产化 + 按需加载。
   归 M3。
7. **API/静态导出/前端三件套手工同步、无一致性夹具**（CONTRACT-01，2026-09-17）—
   修法 = 公共结果契约 + 格式版本 + 最小静态/API 一致性夹具。归 M3。
8. **阶段缓存对模型演化的护栏**（2026-09-30 overlays 轮暴露并修复）— 09-17 教训
   （payload 须枚举 in-place 字段）已部分落实，但 unpickled 旧实例缺新增字段仍
   可崩（ice_thickness_m 实例已修，根因未除）；根治 = 阶段指纹纳入模型 schema 版本
   或 load 时字段完备性校验。另一缺口（2026-10-16 核实）：阶段指纹只含配置与 schema 版本，不含
   代码版本，改了算法而未提升 schema 版本时旧缓存仍会命中；`plates` 阶段的字段清单也漏了
   `coherent_motion`、`convection_harmonics` 等板块运动参数。

## 八、内部文档链接

- `docs/design/architecture.md` — 项目架构（层级架构与分支管理）
- `docs/design/proposals/harness.md` — 守护轴总纲（校验/审计/设定维护：与生成轴正交；两个守护对象=引擎代码+世界设定；三级过期检测；决策记录台账）
- `docs/design/audit-plan.md` — 三波审计计划（守护轴之「守护引擎」实例；工程卫生/物理/架构；启动判据与交付物）
- `docs/design/pipelines/geological-pipeline.md` — 地形生成管线技术参考
- `docs/design/pipelines/map-system.md` — 地图系统架构
- `docs/design/pipelines/climate-pipeline.md` — 气候引擎实现架构
- `docs/design/pipelines/climate-validation.md` — 气候引擎验证指南
- `docs/design/proposals/ecology-layer.md` — 生态层设计方案（引擎已实现，技术参考暂住此文档）
- `docs/design/proposals/civilization-layer.md` — 文明层详细架构设计（三层半格式化架构）
- `docs/design/proposals/language-phylogeny.md` — 语言谱系子系统设计稿（待开发）
- `docs/design/proposals/myth-strata.md` — 神话层累数据模型设计稿（待开发）
- `docs/usage/map-workflow.md` — 地图工作流指南
- `docs/usage/civmap-guide.md` — 文明地图使用指南
- `docs/design/profiling.md` — 性能剖析与基准测试指南

---

*此文档将随开发进展持续更新。*
