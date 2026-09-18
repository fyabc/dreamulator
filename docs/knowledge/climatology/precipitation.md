# 降水：水汽输送、相态与地形效应

> 为 dreamulator 气候引擎的降水模块提供参考。降水由质量守恒水汽收支
> （`climate_simulator.py:_solve_moisture_budget`，公式与各项含义见
> `energy_balance.md` §8）+ 预算内的地形抬升凝结（本文 §三）+ 相态（雨/雪）
> 转换构成。本文档收录降水相态、低温降水与地形降水的科学底座。

---

## 一、饱和水汽压与 Clausius–Clapeyron 方程

饱和水汽压 $e_s$ 随温度**指数**上升（Clausius–Clapeyron 关系）：

$$
\frac{1}{e_s}\frac{de_s}{dT} = \frac{L_v}{R_v T^2}
$$

- 积分近似（**Magnus 公式**，引擎的海岸辐合与饱和比湿计算采用）：$e_s = 611.2\cdot\exp\!\left(\frac{17.67\,T}{T+243.5}\right)$，$T$ 为 °C。
- **每升温 1°C，$e_s$ 增加约 6–7%**——这是"暖湿 / 冷干"的根本来源。
- **三相点（0°C）$e_s = 611.2$ Pa，不为 0**；冰面饱和水汽压略低于过冷液态水（混合云中冰晶增长、液滴蒸发，是温带降水的微物理引擎）。
- 比湿 $q = 0.622\,e_s/P$（$P$ 为气压）。

**对引擎的含义**：低温区的 $q_{sat}$ 确实远低于暖区（−0.3°C 时约为 15°C 的 35%），
但**不会在冰点附近趋近 0**——任何让"降水在 T<0°C 时崩溃到 ~0"的公式都是有问题的。

---

## 二、降水相态：雨 vs 雪（临界温度）

气温跨过冰点时，降水**相态改变**（雨 → 雪），但**总量不消失**：

- **临界气温法**（水文模型通用）：单阈值（如 ~1°C）或双阈值（0–2°C 区间线性插值）
  把降水分为雨/雪（VIC、SWAT、HBV 等）。
- **地面气温 0–2°C** 是雨雪判别关键区间；地面日最低气温 2°C 可作简单分界。
- **降雪比例存在阈值效应**：雨雪过渡带（降雪比例 0.13–0.87）对升温最敏感；
  低于 0.13 为降雨主导，高于 0.87 为降雪主导。
- **关键结论**：冻原/冰原（T<0°C）年降水仍有 **~200–400 mm**（以降雪为主），
  而非接近 0。引擎把高纬冻原降水衰减到 ~5 mm 是**过度**的。

---

## 三、地形降水与雨影（抬升凝结）

湿润空气被迫沿迎风坡抬升时按（湿）绝热直减率冷却，饱和比湿随
Clausius–Clapeyron 关系（§一）指数下降，多余的水汽凝结成云并降落——这是
**地形降水**；气流越过山脊后下沉增温、相对湿度下降，背风侧因此干燥，即
**雨影**。两者是同一个抬升凝结机制的两面，不是两条独立规则。

**抬升凝结份额**。气块抬升 $\Delta z$ 冷却 $\Gamma\Delta z$（$\Gamma$ = 直减率，
°C/km），由 CC 关系可推出饱和比湿的相对下降为指数形式：

$$\frac{q_{sat}(T-\Gamma\Delta z)}{q_{sat}(T)} = \exp(-\Delta z / H_{cc}),\qquad
H_{cc} = \frac{R_v T^2}{L_v\,\Gamma}$$

