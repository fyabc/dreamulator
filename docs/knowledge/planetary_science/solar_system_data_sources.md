# 太阳系天体数据源指南（实测验证版）

> 2026-09-21 整理，来自太阳系参照天体导入（UCC-01 4d：Mars / Moon / Venus /
> Titan 并入 earth root）的实际抓取经验。所有 URL 当日实测；「坑」均为当场踩过。
> 消费方 = `scripts/solar/` 导入器与 `scripts/earth/`；数据缓存约定
> `private/tmp/solar/`（gitignored）。

给一颗真实天体找数据时按四类需求走：**物理/轨道参数**（进 stellar.yaml 型目录）、
**地形**（DEM → CVT mesh）、**气候**（温度/降水气候态 → UCC 描述量）、**表面覆盖**
（水/冰/湖掩膜）。下面按类给来源层级与实测结论。

## 1. 物理与轨道参数

**首选：NASA NSSDC Planetary Fact Sheet**（`https://nssdc.gsfc.nasa.gov/planetary/factsheet/`）。
行星页是 `<name>fact.html`；卫星页命名不规则——木星卫 `joviansatfact.html` 实测可用，
而海王星卫 `neptune_sat_fact.html` / `neptunesatfact.html` 均 404（Triton 需走
JPL + Wikipedia 兜底）。字段给质量（10²⁰ kg）、平均半径、半长轴、偏心率、
**倾角（对卫星 = 黄道基准**，伽利略四星 0.04/0.47/0.18/0.19°）、轨道周期、
几何反照率；自转栏 "S" = 同步自转（周期 = 轨道周期）。

**质量/半径最精：JPL SSD `Planetary Satellite Physical Parameters`**
（`https://ssd.jpl.nasa.gov/sats/phys_par/`），给 GM（km³/s²）与 mean radius。
换算：M = GM/G（G = 6.67430×10⁻¹¹ m³ kg⁻¹ s⁻²，GM 先 ×10⁹ 换 SI）；M⊕ = M/5.9722×10²⁴。
同站 `elem` 页（轨道根数）对网页抓取极不友好（表格机器提取残缺），别指望。

**Wikipedia infobox 只作兜底，两个实锤坑**：
① **倾角基准面混乱**——Io/Europa infobox 给 2.213°/1.791°，那是**木星赤道/拉普拉斯
面**基准；黄道基准是 0.04°/0.47°（以 Fact Sheet 为准）。Triton infobox 首选值
129.812° 是**海王星赤道**基准，黄道基准 = 156.865°（逆行轨道 >90° 表达）。
本仓库 stellar.yaml 约定 = **黄道基准**（与 satellite_moon 条目一致）。
② **反照率分几何/Bond**——Titan 几何 0.22、Bond 0.265；stellar.yaml 的 albedo
字段沿用 Moon 条目约定 = 几何反照率。

Ω/ω/M（升交点/近心点幅角/平近点角）在汇总页普遍缺失；对近圆近共面轨道
（e<0.01、i<0.5°）这三个角在数据精度内简并，取 0 并注释声明是诚实做法
（root 永不 build，目录只服务展示与天文上下文）。

## 2. 地形（DEM）

| 天体 | 源 | 直链 | 格式与坑 |
|------|----|------|----------|
| Mars | MOLA MEGDR 4ppd（PDS Geosciences） | `pds-geosciences.wustl.edu/mgs/urn-nasa-pds-mgs_mola_topography_derived/meg004/megt90n000cb.img`（2 MB，.lbl 同目录） | 裸 `>i2` 大端 720×1440；**col 0 = 0°E**（非 −180°，SAMPLE_PROJECTION_OFFSET=720.5 → 像素中心配准）；单位米、areoid 基准 |
| Moon | LDEM_4（NASA SVS Moon Kit） | `svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/ldem_4.tif`（4 MB） | GeoTIFF float32 720×1440；**单位是 km**（×1000 换米）；1737.4 km 均半径基准。USGS 118 m 全球版 8 GB+，别碰 |
| Venus | Magellan Global Topography 4641 m v02（USGS planetarymaps） | `planetarymaps.usgs.gov/mosaic/Venus_Magellan_Topography_Global_4641m_v02.tif`（64 MB） | GeoTIFF int16 4096×8192；**−32768 = NODATA**（±3.8° 极区无雷达覆盖，需列向最近有效值填充）；geotag 读 ModelPixelScale/ModelTiepoint |
| Titan | 无全球实测地形 | —（Cassini SARTopo/高度计仅局部） | 可用 GCM 自带地形（TAM `dtd`，~5.6°）或参考椭球 |

