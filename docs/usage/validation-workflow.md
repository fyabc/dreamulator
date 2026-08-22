# 气候验证工作流

气候引擎对真实地球观测数据验证的**操作步骤**：导入真实高程、下载参考数据、
运行验证、保存报告。

设计与原理见 [../design/climate-validation.md](../design/climate-validation.md)：
数据源清单（§2）、验证指标说明（§5）、已知限制（§6）、多线证据策略（§7）。

---

## 预下载验证数据

首次运行时，ETOPO1（~400 MB）和 Beck Köppen（~68 MB）会自动下载到系统临时目录。
如需**离线运行**或**预下载**，执行：

```bash
uv run python scripts/download_validation_data.py
```

下载完成后可离线运行：
```bash
uv run python scripts/import_earth_elevation.py --skip-download
uv run python scripts/convert_koppen_map.py
uv run dreamulator climate validate earth --spatial
```

---

## 测试体系一览

气候验证按成本和依赖性分四层，全部位于 `tests/validation/`：

| Tier | 文件 | 内容 | 数据依赖 | 耗时 | CI |
|---|---|---|---|---|---|
| **T3 物理合理性** | `test_physical_plausibility.py` | 7 纯理论断言（单调性、无大气极限、倾角振幅）+ 3 xfail（未实现物理） | 无 | < 1s | ✅ 每次 push |
| **T2 太阳系端元** | `test_end_members.py` | Venus 温室 / Mars 冰封 / 裸岩黑体 / gaia-m HZ 宜居性 | 无（合成网格） | < 1s | ✅ 每次 push |
| **T1 回归门** | `test_regression.py` | gaia-m 200k 基线对比：温度、降水、Köppen 组分布、陆地占比 | 已提交的 gaia-m CVT mesh | ~90s | ❌ `@pytest.mark.slow`（手动触发） |
| **T1 现代地球** | `dreamulator climate validate`（CLI） | Earth DEM → Köppen/ERA5/GPCP 对比（zonal mean + cell-by-cell） | ETOPO1 (~400 MB) + Beck/ERA5/GPCP | ~60-120s | ❌ 需网络 + 参考数据下载 |

**运行速查**：

```bash
# 快速测试（每次 CI 自动跑）
pytest tests/validation/ -m "not slow"

# 完整回归（代码评审时手动触发）
pytest tests/validation/ -m slow -v

# 现代地球验证（需先准备数据，见 §1-4）
dreamulator climate validate earth --dataset all
```

**标记说明**：
- `@pytest.mark.slow` — 默认被 `pyproject.toml` 的 `addopts` 排除，需显式 `-m slow` 运行
- `@pytest.mark.xfail` — 预期的失败（引擎尚未实现的物理），实现后从 xfail → XPASS 报警

**基线快照**：`tests/validation/baselines/gaia-m-200k.json`（schema v1）。
当引擎改动导致指标有预期内变化时，重新生成基线：
```bash
uv run python tests/validation/baselines/generate_baseline.py gaia-m --planet satellite_gaiam
```

---

## 1. 导入真实地球高程（必需）

```bash
# 安装验证脚本依赖（xarray, netCDF4, tifffile）
uv sync --extra validation

# 自动下载 ETOPO1 (~400 MB)，生成 elevation.png + CVT mesh
uv run python scripts/import_earth_elevation.py

# 指定输出目录和分辨率
uv run python scripts/import_earth_elevation.py \
    --output-dir data/worlds/earth/layers/geological/input/maps/earth \
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

完整 Köppen 验证需要 Beck et al. (2018) 的全球气候分类图。转换脚本会自动下载
Beck 图（或读缓存），对 `climate-dev` 分支的 200k Earth mesh 逐 cell 采样，输出
`koppen_obs.json` 到 `maps/planet_earth/`（与 mesh 并排）。

```bash
# 自动下载 + 转换（对 climate-dev 200k mesh 采样）
uv run python scripts/convert_koppen_map.py

# 或显式指定 GeoTIFF / mesh / 输出
uv run python scripts/convert_koppen_map.py \
    --tif path/to/Beck_KG_V1.zip \
    --mesh data/worlds/earth/branches/climate-dev/maps/planet_earth/cvt_mesh.json \
    --output data/worlds/earth/branches/climate-dev/maps/planet_earth/koppen_obs.json
