# 天球星历查询（sky ephemeris）

> **状态**：M1（引擎 + CLI）与 M3（前端天球视图）已实现。
> M1（2026-11-02，分支 `feature/sky-ephemeris`）：`engine/ephemeris.py` +
> `cli_sky.py` + guard 查询注册，测试对齐冻结锚点。
> M3（2026-11-03，分支 `feature/sky-ephemeris-m3`）：`include_events` 快路径
> （全量 ~1 s → 位置+光度 ~1.4 ms）、专用 `GET /api/worlds/{world}/sky`
> （entities 缓存杀 YAML 重解析）、前端 `/worlds/{world}/sky` 星图页
> （**Stellarium 式全屏**：默认沉浸环视——透视投影 + 拖动环视 + 滚轮/双指缩放
> 竖直视场，环视为纯前端投影零请求、圆盘与真实视径成比例、开页自动对准最亮
> 且离地平 ≥10° 的天体；全屏浮动 UI 指针静置自动淡出，左缘工具条 📍观测/🧭显示
> 对话框、点击天体左上详情面板、地平下/升落面板按需弹出、地平/赤道/黄道网格
> 叠加（后两者由结果双坐标反解旋转，frameFit）；附「全天」AEQ 概览圆盘模式；
> 时间滑块/播放、相位/星等/升落、移动端布局）。
> 视图形态已决：环视透视图为主、AEQ 半球圆盘为辅（非可旋转 3D 天球）。
> M2（消费方改读 JSON）与 M4（事件搜索/N 体）未动。框架与约定的单一事实源 =
> `engine/ephemeris.py` 模块 docstring 与 `knowledge/astrophysics/observer_sky_frames.md`；
> 前端操作见 `usage/sky-viewer.md`。
> 实现完成后本文蒸馏进 `pipelines/`。现有原语是 `engine/sky_geometry.py`（角径、天球位置、
> 相位、本影），轨道根数在 `system_catalog.yaml` 的 `orbits:` 段；已有两体传播
> 原型（视频侧消费）。目标：把「在时刻 T、从天体 B 的 (lat, lon) 看去，天空里
> 有什么」做成引擎的第一性查询，渲染、FUI、前端星图与日历共用同一份结果。

## 1. 问题与现状

天空位置目前在引擎里只以零散原语出现：潮汐锁定卫星的母行星天球位置
（`sky_position`）、相位与照度（`phase_geometry`）、本影与食季
（`eclipse_season_fraction`）。完整的「观测者天空」——恒星、行星、卫星在同一
观测点的位置、视直径、相位、升落——没有统一实现。

各消费方各自写轨道传播会漂移：视频侧的镜头规划、FUI 数据卡、前端的天体视图、
世界历法都需要同一组数。catalog 已经存了完整根数（a、e、i、Ω、ω、历元 M0），
没有理由让每个消费方再写一份传播。

## 2. 范围（M1）

**输入**：world；观测天体（例如某颗卫星或行星）；观测点 `(lat, lon)`；时刻
（world 的历元 + 天数，或日历的年/日/时）；目标天体列表（恒星、行星、卫星）。

**输出**：每个目标天体的天球位置（alt/az 与 RA/Dec 两种口径）、视直径、相位与
照度、与恒星/母行星的角距、升落时刻、视运动方向；JSON 与表格两种格式。

- **参考系**：轨道根数在 catalog 的参考面（黄道）中传播；观测点用本地 ENU
  （天顶、真北、东）；自转、轴倾与季节从 world 的输入读。
- **传播**：天体中心的两体开普勒；卫星的相互扰动、节点进动先不进入 M1，
  用 catalog 的根数即可满足镜头/数据卡/日历的精度。
- **相位与亮度**：复用 `sky_geometry` 的 Lambert/照度原语，不另写一份。
- **历元**：catalog 的 `epoch_year=0` + 天数；world 的日历（年、太阳日、季节）
  由 derived 字段给出；观测者的本地时由太阳位置推出。

## 3. 接口

- **纯模块**：`engine/ephemeris.py`，无 IO、无 RNG，输入/输出用 Pydantic 模型，
  可独立单元测试（与 `stellar_physics.py`、`sky_geometry.py` 同风格）。
- **查询注册**：`@query(name="sky_ephemeris", dimension="sky", ...)`，进 guard
  的查询索引。
- **CLI**：
  ```bash
  dreamulator sky --world nacrea --from satellite_nacrea \
      --lat -0.6 --lon 0.4 --at 61.979 --targets all --json
  ```
- **API**：`GET /api/worlds/{world}/sky`（参数 `from`/`lat`/`lon`/`at`/`targets`/`include_events`/`branch`，
  404 世界或天体、422 参数或自转轴拒绝；`include_events=false` 为滑块拖动/播放的快路径）。
  guard 查询路由（`POST /api/guard/queries/sky_ephemeris`）继续可用。
- **渲染/FUI 消费**：读同一份 JSON；不在 Blender/浏览器的运行时里 import 引擎。

## 4. 里程碑

| 里程碑 | 内容 | 估时 |
|------|------|:---:|
| M1 引擎 + CLI | 两体传播、观测者 ENU、相位/大小/升落；测试对齐 `sky_geometry` 锚点（Aegis 89°、11.3°、相位表；卫星视径/方位） | 3–5 天 |
| M2 消费方 | 天空镜头与 FUI 数据卡改读 JSON；视频侧的两体原型退役或变成薄封装 | 2–3 天 |
| M3 前端天球视图 | ✅ 已实现（2026-11-03）：沉浸环视（拖动/缩放）+ 全天概览圆盘、时间滑块、相位、升落；移动端可用 |
| M4 事件与 N 体 | 连珠/食季/掩食的时刻搜索；接 `scripts/astro` 的 REBOUND；长时段节点进动 | 按需 |

## 5. 非目标

- **真实背景星空/星座**：需要一份星表；world 的恒星背景是程序化生成的，M1 不做。
- **大气折射、光行时、相对论**：量级远小于一个像素。
- **地形遮挡**：M1 用理想地平；需要时从高度场生成地平线轮廓（后续）。

## 6. 与现有代码

- `engine/sky_geometry.py`：保留角径/天球位置/相位/本影原语，`ephemeris` 复用。
- `engine/astronomy.py`、`engine/satellite_dynamics.py`：catalog 的 derived 来源。
- `scripts/astro/rebound_nbody.py`：M4 的 N 体与事件搜索。
- `data/worlds/*/layers/astronomy/derived/system_catalog.yaml`：根数、历元。

## 7. 为什么值得做

1. **单一天空物理源**：渲染、FUI、前端、日历、验证不再各写一份传播；
2. **视频**：镜头规划、连珠/食季的时刻、数据卡数字；
3. **前端**：观测者视角的星图是「界内天文」的自然产物（现有
   `StellarSystemViewer` 是系统视角，不是站在地表看到的天球）；
4. **世界**：天空成为可查询的公共产物，供历法、潮汐、星座文化使用。

## 8. 开放问题

- world 的日历/时区（太阳日、季节、年的定义）如何暴露给 CLI；
- 观测点高程、地形遮挡与本地地平线；
- catalog 根数 vs N 体：卫星的相互倾角/节点进动在长时段是否需要；
- 真实地球星空（星表）是否加入、何时加入。
