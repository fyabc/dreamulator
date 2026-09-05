# 气候层改进方案

> **状态**：攻关主线提案（2026-09-05 立项，承接季风 Wave A/B 与第一轮全面诊断）。
> §1 科氏力符号 ✅ 已合入；§2 季风 ΔP 高地热源为**方案底稿**（待与技术债 24 捆绑落地）；
> §3–§7 为诊断排序出的攻关项（P1–P6），全部为提案状态。
> **落地去向**：各项实现后，技术参数/流程写入 [pipelines/climate-pipeline.md](../pipelines/climate-pipeline.md)，
> 验证方法/指标写入 [pipelines/climate-validation.md](../pipelines/climate-validation.md)；
> 本文件保留设计依据（物理第一性 + 文献 + 引擎参照）与实验记录。
>
> 原则：每个决策有**物理第一性**、**地球真实参考**或**业界成熟方案**三者之一支撑；同物理
> （所有世界同一套引擎）；第一性 > 启发式；**动标定态前先做幅度敏感性实验**
> （2026-09-05 Wave B 教训，见 §2.4）。

---

## 0 总览与基线

**当前基线**（earth/climate-dev，Wave A 态，2026-09-05）：

| 指标 | 值 | 说明 |
|---|---|---|
| Köppen 30 类准确率 | 30.5% | cell-by-cell vs Beck 2018 |
| Cohen's Kappa（30 类） | 0.262 | |
| 5 群准确率 / Kappa | 67.4% / 0.583 | D 群仅 4.4% |
| 温度纬向 | RMSE 3.1°C、R² 0.955 | 形状对，极地/大陆内部偏置 |
| 降水纬向 | RMSE 334 mm、R² 0.503 | **形状错**（物理问题） |
| 站点 mean\|ΔP\| | 458 mm/yr | 26 站（`station_diagnostics.py`） |

空间最差格：整个 45±7.5°N 带（0~2%）、西非 15°N（0.8%）、印度洋 0°/60°E（5.7%）。
诊断产物（7 份，可复跑）在 `private/diagnostics/`，脚本见 §8。

**攻关排序**（影响 × 难易，依据 §3–§7）：

| # | 主题 | 状态 | 依赖 | 规模 |
|---|---|---|---|---|
| §1 | 季风边界层科氏力符号 | ✅ 已合入 | — | 小 |
| §3 | 极地偏暖偏湿（P1） | 提案 | — | 小-中（quick win） |
| §4 | 大陆冬季过冷 / D 群崩溃（P2） | 提案 | — | 中 |
| §5 | 海→陆水汽过强 + 风暴路径（P3） | 提案（挂起项立项） | §3 §4 | 大 |
| §2 | 季风 ΔP 高地热源（P4，Wave B 底稿） | 底稿，待捆绑 | §5 + 技术债 24 | 中 |
| §6 | ITCZ 雨带形状（P5）/ 陆蒸偏低（P6） | 提案 | §5 | 中 |

---

## 1 季风边界层科氏力符号翻正（✅ 已合入）

**问题**：`monsoon_boundary_layer_wind` 动量平衡误写 `0 = G + f k̂×v − k_d·v`，正确为
`0 = G − f k̂×v − k_d·v`（右手 ENU 基底、f>0 北半球偏右）——北半球热低压得到反气旋式
流入，南亚/东亚夏季风环流方向镜像。

**定位方法**（纪律样例）：合成点解析场探针实测——`_geostrophic_wind` 的 `r̂×∇p/(fρ)`
符合 Buys-Ballot（勿动），仅季风闭式解反号。**先实测子模块、勿凭坐标约定推翻全局**
（此前「三处一起动」假设被实测推翻）。

**改动**：闭式解两处符号 `v_e=(k_d·G_e+f·G_n)/D`、`v_n=(k_d·G_n−f·G_e)/D`；
docstring/知识库 §4.5/管线文档同步；南/北半球气旋流入单测。

**结果**：kappa 0.265→0.262 持平、准确率 30.5%、温度 R² 0.955；站点诊断季风区降水
普涨（上海 676→1531、北京 364→586）；7 月风向仍未转夏季风（ΔP 强迫与胞圈迁移问题，
§2/§6 域）；降水纬向 R² 0.589→0.503（季风环流重构的代价，随 §5/§2 收回）。

---

## 2 季风 ΔP 高地热源（Wave B 方案底稿，待与技术债 24 捆绑）

### 2.1 问题

季风 ΔP 用**地表温度**季节异常（`pressure_anomaly_monthly`），抓不到两类加热：
- **印度深对流加热**：季风热低压由整层对流层加热维持，地表被云雨冷却，季节地表异常仅
  +4.5 K → 印度热低压只有 −3.9 hPa（观测 ~−10 主导）；
