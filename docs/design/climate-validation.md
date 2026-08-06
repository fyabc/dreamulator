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

> 操作步骤已移至 [../usage/validation-workflow.md](../usage/validation-workflow.md) §1–4。

---

## 4. 运行验证

> 操作步骤已移至 [../usage/validation-workflow.md](../usage/validation-workflow.md) §5。

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
| Match rate | 与 Beck 2018 的面积加权匹配率 | > 55% | > 75% |
| Group R² | 五大气候群（A-E）的面积相关性 | > 0.7 | > 0.95 |

### 5.4 常见问题与调优

| 现象 | 可能原因 | 调整方向 |
|------|---------|---------|
| 全球温度偏高 | 温室效应过强 | 降低 `greenhouse_warming_K` |
| 赤道-极地温差过大 | 环流弱 | 降低 `lat_gradient_c` |
| 降水在海岸线剧烈变化 | 水汽输送步数不足 | 增大 `_MOISTURE_ADVECTION_STEPS` |
| 沙漠面积过大 | 干旱阈值偏低 + 降水不足 | 调整 `orographic_efficiency` |
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
  标定域。本引擎无云物理，此项偏差方向由硬编码决定（见 climate-engine.md 3A.6）。
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
| **T3 单调性 / 物理合理性**（先做） | 纯理论断言，零数据依赖（见 §7.4） | 未建 | 最低 |
| **T2 太阳系端元复现**（性价比最高） | Venus / Mars 参数集 → 终态断言（见 §7.5） | 未建 | 低 |
| **T1 现代地球**（现有） | §1–5 的 ETOPO1 / Beck / ERA5 / GPCP 流程 | **已建**（降级为"一条证据线"） | — |
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

实现形态：`tests/validation/test_physical_plausibility.py` 纯 Python 属性测试
（小网格 n=4096 快速跑），可进 CI。

### 7.5 T2 端元复现（设计）

对 EBM 级引擎，这是**最有效的单一泛化检验**——恰好覆盖奇幻世界会触及的
光度/气压/温室极端：

| 端元 | 输入参数 | 断言 |
|---|---|---|
| Venus | L=1.0, d=0.723 AU, albedo=0.75, p=92 bar, GHG≈500 K | T_surf > 600 K；无液态水胞 |
| Mars | L=1.0, d=1.524 AU, albedo=0.25, p=0.006 bar, GHG≈3 K | 全球均温 < −40°C；无 Af/C 类 |
| gaia-m HZ 中心 | L=0.0357, d=0.2795, GHG=70 K | 温带体制存在（C 类 > 0）；非雪球 |
| 无大气裸岩（TRAPPIST-1b 型） | GHG=0 | 全球均温 ≈ T_eq（±2 K） |

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
