# 光合吸收谱与恒星光谱匹配

> 用途：生态层 NPP 光谱修正（roadmap 技术债 13 的配套知识文档）+ 异星植被颜色推演
> （世界 input 编写与内容线视觉设计的科学依据）。
> 遵循知识库写作准则：每条结论标注来源；推断性内容显式标注「推定」。

## 1 恒星光谱能量分布（SED）与峰值波长

主序星辐射近似黑体，峰值波长由**维恩位移定律**给出：

$$\lambda_{max} = \frac{b}{T_{\text{eff}}}, \qquad b \approx 2.898\times10^{6}\ \text{nm·K}$$

| 光谱型 | T_eff (K) | λ_max (nm) | 峰值所在波段 |
|--------|-----------|------------|--------------|
| F5V | ~6500 | ~446 | 蓝 |
| G2V（太阳） | 5772 | ~502 | 绿（视觉峰值） |
| K2V | ~4950 | ~585 | 黄橙 |
| K8V | ~4050 | ~715 | 深红 / 近红外边界 |
| M3V | ~3300 | ~880 | 近红外 |

温度列取 Pecaut & Mamajek (2013) 主序表典型值；K8V 各测量源散布约 3970–4200 K
（如 HD 88230 = Groombridge 1618，K7.5Ve/K8V，不同文献 3970–4215 K），λ_max 相应
在 690–730 nm 间移动。nacrea 烬星正典 T_eff≈4055 K → λ_max≈715 nm。

**黑体近似的三个注意点**：
1. 真实恒星光谱带吸收线；晚型 K/M 星分子带（TiO 等）强，偏离黑体。
2. 「能量最多的波段」依赖口径：**波长空间**峰值（上表）、频率空间峰值、光子数峰值
   互不相同（后两者向长波移动）。引用时必须标明口径。
3. λ_max 只是一阶锚点；需要精确波段能量份额时用实测 SED 模板（如 PHOENIX/ATLAS
   模型谱），不要用黑体积分代替。

**光合有效辐射（PAR，400–700 nm）份额随光谱型强烈变化**：M 矮星辐射大部分在
近红外，K8 的 PAR 份额也显著低于太阳。这是技术债 13 的根源——生态引擎当前
`par_ratio = L/d²`（总辐射通量比，标量），对 M/K 矮星世界会**高估**叶绿素型植物
NPP；反之若该世界生物演化出 NIR 吸收色素，可利用能量未必低。缺失的修正链：
恒星 T_eff → 地表光谱（含大气透过窗口）→ 色素吸收谱 → 重叠积分 = 有效 PAR。

## 2 地球光合色素吸收谱

| 色素类群 | 代表生物 | 吸收峰 (nm) | 视觉颜色（反射带） | 电子供体 / 备注 |
|---------|---------|-------------|--------------------|-----------------|
| 叶绿素 a | 全部产氧光合生物反应中心 | ~430（Soret）/ ~662 | 蓝绿（反射 500–600 绿光） | H₂O；P680⁺ 氧化电位 ~+1.2 V |
| 叶绿素 b | 绿藻 / 陆生植物天线 | ~453 / ~642 | 黄绿 | 拓宽吸收带，非反应中心 |
| 类胡萝卜素 | 辅助色素（普遍） | 400–500 | 黄 / 橙 / 红 | 光保护 + 溢出能量耗散 |
| 藻胆蛋白 | 蓝藻 / 红藻 | 500–650（藻红 ~565、藻蓝 ~620） | 蓝绿 / 红 | 水下光质互补色适应 |
| 细菌叶绿素 a/b | 紫细菌（不产氧） | 800–870 / ~1020 | 红褐 | H₂S、Fe²⁺、H₂ 等稀缺供体 |
| 细菌叶绿素 c/d/e | 绿硫细菌 | 715–750 | 暗绿褐 | H₂S；极端弱光环境 |
| 视黄醛（细菌视紫红质） | 盐杆菌古菌 | ~550–570 | 紫（反射红+蓝） | 质子泵，非叶绿素路径 |

数据来源：Kiang et al. 2007（I 篇，地球生物吸收谱综述）。

## 3 叶绿素霸权：必然性与偶然性

地球上叶绿素 a 在生物量与碳固定量中占压倒性优势（其他色素多作为辅助天线，
无法独立完成核心光化学反应）。这个格局可以拆成两层：

