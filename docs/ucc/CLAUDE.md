# 统一气候描述（UCC）文档目录

跨世界统一气候分类的单一主题目录。UCC 用「连续描述量 → 版本化分类 profile」两层
结构替代「给每个地点贴一个 Köppen 式字母码」，目标是让用户在任意世界的地图上读到
一致、可解释的气候描述。2026-09-24 文档收拢：原本分散在 `knowledge/climatology/`、
`design/proposals/`、两个世界的 `design-notes/` 与 `private/reviews/` 的 UCC 文档
统一迁入本目录。

## 文档列表

### 根目录

- `specification.md` — **主文档（规格书）**：为什么不以 Köppen 为统一标准、时间基准
  契约、连续描述量（t_*/p_*/ai/deficit/concentration + 五种部分有效状态）、Hamon-1961
  参考需求模型声明与有效域（冻结线规则）、分类 profile v1（热量 4 节点 × AI 4 档 +
  continental/water_stress 修饰语 + 简码）、L2 实验冻结依据、范围限制、canonical
  合成序列反例对、迁移语义演练表。
- `design-anchors.md` — 2026-09-14 设计提案的保留部分：设计原则（物理第一性 /
  方案与档案分离 / 时间序列优先 / 可扩展性）、锚点体系（溶剂相窗 θ、能量-水分 AI、
  世界统计分位数、周期性、环流体制、锁定行星空间、海拔气压）——**UCC v2 候选轴的
  设计基础**、已否证方向（防重试）、混合溶剂世界附录（草案七转正的物性参照）。

### `examples/` — worked examples（真实数据例证，脚本可重生成）

| 文件 | 世界 | 数据源 | 生成脚本 |
|---|---|---|---|
| `earth.md` | Earth（观测） | NCEP/GPCP/Beck | `scripts/climate/ucc_examples_earth.py` |
| `mars.md` | Mars | MOLA + MCD v6.1（L4） | `scripts/solar/ucc_examples_solar.py --planet mars` |
| `moon.md` | Moon | LDEM + Diviner GCP（观测态例外） | `--planet moon` |
| `venus.md` | Venus | Magellan + VCD v2.3（L4） | `--planet venus` |
| `titan.md` | Titan | TAM 水文 run（L4，CC-BY） | `--planet titan` |
| `nacrea.md` | Nacrea（架空世界） | 引擎构建产物 | `scripts/climate/ucc_examples_nacrea.py` |

前五个是 `earth` root 的额外 planet_ids（现实世界数据锚，永不 build）；`nacrea.md`
是架空世界侧的迁移语义夹具（原 nacrea `design-notes/0010`，该处保留 stub 占位）。

### `research/` — 评审与研究记录

- `ucc-review-2026-09-17.md` — 专项评审与重设计正文（描述量 + 版本化 profile 路线的
  裁决依据；UCC-01 四步路线的源头）。
- `ucc-l2-classify-2026-09-20.md` — L2 分类候选比较实验（profile v0/v1 冻结依据）。
- `ucc-body-climate-taxonomy-2026-09-21.md` — 天体气候划分文献调研（806 行，~85 条
  文献带核实等级；v2 候选轴的证据分级来源）。
- `ucc-time-basis-duality-2026-09-21.md` — 时间基准二元性裁决（二元性在阈值语义与
  用途，不在时间基准；物理家族 profile 而非 per-body）。

调研脚本与数据集留痕仍在 `private/reviews/ucc-*.{py,json,msgpack}` 与
`private/reviews/_research/ucc-taxonomy-*.md`（未入库）。

## 实现入口

| 实现 | 位置 |
|---|---|
| 描述量 + 分类 profile | `src/dreamulator/map/ucc.py`（`compute_descriptors()` / `classify_v0()` / `classify_v1()`） |
| 导出格式 | `src/dreamulator/map/export.py` → `maps/<planet_id>/climate_yearly.msgpack` |
| 时间约定 | `src/dreamulator/result_contract.py`（`REFERENCE_MONTH_DAYS` / `result_metadata()`） |
| 前端呈现 | `frontend/src/components/map/MapCellInspector.tsx`（气候描述区，「实验功能」开关门控） |
| 管线技术参考 | `docs/design/pipelines/climate-pipeline.md`（climate_yearly.msgpack 一节） |

## 状态与路线

UCC-01（描述量 + L0/L1 测试 + climate_yearly 浏览 + L2 比较 + profile v0/v1 冻结 +
知识文档 + 前端染色简码 + earth 观测派生 + 太阳系四天体 + nacrea 迁移夹具）**全线完成**。
v2 候选（登记不排期）以 `private/plans/ucc-01-plan.md` 的「v2 候选」节为单一事实源：
热侧域门（Venus Ra-w→Rn）、世界级气候态前缀、高度-气压修饰语 -H、跨溶剂广义 AI、
光照 regime、季节性与字母表改造等——轴设计的物理基础见 `design-anchors.md` §3。

## 写作原则

沿用 `docs/design/CLAUDE.md` 的设计决策硬门槛（物理第一性 / 地球真实参考 / 业界成熟
方案三者至少其一）与 `docs/knowledge/CLAUDE.md` 的知识积累准则（必须附参考来源、
严禁幻觉）。本目录文档只写当前设定，不写历史（历史由 git 管理）。