其中 $H_{cc}$ 称**抬升干燥尺度**（热带约 2.0–2.6 km；$R_v$ = 水汽气体常数
461 J/(kg·K)，$L_v$ = 凝结潜热 2.5×10⁶ J/kg，$T$ 以 K 计）。凝结份额
$\varphi = 1-\exp(-\Delta z/H_{cc})$：抬升 1 km 约凝结 35%、2 km 约 57%。
凝结出的云水并不全部落地为雨——相当部分被输往下游或在云下再蒸发，
**降水效率**实测约 10–50%（Houze 2012），与风速、云微物理过程和地形宽度
有关（空气越过山脉的滞留时间短则效率低；线性理论的完整处理见 Smith 1979，
降水对地形强迫的敏感性标度见 Roe et al. 2002）。

**抬升凝结高度（LCL）**。未饱和空气要先抬升到 LCL 才开始凝结，LCL 之下
凝结量为零。工程近似 $z_{LCL} \approx 125\,(T - T_d)$ 米（$T$、$T_d$ 分别为
干球与露点温度，°C；Lawrence 2005）；月均相对湿度 ~75% 对应约 800 m。

**引擎实现**（CLIM-02 机制迁移后）：地形凝结在水汽预算求解器内完成——每条
上坡有向边的入流系数按 $(1-\varphi)$ 衰减，$\varphi =
1-\exp(-\max(\Delta z - z_{LCL},0)/H_{cc})$；$\Delta z$ 取海平面基准的地形差
（$\max(\text{elev},0)$——气柱在海面上贴海面行走，洋底深度不构成抬升），
凝结份额在迎风格雨出为 $P_{oro}$，背风雨影由通量亏缺自然涌现。全程质量守恒：
衰减掉的就是雨出的，雨出的全部来自通量。早期的「迎风加法雨 + 背风乘法雨影」
两处后处理（分别凭空造水与静默删水）已退役。

**海岸辐合**（引擎 `_coastal_rainout_factor`）：向岸风携带海洋水汽，海岸格
辐合抬升使局地雨出效率升高、离岸（陆地源）风使之降低。调制量纲来自水汽
通量 $f = 1 \pm \varepsilon\,\rho_{air}|U|\,q_{sat}(T)\,s_{yr}/P_{bg}$
（$\rho_{air}$ = 空气密度 1.2 kg/m³，$U$ = 纬向风，$q_{sat}$ = 饱和比湿，
$s_{yr}$ = 参考年秒数，$P_{bg}$ = 1000 mm/yr 参考背景，$\varepsilon$ = 海岸
降水效率系数——观测拟合类常数，迎风 1.3×10⁻⁴ / 背风 0.8×10⁻⁴），作为
$k_{rain}$ 的乘法调制进入预算（守恒），不再直接乘在最终降水上。

---

## SST 对流门（WTG——冷距平洋面的雨出效率，2026-09-16）

弱温度梯度（WTG）近似下热带自由对流层温度水平均匀（Sobel et al. 2001），海洋深对流的
不稳定度由**局地 SST 相对纬向带的距平**决定：暖距平水越过对流阈值族（26-28 °C，
Johnson & Xie 2010）深对流；冷距平水（沿岸/赤道上升流、东边界流、冷舌）自下方被稳定
（信风逆温、海岸雾沙漠——纳米布/阿塔卡马型，Garreaud et al. 2002；冷舌-ITCZ 耦合，
Xie & Philander 1994）——雨出效率坍缩，水汽水平输出到暖池/ITCZ 再雨出（质量守恒的
重分配，非销毁）。GCM 著名的「冷舌过暖 → 赤道东太平洋过湿」（double-ITCZ bias）
与此同构。

引擎实现：`climate_physics.sst_convection_gate`——k_rain 乘法调制，两分支分段线性
ramp（热带/外热带结点 = GPCP 海洋格 e_rel/e_rel(0) 标定，热带敏感得多 = WTG 预期）；
ΔSST 用符号化 5° 纬度带海洋格 cos 加权均值（半球不合并，防半球间对称差伪距平）；
正距平零抑制（暖池/西边界流走廊的结构安全）；下限 f_min = 0.2（层积云 drizzle 残余）。
标定细节与触发覆盖现状 → `docs/design/proposals/climate-layer-improvement.md` §5-α。

