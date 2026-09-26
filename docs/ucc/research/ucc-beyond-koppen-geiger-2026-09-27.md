# UCC 参照调研：Pasta Bioclimate System（「Beyond Köppen-Geiger」三部曲）（2026-09-27）

> 来源：2026-09-27 调研任务（用户 interlude 2026-09-26 提出，次日追加全站调研）。
> 原料：worldbuildingpasta 博客「Beyond the Köppen-Geiger Climate Classification
> System」三部曲全文，Part I（2024-12，扩展与替代方案综述）
> <https://worldbuildingpasta.blogspot.com/2024/12/beyond-koppen-geiger-climate.html>、
> Part II（2025-03，新生物气候分类系统设计正文）
> <https://worldbuildingpasta.blogspot.com/2025/03/beyond-koppen-geiger-climate.html>、
> Part III（2025-05，系统自评）
> <https://worldbuildingpasta.blogspot.com/2025/05/beyond-koppen-geiger-climate.html>。
> 三篇全文的抓取存档在 `private/research/ucc-beyond-koppen-geiger-part{1,2,3}.md`
> （private 目录不入 git；原文因版权不转载进仓库，仅存档供内部核对）。
> 对照材料：`docs/ucc/specification.md`、`docs/ucc/design-anchors.md`、
> `docs/ucc/research/ucc-body-climate-taxonomy-2026-09-21.md`。
> 本文性质：UCC 参照调研——对灰色文献（个人博客，非同行评审）的实践者方法论
> 分析。文献条目已于 2026-09-27 合入 taxonomy 文档 §5 第 5 类。

## 0. 系统与作者定位

这套系统的正式名称，作者按气候学习惯称作 Hersfeldt Bioclimate System，按博客
习惯称作 Pasta Bioclimate System；本文统一简称 **PBS**。作者是 ExoPlaSim（一个
开源的系外行星气候模拟器）的世界构建实践者，配套发布了开源风格的脚本
`koppenpasta`，并有科幻短篇发表于 Analog（2025-05）。三部曲的性质是灰色文献：
没有经过同行评审，因此它的权重定位是「实践者方法论参照」，而不是学术权威。
它对 UCC 的价值在于：它和 UCC 是同题同代的产物——都在回应「Köppen 分类不够
用」这个问题，但 PBS 走的是单层分区标签路线（结构上更接近 Köppen 本身），
UCC 走的是「连续描述量作产品、分类是版本化 profile 视图」的两层路线。

## 1. PBS 的目标与思想

### 1.1 设计目标

Part II 的 Goals 节给出的目标是做 Köppen 的**替代**而非扩展，并且以预测生物
群系（biome，即大尺度生态群落类型，如雨林、稀树草原、苔原）为第一目标，优先
于一般性的气候描述。三个改进方向：

1. 分类参数要与 biome 边界**直接功能关联**，不使用间接代理量。作者对 Köppen 的
   批评是它全用代理：用年均温代理温度范围、用月均温代理极值、用降水阈值代理
   干湿状况。Part II 末节甚至给出了一个「Unproxied Köppen-Geiger」兼容层——
   用直接参数重新定义 Köppen 的字母，作为对照与过渡。
2. 扩展到比现代地球宽得多的世界范围：更宽的温度域、不同的季节形态、潮汐锁定
   （同一面永远朝向恒星）、短年份行星——但仍限定在「可支持 Earthlike（地球型）
   生命」的范围内。
3. 分类边界应反映**基本生态屏障**（霜冻、热害、光照、水分），而不是现代地球
   生物演化史上的偶发事件。

### 1.2 九个参数

PBS 的输入是九个参数，逐个说明如下：

- **MinT / MaxT**：最冷月与最暖月温度，划定温度域。
- **GDD**（生长度日，growing degree days：日温超出生物学下限部分的累计值，
  衡量生长季的热量总量）：25-40 °C 区间按每天 20 GDD 的平台计，40-55 °C
  区间衰减。有两个变体：**GDDz** 是高温截断版；**GDDl** 是光照限制版（见
  1.3）。
- **GInt**（生长中断因子）：累计「生长被打断」的强度，取最长的一段中断期。
  冷侧规则是日均温低于 15 °C 时每低 1 °C 积 1 分、0 °C 封顶为每天 15 分；
  **热侧规则是超过 45 °C 起积、60 °C 封顶**；黑暗期（光照不足）也累计。
  1250 GInt 是真热带（TU）与准热带（TQ）、以及 XT/XD 等类别的分界。
