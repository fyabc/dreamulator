# 云场的统计律：单点光学厚度分布与空间功率谱

本文记录真实云场两条可观测的统计规律（竞品工程实现调研见同目录 `cloud_generation_competitors.md`）——单点（逐像素）光学厚度的概率分布，以及云场作为空间场的功率谱——并说明它们如何约束程序化云纹理的生成。写作动机是太空俯瞰镜头的云层合成（L2 程序化云纹理，`src/dreamulator/media/cloud_render.py`）：与 NASA Blue Marble 全圆盘参照图做同口径定量对比时发现，参照图的云透明度直方图在对数纵轴—线性横轴上呈直线衰减，而我们的初版原型在该指标上显著偏离；这两条统计律正是偏离的诊断依据和修复目标。

## 一、单点分布：光学厚度近似指数（gamma 族形状参数 ≈ 1）

卫星对云光学厚度 τ 的逐像素直方图有一个稳健的形态特征：从最薄档起单调衰减，薄云在面积上占绝对主导。Marchand 等（2010，JGR）对 MISR、ISCCP、MODIS 三套数据的云顶高—光学厚度联合直方图做了系统评审，指出三颗卫星都经常漏检 τ 小于约 0.3 的云，且各直方图的低光学厚度端占比最大；换言之观测到的 τ 分布是被检测下限截断的、向厚云方向快速衰减的分布（全文核验，见参考文献 1）。业务与模拟侧的惯例与之相符：MODIS 三级产品对光学厚度统计同时存正态与对数正态参数；CFMIP 观测模拟器包（COSP）的 CloudSat 模拟器对大尺度层状与对流云液水假定对数正态分布、对雨假定指数分布（参考文献 2）；微波辐射计与雷达反演的云液水路径（LWP）统计在边界层碎云与信风积云 regime 常用形状参数 1–2 的 gamma 分布拟合，形状参数 1 即指数分布（此为领域惯例的转述，属二手引用）。

为什么指数族会出现，有几条互相独立的机制线索，均作启发式理解而非定理：其一，给定均值下最大熵分布即指数分布，云水含量受水汽供给总量约束时自然趋近它；其二，随机凝结增长（乘性）与降水/夹卷消耗（线性汇）的平衡态是 gamma 分布；其三，湍流乘性级串在部分 regime 给出对数正态。三条机制对应不同 regime，观测上是混合形态，但「对数纵轴—线性横轴近似直线」这一指纹在碎云与层积云区最干净。

对生成方法的直接含义：云的不透明度（光学厚度的单调代理量）在云内像素上的分布应当近似指数——大量半透明像素、少数近不透明云核——而不是均匀分布或双峰分布。实现上用「秩 → 均匀分布 → 截断指数分布逆 CDF」的映射可以逐构造地得到该形态：先把像素在所在区域密度场中的分位秩映射为均匀变量 u，再取 alpha = alpha_max · ln(1 − u(1−ε))/ln(ε)。

## 二、空间谱：尺度不变的幂律，一维斜率约 −5/3

Landsat 观测的云辐射/光学厚度场在约 1 km 到上百 km 的尺度范围内是尺度不变的：一维功率谱近似 k 的 −5/3 次幂（Kolmogorov 型标度），这一结果出自 Cahalan 与 Joseph（1989，Mon. Wea. Rev.）对 Landsat MSS（80 m）与 TM（30 m）云场的分形统计分析；Davis 等（1997，J. Atmos. Sci.）在讨论 Landsat 尺度断裂时重绘了该能谱并以 −5/3 参考线对照，并指出约 1 km 以下斜率变陡的部分可归因于三维辐射传输的平滑效应而非云场本身（参考文献 3、4；原始论文全文付费墙内，此处为转引核验层级）。更一般的框架是 Lovejoy 与 Schertzer 的标度/多重分形云理论：幂律谱之上叠加间歇性修正，云边界与云量的空间组织在很宽的尺度范围内无特征尺度。

各向同性二维场的一维与二维谱斜率相差 1，故二维谱斜率 β₂ᴅ ≈ 8/3。这条律对生成的含义是定量的：分形噪声（fBm）每个倍频程振幅按.persistence p 衰减时，其二维功率谱斜率为 β₂ᴅ = 2 − 2·log₂(p)。要匹配 β₂ᴅ = 8/3 需要 p = 2^(−1/3) ≈ 0.79；而图形学常用的 p = 0.5 对应 β₂ᴅ = 4，谱过陡、中频能量不足——这正是我们的原型在 20–200 周/盘面频段比 Blue Marble 低 2–3 倍功率的原因。实际取值不必照抄 0.79：观测的 −5/3 是辐射场（含 τ→反射率的非线性饱和与间歇性）的斜率，且我们的密度场还要经过秩—指数映射，工程上取 0.7 左右的折中即可显著补上中频缺口。

