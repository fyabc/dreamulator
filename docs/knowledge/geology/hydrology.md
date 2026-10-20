# 水文学：D8 流向与汇水面积

> 实现：`src/dreamulator/map/hydrology.py` · 设计：`docs/design/pipelines/geological-pipeline.md` §9

球面 CVT 网格上的河流网络生成，是**地形合成后地形**的一次性水文学产品：洼地填平 →
D8 流向 → 流量累积 → 河网分级/提取，填入 `VoronoiCell` 的
`flow_direction` / `flow_accumulation` / `river_id` / `river_order`，并提取为
河流矢量图层（features.json）。2026-08-26 起流水侵蚀已移除（见
`docs/design/pipelines/geological-pipeline.md` §9.8），水文仅做河网提取。

---

## 1. 洼地填平（priority-flood）

CVT 地形合成会产出大量局部洼地（pit）：直接跑 D8 会在每个洼地得到一个 sink、
河网破碎。用 **priority-flood**（Barnes et al. 2014，O(N log N)）填平：

1. 从海洋 cell（`elevation < sea_level`）出发，用最小堆按高程向外扩张；
2. 每个陆 cell 的临时标高推到 `max(elevation, spill)`（spill = 已填邻居的标高）；
3. 填平只在**临时数组**上进行，**不写回** `cell.elevation`——最终河网提取仍在真实
   地形上做；
4. 内流盆地（无通海出口）在连通球面上不存在（priority-flood 从海洋可达全部 cell），
   完整的湖泊/内流水收支留后续。

`priority_flood_fill(elevation, is_land, neighbors) -> (filled, connected)`：
`filled` 是填平后的标高，`connected` 标记海洋可达的 cell（连通球面上恒全真）。

## 2. D8 流向（最陡下降）

每个陆 cell 的流向是其**最陡下降**邻居：

```
gradient(i→j) = (h_i − h_j) / d_ij
flow_dir[i] = argmax_j gradient(i→j)    # 无下坡邻居 → −1
```

`d_ij` 是大圆距离。D8 只用相对梯度比较，单位（km/m）不影响方向。

## 3. 平区路由（flat routing）

填平后的表面上，溢流台地（spill flat）的 cell 没有严格下坡邻居（`flow_dir=−1`）。
从所有「已解析」cell（海洋 + 已持有下坡方向的 cell）做多源 BFS，把未解析陆 cell
路由到**非上坡**的父 cell（`filled[parent] ≤ filled[child]`）——否则上游山脊 cell
会把平地水导向坡上（已由单元测试覆盖）。

## 4. 流量累积（拓扑排序）

Kahn 拓扑排序，从源头到河口累加上游汇水面积：

```
accum(i) = area(i) + Σ accum(j)   (j ∈ upstream(i))
accum(ocean) = 0                  # 海洋不累积；河口陆 cell 持全流域
```

`flow_accumulation` 单位 **km²**（非 cell 数）。海洋 cell 保持 0，河口陆 cell 的
累积即整条河的流域面积（径流量可在河口读取）。地形视频链的栅格水文
（prog_erosion）把这里的均匀面积累积推广为**水量平衡加权**累积，见 §7。

## 5. 河流分级与河网提取

- `classify_rivers`：按累积面积阈值分级 `{100, 1000, 10000, 100000}`（单位「cell
  数」）→ `river_order` 1–4。阈值按 `cell_area_km2`（平均 cell 面积）缩放，使分级
  **分辨率无关**——order 1 ≈ 100 个 cell、order 4 ≈ 10 万个 cell，与网格精度无关。
- `assign_river_ids`：从河口（流入海洋、累积 ≥ 阈值的陆 cell）逆流追溯，每步跟随
  最大支流，给干流 cell 打 `river_id`；阈值同样按 `cell_area_km2` 缩放。

## 6. 闭合内陆湖（endorheic basin）

`detect_closed_basins`：低于海平面但不连通全球海洋（最大连通分量）的闭合盆地，
标记为 `VoronoiCell.is_lake = True`——即里海/死海/大盐湖型的内陆湖。它们仍是排水
终点（sink），只是分类上区别于海洋；完整的湖泊水收支（§9.5）留后续。

## 7. 河网提取权重、终点湖水收支与月度情相（地形链栅格水文，2026-10）

第 1–6 节是球面 CVT 网格上的引擎水文（均匀面积累积）；地形视频链的
栅格水文（`map/prog_erosion.py`）自 2026-10 起用**水量平衡加权**的累积
提取河网，本节记录其物理与判据。

### 权重 = 年径流（Turc–Pike 年曲线，桶做月度形状）

