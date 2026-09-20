# Titan · UCC Worked Examples（ucc-v1）

> UCC-01 第四步 4d 产物。本文档由脚本生成，勿手改——重生成：
> `uv run python scripts/solar/ucc_examples_solar.py --planet titan`
> 生成日期：2026-09-21。描述量与分类语义见
> `docs/knowledge/climatology/ucc_climate_descriptors.md`（§8 有本天体的示意演练行，
> 本文档是它的真实数据对照）。
> **状态简写**：`OOD` = out_of_domain（需求模型超出有效域）；`MI` = missing_input、
> `NA` = not_applicable、`NPD` = no_positive_demand（语义见知识文档 §3）。

**数据源**（`data_source: gcm-climatology`——认知地位见文件内 provenance，随数据走）：
> - gcm: TAM coupled land-hydrology/atmosphere (Lora, Faulk, Mitchell & Milly 2019; Zenodo 10.5281/zenodo.3473571, CC-BY-4.0), run full_phys.hydro.k1e-5, years 241–250 (10 Titan years, 2029 windows)
> - temperature: TAM `tsurf` (K→°C), DT-weighted bin means; 12 Titan-year phase bins (896.4 Earth-days each)
> - precipitation: TAM `precip` (methane, kg/m²/s) integrated per bin → mm liquid CH₄ (ρ=422.6 kg/m³); p_total per Titan year (10756.5 Earth-days)
> - demand_model_note: NOT applied — Hamon is a liquid-water formula; a methane solvent at 94 K is out of scope (knowledge doc §6). AI/deficit = missing_input by declaration (the cold-side OOD gate would also fire).
> - seas: water_class=ocean where time-mean qsurf > 0.05 m (methane seas/lakes, 42 cells)
> - topography: TAM `dtd` runoff topography (~5.6° GCM grid; possibly datum-offset — relative relief only)
> - epistemic_status: L4 GCM climatology (ucc-review §6.2): a model, not error-free truth

**时间基准**：12 分箱 × 896.38 地球日 = 窗口 10756.5 日；
`month_0` = `titan_year_phase_0_arbitrary_anchor`。`p_total` 按此窗口报告；AI/deficit 为窗口不变量，可跨世界
直接比较（知识文档 §2）。

## 0. 本世界要点（手写注记，随脚本再生）

- **全行星 polar + 供需轴 MI**：tsurf 90.5–96.2 K（−183…−178 °C）→ 所有 cell 热量带 polar；AI/deficit = **missing_input**（demand_model=None 为显式声明——Hamon 是液态水经验式，94 K 甲烷溶剂超出其适用范围，知识文档 §6；这比先算 Hamon 再靠冷侧 OOD 门拦截是更强的拒绝）。陆地 Pn、甲烷海 Po；continental 0%（t_range ~1.6 K——厚大气抹平表面季节）。
- **时间契约极端案例**：bin = 896.4 地球日（Titan 年 = 土星轨道 29.46 年的 1/12）；p_total 按 Titan 年报告。相位锚 = 记录日数 mod Titan 年（表面季节振幅 ~1 K，相位选择为二级效应，已声明）。
- **甲烷降水**：全球均 ~360 mm 液态 CH₄/Titan 年（≈12 mm/地球年）；极地湖区达 ~1500 mm/Titan 年（≈50 mm/地球年，与文献海面蒸发量级一致）；降水强集中（C_TV ~0.63——单一季节箱占主导，TAM 的分点/至点风暴特征）。单位换算按液态甲烷密度 422.6 kg/m³，随文件元数据声明。
- **甲烷海 = 模型态**：qsurf 时均 > 0.05 m → ~1.4% cells。本 run 时段（y241–250）湖区集群偏南半球——Faulk 水文在土星年时标上迁移湖泊；观测名锚点（克拉肯/丽姬亚/安大略）在模型里可能是干地 cell，站点表如实记录（观测名锚点按最近 cell 取、不限海陆；另有两个模型湖区集群锚点）。

## 1. 全局分布（3000 cells；陆地 2958，非陆地 42）

**热量带（全部 cell）**：polar 3000、cold 0、temperate 0、tropical 0。

**修饰语**：continental 0.0%；water_stress 0.0%（陆地）。

**AI 状态（全部 cell）**：missing_input 3000。

**陆地主类组合**：

| 类 | cells | 占陆地 |
|----|-------|--------|
| Pn（polar/供需不适用） | 2958 | 100.0% |
| Cn（cold/供需不适用） | 0 | 0.0% |
| Tn（temperate/供需不适用） | 0 | 0.0% |
| Rn（tropical/供需不适用） | 0 | 0.0% |

**非陆地基码**：Po 42

## 2. 命名地点

