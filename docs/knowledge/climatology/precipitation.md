# 降水：水汽输送、相态与地形效应

> 为 dreamulator 气候引擎的降水模块提供参考。降水由质量守恒水汽收支
> （`climate_simulator.py:_solve_moisture_budget`，公式与各项含义见
> `energy_balance.md` §8）+ 预算内的地形抬升凝结（本文 §三）+ 相态（雨/雪）
> 转换构成。本文档收录降水相态、低温降水与地形降水的科学底座。

---

## 原生降水的面积预算与空间取样

降水深度乘以面积给出水量。同一个原生父格内的细化场应满足
`Σ A_i P_i = A_parent P_parent`，其中面积包含陆地和海洋，月值采用相同的参考时间基准。
高斯网格的父格面积由高斯求积权重乘以经度宽度与半径平方得到；累计权重确定纬度边界，
从而为完整球面建立与原生求积一致的正面积分区。

长期插值底场可保留格内相对形状，再按完整面积积分归一到每个分量的原生月配额。
这是数值分配约束，空间质量由过程模型和独立观测另行检验。
源码 `gcm/native_partition.py` 保存完整分区与双精度月分量，地理点查询返回所在积分单元的深度。
CVT 格心与投影栅格中心构成该场的点取样视图；目标单元的面积平均需显式计算交叠面积。
面积预算、点取样、目标单元覆盖积分分别使用对应的测度。

经纬度矩形目标单元可在 $(\sin\varphi,\lambda)$ 坐标中计算解析交叠，球面面积为
$R^2\Delta\sin\varphi\,\Delta\lambda$。经度周期连接，两极具有有限正面积。
同一稀疏面积算子可以积分全部月份与降水分量；目标面积均值由交叠水量除以该目标面积得到。
区域覆盖核验其足迹中的源水量，全球覆盖进一步核验每个原生单元的完整面积。
投影矩形的球面边界可以在同一等面积坐标中细分为多边形，再与原生经纬度单元裁切。
面积用投影雅可比独立求积核验，相邻细分的交叠面积变化控制雨量分配的数值误差。
极冠与经度周期按球面拓扑处理，所得平均值及覆盖水量对应实际目标足迹。
跨画布所有权与 CVT 多边形分别提供对应的分区几何。

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

## 大陆西侧为什么干（副热带）

地球上副热带的大沙漠多半贴着大陆西岸或占据大陆西部，例如阿塔卡马、纳米布、撒哈拉西部和
澳大利亚西部，而同纬度的大陆东岸往往湿润。三种机制叠加造成这种东湿西干：

1. **西部处在信风的下游。** 副热带低空盛行东风，海洋水汽从大陆东岸进入，沿途不断降落，
   到大陆西部时空气已经穿过整片陆地。西岸吹的是离岸风，近旁的海洋反而送不进水汽。
2. **西部受副热带高压东翼的下沉控制。** 副热带反气旋的东翼伴随下沉运动和向赤道的低空气流，
   把高纬的干冷空气带向低纬。Rodwell 和 Hoskins（1996）指出，大陆东部夏季风的凝结加热会
   激发向西传播的 Rossby 波，在加热区以西造成下沉，这就是「季风与沙漠」的联系；他们 2001 年
   的工作进一步说明，副热带反气旋的东翼下沉与夏季风加热直接相关。
3. **沿岸寒流和上升流稳定了边界层。** 东翼向赤道的沿岸风驱动离岸的 Ekman 输送，深层冷水
   上翻，海面变冷，低层大气被稳定，形成信风逆温和大片层积云（Klein & Hartmann 1993），
   只下毛毛雨或形成海雾，沿岸因此成为雾漠（Garreaud et al. 2002）。

三者的相对重要性因地而异。nacrea 的 T42 GCM 对照提供了一个干净的检验：平板海洋没有洋流和
上升流，第三种机制不存在，但 12–38° 副热带陆地仍然明显东湿西干。西部三分之一年降水约
794 mm、干旱类（Köppen B）占 45%，东部三分之一约 1298 mm、干旱类占 16%；低层相对湿度从
东部的 80% 降到西部的 68%。可见只靠前两种大气机制，就足以造成这种不对称。

引擎实现：前两种机制由质量守恒水汽收支的迎风平流自然给出（`climate_simulator.py:
_solve_moisture_budget()`，水汽沿风场从东岸进入、向西耗尽）；第三种由涌升冷舌
（`map/ocean_circulation.py:apply_upwelling_sst_correction()`）和 SST 对流门
（`climate_physics.sst_convection_gate`）表示。引擎没有动力副热带高压，第二种机制只能
间接体现（见 `docs/design/pipelines/climate-pipeline.md` §5.1）。

## 饱和条件稳定度与线性地形雨的适用范围

Smith 与 Barstad 的线性地形雨模型以稳态背景气流和相应的分层状态描述抬升、水汽转化及降水输送。
原生大尺度凝结与对流具有各自的过程来源，分量相加的水量闭合和线性响应的状态适用性分别验收。
在保留父格水量的降尺度中，未解析过程及无效状态仍保留其父场份额。

实际热力状态的层厚由静力平衡求得：

$$dz=-\frac{R_dT_v}{g}\,d\ln p,\qquad T_v=T\left[1+\left(\frac{R_v}{R_d}-1\right)q\right].$$

这里 $q$ 是比湿，虚温表达采用无凝结物负载的气体密度。环境递减率 $\gamma=-dT/dz$ 与液水饱和递减率
$\Gamma_m$ 的比较给出条件诊断 $g(\Gamma_m-\gamma)/T$。液水气块的浮力诊断进一步计算
饱和虚温随温度和压力共同变化的导数：