每个格子的累积权重不是「上游格数」（也不是降水），而是该格的年地表
径流深度，由 Turc–Pike（Budyko 框架）年曲线给出：E/P = (1 + φ^{−n})^{−1/n}，
φ = PET/P 为干旱指数，Pike (1964) 取 n = 2（文献默认值，不拟合），
径流 R = P − E。曲线内插两个 Budyko 极限：水量极限（φ→∞）E→P、
R→0（超干旱 ~2% 产流，wadi 语义）；能量极限（φ→0）E→PET、
R→P−PET（湿润区 R/P 约 0.3–0.6）。需求侧 PET 用 Hamon (1961) 年公式
（引擎同款，日长 12 h 年近似）；年 P 与年 PET 都是 `climate_monthly.msgpack`
的纯函数，EBM 与 GCM 分支同样可事后重算。

年值不用引擎的单层月桶，是 2026-10-17 荒漠验收窗的实测教训：桶的
溢流条件是湿季累计盈余超过全部蓄水容量（Manabe C = 150 mm），强
季节性气候因此系统性零产流——P = 900 mm/yr 的 Csa 山坡（PET 1218）
桶给出恰好 0，而 Turc–Pike 给 R/P ≈ 0.20（≈176 mm/yr），真实世界的
同型山坡有常流河。月桶保留给月度情相的形状（时令河分类），年值由
Turc–Pike 曲线承担——各自用在自己的文献标准领域。

权重按**固定参考径流** R₀（`RUNOFF_REFERENCE_MM` = 300 mm/yr，地球
陆面平均年径流的文献值）归一，累积读作「参考格」，河网阈值
（`RIVER_THRESHOLD_CELLS`，refine 网格按 factor² 放大）于是是一个
**绝对最小流量**：Q_min ≈ 阈值 × R₀ × 格面积 ≈ 2.1 m³/s（550 km 窗、
2048 网格），恰为最细 0.09 mm 河符号对应的源头河量级，任意窗口同一
物理标准。不能用窗口自己的陆均径流做归一子——那是雨量时代的遗产，
在径流权重下会把阈值按窗口气候重新计价（荒漠窗 R̄ ≈ 20 mm/yr 时
Q_min 跌到 ~0.1 m³/s，wadi 重新蔓生；2026-10-17 荒漠窗实测教训）。
基数 3000 的另两层依据：factor² 缩放保证分辨率不变性；图面密度按
Natural Earth 风格标定。想要更密的河源就调低它（减半 ≈ 1 m³/s）。

归一化之外有一个刻意保留的口径差异：侵蚀物理（SPL）仍用降水权重——
暴雨径流是干旱区刻蚀的主力，侵蚀看的是雨，河网看的是水（Gaea 链
时代的裁决，沿用）。

### 终点湖判据与平衡水位

达到制图门槛的湖按年度水量收支二分。记 R̄ 为陆域年均径流
（mm/yr）、PET 为湖面年均温下的 Hamon 年蒸散、P 为湖面年均降水：

> 入库径流（Σ 入湖格累积 × R̄） < 蒸散需求（f·PET − P）按湖格累计
> ⇒ 终点湖；否则过路湖。

两侧同是参考格（入流 × R₀ 恢复 mm/yr），格面积相消。**入库必须用
级联记账**（`terminal_equilibrium_routing`），单遍累计会错：树枝状湖
会「自重入」——水从一条臂流出、经陆回流、再从另一条臂进入同一个
湖——每个入湖触点都把同一场水再加一次（2026-10-17 实测某湖「入库」
达全窗总水量的 2.5 倍，假过路判据就是这样放走干流的）。级联三步：
全部湖先当汇做「首触」累积，每滴水只记给它到达的第一个湖；湖图
（receiver 森林按湖收缩，必为无环）沿拓扑序传递
`总入流 = 首触外入 + Σ 上游湖出流`、`出流 = 总入流 − 需求`
（需求为负的湿润湖净增水，同样入账）；装不满（总入流 < 需求）即终端。
过路湖的需求同时从**过流量**里扣除（出湖格上的负点权重，Landlab
文档化的传输损失机制）——不扣的话荒漠湖链会把全量洪水传下去，
165 m³/s 的干流曾凭此冲出本应内流的流域（同日实测）。

终点湖随即改写到它的**平衡水位**：装不满到溢口的湖停在年度收支
闭合的面积上，A* = 入库 ÷ 每格需求（参考格）。湖面取洼地内最深的
⌈A*⌉ 格（按 DEM 排序），标为非陆格水供**渲染掩膜**使用；A* 小于
渲染 MMU 的湖维持不住可见水面，是**干盐湖**：整片湖床成陆地（低于
海平面的床面抬到海平面），但最深处保留 1 格非陆汇点——亚 MMU 水面
在所有渲染掩膜里不可见，而河网与累积必须在盐滩终止（流向 Eyre
湖床的河不会穿过湖床走到海）。河链的终点掩膜同时包含缩水水面与
干滩足印（`chain_stop`），河线画到干滩外缘即止。

