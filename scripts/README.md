# scripts/ 目录说明

按域分组，共 61 个脚本。一律在仓库根目录以 `uv run python scripts/<组>/<脚本>.py` 运行。
新增脚本放入对应组；跨组通用工具放 `dev/`。本说明只到目录级——单个脚本的用途看其
模块 docstring，气候诊断的方法论见 `docs/design/proposals/climate-layer-improvement.md` §8
与 `docs/usage/climate-validation-workflow.md`。

## climate/ — 气候验证与诊断（31 个）

围绕 earth/climate-dev 验证环与气候攻关的诊断脚本群。

- `validate_climate.py` — 主验证入口：纬向 T/P vs ERA5/GPCP + Köppen 分布/空间 vs Beck + 陆地比。
- `station_diagnostics.py`、`diagnose_monsoon_regional.py` — 26 基准站 / 8 季风区逐月对照
  （**读构建产物，秒级**；先 `dreamulator build --only climate` 再跑）。
- `diagnose_*.py` — 各攻关项专用诊断（Köppen 混淆/空间、纬向剖面、降水预算、风场散度、
  雨影、大陆度与干燥度扫掠、海洋平流、季节分解等；多数**重跑模拟**，~5 min/个，
  注意 `--world-dir data/worlds`）。
- `climate_diff.py` — 两次构建的差异对比（全局摘要 + 纬度带平均 + Top-N 变化细胞）。
- `convert_koppen_map.py` — Beck Köppen GeoTIFF → 网格观测参考。
- `detect_ocean_bottlenecks.py` — 海盆连通瓶颈探测（洋流求解上下文）。
- `generate_climate_obs.py` — committed 逐格 obs 生成器：NCEP T/SLP/风 + GPCP P → `climate_obs.json`
  （年平、mesh-bound；重建后用本脚本重生成，替代旧无生成器的 ad-hoc 版）。
- `diagnose_climate_bias.py` — 逐格 T/P/风/Köppen 偏差审计（对 `climate_obs.json` + `koppen_obs.json`，
  全局/纬向带/区域/极端格 + Köppen agreement，秒级）。
- `diagnose_monsoon_dp_shape.py` — 季风 ΔP vs NCEP SLP 框对标（A 陆地-only/D 陆−海对比双口径 + g(W)/
  aridity-keep/`_dt_subsidence` 证伪，Stage C；读产物，秒级）。
- `diagnose_desert_wetness.py` — §5 沙漠过湿归因：默认存档模式（秒级，GPCP 海洋格 f(ΔSST) 对流门
  标定 + SST 距平结构核查）；`--ablation` 三引擎重跑（季风/κ 消融逐盒归因，~15 min）。
- `diagnose_lapse_moisture.py` — 递减率干湿维度可行性实验（读产物手算定点，不动引擎）。
- `ablate_heat_transport.py` — 热输送消融（§2.6③：三分支逐个关 ocean-currents/upwelling/
  maritime，隔离各机制对 T/P/D 的贡献；重跑气候，~15 min）。
- `build_bridge_branches.py`、`build_bridge_branches_nacrea.py` — Earth↔Nacrea 单参数桥接
  实验分支生成（fork astronomy 覆写自转/倾角/温室/光谱/通量/年长；分支已 gitignore）。
- `ucc_obs_descriptors.py` — UCC L2 数据集构建（earth root 观测月度序列 → 描述量 +
  Beck Köppen 参照列 + provenance，msgpack 进 private/reviews/）。
- `ucc_classify_experiments.py` — UCC 分类候选比较实验（分组候选/消融/扰动，profile
  v0/v1 冻结依据）。
- `ucc_examples_earth.py` — Earth worked examples 文档生成（~33 命名地点 + 未覆盖类的
  类中心点补位 → `data/worlds/earth/design-notes/ucc-worked-examples.md`；读 L2 数据集，秒级）。
- `ucc_examples_nacrea.py` — Nacrea 迁移语义夹具生成（全局分布 + 预期核对 + 命名地理锚点 +
  极值点 → `data/worlds/nacrea/design-notes/0010-ucc-migration-fixture.md`；解析 mesh，~1 min）。

## earth/ — 真实地球数据导入与验证参考（10 个）

earth 基础世界是**导入世界**（不走 build 管线）；这组把真实观测采样到 CVT 网格。
发布时 `release/publish_world_data.py` 按依赖序自动调用四个 importer。

- `import_earth_elevation.py` → `import_earth_tectonics.py` → `import_earth_watermask.py` →
  `import_earth_climate.py` — 高程（ETOPO1）/ 板块与地壳（PB2002+CRUST1.0）/
  水掩膜（GSHHG）/ 气候（NCEP+GPCP+Beck+SODA 洋流）。
