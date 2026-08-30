# 真实地球数据导入（earth 主世界）

> 本文档汇总 earth 验证世界所需的**真实地球输入数据**：来源、格式、许可、导入脚本、
> 输出与相互依赖。与「气候验证观测数据」分开——后者见 [climate-validation.md](climate-validation.md)。

---

## 1. 概览

earth 主世界的 `maps/planet_earth/` 数据**不是合成管线生成的**，而是由四个专用
导入脚本从真实数据集重建，按依赖顺序执行：

```
ETOPO1（高程）──► PB2002（板块+地壳）──► GSHHG（水掩膜）──► NCEP/GPCP/Beck（气候观测）
```

| # | 数据 | 来源 | 许可 | 导入脚本 | 输出字段 |
|---|------|------|------|----------|----------|
| 1 | **ETOPO1** 高程 | NOAA NGDC | Public domain | `import_earth_elevation.py` | `elevation` |
| 2 | **PB2002** 板块 | Bird 2003 (doi:10.1029/2001GC000252) | ODC-BY | `import_earth_tectonics.py` | `plate_id`、`crust_type`、`boundary_type` |
| 3 | **GSHHG** 水掩膜 | Wessel & Smith 1996 | LGPL-3 | `import_earth_watermask.py` | `water_class` |
| 4 | **NCEP/GPCP/Beck** 气候 | NOAA PSL / figshare | 见下 | `import_earth_climate.py` | `koppen_class`、`temperature_C`、`precipitation_mm`、月均 msgpack |

前三个缓存到系统临时目录（`tempfile.gettempdir()` 下的 `dreamulator_*`），气候观测数据
放在 `private/tmp/climatology/`（gitignored），均可重下载。

---

## 2. 数据源明细

### 2.1 ETOPO1 高程（`import_earth_elevation.py`）

- **URL**：`https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO1/data/ice_surface/grid_registered/netcdf/ETOPO1_Ice_g_gmt4.grd.gz`
- **格式**：NetCDF（gzip），10801×21601，1 arc-minute（~1.8 km）。
- **流程**：下载 → 重采样到 4096×2048 → 建 CVT 网格（`num_nodes` 可配，earth 用 200 000）
  → 逐 cell 采样高程 → 写 `elevation.png` + `cvt_mesh.json` + `map.yaml`。
- **注意**：默认 `--output-dir` 指向 `layers/geological/input/maps/earth`（历史遗留，非标准
  `maps/planet_earth`）。导入到 earth 主世界必须显式传
  `--output-dir <world>/maps/planet_earth`。

### 2.2 PB2002 板块（`import_earth_tectonics.py`）

- **URL**（几何）：`https://raw.githubusercontent.com/fraxen/tectonicplates/master/GeoJSON/PB2002_plates.json`
- **URL**（欧拉极）：`https://mirror.pyrocko.org/peterbird.name/oldFTP/PB2002/PB2002_poles.dat.txt`
- **流程**：52 板块多边形 → 球面点-in-多边形分配 `plate_id` → 地壳类型用 ETOPO1 水深判
  洋-陆边界（OCB，见 [plate_tectonics.md](../../knowledge/geology/plate_tectonics.md)）→
  `boundary_type` 复用 `detect_boundaries`（从真实欧拉极的相对运动推导）→ 写 `plates.json`。
- **地壳口径**：`continental` ≥ −2000 m（陆+大陆架，~41%）、`transitional` −3000~−2000 m、
  `oceanic` < −3000 m。

> **⚠️ 地壳/边界是「推导值」，非直接观测**：`crust_type` 是 ETOPO1 水深的 OCB 启发式；
> `boundary_type` 是 `detect_boundaries` 从真实欧拉极的相对运动**推导**的。它们都源自真实输入
> （ETOPO1 + PB2002），不是合成构建，但也不是观测。**可替换的真实数据集**：
> - 地壳类型 → **CRUST1.0**（Laske 2013，1° 全球地壳类型/厚度，igppweb.ucsd.edu/~gabi/crust1.html）
> - 边界类型 → **PB2002 `steps.dat`**（5819 段边界，含 7 类手工分类 OTF/OSR/SUB/CRB/CTF/CCB）
> 二者均可下载，属可选升级（当前 OCB + 欧拉极推导已够参考用）。

### 2.3 GSHHG 水掩膜（`import_earth_watermask.py`）

- **URL**：`https://www.soest.hawaii.edu/pwessel/gshhg/gshhg-shp-2.3.7.zip`
- **格式**：ESRI shapefile（自写极简 `.shp` 解析器，无额外依赖），用 intermediate 分辨率的
  L1（岸线/陆地）+ L2（湖泊）+ L5（南极冰缘）。南极洲的**陆地由冰缘 L5 界定**（L1 是基岩岸线，
  冰盖覆盖后基岩岸线多在海底），需把 L5 并入陆地多边形，否则南极洲整块被判成海洋。
- **流程**：GSHHG 5 级层级（ocean=0/land=1/lake=2/…）→ `classify_ocean_land` 逐 cell 判定 →
  内陆湖泊按面积分档（阈值 = 海洋调节尺度² = 60 000 km²）：里海/红海/黑海 → `ocean`，
  死海/吐鲁番 → `land`。红海/黑海在 GSHHG 岸线里已通过窄海峡连通为海洋，**与 200k 网格
  分辨率无关**（海峡不会被低精度堵死）。
- **纯函数**：`water_bodies.py`（`read_shp_polygons`、`points_in_rings`、`rings_area_km2`、
  `classify_ocean_land`）。

### 2.4 NCEP/GPCP/Beck 气候观测（`import_earth_climate.py`）

