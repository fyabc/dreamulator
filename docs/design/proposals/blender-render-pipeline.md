# Blender 高清渲染链（blender-render-pipeline）

> **状态**：MVP 已实现（`dreamulator export region` + `scripts/media/blender/region_still.py`，
> 2026-10-02）。本文档记录链路设计与数据包契约；全球尺度、程序细节增强、动画
> 镜头等后续扩展在「路线」节登记，实现后蒸馏进 `pipelines/`。

## 定位

前端 200k cell 的实时展示（~51 km/格的信息密度）对视频素材「用处不大、地位
尴尬」；视频计划（`private/plans/bilibili-video-plan.md` §四-B）的硬约束是
「全球/区域尺度镜头必须走 Blender，前端录屏只用于 UI/FUI 镜头」。本链路把
引擎产出的世界数据交给外部渲染器：**区域数据包 → bpy 脚本重建场景 → Cycles
渲染静帧/动画**，全链 CLI 可复现、不入库任何二进制工程（脚本重建工程模式）。

MVP 范围（用户 2026-10-02 裁决）：**纯数据直出**——只渲染引擎真实产出的高度
场与配色，不叠加程序化细节；细节增强（fBm/Gaea 侵蚀）属后续轮。样板区域 =
nacrea 永耀岛 (0, 0) 2500 km。

## 链路与数据包契约

```
dreamulator export region <world> --lat .. --lon .. --span-km ..
        │  (src/dreamulator/map/region_export.py)
        ▼
private/video/<world>-<lat>_<lon>_<span>km/     ← 不入 git；pack 根目录
  ├─ input/   引擎导出通道（下表）
  ├─ gaea-out/   Gaea 构建产物（见 gaea-video-chain.md）
  └─ color/      着色产物（export render --style satellite）
  input/
  ├─ height.meters.npy   float32 米值，主数据通道（bpy 精确读取，无色彩空间坑）
  ├─ height.png          16-bit，按区域 min/max 归一化，人看参考
  ├─ height.gaea.png     16-bit，海底按 --seafloor-clamp（默认 −400 m）预压平，
  │                      归一量程见 meta（Gaea 2.3 TD 上限 Height 10 km / Width 2400 km）
  ├─ color.png           地形配色裁剪（调色板单源 map/palettes.py，与前端一致）
  ├─ precipitation.mm.{npy,png}   年降水量 mm（pack v2 气候通道，Gaea 2 降雨 mask）
  ├─ temperature.C.{npy,png}      年均温 °C
  ├─ ice.m.{npy,png}              冰川厚度 m（无冰格为 0；雪线 mask 由下游导出）
  ├─ npp.gc_m2_yr.{npy,png}       Miami NPP gC/m²/yr（着色器的连续植被密度通道）
  ├─ headwaters.png               水量盈余区掩膜（P > Hamon PET；Gaea Rivers 的
  │                               Headwaters 输入，约束河流只从盈余区发源）
  ├─ glacier.mask.png             冰川活动掩膜（冰厚>0 ∪ 群系ice；Gaea Glacier 的
  │                               Reference 输入；Snow 输出建议导出供着色）
  ├─ koppen.{codes.npy,png}       uint8 类别码 + 调色板配色 PNG
  ├─ biome.{codes.npy,png}        同上（Whittaker 群系）
  └─ meta.json           见下
        │
        ▼
blender -b -P scripts/media/blender/region_still.py -- --datadir <pack> [--render out.png]
        │  (1 unit = 1 km，物理垂直比例默认 1.0)
        ▼
renders/*.png + scene.blend（同目录，可随时由脚本重建）
```

`meta.json` 字段：`pack_version`（4 = 方位等距窗口 + 统一千米/像素；
3 = 输出网格与引擎网格解耦 + 插值 + Gaea 变体；2 = 气候通道；1 = 仅高度与配色）、
`projection`（窗口投影，v4 起为 `azimuthal_equidistant`）、
`center_lat/lon`、`span_km`、`radius_km`、`grid{w,h}`（输出栅格分辨率，
`--out-res` 正方形，默认 2048）、`sampling`（采样口径说明：标量通道
在 cell 中心 Delaunay 三角网上 Clough-Tocher C1 插值并裁剪到所在三角形顶点值域
（防三次下溢产生假盆地）、中心保真；类别通道与配色
最近邻）、
`extent_km`、`km_per_px`、`elevation_m{min,max}`、`height_png_range_m`、
`height_gaea_png_range_m` 与 `seafloor_clamp_m`（Gaea 变体的归一量程与
压平深度）、`cell_pitch_km`（CVT 平均 cell 间距，供下游按 cell 尺度
自适应效果参数）、`sea_level_m`、`ocean_fraction`、`alignment_probe_max_offset_deg`、
`source`（world/planet/branch + mesh sha256 指纹，无时间戳——跨机可复现）、
`climate`（每个气候通道的 PNG 归一化区间 `png_range`、缺值像素数 `missing`；
Köppen 与群系另有 `legend` 类别码 → 类名映射，类别码在全网格按类名字典序
分配、跨区域稳定，legend 只列本窗口出现的类）。气候通道可用
`export region --no-climate` 关闭。所有通道共用同一输出网格
（`--out-res` 正方形，覆盖同一地理窗口），套准由构造保证；雪线不归档
为独立栅格，由下游从 `ice.m` 与 `temperature.C` 两通道导出。