- `download_validation_data.py` — 预下载 ETOPO1、Beck Köppen、SODA 洋流月度气候态（`--skip-soda` 可跳）。
- `generate_validation_reference.py`、`generate_spatial_reference.py`、`generate_monthly_reference.py`、
  `generate_lgm_reference.py` — 纬向 / 逐格 / 月度 / LGM 验证参考数据生成
  （`generate_spatial_reference.py` 输出前端 `spatialReference.ts`，供 ΔT/ΔP 逐格偏差图层）。
- `export_earth_yearly.py` — earth root 的 UCC 年度文件导出器：从**观测**月度序列直写
  `climate_yearly.msgpack`（描述量 + 当前 profile 分类，`data_source: "observation"`；
  root 永不 build 的 obs 侧对应物，已注册进 publish_world_data 导入链）。

## solar/ — 太阳系参照天体（6 个）

Mars / Moon / Venus / Titan 真实数据参照天体（UCC-01 4d）——**并入 earth root
（现实世界数据锚）作为额外 planet_ids**，不单开世界（用户裁决 2026-09-21；ID 沿用
stellar.yaml 约定：`planet_mars` / `satellite_moon` / `planet_venus` /
`satellite_titan`）。共享导入机制在 `src/dreamulator/import_solar_common.py`
（register_solar_planet / DEM→CVT mesh 地标校验 / climate_monthly 含 **bin_days
时间契约** / UCC yearly 支持 demand_model=None→MI）。**mesh cell 数按各天体数据源
精度定**：Moon 100k（GCP 0.5°）> Mars 10k（MCD ~5.7°）= Venus 10k（VCD ~1.9°）>
Titan 3k（TAM T21 5.6°）。数据为 GCM 气候态（L4 压力测试层，非观测真值；Moon
Diviner 为观测级地表温度例外），provenance 随导出文件走。原始数据缓存
`private/tmp/solar/`（Mars/Venus/Titan 缺失自动重下；Moon GCP 2.8GB 见脚本 docstring）。

- `fetch_lmd_slices.py` — LMD Web 接口免注册抓取器（MCD/VCD 通用：POST 配方 +
  txt 链接解析 + `--max-time` 护栏；**VCD 的 averaging=loct 挂起**，用
  `--averaging off` 固定地方时切片）。
- `import_mars.py` — MOLA 4ppd 地形（PDS IMG，地标校验）+ MCD v6.1 气候态
  （12 个 Ls 箱中心日均 ASCII 切片；P≡0 声明——现今无液态降水，霜层作注脚；
  bin = 火星月 57.25 地球日）。
- `import_moon.py` — LRO LDEM_4 地形（NASA SVS GeoTIFF，km→m）+ Diviner GCP
  18 带聚合（tbol 作 SPT 代理；**地方时分箱** 12×2h；观测级例外声明
  `temperature_kind: surface`；P≡0 真空、demand_model=None→MI）。
- `import_venus.py` — USGS Magellan 全球地形（极区 NODATA 列填充；Maxwell 9.9 km
  地标校验）+ VCD v2.3 固定 LT 切片；**热侧外推缺口活体演示**（Hamon 保留，
  provenance 响亮警告；知识文档 §8）。
- `import_titan.py` — TAM 耦合水文 run（Zenodo CC-BY 单一一致源：tsurf/precip/
  qsurf/dtd）；bin = 896 地球日（土星年 1/12）；P = mm 液态 CH₄；甲烷海
  qsurf>0.05m → water_class ocean；demand_model=None→MI（非水溶剂）。
- `ucc_examples_solar.py` — UCC worked examples 文档生成（`--planet mars|moon|
  venus|titan`：全局分布 + 世界要点注记 + 命名地貌地点 + 极值点 →
  `data/worlds/earth/design-notes/ucc-worked-examples-<body>.md`）。

## astro/ — 天文 N 体与恒星诊断（5 个）

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
- `profile_build.py` — 构建性能剖析（产出 `build_profile.json`，见 `docs/design/profiling.md`）。
- `prepare_civmap_data.py` — 文明地图底图数据下载与预处理。
- `generate_planet_heightmap.py` — 外部高度图生成（世界创作辅助，配合地图导入工作流）。

## 约定

- **仓库根推导**：脚本内一律 `Path(__file__).resolve().parents[2]`（或向上探测 `pyproject.toml`）；
  新增脚本下移层级时记得同步。
- **组内兄弟导入**：climate/ 内诊断脚本经 `sys.path.insert(0, 本目录)` 复用
  `station_diagnostics` 的站点表——跨组复用请改走 `dreamulator` 包。
- **数据文件位置**：观测数据缓存在系统 temp（ETOPO1/Beck）与 `private/tmp/climatology/`
  （NCEP/GPCP/SODA，gitignored）。
