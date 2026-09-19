# 统一气候描述（UCC）：连续描述量与分类 profile

> 2026-09-20 整理，对应 UCC-01 第一至三步的已冻结内容。实现入口是
> `src/dreamulator/map/ucc.py` 的 `compute_descriptors()`（描述量）与 `classify_v0()`
> （分类 profile v0）；逐 cell 描述量的导出格式见
> `docs/design/pipelines/climate-pipeline.md` 的 climate_yearly.msgpack 一节。
> 设计与评审依据是 2026-09-17 的 UCC 专项评审和 2026-09-20 的分类候选比较实验
> （完整记录在本仓库 private/reviews/ 下，未入库）。

统一气候描述（Unified Climate Classification，UCC）要解决的问题是：让用户在任意
世界的地图上读到一致、可解释的气候描述。它用「连续描述量 → 版本化分类 profile」
两层结构替代「给每个地点贴一个 Köppen 式字母码」的单层结构。连续描述量回答
「这个地方的气候是什么样的」，分类 profile 回答「按某一版约定好的阈值，它叫
什么」。前者是科学字段，后者是产品约定，两者分开演化。

## 1. 为什么不以 Köppen 为统一标准

Köppen–Geiger 分类的阈值（18°C 热带线、−3°C 温带线、20·T 干旱线等）是二十世纪
早期对地球植被分布的经验拟合（见 `koppen_classification.md`）。在另一颗行星上，
这些数字没有先验成立的理由；即使在地球上，它们对「供需何时错季」「季节有多强」
这类问题也不直接回答。2026-09-20 的实验还给出了一个量化背景：把引擎的完整
Köppen 实现跑在真实观测月度序列上，与 Beck et al. (2018) 的 Köppen–Geiger 数据
集相比，主群一致率只有 84.7%——数据源、分辨率和年代不同就会带来约 15% 的陆地
分歧。既然连「忠实复现 Köppen」都有这样的一致性天花板，把 Köppen 一致率当作
新体系的验收线就没有意义。

因此 UCC 不把 Köppen 当作目标，也不把「与 Köppen 的分歧」当作失败。Köppen 保留为
并列的参照列（它仍是气候学界的通用语言），分歧被记录下来用于理解两套体系各自
在表达什么。UCC 分类的验收标准是信息保留（类内还剩多少重要差异）、稳定性（输入
在不确定范围内扰动时类别有多稳）和用途价值，而不是字母一致率。

## 2. 时间基准契约

描述量的一切都从时间约定开始，跨世界比较才成立。

- **分箱与时长**：气候序列是一组分箱（bin），每个分箱带时长 Δt。当前的月度产品
  使用 12 个等长参考月，每月 365.25/12 天（`result_contract.REFERENCE_MONTH_DAYS`）。
  契约本身不绑定 12 这个数，也不绑定等长——公式里时长权重 w_i = Δt_i / ΣΔt
  显式出现。
- **温度是均值**：分箱温度是该分箱的平均气温。年均温是时长加权平均
  Σ w_i·t_i，不是简单算术平均（分箱不等长时两者不同）。
- **降水是通量**：分箱降水是平均率（mm/分箱），窗口总量是 Σ P_i·Δt_i。
  年度产品的「年降水」指一个参考年（12 个参考月）的总量。
- **干燥度指数是窗口不变量**：AI = P_total / Eref_total 是两个总量的比值，
  不随窗口长短改变。同一个气候态在 100 地球日的窗口和在 365.25 地球日的窗口里
  应得到相同的 AI；不同的是累计量和「低于某阈值的实际时长」。对年长约 100 地球日
  的 Nacrea，这意味着 UCC 的年降水量按参考年报告，不等于一个本地年的累计——两者
  都有意义，但只有前者可以直接跨世界比较。
