# Moon · UCC Worked Examples — 数据表（ucc-v2）

> UCC-01 第四步 4d 产物。本文档由脚本生成，勿手改——重生成：
> `uv run python scripts/solar/ucc_examples_solar.py --planet moon`
> 生成日期：2026-10-05。本天体的解读（世界要点、读法）见手写文档
> `docs/ucc/examples/moon.md`；描述量与分类语义见
> `docs/ucc/specification.md`（§8 有本天体的示意演练行，
> 本文档是它的真实数据对照）。
> **状态简写**：`OOD` = out_of_domain（需求模型超出有效域）；`MI` = missing_input、
> `NA` = not_applicable、`NPD` = no_positive_demand（语义见知识文档 §3）。

**数据源**（`data_source: observation`——认知地位见文件内 provenance，随数据走）：
> - temperature: LRO Diviner GCP (PDS LRO-L-DLRE-5-GCP-V1.0), bolometric brightness temperature tbol as SPT proxy; nadir observations 2009-07-05…2015-04-01, 0.5° × 0.25 h LT bins aggregated to 12 × 2 h LT
> - temperature_kind: SURFACE temperature (no atmosphere) — declared exception to the near-surface-air contract
> - precipitation: declared zero — vacuum; no precipitation (concentration undefined by contract)
> - demand_model_note: NOT applied (demand_model=None) — no atmosphere, no PET model applies; AI/deficit = missing_input
> - topography: LRO LDEM_4 (NASA SVS Moon Kit)
> - epistemic_status: observation-grade (like earth root), NOT a GCM — but surface-temperature semantics differ from air temperature
> - time_basis: bin = 2.4609 Earth-days (2 h local time); window = 1 synodic rotation, not a year
> - climate_state: airless — declared world regime (axis F); no atmosphere, hence no lapse rate and no -H highland modifier

**世界级声明**：`climate_state: airless`；递减率
未声明（无大气 → -H 不适用）（-H 高地修饰语的判据输入）。

**时间基准**：12 分箱 × 2.46 地球日 = 窗口 29.5 日；
`month_0` = `local_time_00h`。`p_total` 按此窗口报告；AI/deficit 为窗口不变量，可跨世界
直接比较（知识文档 §2）。

## 1. 全局分布（100000 cells；陆地 100000，非陆地 0）

**热量带（全部 cell）**：polar 5902、cold 94098、temperate 0、tropical 0。

**修饰语**：continental 100.0%；water_stress 0.0%（陆地）。

**AI 状态（全部 cell）**：missing_input 100000。

**陆地主类组合**：

| 类 | cells | 占陆地 |
|----|-------|--------|
| En（polar/供需不适用） | 5902 | 5.9% |
| Dn（cold/供需不适用） | 94098 | 94.1% |
| Cn（temperate/供需不适用） | 0 | 0.0% |
| An（tropical/供需不适用） | 0 | 0.0% |

**非陆地基码**：—

## 2. 命名地点

| # | 地点 | 纬 | 经 | 高程 m | T均 | T范围 | P | AI | deficit | 类码 |
|---|------|----|----|--------|-----|-------|---|----|---------|------|
| 1 | 中央湾（近面赤道） | -0.2 | 0.4 | -690 | -52.0 | 295.8 | 0 | MI | MI | **Dn-Sl** |
| 2 | 雨海 | 34.8 | -16.6 | -2332 | -60.7 | 275.7 | 0 | MI | MI | **Dn-Sl** |
| 3 | 静海（阿波罗11） | 1.0 | 23.5 | -1995 | -48.2 | 293.0 | 0 | MI | MI | **Dn-Sl** |
| 4 | 风暴洋 | 20.2 | -54.8 | -2007 | -57.5 | 286.6 | 0 | MI | MI | **Dn-Sl** |
| 5 | 哥白尼坑 | 9.7 | -20.2 | -3498 | -52.4 | 275.3 | 0 | MI | MI | **Dn-Sl** |
| 6 | 阿里斯塔克斯高原 | 23.8 | -47.2 | -3090 | -49.2 | 252.7 | 0 | MI | MI | **Dn-Sl** |
| 7 | 齐奥尔科夫斯基坑（背面） | -20.7 | 129.4 | -1789 | -54.4 | 283.1 | 0 | MI | MI | **Dn-Sl** |
| 8 | 南极-艾特肯盆地 | -53.2 | -169.1 | -7271 | -87.5 | 241.4 | 0 | MI | MI | **Dn-Sl** |
| 9 | 沙克尔顿坑（南极） | -90.0 | -139.3 | 1378 | -112.3 | 152.7 | 0 | MI | MI | **En-Sl** |
| 10 | 北极区 | 89.2 | -19.3 | -1229 | -167.8 | 116.4 | 0 | MI | MI | **En-Sl** |

### 1. 中央湾（近面赤道）

- cell #50172 · 陆地 · 高程 -690 m
- 分箱均 T（°C）：-172.8 -175.7 -177.6 7.5 79.9 114.9 118.3 80.6 -12.4 -153.1 -164.2 -169.6
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -52.0 · t_min -177.6 · t_max 118.3 · t_range 295.8 · 低于0°C份额 0.58 · P 0 mm/窗口 · AI MI · deficit MI · C_TV —
- **分类（ucc-v2）**：cold / n/a（MI） · 简码 **Dn-Sl** · 修饰语：continental

### 2. 雨海

