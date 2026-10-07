# 审计第五波：对外设定文案审计（豁免叙事/类比词/数值一致性/文风）

> 日期：2026-10-07 · 触发：作者裁决「cadence 弹射不入对外天文学设定」「（木卫三
> 类比）类词语仅入设计笔记」「全局审计电报体与数值不一致」。范围：公开仓库
> （private/ 除外），重点 = `data/worlds/nacrea/layers/*/input/`（对外设定）与
> design-notes。方法：两个并行审计代理（数值一致性 + 文风/类比）全量扫描，
> 人工复核后修复。划分规范正文见根 CLAUDE.md「对外设定 vs 设计笔记的划分」。

---

## 一、结论速览

1. **豁免叙事出典清扫完成**：韵珠弹射/死期/「韵珠远行」/末世天象从全部对外
   设定（layers input md + yaml description）移除，仅保留 design-notes/0009
   与附录（含 §10 系综台账）。对外口径统一为「双珠与珠母星及文明长期相伴
   （作者裁决 2026-10-07）」+ design-notes 指针。sky_phenomena #15「韵珠远行」
   条目删除（视频素材侧影响已在 today.md Phase 2 登记）。
2. **类比词清扫完成**（对外设定）：stellar.yaml 七条 body description、
   satellite_architecture「太阳系类比」整列、Molniya/范艾伦/柯伊伯类似物/
   阿塔卡马/西伯利亚/北美大平原/澳洲/金星式/土星同类/木星系 DAM/木卫一
   5.9 R_J/GOE/LHB 等改为世界内表述。保留三类合法参照：面向读者的单位参照
   （满月/金星/Io 热流倍率/地球内热流）、地球 vs Nacrea 读者对比框架
   （civilization 层骨架，见 §五-1 待裁决）、学科通用术语（希尔球/洛希极限/
   Cassini 态/托林/Köppen 码）。
3. **数值一致性修复 ~45 处**（明细 §三）：路线 1 亮度/热流残留（上一轮漏网：
   K8→K6、φ=82.1°→82.7°、[Fe/H]−0.15→−0.19、11.03°→11.27°、78 m→61 m、
   74 万→72.3 万 km、37→29.4 Gyr、Ember 凌星 5.4→4.9 d、食频 11→6 次等）+
   3.147 d/75.5 h 旧周期家族统一为 3.138 d（恒星日）/75.3 h（潮汐钟）/
   77.8 h（相位=太阳日）三个口径 + coupled_magnetic 磁偶极倾角 9.0°→18.0°、
   背景场 0.360→0.384 μT（78×）。
4. **模板化 8 处**：space_age（Aegis 距离/主序寿命）、scientific_enlightenment
   （Aegis 视直径/潮差 ×2）、habitability_solutions（自转/太阳日）、
   coupled_magnetic（公转周期）、giant_brightness（极细相倍数）改用
   `{{ entities.* }}`/`{{ sky.* }}` 渲染，杜绝再漂移。
5. **发现一处真输入矛盾并已修**：`terrain_config.yaml` `rotation_period_days:
   3.147`（气候引擎实际消费的科氏力/扩散输入）≠ stellar.yaml 权威值 3.138
   ——已统一为 3.138。**影响**：Ω 差 0.3%，盘上气候产物为 3.147 构建，
   下次全量重建（Phase 2）自动归一，无需单独重建。
6. **电报体**：对外设定中重灾区 space_age.md 已全文改写；
   civilization_divergence 最差单元格已改写；其余中轻度文件（coupled_magnetic、
   habitability_solutions、long_term_cycles 正文箭头链、geological_history
   太古宙单元格）已局部修复或并入 Phase 2 文明/气候叙事重生成（该轮会整篇
   重写这些文档）。docs/usage 与 worldbuilding 的五处最重电报体登记不排期。

## 二、豁免叙事出典清扫（映射表）

