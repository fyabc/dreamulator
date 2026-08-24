# 气候引擎验证指南

> 本文档描述如何下载真实地球观测数据，用于验证 dreamulator 气候引擎的输出精度。

---

## 目录

1. [概览](#1-概览)
2. [数据源清单](#2-数据源清单)
3. [下载与预处理](#3-下载与预处理)
4. [运行验证](#4-运行验证)
5. [验证指标说明](#5-验证指标说明)
6. [已知限制](#6-已知限制)
7. [验证策略：多线证据与反过拟合](#7-验证策略多线证据与反过拟合)

---

## 1. 概览

验证流程对比三个维度的模拟结果与真实观测：

```
真实地球 DEM (ETOPO1)
       │
       ▼
  气候引擎计算 → temperature, precipitation, Köppen
       │
       ▼
  对比观测数据 → RMSE, R², 匹配率
```

**快速验证**（无需下载额外数据）：仅使用 zonal mean 参考值（已内嵌在 `validate_climate.py` 中）。

**完整验证**（需下载数据）：逐 cell 对比 Beck et al. (2018) Köppen 观测图。

---

## 2. 数据源清单

### 2.1 地形数据（引擎输入）

| 数据 | 来源 | 格式 | 大小 | 分辨率 |
|------|------|------|------|--------|
| **ETOPO1** | [NOAA NGDC](https://www.ngdc.noaa.gov/mgg/global/) | NetCDF (.grd.gz) | ~400 MB | 1 arc-min (~1.8 km) |

**下载方式**：自动（`import_earth_elevation.py` 从 NOAA 直接下载）。

### 2.2 参考气候数据（验证目标）

| 数据 | 来源 | 格式 | 大小 | 分辨率 | 用途 |
|------|------|------|------|--------|------|
| **ERA5 月均温** | [Copernicus CDS](https://cds.climate.copernicus.eu/) | NetCDF | ~5 GB | 0.25° | 温度验证 |
| **GPCP v2.3** | [NOAA PSL](https://psl.noaa.gov/data/gridded/data.gpcp.html) | NetCDF | ~3 MB | 2.5° | 降水验证 |
| **Beck et al. 2018 Köppen** | [figshare](https://doi.org/10.1038/sdata.2018.214) | GeoTIFF | ~10 MB | 5 arc-min | 气候分类验证 |

> **快速模式**：温度/降水的 zonal mean 参考值已硬编码在 `validate_climate.py` 中，
> 无需下载上述数据即可运行快速验证。仅 Köppen 完整验证需要下载 Beck 2018 数据。

### 2.3 数据许可证

| 数据 | 许可证 |
|------|--------|
| ETOPO1 | Public domain (NOAA) |
| ERA5 | Copernicus License (free for non-commercial research) |
| GPCP v2.3 | Public domain (NOAA) |
| Beck et al. 2018 | CC BY 4.0 |

---

## 3. 下载与预处理

> 操作步骤已移至 [../usage/validation-workflow.md](../../usage/validation-workflow.md) §1–4。

---

## 4. 运行验证

> 操作步骤已移至 [../usage/validation-workflow.md](../../usage/validation-workflow.md) §5。

---

## 5. 验证指标说明

### 5.1 温度

| 指标 | 含义 | 阈值 | 理想值 |
|------|------|------|--------|
| RMSE | zonal mean 的均方根误差 | < 5 °C | < 2 °C |
| Bias | 系统偏差（模型 - 观测） | — | 0 °C |
| R² | 空间相关性 | > 0.8 | > 0.95 |

### 5.2 降水

| 指标 | 含义 | 阈值 | 理想值 |
|------|------|------|--------|
| RMSE | zonal mean 的均方根误差 | < 800 mm/yr | < 300 mm/yr |
| Bias | 系统偏差 | — | 0 mm/yr |
| R² | 空间相关性 | > 0.6 | > 0.85 |

### 5.3 Köppen 分类

| 指标 | 含义 | 阈值 | 理想值 |
|------|------|------|--------|
| Match rate | 与 Beck 2018 的面积加权匹配率 | > 50% | > 75% |
| Group R² | 五大气候群（A-E）的面积相关性 | > 0.7 | > 0.95 |

### 5.4 常见问题与调优

| 现象 | 可能原因 | 调整方向 |
|------|---------|---------|
| 全球温度偏高 | 温室效应过强 | 降低 `greenhouse_warming_K` |
| 赤道-极地温差过大 | 环流弱 | 降低 `lat_gradient_c` |
| 降水在海岸线剧烈变化 | 水汽输送过短（湍流扩散 κ 不足） | 增大 `_MOISTURE_DIFFUSIVITY_M2S` |
| 沙漠面积过大 | 陆地蒸散偏低 + 降水不足 | 调整 `_LAND_EVAPOTRANSPIRATION_FRACTION` |
| 极地温度不够冷 | 反照率未考虑冰盖 | 调整纬度梯度 |

---

## 6. 已知限制

1. **zonal mean 参考值**：从 ERA5/GPCP 提取，分辨率为 2° 纬度带。无法捕获经度方向的误差。
2. **Köppen 完整验证**：需要额外下载 Beck et al. 2018 GeoTIFF，当前仅支持 zonal 对比。
3. **季节周期**：当前验证针对年均值，未逐月验证季节性。
4. **洋流**：当前未纳入定量验证（缺乏合适的格点化洋流观测数据集）。
5. **CVT 网格分辨率**：32K cell ≈ 200 km 间距，不足以分辨局地气候效应（如安第斯山脉的雨影）。
6. **单点校准风险**：§1–5 的全部验证仅针对现代地球——这在校准意义上充分，
   作为泛化验证不充分（见 §7）。

---

## 7. 验证策略：多线证据与反过拟合

> 来源：2026-08-03 验证方法论调研。结论：**现代地球是校准点，不是验证**。
> 业界用模型无法被观测直接证伪的状态（古气候、太阳系端元、理想化实验）
> 检验泛化能力。本节定义本引擎的分层验证计划。

### 7.1 为什么仅验证现代地球会过拟合

引擎的云/对流/水汽/热输送参数化全部在地球态（快自转、23.4° 倾角、N₂-O₂-H₂O
大气、太阳光谱）标定，而世界引擎必须覆盖的参数空间里地球是**非典型点**。
文献在案的失效模式：

- **慢自转云反馈**：Yang et al. (2013) 的次恒星点云稳定效应是高引也是高争议结论——
  THAI 四模型比对显示 GCM 在次恒星云量上严重分歧，根源是地球调优方案被推出
  标定域。本引擎无云物理，此项偏差方向由硬编码决定（见 climate-pipeline.md 3A.6）。
- **Earth-bias**（Rushby 2016 命名）：CO₂/H₂O 反馈被默认在不同光谱/自转/海洋
  几何下同样运作（Shields et al. 2016 综述 M 矮星宜居性问题）。
- **地转近似失效**：潮汐锁定 / 高倾角世界的 eyeball 态与昼夜梯度超出
  geostrophic 平衡适用范围。
- **相变盲区**：失控温室、CO₂ 大气坍塌、雪球态是不连续相变，温和现代态
  调出的模型会径直走过或放错位置。

### 7.2 业界四支柱

| 支柱 | 做法 | 检验对象 |
|---|---|---|
| **PMIP 古气候协议** | 中全新世 6 ka / LGM 21 ka / 末次间冰期 127 ka / 上新世暖期 / DeepMIP（PETM、EECO） | 隔离单一强迫 → **响应**对不对，而非均值态对不对 |
| **THAI / CUISINES 系外比对** | 多个 GCM 跑标准化 TRAPPIST-1e 用例（干/湿两档）；无观测 → 模型间一致 + 物理合理性 + 极限情形 | 独立代码间分歧 = 参数化伪影探测器 |
| **太阳系端元压测** | Venus（737 K / 92 bar）、Mars（CO₂ 坍塌）、faint-young-Sun、金星宜居史（Way et al. 2020） | 机制级证伪：已知参数复现已知终态 |
| **理想化 + 过程诊断** | Held-Suarez、aquaplanet（APE）、Taylor 图、Hadley 宽度 / ITCZ 位置、ECS 多线约束（Sherwood et al. 2020） | 动力与过程物理符合理论 |

### 7.3 本引擎分层验证计划

| Tier | 内容 | 状态 | 成本 |
|---|---|---|---|
| **T3 单调性 / 物理合理性**（先做） | 纯理论断言，零数据依赖（见 §7.4） | **已建** (7 tests: 5 pass + 3 xfail) | 最低 |
| **T2 太阳系端元复现**（性价比最高） | Venus / Mars / airless / nacrea HZ 断言（见 §7.5） | **已建** (4 tests) | 低 |
| **T1 现代地球**（现有） | §1–5 的 ETOPO1 / Beck / ERA5 / GPCP 流程 | **已建**（降级为"一条证据线"） | — |
| **T1 回归门**（新增） | nacrea 200k 基线快照 → CI 回归对比（见 §7.8） | **已建** (`tests/validation/test_regression.py`) | 中（~90s） |
| **T4 古气候体制检验** | LGM 型（低 CO₂）/ 始新世型（高 CO₂ 无冰）边界条件 → 核查**体制**而非数值；定量对比用 DeepMIP 代理库 | 规划中 | 中 |
| **T5 模型间比对 / JWST 仿真** | THAI 式比对需多个独立引擎 | 暂缓（单项目不现实） | 高 |

### 7.4 T3 单调性断言清单（设计）

不需要任何数据集，只需理论——捕获最严重的地球过拟合 bug：

- 全球均温随 `stellar_luminosity_sol`、`greenhouse_warming_K` 单调上升
- 冰-反照率反馈产生双稳态：光照低于阈值 → 雪球态（全球海洋封冻）
- 高倾角 → 极地增温、赤道降温（年均）
- 快自转 → Hadley 胞变窄（当前 30° 边界为硬编码，此项待 3A.6 行星化后方可断言）
- 无大气极限：`greenhouse_warming_K=0` 时 T_surf → T_eq（黑体）
- 日照相同的快/慢自转世界：慢自转经向温度梯度更弱

实现形态：`tests/validation/test_physical_plausibility.py`（小网格 n=144 快速跑），
可进 CI（已集成）。共 7 个测试：5 pass（光照/温室/反照率单调性、无大气极限、
倾角季节性振幅）+ 3 xfail（冰-反照率双稳态、高倾角极地增温、Hadley 宽度自转依赖待后续实现）。

### 7.5 T2 端元复现（设计）

对 EBM 级引擎，这是**最有效的单一泛化检验**——恰好覆盖奇幻世界会触及的
光度/气压/温室极端：

| 端元 | 输入参数 | 断言 | 状态 |
|---|---|---|---|
| Venus | L=1.0, d=0.723 AU, albedo=0.75, p=92 bar, GHG≈500 K | T_min > 300 K；全 cell > 50°C | ✅ `tests/validation/test_end_members.py` |
| Mars | L=1.0, d=1.524 AU, albedo=0.25, p=0.006 bar, GHG≈3 K | T_mean < −40°C；无 Af/Aw/Cfa/Cfb 类 | ✅ 同上 |
| 无大气裸岩 | GHG=0, albedo=0.1 | T_land_mean ≈ T_eq（误差 < 25°C） | ✅ 同上 |
| nacrea HZ 中心 | L=0.0357, d=0.2795, GHG=78 K | T_mean > 0°C；T_max > 15°C；液态水体制存在；EF < 50% 陆地 | ✅ 同上 |

### 7.6 替代数据（T4 及后续）

- **古气候代用指标**：叶缘分析 / CLAMP（年均温）、δ¹⁸O、TEX₈₆ 海温、冰川地质；
  Judd et al. (2024, *Science*) 的 485 Myr 地表温度综合；DeepMIP 代理数据库
  （结构化模型-数据对比目标）。
- **深时体制检验**（查体制不查数值）：雪球地球（须产生全球冰封）、PETM（+5–9°C
   transient）、白垩纪温室（无冰极地）。
- **太阳系实测**：Venus / Mars / Titan 表面测量作为端元真值。
- **JWST 新兴观测**（首批系外气候边界条件）：TRAPPIST-1b 昼侧 ~500 K ≈ 无大气
  裸岩（Greene et al. 2023）、1c 排除厚 CO₂（2023）、内行星热再分配弱
  （Ducrot et al. 2024；Gillon et al. 2025 首批热相曲线）。

### 7.7 首个实现 PR

`tests/validation/`：T3 单调性断言 + T2 Venus/Mars 复现（§7.4/§7.5）。
纯 Python 属性测试，与性能基准套件（perf plan §三）同期搭建，进 CI 门。

### 7.8 T1 回归门（nacrea 200k 基线）

**目标**：每次气候引擎代码变更后，在 nacrea 200k 数据集上重新运行气候模拟，
与提交的基线快照对比全局指标——防止无意中的精度退化。

**基线快照**：`tests/validation/baselines/nacrea-200k.json`（schema v1）。
包含温度均值、降水均值、Köppen 分类分布、陆地占比。使用以下命令生成/更新：

```bash
uv run python tests/validation/baselines/generate_baseline.py nacrea \
    --planet satellite_nacrea
```

**回归测试**：`tests/validation/test_regression.py`（`@pytest.mark.slow`）。
加载提交的 200k CVT mesh，运行气候模拟，逐项对比基线指标。各指标容差：

- 全球均温：±2.0°C
- 陆地/海洋均温：±3.0 / ±2.0°C
- 全球/陆地降水：±200 mm/yr
- Köppen 组分布：±8 pp
- 陆地占比：±2%（绝对）

**运行**：`pytest tests/validation/test_regression.py -m slow`

**CI 集成**：默认 CI 跳过 slow 测试（`pyproject.toml` 中 addopts 排除 `slow`）。
回归门在代码评审阶段由开发者手动运行，或通过独立的 `slow` CI job 触发。

### 7.9 泛化得分（分层复合 + 并列报告）

> 来源：2026-08-21 讨论。把「现代地球准确率」扩成「多线并列的泛化得分」，防止
> 单一地球基准过拟合。用户提出的「加权求和」在此落地，但拆成**三层并列**而非
> 扁平加权——因为非地球数据的形态不同（定量网格 vs 体制/单点），不能直接加权成
> 一个「准确率」。

**数据形态二分**（为什么不能扁平加权求和）：

| 形态 | 数据集 | 能算什么 |
|---|---|---|
| **定量网格级**（有逐 cell 参考场） | 现代地球（Beck/ERA5/GPCP）+ 古地球 LGM（CHELSA-TraCE21k） | % 准确率（同单位，可加权） |
| **体制/单点级**（仅若干数值或有无断言） | 金星 737K/92bar、火星 ~210K、泰坦 94K、TRAPPIST-1b/c 亮温 | pass/fail 比例（非 %） |

**分层复合评分**（三列并列 + 一个汇总）：

```
① 定量气候准确率 = w1·现代Köppen + w2·现代T + w3·现代P + w4·LGM T/P   （同单位）
② 体制合规率     = 端元断言通过数 / 总断言数                          （T2 扩展）
③ 物理单调性     = T3 测试通过率                                      （已建）

复合「泛化得分」只作汇总展示；防过拟合价值在「并列看差异」，不在单一数字。
```

**纪律（关键）**：**只在现代地球上校准**；泛化得分与各并列列是**只读体检**，不进
目标函数。若对着加权和调参，等于把过拟合从「地球一点」摊到「几个点」——还是过拟合。
并列列无法被调权重糊弄，合成数可以。

**数据获取渠道**（已确认可得，按性价比排序）：

| 数据 | 可得性 | 用途 | 备注 |
|---|---|---|---|
| **CHELSA-TraCE21k**（LGM→现代，1km 月度 T/P） | ✅ CC BY 2.0，全量 3.8TB，可只取 21ka 单时间片 + 降采样 | 最高价值：同一颗行星的「冷体制」定量网格 | ⚠️ CCSM3 降尺度产物，非纯观测 |
| MARGO（LGM 海温）/ BIOME6000（花粉→群系） | ✅ 纯观测 | 古气候纯观测补充（稀疏） | §7.6 已列 |
| 泰坦（94K、甲烷循环） | ✅ 可加端元断言 | T2 扩展 | — |
| TRAPPIST-1b/c | ✅ JWST 已发表 | 单点亮温断言（无大气→裸岩平衡温） | §7.6 已列 |

**落地顺序**：① 下载 LGM 单时间片 T/P，重采样到 CVT mesh（复用 `convert_koppen_map.py`
采样模式），生成 `lgm_obs.json`；② `validate_climate.py` 加「LGM 准确率」列与地球并列；
③ 补 Titan + TRAPPIST 断言进 `test_end_members.py`；④ 汇总成三列并列报告
（`climate validate --generalize`）。

**与「同物理 / 第一性」原则的呼应**：泛化得分正是「同物理」的可测量形态——引擎对
Earth（三圈环流）、LGM（冷体制）、金星/火星（极端端元）、nacrea（单圈环流）用**同一套
代码路径**，泛化得分衡量的是这套路径在离开地球标定域后还剩多少正确性。

---

## 参考资料

- ETOPO1: Amante, C. & Eakins, B.W. (2009). *ETOPO1 1 Arc-Minute Global Relief Model*. NOAA.
  https://www.ngdc.noaa.gov/mgg/global/
- ERA5: Hersbach, H. et al. (2020). The ERA5 global reanalysis. *Q. J. R. Meteorol. Soc.*
  https://doi.org/10.1002/qj.3803
- GPCP: Adler, R.F. et al. (2016). Global Precipitation Climatology Project.
  https://doi.org/10.1175/1520-0493(2003)131<0296:TVGPCP>2.0.CO;2
- Beck, H.E. et al. (2018). Present and future Köppen-Geiger climate classification maps.
  *Scientific Data*, 5, 180214. https://doi.org/10.1038/sdata.2018.214

**验证策略（§7 来源）**

- PMIP4/CMIP6 古气候协议: Kageyama, M. et al. (2018). *GMD* 11, 1033. https://gmd.copernicus.org/articles/11/1033/2018/ · https://pmip.lsce.ipsl.fr/ · DeepMIP: https://www.deepmip.org/
- THAI 系外行星模式比对: Fauchez, T. et al. (2020). *GMD* 13, 707. https://gmd.copernicus.org/articles/13/707/2020/ · Turbet, M. et al. (2022). *PSJ*. https://iopscience.iop.org/article/10.3847/PSJ/ac6cf1 · Sergeev, D. et al. (2022). *PSJ*. https://iopscience.iop.org/article/10.3847/PSJ/ac6cf2 · CUISINES: https://iopscience.iop.org/collections/2632-3338_CUISINES
- 太阳系端元: Kasting, J. (1988). *Icarus* 74. https://www.sciencedirect.com/science/article/pii/0019103588901169 · Caldeira, K. & Kasting, J. (1992). *Nature* 360, 721. · Forget, F. & Pierrehumbert, R. (1997). *Science*. https://www-mars.lmd.jussieu.fr/mars/publi/science97.pdf · Ramirez, R. et al. (2014). *Nature Geoscience*. · Way, M. et al. (2020). Venusian climates. https://arxiv.org/abs/2003.05704
- Faint young Sun: Feulner, G. (2012). *Rev. Geophys.* https://courses.seas.harvard.edu/climate/eli/Courses/EPS281r/Sources/Faint-young-sun-paradox/more/Feulner-2012-review.pdf
- 慢自转云反馈: Yang, J., Cowan, N. & Abbot, D. (2013). *ApJL* 771, L45. https://iopscience.iop.org/article/10.1088/2041-8205/771/2/L45/pdf · Earth-bias: Rushby, A. (2016). https://ueaeprints.uea.ac.uk/58503/ · M 矮星宜居性: Shields, A. et al. (2016). https://ar5iv.labs.arxiv.org/html/1610.05765
- 理想化实验与诊断: Held, I. & Suarez, M. (1994). *BAMS*. https://journals.ametsoc.org/view/journals/bams/75/10/1520-0477_1994_075_1825_apftio_2_0_co_2.xml · Thatcher & Jablonowski (2016, moist aquaplanet). https://gmd.copernicus.org/articles/9/1263/2016/ · Taylor diagrams: https://climatedataguide.ucar.edu/climate-tools/taylor-diagrams · ECS 多线约束: Sherwood, S. et al. (2020). *Rev. Geophys.* https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2019rg000678 · Hadley/ITCZ: Watt-Meyer & Frierson (2019). https://journals.ametsoc.org/view/journals/clim/32/4/jcli-d-18-0434.1.xml
- 古气候代用指标: Royer, D. (2012, 叶缘分析综述). https://droyer.wescreates.wesleyan.edu/Royer_2012_PSP18_leaf-climate_review.pdf · CLAMP. https://palaeo-electronica.org/2006_2/clamp/clamp.pdf · Judd, E. et al. (2024, 485 Myr 温度史). *Science*. https://www.jessicatierneyclimate.com/s/Judd2024Science.pdf · DeepMIP 代理库: Lunt, D. et al. (2019). https://gmd.copernicus.org/articles/12/3149/2019/
- JWST 系外气候观测: Greene, T. et al. (2023, TRAPPIST-1b). *Nature*. https://www.nature.com/articles/s41586-023-05951-7 · TRAPPIST-1c 排除厚 CO₂. *Nature*. https://www.nature.com/articles/s41586-023-06232-z · Ducrot, E. et al. (2024). https://arxiv.org/abs/2412.11627 · Gillon, M. et al. (2025, 首批热相曲线). https://arxiv.org/abs/2509.02128