工程要点：GeoTIFF 用 **tifffile**（已是项目依赖）就够——USGS 行星镶嵌都是简单
圆柱投影，地理配准从 geotag 或已知边界手推，不需要 rasterio/GDAL。
**任何新 DEM 第一动作 = 地标方位探针**：用已知地标（Olympus Mons 226°E +20 km、
Hellas 70°E −8 km、Maxwell Montes 5°E +10 km、SPA 盆地 −7 km）钉死三件事——
row 0 是北还是南、col 0 是 0°E 还是 −180°、单位是 m 还是 km。四种组合都会遇到。

## 3. 气候

**LMD 行星气候数据库（MCD = Mars / VCD = Venus）**：完整 NetCDF 档需邮件注册
（复杂度低：邮箱/表单，无机构审批）；**免注册 Web 接口**可批量抓 2D ASCII 切片
（POST 配方固化在 `scripts/solar/fetch_lmd_slices.py` docstring）。实测坑：
① **MCD `averaging=loct`（日均）可用**，头注释 "Diurnal mean over all local times"
可验证；**VCD 同参数会无限挂起**——换固定地方时切片 + curl `--max-time` 护栏。
② 输出是**显示网格**（MCD 64 经×48 纬、VCD 96×96），非 GCM 原生分辨率。
③ ASCII 的经度行标签是 floor 取整，精确轴用 `linspace(0, 360, n)` 重构；
纬度列头是全精度。④ 火星无显式降水率变量；水相关有 `surf_h2o_ice`（表面霜
kg/m²）等可作诚实注脚。

**LRO Diviner（Moon 表面温度，观测级）**：无紧凑现成气候态文件——GCP 累积产品
（PDS `LRO-L-DLRE-5-GCP-V1.0`，Williams et al. 2017）= **18 个纬度带 × 156 MB
ASCII .tab**（~2.8 GB，直链免注册），列 `clon/clat/ltim/t3…t9/tbol`（0.5° ×
0.25 h 地方时）；−9999 = 无观测、负亮温 = 低于通道灵敏度。用 `tbol`
（玻尔兹曼亮温）作表面温度代理并声明；聚合成本地 12 × 2 h 地方时箱。
GHRM GeoTIFF（3.15 GB/张且只有午夜时刻）不实用。

**GCM 输出开放存档看 Zenodo**：TAM（Titan，Yale Lora 组）全 CC-BY-4.0；
水文 run（Faulk/Lora，Zenodo 3473571）**单文件同时含 tsurf/precip/qsurf/dtd**
——优先单一一致源，别跨 run 拼接 T 和 P。时间轴是地球日；`average_DT` 给每步
窗口长度，bin 聚合率变量要 **DT 加权平均再乘箱窗**（对步求和会把记录年数
乘进去——当场踩过的 10× bug）。

## 4. 通用工程经验

- curl 一律带 `--max-time`（CGI 静默挂起没有超时就是黑洞）；代理通过
  `--proxy <地址>` 命令行参数显式传入（脚本均有该参数；本地代理地址是
  机器特定信息，不入库），失败再裸连重试。
- 大文件下载实测带宽可行（156 MB/带数分钟），但要跑后台 + 落日志文件
  （管道接 tail 的后台任务会被 SIGPIPE 杀死——踩过）。
- **Provenance 纪律**：检索日期、产品版本、认知地位（观测 / GCM 气候态 = L4）
  写进导出文件与脚本 docstring，随数据走（ucc-review §6.2 层级语言）。
- 单位换算三处高频出错点：GM→kg、km→m（LDEM）、kg/m²→mm（按溶剂密度：
  水 1:1，液态甲烷 ÷422.6 kg/m³）。

## 相关文档

- `docs/knowledge/climatology/ucc_climate_descriptors.md` — UCC 描述量/分类语义
  （§8 有 Mars/Venus/Moon/Titan 演练与实测对照）
- `scripts/solar/` — 四导入器 + LMD 抓取器（README 有逐脚本说明）
- `data/worlds/earth/design-notes/` — 各天体 worked examples（脚本生成）