## 对流临界雨出门（降水是柱水汽的临界现象，2026-09-17）

观测告诉我们，大气把柱水汽变成降水的效率不是一个常数，而是随着柱水汽接近某个
临界值而急剧抬升。把热带洋面上的格点按柱水汽分箱统计条件平均降水率，会看到一条
明确的幂律抬升曲线：〈P〉 = a·(w − w_c)^β（β ≈ 0.23），低于临界值 w_c 时降水几乎
为零，95% 的降水发生在 0.8·w_c 以上（Peters & Neelin 2006；Neelin, Peters & Hales
2009，热带三大洋的一致结果）。临界值随对流层平均温度线性上升（约 2.2 mm/K），
但比柱饱和值的增速（约 6%/K）慢得多——所以用「柱水汽/柱饱和值」这个无量纲比值
来表达临界性是合理的近似。陆地上的临界柱湿度比洋面低（Schiro et al. 2016，
Amazon vs 西太平洋探空对比；Ahmed & Neelin 用浮力机制解释）。

这套物理有两个常被忽视的推论，正好对应本引擎的两个病灶。其一，**沙漠为什么干**：
深撒哈拉的柱水汽其实不算小（约 10 mm 量级），干的原因是它远低于当地温度对应的
临界值，对流根本组织不起来，水汽滞留时间约 150 天；而对流区（刚果、西太平洋暖池）
的柱水汽在临界值附近，水汽约一周就雨出一次。两边的雨出效率差 15 到 20 倍——
用一句统一的水汽收支语言说，P = W/τ 里的 τ 不是常数。引擎此前把 τ 设成全局均匀
的 9 天（全球平均的水汽滞留时间），于是沙漠的柱水汽每九天被平白雨出一遍，这是
撒哈拉降水偏湿十倍的直接机制。其二，**过境水汽为什么到不了季风陆地**：水汽在
孟加拉湾这类过境洋面上输送时，按 e^(−t/τ) 边走边漏（输送时间约 8 天 ≈ τ），到岸
之前就漏掉一多半——观测的湾内柱水汽接近赤道印度洋的值，模型的却掉到六成以下，
恒河平原因此被饿死（模型 W 约 9 mm，观测约 40 mm）。

还有一层自组织的性质值得单独说明（Neelin–Peters–Hales 论文的核心洞察之一）：
被对流约束的水汽分布会自己迁移到临界值附近——一个柱子低于临界，降水几乎停止，
水汽在水汽收支里继续累积（或被平流输送过去），直到越过临界才重新雨出。这给
引擎里的门提供了一个「自释放」回路：把过境洋面的雨出压低后，湾内柱水汽会回升，
更多水汽得以输送到恒河平原，陆地柱水汽升过临界值后门打开、雨在那里落下。压制
不是销毁，是质量守恒的重定向——沙漠不下的雨，会落到被强迫到临界以上的辐合区。

引擎实现：`climate_physics.convective_pickup_gate`——k_rain 乘法调制，门变量是
x = W/W_sat(T)（W_sat 用冷阱同一个 `column_water_saturation`，冷区 x≈1 自动豁免，
暖池 x=1 结构性不动）；分段线性压制曲线，下限 f_min = 9d/150d（深沙漠观测滞留时间
与引擎基底之比）。门在水分收支里按 iterate-once 应用：每月（和年）先用基底
k_rain 解一遍得到 W₀，门由 W₀ 定出，然后带着门重解——每次求解仍是线性的。结点
标定与验收现状 → `docs/design/proposals/climate-layer-improvement.md` §5-β。

## 参考来源

- Smith, R.B. (1979). "The influence of mountains on the atmosphere."
  *Advances in Geophysics* 21, 87–230.（地形降水线性理论）
- Houze, R.A. (2012). "Orographic effects on precipitating clouds."
  *Reviews of Geophysics* 50, RG1001.（降水效率 10–50% 及云物理机制综述）
