# 月度温度 / 降水展示（Phase 4 前端延伸）

> **状态**：设计提案（未实现）——数据已在后端算好但未导出，前端尚无月度图层。
> 2026-08-28 起草，源自 `private/plans/climate-accuracy-plan.md` Phase 4。

> 本文档描述「月度气候展示」——把季节能量平衡模型（EBM）已经算好的 **12 个月
> 温度 + 降水**导出到前端，用 SunControl 的周年滑杆驱动，实现「拖动季节看月度气候
> 图层变化」。

## 1 目标

- 前端新增「月度温度 / 月度降水」图层（或年度图层的「月度模式」）。
- SunControl 周年滑杆（0–360°）兼作「月份输入」，驱动月度图层。
- 温度用**真实**季节 EBM 输出；降水先上**粗版**（ITCZ 迁移高斯重构，无季风）。

## 2 数据源（后端已算好）

`compute_seasonal_climate` 已经输出（`simulate_climate` 里）：

- `t_monthly_C`（N×12）——真实月度温度：季节 EBM（`T_amp=ΔQ_ω(1−α)/√(B_eff²+(ωC)²)`
  + 热容 + 冰反照率），`t_mean_C + amplitude·cos(...)`。
- `p_monthly`（N×12）——**粗版**月度降水：`(p_annual − conv) × p_factor + conv/12`，
  其中 `p_factor` 是 `monthly_precipitation_factor`（以迁移 ITCZ 为中心的高斯，σ=15° +
  0.3 均匀底，`is_land` 参数当前未用）。

**与 Köppen 同源**：`t_hot/t_cold = max/min(t_monthly_C)`、`p_dry/p_wet/p_warm/p_cold =
min/max/半年度和(p_monthly)`。所以导出的月度 T/P 与 Köppen 图**完全对应**——「粗」是
物理层面的粗（无季风），不是「和 Köppen 对不上」。

> 降水粗版的根治（季风动力学：季节风反转 + 内陆水汽输送）见 roadmap §7 #2/#18，属
> 新物理机制，本提案只做「粗版渲染」，等季风落地后再升级为真月度降水。

## 3 现状机制（年度图层怎么做的）

年度温度/降水图层**不是**用后端导出的 PNG 栅格，而是从 **mesh 的 per-cell 字段**现场烘焙：

1. 前端读 `cvt_mesh.json` 里每个 cell 的 `temperature_C` / `precipitation_mm`。
2. `layerBakes.ts` 的 `bakeLayerTextures` 遍历 cell，用色标映射 RGB——
   温度 diverging（`(tC+40)/80 → TEMPERATURE_SCALE`，0°C 居中）、
   降水 log（`log10(pMm+1)/log10(30001) → PRECIP_SCALE`）。
3. 存成 `cell.id → RGB` 的 Map，烘焙成颜色纹理；`useGPUTerrain` 的 layer bake
   **模块级缓存**（换图层/路由不重烘，一次 CPU 烘焙 ~100ms）。

> 后端导出的 `temperature.png` / `precipitation.png` **前端渲染不用**，仅作为后端/
> 静态站产物。

## 4 设计

### 4.1 数据格式：方案 B（单个二进制）

**不把 12 个月塞进 mesh**（会让 `cvt_mesh.json` 翻倍、每次进地图都白载），而是单独一个
`climate_monthly.msgpack`：

```
climate_monthly.msgpack
  ├─ t_monthly: float32[N×12]     # 月度温度 °C
  ├─ p_monthly: float32[N×12]     # 月度降水 mm/月
  ├─ temperature_range_c: [min, max]
  ├─ precipitation_range_mm: [min, max]
  └─ month_0: "vernal_equinox"    # 月历约定（见 4.4）
```

- 体积：200k×24×4 ≈ 19 MB raw，gzip ~10 MB（远小于 24 张 PNG 的 ~72 MB）。
- 前端**按需加载**（只有打开月度图层才 fetch），复用现有 MessagePack 解析（mesh 已用）。
- 否决方案 A（12 个月 PNG 栅格）：24 张 ×~3MB ≈ 72MB，GitHub Pages 撑不住。

### 4.2 前端烘焙：复用 `layerBakes.ts`

现有 `bakeLayerTextures` 已经「per-cell 数据 → 色标 → 纹理」。月度图层只是把数据源从
「annual 标量」换成「month 列」：

- 新增一个 `bakeMonthlyLayer(month)`，读 `climate_monthly.msgpack` 的第 month 列，
  走**同一套** `TEMPERATURE_SCALE` / `PRECIP_SCALE` 色标。
- 月份变化时触发**重烘焙**（~100ms，`useRafCoalesced` 已做帧合并，滑杆拖动不卡）。
- 缓存策略：可预烘 12 张纹理（一次烘完，滑杆切换 O(1)），或按需烘当前月。

### 4.3 SunControl：连续滑杆 + 月序读数

**不把周年滑杆改成 12 格**——光照（太阳赤纬）是连续的，snap 会让终结线在月界跳变；
月度 T/P 本就是离散月度平均，让它「跳到最近月」合理。

- **主刻度不动**：春分/夏至/秋分/冬至（通用二分二至，Earth & nacrea 都成立）。
- **月度用「月序」读数**（非「月份」非「节气」——两者都是地球历法/气候命名，nacrea
  不适用）：`M1…M12`，即「年 12 等分」这个物理概念。仅当月度气候图层开启时显示。
- 派生：`month = round(season / 30) % 12`（0°=春分=M1，90°=夏至=M4，…）。

### 4.4 月历约定（需实现时核实）

SunControl 的 season 约定是「0° = 北半球春分」（`solarDeclinationDeg`）。后端
`monthly_temperature` 的 `month_hot` 相位、`monthly_insolation` 的 month 0 参考，需在
实现时对齐——确保前端 `season=0` 对应后端 `t_monthly[:, 0]` 也是「春分起首月」。若相位
偏移（如后端 month 0 = 冬至），在导出层做一次 `np.roll` 对齐，而不是改前端。

### 4.5 栏标题

建议「光照」→「太阳」（概括周日 + 周年 + 派生的月序），或保持「光照」、把月度气候做成
独立图层开关（SunControl 只被动提供月序读数）。倾向后者（职责清晰、标题改动最小）。

## 5 实现步骤

1. **后端**：`export_climate_layers` 增加 `climate_monthly.msgpack` 导出
   （`t_monthly` + `p_monthly` + 范围元数据 + 月历约定）。
2. **静态导出三件套**（CLAUDE.md 约定）：`scripts/export_static.py` 导出该文件 +
   `frontend/src/api/staticClient.ts` 加读取方法 + `client.ts` unified API 委托。
3. **前端烘焙**：`layerBakes.ts` 增加 `bakeMonthlyLayer(month)`；`useGPUTerrain` 增加
   月度纹理缓存。
4. **SunControl**：周年滑杆下加「月序」读数（月度图层开启时显示）。
5. **图层面板**：新增「月度温度 / 月度降水」开关（或年度图层的「月度模式」）。
6. **i18n**：新增月度相关文案（zh-CN + en）。

## 6 决策记录

| 决策 | 选择 | 备选 |
|---|---|---|
| 数据格式 | B（msgpack 二进制） | A（12 个月 PNG 栅格，~72MB 否） |
| 滑杆 | 连续（不切 12 格） | 12 格（光照跳变，否） |
| 月度命名 | 月序 M1–M12（通用） | 月份/节气（地球特定，nacrea 不适用） |
| 降水版本 | 粗版（ITCZ 高斯） | 真月度（需季风动力学，挂 #2/#18） |
