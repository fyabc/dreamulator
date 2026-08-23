# 竞品分析

> 从 `roadmap.md` 拆分而来（2026-08-04）。2026-08-08 扩展：各 DAG 层级专业工具对比 +
> 2024–2025 世界构建工具格局。2026-08-10 扩展 §六：分辨率对标 + 多分辨率基准测试 + 业界数据处理方案。
> 2026-08-16 扩展 §七：World Anvil 方法论参照（自洽性 vs 创造性）。2026-08-17 扩展 §八：宜居卫星设定参照。

---

## 一、核心优势总结

相比市面上三大类世界构建工具，Dreamulator 有三个不可替代的护城河：

### 1. 物理因果（Causality）

| 竞品 | 弱项 | Dreamulator 优势 |
|------|------|-----------------|
| [**Azgaar**](https://azgaar.github.io/Fantasy-Map-Generator/) | 启发式随机生成（heuristics），气候与地形无因果关联 | 基于 `physics → chemistry → climate` DAG 推演，"因为有暖流所以是雨林" |
| [**Inkarnate**](https://inkarnate.com/) / [**Wonderdraft**](https://www.wonderdraft.net/) | 纯手绘，无任何物理验证 | 引擎自动校验设定自洽性 |
| [**World Anvil**](https://www.worldanvil.com/) / [**Novelcrafter**](https://novelcrafter.com/) | "设定集维基"，无物理约束 | 科学约束的输入校验 + DAG 级联影响追踪 |

### 2. 版本控制（Versioning）

| 竞品 | 弱项 | Dreamulator 优势 |
|------|------|-----------------|
| [**Gleba**](https://calandiel.itch.io/gleba) | 单机沙盒，无分支/合并概念 | Git 风格分支系统 + `_inherit` 继承 + 多人共创 |
| **所有竞品** | 设定冲突无法追踪 | DAG Diff：修改地质层 → 自动标记下游气候/文明层为 Dirty |

### 3. AI 语义缝合（AI-Semantics）

| 竞品 | 弱项 | Dreamulator 优势 |
|------|------|-----------------|
| **World Anvil** | AI 辅助写作，无数据验证 | LLM 读取结构化 YAML → 编译为叙事，而非 LLM 直接写文本 |
| **Novelcrafter** | 纯文本 AI 辅助 | 科学数据 → `narrate` 命令 → 物理自洽的故事 |

**定位总结**：Azgaar 提供世界观的**画布**，World Anvil 提供世界观的**图书馆**，Dreamulator 构建世界观的**物理引擎与因果引擎**。

---

## 二、参考链接

### 竞品

| 工具 | 链接 | 类型 |
|------|------|------|
| Azgaar's Fantasy Map Generator | https://azgaar.github.io/Fantasy-Map-Generator/ | 地图生成 |
| Inkarnate | https://inkarnate.com/ | 手绘地图 |
| Wonderdraft | https://www.wonderdraft.net/ | 手绘地图 |
| World Anvil | https://www.worldanvil.com/ | 设定管理 |
| Novelcrafter | https://novelcrafter.com/ | AI 写作辅助 |
| Gleba | https://calandiel.itch.io/gleba | 科学模拟（闭源） |
| Songs of the Eons (SotE) FOSS 版 | https://github.com/Calandiel/SongsOfGPL | 科学模拟（GPL，仅游戏部分，不含世界生成器） |
| Foundry VTT | https://foundryvtt.com/ | TTRPG 平台 |

### 设计概念

| 概念 | 链接 | 来源 |
|------|------|------|
| Clausewitz Engine (Paradox) | https://eu4.paradoxwikis.com/Map_modding | P 社游戏引擎 |
| Dwarf Fortress Legends | https://dwarffortresswiki.org/index.php/Legends | 程序化历史生成 |
| Cliodynamics | https://peterturchin.com/cliodynamics/ | Peter Turchin |
| HANDY Model | https://doi.org/10.1016/j.ecolecon.2014.02.015 | Motesharrei et al. (2014) |
| SDT (Structural-Demographic Theory) | https://peterturchin.com/structural-demographic-theory/ | Peter Turchin |
| Joseph Tainter — Complexity Collapse | https://en.wikipedia.org/wiki/Joseph_Tainter | 复杂性边际收益递减 |
| Seshat Global History Databank | https://seshatdatabank.info/ | 全球历史数据库 |
| Energy Balance Model | https://en.wikipedia.org/wiki/Energy_balance_model | 气候科学 |
| Atmospheric Circulation | https://en.wikipedia.org/wiki/Atmospheric_circulation | 大气环流 |
| Orographic Lift | https://en.wikipedia.org/wiki/Orographic_lift | 地形抬升 |
| Thermohaline Circulation | https://en.wikipedia.org/wiki/Thermohaline_circulation | 热盐环流 |
| Lyapunov Exponent | https://en.wikipedia.org/wiki/Lyapunov_exponent | 混沌理论 |
| Monte Carlo Method | https://en.wikipedia.org/wiki/Monte_Carlo_method | 不确定性量化 |
| D8 Flow Direction | https://en.wikipedia.org/wiki/Flow_direction | 水文模型 |
| Sediment Transport | https://en.wikipedia.org/wiki/Sediment_transport | 沉积物搬运 |

---

## 三、世界构建工具格局（2024–2025）

### 3.1 地图与地形生成

| 工具 | 类型 | 核心能力 | 与 Dreamulator 对比 |
|------|------|---------|-------------------|
| [**Azgaar's FMG**](https://azgaar.github.io/Fantasy-Map-Generator/) | 开源 Web | 启发式随机地图 + 城市/国家/文化生成；Voronoi 单元 + 风力/温度/降水简化模型 | 启发式无因果链；Dreamulator 的 DAG 推演给出可溯源的因果 |
| [**Gleba**](https://calandiel.itch.io/gleba) | 闭源（itch.io 免费） | 科学模拟：球面地形 + 气候 + 简单生态 | 同赛道，但无分支系统 / 无 AI 叙事；Gleba 本体闭源，但同作者的 SotE FOSS 版 [SongsOfGPL](https://github.com/Calandiel/SongsOfGPL)（Lua）**含完整气候代码**（`sote/game/climate/`，诊断式 2 月模型），算法详见 §4.3 |
| [**World Creator**](https://www.world-creator.com/) | 商用 | 2025.1：多层 Biome 系统 + 实时侵蚀/沉积/水/熔岩模拟 + Blender Bridge + 百万级 3D 模型散布 | 纯地形雕刻/渲染，非科学模拟；不生成气候或文明 |
| [**Gaea**](https://quadspinner.com/) | 商用 | 节点图程序化地形：分形噪声 + 水力/热力侵蚀 + 沉积。2025 支持 tile-aware 导出 | 局部地形（~几 km²），非全球尺度；针对游戏/影视资产 |
| [**World Machine**](https://www.world-machine.com/) | 商用 | 节点图地形：确定性侵蚀设备、多掩码导出。地质时间线模拟（GeoGlyph 附加） | 同上；适合可复现的资产管线，无气候/生态/文明 |
| [**Gaia Pro**](https://www.procedural-worlds.com/products/professional/gaia-pro/) (Unity) | 商用 | Unity 地形 + 植被/水体一键生成；2024 最佳开发工具奖 | 游戏引擎资产生成器，非科学模拟 |
| [**TerreSculptor**](https://www.demenzunmedia.com/terresculptor/) | 商用 | 高度图雕刻 + 侵蚀滤镜 | 同 Gaea/World Machine |
| [**Nixis**](https://github.com/MightyBOBcnc/nixis) | 开源 Python | 球面类地行星程序化生成：构造 + 水力侵蚀 + 河流/流域 | 早期阶段（仅灰度输出）；算法思路可参考 |
| [**the-dark-candle**](https://github.com/feinorgh/the-dark-candle) | 开源 Rust/Bevy | 3D 测地线行星生成：多构造模式 + 侵蚀 + 等距圆柱/Mollweide/正射投影 + GPU 着色器 | CVT 而非 Voronoi；3D globe 交互 + 构造 timelapse 回放是 Dreamulator 的待做项 |
| [**Cartographer 2**](https://apps.apple.com/tw/app/cartographer-2-rpg-world-maker/id6744778305) | iOS 商用 | 一键程序化世界 + 气候/生物群系模拟 + 海平面/冰盖调节 | 移动端；简化但完整的"气候→群系"链 |
| [**Inkarnate**](https://inkarnate.com/) | Web 商用 | 手绘风格地图；资产库（城堡/树木/山脉图标） | 纯视觉；无模拟 |
| [**Wonderdraft**](https://www.wonderdraft.net/) | 桌面商用 | 手绘风格地图；自定义资产 | 纯视觉；无模拟 |

### 3.2 天文与恒星系

| 工具 | 类型 | 核心能力 | 与 Dreamulator 对比 |
|------|------|---------|-------------------|
| [**Universe Sandbox**](https://universesandbox.com/) | 商用 | 实时物理沙盒：重力/碰撞/气候/物质交互。2024 更新 35 引入新一代图形渲染器。支持自定义行星大气、Trisolaris 三星系统 | 侧重交互实验（"撞碎地球"）；Dreamulator 侧重从第一性原理构建自洽世界 |
| [**SpaceEngine**](https://spaceengine.org/) | 商用 | 全宇宙程序化天文馆：真实星表 + 程序化生成。10 Gpc³ 可探索空间。黑洞用真实 GR 数学建模 | 侧重探索已知 + 未知宇宙；Dreamulator 侧重"构建自己的恒星系" |
| [**StarGen**](https://github.com/otherstar/StarGen) | 开源 | 恒星系统生成（质量/光度/温度/寿命 + 行星轨道） | Dreamulator 天文学引擎的同功能模块；StarGen 可作单元测试交叉验证 |

### 3.3 设定管理与 AI 辅助

| 工具 | 类型 | 核心能力 | 与 Dreamulator 对比 |
|------|------|---------|-------------------|
| [**World Anvil**](https://www.worldanvil.com/) | Web 商用 | "设定集维基"：文章/时间线/地图/家族树。AI 辅助写作 | 文档管理 + AI 写作；Dreamulator 是物理引擎 + AI 叙事 |
| [**Novelcrafter**](https://novelcrafter.com/) | Web 商用 | AI 辅助小说写作；Codex 设定管理 | 纯文本 AI；无数据验证 |
| [**LegendKeeper**](https://www.legendkeeper.com/) | Web 商用 | wiki 式设定管理 + 交互式地图标注 | 设定组织工具；无模拟 |
| [**WorldBuilder**](https://devpost.com/software/world-builder) | Web AI | LLM 推理 + 科学地理生成（风/洋流/板块）→ 文明放置 + 历史叙事 | 与 Dreamulator 理念最接近；LLM 驱动 vs DAG 引擎驱动 |

### 3.4 程序化文明与历史

| 工具 | 类型 | 核心能力 | 与 Dreamulator 对比 |
|------|------|---------|-------------------|
| [**Dwarf Fortress**](https://store.steampowered.com/app/975370/Dwarf_Fortress/) | 商用 | 完整程序化链：地质→生态→文明→历史→传说物品。200+ 年世界史自动生成 | 终极参照——全链程序化文明的黄金标准。Dreamulator 目标同构但侧重科学推演+架空世界设计 |
| [**Ultima Ratio Regum**](https://www.markrjohnsongames.com/) | 独立 | 程序化文明/宗教/语言/旗帜/文化史生成。社会科学家开发，受博尔赫斯启发 | 文明层方法论参照；v0.10.1（2023） |
| [**Songs of the Eons**](https://songsoftheeons.com/) | 独立 | 地质时间尺度世界演化 + 文明生态模拟 | 与 Dreamulator 最接近的独立项目；开发缓慢但理念高度重叠 |

---

## 四、各 DAG 层级专业软件对照

Dreamulator 的 DAG 管线：`physics → chemistry → astronomy → geological → climate → ecology → civilization`。
每个层级都有学术界/工业界的专业工具——Dreamulator 不是替代它们，而是将它们的能力"缩小并串联"。

### 4.1 天文学层

| 工具 | 用途 | 与 Dreamulator 的关系 |
|------|------|---------------------|
| [**Modules for Experiments in Stellar Astrophysics (MESA)**](https://docs.mesastar.org/) | 1D 恒星结构与演化（主序→巨星→白矮星/超新星） | Dreamulator 仅做简化分析公式（质光关系、主序寿命）；MESA 提供完整演化轨迹，可作为"高精度模式"的参考 |
| [**PHOENIX / ATLAS**](https://www.physics.unlv.edu/~khl/atlas/) | 恒星大气模型与光谱合成 | 为异星植物光合作用/视觉适应提供光谱输入 |
| [**REBOUND**](https://rebound.readthedocs.io/) | N 体轨道积分（IAS15 自适应步长） | Dreamulator 当前用开普勒近似；N 体模式（多星系统/共振链）可用 REBOUND 验证 |

### 4.2 地质层

| 工具 | 用途 | 与 Dreamulator 的关系 |
|------|------|---------------------|
| [**GPlates**](https://www.gplates.org/) | 板块构造重建与可视化。支持 Euler 极旋转、洋壳年龄、古地理重建 | Dreamulator 的 tectonic_simulator（Euler 极 + 边界演化）是 GPlates 的"正向生成"镜像——GPlates 做反演（数据→模型），Dreamulator 做生成（参数→板块） |
| [**Badlands**](https://badlands.readthedocs.io/) | 盆地地层模拟：侵蚀/沉积/构造沉降/海平面变化 | 3B 侵蚀层的参考模型 |
| [**Landlab**](https://landlab.github.io/) | 地表过程建模框架：河流/坡面/冰川/海岸线 | Dreamulator 拟实现的 D8 流向/流量累积/水力侵蚀可复用 Landlab 算法 |
| [**Fastscape**](https://fastscape.org/) | 河流切割 + 坡面扩散地表演化 | 轻量级，算法可参考 |

### 4.3 气候层

| 工具 | 用途 | 与 Dreamulator 的关系 |
|------|------|---------------------|
| [**PlaSim**](https://www.mi.uni-hamburg.de/en/arbeitsgruppen/theoretische-meteorologie/modelle/plasim.html) | 中等复杂度 3D GCM。灵活、快速、支持任意轨道/物理参数 | Dreamulator 目前的 EBM + BFS 水汽比 PlaSim 简单 2–3 个数量级；长期"简化 GCM"方向可对标 PlaSim |
| [**ExoPlaSim**](https://github.com/alphaparrot/ExoPlaSim) | PlaSim 扩展：潮汐锁定行星、非太阳光谱、超地球。pip 安装 + Python API。MNRAS (2022) 发表。**2026-08 已启动 PoC**——用 gaia-m 参数配置 ExoPlaSim（T21/T42），对比 dreamulator 当前启发式气候输出，评估替代 `climate_simulator.py` 的可行性 | Dreamulator 的"简化 GCM"方向直接对标。ExoPlaSim 已解决：潮汐锁定、冰川模块、碳-硅酸盐风化。主要风险：Fortran 编译依赖（Windows 兼容性）、T21 分辨率 vs CVT 100K 网格的地形细节损失 |
| [**CESM / ROCKE-3D**](https://www.cesm.ucar.edu/) | 全复杂度地球系统模型（大气/海洋/陆地/海冰/碳循环耦合） | 精度标杆——Dreamulator 气候验证的参照系 |
| [**climlab**](https://climlab.readthedocs.io/) | Python 气候建模工具箱：EBM/RCE/辐射对流。Brian Rose (SUNY Albany) | Dreamulator 同架构（Python 纯函数模块）；其 `climlab.EBM` 类（1D 纬度能量平衡模型，解 `0 = D∇²T + Q(φ)(1−α) − (A+BT)`）是温度模型「sin² → 正式 EBM 求解」的直接对标 |
| [**ExoCAM**](https://github.com/storyofthewolf/ExoCAM) | CESM 的系外行星分支 | 与 ExoPlaSim 同赛道；全复杂度 |

**游戏侧快速气候引擎参照（2026-08-21 调研）**：Gleba（Calandiel）闭源，但同作者的
SotE FOSS 版 SongsOfGPL（Lua，`github.com/Calandiel/SongsOfGPL`）**含完整气候代码**
（`sote/game/climate/`）。SotE 气候是「诊断式 2 月分解」——作者 devlog「The climate woes」
记录其演变：GCM（prognostic）→ 诊断式（diagnostic）→ 神经网络（climatenet，已搁置）。
「GCM 太慢且不预测 Köppen、诊断式更适合游戏」的结论与 dreamulator §7「GCM vs 参数化管线」
同向。对 dreamulator Phase 2/3 的直接参照：

| SotE 机制 | 实现（`climate-simulation.lua`） | 对 dreamulator 的启示 |
|---|---|---|
| **2 月分解** | 只算 1/7 月温度+降水，Köppen（`koppen.lua`）只用这两个月 | 验证 Phase 3「路径 A：两季分解」够用，无需 12 月全解 |
| **方向性大陆度+雨影** | `calculate-continentality.lua`：沿纬线左右各扫一遍海岸，陆地累加大陆度、海拔抬升累加雨影，按纬度 sigmoid 混合模拟盛行西风 | 「东岸湿/西岸干」不对称的**自然来源**，比「海陆感知启发式」更物理更便宜 |
| **saldo ITCZ 偏移** | `calculate-saldo.lua`：每经度柱算南北半球陆地量，把 ITCZ 往陆地多的一侧偏 | 命中 roadmap #25 ②「ITCZ 年均 0°N 缺 ~6°N NH 陆偏」 |
| **经验季节振幅** | `16×cont²×SEASONALITY_TEMPERATURE_BASE(400)` 封顶 40°C，乘 `(1-hadley_influence)` | 对应 Phase 2 大陆度；dreamulator 用 EBM（更物理），SotE 纯经验式 |
| **Hadley 修正** | `hadley_influence` +6°C 增温、×降水削减，随大陆度调制 | 对应 Step 6 副热带抑制 |

SotE `koppen.lua` 的 B 类阈值公式（`20·T + offset`，offset 由夏/冬降水占比取 0/140/280）
与 dreamulator `koppen_classify` 完全一致——交叉验证 B 阈值实现无误。

**通用性评估（对异星适应度）**：SotE 的「方向性」「2 月分解」「saldo」是**概念可借鉴**，
但其**实现是 Earth 特调**——方向用 `6*lat/90` sigmoid 硬编码三圈环流、基础温度用 Earth
观测纬度剖面（`80/68.5/59.5/43.1/21/5°` 分段线性）、Hadley/ITCZ 为预计算 Earth 场。对
Nacrea 单圈环流（`hadley_extent=90`）或三圈纬度不同的行星会错位。dreamulator 的正确做法
是**从自己的 `hadley_cell_wind`（`hadley_extent_deg`/`polar_cell_start_deg` 参数化）推导
「向风方向」**，替换各向同性 `distance_to_coast`——抄概念、第一性重推实现（「第一性 > 先验」）。

### 4.4 生态层

| 工具 | 用途 | 与 Dreamulator 的关系 |
|------|------|---------------------|
| [**Madingley Model**](https://github.com/Madingley/Madingley) | 通用生态系统模型（UNEP WCMC）：个体级异养 + 功能群自养。C#/R/Python | Dreamulator P2 "简单食物网"的参照；Madingley 是网格化全球生态模型，输出 NPP/生物量/功能群分布 |
| [**Biblaridion's Alien Biosphere**](https://www.youtube.com/playlist?list=PLB1C15C2225B4C9E8) | YouTube 方法论系列：物理约束→身体结构→进化枝→生态位→食物网→智慧生物 | Dreamulator P3 异星物种推演的直接参照（已在 [ecology-layer.md](proposals/ecology-layer.md) §三详细分析） |
| [**NetLogo**](https://ccl.northwestern.edu/netlogo/) | 基于 agent 的生态模拟平台 | 原型验证：食物网/种群动态/岛屿生物地理学 |
| [**EcoSim**](https://github.com/EcoSim) | C++ 个体级生态系统模拟 | P2 食物网的算法参考 |

### 4.5 文明层

| 工具 | 用途 | 与 Dreamulator 的关系 |
|------|------|---------------------|
| [**Clausewitz Engine**](https://eu4.paradoxwikis.com/Map_modding) (Paradox) | P 社大战略游戏引擎：省份/人口/经济/外交/战争 | 文明层"策略模式"建模的参照；Dreamulator 做离线推演而非实时游戏 |
| [**Seshat Global History Databank**](https://seshatdatabank.info/) | 全球历史数据库：300+ 社会、200+ 变量编码 | 文明推演验证数据源——"Dreamulator 生成的文明是否在 Seshat 的分布范围内？" |
| [**HANDY Model**](https://doi.org/10.1016/j.ecolecon.2014.02.015) | 人类-自然动力学：ODE 人口/资源/财富/生态承载 | Dreamulator 文明层 ODE 的范式参照 |
| [**Cliodynamics**](https://peterturchin.com/cliodynamics/) | 数学历史动力学：结构-人口理论 (SDT)、帝国兴衰建模 | 文明种子设计的理论框架（civilizations.yaml 引用的 HANDY/SDT 来源） |

---

## 五、Dreamulator 在工具谱系中的位置

```
                    科学精度
                        ↑
              CESM ●    │
              GPlates ●  │    ● Dreamulator（目标：各层级的"最小可行模型"串联）
       ExoPlaSim ●       │
              MESA ●     │    ● Gleba（同赛道，无分支/AI）
                         │
   ──────────────────────┼──────────────────────→ 架空自由度
                         │
       Azgaar ●          │    ● Dwarf Fortress（全链程序化，无物理约束）
  World Anvil ●          │    ● Ultima Ratio Regum
    Inkarnate ●          │
```

**Dreamulator 的独特生态位**：在 "科学工具"（精确但孤立、需专业知识）和 "创作工具"（自由但无物理约束）之间架桥。每个 DAG 层级不追求该领域最高精度，而是追求**层间因果传导**——改变地轴倾角→自动重算气候→自动更新生态→自动影响文明种子。

这一"受控因果链"是市面上任何单一工具都不具备的。

---

## 六、分辨率对标与数据处理方案（2026-08-10 基准测试）

### 6.1 各工具/领域精度对标

| 工具/领域 | 典型网格 | 间距 | dreamulator 对等 | 数据来源 |
|-----------|---------|------|-----------------|---------|
| **标准 GCM** (CMIP6) | ~200×100 格点 | 50–100 km | 200k ≈ 51 km ✅ 已达标 | CMIP6 规范 |
| **高分辨率 GCM** (HighResMIP) | ~500×250 | ~25 km | 500k ≈ 32 km ✅ 后端可行 | HighResMIP 白皮书 |
| **前沿 GCM** (NextGEMS) | ~2000×1000 | ~10 km | ~3M cells | NextGEMS (2024) |
| **NeuralGCM** (Google) | — | 140 km | 30k ≈ 140 km | Nature (2024) |
| **ExoPlaSim T21** | 32×16 谱 | ~620 km | dreamulator 200k 精细 **12×** | MNRAS (2022) |
| **ExoPlaSim T42** | 64×32 谱 | ~310 km | dreamulator 200k 精细 **6×** | MNRAS (2022) |
| **Azgaar FMG** | **10k cells** 默认 | ~200 km | 200k 已超 **20×** | Azgaar Q&A |
| **Dwarf Fortress** | 瓦片地图 | 局部 | 不同范式 | — |
| **World Creator / Gaea** | 百万顶点 | ~米级 | 局部地形雕刻，非全球尺度 | 官网 |

**关键发现**：dreamulator 的 200k（51 km）已经是世界构建工具的顶级精度，且前端已验证可用（~220 MB JSON，现代浏览器可加载）。ExoPlaSim（项目对标的简化 GCM）在 T21 下约 620 km——dreamulator 实际上比它精细 12×。500k（32 km）属于"高分辨率气候模型"级别。真正需要 >1M 节点的场景是局部地形雕刻（Gaea/World Creator 的领域），不属于全球气候推演范畴。

### 6.2 dreamulator 多分辨率基准测试

实测数据（seed=42，同一 geography.yaml，不同 `num_nodes`）：

| 节点数 | 间距 | 地质 | 气候 | ocean(GMRES) | 总计 | JSON 大小 | 前端可行性 |
|--------|------|------|------|-------------|------|----------|-----------|
| 100k | 71 km | ~126s | 68s | 32s | ~200s | 108 MB | ✅ 正常 |
| 200k | 51 km | 238s | 147s | 88s | **391s** | ~220 MB | ✅ 正常（gzip ~50 MB） |
| 500k | 32 km | 583s | 482s | **356s** | 1079s | 570 MB | ❌ OOM 失败 |
| 1M | 23 km | 1434s | 1003s | **764s** | 2464s | ~1.1 GB | ❌ 不可用 |

**瓶颈分析**：
- **后端**：ocean (GMRES) 是唯一超级线性瓶颈——100k→1M 缩放 23.8×（预期 10×）。各跳段：100k→200k 2.75×、200k→500k 4.05×、500k→1M 2.15×。200k（391s, ~6.5 min）为当前可接受的构建时间上限。地质层其余各阶段缩放健康（O(N) 到 O(N^1.5) 符合预期）。
- **前端**：JSON 格式的硬上限约 500k cells（570 MB → `JSON.parse()` ~2 GB 堆内存 → OOM）。200k（~220 MB JSON, gzip ~50 MB）可正常加载

### 6.3 业界数据处理方案对标

| 策略 | 使用者 | 原理 | dreamulator 可借鉴 |
|------|--------|------|-------------------|
| **二进制科学格式** (NetCDF/HDF5) | 所有 GCM、NASA、NOAA | 多维数组直接映射到磁盘，零解析开销 | MessagePack 替换 JSON → 文件减半，parse 快 10× |
| **分离静态/动态数据** | GCMs（网格 + 变量分文件） | 几何拓扑网格只存一次，气候变量按时间片存储 | 几何固定、气候/生态按需更新，增量构建只传变化量 |
| **层级 LOD** (Cluster Tree) | UE5 Nanite | 128 三角形一组 → 父子层级简化 → 只渲染可见 + 适当细节的 cluster | 前端只渲染可视区域 + 缩放级别对应的 cell 子集 |
| **GPU 端处理** | World Creator（全 GPU 渲染）、Gaea（GPU 侵蚀） | 所有计算在显卡上完成 | 已用 DataTexture 烘焙，可深化为 GPU 端 KD-tree |
| **分块构建** (Tiled Builds) | Gaea、Infinite Lands (Unity) | 将世界拆分为独立瓦片，按需构建和加载 | 按纬度带或板块拆分 mesh 文件 |
| **流式加载** | UE5 Nanite（SSD streaming） | 只从磁盘流式读取可见 cluster | 前端逐区域渐进加载 cell，非一次 570 MB |
| **Web Worker 解析** | 现代 Web 应用标准实践 | 在主线程外解析数据，通过 `postMessage` 传递 TypedArray | 二进制 + Worker → 主线程零阻塞 |
| **压缩编码** | UE5 Nanite（特殊 mesh 编码，7.6× 小于标准 mesh） | 定制二进制格式 + 量化 | gzip 已 4×，MessagePack + 浮点截断可再省 2× |

### 6.4 分辨率策略建议

1. **200k 为当前生产主力**（v0.24+）：51 km 已超过所有竞品和简化 GCM，前端已验证可用（~220 MB JSON，gzip 传输 ~50 MB）
2. **500k 作为"高精度模式"**（远期）：二进制格式改造（MessagePack + Worker）已完成，仍需评估解析后 JS 堆膨胀（3–4×）是否支撑后再开放
3. **1M+ 仅用于局部精细化**：不是全球均匀细化，而是选定区域用外部工具（Gaea/World Machine）做高分辨率雕刻，再回贴
4. **提高气候预测保真度优先于提高网格分辨率**：从 EBM 升级到简化 GCM（ExoPlaSim 路径）对输出质量的提升远大于 51→32 km 的网格细化

---

## 七、World Anvil 方法论参照（自洽性 vs 创造性）

> 2026-08-16 补：守护轴（[harness.md](proposals/harness.md)）设计时调研 World Anvil 的**方法论**（非工具功能，
> 工具功能对比见 §三.3）。本节聚焦 World Anvil 对「自洽性 vs 创造性」矛盾的处理方式，作为守护轴
> 「硬度旋钮 / 意图感知 / 后果映射」的业界参照。详表见
> `docs/knowledge/agent-engineering/self-maintenance-patterns.md` §三。

### 7.1 核心方法论：Agile Worldbuilding Method

World Anvil 创始人 Janet Forbes & Dimitris Havlidis 合创的 **Agile Worldbuilding Method**
核心口号是「**防止 over-worldbuilding（规则过多扼杀创造）和 under-worldbuilding（规则过少导致
lore drift）**」——这正是 Dreamulator 在 [vision.md](proposals/vision.md) §7「混沌边缘」和四层控制模型
「约束分级」所表达张力的业界版本：

| World Anvil 概念 | Dreamulator 对应 |
|---|---|
| over-worldbuilding（规则过多） | 混沌边缘的「规则太多 → 自相矛盾死锁」 |
| under-worldbuilding（规则过少） | 混沌边缘的「规则太少 → 失真」；守护轴的 silent drift / stale memory |
| Agile（敏捷迭代，先粗后细） | 设定维护工作流（拷问 → 补全 → 归档）的持续循环 |
| 逐条定「这一条要多硬」 | 四层控制模型的约束分级（Hard/Soft/Preference/Override） |

### 7.2 Hard vs Soft Worldbuilding（光谱）

[学院指南](https://academy.worldanvil.com/blog/hard-versus-soft-worldbuilding) 明确自洽性和创造性
是**光谱而非二元对立**，且「约束反而激发创造力」（Sanderson 第二定律：限制 > 力量）。对应 Dreamulator
的「硬度光谱」（vision.md §4 硬科幻 → 软魔法）+ 守护轴「硬度旋钮」（harness.md §10）。

### 7.3 核心资料清单

| 资源 | 链接 | 内容 |
|---|---|---|
| Worldbuilding Academy | https://academy.worldanvil.com/worldbuilding-courses | 免费课程；旗舰「How to Start Worldbuilding (101)」（Janet Forbes 主讲） |
| Agile Worldbuilding Method | https://academy.worldanvil.com/worldbuilding-courses | 防 over/under-worldbuilding 的方法论 |
| Hard vs Soft Worldbuilding | https://academy.worldanvil.com/blog/hard-versus-soft-worldbuilding | 自洽性 vs 创造性光谱 |
| World Anvil Blog | https://blog.worldanvil.com/ | 教程/技巧/活动；「Immersive Worldbuilding with Janet」YouTube 系列 |
| Janet Forbes | https://www.janetforbes.com/ | CEO/联合创始人，*Dark Crystal Adventure Game* 主作者；「4 Blueprints of Worldbuilding」webinar |
| WorldEmber | https://blog.worldanvil.com/worldanvil/events/worldember-advent-calendar-daily-prompts-for-you/ | 年度 12 月活动，31 天每日 prompt，社区共创 |

### 7.4 对 Dreamulator 的启示

1. **硬度可配置**：World Anvil 不强制每个用户「一样硬」，守护轴严格度应挂 per-world/branch 的
   「硬度档」（harness.md §2.4、§10）。
2. **自洽性的「成本」模型**（Sanderson 第一定律）：软设定机制可未知，但后果须映射到状态变量才能
   推演——守护轴的「后果映射」校验维度（harness.md §9.2）。
3. **canon 管理**：World Anvil 系工具对 lore drift 的解法（`Status: Canon` 标记、scratchpad 隔离
   非 canon 想法）→ 决策记录的 `status` + `divergence: intentional` 标记（harness.md §8.1）。

---

## 八、宜居卫星设定参照

> 2026-08-17 补：gaia-m 的 Nacrea 是「宜居卫星」设定，本节梳理采用了这一母题的作品/游戏，
> 作为设定参照与卖点依据（间奏曲 #8）。

### 8.1 电影 / 影视

| 作品 | 卫星 | 环绕对象 | 特征 |
|---|---|---|---|
| **阿凡达 Avatar**（卡梅隆） | 潘多拉 Pandora | 气态巨行星波吕斐摩斯（绕半人马座 α A） | 宜居卫星**原型**——略小于地球的岩质卫星，葱郁异星生态 |
| **星球大战 Star Wars** | 恩多 Endor | 双恒星系统 | 密林覆盖（伊沃克人） |
| | 雅文 4 Yavin 4 | 气态巨行星雅文 | 丛林卫星（义军基地） |
| | 阿奇托 Ach-To | 海洋星球 | 海洋卫星（绝地岛，《最后的绝地武士》） |
| | 穆斯塔法 Mustafar | 气态巨行星 | 熔岩卫星 |
| **异形 Alien** | Acheron / LV-426 | 行星 Calpamos | 荒凉岩质卫星 |

### 8.2 游戏

| 作品 | 卫星 | 特征 |
|---|---|---|
| **The Outer Worlds** | Monarch | 气态巨行星的卫星，主游戏区之一 |
| **无主之地前传 Borderlands: The Pre-Sequel** | Elpis | 潘多拉星的卫星，带稀薄大气/氧气 |
| **Destiny 2** | 月球（及多个卫星） | 殖民后的月球 |
| **Warframe** | Lua | 月球 |
| **No Man's Sky / Elite Dangerous / Stellaris** | 程序化宜居卫星 | 引擎允许生成宜居卫星 |
| **Mass Effect** | 月球、Ganymede 等 | 殖民卫星（非 lush） |

### 8.3 文学 / 动画

| 作品 | 卫星 | 特征 |
|---|---|---|
| **Aurora**（Kim Stanley Robinson） | 该行星的卫星 | 硬科幻系外卫星 |
| **2312**（KSR） | 多个卫星 | 太阳系内 |
| **Cowboy Bebop** | Ganymede / Callisto | 殖民卫星 |
| **Planetes** | 月球 | 殖民月球 |

### 8.4 科学背景（现实依据）

- **Kepler-1625b 候选 exomoon**：Teachey & Kipping (2018) 发现的海王星级候选卫星，位于宜居带——
  学界以「寻找潘多拉/恩多」作为 exomoon 探索的叙事锚点（[Space.com](https://www.space.com/42023-possible-exomoon-discovery-pandora-endor.html)）。
- **磁层屏蔽**：Heller & Zuluaga (2013) 提出巨行星磁层可保护卫星大气（即 gaia-m 决策记录
  `0006-habitability-protection.md` 引用的机制）。
- **关键论点**：绕红矮星气态巨行星的卫星**可能比被潮汐锁定的类地行星更宜居**（免受潮汐锁定之苦），
  与 Nacrea「绕 M 矮星巨行星」设定同构（[IAA-CSIC](http://sir.caha.es/news/releases-mainmenu-163/habitable-moons-around-cool-nearby-stars-from-science-fiction-to-reality)）。

### 8.5 与 Dreamulator 的对比

fiction 里的宜居卫星多为**地球级或更小**（潘多拉≈地球、恩多≈1/3 地球）。而 **Nacrea 是 1.2 M⊕
的「超级卫星」**，比绝大多数虚构宜居卫星都大——这是 gaia-m 相对稀缺的差异化定位，可作为卖点。

- [Pandora (Avatar) — Wikipedia](https://en.wikipedia.org/wiki/Pandora_(Avatar))
