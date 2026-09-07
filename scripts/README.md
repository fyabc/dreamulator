# scripts/ 目录说明

按域分组，共 40 个脚本。一律在仓库根目录以 `uv run python scripts/<组>/<脚本>.py` 运行。
新增脚本放入对应组；跨组通用工具放 `dev/`。本说明只到目录级——单个脚本的用途看其
模块 docstring，气候诊断的方法论见 `docs/design/proposals/climate-layer-improvement.md` §8
与 `docs/usage/climate-validation-workflow.md`。

## climate/ — 气候验证与诊断（22 个）

围绕 earth/climate-dev 验证环与气候攻关的诊断脚本群。

- `validate_climate.py` — 主验证入口：纬向 T/P vs ERA5/GPCP + Köppen 分布/空间 vs Beck + 陆地比。
- `station_diagnostics.py`、`diagnose_monsoon_regional.py` — 26 基准站 / 8 季风区逐月对照
  （**读构建产物，秒级**；先 `dreamulator build --only climate` 再跑）。
- `diagnose_*.py` — 各攻关项专用诊断（Köppen 混淆/空间、纬向剖面、降水预算、风场散度、
  气压异常、雨影、冬季风/冬季气压、大陆度与干燥度扫掠、海洋平流、季节分解、副热带高压等；
  多数**重跑模拟**，~5 min/个，注意 `--world-dir data/worlds`）。
- `climate_diff.py` — 两次构建的差异对比（全局摘要 + 纬度带平均 + Top-N 变化细胞）。
- `convert_koppen_map.py` — Beck Köppen GeoTIFF → 网格观测参考。
- `detect_ocean_bottlenecks.py` — 海盆连通瓶颈探测（洋流求解上下文）。

## earth/ — 真实地球数据导入与验证参考（8 个）

earth 基础世界是**导入世界**（不走 build 管线）；这组把真实观测采样到 CVT 网格。
发布时 `release/publish_world_data.py` 按依赖序自动调用四个 importer。

- `import_earth_elevation.py` → `import_earth_tectonics.py` → `import_earth_watermask.py` →
  `import_earth_climate.py` — 高程（ETOPO1）/ 板块与地壳（PB2002+CRUST1.0）/
  水掩膜（GSHHG）/ 气候（NCEP+GPCP+Beck+SODA 洋流）。
- `download_validation_data.py` — 预下载 ETOPO1、Beck Köppen、SODA 洋流月度气候态（`--skip-soda` 可跳）。
- `generate_validation_reference.py`、`generate_monthly_reference.py`、`generate_lgm_reference.py` —
  纬向气候态 / 月度 / LGM 验证参考数据生成。

## astro/ — 天文 N 体与恒星诊断（4 个）

- `rebound_nbody.py` — REBOUND 自旋-轨道积分（轨道稳定性、Laplace 共振角）。
- `rebound_scan.py`、`rebound_phase_scan.py` — 参数扫描 / 共振相位扫描。
- `diagnose_stellar_physics.py` — 恒星物理公式（质光关系、演化时标）诊断。

## release/ — 发布与静态导出（2 个）

- `publish_world_data.py` — 发版一条命令：构建全部世界（earth 走 importer）+ 打包 +
  上传 GitHub Release（固定 tag `worlds-data`）；`deploy-pages.yml` 消费该产物。
- `export_static.py` — 静态站数据导出（`frontend` 的 `npm run export` / `build:static` 调它；
  `deploy-pages.yml` 直接运行）。**移动此文件须同步 CI 的 path trigger 与 package.json。**

## dev/ — 开发工具（4 个）

- `check_doc_refs.py` — 文档↔代码引用审计（`docs/design/pipelines/` 的 file:line 与反引号符号）；
  **pre-push 钩子对 main 强制**（`.git/hooks/pre-push`，钩子内路径指向本组）。
- `profile_build.py` — 构建性能剖析（产出 `build_profile.json`，见 `docs/usage/profiling.md`）。
- `prepare_civmap_data.py` — 文明地图底图数据下载与预处理。
- `generate_planet_heightmap.py` — 外部高度图生成（世界创作辅助，配合地图导入工作流）。

## 约定

- **仓库根推导**：脚本内一律 `Path(__file__).resolve().parents[2]`（或向上探测 `pyproject.toml`）；
  新增脚本下移层级时记得同步。
- **组内兄弟导入**：climate/ 内诊断脚本经 `sys.path.insert(0, 本目录)` 复用
  `station_diagnostics` 的站点表——跨组复用请改走 `dreamulator` 包。
- **数据文件位置**：观测数据缓存在系统 temp（ETOPO1/Beck）与 `private/tmp/climatology/`
  （NCEP/GPCP/SODA，gitignored）。
