# 文明引擎实现架构

> 本文档描述 dreamulator 文明引擎（CivilizationEngine）的计算方式：宜居海岸与
> 农业核心区分类、宜居/农业评分（含湖滨淡水修正）、文明摇篮候选区发现、
> 星空文化（sky culture）钩子的校验与派生，以及输出格式。
> 对应源码：`src/dreamulator/engine/civilization.py`（引擎封装）、
> `engine/habitability.py`（评分纯函数）、`engine/seed_discovery.py`
>（摇篮候选发现）、`engine/sky_culture.py`（星空文化纯函数）与
> `models/sky_culture.py`（数据模型）。
> 知识背景见 [knowledge/sociology/human_settlement.md](../../knowledge/sociology/human_settlement.md)。

---

## 1. 在 DAG 中的位置与数据流

CivilizationEngine 声明 `requires = ["ecology", "climate", "geological"]`，是
DAG 的最后一环。它加载三层数据齐全的 CVT 网格（温度、降水、最热月温、
距海距离来自气候层，`soil_fertility` 来自生态层），逐格计算文明字段后写回
网格，输出 `layers/civilization/derived/habitability_summary.yaml` 与
`civilization_seed_candidates.yaml`。

本引擎是气候/生态与 Phase 3C 半结构化文明模型之间的薄桥：只产出两个逐格
陆地适宜性图层（`habitable_coast` / `agricultural_core`）与连续评分
（`habitability_score` / `agriculture_score`），供 `civilizations.yaml` 锚定。
引擎同时承载星空文化钩子（§6）——与网格无关的纯设定数据，走独立的
加载/校验/派生路径。

## 2. 海陆判据与湖面语义

海陆判据与生态引擎同源：`resolve_land_mask`（`water_bodies.py`，优先
`water_class`、旧网格回退连通性），不用裸海拔符号、不用 `crust_type`。
湖泊格（`is_lake=True`）按水面处理：`habitability_score = 0`、
`agriculture_score = 0`、`habitable_coast = False`、`agricultural_core =
False`——湖面上无人定居也无农业，适宜性落在湖滨陆地而非湖面本身。

## 3. 分类与评分（habitability.py 纯函数）

四个纯函数均接收 `is_ocean` 短路参数（湖面格以 `is_ocean=True` 传入）：

- **classify_habitable_coast** — 布尔分类：陆地格且年均温 >0 °C（永冻以下
  不宜定居）、年降水 >500 mm（雨养定居的水分下限）、距海 ≤200 km（沿海
  门槛，取人类聚落分布的宽松截断）。三个阈值常量为 `T_MIN_C`、`P_MIN_MM`、
  `COAST_THRESHOLD_KM`。
- **classify_agricultural_core** — 布尔分类：陆地格且最热月温 >10 °C
  （Köppen 树线 `TREE_LINE_C`，10 °C 暖月等温线是作物/森林气候与极地气候的
  标准分界）。保留「法罗群岛式可居不可耕」的区分。
- **habitability_score** — 连续 0–100 评分：`f_T`（人类气候生态位不对称
  带，峰值约 13 °C 年均温，冷侧陡峭热侧平缓——Xu et al. 2020）乘 `f_P`
  （`min(1, P/500mm)` 干旱爬坡）。沿海可达性刻意不是因子：那是经济/贸易
  优势（描述人口在何处集中），由 `distance_to_coast_km` 单独承载。
- **agriculture_score** — 连续 0–100 评分：最热月温 ≤10 °C 硬零，之上为
  f_thermal（月分辨 GDD 代理，基数 10 °C）× f_water（仅降水的干旱代理）×
  f_soil（USDA 土纲肥力权重）。

### 湖滨淡水修正（2026-10 加入）

`habitability_score` 增加第四个输入 `near_freshwater`：与任一湖泊格相邻的
陆地格，评分乘 `FRESHWATER_BONUS`（1.15，封顶 100）。引擎侧由
`_compute_near_freshwater`（`civilization.py`）预计算逐格邻湖标志。

该修正的认识论类别是**观测拟合**而非第一性推导：地球湖滨人口密度优势
（五大湖、维多利亚湖沿岸）是经验事实，换算成 15% 乘数是标定选择，标定域为
类地行星。它补的洞是小湖（`water_class=land`）不产生海岸线——气候层的
距海 BFS 以海陆掩膜为种子，内陆小湖不在种子集，其湖岸没有沿海信号；大
内陆海（`water_class=ocean`，里海语义）沿岸已有 coastal 语义，淡水修正
在其上叠加无害（同一乘数，从简不区分）。

