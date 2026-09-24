# UCC 设计锚点：原则、锚点体系与已否证方向

> 本文是 2026-09-14 UCC 设计提案（原 `docs/design/proposals/unified-climate-taxonomy.md`）
> 经实现裁决后保留的部分：设计原则（§2）、锚点体系（§3——UCC v2 各候选轴的设计
> 基础）、已否证方向（§9，防止重试）与混合溶剂世界附录（草案七转正任务的物性
> 参照）。节号沿用原提案编号，内部与外部引用（如「§3.7 高度-气压修饰语」）不变。
>
> **已删章节的去向**（git 历史可查）：§0 问题定义 → `specification.md` §1；
> §1 调研 → `research/ucc-body-climate-taxonomy-2026-09-21.md`（806 行文献证据）
> 与 `docs/knowledge/planetary_science/planetary_climate_taxonomy.md`；§4 网格/
> 归并/世界档案 YAML 与 §5 分段编码语法 → 实现走了更简的「代码内版本化
> profile + 简码」路线（`specification.md` §5）；§6 世界覆盖矩阵 →
> `examples/`（六天体实测）；§7 实施分期 → `private/plans/ucc-01-plan.md`
> （已全部执行）；§8 命名 → UCC 定名，原则已体现于全库用法。
>
> 现状与实现入口 = `specification.md`；评审与重设计正文 =
> `research/ucc-review-2026-09-17.md`。

---

## 2. 设计原则

1. **物理第一性**。每个阈值必须属于三类之一：(a) 世界物理可推导量，如溶剂相变
   温度、能量-水分无量纲比、环流边界纬度；(b) 世界自身分布的统计量，如分位数，
   只用于归并步骤与修饰段；(c) 方案默认节点，节点值有明确的地球物理语义锚定，
   档案可以覆写。不接受裸调魔数。
2. **方案与档案分离**。普适层零世界假设；一切世界特异性（溶剂、环流体制、归并、
   别名）住进档案 YAML。
3. **时间序列优先**。分类消费的是随时间变化的温度与降水序列本身，而不是单一
   年平均值；季节振幅、集中度、相位全部从序列计算。这里的「月」不专指地球的
   历法月，而是「气候相对稳定、可以采样的较短时间区间」，与采样 bin 数相关
   （详见 3.4 末尾的时间表示说明）。
4. **可扩展性**。参照 ASCIIPA（`packages/conlang/docs/asciipa-reference.md`）
   的做法：分段编码；每段有字符表；档案级的重绑定指令（`rebind:` 节，类比
   ASCIIPA 的 `@bind`）；未知段透传（解析器前向兼容）。新的扩展段追加在编码
   尾部，永不破坏既有编码。
5. **正交性修复**。Köppen 的结构缺陷是把水分带（B 群）插进温度轴，又把「干夏/
   干冬」（s/w）与「干湿程度」（f/m/a）混在同一个字母位。UCC 把热量、水分、
   集中度、相位拆成独立段，各段有自己的物理判据——「10 倍降水比」的双重含义、
   「3 个月旱加 9 个月雨」与「3 个月雨加 9 个月旱」同归 Cwa 这两类歧义在编码
   层面消失。

---

## 3. 锚点体系

以下锚点，每类依次说明：定义、物理来源、默认节点。引擎侧如何取得这些输入，
集中在第 7 章的数据面盘点，正文不重复。

### 3.1 溶剂相窗锚点（热量轴之根）

取主导循环溶剂在世界平均地表气压 P₀ 下的液窗 `[T_melt(P₀), T_boil(P₀)]`，定义
归一化温度

```
θ = (T − T_melt(P₀)) / (T_boil(P₀) − T_melt(P₀))
```

对逐月温度序列计算三个量：θ_cold（最冷月）、θ_warm（最热月）、θ_ann（年均）。

Köppen 与这条轴的兼容不是巧合。地球水在 1 atm 下的液窗恰为 [273.15, 373.15] K，
宽 100 K，于是 Köppen 的四个魔数投影到 θ 轴上是一组整齐的节点：

| Köppen 阈值 | θ 节点 |
|---|---|
| 最热月 0 °C（EF 与 ET 的分界） | 0.00 |
| 最冷月 −3 °C（C 与 D 的分界） | −0.03 |
| 最热月 10 °C（树木线，E 与 C/D 的分界） | 0.10 |
| 最冷月 18 °C（热带线，A 与 C 的分界） | 0.18 |