- **Ar**（干旱度）= 年 AET/PET。AET 是实际蒸散（生态系统实际消耗的水量），
  PET 是潜在蒸散（供水充足时可能消耗的水量）；比值越低越干。阈值：大于 0.9
  为雨林、大于 0.75 为季节林、小于 0.2 为干旱、小于 0.06 为极旱。这是
  Prentice 一系的经典干旱度定义。
- **GAr** = 用 GDD 加权的 AET/PET——只有生长季内的干湿状况才算数。小于 0.5
  判半干旱。
- **GrS**（雨热相位比）= GDD 加权降水 / 未加权 AET，用来判别地中海式气候
  （冬雨夏干，雨和热不同相位）。地球阈值 1.15；作者为迁就 ExoPlaSim 的模拟
  偏差把它重调为 0.8（这个重调是重要的反面教材，见 §3 第 6 条）。
- **Evr**（水涝比）= 年 AET/年降水。小于 0.4 为超湿润（TUrp，沼泽/雨林/
  季风厚林一类的水涝族）、小于 0.45 为 pluvial（多雨）。
- **MinIce**（最小冰量指标）：区分 CI（冰盖）、**CG（永冻但无冰的干冷荒原**，
  南极干谷的类比——冷到常年冻结、又干到积不成冰）、CF（苔原）。

PET 的计算有三档方法：ASCE 标准化的 Penman-Monteith 法、简化的 Hargreaves
法、以及 Köppen 式的 7 mm·月⁻¹·°C⁻¹ 兜底公式；还有一个 `pet_gascon` 变体，
让有效气体常数随大气成分调整，用于修正非地球大气下的 PET。AET 缺失时用土壤桶
估计器补（土壤有效容量 50 cm、25 cm 以下土面蒸发受限、跨年自洽迭代）——这个
估计器与 dreamulator 引擎的 soil bucket 加 Budyko 再循环属同一族方法。

### 1.3 时间与光照的系外处理

GDD 按「生长度月 × 月长」累计，即用月长修正来适配非地球的轨道周期；支持把
多个文件按顺序拼成一个年（sequential 模式），也支持无季节的年均模式
（seasonless）。另有一个 **productivity modifier**（生产力修正旋钮）：把生物学
阈值整体缩放，例如生产力翻倍时 GInt 的冷侧起点从 15 °C 移到 7.5 °C、热侧从
45 °C 移到 52.5 °C——这是给「异星生物更强/更弱」预留的连续调参。**GDDl**
（光照限制版生长度日）用约 200 W/m² 的光合减速阈值把光照变成一等分类变量。

### 1.4 分区结构

顶层是六个群：T（热带：TU 真热带、TQ 准热带、TF 暮光带、TG 黑暗带）、
C（冷侧：CT 亚热带、CD 温和、CE 北方式 boreal、CF 苔原、CG 干冷荒、CI 冰盖，
以及 XT/XD/XF/XG 等极端变体）、H（热侧）、E（extraseasonal 极端双季：
Exa 超季节、Exb 亢季节，以及 ET/ED/EF pulse/EG 荒芜）、A（干旱：As 半荒漠、
Ad、Ah）、O（海洋：Oc/Ot/Oh 大于 40 °C 热海洋/Or 大于 60 °C、Oe、Ofi/Ofd/Ofg
黑暗季节冰）。类别码是 2-3 个字母的助记组合（如 TUrp、CAMb、Aha），X 是群
占位符——作者明确警告**不要把 x 用作正式类别字母**，因为 x 在气候分类传统里
是通配符惯例（这条对 UCC 的字母表改造直接有用，见 §3 第 12 条）。跨类别的
优先级规则成体系（例如 XF 压 XA 压湿润类；A 压 XA；TF 压半干旱、TG 压干旱；
黑暗海洋压温度带）。

### 1.5 验证方法

地球侧用五个 biome 参照源互校：WWF/Olson 2001 陆地生态区、IUCN 全球生态系统
类型学、Haxeltine & Prentice 1996 的 BIOME3 图、Campbell《Habitats of the
World》、Pfadenhauer & Klötzli 2014《Vegetation der Erde》。数据用 TerraClimate
观测，模型侧用 ExoPlaSim 跑基线地球做双对照。系外侧做参数扫描画廊（温度、
倾角、日长、偏心率、潮汐锁定、短年行星 Teacup Ae 逐一出图）。另有区域调阈
（东亚的类别边界按中国森林型过渡带与日韩的常绿斑块定标）。