- cell #21468 · 陆地 · 高程 -2332 m
- 分箱均 T（°C）：-175.4 -178.5 -180.2 -6.2 55.7 91.7 95.5 64.3 1.7 -157.9 -167.2 -172.3
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -60.7 · t_min -180.2 · t_max 95.5 · t_range 275.7 · 低于0°C份额 0.58 · P 0 mm/窗口 · AI MI · deficit MI · C_TV —
- **分类（ucc-v2）**：cold / n/a（MI） · 简码 **Dn-Sl** · 修饰语：continental

### 3. 静海（阿波罗11）

- cell #49122 · 陆地 · 高程 -1995 m
- 分箱均 T（°C）：-171.6 -174.9 -176.7 35.7 86.9 115.8 116.3 87.4 -11.3 -153.5 -163.6 -169.2
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -48.2 · t_min -176.7 · t_max 116.3 · t_range 293.0 · 低于0°C份额 0.58 · P 0 mm/窗口 · AI MI · deficit MI · C_TV —
- **分类（ucc-v2）**：cold / n/a（MI） · 简码 **Dn-Sl** · 修饰语：continental

### 4. 风暴洋

- cell #32519 · 陆地 · 高程 -2007 m
- 分箱均 T（°C）：-173.8 -175.7 -177.1 -12.2 58.4 107.8 109.5 76.1 -15.5 -153.2 -164.6 -170.1
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -57.5 · t_min -177.1 · t_max 109.5 · t_range 286.6 · 低于0°C份额 0.67 · P 0 mm/窗口 · AI MI · deficit MI · C_TV —
- **分类（ucc-v2）**：cold / n/a（MI） · 简码 **Dn-Sl** · 修饰语：continental

### 5. 哥白尼坑

- cell #41585 · 陆地 · 高程 -3498 m
- 分箱均 T（°C）：-163.9 -165.8 -167.1 -36.1 71.4 107.7 108.3 68.6 3.1 -144.5 -153.4 -157.7
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -52.4 · t_min -167.1 · t_max 108.3 · t_range 275.3 · 低于0°C份额 0.58 · P 0 mm/窗口 · AI MI · deficit MI · C_TV —
- **分类（ucc-v2）**：cold / n/a（MI） · 简码 **Dn-Sl** · 修饰语：continental

### 6. 阿里斯塔克斯高原

- cell #29914 · 陆地 · 高程 -3090 m
- 分箱均 T（°C）：-148.7 -151.8 -153.8 -26.2 41.6 92.0 99.0 63.1 -10.1 -116.5 -136.5 -142.5
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -49.2 · t_min -153.8 · t_max 99.0 · t_range 252.7 · 低于0°C份额 0.67 · P 0 mm/窗口 · AI MI · deficit MI · C_TV —
- **分类（ucc-v2）**：cold / n/a（MI） · 简码 **Dn-Sl** · 修饰语：continental

### 7. 齐奥尔科夫斯基坑（背面）

- cell #67670 · 陆地 · 高程 -1789 m
- 分箱均 T（°C）：-169.8 -172.9 -175.0 -4.3 75.9 108.1 104.3 62.1 -6.4 -148.8 -160.0 -166.2
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -54.4 · t_min -175.0 · t_max 108.1 · t_range 283.1 · 低于0°C份额 0.67 · P 0 mm/窗口 · AI MI · deficit MI · C_TV —
- **分类（ucc-v2）**：cold / n/a（MI） · 简码 **Dn-Sl** · 修饰语：continental

### 8. 南极-艾特肯盆地

- cell #90004 · 陆地 · 高程 -7271 m
- 分箱均 T（°C）：-182.4 -183.8 -186.6 -77.6 22.4 53.2 54.7 29.7 -61.5 -166.0 -173.4 -178.6
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -87.5 · t_min -186.6 · t_max 54.7 · t_range 241.4 · 低于0°C份额 0.67 · P 0 mm/窗口 · AI MI · deficit MI · C_TV —
- **分类（ucc-v2）**：cold / n/a（MI） · 简码 **Dn-Sl** · 修饰语：continental

### 9. 沙克尔顿坑（南极）

- cell #99999 · 陆地 · 高程 1378 m
- 分箱均 T（°C）：-70.2 -51.7 -40.8 -49.3 -113.1 -147.1 -193.5 -181.2 -139.8 -124.0 -116.2 -120.8
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -112.3 · t_min -193.5 · t_max -40.8 · t_range 152.7 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI MI · deficit MI · C_TV —
- **分类（ucc-v2）**：polar / n/a（MI） · 简码 **En-Sl** · 修饰语：continental

### 10. 北极区

- cell #8 · 陆地 · 高程 -1229 m
- 分箱均 T（°C）：-211.6 -165.1 -140.6 -117.6 -125.0 -100.1 -132.1 -172.8 -204.1 -211.8 -216.5 -216.2
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -167.8 · t_min -216.5 · t_max -100.1 · t_range 116.4 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI MI · deficit MI · C_TV —
- **分类（ucc-v2）**：polar / n/a（MI） · 简码 **En-Sl** · 修饰语：continental

## 3. 极值点

| 量 | cell | 纬, 经 | 高程 m | 描述量 | 类码 |
|----|------|--------|--------|--------|------|
| 最冷（t_mean 最低） | #99946 | -87.5, 2.2 | -3435 | T均 -231.8 · P 0 · AI MI | **En** |
| 最热（t_mean 最高） | #40705 | 10.8, 26.7 | -1557 | T均 -43.4 · P 0 · AI MI | **Dn-Sl** |
| 季节最强（t_range 最大） | #53280 | -3.9, -53.8 | -1959 | T均 -51.5 · P 0 · AI MI | **Dn-Sl** |