- **底层物理化学的必然性**：水是最丰富的电子供体，但极其稳定——裂解水需要
  强氧化电位（P680⁺ ~ +1.2 V），只有叶绿素双光系统（Z 机制，两个光子串联）
  在量子效率与热力学上稳定跨过这一门槛。视黄醛或细菌叶绿素只能做单光子驱动的
  不产氧光合，依赖 H₂S/Fe²⁺/H₂ 等稀缺供体，生态扩张潜力天然受限
  （Blankenship 2014；Olson & Blankenship 2004）。
- **赢家通吃的历史偶然性**：大氧化事件（GOE，~2.4 Ga）把氧气变成全球性毒物，
  清洗了此前占主导的厌氧光合生物，把它们驱入深海热泉、富硫湖等边缘生态位。
  若早期视黄醛生物（吸绿光、呈紫色）先一步锁死生态位，星球可以保持紫色——
  即「紫地球假说」（Purple Earth hypothesis，DasSarma 2006）。

**世界构建含义**：绿色主导不是物理必然，而是「水裂解门槛 × GOE 清洗」两个条件
叠加的结果。打破其中任一条件的异星，植被颜色可以完全不同（§5）。

### 3.1 C3/C4 效率上限（浓缩机制的光子代价）

C3 路径固定 1 分子 CO₂ 的光子需求约 8 个（18 ATP + 12 NADPH / 葡萄糖）；但
Rubisco 兼有氧化酶活性，高温/低 CO₂ 下光呼吸可在 C3 植物中损失可观的已固定碳
（教科书写法：逆境下可达 20–50%）。C4/CAM 是「用额外 ATP 换碳浓缩」的机制：
量子需求升到 ~10–12 光子/CO₂（量子产额低约 20–30%），但在高温、强光、低 CO₂
环境净光合反而更高（Taiz & Zeiger, *Plant Physiology*）。

**异星含义**：K/M 星宜居世界若 CO₂ 分压低、昼面辐照强，C4 样浓缩机制可能被
优先选择；这与色素颜色（§4）是两个独立的设计维度——前者改能量效率，后者改
反射光谱。NPP 引擎的光谱修正落地时，效率上限应作为 pigment family 的属性字段。

## 4 K/M 星行星的色素颜色预测（文献结论 + 核查记录）

- **Kiang et al. 2007（II 篇）**：色素吸收峰倾向于出现在大气透过窗口的边缘——
  光收集在窗口最蓝边、能量捕获在窗口最红边。结论按光谱型分档：F/G 星与地球
  接近（绿色主导 + 近红外「红边」）；**K 星峰值在红橙，植被颜色相对地球只有
  轻微偏移**；**M 星峰值在近红外，陆地上不产氧 NIR 光合可能占竞争优势，
  植被呈紫罗兰到黑色**。
- **Lehmer & Catling 2021**（光谱优化计算吸收峰最优位置）：对 G、K、早 M 型星，
  最优吸收峰在 675 / 711 / 746 nm（原文 "for G, K, and early M type stars, red or
  just beyond is preferred"）；最冷 M 星可移到近红外 1 μm 以外。论文未直接给出
  视觉色，但强吸收 675–746 nm 意味着可见反射带偏向短波侧（蓝绿–黄绿）。
- **核查记录（2026-09，外部 AI 讨论吸收）**：「绕 K 型星植物呈蓝绿色」**不可
  归因于 Kiang**——Kiang 的结论是 K 星只有轻微色偏，强偏移（紫→黑）是 M 星
  NIR 不产氧光合的情形。但蓝绿/黄绿/黑作为 K 星植被颜色**均在物理合理范围内**：
  子型越晚（K8 → λ_max 715 nm 已贴近叶绿素 a 红吸收峰之外），反射带越偏短波，
  或演化出宽吸收带呈黑色。表述时应写成「可能性谱系」，不写单一结论。
- **K8 锚定（nacrea 烬星）**：可见光通量偏低 + 红橙/NIR 充沛的环境下，宽吸收带
  （黑色）策略能量利用率最高——与正典设定「赤道红外雨林叶片深黑/紫黑色（广谱
  吸收色素）」自洽；冠层下的荫生层只剩蓝绿残光，红橙辅助色素（类胡萝卜素/
  花青素型）呈红/橙——与地球红藻深水适应、秋叶显色同机制。

## 5 斑斓星球设计启示（打破赢家通吃的四种机制）