| 文件 | 处置 |
|---|---|
| sky_phenomena.md #15 | 删除「韵珠远行」条目 |
| satellite_architecture.md | 豁免段改正面正典 + 0009 指针；「失稳前兆（诊断律）」→「远期增温趋势 = 诊断信号」 |
| stellar.yaml description（纪元约定/orbits 横幅/Cadence·Vigil 注与 description） | 弹射/死期/豁免细节移除，留「数值审计见 design-notes/0009 §2」 |
| planets.yaml Vigil 注释 | 同上 |
| long_term_cycles.md 行 6/§5/§6 | 「距韵珠远行还有多久」等移除；行 6 改双源泵浦 + 双珠长期相伴 |
| orbital_dynamics.md | 「叙事豁免」措辞 → 「长期动力学审计」指针 |
| design-notes/0009 + 附录 + README | 保留全部审计叙事（裁决指定的家） |

## 三、数值修复明细（权威源 = system_catalog + 0009 定版带）

| 文件:行 | 旧 | 新 |
|---|---|---|
| world.yaml / astronomy `_overview` / sky_phenomena:59 | K8 | K6 |
| long_term_cycles:25,74 | φ=82.1°、2.2 d | φ=82.7°、2.0 d |
| long_term_cycles:138 | [Fe/H]=−0.15 | −0.19 |
| long_term_cycles:47 | 断链 climate-engine.md | proposals/climate-layer-improvement.md |
| coupled_magnetic:15,23,24,32,33,39 | 9.0° / 0.360 μT / 83.3× / 75.5h / 0.36 μT | 18.0° / 0.384 μT / ~78× / 模板 75.3h / 0.38 μT |
| satellite_architecture:14 | ~8× 木星 | 删倍数（见 §五-2） |
| physical_params:36,40 | 3.147 d / τ_e 4.2 | 3.138 d / 4.1 Myr |
| tidal_effects:58,104,135 | 75.5 / 历史叙事括注 / 3.147 | 75.3 / 现行陈述 / 3.138 |
| terrain_config:27,153,186 | 3.147（输入值）/ 75.5h / 724 000 km·10.1 R_p | 3.138 / 75.3h / 723 300 km·10.15 R_p |
| stellar.yaml:467,470 注释 | 3.147 d / 4.2 Myr | 3.138 d / 4.1 Myr |
| giant_brightness:24 | 极细相约 0.3 倍满月 | 模板渲染（≈0.5 倍，821×Φ(170°)） |
| space_age:27,28,30,41,47,49 | 74 万 km/2.5s、0.15–0.2 AU、37 Gyr、74 万、Ember 5.4 d、柯伊伯类似物 5–10 AU | 模板 72.3 万/2.4s、0.26–0.32 AU、模板 29.4 Gyr、模板、4.9 d（会合）、墟带 1.4–2.7 AU + 奥尔特 ~10³–6×10⁴ AU |
| scientific_enlightenment:13,16,24,26,27 | 11.03°/450×、78 m ×2、Ember 5.4 d、每年 11 次 2.5h | 模板 11.27°/470×、模板 61 m、4.9 d、~6 次（5–9 轮转）2.2h/全程 2.45h |
| habitability_solutions:11,18 | 75.5h/3.147 天昼夜、0.36 μT | 模板（恒星自转 75.3h + 太阳日 3.24 d）、0.38 μT |
| civilization_divergence:22 | Aegis 相位 75.5h | ~77.8h（= 太阳日，相位周期是会合拍） |
| ecology 家族 6 处 | 75.5h | 75.3h（潮汐钟）/ 77.8h（相位生物钟） |
| 0010:113 / geological_history:24 | 3.147 d / GOE | 3.138 d / 大氧化事件 |
| climate_portrait:48 | 99.7 d | 99.8 d |

**口径约定（本轮确立）**：恒星日（=公转周期）3.138 d / 75.3 h = 潮汐钟与
「自转」语境；太阳日 3.24 d / 77.8 h = 昼夜交替与 Aegis 相位语境；两者不得混写。

