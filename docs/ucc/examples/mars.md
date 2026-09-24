# Mars · UCC Worked Examples（ucc-v1）

> UCC-01 第四步 4d 产物。本文档由脚本生成，勿手改——重生成：
> `uv run python scripts/solar/ucc_examples_solar.py --planet mars`
> 生成日期：2026-09-21。描述量与分类语义见
> `../specification.md`（§8 有本天体的示意演练行，
> 本文档是它的真实数据对照）。
> **状态简写**：`OOD` = out_of_domain（需求模型超出有效域）；`MI` = missing_input、
> `NA` = not_applicable、`NPD` = no_positive_demand（语义见知识文档 §3）。

**数据源**（`data_source: gcm-climatology`——认知地位见文件内 provenance，随数据走）：
> - gcm: MCD_v6.1 with climatology average solar scenario. — web-interface 2D ASCII slices (diurnal-averaged, dust=1 climatology scenario), Ls 15.0deg. Altitude 1.0 m ALS. Diurnal mean over all local times.
> - temperature: near-surface air temperature (MCD `t`), diurnal mean at 12 Ls-bin centres; K→°C
> - precipitation: declared zero — no liquid precipitation on present-day Mars; trace frost deposition not represented (ucc §8 exercise path)
> - surface_pressure: MCD `ps` diurnal mean; global mean 626 Pa (range 208–1335, seasonal CO₂ cycle)
> - frost_context: MCD `surf_h2o_ice`: mean 0.1598 kg/m², max 10.12 kg/m² (kg/m² ≡ mm w.e.) — trace frost, declared NOT precipitation
> - topography: MOLA MEGDR 4ppd (PDS)
> - epistemic_status: L4 GCM climatology (ucc-review §6.2): a model, not error-free truth
> - time_basis: bin = 57.25 Earth-days (Martian month); p_total per Martian year (686.98 d)

**时间基准**：12 分箱 × 57.25 地球日 = 窗口 687.0 日；
`month_0` = `ls_15_first_bin_center`。`p_total` 按此窗口报告；AI/deficit 为窗口不变量，可跨世界
直接比较（知识文档 §2）。

## 0. 本世界要点（手写注记，随脚本再生）

- **全行星 100% Pn（polar/供需 OOD）**：日均气温在任何分箱都不达冰点（全网格 t_max 最高 −25 °C），冷侧有效域门全域触发——温度/降水轴照常有效，AI/deficit 全 OOD 不报数。§8 演练表预测的「赤道低地 t_max≥0 → AI=0 valid → polar/arid (Pa)」路径在**日均**序列上不出现（需要箱均温度越过冰点的数据集，如正午切片——那是另一个声明的时间语义）。
- **continental ~68%**：t_range（分箱均值的季节幅度）中位 41 °C、最大 ~106 °C，远超 25 °C 阈值——修饰语在火星点亮的正是**季节振幅**（日循环已被 diurnal 平均移除），与地球上的语义一致；water_stress 0%（deficit 随 AI 一并 OOD）。
- **P ≡ 0 为声明式导入**：现今火星无液态降水，痕量 H₂O/CO₂ 霜不冒充降水；C_TV 因此全域无定义（无降水时 concentration=None，非 0）。表面气压全球均 626 Pa、季节 CO₂ 循环与文献一致（MCD ps）。热量带全 polar 是日均气温口径的结果：t_max<10 °C 判据在火星无一例外。

## 1. 全局分布（10000 cells；陆地 10000，非陆地 0）

**热量带（全部 cell）**：polar 10000、cold 0、temperate 0、tropical 0。

**修饰语**：continental 68.2%；water_stress 0.0%（陆地）。

**AI 状态（全部 cell）**：out_of_domain 10000。

**陆地主类组合**：

| 类 | cells | 占陆地 |
|----|-------|--------|
| Pn（polar/供需不适用） | 10000 | 100.0% |
| Cn（cold/供需不适用） | 0 | 0.0% |
| Tn（temperate/供需不适用） | 0 | 0.0% |
| Rn（tropical/供需不适用） | 0 | 0.0% |

