# 极地气压与环流圈体制（极地高压何时成立）

> 2026-10 入库。动机：nacrea 两圈体制的 GCM 模拟显示纬向平均极地海平面
> 气压为**低**压，与「极地冷 → 空气下沉 → 高压」的直觉相反。本文厘清极地
> 高/低压的两类机制及其对环流圈体制的依赖，并给出世界构建时的判据。

## 1. 纬向平均地表气压跟着翻转环流的垂直支走

质量流函数（mass streamfunction）描述的经向翻转环流中，每个环流圈有
一个上升支和一个下沉支。统计稳态下，**下沉支对应地表高压**（空气在低层
辐散、柱内质量堆积，副热带高压即如此），**上升支对应地表低压**（低层
辐合、高层辐散把质量抽走，赤道低压带即如此）。这是连续性方程的直接
推论，与环流圈的热力驱动方式无关（参见 Vallis《Atmospheric and Oceanic
Fluid Dynamics》第 11 章的流函数框架）。

因此一个纬度带的地表气压高低，首先由「该处是哪个环流圈的哪个垂直支」
决定：

| 环流圈结构 | 极地垂直支 | 纬向平均极地 SLP |
|---|---|---|
| 三圈（地球型：Hadley + Ferrel + 极地胞） | 极地胞**下沉**支 | **高压**（叠加热力贡献，见 §2） |
| 两圈（慢自转：Hadley + 涡旋驱动间接胞抵极） | 间接胞**上升**支 | **低压** |
| 单圈（Hadley 直达极地） | Hadley **下沉**支 | 高压（动力性） |

慢自转行星（Ω ≲ 0.5 Ω⊕）处于两圈体制：Hadley 胞展宽（本库 nacrea 的
GCM 实测边界 ~47°），其外是一个涡旋（斜压瞬变波）驱动的间接胞，一直
延伸到极地而无独立极地胞（Kaspi & Showman 2015 的 Ω 体制判据：Ferrel
型间接胞在 Ω > ~1/4 Ω⊕ 出现并随 Ω 减小展宽；轴对称理论对 Hadley 宽度
的极限见 Guendelman & Schneider 2018）。极点于是是间接胞的上升支 →
纬向平均极地低压、地面西风一直吹到极地（无极地东风带）。

## 2. 热力性极地高压：真实但浅薄、且依赖冷下垫面

「极地冷 → 高压」的直觉对应另一类机制——**热力性反气旋**：雪/冰覆盖的
地表（冬季大陆、冰盖）强烈辐射冷却 → 边界层空气致密 → 近地面气压升高。
它的特征是**冷心、浅薄**：气压异常随高度迅速衰减并在中层反转成低压
（「the cold polar high weakens aloft to become a low at 700 hPa」），与
副热带那种动力下沉的**暖心深厚**高压形成对照（Reboita et al. 2019）。
原型案例：

- **西伯利亚高压**：冬季欧亚大陆表层强烈冷却形成的冷性浅反气旋
  （Britannica「Siberian anticyclone」；Cambridge《The Atmospheric
  Circulation》：「a cold, shallow anticyclone driven largely by radiative
  cooling to space」），冷空气受地形盆地堆聚而加深。
- **南极高压**：辐射冷却 + 下坡风（katabatic）排水 + 高原地形；注意观测
  「南极海平面高压」有一部分是高海拔归算到海平面的假象（Parish 1998,
  MWR）。
- 极地胞下沉支对极地高压的贡献在教科书框架中存在（NOAA JetStream），但
  量级上弱于热力项，且**以极地胞存在为前提**。

关键推论：热力性极地高压需要**持续强冷却的下垫面**（冬季大陆、冰盖、
雪被）。全球海洋世界（aquaplanet）或无冰盖世界缺少这个条件；此时纬向
平均极地气压的符号由 §1 的动力学项决定。两类信号可以并存：纬向平均为
低压的体制下，冬季冷大陆上仍可出现区域性的西伯利亚高压式热力高压
（区域模 vs 纬向平均是两个层次，不矛盾）。

## 3. 伴随的可观测指纹（用于校验模拟或设定）

两圈体制（极地低压）与三圈体制（极地高压）在纬向平均场上有一组联动
指纹，可用作模拟自洽性检查：

| 指纹 | 三圈（地球型） | 两圈（慢自转） |
|---|---|---|
| 极地 SLP | 极大（高于副极地槽） | 单调递减至极地极小 |
| 高纬地面纬向风 | 极地东风（极地胞地面支） | 西风延伸至极地 |
| 质量流函数符号翻转（北半球） | 两次（~30°、~60°） | 一次（Hadley 边界） |
| 极地垂直速度 | 下沉 | 上升 |
| 极地降水体制 | 极地沙漠（下沉支） | 偏湿（上升支；量级见引擎标定） |

本库 ExoPlaSim 对照实验（2026-10-05，T21L10 aquaplanet）：地球参数
配置复现三圈全套指纹（SLP 1009→1014→1005→1023 hPa、极地东风 −2.7 m/s、
ψ 三次翻转）；nacrea 参数（Ω=0.32 Ω⊕）复现两圈全套指纹（SLP 单调降至
~1004 hPa、地面西风抵极、ψ 单次翻转于 47°、极地上升）。同一模型两套
参数给出相反符号，说明气压符号是环流拓扑量而非模式噪声。

## 4. 对世界构建与引擎的含义

- 慢自转海洋世界不应先验假设极地高压或极地沙漠；极地偏湿（上升支）是
  体制的自然推论。nacrea 的 `terrain_config.yaml` 以
  `hadley_extent_deg=47 / polar_cell_start_deg=90` 编码两圈体制。
- 引擎的扩散 EBM 分支（`hadley_extent_deg < 90`）与 Held-Hou 单圈分支
  （`>= 90`）的切换即对应本文的体制切换；分支选择应由 GCM 或观测的
  流函数证据决定，不由调参 convenience 决定。
- 引擎当前在两圈体制下的副极地降水收敛环（~63–67°）相对 GCM 偏强约一个
  量级（上升支过窄所致），属标定轮待仲裁项（GCM 为 oracle）；本文只登记
  体制级结论，量级标定不在本文范围。

## 参考

- NOAA JetStream — Global Atmospheric Circulations（极地胞下沉与极地高压的教科书框架）
- Britannica — Siberian anticyclone / Polar anticyclone（热力性冷反气旋）
- Cambridge, *The Atmospheric Circulation*（ch. 4）—「cold, shallow anticyclone driven largely by radiative cooling」
- Parish, T.R. (1998), *Mon. Wea. Rev.* 126 — 南极海平面气压归算假象
- Reboita et al. (2019), *Front. Earth Sci.* — 副热带高压的动力下沉属性（对照热力性极地高压）
- Environment Canada, *AWARE* 航空气象教材 — 冷心高压随高度反转为低压
- Vallis, *Atmospheric and Oceanic Fluid Dynamics* ch. 11 — 质量流函数框架
- Guendelman & Schneider (2018), *GRL* — 轴对称 Hadley 宽度极限
- Kaspi & Showman (2015) — 自转速率与环流体制（间接胞/Ferrel 出现判据）