## 4. 文明摇篮候选（seed_discovery.py）

`discover_seed_candidates` 在农业核心区布尔场上做连通域标记
（`label_agricultural_regions`，最小 20 格 ≈ 5×10⁴ km² 才够支撑一个摇篮），
对每个区域聚合特征（面积、平均 NPP、土壤肥力权重、群系组成），按
`cradle_score`（面积 × 生产力 × 肥力的几何组合）排序输出候选清单。确定性
算法，无 RNG。种子候选仅供 `civilizations.yaml` 作者锚定参考，不自动生成
文明实体。

## 5. 输出

- **网格字段**（写回 cvt_mesh，经 `DYNAMIC_CELL_FIELDS` 导出）：
  `habitable_coast`、`agricultural_core`、`habitability_score`、
  `agriculture_score`。
- **habitability_summary.yaml**：陆地格的六个计数桶（overlap /
  habitable_not_agricultural / agricultural_not_habitable / neither 及两个
  总数）、评分统计、摇篮候选数量。湖面与海洋格不进计数（summary 只覆盖
  陆地格）。
- **civilization_seed_candidates.yaml**：候选区域清单（排名、特征、评分）。
- **sky_culture.yaml**：校验后的星空文化（§6）；成功构建总是写出（无作者
  输入时 `cultures: []`），失败构建不发布任何 derived。

## 6. 星空文化（sky culture 钩子）

文明层对天文层背景天球目录（`sky_background.yaml`）的消费接口，实现的是
`models/sky_background.py` 设计时预留的两个跨层消费方之一（Stellarium 星空
文化范式）：文化给背景星起专名、把星连成星官图形，**引用一律走稳定 id、
永不复制坐标**——星的位置只住在天文层目录里，移动恒星不需要改任何文化
文件。另一个消费方（生态层的 `transient_events` 辐射强迫）仍为设计预留，
等待生态层的时序事件模型。

**输入**（可选，`layers/civilization/input/sky_culture.yaml`）：

```yaml
cultures:
  - id: culture_xiangxing        # 稳定 id；civilizations.yaml 实体就位后合并对齐
    name: "向星诸族（暂定）"
    description: "…"             # 可选
    star_names:                  # 背景星 id → 该文化的专名（可选）
      star_arrow_alpha: "出鞘"
    asterisms:
      - id: asterism_arrow       # 全局唯一（前端选择命名空间是扁平的）
        name: "箭"
        meaning: "…"             # 可选，详情面板展示
        lines:                   # Stellarium 式无序星对边表，支持分叉图形
          - [star_arrow_delta, star_arrow_gamma]
          - [star_arrow_beta, star_arrow_alpha]
```

**校验分两层**。结构问题由 Pydantic 校验器在加载时拒绝（`models/sky_culture.py`）：
空边表、自环边、文化 id 重复、星官 id 跨文化重复。跨文件引用完整性由
`validate_cultures`（`engine/sky_culture.py`）对照天文层目录检查：边表顶点与
`star_names` 键必须是**署名星或深空天体 id**——程序化暗星场 id（`bg_star_*`）
一律拒绝，因为改 starfield 的 seed/count 会静默重编号，陈旧引用会无声指向
另一颗星（语义漂移比断链更糟）。未知 id 使构建**硬失败**，错误消息一次列全；
天文目录完全不存在时降级为 warning（无法校验，引用原样通过）。目录经
`find_input` 的 derived 优先搜索读取（`_load_sky_catalogue`），fresh checkout
回退到 input 时现场派生。

**派生**（`derive_sky_culture`）只做规范化：无序边对去重（保留首现顺序）。
`SkyCultureDerived` 与输入同形，成功构建总是写出。

**消费**：API 端点 `GET /api/worlds/{world}/sky/culture`（读 civilization
derived，stat 校验缓存，与 `/sky/background` 同款式）；前端天球视图把 id
连到背景星表目录帧单位矢量上，沿大圆采样后经同一旋转/投影管线绘制（两种
视图模式都画，环视模式可悬停/点击选中，选中 id 与署名星/深空天体共用
`data-bg-id` 命名空间）。sky 页为 API-only，无静态导出镜像。操作说明见
[usage/sky-viewer.md](../../usage/sky-viewer.md)。