**非陆地基码**：—

## 2. 命名地点

| # | 地点 | 纬 | 经 | 高程 m | T均 | T范围 | P | AI | deficit | 类码 |
|---|------|----|----|--------|-----|-------|---|----|---------|------|
| 1 | 奥林帕斯山 | 19.2 | -133.6 | 18768 | -67.2 | 11.5 | 0 | OOD | OOD | **Pn** |
| 2 | Ascraeus Mons（塔尔西斯） | 12.3 | -105.3 | 15789 | -68.3 | 11.5 | 0 | OOD | OOD | **Pn** |
| 3 | 水手谷中部 | -14.7 | -56.7 | -4443 | -54.6 | 34.2 | 0 | OOD | OOD | **Pn-x** |
| 4 | 希腊盆地底部 | -42.7 | 69.8 | -6559 | -69.9 | 84.9 | 0 | OOD | OOD | **Pn-x** |
| 5 | 阿吉尔盆地 | -48.8 | -43.4 | -2785 | -76.7 | 92.7 | 0 | OOD | OOD | **Pn-x** |
| 6 | 阿拉伯高地 | 19.7 | -29.8 | -3127 | -57.1 | 17.6 | 0 | OOD | OOD | **Pn** |
| 7 | 大瑟提斯高原 | 8.9 | 70.0 | 1686 | -55.3 | 10.7 | 0 | OOD | OOD | **Pn** |
| 8 | 埃律西昂平原 | 3.1 | 154.3 | -2720 | -66.7 | 17.1 | 0 | OOD | OOD | **Pn** |
| 9 | 子午线平原（机遇号） | -2.6 | -6.1 | -1493 | -54.6 | 23.0 | 0 | OOD | OOD | **Pn** |
| 10 | 乌托邦平原 | 46.9 | 116.3 | -4847 | -80.1 | 65.1 | 0 | OOD | OOD | **Pn-x** |
| 11 | 北极冠 | 85.3 | -13.0 | -3580 | -110.0 | 66.0 | 0 | OOD | OOD | **Pn-x** |
| 12 | 南极高原（Planum Australe） | -84.5 | 50.3 | 2949 | -109.4 | 99.7 | 0 | OOD | OOD | **Pn-x** |

### 1. 奥林帕斯山

- cell #3373 · 陆地 · 高程 18768 m
- 分箱均 T（°C）：-70.9 -73.1 -72.1 -70.4 -66.7 -63.6 -62.1 -61.6 -64.3 -67.5 -67.1 -67.5
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -67.2 · t_min -73.1 · t_max -61.6 · t_range 11.5 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn** · 修饰语：—

### 2. Ascraeus Mons（塔尔西斯）

- cell #3954 · 陆地 · 高程 15789 m
- 分箱均 T（°C）：-71.5 -74.1 -72.5 -70.7 -68.8 -64.8 -63.1 -62.6 -65.6 -69.0 -68.9 -68.1
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -68.3 · t_min -74.1 · t_max -62.6 · t_range 11.5 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn** · 修饰语：—

### 3. 水手谷中部

- cell #6213 · 陆地 · 高程 -4443 m
- 分箱均 T（°C）：-59.4 -67.8 -73.4 -73.3 -64.8 -55.2 -46.0 -39.2 -39.4 -42.3 -44.4 -50.3
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -54.6 · t_min -73.4 · t_max -39.2 · t_range 34.2 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn-x** · 修饰语：continental

### 4. 希腊盆地底部

- cell #8495 · 陆地 · 高程 -6559 m
- 分箱均 T（°C）：-79.2 -100.7 -113.6 -112.2 -99.4 -81.0 -55.4 -36.2 -28.7 -32.4 -41.6 -58.1
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -69.9 · t_min -113.6 · t_max -28.7 · t_range 84.9 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn-x** · 修饰语：continental

### 5. 阿吉尔盆地