- **分箱均值不是天气**：「低于 0°C 的时间份额」是分箱平均温度低于阈值的时间
  份额，不是实际霜冻天数。月度分箱会抹掉日内的冻融循环，长太阳日世界（如
  Nacrea）尤其如此。需要日内极端时，应增加更高频的输入或专门的诊断量，而不是
  从月均值里猜。

## 3. 连续描述量

描述量刻意保持少而互补；每个量回答一个其它量回答不了的问题。全部定义见
`ucc.py:compute_descriptors()`，下表是语义与解释边界。

| 描述量 | 定义 | 单位 | 解释边界 |
|--------|------|------|----------|
| t_mean | Σ w_i·t_i | °C | 时长加权年均温 |
| t_min / t_max | 分箱均值的最小 / 最大值 | °C | 是分箱均值的极值，不是天气瞬时极值 |
| t_range | t_max − t_min | °C | 明称为「范围」，不与半振幅混淆 |
| t_below_frac | 分箱均值 < 0°C 的时间份额 | — | 不是霜冻天数（见 §2） |
| p_mean_rate | Σ w_i·P_i | mm/参考月 | 窗口平均降水率 |
| p_total | Σ P_i·Δt_i | mm/参考年 | 参考年总量，非本地年（见 §2） |
| ai | P_total / Eref_total | — | 同期同窗的参考供需比，不是土壤湿度 |
| deficit | Σ max(Eref_i − P_i, 0)·Δt_i / Σ Eref_i·Δt_i | — | 同期亏缺份额：只算当月缺口，忽略储水和横向输水，不命名为实际干旱强度 |
| concentration | C_TV = 0.5 Σ \|q_i − w_i\|，q_i = P_iΔt_i / P_total | — | 降水在时间上的分布与均匀率的差别；集中不等于单峰，也不等于降水丰富；无降水时无定义 |

**部分有效**是契约的一部分：任何字段缺失时，其余有效字段照常输出，缺失字段
携带状态而不是让整条记录消失。状态有四种——`valid`（有效）、`missing_input`
（缺输入，例如没有 PET 模型时 AI 不可算）、`not_applicable`（不适用，例如
P 与 Eref 同为零时 AI 无定义）、`no_positive_demand`（有降水但参考需求为零，
此时不存在有限的供需比，不允许把无穷大偷偷塞进湿润档）。恒温世界是一个重要
的边界用例：全年各分箱同为 15°C 时，温度统计全部有效且 t_range 为零，但温度
季节相位这类量不适用——「没有温度季节」不等于「没有降水季节性」。

## 4. 参考需求模型：Hamon-1961（声明的近似）

AI 和 deficit 里的 Eref 是参考蒸散需求，当前用 Hamon(1961) 温度法估算：逐分箱
Eref（mm/天）= 29.8 × 12 × e_s(t) / (t + 273.15)，其中 e_s 是饱和水汽压（kPa），
固定取 12 小时日长。这是一个纯温度驱动的经验式，实现见
`climate_physics.py:_hamon_pet_mm_per_day()`。

必须明确两点。第一，这是**声明的近似**，不是经过 FAO-56 Penman–Monteith 标定的
参考蒸散 ET0——FAO-56 的参考面是充分供水的假想草地（草高 0.12 m、表面阻力
70 s/m、反照率 0.23），计算涉及温度、湿度、风和辐射（Allen et al. 1998）。
两个模型给出的「干燥度指数」数值不能直接混用，Zomer et al. (2022) 的全球
AI/PET 数据库用的就是 FAO-56 ET0。第二，Hamon 的地球标定不自动迁移到其他
大气成分或溶剂——跨世界时 UCC 只承诺「同一个需求模型、同一种声明」，不承诺
该模型在每个世界都物理准确。描述量文件通过 `demand_model: "hamon-1961"` 元数据
把所用模型随数据带走；未来若升级需求模型，AI 系列量的语义随模型版本一起变。

## 5. 分类 profile v0

