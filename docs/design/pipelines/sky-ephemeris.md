# 天球星历与背景天球

本文是观测者天空查询的实现参考：在时刻 T、从天体 B 表面的 (lat, lon) 看去，天上每个天体在哪里、多大、什么相位、
何时升落，以及恒星系之外的固定背景天球。渲染、FUI 数据卡、前端星图与历法读取同一份结果，各消费方不再自带轨道传播。
参考系与自转轴约定的单一事实源是 `engine/ephemeris.py` 的模块 docstring，物理背景见
[观测者天球框架](../../knowledge/astrophysics/observer_sky_frames.md)，前端操作见
[天球视图](../../usage/sky-viewer.md)，未实现部分见[提案](../proposals/sky-ephemeris.md)。

## 1. 模块分工

| 模块 | 职责 |
|---|---|
| `engine/ephemeris.py` | 纯函数查询，无 IO、无 RNG：两体开普勒传播、观测者框架、坐标变换、测光与升落。 |
| `engine/sky_geometry.py` | 角径、相位、照度与本影原语；星历的测光直接复用这里的 Lambert 相位与反射星等。 |
| `engine/sky_background.py` | 背景天球的纯函数派生：方向单位矢量、由光度推星等、种子化暗星场。 |
| `models/sky_background.py` | 背景天球的输入与派生 Pydantic 模型。 |
| `cli_sky.py` | 顶层命令 `dreamulator sky`。 |
| `api_routes/worlds.py` | 三个只读端点：天空查询、背景天球、星空文化。 |

## 2. 查询

入口是 `sky_ephemeris(entities, observer_id, lat_deg, lon_deg, at_days, targets, include_events)`。
`entities` 是天文层 `system_catalog.yaml` 经 `guard.facts.load_entities` 展平后的实体表，`orbits:` 段的完整精度根数须已合并。
`at_days` 是距 catalog 历元的天数；`targets` 为 `None` 时报告观测者以外的全部实体，顺序与 catalog 相同。
未知天体抛 `KeyError`，自转轴无法确定或父链成环时抛 `ValueError`。

每个目标的结果包括地平坐标（高度与方位，方位从真北顺时针量）、黄道坐标、观测者真赤道上的赤经赤纬、角直径、相位角与照亮比、
视星等与照度、到恒星和母天体的角距、升落状态与下次升落的时间偏移，以及瞬时高度变化率。
高度变化率对全部目标共用一次中心差分，步长取观测者太阳日（缺失时用自转周期）除以升落采样数。

**自转轴阶梯。** 潮汐锁定天体以自身轨道法向为北，本初子午线瞬时指向母天体，因此母天体恒在 (0, 0) 的天顶；
catalog 的自转周期在这一分支中不使用。其次读取 `spin_axis_ecliptic_longitude_deg` 与 `axial_tilt_deg`，t = 0 时本初子午线指向
本体赤道在黄道上的升交点。非锁定卫星缺少倾角时退回轨道法向。其余缺少自转轴方位的天体直接报错，不编造方位。

**升落。** 在窗口 W = min(观测者年, max(太阳日项, 同级天体会合周期项)) 内按高度采样，按符号变化分为有升落、恒不落、恒不升三类，
首个穿越再用二分法求精。从锁定观测者看母天体高度恒定，结果为恒不落。跨多年的分类（慢自转世界的极夜开始）留给事件搜索。

**快路径。** `include_events=False` 跳过升落搜索，位置、测光与高度变化率保留，升落字段为 `None`。按实现注释，完整查询约 1 s，
快路径约 1 ms；升落搜索每个目标约 50 ms，是查询中随周期增长的部分。前端拖动时间和播放时用快路径，暂停后才取完整升落。

查询以 `@query(name="sky_ephemeris", dimension="sky")` 注册进 guard 查询索引，`guard/queries.py` 导入模块时触发注册，
因此 `POST /api/guard/queries/sky_ephemeris` 与专用端点返回同一结果。

## 3. 命令行与端点

