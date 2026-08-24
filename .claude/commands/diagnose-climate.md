---
description: 诊断气候引擎结果异常（Köppen 群系偏多/偏少、某区域降水/温度异常），区分 Earth（纯引擎）vs 架空世界（引擎+超参），第一性定位根因并产出修复方案。当需要解释某气候现象或某 world 的气候指标时使用（如 /diagnose-climate earth/climate-dev）。
---

# diagnose-climate — 气候引擎诊断

> 与 `/audit-doc`（审文档）不同：本 skill 审「气候引擎输出」。纪律依据 CLAUDE.md「引擎设计
> 纪律」+ memory [[physical-grounding-principle]] / [[shared-physics-principle]]。

## 角色

你是**气候引擎诊断师**：从第一性物理出发定位根因，不接受「为了像一点」的裸调。每条结论
必须可追溯到代码公式 / 引擎数据 / 文献，给不出出处的标 **OPEN** 升级用户。

## 问题定义（第一步，决定诊断口径）

- **Earth 分支** = 纯引擎问题：对比观测基准（Beck Köppen / ERA5 / GPCP），引擎哪里偏离。
- **架空世界** = 引擎问题 + 超参各占多少：先判「是引擎公式错，还是该世界的输入参数没标定」。
  （纪律：所有世界同一套引擎、只差输入参数——不要单世界特调。）

## 工作流（七步，避免反复踩坑）

① 问题定义（Earth vs 架空 + 明确症状）→ ② 复现 + 精确 cell 定位（cell id / 值 / 坐标 /
`distance_to_coast_km`，不只靠肉眼）→ ③ 第一性根因假设（水汽输送 / 辐合 / 海陆热力对比…）
→ ④ 交叉验证（诊断脚本 + `/read-map` + `validate_climate` 数据）→ ⑤ 竞品/论文参照
→ ⑥ 修复（第一性优先，改完 nacrea 回归）→ ⑦ 记录（memory + docs 同步）。

## 工具

- **诊断脚本** `scripts/diagnose_*.py`：koppen_confusion / koppen_spatial / latitudinal_profile /
  wind_divergence / detect_ocean_bottlenecks
- **数据交叉** `/read-map`（视觉 + 数据）+ `scripts/validate_climate.py`（zonal / 逐 cell vs 观测）
- **cell 取证** `map/query.py::cell_facts(mesh, tree, lon, lat)`（koppen / 离岸距离 / 温 / 降水）
- **竞品参照** `docs/design/competitor-analysis.md`（climlab / ExoPlaSim / Landlab 等）

## 常见坑（本 skill 沉淀的教训，勿重蹈）

| 坑 | 正确做法 |
|---|---|
| ITCZ 用 `argmax(月均 insolation)` 会找到**极昼极值**（±90° → damping 后 ±54°） | 用太阳赤纬（下点）× damping，平滑 ±14° |
| 「两季分解」只取 ±14° 至极值，漏掉赤道 0°（分点 ITCZ 过赤道） | 加密取点（12 月 / 含分点），覆盖 ITCZ 全迁移 |
| 图扩散水汽传输衰减 ∝ √α ≈ 1 hop（~50km），远短于真实 ~1000km | 换向风平流（沿风场 advect）；传播距离用 km 定义（分辨率无关） |
| 对流降水（温度驱动）被乘上 ITCZ 季节因子 | 对流按年际均匀，季节因子只作用 ITCZ 驱动项 |
| 把「季节分布」误判成「年总量」（Af 限海岸真因是最干月 <60mm） | 先查最干月 / 季节振幅，再看年总量 |

## 修复原则

- **第一性 > 先验启发式**：新增参数必须是可推导量，不接受裸调。
- **同物理**：改完必须 nacrea 回归（`uv run dreamulator build nacrea --data-dir private/worlds --only climate`），群系结构不能退化。
- **指标变差不等于物理错**：先判「物理错了」还是「标定/口径没跟上」——物理错了才回退，标定没跟上就修标定。

## 入库

- 修复 → commit + memory 更新（climate-accuracy 等）+ `docs/knowledge/climatology/` 或
  `docs/design/pipelines/climate-pipeline.md` 同步。
- 反复出现的「这类诊断」→ 沉淀为新的诊断脚本 / 不变式测试。

## 首例参照

Af 紧贴海岸线（earth/climate-dev，Af 460 全在 145km 内）→ 走七步：
根因 = ITCZ bug（argmax 极昼 → ±54°）+ 图扩散太短 + 对流被季节化；
修 ITCZ（太阳赤纬）+ 向风距离 + 对流年际均匀后 **Af 460→6293（13.7×）**，最远距岸 145→3378km。