| # | 地点 | 纬 | 经 | 高程 m | T均 | T范围 | P | AI | deficit | 类码 |
|---|------|----|----|--------|-----|-------|---|----|---------|------|
| 1 | 克拉肯海（观测名锚点） | 63.0 | -41.8 | 786 | -179.6 | 1.4 | 448 | MI | MI | **Pn** |
| 2 | 丽姬亚海（观测名锚点） | 80.6 | -45.0 | 698 | -179.7 | 1.7 | 562 | MI | MI | **Pn** |
| 3 | 安大略湖（观测名锚点） | -2.9 | -150.0 | 1376 | -178.0 | 0.6 | 13 | MI | MI | **Pn** |
| 4 | 北极甲烷湖区（模型 qsurf 集群） | 80.7 | 40.4 | 503 | -179.8 | 1.5 | 616 | MI | MI | **Po** |
| 5 | 南极甲烷湖区（模型 qsurf 集群） | -68.0 | 6.3 | 402 | -179.4 | 1.9 | 104 | MI | MI | **Po** |
| 6 | 香格里拉（赤道沙丘带） | -9.1 | -158.4 | 1198 | -178.1 | 0.9 | 11 | MI | MI | **Pn** |
| 7 | 阿鲁（Xanadu 亮区） | 8.1 | -99.0 | 1502 | -178.1 | 0.5 | 19 | MI | MI | **Pn** |
| 8 | 赤道区（0° 本初） | 0.0 | -0.9 | 1484 | -177.9 | 0.4 | 16 | MI | MI | **Pn** |
| 9 | Menrva 盆地 | 35.9 | -53.1 | 767 | -178.6 | 1.0 | 82 | MI | MI | **Pn** |
| 10 | 南极区 | -85.1 | 118.2 | 749 | -179.8 | 2.0 | 3785 | MI | MI | **Pn** |

### 1. 克拉肯海（观测名锚点）

- cell #160 · 陆地 · 高程 786 m
- 分箱均 T（°C）：-179.6 -179.8 -180.0 -180.1 -180.1 -180.0 -179.8 -179.4 -179.0 -178.8 -178.9 -179.3
- 分箱降水（mm/箱）：7.8 5.2 5.7 2.0 3.9 5.5 5.6 7.1 5.5 7.3 183.2 209.1
- 描述量：t_mean -179.6 · t_min -180.1 · t_max -178.8 · t_range 1.4 · 低于0°C份额 1.00 · P 448 mm/窗口 · AI MI · deficit MI · C_TV 0.71
- **分类（ucc-v1）**：polar / n/a（MI） · 简码 **Pn** · 修饰语：—

### 2. 丽姬亚海（观测名锚点）

- cell #16 · 陆地 · 高程 698 m
- 分箱均 T（°C）：-179.8 -180.1 -180.3 -180.3 -180.4 -180.4 -180.1 -179.6 -179.1 -178.7 -178.9 -179.4
- 分箱降水（mm/箱）：31.2 11.6 13.7 8.9 9.2 8.1 5.6 5.3 3.8 2.8 364.4 97.7
- 描述量：t_mean -179.7 · t_min -180.4 · t_max -178.7 · t_range 1.7 · 低于0°C份额 1.00 · P 562 mm/窗口 · AI MI · deficit MI · C_TV 0.66
- **分类（ucc-v1）**：polar / n/a（MI） · 简码 **Pn** · 修饰语：—

### 3. 安大略湖（观测名锚点）

- cell #1585 · 陆地 · 高程 1376 m
- 分箱均 T（°C）：-178.3 -178.0 -177.9 -178.0 -177.9 -177.9 -177.8 -177.7 -178.1 -178.3 -178.4 -178.4
- 分箱降水（mm/箱）：2.5 1.1 0.0 0.0 0.0 1.3 2.6 0.4 0.1 0.2 2.3 2.8
- 描述量：t_mean -178.0 · t_min -178.4 · t_max -177.7 · t_range 0.6 · 低于0°C份额 1.00 · P 13 mm/窗口 · AI MI · deficit MI · C_TV 0.44
- **分类（ucc-v1）**：polar / n/a（MI） · 简码 **Pn** · 修饰语：—

### 4. 北极甲烷湖区（模型 qsurf 集群）

- cell #18 · 海洋/海域 · 高程 503 m
- 分箱均 T（°C）：-179.8 -180.0 -180.2 -180.3 -180.4 -180.4 -180.1 -179.6 -179.2 -178.9 -179.0 -179.5
- 分箱降水（mm/箱）：23.4 9.7 11.3 9.5 10.7 9.7 6.6 4.9 2.5 4.2 346.9 176.2
- 描述量：t_mean -179.8 · t_min -180.4 · t_max -178.9 · t_range 1.5 · 低于0°C份额 1.00 · P 616 mm/窗口 · AI MI · deficit MI · C_TV 0.68
- **分类（ucc-v1）**：polar / n/a（非陆地） · 简码 **Po** · 修饰语：—

### 5. 南极甲烷湖区（模型 qsurf 集群）

