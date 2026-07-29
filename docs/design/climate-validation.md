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

### 3.1 导入真实地球高程（必需）

```bash
# 安装验证脚本依赖（xarray, netCDF4, tifffile）
uv sync --extra validation

# 自动下载 ETOPO1 (~400 MB)，生成 elevation.png + CVT mesh
uv run python scripts/import_earth_elevation.py

# 指定输出目录和分辨率
uv run python scripts/import_earth_elevation.py \
    --output-dir private/worlds/earth/layers/geological/input/maps/earth \
    --resolution 2048x1024 \
    --mesh-nodes 32768

# 跳过下载（使用已缓存的文件）
uv run python scripts/import_earth_elevation.py --skip-download --skip-mesh
```

**输出文件**：
- `elevation.png` — 16-bit PNG 高度图（2048×1024）
- `cvt_mesh.json` — CVT 网格（32768 cells），每个 cell 的 elevation 从真实 DEM 采样
- `map.yaml` — 地图元数据
- `metadata.json` — 数据来源 + 编码参数

### 3.2 下载 Beck et al. 2018 Köppen 地图（可选）

完整 Köppen 验证需要 Beck et al. (2018) 的全球气候分类图。

```bash
# 下载（~10 MB GeoTIFF）
curl --proxy http://127.0.0.1:10808 -L \
    "https://figshare.com/ndownloader/files/12407516" \
    -o data/earth/Beck_Koppen_2018.tif

# 转换 GeoTIFF → dreamulator JSON 格式
uv run python scripts/convert_koppen_map.py \
    data/earth/Beck_Koppen_2018.tif \
    --output data/worlds/earth/layers/climate/reference/koppen_obs.json \
    --width 2048 --height 1024
```

> `convert_koppen_map.py` 将在后续版本中提供。当前可使用快速模式跳过此步骤。

### 3.3 下载 ERA5 温度数据（可选）

```bash
# ERA5 需要 Copernicus CDS API key (免费注册)
# 安装 CDS API
uv pip install cdsapi

# 下载 1981–2010 月均温
python -c "
import cdsapi
c = cdsapi.Client()
c.retrieve('reanalysis-era5-single-levels-monthly-means', {
    'product_type': 'monthly_averaged_reanalysis',
    'variable': '2m_temperature',
    'year': [str(y) for y in range(1981, 2011)],
    'month': [str(m).zfill(2) for m in range(1, 13)],
    'time': '00:00',
    'format': 'netcdf',
}, 'data/earth/ERA5_t2m_1981-2010.nc')
"
```

### 3.4 下载 GPCP 降水数据（可选）

```bash
# GPCP v2.3 月均降水（~3 MB，无需 API key）
curl --proxy http://127.0.0.1:10808 \
    "https://downloads.psl.noaa.gov/Datasets/gpcp/precip.mon.mean.nc" \
    -o data/earth/GPCP_precip_mon_mean.nc
```

---

## 4. 运行验证

### 4.1 快速验证（推荐首次运行）

```bash
# 对 climate-dev 分支运行快速验证
uv run python scripts/validate_climate.py earth --branch climate-dev

# 对主世界运行
uv run python scripts/validate_climate.py earth
```

**输出示例**：
```
Validating climate engine against real Earth observations...
  World: earth  Planet: earth
  Mesh: 32768 cells

============================================================
1. Temperature Validation (zonal mean vs ERA5)
------------------------------------------------------------
  RMSE:  2.3 °C  (threshold: 5.0 °C)
  Bias:  +0.8 °C
  R²:    0.94
  Result: ✅ PASS

============================================================
2. Precipitation Validation (zonal mean vs GPCP)
------------------------------------------------------------
  RMSE:  420 mm/yr  (threshold: 800 mm/yr)
  Bias:  -120 mm/yr
  R²:    0.78
  Result: ✅ PASS

============================================================
3. Köppen Classification Validation (vs Beck et al. 2018)
------------------------------------------------------------
  Match rate: 71%  (threshold: 55%)
  Group R²:   0.92
  Group errors: {'A': +3.2, 'B': -5.1, 'C': +1.8, 'D': -0.5, 'E': +0.6}
  Result: ✅ PASS

============================================================
4. Land Fraction Check
------------------------------------------------------------
  Simulated: 29.1%  (Earth: 29.0%)
  Result: ✅ PASS

============================================================
✅ OVERALL: Climate engine VALIDATED against Earth observations
============================================================
```

### 4.2 保存验证报告

```bash
uv run python scripts/validate_climate.py earth \
    --branch terrain-dev \
    --output-dir reports/climate/
```

生成 `reports/climate/climate_validation.json`。

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