因此方案默认 θ 节点就取 {−0.03, 0, 0.10, 0.18}。地球档案不需要任何覆写就能
重现 Köppen 的温度带；其他世界继承同一组相对节点，这是有物理动机的起点——液窗
内的相对位置决定溶剂循环的强度与生物化学反应速率的窗口。但要说清楚：这组节点
对异星的有效性是一个假设，不是定律，本方案不预设它成立，档案可以覆写全部节点。

θ 归一化可移植性的支持来自一个一致性检验：土卫六的甲烷液窗约为 90.7 K 至
117 K（1.47 bar 下），表面均温 94 K，算得 θ_ann ≈ 0.13；地球的 θ_ann ≈ 0.15。
两颗溶剂循环活跃的世界落在同一个低 θ 段，说明 θ 归一化把「冷世界里的相对温暖」
与「热世界里的相对温暖」放到了同一个坐标上。两点提醒：水液窗恰好 100 K 宽是
数值巧合，θ 节点继承的是相对语义而不是绝对数字；两例一致只是支持不是证明
（见 7.3 风险）。

混合溶剂世界的相窗可能不止一个（水窗加乙烷窗）。规则是：溶剂段声明**主导循环
溶剂**，即大气中承担「蒸发-凝结-降水」循环的那一个，θ 用主导溶剂计算；次要
液窗作为扩展段标记（`-W2`，Phase 3 预留）。密度翻转（四氢化萘与水在 −12 °C
密度交叉，见附录）是海洋层序现象而不是大气分类维度，不进编码——该世界的气候
分类照常按主导可凝组分计算。

气压的两个用途要分开。世界气压 P₀ 进液窗定义，这是低气压与高气压世界的支持
机制。海拔不进 θ：如果用局部气压算液窗，高原 cell 的同一温度会映射到更高的 θ，
冷带边界随海拔反向漂移（已否证，见第 9 节）；海拔效应由温度场本身承担（递减率
已在引擎中），加上 `-H` 高地覆盖段（3.7）。

**生物圈接口**（原「生物圈锚点」，审稿后并入本节）。Köppen 的 10 °C 与 18 °C
本质上是地球植被的生理极限；在 UCC 里它们已经是 θ 默认节点，也就是说它们
是「地球生物学档案」的槽位填充，而不是方案常数。异星生物的热极限不可先验地
知道，所以方案只留接口：档案的 `bio_anchors:` 节声明「生物生长温度上下限」
（默认值就是上面这组 Köppen 推出的 θ 节点），允许世界作者覆写 θ 节点或追加
生物带；`-B` 扩展段承载生物带编码，没有生态数据时段位缺省、方案照常运转。
Holdridge 生物温度（0–30 °C 截断的年均温）的思想以「θ_ann 加截断节点」的形式
由 `bio_anchors` 表达，不做独立体系。这一接口在引擎侧的依赖方向问题见 7.3。

### 3.2 能量-水分平衡锚点（水分轴之根）

定义干燥度指数 `AI = P_annual / PET_annual`（UNEP 约定，等于 Budyko DI 的倒数）。
这里 **P 是年降水量**；**PET 是潜在蒸散量**——一地若始终供水充足时能蒸发掉的
水量，它不是实际蒸散（实际蒸散受供水限制），而是「大气对水分需求强度」的量度。
UCC 用 Hamon 形式的 PET，即温度与昼长的函数（Hamon 1961），引擎已实现并在
`subsidence_aridity_gate()` 中消费。

默认节点取 UNEP 干燥度分区（Zomer et al. 2022），与引擎既有的 AI 阈值同源，
不引入新魔数：

| AI | 带 | 字符 |
|---|---|---|
| > 0.65 | 湿润 | `W` |
| 0.50–0.65 | 半湿润（干亚湿润） | `w` |
| 0.20–0.50 | 半干旱 | `s` |
| 0.05–0.20 | 干旱 | `a` |
| ≤ 0.05 | 极旱 | `A` |

AI 是无量纲比值，跨气压、跨重力的世界直接可用。跨溶剂时 PET 需要广义化：把
潜热与饱和水汽压换成溶剂参数（Clausius–Clapeyron 关系用溶剂的汽化潜热与摩尔
质量），属 Phase 3 工作。