```

> `koppen_obs.json` 已加入 `.gitignore`（可再生，不入库）；新 clone 需先运行
> `scripts/convert_koppen_map.py` 生成本地参考文件，否则 Köppen 诊断会提示
> "koppen_obs.json not found"。

## 3. 下载 NCEP/NCAR 温度数据（可选）

参考纬向温度剖面改用 **NCEP/NCAR Reanalysis 1**（免费，无需 API key）。
长期月均温（12 个月气候态，~650 KB）：

```bash
curl "https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/surface/air.mon.ltm.nc" \
    -o data/earth/NCEP_air_mon_ltm.nc
```

> ERA5（Copernicus CDS，需注册 + ~5GB）与 NCEP 纬向形态差 <0.5°C；NCEP 免费零门槛，足够作形状基准。

## 4. 下载 GPCP 降水数据（可选）

```bash
# GPCP v2.3 月均降水（~20 MB，无需 API key）
curl "https://downloads.psl.noaa.gov/Datasets/gpcp/precip.mon.mean.nc" \
    -o data/earth/GPCP_precip_mon_mean.nc
```

> **纬向参考数组的生成**：`validate_climate.py` 里的 `_ZONAL_TEMP_REF` /
> `_ZONAL_PRECIP_REF` 是**硬编码**的 2° 纬向均值（90N→88S），由上述原始数据
> 一次性算出。重生成脚本见 `scripts/generate_validation_reference.py`。

---

## 5. 运行验证

### 5.1 快速验证（推荐首次运行）

```bash
# 对 climate-dev 分支运行快速验证
dreamulator climate validate earth --branch climate-dev

# 对主世界运行
dreamulator climate validate earth

# 仅验证温度（ERA5）
dreamulator climate validate earth --dataset era5

# 仅验证降水（GPCP）
dreamulator climate validate earth --dataset gpcp

# 仅验证 Köppen 分类（Beck 2018）
dreamulator climate validate earth --dataset beck2018 --spatial

# 保存验证报告
dreamulator climate validate earth --output-dir reports/climate/
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
dreamulator climate validate earth --output-dir reports/climate/
```

生成 `reports/climate/climate_validation.json`。

### 5.3 回归测试（gaia-m 200k 基线）

```bash
# 生成/更新基线快照
uv run python tests/validation/baselines/generate_baseline.py gaia-m \
    --planet satellite_gaiam

# 运行回归对比（标记为 slow，默认 CI 跳过）
uv run pytest tests/validation/test_regression.py -m slow -v
```

基线快照位于 `tests/validation/baselines/gaia-m-200k.json`，
包含温度、降水、Köppen 分类、陆地占比的全局指标。
回归测试加载提交的 200k CVT mesh，运行气候模拟，逐项对比基线。

---

## 6. 诊断脚本（区分引擎 bug vs 参数调参）

除了上面的验证 CLI（综合评分），还有三个**交互式诊断脚本**，用于在"引擎 bug"与
"参数待微调"之间做二分。核心原则：**现代地球是唯一有「标准答案」的基准**
（Beck 2018 / ERA5 / GPCP）；系统性偏差若在地球与 gaia-m 上都出现 → 引擎 bug，
只在 gaia-m 出现 → 参数微调。

| 脚本 | 内容 | 何时用 |
|---|---|---|
| `scripts/diagnose_koppen_spatial.py` | 经纬网格 + 两极合并的 Köppen 空间准确率热图（逐 bin 排序） | 找出空间上最差/最好的区域 |
| `scripts/diagnose_latitudinal_profile.py` | 5° 分带、海陆分离的纬向 T/P 剖面 vs ERA5/GPCP，逐带偏差表 + **形状(引擎) vs 幅度(参数)** 判读 | 判断纬向梯度形状对不对 |
| `scripts/diagnose_koppen_confusion.py` | 完整混淆矩阵 + 逐群 precision/recall/f1 + top 混淆对 + BWk/ET 调参目标验证 | 找出哪类 Köppen 最易错、错成哪类 |

```bash
uv run python scripts/diagnose_koppen_spatial.py
uv run python scripts/diagnose_latitudinal_profile.py
uv run python scripts/diagnose_koppen_confusion.py
```

> **说明**：三个脚本默认跑在 `climate-dev` 分支的 **200k** Earth 网格上（与地球
> 海陆分布一致），`koppen_obs.json` 参考以相同 200k mesh 生成、存于
> `maps/planet_earth/`（与 mesh 并排）。cell-by-cell 准确率（~27%）低于分布匹配
> （~54%）——这是两个不同指标，空间准确率天然更低。诊断结论以**相对对比**
> （调参前后、地球 vs gaia-m）为准。