- **高原表征错乱**：青藏以 4844 m 海拔的地表温度参与，季节摆动 +9.3 K → −8.2 hPa，
  反而主导——与「高原是抬升热源、非地表热源」相反。

### 2.2 文献依据

- [Boos & Kuang 2010, *Nature*](https://www.researchgate.net/publication/51441306_Dominant_control_of_the_South_Asian_Monsoon_by_orographic_insulation_versus_plateau_heating)：
  南亚季风主导因子是地形屏障（挡住干冷空气）+ 低地加热，非高原加热本身。
- [Boos & Kuang 2013, *Scientific Reports*](https://pmc.ncbi.nlm.nih.gov/articles/PMC3561641/)：
  敏感性实验——抑制北印度**非抬升**加热：低层风 −1.1 m/s、降水 −1.2 mm/d；抑制高坡地
  加热影响更弱（0.89/0.47），尽管焓损失相当（234 vs 225 TW）。**非抬升加热主导**。
  季风水汽大部分位于海拔 ~3 km 以下（z_moist 锚点）。
- [Wu et al. 2012](https://pmc.ncbi.nlm.nih.gov/articles/PMC3349950/)：地表感热增熵触发
  低层上升；高原是感热驱动的大气泵，上升支最大值近地面。

### 2.3 方案（底稿）

静力响应加两个海拔依赖因子：

```
ΔP = −P(z) · f(z) · ΔT / T̄_zonal
P(z) = P_sfc·exp(−z/H)      # 局地气压：气压异常 ∝ 上方气柱质量（H 标高 ∝ 1/g）
f(z) = f_deep·exp(−z/z_moist)  # 加热比例：水汽顶之上加热的是干空气，投影小
```

z_moist = 3 km（文献锚点）；P(z) 无自由参数。效果：印度 −4.5 hPa、青藏压到 ~−1 hPa，
主导权翻转（7:1），方向与文献一致。

### 2.4 三档实验与结论（2026-09-05，**勿单独落地**）

| 档位 | 全球幅度 | 纬向降水 R² | kappa | 结果 |
|---|---|---|---|---|
| 基线（depth_fraction 0.25 均匀） | 1× | 0.503 | 0.262 | 现态 |
| f_deep=0.7 | 2.8× | **0.079** | 0.220 | 灾难：亚马逊 Af 崩、撒哈拉变湿（depth_fraction 灾难重演） |
| f_deep=0.35（全球中性） | ~1× | 0.387 | 0.249 | 仍全面回退 |

**结论**：物理方向对，但现水分收支紧平衡围绕「青藏 −8 hPa 低压存在」共适应——压掉它
水分重分配（撒哈拉 379→445、萨赫勒 573→707、上海/达尔文站点爆表）。**必须与技术债 24
（环流胞圈逐月迁移）捆绑再标定后落地**，单上必回退。已全部回退，底稿保留在本节。

---

## 3 极地偏暖偏湿（P1）

### 3.1 海冰表面温度（✅ 已实现，2026-09-05）

**根因**：模型把冰盖海洋表面当 −1.8°C 开阔水（冻结点）——真实冰面经海冰隔热后
与大气平衡，年均远低（中央北极 ~−16°C）。−1.8°C 经能量限制蒸发公式产生 ~500 mm/yr
冰面蒸发（观测冰区蒸发 O(100 mm)），就地雨出 → 极地偏湿；温度本身 +13.8 偏暖。
参照：Semtner (1976) 零层海冰热力学（冰面能量平衡）。

**实现**（`_ocean_surface_temperature`）：
- 冰面温度 = 观测锚定剖面（NCEP 纬向平均表面温度，冰区边缘→极点逐段线性：
  NH 72° −6 → 80° −12 → 90° −17；SH 63° −4 → 70° −13 后持平，72°S 以南为南极陆地），
  与开洋分支同样随全球均温 1:1 平移（异星气候态自适应）。
- 冰缘改半球不对称：年均海冰范围（NSIDC 1981–2010：北冰洋 11.7 Mkm² ≈ 72°N、
  南极 11 Mkm² ≈ 63°S），sigmoid 宽度 6°；此前对称 70° 不符。
- 温度夹取下限 −2 → −60（允许真实冰面温度）。

**结果**（earth，κ 保持中性前提下）：温度纬向 RMSE **3.13 → 2.1**；88N 温度偏差
**+13.8 → +0.3**、88N 降水偏差 +167 → +27；降水纬向 R² 0.503 → 0.506；κ 0.262 → 0.260
持平；站点遥相关干净。

**事故记录**：首版把 `abs_lat` 从弧度重构成度数时漏了 `sin()` 仍消费弧度，
开洋 SST 剖面变剧烈振荡，洋流半拉格朗日平流把 ±30°C 异常搅到全球（温度验证
RMSE 3.1→8.2 FAIL）。教训入 today.md：改三角函数输入单位前全局搜索变量消费方。

### 3.2 寒带降水低温钳制（提案，未实现）

**残余症状**：南极大陆降水 663 vs 观测 145 mm（北极已修好）——南极是陆地，
水分来自南大洋平流/扩散，雨出率对 −30°C 无物理钳制（模型 W 场不受饱和约束，
冷空气柱照样雨出）。

**方案方向**：柱水汽饱和上限 W ≤ W_sat(T) ≈ q_sat(T_sfc)·H_v·ρ_air/ρ_w
（q_sat 为 Clausius-Clapeyron 饱和比湿、H_v ≈ 2.1 km 水汽标高；量级自洽：
0°C ~10 mm、−20°C ~2.7 mm、25°C ~51 mm 可降水量），超额立即雨出。
属水分预算求解器改动（紧平衡系统），动手前先做幅度敏感性实验（纪律 ⑤）。

---

## 4 大陆冬季过冷 / 季节振幅过大（P2，D 群崩溃）

**症状**：D 群准确率 4.4%；Dfc→Dwb/Dfb/ET 合计 ~5600 混淆（前二）；站点：莫斯科年均
−4.8 vs +5.8、振幅 53.6 vs 25.9，乌鲁木齐/丹佛/芝加哥同型（年均低 8–11°C、振幅
1.7–2.1×）；纬向 52–62N 陆地 −2.7~−9.6。

**根因假设（待纬度×季节偏差分解后定位）**：
1. 季节 EBM 冬季经向热输送不足（显式热输送的四极模阻尼在冬季是否过强？）；
2. 雪冰反照率在大陆内部过强（季节冰反照率把大陆内部冬季打太冷）；
3. 大陆度参数（D_land=0.2）与冬季缺静止波/海洋放热的叠加。

**参照**：Held-Suarez 类实验的冬季输运；North 1975 季节 EBM；
`docs/knowledge/climatology/energy_balance.md` §6 季节 EBM。

**方案方向**：先做「纬度 × 季节」温度偏差矩阵分解（模型−ERA5），定位是振幅问题
（热容量/阻尼）还是均值问题（反照率/输送），再对症。影响最大（D 群 13214 格 + C 群级联）。

---

## 5 海→陆水汽输送过强 + 中纬风暴路径欠输送（P3，大标定轮）

**症状**：海→陆输送陆均 514 vs 观测 ~268 mm（**~2× 过强**，与 2026-08 诊断一致）；
38–52N 纬向降水 −350~−550（风暴路径缺）；沙漠偏湿（开罗 177/24、达喀尔 784/405、
BWh→湿类混淆 ~4500）；中纬内陆偏干（伦敦 302/604、芝加哥 496/884）；部分沿海过湿
（墨尔本 1776/648、达尔文 3850/1581、上海 1531/1116）。

**对应**：路线图技术债 20②（风暴路径陆均贡献 ~132 vs 观测 900–1000）+ κ 标定
（3.75e5 曾从 1e6 下调）。即此前「长期排队」的挂起项，§3/§4 落地后正式立项。

**参照**：ExoPlaSim 显式解析涡旋、风暴路径降水涌现（PoC 已跑通，nacrea Ω 扫描在案）；
van der Ent / Savenije 水汽输送观测约束。

**方案方向**：κ 空间化（中纬涡旋扩散增强、副热带抑制）+ 风暴路径雨出增强的幅度/位置
再标定（斜压带 `_baroclinic_band` 已有位置推导，缺幅度标定）。此轮会顺带裁决
自由参数第二波（技术债 16：lat_gradient_earth_c、hadley_extent_deg、ITCZ sigma_deg）。

---

## 6 ITCZ 雨带形状（P5）与陆地蒸散（P6）

**P5 症状**：5N 核心 1149 vs GPCP 2170（偏弱）、12–18N +317（偏湿）；对流增强项
陆均仅 133。随 §5 的 κ/风暴路径调整一并观察。
**P6 症状**：陆地蒸散 317 vs 观测 ~490。候选机制：土壤湿度记忆（bucket model）——
干土增感热减潜热的正反馈，稳定沙漠边界（interlude 外部建议，待 §5 后裁决）。

---

## 7 季风建立（P4，依赖 §2+§5+技术债 24）

**症状**：Delhi 186/773、Dhaka 883/2023、广州 1029/1742；7 月风向仍偏北来向；
Aw→BWh/BSh 混淆 ~2300；0N60E 格 5.7%。

**依赖链**：§2 底稿（ΔP 热源）提供强迫、技术债 24（环流胞圈逐月迁移）提供季节风反转、
§5 清理水分路由——三者捆绑才是「季风建立」的完整攻关。验收锚点：印度 7 月偏南来向 +
降水到位（`station_diagnostics.py` Delhi/Dhaka/Guangzhou）+ Congo 水分路由（技术债 24 锚点）。

---

## 8 诊断基建（验证方法，待并入 climate-validation.md）

| 脚本 | 内容 | 耗时 |
|---|---|---|
| `validate_climate.py` | 纬向 T/P（ERA5/GPCP）+ Köppen 分布/空间 + 陆地比 | ~5 min（重跑模拟） |
| `diagnose_koppen_confusion.py` | 30 类 precision/recall/F1 + 混淆对 | ~5 min |
| `diagnose_koppen_spatial.py` | 15°×30° 格准确率（找空间错误集中区） | ~5 min |
| `diagnose_latitudinal_profile.py` | 纬向 T/P 逐带偏差（海陆拆分） | ~5 min |
| `diagnose_precip_budget.py` | 降水预算分解 + 水循环闭合检查 | ~5 min |
| `diagnose_wind_divergence.py` | 风场散度带（ITCZ/副高/极锋位置） | ~5 min |
| `station_diagnostics.py` | 26 基准站逐月 T/P/风向（读构建产物，秒级） | 秒级 |
| `diagnose_monsoon_regional.py` | 8 季风区逐月降水相位/量级（秒级） | 秒级 |

**注意**：前六个脚本**重跑模拟**且默认 `--world-dir data/worlds`——诊断开发态必须加
`--world-dir private/worlds`；后两个读构建产物，需先 `dreamulator build --only climate`。
验证基线数据（Köppen 观测、ERA5/GPCP 纬向值）的出处与下载见
[pipelines/climate-validation.md](../pipelines/climate-validation.md)。

**竞品引擎参照**：Gleba（Calandiel，本机 `E:\Gleba-0.3.5\`，Godot 4.7）——不做流体力学，
追踪高/低压中心季节移动（ITCZ/副高/极锋三振荡带），群系由季节性风×洋流交互导出；
其「气压中心迁移」与技术债 24 同向。ExoPlaSim PoC（`private/external-projects/exoplasim_poc`，
nacrea Ω 扫描已跑通）。

---

## 9 实现顺序

| 顺序 | 项 | 依赖 | 依据 |
|---|---|---|---|
| 1 | §3 极地（SST 剖面 + 低温雨出钳制） | — | Clausius-Clapeyron 约束，独立 |
| 2 | §4 大陆冬季（先偏差分解再动手） | — | D 群 4.4%，影响最大 |
| 3 | §5 水分路由大标定（κ + 风暴路径） | §3 §4 | 技术债 20②，ExoPlaSim 参照 |
| 4 | §2+§7 季风（ΔP 热源 + 胞圈迁移捆绑） | §5 | 技术债 23/24 |
| 5 | §6 ITCZ/陆蒸 搭车 | §5 | |

每步验收：validate_climate 指标不回退 + 对应站点/区域诊断改善 + nacrea 回归（同物理）。

---

## 参考资料

- Boos, W. R., & Kuang, Z. (2010). *Dominant control of the South Asian Monsoon by orographic insulation versus plateau heating*. Nature.
- Boos, W. R., & Kuang, Z. (2013). *Sensitivity of the South Asian monsoon to elevated and non-elevated heating*. Scientific Reports. [PMC3561641](https://pmc.ncbi.nlm.nih.gov/articles/PMC3561641/)
- Wu, G. et al. (2012). *Thermal Controls on the Asian Summer Monsoon*. Scientific Reports. [PMC3349950](https://pmc.ncbi.nlm.nih.gov/articles/PMC3349950/)
- Held, I. M., & Hou, A. Y. (1980). *Nonlinear axially symmetric circulations in a nearly inviscid atmosphere*. JAS 37.
- North, G. R. (1975). *Theory of energy-balance climate models*. JAS 32.
- Gleba — Calandiel 世界生成器（本机 `E:\Gleba-0.3.5\`）：[itch.io](https://calandiel.itch.io/gleba)、[Devlog #3 气候模型](https://calandiel.itch.io/gleba/devlog/1452492/devlog-3-winds-ocean-currents-and-orbs)
- ExoPlaSim（系外行星 GCM）PoC：`private/external-projects/exoplasim_poc`
- 源码：`map/climate_simulator.py`、`engine/climate_physics.py`、`engine/climate_seasonality.py`、`engine/monsoon_circulation.py`。