## 区域窗口数学（局部方位等距，pack v4）

- 窗口是星球真实半径球面上以请求中心为切点的方位等距平面（x 东、y 北，
  千米），与全球画布链共用 `map/td_canvas.py` 的 `CanvasGeometry` 换算单源。
- 平面内 `|x| ≤ span/2`、`|y| ≤ span/2` 即窗口；中心距离在任何方位上都是
  真实公里数，窗口在任意纬度都是真实千米正方形（旧等距圆柱裁剪只在中心
  纬度近似成立，高纬东西向误差随跨度增大）。
- 极区中心与跨 ±180° 经线的窗口均可导出；只有 span 触及对跖点（πR）时才
  拒绝——那里方位等距投影本身退化。
- 输出栅格是窗口平面上的均匀网格（`extent_km = span_km`，
  `km_per_px = span/out_res`）；标量通道的 Clough-Tocher 插值同样在平面
  坐标（km）里做。旧 v3 包的等距圆柱像素盒（`pixel_box`）已退役。

## 已知数值口径（f32 tie-flip）

盘上 mesh 的分列存储（`STATIC_CELL_COLUMNS`）把 `x/y/z`/`elevation` 存为
float32，而 `elevation.png` 是构建期用内存 f64 网格栅格化的。区域包用盘上
mesh 重新 NN 栅格化，约 1% 像素的并列最近邻会翻到相邻 cell（孤立散点、多在
深海、量级几十米）。验收口径：与 elevation.png 的海陆符号一致率 ≥ 99.9%、
平均差 < 5 m 即判对齐（验证脚本 `private/research/2026-10-blender-region/`）。
回贴链（Gaea round-trip）将来比较时应对 cell 空间，勿对 PNG 逐字节。

## 与相邻链路的关系

- **Gaea 精化链**（`gaea-refinement.md`）：共享「区域选择 + 16-bit 导出」的
  接口词汇（refine_regions 的 bbox 语义、target_resolution）；球极投影腿
  落地后本链的极区拒绝自动解除。Blender 链不依赖 bake（读盘上 map 数据，
  只读不回写）。
- **地形 bake**（today 待办 4）：bake 冻结的是「外部编辑往返」的输入基座；
  本链是纯消费者，无交互。
- **资产管理约定**：正式 CLI 入 in-package（`dreamulator export region`，
  与 `export layers` 同族）；Blender 专属胶水入 `scripts/media/blender/`；
  数据包与渲染输出入 `private/video/<项目>/`（不入 git）；试验脚本入
  `private/research/<topic>/`。

## 硬件与渲染参数基线（2026-10-02 实测）

本机样例环境（8 核笔记本 CPU + RTX 3060 Laptop 6 GB，Blender 5.2.2 LTS）：
Cycles 设备自动降级 OptiX > CUDA > CPU；seed 固定 42 + OpenImageDenoise。
6 GB 显存 = 贴图预算硬顶（8k RGBA ≈ 268 MB、16k ≈ 1 GB 慎用）；区域网格
（数十万面）对 3060 是轻负载。浏览器/前端走 AMD 集显，与渲染不抢卡。

## 路线（登记不排期）

- 细节增强层：Gaea 侵蚀、fBm 位移/法线，或 terrain-diffusion 条件化细化
  （MIT，tiff-export 吃粗 GeoTIFF 高程+温度+降水通道 → 256× 上采样）。
  2026-10-05 调研通过并接受为管线方案（用户裁决：先用之，不够再改进）——
  nacrea 永耀岛 550 km 实测：海岸线符号一致率 97.5% @SNR 0.2、同 seed
  逐位确定、0.6 s/tile @3060 6 GB；注意其温度通道是海平面口径、条件须
  重采样到模型粗格 23 km/px。脚本与报告在
  `private/research/2026-10-terrain-diffusion/`。产品化形态 =
  `export region` 气候通道档 + 独立 venv 子进程调用（不 import 其代码）；
  「编造细节」需与纯数据渲染可区分（细化层独立成包，不覆盖原始通道）。
- 多图层数据包（temperature/precipitation/koppen 区域裁剪 + Blender 材质切换），
  服务气候叙事镜头。**每个场一个 `.npy`、不合并 `.npz`**（2026-10-02 裁决）：npz 的
  zip 头带时间戳会破坏逐字节复现，合并容器还牺牲逐层懒加载；外部工具（Gaea）的
  互通格式是 16-bit PNG/GeoTIFF/EXR，与 npz 无关。
- 相机动画（高空俯冲 / 火山口仰视看巨神星，bilibili-video-plan §四方案 A）。
- 云层场 / 夜灯贴图 / 红矮星大气 LUT（§四-B 缺口清单，均「新导出脚本即可」）。
- 全球整球渲染（8192×4096 贴图 + 整球网格，显存允许时）。

## 参考

- 需求 SoT：`private/plans/bilibili-video-plan.md` §四/§四-B/§五
- Gaea 链接口词汇：`docs/design/proposals/gaea-refinement.md` §2/§3/§6
- 区域导出实现：`src/dreamulator/map/region_export.py`、`src/dreamulator/cli_export.py`
- bpy 场景构建：`scripts/media/blender/region_still.py`