### 1.6 作者自认的弱点（Part III）

青藏高原内部出现假 boreal 林（boreal-苔原分界线在高海拔失效）；东非裂谷在
赤道出现「地中海」类怪异但有物理解释（双雨季加雨影时序）；伊朗/巴基斯坦的
Ad/Ah 边界两头不讨好（妥协处理）；中亚出现大块离海岸很远的地中海类（作者接受
为区域怪癖）；印度干旱林/疏林的多样性不足；**Teacup Ae 短年行星（一年只有
地球的三分之一长）暴露了系统性问题：短年导致 GDD 累计不足、苔原误蔓延，而用
productivity 旋钮补偿后 CD（温和）带又整个消失**。作者的总结论是：这套系统
并非处处可以盲读（blind read），需要结合每个世界的具体条件解读，且对异星
生命适应方式的假设不可避免。

## 2. 与 UCC 的逐维对照

| 维度 | PBS 的做法 | UCC 的做法 | 判读 |
|------|-----------|-----------|------|
| 架构 | 参数算好后输出**单层分区标签**；参数本身很丰富，但产品是 zone 码 | **连续描述量本身就是产品**，分类只是版本化 profile 的一个视图 | UCC 的两层分离更干净。PBS 的参数层其实已经是「准描述量」，只是没有被当作产品暴露出来 |
| 时间基准 | 月长修正累计、productivity 生物学旋钮、多文件拼年；年长混淆对 Ar 的影响作者自认未解决 | 本地采样窗口契约（nacrea 的 4 天窗口实践）、365.25/12 只是单位约定；二元性裁决把阈值语义分家 | 同题同困。PBS 把生物学差异做成连续调参旋钮；UCC 做成离散的、可声明的物理家族 profile——UCC 的架构更能防止裸调 |
| 生物锚定 | 单一 Earthlike 谱系，但把异星低温锚点直接放进同一条分类梯（−60 °C 过氧化氢冰点、−97 °C 水-氨共晶、−180 °C 氮/氧大气冻结出局、锂-氨卤水） | A 地球生命默认本体 + B 物理家族 profile（methane-hydrology、airless-thermal）；土著生物宜居性是读数层不是分类层 | PBS 把跨溶剂阈值塞进同一个分类梯，简单但混合了谱系；UCC 分家族，严谨但多一层。PBS 的低温梯子数值可以直接喂给 UCC 轴 C |
| 水分轴 | Ar/GAr 用 AET/PET（AET 靠土壤桶估计）；GrS 雨热相位；Evr 水涝 | ai = p/PET_ref（Hamon 参考需求，与模型土壤态解耦）+ deficit + concentration | PBS 的 AET 路线对观测地球更真实，但对引擎产品有自引用味道（用模型自己算的水循环喂分类）；UCC 的参考需求解耦更干净。不过 PBS 的 GAr（生长季加权）与 GrS 是 UCC「雨热相位描述量」v2 候选的现成工作先例，而且附送作者试过的几十个失败替代方案 |
| 光照 | **一等变量**：GDDl、TF/TG/Ofg 类别、约 200 W/m² 阈值 | v2 候选轴 D（词汇方案评级 A，或纳入轴 C） | PBS 是轴 D 的实现级先例证据：词汇、阈值、潮汐锁定实测三样齐全 |
| 热侧极端 | GInt 热侧 45→60 °C 曲线 + H 群 + Oh/Or 热海洋 | 热侧域门（Venus Ra-w→Rn 前置修复）+ 热侧生物阈值轴候选（t_above_frac、heat_stress） | PBS 的 45/60 °C 锚是 heat_stress 修饰语的量化先例，与「复杂生命上限约 60 °C」的文献一致 |
| 高度-气压 | `pet_gascon` 让 PET 依赖大气成分；Penman-Monteith 法直接吃气压输入 | v2 轴 B（-H 修饰语 + 三相点描述量） | PBS 证明了需求模型必须携带逐世界物理参数——是轴 B 的工程先例（成分侧） |
| 世界级前缀 | 无 | v2 轴 F（证据最强的候选轴） | UCC 独有 |
| 海洋 | O 群全套（SST + 冰 + 光照，含大于 40/60 °C 的热海洋） | v1 范围限制（以陆地为主） | PBS 的海洋带词汇可作 UCC 将来扩域到海洋时的参照 |
| 缺失数据语义 | 无——缺数据靠估计器兜底 | **五种部分有效状态**（status codes 显式声明为什么算不出） | UCC 独有，工程上是关键差异 |
| 认识论标注 | 诚实但非正式：明说 GrS 0.8 是为 ExoPlaSim 偏差重调、阈值按区域调过 | 显式类别标注（守恒/近似/拟合/稳定化）+ 标定域声明 | PBS 的按模型重调阈值正是 UCC profile 版本化 + provenance 声明要纪律化的行为——反面教材兼动机强化 |
| 验证 | 地球 biome 五源互校 + ExoPlaSim 参数扫描画廊 | Beck Köppen + L2 冻结实验 + 六天体/架空世界 examples | PBS 的参数扫描画廊（倾角/日长/短年逐张出 zone 图）是 UCC examples 值得借鉴的呈现形式 |
| 落地形态 | 离线脚本 koppenpasta（多系统并排地图 + 图例 + T-P 散点着色） | 引擎内建 + 前端染色 + 声明面板 | PBS 的「T-P 散点按 zone 着色」是 L2 类实验的廉价诊断图 |