海洋 cell 沿用现契约输出 `"Ocean"`（UCC 码 `OC`），不做海面分类，与
`koppen_classify` 行为一致。

### 3.3 世界统计锚点（分位数）

分位数回答「这块地在本世界算多湿、多热」，是相对程度、不是绝对类别。设计上
不让分位数当主轴：纯相对分档会让海洋行星和沙漠行星都各得一个「最湿带」，跨
世界不可比，失去物理意义（第 9 节）。分位数用在两处：

1. **归并步骤的经验依据**（第 4 节）：统计世界实际占据的网格组合，空组合与
   稀有组合归并掉。
2. **可选扩展段 `-Q`**（世界相对分位标记）：cell 的年降水量在本世界的十分位
   （`-Q1` 到 `-Q9`），作为跨世界比较高低程度时的上下文修饰，不参与主分类。

### 3.4 周期性锚点（季节与变化的普适化）

普适化的做法是对温度、降水序列做谐波分解，不假设「年周期是唯一周期」；年长
不等于 12 个采样区间的世界按年相位重采样。各量定义与默认节点如下：

| 量 | 定义 | 所在段 | 默认节点 |
|---|---|---|---|
| 振幅 | α = θ_warm − θ_cold（液窗归一，无量纲） | 热量段修饰符 | α ≥ 0.30 为 `x`（大陆性；北京约 0.31）；α ≤ 0.12 为 `o`（海洋性；伦敦约 0.11）；其间省略 |
| 生长季长度 | 年内 θ_m ≥ 0.10 的月份数（Trewartha 轴的移植） | 热量段数字 | 0–12 原样编码；A 带恒为 12 则省略，F 带恒为 0 |
| 集中度 | CR = 最湿连续四分之一年的降水 / 年降水（窗长按年长比例取，跨世界可比） | 降水段 | CR < 0.45 为 `u`（均匀）；0.45–0.60 为 `k`；> 0.60 为 `m`（季风性集中） |
| 相位（雨热同期性） | 降水峰值（最湿月）相对温度峰值（最热月）的相位——两者同季、反季、还是无显著湿季 | 相位段 | 最湿月落在温度峰值一侧（夏雨）为 `Pw`；落在温度低谷一侧（冬雨）为 `Ps`；无显著湿季（全年均匀）为 `Pf`；降水双峰（第二谐波振幅大于第一谐波）为 `P2` |
| 变化率与极端 | 最快季节转换速率 max\|dθ/dt\|、霜热极端频次 | `-V` 扩展段 | Phase 3 预留（nacrea 巨型风暴、翻转历法世界都用得上） |

四个设计要点：

- 高偏心率距离季节世界自动覆盖。距离季驱动温度与降水同相于近日点，降水峰值
  落在温度峰值一侧，输出 `Pw`（夏雨型）。机制不需要知道季节的驱动力是倾角还是
  距离，只测量降水峰值相对温度峰值的位置——这就是「所有变化规律」的普适化
  处理方式。
- 锁定世界退化保护。无周年季节时振幅、集中度、相位全部落入省略档，空间梯度
  由热量带 Ls/Lt/Ln 承担（3.6）。
- 弱季节保护。α 低于噪声阈值（档案可设，默认 0.02）时相位段强制 `Pf`，防止
  对近乎常数的序列读出伪相位。
- 相位段的字母选择。`Ps`/`Pw`/`Pf` 的 s/w/f 沿用主流气候分类（Köppen/Trewartha）
  的第二字母语义——summer dry（夏干）/ winter dry（冬干）/ no dry season（无
  干季）。它们与 UCC 的「雨热同期性」是镜像关系：主流从「干季在哪」定义，UCC
  从「湿季在哪」定义，两者等价（夏干 ⟺ 冬雨 ⟺ 最湿在冬 ⟺ 反相）。P 前缀标识
  「phase」段、与水分段的裸 `s`/`w` 消歧；`P2` 保留双峰。

