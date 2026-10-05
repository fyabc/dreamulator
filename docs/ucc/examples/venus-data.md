# Venus · UCC Worked Examples — 数据表（ucc-v2）

> UCC-01 第四步 4d 产物。本文档由脚本生成，勿手改——重生成：
> `uv run python scripts/solar/ucc_examples_solar.py --planet venus`
> 生成日期：2026-10-05。本天体的解读（世界要点、读法）见手写文档
> `docs/ucc/examples/venus.md`；描述量与分类语义见
> `docs/ucc/specification.md`（§8 有本天体的示意演练行，
> 本文档是它的真实数据对照）。
> **状态简写**：`OOD` = out_of_domain（需求模型超出有效域）；`MI` = missing_input、
> `NA` = not_applicable、`NPD` = no_positive_demand（语义见知识文档 §3）。

**数据源**（`data_source: gcm-climatology`——认知地位见文件内 provenance，随数据走）：
> - gcm: VCD_v2.3 with Standard cloud albedo scenario, average solar EUV conditions. Altitude 1.0 m ALS. Local time 12.0Vhrs (at longitude 0) — web-interface 2D ASCII slices (standard cloud albedo / average EUV; fixed local time 12 Vhrs, NOT diurnal-averaged — surface diurnal range negligible), Ls ?
> - temperature: VCD `tsurf` surface temperature (K→°C); with the 92-bar atmosphere surface ≈ near-surface air (near-isothermal ~737 K)
> - precipitation: declared zero — no precipitation reaches the surface (H₂SO₄ cloud rain evaporates as virga)
> - surface_pressure: VCD `ps` diurnal mean; global mean 9268 kPa
> - topography: USGS Venus Magellan Global Topography 4641m v02
> - epistemic_status: L4 GCM climatology (ucc-review §6.2): a model, not error-free truth
> - demand_model_warning: HOT-SIDE DOMAIN GATE (v2): the whole year sits above the 35 °C gate, so AI/deficit/phase report out_of_domain and the supply slot reads n — Hamon at ~737 K is arithmetic extrapolation far outside its liquid-water calibration domain.
> - time_basis: bin = 18.73 Earth-days (Venus month); p_total per Venus year (224.701 d)
> - climate_state: runaway_greenhouse — declared world regime (axis F); Wolf 2017 / Goldblatt 2015 runaway-greenhouse lineage
> - lapse_rate: 8.0 K/km near-adiabatic deep atmosphere (VIRA — Seiff et al. 1985; Zasova et al. 2006) — enables the -H highland modifier (expected to stay silent: every bin is far inside the tropical band)

**世界级声明**：`climate_state: runaway_greenhouse`；递减率
8 K/km（-H 高地修饰语的判据输入）。

**时间基准**：12 分箱 × 18.73 地球日 = 窗口 224.7 日；
`month_0` = `ls_15_first_bin_center`。`p_total` 按此窗口报告；AI/deficit 为窗口不变量，可跨世界
直接比较（知识文档 §2）。

## 1. 全局分布（10000 cells；陆地 10000，非陆地 0）

**热量带（全部 cell）**：polar 0、cold 0、temperate 0、tropical 10000。

**修饰语**：continental 0.0%；water_stress 0.0%（陆地）。

**AI 状态（全部 cell）**：out_of_domain 10000。

**陆地主类组合**：

| 类 | cells | 占陆地 |
|----|-------|--------|
| En（polar/供需不适用） | 0 | 0.0% |
| Dn（cold/供需不适用） | 0 | 0.0% |
| Cn（temperate/供需不适用） | 0 | 0.0% |
| An（tropical/供需不适用） | 10000 | 100.0% |

**非陆地基码**：—

## 2. 命名地点

| # | 地点 | 纬 | 经 | 高程 m | T均 | T范围 | P | AI | deficit | 类码 |
|---|------|----|----|--------|-----|-------|---|----|---------|------|
| 1 | 麦克斯韦山脉 | 64.7 | 6.8 | 8269 | 414.8 | 0.0 | 0 | OOD | OOD | **An** |
| 2 | 伊师塔地 | 69.4 | 42.4 | 2441 | 448.0 | 0.0 | 0 | OOD | OOD | **An** |
| 3 | 阿佛洛狄忒地 | -9.4 | -159.9 | 1999 | 448.8 | 0.0 | 0 | OOD | OOD | **An** |
| 4 | 贝塔区（Theia Mons） | 25.6 | -78.6 | 3684 | 437.5 | 0.0 | 0 | OOD | OOD | **An** |
| 5 | Maat Mons | 0.3 | -165.7 | 7693 | 437.8 | 0.0 | 0 | OOD | OOD | **An** |
| 6 | 几内亚平原 | -21.1 | -39.6 | 708 | 459.8 | 0.0 | 0 | OOD | OOD | **An** |
| 7 | 拉维尼亚平原 | -21.1 | -15.6 | 506 | 461.8 | 0.0 | 0 | OOD | OOD | **An** |
| 8 | 赤道低地 | 0.7 | 148.9 | 1090 | 454.5 | 0.0 | 0 | OOD | OOD | **An** |
| 9 | 北极区 | 85.3 | -13.0 | -282 | 464.5 | 0.0 | 0 | OOD | OOD | **An** |
| 10 | 南极区 | -85.9 | 3.6 | 427 | 460.0 | 0.0 | 0 | OOD | OOD | **An** |