分类层把连续描述量映射成有限个可命名、可着色的类。profile 是版本化的：阈值、
名称和有效域构成一个不可变的版本（当前版本标识 `ucc-v0`），任何阈值改动都
产生新版本，旧版本的结果仍可复现。所有阈值都是**声明的经验候选**，全局共享，
绝不按世界各自取分位数——允许一张地图「看起来不够细」，不允许为了它暗改标准。

### 5.1 主类：热量背景 × 参考供需等级

热量背景用分箱均值的极值判定（沿用 Köppen 的热量节点，但只作为声明的经验值）：

| 热量带 | 判据 |
|--------|------|
| polar（极地） | t_max < 10 °C |
| cold（寒冷） | t_min < −3 °C 且 t_max ≥ 10 °C |
| temperate（温和） | −3 °C ≤ t_min < 18 °C |
| tropical（热带） | t_min ≥ 18 °C |

参考供需等级只对陆地判定，用干燥度指数 AI 分三档：arid（AI < 0.5）、
transitional（0.5 ≤ AI < 1.0）、humid（AI ≥ 1.0）。海洋 cell 只给热量带，
干湿轴标记 not_applicable——海洋保留温度与季节描述，面向陆地的干湿类不适用
（海洋分区另有 `ocean_provinces.md` 的体系）。陆地 cell 的 AI 若处于任何非
valid 状态，主类只报热量带并把状态原样带出，不伪装成某个干湿类。

主类共 12 个陆地类 + 4 个海洋热量带。

### 5.2 修饰语（按需出现，不改变主类）

两个修饰语在主类之上独立标记：

- **continental（强季节）**：t_range ≥ 25 °C。它把同一主类内的海洋性与大陆性
  气候分开（伦敦型与北京型的差异），是主类内最大的一项信息损失。
- **water_stress（季节水压力）**：deficit ≥ 0.5，仅在 deficit 有效时给出。
  它把「年供需比相同、但降水与需求错季」的地方标出来——年 AI 相同的两个地点，
  供需同步者 deficit 接近零，错季者可以很高，这是年总量指标结构上无法表达的
  差异。

### 5.3 冻结依据（2026-09-20 L2 实验摘要）

候选比较在真实观测月度网格（NCEP/NCAR R1 温度、GPCP v2.3 降水，20 万 cell，
5.8 万陆地 cell，Beck 2018 Köppen 作参照列）上进行，Köppen 由引擎并列计算。
评估轴是压缩损失（类内还剩多少描述量差异）、稳定性（输入扰动下的换类率）、
覆盖率与复杂度。要点：

- 热量节点带相对「均温 3 带」简单基线的最强单项增益是 t_below_frac 的类内
  压缩 0.67 → 0.00：均温带把「全年无霜」与「有霜季」的地点混在一起，节点带
  把它们精确分开；代价是扰动换类率从 7.8% 升到 8.3%（16 次系统性扰动：
  每 cell 温度恒定偏移 σ=0.75 °C、降水对数正态 σ=12%）。
- continental 修饰语使其轴向类内差异下降 42%（标记 34.5% 陆地），water_stress
  下降 14%（标记 28.4% 陆地），两者采纳。
- 降水集中度修饰语的增益只有 0.2% 且只涉及 5% 陆地，按「没有可重复证据就不
  添加」的停止规则拒绝；把干旱档细分为 AI < 0.2 / 0.2–0.5 的方案（沙漠/半干旱
  分离）证据可重复但收益边际（换类率再升 1 个百分点），不进 v0，留待着色
  阶段重议。
- 同复杂度下，Köppen（27 类）在 t_range、concentration 轴上的类内压缩最好，
  这是它用 s/w/f/m 字母直接编码季节性的结果，代价是类数最多、换类率最高
  （9.4%），且它完全不含供需轴（AI 的类内保留最差）。UCC 用 12 个主类拿到
  大部分压缩，并保留 Köppen 没有的供需信息。