时间表示与 bin 数的关系：3.4 的所有量都是**相位分量**——集中度用年长四分之一
的连续窗口，相位用降水峰值相对温度峰值的位置，极值取自采样序列——因此分类对
bin 数不敏感：世界存储用更多 bin 时同一套公式直接成立，锁定世界零周期时各量
落入省略档。引擎数据契约里的「月」（年 12 等分）是存储约定而非物理常量：对地球
它是充分采样（温度年循环谐波 1–2 阶主导、约 4 阶充分，12 bin 按 Nyquist 可精确
表示 ≤6 阶）；nacrea 年长 100 天，「月」= 8.33 天 ≈ 2.4 个太阳日，bin 无历法
含义（弱季节所以采样误差小，未咬人）。「时间表示通用化」（bin 数由世界强迫
频谱派生，或直接存谐波系数；潮汐锁定 = 0 谐波稳态特例）已登记 roadmap 技术债，
与 Phase 3 的 `-L` 锁定段同一前提捆绑；分类端无需改动、自动受益。

### 3.5 环流体制锚点

世界级信息进编码前缀：每半球环流圈数 `C<n>`。圈数本身可由 Held & Hou (1980)
的尺度理论从自转速率、行星半径、气体常数派生（快自转世界会得到更多圈），
也可以直接读引擎配置的体制值。潮汐锁定世界的体制码是 `TL`。

这是编码里唯一的「环流」信息，只表达世界级的环流体制（几个圈、是否锁定），
不划分 cell 级的环流带。划分 cell 级环流带（热带/副热带/中纬/极地）的做法
已否证：它与热量带加水分带高度冗余（热带≈热、副热带≈干旱、中纬≈温带、极地≈
寒），单圈世界里整段退化为无信息（见第 9 节）。温度带、水分带、季节相位已经
承载了环流带想要表达的纬向分异。

### 3.6 锁定行星空间锚点

采用眼球行星文献的三 regime 词汇（Turbet et al. 2016；arXiv:2212.06185）：以
星下点角距划区。锁定世界没有季节，热量带的 θ 判据（最冷月/最热月）失效，故
锁定世界的热量带改用三个空间分区：`Ls` 星下区（角距 ≤ 45°）、`Lt` 晨昏带
（45°–90°）、`Ln` 夜侧（> 90°）。它们与自转世界的 A/C/D/E/F 是同一个热量轴
在两种体制下的表达（见 5.2 热量带行），不是独立的段。引擎尚无锁定气候模式
（需要恒定点强迫的 EBM/GCM 分支），这超出分类方案的职责——分类只做「引擎产出
什么就分什么」的下游，编码位先占住；锁定世界的其他扩展（食、天平动）归 `-L`
段 Phase 3。

上述「无季节」假设以**低 e** 为前提。高 e 锁定世界有**离心率季节（距离季节）**：
近日点/远日点的日照按 1/r² 变化，产生全球同相的「夏/冬」（与倾角季节的南北半球
反相不同），相位段会输出 `Pw` 而非退化省略；且离心率使星下点**天平动**（libration，
Dobrovolskis 2007），e≥0.72 时摆动超过 90°、永久夜侧消失，`Ls`/`Lt`/`Ln` 分区本身
失效。这一按 e 的二分留待 Phase 3（依赖引擎是否给 e>0 的锁定场景）处理。

### 3.7 海拔/气压锚点

高地覆盖段 `-H`，判据采用 Trewartha 的高地判据（而非简单海拔阈值）：把 cell
的温度修正到海平面（加递减率 × 海拔），若**修正后的 θ 落入与当前不同的热量带**，
说明这个 cell 的热量带是海拔「抬」出来的（不是纬度给的），追加 `-H` 标记。
这样海拔通过温度场体现主分类（一个热带高山的 θ 落在 C 带，它就是 C 带，气候
状态确实温和），但 `-H` 保留「成因」——`C-H` 是「海拔的 C 带」，与伦敦的纬度
C 带区分。这是 Köppen（状态分类，海拔不单独设类）与 Trewartha（成因区分，设
高地类）两派的折中：主分类跟 Köppen，成因标记跟 Trewartha。青藏 Cwc 即
`C-Wk-Pw-H` 一类。海拔对 θ 的间接影响（递减率）已含在温度场，不重复编码；θ
只用 P₀ 液窗，理由见 3.1。

---
## 9. 已否证方向（防止重试）

- **纯世界分位数相对主义**（所有带都用世界自身分位数划分）：海洋行星与沙漠
  行星会各得一个「最湿带」，跨世界不可比，失去物理语义。结论：分位数只做归并
  依据与 `-Q` 修饰段（3.3）。
- **直接 Köppen 化**（把 18/10/−3 °C 原样用于异星）：这些是地球植被的经验
  拟合，没有先验理由移植。结论：以 θ 液窗归一化替代，地球节点按构造保留。