- cell #8810 · 陆地 · 高程 -2785 m
- 分箱均 T（°C）：-85.5 -108.0 -120.6 -122.2 -115.1 -94.3 -68.7 -40.3 -29.5 -32.2 -42.6 -61.7
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -76.7 · t_min -122.2 · t_max -29.5 · t_range 92.7 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn-x** · 修饰语：continental

### 6. 阿拉伯高地

- cell #3367 · 陆地 · 高程 -3127 m
- 分箱均 T（°C）：-56.2 -55.0 -55.0 -53.3 -51.2 -50.6 -52.3 -56.7 -65.4 -68.2 -62.4 -58.5
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -57.1 · t_min -68.2 · t_max -50.6 · t_range 17.6 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn** · 修饰语：—

### 7. 大瑟提斯高原

- cell #4225 · 陆地 · 高程 1686 m
- 分箱均 T（°C）：-57.9 -60.9 -60.9 -56.6 -51.7 -51.4 -50.4 -50.3 -54.6 -57.2 -56.4 -55.4
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -55.3 · t_min -60.9 · t_max -50.3 · t_range 10.7 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn** · 修饰语：—

### 8. 埃律西昂平原

- cell #4748 · 陆地 · 高程 -2720 m
- 分箱均 T（°C）：-69.9 -74.5 -74.0 -72.2 -70.7 -62.9 -61.2 -57.3 -60.7 -65.6 -65.5 -65.6
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -66.7 · t_min -74.5 · t_max -57.3 · t_range 17.1 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn** · 修饰语：—

### 9. 子午线平原（机遇号）

- cell #5278 · 陆地 · 高程 -1493 m
- 分箱均 T（°C）：-57.7 -63.9 -67.4 -66.0 -59.8 -51.9 -47.4 -44.4 -46.3 -49.1 -49.4 -52.1
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -54.6 · t_min -67.4 · t_max -44.4 · t_range 23.0 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn** · 修饰语：—

### 10. 乌托邦平原

- cell #1371 · 陆地 · 高程 -4847 m
- 分箱均 T（°C）：-73.7 -59.2 -53.9 -51.2 -55.0 -62.9 -80.4 -96.9 -111.8 -116.3 -108.2 -91.4
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -80.1 · t_min -116.3 · t_max -51.2 · t_range 65.1 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn-x** · 修饰语：continental

### 11. 北极冠

- cell #21 · 陆地 · 高程 -3580 m
- 分箱均 T（°C）：-123.6 -121.5 -117.6 -59.3 -64.0 -87.6 -123.7 -124.3 -124.2 -125.3 -125.0 -124.1
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -110.0 · t_min -125.3 · t_max -59.3 · t_range 66.0 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn-x** · 修饰语：continental

### 12. 南极高原（Planum Australe）

- cell #9977 · 陆地 · 高程 2949 m
- 分箱均 T（°C）：-127.6 -129.2 -130.3 -131.7 -132.0 -130.1 -126.0 -122.7 -100.6 -32.4 -51.9 -98.9
- 分箱降水（mm/箱）：0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
- 描述量：t_mean -109.4 · t_min -132.0 · t_max -32.4 · t_range 99.7 · 低于0°C份额 1.00 · P 0 mm/窗口 · AI OOD · deficit OOD · C_TV —
- **分类（ucc-v1）**：polar / n/a（OOD） · 简码 **Pn-x** · 修饰语：continental

## 3. 极值点

| 量 | cell | 纬, 经 | 高程 m | 描述量 | 类码 |
|----|------|--------|--------|--------|------|
| 最冷（t_mean 最低） | #9998 | -89.5, 55.6 | 3846 | T均 -125.2 · P 0 · AI OOD | **Pn** |
| 最热（t_mean 最高） | #5794 | -8.7, -40.2 | -771 | T均 -52.7 · P 0 · AI OOD | **Pn-x** |
| 季节最强（t_range 最大） | #9955 | -82.7, -175.3 | 2973 | T均 -104.4 · P 0 · AI OOD | **Pn-x** |