## 四、类比词处置

- **已删（对外设定）**：stellar.yaml descriptions（Europa 大小/Charon 级/火卫一/
  欧罗巴/木卫三/木卫四/海卫一/阋神星 Dysnomia/迷你海卫一式）、satellite_
  architecture 类比列与「海卫一同类比/加尔尼群/LHB」、space_age（Molniya/
  范艾伦/柯伊伯带类似物）、habitability_solutions（Molniya）、climate_zones
  （阿塔卡马）、climate_portrait（西伯利亚/北美大平原 ×2）、geography（澳洲）、
  orbital_dynamics（金星式/土星同类）、astronomy_spaceflight（木星系 DAM/
  木卫一 5.9 R_J）、geological_history（GOE 缩写）、sky_phenomena（类金星大距）。
- **保留（合法）**：单位参照（满月/金星/Io/地球内热流倍率、地月距离、地球
  1960s 年代对照）；读者对比框架（civilization 层「地球 vs Nacrea」表、
  geological_history「地球对比」节、physical_params Q 值观测锚表）；学科通用
  术语（Cassini 态、洛希极限、希尔球、Köppen 码、托林、奥尔特云、特洛伊、
  L4/L5）；yaml 注释中的类比（内部编写依据，不渲染）；「雪球地球/泥泞雪球」
  （后者是自有名词，前者作体制术语保留于对比表）。
- **文献引用**：对外文档中的学术引用（Christensen 2009、Peale & Cassen、
  Sudarsky、Izidoro 等）判定为科学出处标注、合法保留（知识库准则要求出处）。

## 五、作者裁决（2026-10-07，全部已执行）

1. **「地球 vs Nacrea」对比框架 → 移设计笔记**：新建
   `design-notes/0011-civilization-earth-comparison.md` 存档全部对比表；
   space_age（科技树总表去地球列）、scientific_enlightenment（双表去地球列、
   「开普勒三大定律」→「行星运动三定律」）、coupled_magnetic（生物效应/
   电磁学催熟去对比列）、civilization_divergence（「哥白尼革命」→「宇宙观
   革命」、「地球式霸权」改世界内表述）、astronomy_spaceflight（「伽利略
   证据」「巴比伦加速器」改世界内表述）。climate_portrait 的「实际地球」
   对比列归 Phase 2 重生成时迁入 0011（0011 头部已登记）。
2. **Aegis 磁场 = 400 μT 定值；「8× 木星」为错误值，已全库删除**（对外
   satellite_architecture/coupled_magnetic、设计笔记 0006 同步）。
3. **×Io / ×木星 / ×满月 单位倍率保留**（单位参照例外确认）。
4. **0008 §① 已按 GCM Hadley 52 设定更新**：口径 NH=80 m/s（N=0.01 s⁻¹、
   H=8 km）→ L_R≈2440 km、a/L_R≈2.8、S≈7.8（地球 780/8.2/67）；体制图景
   改写为「宽 Hadley（0–52°）+ 高纬浅极地胞两圈」，斜压活动带位于 52°
   外缘与高纬锋区；~560 mm 旧幅度数字撤回，待 GCM 轮 02 风暴带输出复核。

## 五-bis、结构重组轮（2026-10-07 深夜，作者指令「整理设定文档」）

在同一轮内追加执行的对外设定结构重组（全部为文档级，无设定值变更，除注明）：

1. **新增 `cycles_registry.md`（天文学层）**：全系统周期节律的单一查阅入口
   ——从 10 h Aegis 自转/38 h 电流片穿越/3.138 d 主潮/3.24 d 太阳日，经
   48 d 食季、13 yr 近日点大年、~1500 yr 双掩大连珠，到 2.85 kyr 链呼吸、
   20 kyr 万年火山脉冲、120 Myr 超大陆旋回；每行含驱动机制、可观察后果、
   权威出处与修改同步规则。long_term_cycles.md 头部加指针。