- **局部气压液窗**（θ 用 P(z) 而非 P₀ 计算）：高原 cell 的同一温度会映射到更
  高的 θ，冷带边界随海拔反向漂移——10 °C 在 5 km 高度算出 θ = 0.12，逃出
  E 带，方向错误。结论：海拔走 `-H` 覆盖段加温度递减率本身。
- **整行星级分类当逐 cell 方案**（PHL thermo/meso/psychro、Kopparapu 宜居带
  类别）：没有空间分异，服务不了世界构建的地图需求。结论：作为互补品可放在
  天文层当粗筛标签，不进本编码。
- **cell 级环流带（T/S/M/P）**：Alisov 遗传分类（以气团-环流带划分气候的苏联
  传统，Alisov 1956）是有据的先例，但 cell 级环流带与热量带加水分带高度冗余
  （Köppen 的 A/B↔Hadley、C/D↔Ferrel、E↔极地的对应），且单圈世界（nacrea）
  里整段退化为无信息。结论：只保留世界级体制码 `C<n>`/`TL`（3.5），cell 级
  环流带移除，其纬向分异由热量带、水分带、季节相位承载。
- **照搬 Trewartha/Holdridge/Thornthwaite 为独立并列体系**（roadmap 原 P2
  条目 4 的方案）：三套并存等于三套地球阈值加上无跨世界语义，维护成本与信息
  冗余都高。结论：三者的创新点（生长季长度、生物温度、PET 双平衡）已被
  3.1–3.3 吸收为单一体系的轴，不再单独立项；roadmap 条目 4 改指本提案。

---

## 附录：混合溶剂世界（供编码参考）

本附录记录与 UCC 编码相关的混合溶剂世界要点，正文不再依赖外部草案文档。

### 混合溶剂类型（原草案三、四、七、八）

| 草案 | 概念 | 溶剂结构 | 对 UCC 的意义 |
|---|---|---|---|
| 草案三 | 温水双洋 | 上层乙烷海（ρ≈0.4）+ 下层水海（ρ≈1.0），互不相溶 | 双液窗：水窗 + 乙烷窗 |
| 草案四 | 冷海双洋 | 上层乙烷 + 下层液氨 | 双液窗：氨窗 + 乙烷窗 |
| 草案七 | 四氢化萘密度翻转油海 | 四氢化萘油海 + 水，密度随温度交叉 | 密度翻转（−12 °C） |
| 草案八 | 冰-油-卤水三层 | 部分加氢环烷芳烃混合物油层（ρ 0.92–0.99） | 静态三层密度阶梯 |

### 草案七的密度翻转（为什么不进编码）

四氢化萘（tetralin，C₁₀H₁₂）密度 0.970 g/cm³（20 °C），热膨胀系数 8.8×10⁻⁴ K⁻¹，
密度随降温快速上升；而过冷水密度随降温下降。两条曲线在 **−12 °C 交叉**：
T > −12 °C 时油浮水上，T < −12 °C 时水浮油上，导致「冰—油—水」层序每年冬夏
各翻转一次（瑞利-泰勒失稳）。

这是**海洋层序**现象（密度分层翻转），不是**大气**现象。UCC 分类的是大气循环
（蒸发-凝结-降水），密度翻转不影响大气分类维度，故不进编码（3.1）——该世界的
气候分类照常按主导可凝组分计算。

### 四氢化萘物性（`tl` 子码的依据）

| 物质 | 分子式 | 密度 g/cm³ (20 °C) | 熔点 | 沸点 |
|---|---|---|---|---|
| 四氢化萘（tetralin） | C₁₀H₁₂ | 0.970 | −35.8 °C | 207.6 °C |
| 十氢萘（decalin） | C₁₀H₁₈ | 0.890 | −43/−31 °C | ~190 °C |
| 茚满（indane） | C₉H₁₀ | 0.965 | −51.4 °C | ~178 °C |

---

## 参考文献

