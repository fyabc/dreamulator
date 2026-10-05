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
private/video/<world>-<lat>_<lon>_<span>km/     ← 不入 git
  ├─ height.meters.npy   float32 米值，主数据通道（bpy 精确读取，无色彩空间坑）
  ├─ height.png          16-bit，按区域 min/max 归一化，人看参考
  ├─ color.png           地形配色裁剪（调色板单源 map/palettes.py，与前端一致）
  └─ meta.json           见下
        │
        ▼
blender -b -P scripts/media/blender/region_still.py -- --datadir <pack> [--render out.png]
        │  (1 unit = 1 km，物理垂直比例默认 1.0)
        ▼
renders/*.png + scene.blend（同目录，可随时由脚本重建）
```

`meta.json` 字段：`center_lat/lon`、`span_km`、`radius_km`、`grid{w,h}`、
`pixel_box[x0,y0,x1,y1]`（全网格精确像素盒，消费方免猜 floor/ceil）、
`extent_km`、`km_per_px`、`elevation_m{min,max}`、`height_png_range_m`、
`sea_level_m`、`ocean_fraction`、`alignment_probe_max_offset_deg`、
`source`（world/planet/branch + mesh sha256 指纹，无时间戳——跨机可复现）。

## 区域窗口数学（等距圆柱裁剪）

- 1° 纬度 = πR/180 km（用 `map.yaml` 的真实 `radius_km`，nacrea = 6816.97；
  该字段是 MapMetadata 之外的额外字段，经 `read_radius_km` 直读 yaml）。
- 东西向半宽除以 cos(lat) 补偿等距圆柱的纬向拉伸——裁剪窗在中心纬度处
  按千米为正方形。
- **边界保护**：窗口触及 |lat| > 75° 或跨 ±180° 经线即拒绝（指路 Gaea 链的
  球极投影方案，见 `gaea-refinement.md` §3）。
- 像素映射与 `make_equirect_grid` 逐像素一致（列 edge-aligned、行 endpoint
  linspace），裁剪自全网格 NN 索引的切片——**对齐按构造保证，不重投影**。

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

Dell G15 5515（Ryzen 7 5800H + RTX 3060 Laptop 6 GB，Blender 5.2.2 LTS）：
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
