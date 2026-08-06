# 气候验证工作流

气候引擎对真实地球观测数据验证的**操作步骤**：导入真实高程、下载参考数据、
运行验证、保存报告。

设计与原理见 [../design/climate-validation.md](../design/climate-validation.md)：
数据源清单（§2）、验证指标说明（§5）、已知限制（§6）、多线证据策略（§7）。

---

## 1. 导入真实地球高程（必需）

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

## 2. 下载 Beck et al. 2018 Köppen 地图（可选）

完整 Köppen 验证需要 Beck et al. (2018) 的全球气候分类图。

```bash
# 下载（~10 MB GeoTIFF）
curl -L \
    "https://figshare.com/ndownloader/files/12407516" \
    -o data/earth/Beck_Koppen_2018.tif

# 转换 GeoTIFF → dreamulator JSON 格式
uv run python scripts/convert_koppen_map.py \
    data/earth/Beck_Koppen_2018.tif \
    --output data/worlds/earth/layers/climate/reference/koppen_obs.json \
    --width 2048 --height 1024
```

## 3. 下载 ERA5 温度数据（可选）

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

## 4. 下载 GPCP 降水数据（可选）

```bash
# GPCP v2.3 月均降水（~3 MB，无需 API key）
curl \
    "https://downloads.psl.noaa.gov/Datasets/gpcp/precip.mon.mean.nc" \
    -o data/earth/GPCP_precip_mon_mean.nc
```

---

## 5. 运行验证

### 5.1 快速验证（推荐首次运行）

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

### 5.2 保存验证报告

```bash
uv run python scripts/validate_climate.py earth \
    --branch terrain-dev \
    --output-dir reports/climate/
```

生成 `reports/climate/climate_validation.json`。
