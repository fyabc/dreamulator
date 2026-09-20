# 无生命天体的气候划分：学界实践与 UCC 含义

> 2026-09-21 整理，来自天体气候划分文献调研（UCC v2 候选轴的参照目标调研）。
> 完整证据（~85 条文献、判据原文引述、检索留痕、核实等级标注）在
> `private/reviews/ucc-body-climate-taxonomy-2026-09-21.md`（未入库）；本文是
> 世界无关的知识提炼。所有引用均经该调研核到摘要/原文级。

给火星、金星、土卫六、月球这样的无生命天体做「气候分类」时，一个反复被证实的
事实是：**学界没有对被广泛采用的格点级气候分类方案**。地球上的 Köppen–Geiger
谱系（格点贴字母码）在这些天体上既没有先例、也没有需求——它们的气候空间信息
住在别的变量轴上。这不意味着这些天体没有气候区划语言；恰恰相反，每个天体都有
自己成熟的组织方式，只是轴不同。

## 1. 各天体的实际区划实践

**Mars**：唯一的 Köppen 化尝试是 Hargitai（2010，LPSC 会议摘要）的温度-only
A–F 带，未被主流采用。实际的区划语言按变量轴组织：① 表面气压 vs 水的三相点
（611 Pa）——Haberle et al. (2001) 以此划出五个「液态水有利区」，约占火星面积
29%；② 挥发分稳定的纬度界（地下冰稳定 ~49°、表面霜 ~30°，Schorghofer &
Aharonson 2005）；③ 尘暴事件分类（regional A/B/C，Kass et al. 2016，判据如
50 Pa 温度抬升 >200 K）；④ 古气候干旱度指数与显式 "climate zonation"
（Kite & Noblet 2022）；⑤ 气候态时间演化（Kite & Conway 2024 的七次转折）。

**Titan**：无正式分区，但有稳定的非正式区域词汇——极地湖区（湿）/ 赤道干旱
沙丘带 / 中纬云带 / ITCZ 迁移带（Faulk et al. 2020 的 "polar moist climes and
equatorial deserts"；云气候学观测线 Roe 2005、Rodriguez 2009/2011、Turtle
2011/2018）。供需型收支语言已经存在：Schneider et al. (2012, Nature) 的净
降水−表面输运−蒸发年均平衡句、Mitchell et al. (2012) 的 P/E 强度。唯一显式
分类尝试是 Olcott (2024) 的 Yale 本科毕业论文（TAM 模式、温度+降水+季节变率
三变量、受 Köppen 启发，未经同行评审）。

**Venus**：高置信负结果——不存在任何表面气候分区（12 条检索全记录在案）。
表面唯一有效的空间轴是**高度**：递减率 7–8.5 K/km（实测核实值），13 km 地形
幅度对应 ~100 K 温差；Maxwell Montes 的「雪线」（金属霜沉积边界）本质是等
温度-气压等高线（Strezoski & Treiman 2022）。cold collar、极涡、云层分层都是
大气柱的垂直/动力结构描述，不是地表分区。「分类」只发生在气候态类型学
（runaway vs moist greenhouse；Way & Del Genio 2020 的 Arid/Aqua-Venus 情景）。

**Moon 与无大气天体**：「气候」概念本身不存在——主流文献（Williams et al.
2017 Icarus；Schorghofer 2025）全文 climat* 零次出现，学科词汇是 **thermal
environment**。但存在正式的定量分类词汇：**cold trap**（现代操作判据：年最高
温 <110 K ⇔ 水冰保存 >1 Gyr，Williams et al. 2019；原始判据 Watson et al.
1961）、**PSR 永久阴影区**（Mazarico et al. 2011 正式定义 + 面积统计）、
纬度 × 地方时坐标系。水星研究完整复用同一套词汇（Deutsch et al. 2016/2018）。

## 2. 通用跨行星框架：四类独立实践

① **温度阈值气候态**：Wolf et al. (2017) 用全球均温阈值分四态
（<235 K 冰封 / 250 K / 275–315 K 宜居 / >330–355 K 湿温室），Goldblatt et al.
(2015) 给出禁态区间，Ramirez (2020) 证明阈值随 N₂ 分压与恒星型移动（= 阈值
必须声明标定域）。② **动力 regime**：Haqq-Misra et al. (2018) 按 Rossby 变形
半径/Rhines 长度与行星半径之比三分。③ **GCM 互比较场景**：Yang et al. (2019)
的 875 颗行星网格实验、THAI、CUISINES (2024)——按场景而非按格点分类。
④ **地球分类移植**：同行评审论文为零；唯一应用是 Uppsala (2025) 硕士论文把
Köppen 用于古火星与 TRAPPIST-1。

格点级「热量 × 供需」两轴组合（UCC 的现有设计）在文献中是**空位**——最近的
已核实先例是 Del Genio et al. (2019) 的系外行星 aridity index（格点级净水分
供给，III 类），但没有人把它和热量带组合成分类。

## 3. 对 UCC 的含义（三层分工）

UCC v1 在四天体上产出高度均质的类分布（Mars 100% Pn、Venus 100% Ra-w、
Titan Pn/Po、Moon Cn/Pn）——调研结论：**这不是缺陷**。学界同样不做格点级分类；
把这些天体的空间信息硬塞进热量/供需两轴是层次错误。正确方向是三层分工：

1. **世界级前缀**承载「这是哪类行星气候」（runaway / 薄 CO₂ 冷干 / 甲烷水文 /
   无大气）——学界跨行星分类最成熟的一支正是这种行星级类型学（证据 A）；
2. **修饰语与新描述量**承载 cell 级剩余空间信息：高度-气压修饰语（Venus 的
   61 °C t_mean 跨度全在数据里、类码全同——证据 A，提案 §3.7 已有 -H 设计）、
   三相点关系描述量（Mars）、光照 regime 与冷阱判据（Moon，词汇一手但纳入
   UCC 属语义扩展，须声明）；
3. **广义需求模型**让供需轴在可算的世界复活（Titan 甲烷版 AI——一手概念存在、
   统一化属首创，证据 B+）、在不可算的世界诚实拒绝（Venus 热侧、Moon 无大气）。

候选轴优先级、每轴的五项评估（文献支撑/新描述量/共享阈值兼容性/区分度收益/
证据等级）见 `private/plans/ucc-01-plan.md`「v2 候选」节与调研文档 §6。

## 4. 引用纪律警示

本次调研的任务书预设了 17 处「已知文献」，经多数据库穷尽检索**全部不存在或
题录有误**（含把 Schneider et al. 2012 Nature 的内容安到不存在的 Faulk 2017
GRL 上、年份互换、期刊错配等）——每条的真实替代文献见调研文档 §5.2 勘误框。
教训与仓库既有纪律一致（memory: citation-verify-primary-source）：**凭印象
写入调研提示的引文错误率极高**；任何进入仓库文档的引用必须走「抓到摘要/原文
→ 标注核实等级」流程，负结果与勘误本身是一级产出。

## 相关文档

- `docs/knowledge/climatology/ucc_climate_descriptors.md` — UCC 描述量与分类
  profile（§8 有四天体的演练与实测对照）
- `data/worlds/earth/design-notes/ucc-worked-examples-{mars,moon,venus,titan}.md`
  — 四天体实测 worked examples
- `docs/knowledge/planetary_science/solar_system_data_sources.md` — 四天体数据源
  与抓取经验
- `private/reviews/ucc-body-climate-taxonomy-2026-09-21.md` — 完整证据文档（未入库）