### 5.4 与 Köppen 交叉阅读

两体系的轴是故意正交的。UCC 温和带里有 57% 的陆地 cell 在 Beck 数据集里属于
干旱 B 群——这不是误分：Köppen 的 B 群会覆盖热量字母（一个寒冷沙漠可以是
BWk 而不是 D），UCC 则把热量与干湿放在两根独立的轴上同时报告。反过来，UCC 的
arid 档 97% 命中 Beck 的 B 群，humid 档只有 2%。读图时两套标签并存：Köppen 码
回答「按地球植被经验它叫什么」，UCC 主类回答「按声明的物理阈值它的热量与
供需是什么」。

## 6. 范围限制

首期 UCC 只承诺「温度—水循环季节气候描述」。以下内容**不在**当前描述量与
profile 的表达范围内，引用 UCC 结果时不应外推：

- 日内极端（霜冻天数、热浪）——月分箱结构上抹掉了日内循环；
- 风暴、湿热胁迫、辐射暴露等生存风险——一个简码不能覆盖所有生态风险；
- 固态降水比例——需要真实的雨/雪分相输出，仅凭月均温的估计只能标注为代理；
- 降水的双峰形状与相位——集中度 C_TV 不区分单峰与对称双峰，相位需要另行
  定义时间原点与质量标记；
- 非水溶剂与混合溶剂的供需分类——参考需求模型尚未在这些条件下验证；
- 实际水资源可用性——河水、冰川融水、地下水属于水文层，UCC 的 deficit 只
  描述气候供需的同期亏缺，不描述一个地点实际有多少水可用。

## 参考资料

- Hamon, W.R. (1961). Estimating potential evapotranspiration. *Journal of the
  Hydraulics Division, ASCE*, 87(HY3), 107–120.
- Allen, R.G., Pereira, L.S., Raes, D., & Smith, M. (1998). *Crop
  evapotranspiration* (FAO Irrigation and Drainage Paper 56). FAO.
  [Chapter 2](https://www.fao.org/4/x0490e/x0490e06.htm)
- Zomer, R.J., Xu, J., & Trabucco, A. (2022). Version 3 of the Global Aridity
  Index and Potential Evapotranspiration Database. *Scientific Data*, 9, 409.
  [doi:10.1038/s41597-022-01493-1](https://doi.org/10.1038/s41597-022-01493-1)
- Beck, H.E. et al. (2018). Present and future Köppen-Geiger climate
  classification maps at 1-km resolution. *Scientific Data*, 5, 180214.
  [doi:10.1038/sdata.2018.214](https://doi.org/10.1038/sdata.2018.214)
- Beck, H.E. et al. (2023). High-resolution (1 km) Köppen-Geiger maps for
  1901–2099 based on constrained CMIP6 projections. *Scientific Data*, 10, 724.
  [doi:10.1038/s41597-023-02549-6](https://doi.org/10.1038/s41597-023-02549-6)
- Knoben, W.J.M., Woods, R.A., & Freer, J.E. (2018). A Quantitative Hydrological
  Climate Classification Evaluated With Independent Streamflow Data. *Water
  Resources Research*, 54. [doi:10.1029/2018WR022913](https://doi.org/10.1029/2018WR022913)
  （连续描述 + 独立用途验证的方法论参照）

## 相关文档

- `koppen_classification.md` — Köppen 阈值表（UCC 的并列参照列）
- `climate_classification_comparison.md` — 四大分类体系比较（UCC 的调研背景）
- `energy_balance.md` — Hamon PET 在引擎沉降干旱门中的另一处消费
- `ocean_provinces.md` — 海洋分区体系（UCC 干湿轴不覆盖海洋）
- `docs/design/pipelines/climate-pipeline.md` — climate_yearly.msgpack 导出格式
  与 `result_metadata()` 时间约定（实现层技术参考）