2. **giant_brightness.md 并入 sky_phenomena.md**（消除同主题双文档）：亮度
   参数表进 §2、日食地理隔离表进 §5；test_doc_render 锚随迁；引擎注释
   （sky_geometry/physical_inputs）与 test_sky_geometry 的旧正典锚
   （1.91 W/m²/−26.20/−19.57 等）全部升级为现行正典（2.79/−26.65/−20.02）。
3. **生态层去重**：ecology.md 原为四篇专题的全文合并且已数字漂移（迁徙
   速度两套值 53/61 km 每天），改为层导览（专题文档 = 单一事实源）；
   迁徙动力学按 99.8 d 年重算（最低连续速度 71 km/天、年行程 ~7,100 km、
   4 段单程）；stable_ecosystems 带界按定版气候修订（雨林 0–20° →
   赤道-热带簇 ~20°S–20°N、全年 19–27°C；「高纬雾林 60–75°」→「苔原缘
   52–62°、0–4°C」——旧带界在 62 K 温室构建下成立，冰盖扩张后作废）。
4. **气候层三篇刷新**：atmospheric_dynamics（三圈 55° → 宽 Hadley 52° 两圈、
   Ω/f 按 3.138 d 重算、去除陈旧 build 戳）；climate_zones（seed42 时代统计
   全部按定版构建重算：19 类 Köppen、EF 24.1%/BSk 18.8%/Cfb 13.2%、纬度带
   构成、Af 两簇、Cs 285 格、季节 24.95 d、极夜 49.9 d）；climate_portrait
   （62 K 暖世界叙事 → 35 K「凉温带湿润」世界：陆地均温 7.6°C、宜居陆地
   70.3%、温程中位 6.0 K、无 D 保持；地球对比列迁 0011）。climate_zones 与
   climate_portrait 头部加「滚动文档」标记（作者指令：随气候引擎改进轮持续
   变动，每次重建后须复核）。
5. **超大陆旋回口径统一**：太古宙 ~70 Myr（板块 30–40 cm/yr）→ 现行
   ~120 Myr（第 51 次旋回裂解中期），tidal_effects 的「~2 亿年」与
   geological_history 的「~1 亿年」收敛为该口径。
6. **geological_history 地球对比表迁 0011**（0011 标题相应泛化为
   「对外设定的地球对比框架」）；geography.md 全局指标按当前网格重测
   （陆地 59,731 格 29.9% / 174.3 M km² / 陆块 303 / 封闭内湖 5 处）。
7. **登记待裁决（新）**：叙事口径「海洋覆盖 72%」（stellar.yaml 描述等多处）
   与构建实测 70.1%（陆地 29.9%）差 ~2 个百分点——统一到哪边需作者定
   （改叙事 = 动多处 description；改目标 = 动 land_fraction_target）。

## 六、遗留（并入 Phase 2 / 登记不排期）

- climate_portrait（62 K/55° 旧口径）、atmospheric_dynamics（三圈 55° 结构性
  错误：现行为两圈 Hadley 0–52 + 极地胞 52–90）、climate_zones（55° 族）
  ——Phase 2 气候叙事重生成整篇重写。
- UCC yearly 15 份 10-05 旧口径导出——Phase 2 regen。
- 电报体中轻度残留（coupled_magnetic 表格引注、long_term_cycles 正文箭头链、
  geological_history 表格密度）——Phase 2 重写时按规范收口。
- docs/usage 与 worldbuilding 电报体最重五处：`usage/skills.md`、
  `worldbuilding/terrain_tuning_guide.md`、`worldbuilding/narrative_craft.md`、
  `usage/map-workflow.md`、`worldbuilding/map_design_guide.md`——登记不排期。
- ecology 带界描述与 hadley52 后生物群系的一致性——Phase 2 生态重生成时核。
- terrain_config `rotation_period_days` 修正（3.147→3.138）使盘上气候产物
  过期 0.3%（Ω 项）——Phase 2 全量重建自动归一。