- Roe, G.H., Montgomery, D.R., & Hallet, B. (2002). "Precipitation sensitivity
  to topographic forcing: Theory and observations." *JGR* 107(D21), 4585.
- Lawrence, M.G. (2005). "The relationship between relative humidity and the
  dewpoint temperature in moist air: A simple conversion and applications."
  *BAMS* 86, 225–233.（z_LCL ≈ 125(T−T_d) 近似）
- Peters, O., & Neelin, J.D. (2006). "Critical phenomena in atmospheric
  precipitation." *Nature Physics 2*, 393–396.
- Neelin, J.D., Peters, O., & Hales, K. (2009). "The transition to strong
  convection." *JAS 66*, 2367–2384, doi:10.1175/2009JAS2962.1.
- Holloway, C.E., & Neelin, J.D. (2009). "Moisture vertical structure, column
  water vapor, and tropical deep convection." *JAS 66*, 1665–1683.
- Schiro, K.A., Neelin, J.D., Adams, D.K., & Lintner, B.R. (2016). "Deep
  convection and column water vapor over tropical land versus tropical ocean."
  *JAS 73*, doi:10.1175/JAS-D-16-0119.1.
- Ahmed, F., & Neelin, J.D. (2018). "Reverse engineering the tropical
  precipitation–buoyancy relationship." *JAS 75*, doi:10.1175/JAS-D-17-0333.1.
- Sobel, A.H., Nilsson, J., & Polvani, L. (2001). "The weak temperature gradient
  approximation and balanced tropical moisture waves." *JAS 58*, 3650–3665.
- Johnson, N.C., & Xie, S.-P. (2010). "Changes in the sea surface temperature
  threshold for tropical convection." *Nat. Geosci.* 3, 842–845.
- Garreaud, R.D., Rutllant, J., & Fuenzalida, P. (2002). 副热带西海岸海岸低
  （冷洋面上的低层结构与沿海干旱）— *J. Climate 15*, 75 ff.
- Xie, S.-P., & Philander, S.G.H. (1994). "A coupled ocean-atmosphere model of
  the tropical Pacific: the cold tongue–ITCZ interaction." *J. Climate* 7.

- 陈仁升等. *固液态降水分离方法探讨* — [ResearchGate PDF](https://www.researchgate.net/profile/Chen_Rensheng/publication/283600062_A_discuss_of_the_separating_solid_and_liquid_precipitations/links/568e601208aef987e567b150.pdf)
- 中国天山山区降水形态分离及降雪影响因素分析 — [知网](https://d.wanfangdata.com.cn/thesis/Y3443596)
- 我国中东部平原临界气温条件下降水相态判别 — [气象期刊](http://qxqk.nmc.cn/qx/ch/reader/view_abstract.aspx?file_no=20190801&st=alljournals)
- 陈亚宁团队：全球变暖加速亚洲高山区降雪率变化（阈值 0.13/0.87）— [中亚生态与环境研究中心](http://www.rceeca.com/kyjz/info/2025/93945.html)
- Clausius–Clapeyron 实现（Breeze.jl）— [GitHub](https://github.com/NumericalEarth/Breeze.jl/blob/3eeb010c90b0861476ef77e62ff478a36baec2b5/src/Thermodynamics/clausius_clapeyron.jl)
- 温度依赖降水（精确非线性山地波）— [Springer J. Math. Fluid Mech.](https://link.springer.com/article/10.1007/s00021-025-00946-y)
- 气溶胶对温度–降水标度的间接效应（CC 标度 6.1–8.6%/°C）— [ACP](https://acp.copernicus.org/articles/20/6207/2020/acp-20-6207-2020.html)

## 相关文档

- `energy_balance.md` §8 — 质量守恒水汽收支的完整方程与各项含义、土壤水桶、
  冷阱路由、收敛哨兵；温度（降水相态与 q_sat 的输入）
- `atmospheric_circulation.md` — 风场（水汽输送 + 海岸辐合的驱动力）
- `koppen_classification.md` — 降水阈值（Köppen 分类输入）