### 1. 麦克斯韦山脉

- cell #500 · 陆地 · 高程 8269 m
- 分箱均 T（°C）：414.8 414.8 414.8 414.8 414.8 414.8 414.8 414.8 414.8 414.8 414.8 414.8
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean 414.8 · t_min 414.8 · t_max 414.8 · t_range 0.0 · 低于0°C份额 0.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v2）**：tropical / n/a（OOD） · 简码 **An** · 修饰语：—

### 2. 伊师塔地

- cell #306 · 陆地 · 高程 2441 m
- 分箱均 T（°C）：448.0 448.0 448.0 448.0 448.0 448.0 448.0 448.0 448.0 448.0 448.0 448.0
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean 448.0 · t_min 448.0 · t_max 448.0 · t_range 0.0 · 低于0°C份额 0.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v2）**：tropical / n/a（OOD） · 简码 **An** · 修饰语：—

### 3. 阿佛洛狄忒地

- cell #5842 · 陆地 · 高程 1999 m
- 分箱均 T（°C）：448.8 448.8 448.8 448.8 448.8 448.8 448.8 448.8 448.8 448.8 448.8 448.8
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean 448.8 · t_min 448.8 · t_max 448.8 · t_range 0.0 · 低于0°C份额 0.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v2）**：tropical / n/a（OOD） · 简码 **An** · 修饰语：—

### 4. 贝塔区（Theia Mons）

- cell #2849 · 陆地 · 高程 3684 m
- 分箱均 T（°C）：437.5 437.5 437.5 437.5 437.5 437.5 437.5 437.5 437.5 437.5 437.5 437.5
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean 437.5 · t_min 437.5 · t_max 437.5 · t_range 0.0 · 低于0°C份额 0.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v2）**：tropical / n/a（OOD） · 简码 **An** · 修饰语：—

### 5. Maat Mons

- cell #4965 · 陆地 · 高程 7693 m
- 分箱均 T（°C）：437.8 437.8 437.8 437.8 437.8 437.8 437.8 437.8 437.8 437.8 437.8 437.8
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean 437.8 · t_min 437.8 · t_max 437.8 · t_range 0.0 · 低于0°C份额 0.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v2）**：tropical / n/a（OOD） · 简码 **An** · 修饰语：—

### 6. 几内亚平原

- cell #6781 · 陆地 · 高程 708 m
- 分箱均 T（°C）：459.8 459.8 459.8 459.8 459.8 459.8 459.8 459.8 459.8 459.8 459.8 459.8
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean 459.8 · t_min 459.8 · t_max 459.8 · t_range 0.0 · 低于0°C份额 0.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v2）**：tropical / n/a（OOD） · 简码 **An** · 修饰语：—

### 7. 拉维尼亚平原

- cell #6807 · 陆地 · 高程 506 m
- 分箱均 T（°C）：461.8 461.8 461.8 461.8 461.8 461.8 461.8 461.8 461.8 461.8 461.8 461.8
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean 461.8 · t_min 461.8 · t_max 461.8 · t_range 0.0 · 低于0°C份额 0.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v2）**：tropical / n/a（OOD） · 简码 **An** · 修饰语：—

### 8. 赤道低地

- cell #4947 · 陆地 · 高程 1090 m
- 分箱均 T（°C）：454.5 454.5 454.5 454.5 454.5 454.5 454.5 454.5 454.5 454.5 454.5 454.5
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean 454.5 · t_min 454.5 · t_max 454.5 · t_range 0.0 · 低于0°C份额 0.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v2）**：tropical / n/a（OOD） · 简码 **An** · 修饰语：—

### 9. 北极区

- cell #21 · 陆地 · 高程 -282 m
- 分箱均 T（°C）：464.5 464.5 464.5 464.5 464.5 464.5 464.5 464.5 464.5 464.5 464.5 464.5
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean 464.5 · t_min 464.5 · t_max 464.5 · t_range 0.0 · 低于0°C份额 0.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v2）**：tropical / n/a（OOD） · 简码 **An** · 修饰语：—

### 10. 南极区

- cell #9993 · 陆地 · 高程 427 m
- 分箱均 T（°C）：460.0 460.0 460.0 460.0 460.0 460.0 460.0 460.0 460.0 460.0 460.0 460.0
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean 460.0 · t_min 460.0 · t_max 460.0 · t_range 0.0 · 低于0°C份额 0.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v2）**：tropical / n/a（OOD） · 简码 **An** · 修饰语：—

## 3. 极值点

| 量 | cell | 纬, 经 | 高程 m | 描述量 | 类码 |
|----|------|--------|--------|--------|------|
| 最冷（t_mean 最低） | #466 | 64.4, 2.9 | 10180 | T均 408.8 · P 0 · AI OOD | **An** |
| 最热（t_mean 最高） | #1435 | 46.4, -42.2 | -710 | T均 469.0 · P 0 · AI OOD | **An** |
| 季节最强（t_range 最大） | #0 | 89.6, 23.9 | -722 | T均 465.7 · P 0 · AI OOD | **An** |