- cell #2885 · 海洋/海域 · 高程 402 m
- 分箱均 T（°C）：-180.0 -179.6 -178.9 -178.4 -178.4 -178.6 -179.0 -179.5 -179.8 -180.1 -180.2 -180.3
- 分箱降水（mm/箱）：4.1 0.5 0.0 16.1 1.3 40.0 2.8 8.7 6.7 7.9 10.5 5.8
- 描述量：t_mean -179.4 · t_min -180.3 · t_max -178.4 · t_range 1.9 · 低于0°C份额 1.00 · P 104 mm/窗口 · AI MI · deficit MI · C_TV 0.39
- **分类（ucc-v1）**：polar / n/a（非陆地） · 简码 **Po** · 修饰语：—

### 6. 香格里拉（赤道沙丘带）

- cell #1661 · 陆地 · 高程 1198 m
- 分箱均 T（°C）：-178.4 -178.1 -177.8 -177.9 -177.8 -177.8 -177.7 -177.8 -178.2 -178.4 -178.5 -178.5
- 分箱降水（mm/箱）：0.7 0.5 0.0 0.0 0.0 3.2 3.5 0.0 0.0 0.1 1.0 1.6
- 描述量：t_mean -178.1 · t_min -178.5 · t_max -177.7 · t_range 0.9 · 低于0°C份额 1.00 · P 11 mm/窗口 · AI MI · deficit MI · C_TV 0.54
- **分类（ucc-v1）**：polar / n/a（MI） · 简码 **Pn** · 修饰语：—

### 7. 阿鲁（Xanadu 亮区）

- cell #1260 · 陆地 · 高程 1502 m
- 分箱均 T（°C）：-178.1 -178.0 -178.3 -178.3 -178.2 -178.1 -177.9 -177.9 -177.9 -178.0 -178.2 -178.2
- 分箱降水（mm/箱）：6.4 1.6 0.0 0.0 0.0 0.0 0.8 0.2 0.1 0.5 2.8 6.7
- 描述量：t_mean -178.1 · t_min -178.3 · t_max -177.9 · t_range 0.5 · 低于0°C份额 1.00 · P 19 mm/窗口 · AI MI · deficit MI · C_TV 0.58
- **分类（ucc-v1）**：polar / n/a（MI） · 简码 **Pn** · 修饰语：—

### 8. 赤道区（0° 本初）

- cell #1508 · 陆地 · 高程 1484 m
- 分箱均 T（°C）：-178.1 -177.9 -177.8 -177.9 -177.9 -177.7 -177.7 -177.7 -177.8 -178.0 -178.1 -178.1
- 分箱降水（mm/箱）：4.3 2.3 0.0 0.0 0.0 0.6 1.0 0.2 0.1 0.4 2.2 4.6
- 描述量：t_mean -177.9 · t_min -178.1 · t_max -177.7 · t_range 0.4 · 低于0°C份额 1.00 · P 16 mm/窗口 · AI MI · deficit MI · C_TV 0.52
- **分类（ucc-v1）**：polar / n/a（MI） · 简码 **Pn** · 修饰语：—

### 9. Menrva 盆地

- cell #613 · 陆地 · 高程 767 m
- 分箱均 T（°C）：-178.7 -178.9 -179.1 -179.0 -178.9 -178.7 -178.5 -178.4 -178.2 -178.1 -178.2 -178.5
- 分箱降水（mm/箱）：10.3 4.7 1.1 0.0 0.0 0.0 1.1 4.5 3.7 6.7 34.9 14.3
- 描述量：t_mean -178.6 · t_min -179.1 · t_max -178.1 · t_range 1.0 · 低于0°C份额 1.00 · P 82 mm/窗口 · AI MI · deficit MI · C_TV 0.48
- **分类（ucc-v1）**：polar / n/a（MI） · 简码 **Pn** · 修饰语：—

### 10. 南极区

- cell #2997 · 陆地 · 高程 749 m
- 分箱均 T（°C）：-180.5 -179.8 -179.0 -178.7 -178.8 -179.1 -179.5 -179.8 -180.1 -180.5 -180.6 -180.7
- 分箱降水（mm/箱）：94.1 15.8 2.7 2901.5 242.2 17.4 33.9 54.6 70.3 112.1 111.9 128.2
- 描述量：t_mean -179.8 · t_min -180.7 · t_max -178.7 · t_range 2.0 · 低于0°C份额 1.00 · P 3785 mm/窗口 · AI MI · deficit MI · C_TV 0.68
- **分类（ucc-v1）**：polar / n/a（MI） · 简码 **Pn** · 修饰语：—

## 3. 极值点

| 量 | cell | 纬, 经 | 高程 m | 描述量 | 类码 |
|----|------|--------|--------|--------|------|
| 最冷（t_mean 最低） | #2965 | -77.5, 170.5 | 599 | T均 -181.3 · P 396 · AI MI | **Po** |
| 最热（t_mean 最高） | #1563 | -2.8, -4.2 | 1455 | T均 -177.9 · P 14 · AI MI | **Pn** |
| 季节最强（t_range 最大） | #2933 | -75.0, -109.6 | 910 | T均 -179.8 · P 270 · AI MI | **Pn** |
| 降水最多 | #2995 | -85.4, -5.6 | 726 | T均 -179.7 · P 4084 · AI MI | **Pn** |
