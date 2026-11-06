# 湿静力能辐合闭合：阶段 0 终止说明

> 状态：已否证终止，未进入实现。立项日期：2026-11-02；终止日期：2026-11-02。
>
> 再分析规定输入下，柱净能量收入与热带洋面降水减蒸发的型相关为 −0.04，
> 本提案的局地闭合未通过阶段 0。现行湿槽回路仍采用三轮停止点；
> 海温梯度驱动的边界层模型仅保留为补充候选。原始论证与逐轮实验记录由 git 和另存档案保留。

## 1 原主张与成立条件

本提案由[气候迭代的湿槽结论](climate-engine-round.md#33-湿槽迭代)分出。
现行湿槽回路的三轮迭代是按地球观测拟合的停止点，增加轮数不能使它收敛。
原方案希望以柱积分湿静力能收支直接诊断热带辐合，消除对停止轮数的依赖。

湿静力能包含显热、重力势能与水汽潜热。按两层平均辐散环流近似，拟议闭合为

    D = F_net / M ,
    L(P − E) = (M_q / M) F_net .

其中 `D` 为低层辐合，`F_net` 为大气柱净能量收入，`L` 为汽化潜热，`P` 与 `E` 分别为
降水率和蒸发率；`M` 是总湿稳定度，`M_q` 表示同一环流的水汽输送贡献。
方案依赖热带弱温度梯度近似，并要求总湿稳定度的符号与量级能够独立推出。
在正总湿稳定度等假设下，原方案预期反馈增益小于一；这些条件需要实测，不能直接作为收敛保证。

这一近似还要求识别平均环流承担的能量输送。涡旋输送与海洋输送不能直接全部归入
局地辐合，季节能量平衡模型的经向扩散项也不能自动提供这种分解。

## 2 否证依据与证据边界

### 2.1 引擎输入的限制

现行辐射使用全球反照率与线性化出射长波，给出的热带柱净能量收入近乎均匀且几乎处处为正，
不能表达降水减蒸发的正负空间结构。这一检验只说明现行输入不足，尚不能单独裁决闭合是否成立，
因此阶段 0 另用再分析规定输入复测。辐射空间结构的候选设计由[柱辐射场提案](column-radiation-field.md)维护。

### 2.2 再分析规定输入的复测

复测使用 NOAA PSL 的 NCEP/NCAR 再分析 1 号辐射与地表通量，取 1991–2020 年月气候态
构成大气柱净能量收入；降水使用 GPCP，蒸发由同套再分析的地表潜热通量换算。
热带洋面定义为 30°S–30°N，柱净能量收入与降水减蒸发的型相关为 **−0.04**。

柱净能量收入受信风区的潜热通量主导，而信风区主要蒸发并向辐合区输出水汽。
柱辐射加热与对流的空间结构相符，但与潜热分量相加后，净能量收入不能预测局地降水型态。
复现该型态需要总湿稳定度剧烈变化并变号，超出本提案能够独立推导的稳定闭合。
热带水汽供给的非局地性仍需由风场与水汽平流表达。

NCEP 辐射属于再分析预报场，云偏差使其约束弱于 CERES，且存在全球能量不平衡；
复测因此以不受常量偏移影响的型相关为主判据。这项证据支持终止本提案的局地闭合，
柱积分湿静力能守恒与包含完整输送的环流模型仍须按各自假设检验。

## 3 当前处理与补充候选

现行湿槽三轮停止点保持不变，回路定义与局限由[气候管线第 5.7 节](../pipelines/climate-pipeline.md#57-gw6-湿槽回路w-供给路线默认开)维护。
本提案没有实现闭合开关，也没有退役湿槽；单轮求解与性能收益均未获得验证。

Lindzen–Nigam 边界层模型以海温梯度驱动气压梯度和辐合，属于外加强迫。
规定海温的离线检验表明，它主要补充海温锋面附近的中小尺度结构，不能完整保住现行雨带的
大尺度纬度定位，因此只适合作补充。检验使用同一再分析气候态、既有洋面阻力率与多个平滑尺度，
并剔除赤道两侧 3°；这种离线结果不能视为引擎自身海温与风场已通过验收。
接入前须先处理[地面风提案](surface-wind-from-pressure.md)的上游缺口，并检验是否重复计入热带辐合。

## 4 不采用的方向

- 用局地柱净能量收入直接替换湿槽：阶段 0 的再分析规定输入检验未通过。
- 继续调湿槽轮数、欠松弛或限幅来宣称收敛：这些量规定停止点，不能给回路提供定点。
- 给总湿稳定度加裸下限或给求解器风再加上限：会掩盖闭合与输送缺口。
- 直接接入 `qtcm` 或 QTCM1：维护状态与时间积分架构不适配当前诊断管线，分发许可也未明确。
- 用 Lindzen–Nigam 模型独自替换现行方案：离线检验只能支持中小尺度补充。

## 参考资料

- Neelin, J. D., Held, I. M. (1987). Modeling tropical convergence based on the moist static energy
  budget. *Monthly Weather Review* 115(1), 3–12.
- Sobel, A. H., Bretherton, C. S. (2000). Modeling tropical precipitation in a single column.
  *Journal of Climate* 13, 4378–4392.
- Raymond, D. J., Sessions, S. L., Sobel, A. H., Fuchs, Ž. (2009). The mechanics of gross moist
  stability. *Journal of Advances in Modeling Earth Systems* 1, 9.
- Back, L. E., Bretherton, C. S. (2006). Geographic variability in the export of moist static energy
  and vertical motion profiles in the tropical Pacific. *Geophysical Research Letters* 33, L17810.
- Back, L. E., Bretherton, C. S. (2009). On the relationship between SST gradients, boundary layer
  winds, and convergence over the tropical oceans. *Journal of Climate* 22, 4182–4196.
- Lindzen, R. S., Nigam, S. (1987). On the role of sea surface temperature gradients in forcing
  low-level winds and convergence in the tropics. *Journal of the Atmospheric Sciences* 44, 2418–2436.