- **Köppen**：Beck et al. (2018) Present Köppen-Geiger，5 arc-min
  （`https://doi.org/10.1038/sdata.2018.214`，figshare 下载，CC-BY）。
- **温度**：NCEP/NCAR Reanalysis 1 `air.mon.ltm.nc`（2.5° 月均气候态，NOAA PSL）。
- **降水**：GPCP v2.3 `precip.mon.mean.nc`（2.5° 月均，NOAA PSL，需算 12 月气候态）。
- **海平面气压**：NCEP/NCAR Reanalysis 1 `slp.mon.ltm.nc`（2.5° 月均，NOAA PSL）。

**流程**：四个观测数据采样到 cell 中心（Beck 最近邻、NCEP/GPCP/SLP 双线性）→ 写
`cvt_mesh.json` 的 per-cell 字段（`koppen_class`/`temperature_C`/`precipitation_mm`/
`temperature_hottest/coldest_month_C`/`wind_east/north_m_s`/`distance_to_coast_km`）+
`climate_monthly.msgpack`（`t_monthly`/`p_monthly`/`pressure_monthly`，量化 int16，与
`export._quantize_int16` 同格式，月份按 3 月春分起排序）→ 次要导出
（`koppen.json`/`temperature.png`/`precipitation.png`/`climate_metadata.json`）。

> 派生字段来源：最热/最冷月 = NCEP 月均 max/min；距岸距离 = `_graph_distance_to_coast`
> （`water_class` 图 Dijkstra）；风 = NCEP `uwnd/vwnd.mon.ltm.nc` 年均。
> **风是 sigma 0.995（~40m）近地面风**，比 10m 风系统偏弱 ~2–3 倍（NCEP derived surface
> 无 10m 风）；量级仅供参考，方向正确。SST 异常 / 洋流是引擎模拟专属，真实观测无此概念，
> 保持 None。

> **earth 基础世界从不 build 气候**：它的气候字段是**真实观测**，不是引擎模拟。验证时用它
> 作 ground truth 去对比 nacrea 等生成世界的模拟精度（见 climate-validation.md）。

---

## 3. 导入命令（一次性重建 earth）

```bash
uv run python scripts/import_earth_elevation.py \
    --output-dir private/worlds/earth/maps/planet_earth \
    --resolution 4096x2048 --mesh-nodes 200000 --seed 42 --skip-download

uv run python scripts/import_earth_tectonics.py \
    --output-dir private/worlds/earth/maps/planet_earth

uv run python scripts/import_earth_watermask.py \
    --output-dir private/worlds/earth/maps/planet_earth

uv run python scripts/import_earth_climate.py \
    --output-dir private/worlds/earth/maps/planet_earth
```

> 日常在 `private/worlds` 迭代；发版前同步到 `data/worlds` 并 commit（LFS 纪律见根 CLAUDE.md）。

---

## 4. 数据模型字段

四个导入脚本填充 `VoronoiCell`（`src/dreamulator/map/models.py`）的以下字段：

| 字段 | 来源 | 值 |
|------|------|-----|
| `elevation` | ETOPO1 | 米（绝对高程） |
| `plate_id` / `crust_type` / `boundary_type` | PB2002 | 真实板块 / 地壳 / 边界类型 |
| `water_class` | GSHHG | `"ocean"` / `"land"`（权威海陆判据，供气候+前端渲染） |
| `koppen_class` / `temperature_C` / `precipitation_mm` | NCEP/GPCP/Beck | 真实气候（年均温度 / 年降水 / Köppen） |

`water_class` 是**权威海陆判据**，替换了 `elevation >= 0` 符号判定。前端
（`layerBakes.ts`、`MapCellInspector.tsx` 等）用 `water_class` 决定蓝/绿着色；
气候引擎的 `is_land` 用它区分陆/海。

---

## 5. 耐久性护栏

earth 的 `terrain_config.yaml` 设 `elevation_source: imported`，地质引擎
（`engine/geological.py`）检测后**跳过合成管线**，防止 `build earth --only geological`
用合成地形覆盖已导入数据——`d7384dc`「双世界全量重建」曾因此把 ETOPO1 高程覆盖成合成地形。

---

## 6. 已知限制

- **海岸 cell 采样**：`water_class` 用 cell 中心点判定，~26% 陆地（真实 ~29%），比高程符号
  （~29.5%）略低，源于海岸 cell 中心落在水面。改用 land fraction 是后续优化。
- **小内陆水体**：面积阈值把死海等小湖判为 `land`（气候影响可忽略）；里海/红海/黑海判为
  `ocean`。完整区分「内陆水 vs 干盆地」仍需水掩膜数据集（GSHHG 已提供）+ 面积分档。
- **气候观测分辨率**：NCEP/GPCP/SLP 是 2.5°（~280 km），比 200k 网格（~1°）粗，高海拔细节
  （珠峰等）被平均掉；Beck Köppen 是 5 arc-min（高分辨率，与温度/降水分辨率不一致）。要逐 cell
  高精度需换 ERA5（0.25°）或 WorldClim（1 km），属可选升级。

---

## 7. 相关文档

- [climate-validation.md](climate-validation.md) — 气候验证的**观测参考数据**（ERA5/GPCP/Beck Köppen），
  与本文的「输入数据」互补。
- [plate_tectonics.md](../../knowledge/geology/plate_tectonics.md) — PB2002 与 OCB 地壳分类的知识条目。
- [map-workflow.md](../../usage/map-workflow.md) — §10「导入外部高度图」与通用导入按钮。
- 竞品参照：[competitor-analysis.md](../competitor-analysis.md) 气候层（ExoPlaSim/climlab）。