**排水全程用改写前的树**，终端湖足印在累积与河链里按汇切断
（receiver 置 −1）；不可以在改写后的场上重跑 Priority-Flood——干化
盆地的汇点会成为新基准面，把判据时根本没喂它的大河**捕获**进来
（164 m³/s 的干流曾这样死在一个按 15 格入库评估的不可见盐滩上）。
河链的绘制在足印内补一段续走：缩水湖的可见水面在改写前流域之内、
隔着一圈干出的湖床，切断的 receiver 让链停在流域外缘，图上读作断河
——链沿改写前湖底地形的**下降树**（`lake_fringe_descend`）走过干床、
画进可见水面一格。下降树按高程自低向高指认（每格指向已解析邻居中
最低者，处理序即拓扑序、天然无环），因为湖缘在溢流高程上带着数米宽
的平底带，单步最陡下降在那没有严格更低的邻居（2026-10-17 箭头河
2.5 km 空隙的根因：终点格 811 m，八个邻格全部 ≥811）。干盐滩没有
可见水面，链仍止于足印外缘。refine 的复用
缓存（`height.pre-equilibrium.npy`）存**改写前**的高度场：干化会把
低于海平面的床面抹平，从改写后的场无法再导出判据，快速迭代环必须
从原始几何重新推导。

两个近似都往「过路」方向偏保守：湖面蒸发系数 f = 1.0（深水湖年蒸发
约为参考蒸散面的 0.9–1.3 倍，取下侧使判据恰在干旱带不误伤）；PET 用
年均温代入（Magnus 饱和汽压对温度是凸函数，年均温的 PET 略低于
月均温 PET 的年平均）。图边界上的湖强制过路（流域被窗口截断，
续流是更保守的读法）。低于海平面的封闭洼地（heal_inland_water 的
`inland_big`）参与同一判据：装得满的照常是湖，装不满的干化为盐滩；
其收支为正但 DEM 封闭时（洼地本应溢流却无溢口可凿），诚实语义是
保持终点并在 meta 里记录（凿口属于传输损失一档的后续工作）。

2026-10-17 三窗实测：混合气候窗（25N-100W）101 湖 → 66 过路 /
34 干盐滩 / 1 缩水；荒漠窗（22.5N-100.5E，全陆高原）终端湖占绝大多数；
山前荒漠窗（21.5N-95.5E，主验收窗）级联口径下终端 132（108 干盐滩 +
24 缩水）、湖面占陆 4.2%，原「165 m³/s 干流冲出东缘」消失、内流区
恢复，出框河只剩南/西缘山地湿侧的 55–88 m³/s。北半部原大量小湖在
扣减口径下入库中位 ≈0（需求中位 0.84 m³/s）——多数干化，「有湖就有
水」的旧语义在干旱区高估了大部分水面。

### 月度情相：基流与常流／非常流河段

年径流决定哪里能形成河道，月径流决定已成图河段在一年里有多少个月
保持活动流量。情相提取不改排水树，也不重复地形与湖泊计算：它在
年水文得到的最终 receiver 上分别做十二次累积，每次使用该月的径流
权重。累积是线性的，十二月累积之和等于同一参考径流下的年累积，
所以月度分类与年度河网使用同一张水量场。过路湖的蒸散扣减仍是年度
收支，不拆到各月；这会偏向把荒漠湖下游判为活跃，属于保守方向。

**成图流量与活动流量是两个独立判据。** 年度成图门槛仍约为 2.1 m³/s，
只决定一条河是否值得画。月活动门槛 `REGIME_ACTIVE_DISCHARGE_M3S`
则取月均 1 L/s，只用于区分模型中的活动与断流月份。它换算为累积
参考格时使用 `Q_m = acc_m · R₀ · 格面积 ÷ 当月秒数`，不会从年度成图
门槛除以十二得到。Fritz et al. (2020) 汇总的区域研究中有 1 L/s 的
操作化先例，但文献没有全球统一的断流数值；本库把 1 L/s 视为统一的
工程约定，而不是自然常数。

**月径流形状包含快速流与基流。** Manabe 桶先给出月产流，随后把每
月产流 `W_m` 的固定比例 `f` 补给一个网格内的概念性地下水库，余数
作为快速流。该模型不模拟地下水头或含水层分布，只描述补给延后排出
的时间结构，采用 WBM 启发的单线性水库。记月长为 `Δ`，退水时间尺度
为 `τ`，`a = exp(−Δ/τ)`，`c = τ(1−a)/Δ`，当月补给为 `G_m = fW_m`，
则月末储量与当月基流为

```
S_m = a·S_(m−1) + c·G_m
B_m = S_(m−1) + G_m − S_m
stream_m = (1−f)·W_m + B_m
```