```bash
uv run dreamulator sky nacrea --from satellite_nacrea --lat -0.106 --lon 1.121 --at 61.979
uv run dreamulator sky nacrea --at 61.979 --targets planet_aegis,satellite_cadence --json
```

`--from` 省略时使用 catalog 的 `target_body_id`；`--targets` 取逗号分隔的天体编号或 `all`；`--json` 输出查询结果原文，
供视频镜头规划与数据卡消费。其余参数说明见 [CLI 参考](../../usage/cli.md#天球星历sky)。

| 端点 | 内容 | 缓存 |
|---|---|---|
| `GET /api/worlds/{world}/sky` | 查询结果原文，参数为 `from`、`lat`、`lon`、`at`、`targets`、`include_events`、`branch`。世界或天体不存在返回 404，参数越界或自转轴不可解返回 422。 | 实体表按 (世界, 分支) 缓存，`system_catalog.yaml` 的修改时间或大小变化时重读；每次重新解析约 135 ms，缓存避免时间滑块逐帧重读。 |
| `GET /api/worlds/{world}/sky/background` | 天文层派生的背景天球。 | 同样按文件修改时间与大小校验。 |
| `GET /api/worlds/{world}/sky/culture` | 文明层派生的星空文化，消费规则见[文明管线第 6 节](civilization-pipeline.md)。 | 同上。 |

三个端点最多各缓存 8 个 (世界, 分支) 组合。天空查询的输出随时刻与观测点参数化，静态导出不提供这些端点，静态站显示提示面板。

## 4. 背景天球

天文层读取可选输入 `layers/astronomy/input/sky_background.yaml`（`SkyBackgroundInput`），由 `derive_sky_background`
派生后总是写出 `layers/astronomy/derived/sky_background.yaml`；没有输入时写出空目录。背景方向固定在黄道系天球上，与时刻和观测者无关，
前端用查询结果反解的旋转就地投影，因此环视拖动不发请求。

| 对象 | 派生内容 |
|---|---|
| 手置近邻星 | 黄经黄纬转为单位矢量（`unit_vector_ecliptic`）；只给光度与距离时由 `magnitude_from_luminosity` 推视星等，使用太阳热星等 4.74 且不做热改正。可附变星元数据。 |
| 程序暗星场 | `generate_starfield` 按种子抽取各向同性方向；累计星数按 N(<m) ∝ 10^(0.6m) 在 0 等到给定极限星等之间反函数取样；色温按三档抽取并偏向冷星。相同种子逐值复现。 |
| 深空天体 | 方向矢量、类型、角大小与积分星等。 |
| 银道带 | 由极点方向、宽度与峰值亮度定义的大圆带，前端按几何绘制，不使用纹理。 |
| 飞掠天体 | 方向、现距、当前星等，以及可选的最近距离与掠过年代，供撞击体供给等叙事引用。 |
| 瞬变事件钩子 | 超新星、伽马射线暴等事件的方向，可选的历元窗口、峰值星等与每百万年发生率，供生态层按设计消费。 |

文明层的星空文化按编号引用这份目录画星官连线，未知编号构建失败，程序暗星场不可引用；连线只引用编号，不复制坐标。
具体世界的星官与命名属于该世界的输入与设计笔记。

## 5. 消费方与验证

视频侧的天空镜头状态与 FUI 数据卡读取 `dreamulator sky --json` 的结果，原有的两体开普勒原型已退为薄封装；前端星图页读取
天空端点与背景端点。测试对齐 `sky_geometry` 的冻结锚点，包括母天体高度、卫星视径与方位以及相位表。

## 6. 已知限制

- 传播只用天体中心的两体开普勒，不含卫星相互扰动与节点进动。
- 锁定观测者把母天体钉在天顶，真实锁定天体匀速自转时母天体会按中心差摆动约 ±2e（nacrea 约 ±0.28°）；两种视图相差一个绕自转轴的
  整体旋转，低于现有消费方的分辨率。
- 理想球面地平，不含地形遮挡、大气折射和光行时。
- 食、凌与连珠的时刻搜索尚未实现。