若希望异星出现「多种色素分庭抗礼」而非单一颜色通吃，须在设计上限制霸权形成
条件。四种机制各有地球锚点（外部讨论方案，经核查与文献机制一致）：

1. **电子供体限制**：锁死水裂解路径（水被深锁 / 高能光子组合不足）→ 不产氧
   光合按供体地理分布形成**马赛克色斑**：H₂S 区绿硫细菌型（暗绿/褐）、Fe²⁺ 区
   紫细菌型（紫红）、H₂ 区视黄醛古菌型（橙黄）。地球锚点：火山硫泉、太古
   条带铁建造时期的富铁海。
2. **大气滤镜切割光谱**：厚气溶胶/甲烷/臭氧吸收把连续光谱切成几个分离的窄带
   透光窗口 → 不同色素占据平行的「光学生态位」。地球锚点：水体光谱窗口与
   藻类垂直分带。
3. **极端空间分层（光谱生态位分化）**：巨型多层冠层逐层过滤光质——顶层吸收
   红+NIR（黑/深蓝绿）、中层吸收黄绿（紫/洋红）、底层吸收蓝残光（鲜红/橙）。
   地球锚点：浮游植物色素组成的适应性分化（Stomp et al. 2004）。
4. **高频环境震荡 + 强制共生**：季节/食季光质剧变，单一色素无法全年适应 →
   多色素「拼图式共生体」（地衣类比），宏观呈斑驳复合色。nacrea 的食季
   （每 78 h 一次 ~2.2 h 全食，4.7 yr 交点周期）是现成的震荡源（推定：
   幅度是否足以驱动该机制待生态层推演）。

**约束**：以上机制必须与世界 input（水圈存量、大气成分、冠层结构、轨道几何）
自洽；颜色是生态层推演的输出而非独立旋钮。引擎侧承接（色素族字段、NPP 光谱
积分）属远期推演线（roadmap 技术债 13 / ecology-layer P3）。

## 6 源码引用

- `src/dreamulator/engine/ecology.py` — `par_ratio` 现状（总通量标量，未做光谱修正）
- `src/dreamulator/engine/physical_inputs.py` — 恒星参数解析（现只读总光度，
  未读 T_eff/光谱型；修正链落地时需扩展）
- `src/dreamulator/engine/stellar_physics.py` — T_eff 反演（Stefan-Boltzmann）

## 相关文档

- `../astrophysics/stellar_physics.md` — 恒星 SED 与维恩位移（天体物理侧）
- `../astrobiology/alternative-solvents.md` — 非水基生命（不产氧代谢的另一极端）
- `ecological_mathematical_models.md` — NPP 代谢标度（par_ratio 的消费方）

## 参考文献

- Kiang, N. Y., et al. (2007). Spectral Signatures of Photosynthesis. I. Review of
  Earth Organisms. *Astrobiology*, 7(1), 208–221.
- Kiang, N. Y., et al. (2007). Spectral Signatures of Photosynthesis. II.
  Coevolution with Other Stars and the Atmosphere on Extrasolar Worlds.
  *Astrobiology*, 7(1), 252–274.
- Lehmer, O. R., & Catling, D. C. (2021). The Peak Absorbance Wavelength of
  Photosynthetic Pigments around Other Stars from Spectral Optimization.
  *Frontiers in Astronomy and Space Sciences*, 8, 689441.
- DasSarma, S. (2006). Extreme halophiles are models for how retinal-based
  photosynthesis may have evolved on an early purple Earth. *Medical Hypotheses*,
  66(2), 364–368.
- Olson, J. M., & Blankenship, R. E. (2004). Thinking about the evolution of
  photosynthesis. *Photosynthesis Research*, 80, 373–386.
- Blankenship, R. E. (2014). *Molecular Mechanisms of Photosynthesis*, 2nd ed.
  Wiley-Blackwell.
- Stomp, M., et al. (2004). Adaptive divergence in pigment composition among
  phytoplankton. *Nature*, 432, 568–570.
- Taiz, L., Zeiger, E., Møller, I. M., & Murphy, A. (2015). *Plant Physiology and
  Development*, 6th ed. Sinauer（C3/C4 量子需求与光呼吸，教科书）.
- Pecaut, M. J., & Mamajek, E. E. (2013). Intrinsic Colors, Temperatures, and
  Bolometric Corrections for Pre-Main-Sequence Stars（EPE 主序表同源）。
  arXiv:1303.1645.