## 三、间歇性：乘性级串与子单元离散结构

功率谱与单点分布只约束云场的二阶与一阶统计，还缺一条形态约束：真实中尺度云系不是光滑团块，而是离散子单元的聚合——对流簇是清晰亮元加元间暗缝的集合，层积云_sheet_ 带开/闭细胞与条纹子结构（NASA 全圆盘参照图的局部裁剪可直接看到）。这是湍流乘性级串的间歇性修正：Lovejoy 与 Schertzer 的标度/多重分形云理论在幂律谱之上叠加一个乘性级串场，使云掩膜在每个尺度上破裂成子元素。生成侧的落点是把一个 4 倍频程（600→40 km）乘性场作用在密度场的秩/阈值映射**之前**——秩映射保证单点指数分布不被破坏，级串只改空间组织。对照卫星裁剪图调参的教训：级串对比度过强会把中尺度云系完全打散成碎条（proto41），且级串场若沿风场全位移采样会把子单元拉成各向异性丝缕（真实积云细胞近各向同性），取半位移收敛（proto42）。

## 四、两条律的联合指纹：梯度统计

单点指数分布与空间幂律谱共同决定梯度幅值的分布形态：透明度场处处有结构（谱无特征尺度）且大部分像素处于低透明度区（指数分布），故梯度幅值直方图在对数纵轴上也呈近似直线衰减、且中位梯度不为零。定量对比脚本 `<render-workdir>/temp/cloud_compare.py` 用这三组指标（透明度直方图的对数线性度、梯度分位数、径向功率谱）把生成图与参照图放在同一口径下比较，是云纹理观感迭代的验收工具。

## 五、对 dreamulator 云纹理生成的参数映射

| 统计律 | 生成侧实现 | 参数位置 |
|---|---|---|
| 云内透明度指数分布 | 秩 → 均匀 → 截断指数逆 CDF；区域峰值 alpha_max = 1−exp(−k·cover) | `cloud_render.py` 的 `LOWCLOUD_OPACITY_K` 与 billow 段的 `alpha_shape` |
| 空间谱 β₂ᴅ ≈ 8/3 | 可见密度层（billow/detail/deck/cirrus/haze）的 fBm persistence 取 `DENSITY_GAIN`（0.7，由 p = 2^(−(β₂ᴅ−2)/2) 折中） | `cloud_render.py` 的 `DENSITY_GAIN` |
| 调制场（风扭曲/天气系统/尺度交叉淡化）保持光滑 | 这些场不是可见纹理，仍用 persistence 0.5 | `cloud_render.py` 的 `FBM_GAIN` |
| 薄云主导、晴空微纹理 | 阈值下薄纱 + 全域弥漫 haze 层 | `cloud_render.py` 的 veil 与 `HAZE_*` 常量 |
| 间歇性乘性级串（子单元离散结构） | 密度场秩映射前的 4 倍频程乘性场 | `cloud_render.py` 的 `CASCADE_*` 常量 |

## 参考文献

0. Lovejoy, S., and D. Schertzer (1985/1995). 标度/多重分形云理论：幂律谱之上的间歇性乘性级串。转引层级：经 `cloud_generation_competitors.md` 与本文 §三 的工程对照使用（原始文献未全文核验）。

1. Marchand, R., T. Ackerman, M. Smyth, and W. B. Rossow (2010). A review of cloud top height and optical depth histograms from MISR, ISCCP, and MODIS. *J. Geophys. Res.*, 115, D16206. https://atmos.uw.edu/~roj/publications/Marchand_et_al_2010_JGR_A_review_of_CTH_OD_histograms.pdf （全文开放，已核验）
2. CFMIP Observation Simulator Package 云雷达/激光雷达模拟器的液水分布假定（层状与对流云液水对数正态、雨指数）。EGUsphere 预印本 2023-2161（CFODD 分析）。 https://egusphere.copernicus.org/preprints/2023/egusphere-2023-2161/egusphere-2023-2161-ATC1.pdf
3. Cahalan, R. F., and J. H. Joseph (1989). Fractal statistics of cloud fields. *Mon. Wea. Rev.*, 117, 261–272. https://journals.ametsoc.org/view/journals/mwre/117/2/1520-0493_1989_117_0261_fsocf_2_0_co_2.pdf （付费墙；谱斜率经参考文献 4 转引核验）
4. Davis, A., A. Marshak, R. Gerber, and W. J. Wiscombe (1997). The Landsat scale break in stratocumulus as a three-dimensional radiative transfer effect: Implications for cloud remote sensing. *J. Atmos. Sci.*, 54, 241–260. （−5/3 参考线重绘与 1 km 尺度断裂归因）
5. MODIS 云光学产品算法与三级统计约定（光学厚度直方图、对数正态参数）。 https://modis.gsfc.nasa.gov/data/atbd/atbd_mod05.pdf