**双方各自独有的东西**：PBS 有而 UCC 没有的——biome 预测这个目标本身（生态
耐受梯子）、光照作为一等变量、热中断曲线、地中海/pluvial 作为一等分区、海洋
带系、AET 土壤桶估计器、unproxied-Köppen 兼容层、参数扫描画廊、短年行星的
实测教训（Teacup Ae）。UCC 有而 PBS 没有的——连续描述量产品层、部分有效
状态、时间基准契约（相对旋钮）、家族 profile 架构、世界级气候态前缀、反循环
的参考需求、冻结实验方法学、认识论类别标注、引擎/前端活产品、canonical
合成反例对。

## 3. 可借鉴点评估（14 条判定）

每条给出「借鉴 / 存档 / 忽略」判定、去向和理由：

1. **GrS（GDD 加权降水除以未加权 AET）及其失败替代方案清单**——判定：借鉴。
   作者在试出 GrS 之前把 GAr/Ar 比、累积亏缺、加权 AET 对比等几十种替代都
   试过并记录为更差，这是 UCC v2 候选「雨热相位描述量」与「季节性轴」的实现级
   先例，而且附送现成的负结果库防止我们重试。去向：`private/plans/ucc-01-plan.md`
   「v2 候选」节引用。
2. **光照 regime 词汇**（GDDl、TF/TG/Ofg 类别、约 200 W/m² 光合减速阈值、
   「黑暗压过干旱」的优先级规则）——判定：借鉴。轴 D（光照 regime）从「词汇
   方案评级 A」升级为「有工作先例」。去向：taxonomy 轴 D 证据段 +
   design-anchors §3。
3. **热侧 GInt 曲线（45→60 °C）+ H 群 + Oh/Or 热海洋**——判定：借鉴。这是
   热侧域门/heat_stress 修饰语的量化锚，与「复杂生命约 60 °C 上限」的文献
   一致。去向：v2 热侧生物阈值轴的证据行。
4. **低温耐受梯的异星锚点**（−60 °C 过氧化氢冰点、−97 °C 水-氨共晶、
   −180 °C 氮大气冻结出局、锂-氨卤水、−80 °C 代谢下限）——判定：借鉴。
   去向：轴 C（跨溶剂广义 AI）+ design-anchors 混合溶剂附录的数值锚。注意
   标注为二级核实（博客转述，非原始文献）。
5. **Teacup Ae 短年教训**（短年导致 GDD 不足、苔原误蔓延；用 productivity
   旋钮补偿后 CD 带整个消失）——判定：借鉴，作为外部印证。这是 UCC「本地
   采样窗口契约 + 家族 profile」路线的独立外部印证：naive 的年长阈值缩放在
   两个方向上都翻了车。去向：时间基准二元性文档补一条外部先例。与 nacrea
   （100 天年）直接相关。
6. **按模型重调阈值的实践**（GrS 1.15→0.8 迁就 ExoPlaSim 偏差）——判定：
   存档，不作借鉴。这正是 UCC profile 版本化 + uccSource 声明面板要防止的
   「模型偏差与阈值耦合」。去向：声明面板的动机强化引用。
7. **productivity modifier 生物学旋钮**——判定：存档。概念上它等于家族
   profile 的连续版本；单个旋钮没有声明域，是裸调风险。它的存在证明了
   「生物学参数必须做到 profile 级别」这个判断。
