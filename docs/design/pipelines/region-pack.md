# 区域数据包与 Blender 静帧

本文是区域数据包（`dreamulator export region`）及其 Blender 消费脚本的实现参考。数据包把引擎网格上的高程与气候裁成一个
真实千米正方形窗口，供 terrain-diffusion 细化、Gaea、着色出图和 Blender 渲染共同读取。操作步骤见
[地形视频链](../../usage/terrain-chain.md)与 [CLI 参考](../../usage/cli.md#区域数据包export-region)，设计理由与后续扩展见
[提案](../proposals/blender-render-pipeline.md)。

源码：`src/dreamulator/map/region_export.py`（窗口、取样与写包）、`src/dreamulator/cli_export.py`（命令行）、
`scripts/media/blender/region_still.py`（Blender 场景重建与渲染）。

## 1. 窗口

窗口是星球真实半径球面上以请求中心为切点的方位等距平面，x 向东、y 向北、单位千米，换算与全球画布链共用
`map/td_canvas.py` 的 `CanvasGeometry`。平面内 |x| 与 |y| 都不超过 span/2 的范围就是窗口；中心距离在任何方位上都是真实千米，
所以窗口在任意纬度都是真实正方形。极区中心和跨 ±180° 经线的窗口都可以导出，只有边长触及对跖点（πR）时拒绝，
因为方位等距投影在那里退化。输出栅格是窗口平面上的均匀正方形网格，边长 `--out-res` 缺省 2048 像素，
像素尺度为 span 除以分辨率。

## 2. 取样

标量通道（高程、降水、温度、冰厚、NPP、年径流）在格心 Delaunay 三角网上做 Clough–Tocher C1 插值，并截断到所在三角形的
顶点取值范围，格心保持原值，也避免三次插值下冲造成假盆地。下游侵蚀由梯度驱动，线性插值的折痕会被当成河道种子，
所以选用 C1 插值。类别通道（Köppen、群系、湖冰月数）与地形配色取最近格。凸包外与退化窗口退回最近格。
缺值格在数值 `.npy` 中记为 NaN、在 PNG 中记为 0，每个通道的缺值像素数写入 meta。

## 3. 包内文件

包根目录下 `input/` 存放引擎导出通道，`gaea-out/`、`color/`、`refined-out/` 等由下游阶段写入。所有通道共用同一输出网格，
套准由构造保证。每个场单独保存为一个文件，不合并成 `.npz`：zip 头的时间戳会破坏逐字节复现，合并容器也牺牲逐层懒加载。

| 文件 | 内容 |
|---|---|
| `height.meters.npy` | float32 米值高程，主数据通道。 |
| `height.png` | 16 位高程，按窗口最小最大值归一，供人查看。 |
| `height.gaea.png` | 16 位高程，海底先压平到 `--seafloor-clamp`（缺省 −400 m），使 Gaea 的竖向量程留给陆地。 |
| `color.png` | 地形配色裁剪，调色板与前端同源（`map/palettes.py`）。 |
| `precipitation.mm`、`temperature.C`、`ice.m`、`npp.gc_m2_yr` | 年降水、年均温、冰厚（无冰为 0）与 Miami NPP，各有 `.npy` 数值与 `.png` 归一图。 |
| `runoff.mm` | 年径流，由逐格年降水与 Hamon 潜在蒸散按 Turc–Pike 公式计算后插值；仅在有月气候时写出。 |
| `lake_ice.months.npy` | uint8，月均气温低于 0 °C 的月数；12 表示常年封冻，1–11 为季节性封冻，0 为不封冻；仅在有月气候时写出。 |
| `headwaters.png` | 16 位掩膜，标出降水大于 Hamon 潜在蒸散的水量盈余陆地，作为 Gaea 河流节点的源区输入。 |
| `glacier.mask.png` | 16 位掩膜，冰厚大于 0 或群系为冰的像素，作为 Gaea 冰川节点的参考输入。 |
| `koppen.codes.npy`、`koppen.png`，`biome.codes.npy`、`biome.png` | uint8 类别码与调色板配色图。类别码在全网格按类名字典序分配，跨窗口稳定。 |
| `meta.json` | 窗口与量程契约，见下节。 |

`--no-climate` 只写高度与配色。雪线不单独归档，由下游从冰厚与温度两个通道推出。

## 4. `meta.json`

| 字段 | 含义 |
|---|---|
| `pack_version` | 当前为 4：方位等距窗口与统一千米像素。3 为输出网格与引擎网格解耦并加入 Gaea 变体，2 加入气候通道，1 只有高度与配色。 |
| `projection` | `azimuthal_equidistant`；像素与经纬度的互换须使用同一平面。 |
| `center_lat`、`center_lon`、`span_km`、`radius_km`、`grid` | 窗口中心、边长、星球半径与栅格尺寸。 |
| `extent_km`、`km_per_px` | 窗口实际边长与均匀像素尺度。 |
| `sampling` | 取样口径的文字说明。 |
| `cell_pitch_km` | CVT 平均格距 √(4πR²/N)，供下游按格尺度设置效果参数。 |
| `elevation_m`、`elevation_m_global` | 窗口内与全星球的高程范围；跨窗口一致的配色锚定在全球范围上。 |
| `height_png_range_m`、`height_gaea_png_range_m`、`seafloor_clamp_m` | 两种 16 位高程图的归一量程与压平深度。 |
| `sea_level_m`、`ocean_fraction` | 海平面与窗口海洋占比。 |
| `alignment_probe_max_offset_deg` | 与引擎等距圆柱导出网格的套准探针最大偏移。 |
| `source` | 世界、星球、分支与网格 sha256 指纹，不含时间戳，跨机可复现。 |
| `climate` | 各气候通道的 PNG 归一区间与缺值像素数，类别通道另附本窗口出现的类别码图例，以及湖冰与源区的说明。 |

**数值口径。** 盘上网格把格心坐标与高程存为 float32（`STATIC_CELL_COLUMNS`），而引擎的 `elevation.png` 在构建期由内存中的 float64
网格栅格化。区域包用盘上网格重新取最近格时，约 1% 像素的并列最近邻会翻到相邻格，多为深海孤立散点、量级几十米。
对齐验收以与 `elevation.png` 的海陆符号一致率不低于 99.9%、平均差小于 5 m 为准；回贴比较在格空间进行，不对 PNG 逐字节比较。

## 5. Blender 静帧

`region_still.py` 在 Blender 自带的 Python 中运行，按数据包重建场景，`.blend` 是可随时重建的一次性产物，不入库。
场景单位为 1 单位 = 1 km，竖直比例缺省为物理比例，`--zscale` 可夸张。`--terrain auto` 依次选用 terrain-diffusion 细化高程
（`refined-out/height.meters.npy`）、Gaea 侵蚀高程（`gaea-out/` 下的 EXR，按 `height_gaea_png_range_m` 还原米值）和引擎原始高程。
渲染使用 Cycles，设备按 OptiX、CUDA、CPU 顺序降级，固定种子 42 并用 OpenImageDenoise，同一数据包与参数给出确定结果。

参考测量配置为 8 核 CPU、6 GB 显存的 RTX 3060 Laptop 与 Blender 5.2.2 LTS。显存是贴图预算的硬上限：8k RGBA 贴图约 268 MB，
16k 约 1 GB 时须谨慎；数十万面的区域网格对这一配置是轻负载。

## 6. 已知限制

- 渲染只消费引擎与细化阶段的真实输出，不叠加程序化细节。
- 只有区域静帧；相机动画与整球 Blender 渲染未实现，太空俯瞰的整球镜头由 [太空俯瞰星球链](orbital-weather-globe.md) 提供。