$$\frac{dT_{v,p}}{dz}=-\Gamma_m\frac{\partial T_{v,s}}{\partial T}
+\frac{dp}{dz}\frac{\partial T_{v,s}}{\partial p},\qquad
N_p^2=\frac{g}{T_{v,e}}\left(\frac{dT_{v,e}}{dz}-\frac{dT_{v,p}}{dz}\right).$$

下标 $s$ 表示饱和状态，$p$ 表示气块，$e$ 表示环境。此近似令凝结物即时落出，保留真实负值，
可用有限气块位移独立核对其导数。压力导数、环境虚温和相变约定共同决定实际稳定度。
完整湿浮力频率还需要总水混合比及其垂直梯度、云凝结物、液水热容和相变约定。
未饱和虚位温分层、液水饱和条件分层和完整湿分层使用各自的状态定义。

山地云中可以发生嵌入对流，改变降水效率、位置及强度。单一上游稳定度或低层 RH 对实际云层及对流的预测范围有限，
近饱和阈值可用于描述输入覆盖，过程适用域需要云层、热力和流动条件共同约束。
RH 的单位与垂直坐标也须按实际数据生产公式核对，写出量化造成的误差按输入编码推导。

ICAR 以线性山地波提供扰动风场，并推进时间输送及微物理。新西兰公里级研究表明其高山降水有改善，
同时显示模型顶高度和稳定气流状态会影响误差。行星接入须统一各物理模块的重力、热力及自转参数。
比湿 $q$ 转干空气水汽混合比使用 $r=q/(1-q)$；诊断云属性与微物理凝结物按过程来源分别核对。

## 地形暴露与守恒降水分配

地形暴露指标用上游高差概括抬升和遮蔽的空间关系。Böhner 与 Antonic（2009）的
SAGA wind effect 方法沿风向搜索地形，按距离加权并以对数和分数次幂压缩响应。
其角度变换使用米制高差和距离平方根，属于具有固定单位约定的地球经验参数化。
300 km 搜索支持、1.5 倍步长增长和响应阻尼沿用参考实现，标定域与观测误差另行声明。

细地形与大气模式地形计算相同指标，取两者比值可以表达未解析地形的增量，
同时保留原生降水的大尺度分配。高频降水加权的风向积分保留湿天气的不同流向，
月平均风向提供相应的简化对照。该几何指标描述地形暴露关系，凝结、云水转化和输送
由原生大气模式及其经验闭合承担。

CHELSA 的降尺度框架按父格内的地形权重分配降水并恢复父格配额。
对细格权重 $w_i>0$、面积 $A_i$ 和父格月平均降水 $P_p$，分配为
$P_i=P_p w_i / (\sum_{i\in p} A_i w_i/\sum_{i\in p}A_i)$。
完整陆海覆盖参加分母；大尺度与对流分量分别归一，空间响应只作用于有依据的过程分量。
守恒检查与地球迎背风空间质量分别验收，经验权重的应用范围由实际观测比较确定。

## 参考来源

- Böhner, J., & Antonic, O. (2009). Land-Surface Parameters Specific to Topo-Climatology.
  *Developments in Soil Science* 33, 195–226. DOI:10.1016/S0166-2481(08)00008-1。
- SAGA GIS. Wind Effect 的算法实现：
  <https://github.com/saga-gis/saga-gis/blob/master/saga-gis/src/tools/terrain_analysis/ta_morphometry/wind_effect.cpp>。
- Karger, D. N. 等 (2017). Climatologies at high resolution for the earth’s land surface areas.
  *Scientific Data* 4, 170122. DOI:10.1038/sdata.2017.122。

- Gutmann, E. 等 (2016). "The Intermediate Complexity Atmospheric Research Model (ICAR)."
  *Journal of Hydrometeorology*. DOI: [10.1175/JHM-D-15-0155.1](https://doi.org/10.1175/JHM-D-15-0155.1)。
- Horak, J. 等 (2019). "Assessing the added value of the intermediate complexity atmospheric research (ICAR) model for precipitation in complex topography."
  *Hydrology and Earth System Sciences* 23, 2715–2734。
  DOI: [10.5194/hess-23-2715-2019](https://hess.copernicus.org/articles/23/2715/2019/)。

- Smith, R.B. (1979). "The influence of mountains on the atmosphere."
  *Advances in Geophysics* 21, 87–230.（地形降水线性理论）
- Smith, R.B., & Barstad, I. (2004). "A Linear Theory of Orographic Precipitation."
  *Journal of the Atmospheric Sciences* 61, 1377–1391。作者会议全文：<https://ams.confex.com/ams/pdfpapers/62756.pdf>。
- Fuhrer, O., & Schär, C. (2005). "Embedded Cellular Convection in Moist Flow past Topography."
  *Journal of the Atmospheric Sciences* 62, 2810–2828。全文：<https://iacweb.ethz.ch/doc/publications/2005_Fuhrer_Cellular.pdf>。
  方程 4 与周边讨论给出完整湿稳定度的状态输入及条件不稳定云层的解释范围。
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
- Rodwell, M.J., & Hoskins, B.J. (1996). "Monsoons and the dynamics of deserts."
  *QJRMS* 122, 1385–1404, doi:10.1002/qj.49712253408.
- Rodwell, M.J., & Hoskins, B.J. (2001). "Subtropical anticyclones and summer
  monsoons." *J. Climate* 14, 3192–3211.
- Klein, S.A., & Hartmann, D.L. (1993). "The seasonal cycle of low stratiform
  clouds." *J. Climate* 6, 1587–1606.

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