实现以解析周期稳态初始化储量，因此十二月基流之和等于十二月补给
之和，快速流加基流的年总量严格等于输入产流。随后再把十二个月
归一成份额并乘回 pack 的 Turc–Pike 年径流，所以基流只改变年内分配，
不改变已经验收的年河网。桶全年不产流时没有可进入水库的补给，形状
仍回退到逐月正水分盈余 `(P − PET)+`；连正盈余也没有时十二个月均分，
表示缺少季节信息，而不是独立观测。

中央参数取 `f = 0.5`、`τ = 40 d`，与 Grogan et al. (2022) 的 WBM
默认值一致。它们是经验分配参数，不是跨世界普适常数。主验收窗的
两轮敏感性实验覆盖 `f = 0.25/0.75` 与 `τ = 10/200 d`：中央情景的
常流河段长度占 97.0%，Cfb 区占 84.5%；全部角点的整体常流长度包络
为 94.9–98.0%，Cfb 包络为 71.5–90.9%。这些数字说明情相仍有参数
不确定性，不能宣称已经在本世界校准。

**产品只分两类。** 某河道格十二个月都高于活动门槛时为常流，否则为
非常流；相邻同类格组成河段，每个河段独立平滑和输出，不再让整条
河链被单个最干格降级。链末追加的汇合格、湖岸格和干床续走格继承
最后真实河道格的情相，不制造额外出口河段。月气候学不能可靠区分
持续数日的暴雨事件与季节性断流，因此不把非常流进一步拆成严格的
间歇河和暂时河。湖面仍采用年平衡水位，本机制不模拟逐月岸线消长。
输出 `rivers.regime.npy` 按河段记录 0（常流）或 1（非常流）；世界缺
月度气候或 pack 缺年径流通道时不写该文件，渲染全部回退为实线。

### 后续方向（登记）

- **河道传输损失**：「越流越少、中途消失于荒漠」需要沿程蒸渗损失项
  （Landlab `FlowAccumulator` 允许负权重，是现成机制先例；干旱区
  河道传输损失实测均值约 46%，Okavango 型内陆三角洲蒸发掉入流的
  96–98%）。
- **月度度日雪模块**：桶 v1 明文把所有降水按液态处理，冬季降水
  提前成冬季流量、缺春汛；McCabe & Markstrom (2007) 的月水量平衡
  模型带概念雪库（月均温定雨雪比例，度日律融雪，度日因子雪面
  1.6–6.0 mm/°C/d，雨雪分区约在干球 +1 °C 附近的过渡带），月分辨率
  对河流情相分类足够（Haines et al. 1988 的全球情相分类即用月流量）。

## 参考

- Barnes, R., Lehman, C., & Mulla, D. (2014). Priority-flood: An optimal
  depression-filling and watershed-labeling algorithm for digital elevation
  models. *Computers & Geosciences*, 62, 117–127.
- O'Callaghan, J. F., & Mark, D. M. (1984). The extraction of drainage networks
  from digital elevation data. *Computer Vision, Graphics, and Image Processing*,
  28(3), 323–344.（D8 流向）
- Manabe, S. (1969). The atmospheric circulation and the hydrology of the
  Earth's surface. *Monthly Weather Review*, 97(12), 739–774.（§7 土壤桶）
- Hamon, W. R. (1961). Estimating potential evapotranspiration. *Proc. ASCE,
  Journal of the Hydraulics Division*, 87(HY3), 107–120.（§7 蒸散需求）
- Pike, J. G. (1964). The estimation of annual run-off from meteorological
  data in a tropical climate. *Journal of Hydrology*, 2(2), 116–123.
  （§7 Turc–Pike 旁证锚，n = 2）
- Jarihani, B., et al. (2015). Where does all the water go? Partitioning water
  in the 'Channel Country' of arid Australia. *Journal of Hydrology*,
  529, 751–769.（§7 传输损失量级）
- McCabe, G. J., & Markstrom, S. L. (2007). A monthly water-balance model
  driven by a graphical user interface. *USGS Open-File Report* 2007-1088.
  （§7 雪库方案）
- Haines, A. T., Finlayson, B. L., & McMahon, T. A. (1988). A global
  classification of river regimes. *Applied Geography*, 8(4), 255–272.
  （§7 月流量分辨率依据）
- Grogan, D. S., et al. (2022). WBM v.1.0.0. *Geoscientific Model
  Development*, 15, 7287–7323.（§7 快速流与浅层地下水线性水库结构、
  默认分配参数）https://gmd.copernicus.org/articles/15/7287/2022/
- Fritz, K. M., et al. (2020). Classifying streamflow duration: The
  scientific basis and an operational framework for method development.
  *Water*, 12(12), 3429.（§7 情相定义、无统一时长阈值与区域操作化
  判据）https://pmc.ncbi.nlm.nih.gov/articles/PMC7592706/