- Köppen, W. (1936). "Das geographische System der Klimate." *Handbuch der Klimatologie I.C*.
- Trewartha, G.T. (1966). *The Earth's Problem Climates*. Univ. of Wisconsin Press.
- Thornthwaite, C.W. (1948). "An approach toward a rational classification of climate." *Geographical Review 38*.
- Holdridge, L.R. (1947). "Determination of world plant formations from simple climatic data." *Science 105*.
- Budyko, M.I. (1974). *Climate and Life*. Academic Press.（辐射干燥度指数 DI = PET/P）
- Zomer, R.J. et al. (2022). "Version 3 of the Global Aridity Index and Potential Evapotranspiration Database." *Scientific Data 9:327*.（UNEP AI 阈值表）
- Hamon, W.R. (1961). "Estimating potential evapotranspiration." *J. Hydraulics Div. ASCE 87*.
- Held, I.M. & Hou, A.Y. (1980). "Nonlinear Axisymmetric Circulations in a Nearly Inviscid Atmosphere." *J. Atmos. Sci. 37*.（Hadley 范围的尺度理论）
- Alisov, B.P. (1956). *Климатические пояса и области*（气候带与区域；气团-环流带遗传分类传统）.
- Kopparapu, R.K. et al. (2018). 宜居带类别的系外行星分类；综述见 arXiv:2409.09666 "Classifications for Exoplanet and Exoplanetary Systems" (2024).
- Turbet, M. et al. (2016). "The habitability of Proxima Centauri b: II. Possible climates and observability." *A&A 596:A112*.
- Dobrovolskis, A.R. (2007). "Spin states and climates of eccentric exoplanets." *Icarus 192, 1–23*.（锁定行星的离心率季节与星下点天平动——3.6 高 e 二分的依据）
- "Terminator Habitability: The Case for Limited Water Availability on M-dwarf Planets" (2023). arXiv:2212.06185.
- Olcott, A.M. & Lora, J.M. (2024). "Investigating the Effect of Titan's Hydrologic Cycle on its Surface Environment." Yale STARS2 Symposium poster.（土卫六气候分类先例：表面温度/降水/季节三变量借鉴 Köppen + TAM 模型）
- Hayes, A.G., Lorenz, R.D., & Lunine, J.I. (2018). "A post-Cassini view of Titan's methane-based hydrologic cycle." *Nature Geoscience 11, 306–313*.（土卫六甲烷湖分布、赤道干燥、经向温度梯度 ~3 K——5.3 土卫六示例的物理依据）
- Engle, A.E. et al. (2021). "Phase Diagram for the Methane–Ethane System and Its Implications for Titan's Lakes." *The Planetary Science Journal 2:4*.（甲烷-乙烷共晶凝固点 ~72 K，解释 5.3 土卫六「F 带却液态湖」的混合溶剂现象）
- Lunine, J.I. & Lorenz, R.D. (2009). "Titan's methane cycle."（见 geo.arizona.edu 转载）
- Forget, F. & Leconte, J. (2014). "Possible climates on terrestrial exoplanets." *Phil. Trans. R. Soc. A 372*.
- Hoffman, P.F. et al. (2017). "Snowball Earth climate dynamics and Cryogenian geology-geobiology." *Science Advances 3, e1600983*.（非液态表面循环 + 冰下液态海洋的分层宜居先例——7.3 固态溶剂循环边界的依据）
- Budisa, N. & Schulze-Makuch, D. (2014). "Supercritical Carbon Dioxide and Its Potential as a Life-Sustaining Solvent in a Planetary Environment." *Life 4(3), 331–340*.（超临界 CO₂ 作生命溶剂，备受质疑——7.3 超临界溶剂边界的依据）
- Hersfeldt, N. (2024–2025). "Beyond the Köppen-Geiger Climate Classification System" 系列（worldbuildingpasta.blogspot.com；Pasta Bioclimate System，非学术先例）.
- Orosz, J.A. et al. (2012). "Kepler-47: A Transiting Circumbinary Multi-Planet System." *ApJ 761*.（arXiv:1208.5489；环双星宜居带行星锚）
- Madhusudhan, N. et al. (2023). "Carbon-bearing Molecules in a Possible Hycean Atmosphere." *ApJ Lett*.（K2-18 b）
- "General Circulation Models of Hycean Worlds" (2025). arXiv:2511.07546.
- "Exploring exomoon atmospheres with an idealized general circulation model" (2018). *MNRAS 479:3477*.（系外卫星气候：食与锁定效应）
- 内部文档：`docs/knowledge/climatology/climate_classification_comparison.md`
  （地球四体系比较）、`docs/knowledge/astrobiology/alternative-solvents.md`
  （溶剂相图数据）、`packages/conlang/docs/asciipa-reference.md`（可扩展 DSL
  语法参照）。