8. **AET 基的 Ar/GAr（对 P 基 AI 的替代方案）**——判定：存档。它对 AET 的
   辩护（土壤缓冲、干季可见性、对采样期不敏感）值得记入 design-anchors 的
   权衡段；但引擎产品用 AET 是自引用（用模型自己的水循环喂分类），UCC 的
   参考需求解耦原则不动摇。
9. **Unproxied Köppen-Geiger 兼容层**（用直接参数重新定义 Köppen 字母）——
   判定：借鉴，低优先。去向：specification §5.4「与 Köppen 交叉阅读」的升级
   候选——交叉表可以从「码对码」升级为「参数重述 Köppen」，减少代理量污染。
10. **CG 干冷荒（永冻无冰）与 CI/CF 的三分**——判定：借鉴。去向：
    airless-thermal 家族 profile 与 Mars example 的词汇参照（南极干谷类比；
    「冷但干到积不成冰」是纯气候数据可判的带）。
11. **T-P 散点按 zone 着色 + 三联图版式**（模型分辨率双系统并排 + 插值带
    图例）——判定：借鉴，工具面。这是 examples/L2 实验的诊断图形式，成本低、
    信息密度高。去向：下次 UCC 文档/profile 更新时一起做。
12. **x 字母警告**（x 是通配符惯例，不要用作正式类别字母）——判定：借鉴，
    一行。去向：「季节性与字母表改造」候选的约束条件（我们有过 w 改名讨论，
    同理应避开 x）。
13. **海洋 O 群带系**（含热海洋、黑暗海洋）——判定：存档。UCC 海洋扩域未
    排期，词汇留档待用。
14. **PBS 整体作为并行分类产品接入**——判定：忽略。与「不搞并列双产品」的
    裁决冲突（见时间基准二元性文档）；PBS 是单人博客工具，UCC 走引擎内建 +
    profile 版本化路线。

**与已否证方向的核对**（design-anchors §9 与 UCC 各项裁决）：第 6、7、14 条
正是撞线项，已分别判存档/忽略；第 1、2、3、5 条均为「证据补强」而非新机制，
不与任何已否证方向冲突；第 8 条明确不动摇参考需求解耦原则。

## 4. 参考文献的处理

主条目与二级转述清单已于 2026-09-27 合入
`docs/ucc/research/ucc-body-climate-taxonomy-2026-09-21.md` §5 第 5 类
（「实践者/世界构建业余型」），核实等级标注从该文档体例（三部曲全文已抓取
存档 = 已核实原文；其转述的 Olson 2001、Haxeltine & Prentice 1996、IUCN GET、
Pfadenhauer & Klötzli 2014、Campbell、Belda 2014、ASCE Penman-Monteith /
Hargreaves 等为博客转述、元数据核实级，按需再升级）。原草案文本如下，留档
备查：

> worldbuildingpasta（笔名）. "Beyond the Köppen-Geiger Climate Classification
> System, Part I: Extensions and Alternatives" (2024-12), "Part II: A New
> Bioclimate Classification System" (2025-03), "Part III: Assessing the Pasta
> Bioclimate Classification System" (2025-05).
> worldbuildingpasta.blogspot.com。灰色文献（博客，非同行评审）；实践者
> 方法论参照。全文存档 → `private/research/ucc-beyond-koppen-geiger-part{1,2,3}.md`
> （2026-09-27 抓取）。要点：PBS = biome 预测导向的 Köppen 替代；9 参数
> （GDD/GDDz/GDDl、GInt、Ar/GAr/GrS/Evr、MinIce/MinT/MaxT）；T/C/H/E/A/O 群
> + 优先级规则；光照与热中断一等化；ExoPlaSim 生态；per-model 阈值重调
> （GrS 1.15→0.8）自认。

## 5. 结语

PBS 是目前所见完成度最高的「Köppen 替代」业余实践，它与 UCC 的关系不是竞争
而是互证：它用一条完全不同的路线（单层标签 + 生物学目标 + 旋钮适配）撞上了
与 UCC 相同的一批问题（短年时间基准、模型偏差与阈值耦合、代理量污染），并以
自己的方式翻车（Teacup Ae、GrS 重调）——这些翻车记录恰好从外部印证了 UCC
的架构选择（本地窗口契约、profile 版本化、参考需求解耦）。它的九参数体系里
有五个可以直接为 UCC v2 的候选轴提供先例证据（GrS 之于雨热相位、GDDl 之于
光照 regime、GInt 热侧之于 heat_stress、低温梯之于轴 C、pet_gascon 之于轴 B），
且都附带作者踩过的坑作为免费负结果。
