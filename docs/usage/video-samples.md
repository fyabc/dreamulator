# 样片复现手册（太空镜头 · 云流 · 自转 · 掩食 · 板块运动）

本手册把「发给群友看」的成品级样片整理成一条命令即可重跑的形式。所有产物写入
`exports/`（已被 gitignore，不进版本库），生成脚本随仓库版本管理：视频脚本在
`scripts/media/`，板块运动链在 `scripts/geology/`。同种子 + 同输入 = 同输出，
换时刻/换风格只需改对应旗标。

## 0. 前置准备

1. **构建世界**：样片基于 nacrea 的已构建地图
   `data/worlds/nacrea/maps/satellite_nacrea`，以及气候正典所在分支的
   `data/worlds/nacrea/branches/gcm-t42-712/maps/satellite_nacrea`
   （`uv run dreamulator build nacrea -b gcm-t42-712`；地图变更后静帧与视频都需重跑）。
2. **GCM 气象图层包**：云流/自转/掩食链都读
   `exports/weather/nacrea-gcm-t42-712`（1485 帧、6 小时间隔的逐帧云量、云顶高度、
   双层风场与太阳直射点）。包的生成方法见
   [exoplasim-gcm.md](exoplasim-gcm.md) 与
   [../design/pipelines/gcm-weather-pack.md](../design/pipelines/gcm-weather-pack.md)。
3. **ffmpeg**：视频脚本优先找系统 ffmpeg，找不到就回退
   `imageio-ffmpeg`。手册统一用 `uv run --with imageio-ffmpeg python ...`，
   不污染项目依赖。
4. **依赖**：`uv sync --all-extras`（`export globe` 的噪声核需要 media extra）。
5. **内存约束**：8K 渲染与长视频很吃内存，重负载任务串行执行，不要并行开两个渲染。

## 1. 静帧（export globe）

静帧是所有云流/自转/掩食视频的输入。同一个命令出两版：无风暴版（`-clear`）与
风暴版（`--cyclones`，气象包的真实移动温带气旋轨迹 + 正典参数化热带气旋）。

```bash
# 无风暴版（当前样片：exports/globe/nacrea-gcm-t42-712-f273-clear）
uv run dreamulator export globe nacrea -p satellite_nacrea -b gcm-t42-712 \
    --weather-pack exports/weather/nacrea-gcm-t42-712 --frame 273 \
    -o exports/globe/nacrea-gcm-t42-712-f273-clear

# 风暴版（当前样片目录名 ...-chirality，沿用修复分支命名；重跑建议用 -cyclones）
uv run dreamulator export globe nacrea -p satellite_nacrea -b gcm-t42-712 \
    --weather-pack exports/weather/nacrea-gcm-t42-712 --frame 273 --cyclones \
    -o exports/globe/nacrea-gcm-t42-712-f273-cyclones
```

**`-b gcm-t42-712` 不能省**：地表着色（生物群系、干旱带、植被）取自分支地图自带的
气候字段。GCM 分支是气候正典（干旱类陆地约 21%）；不带 `-b` 会退回 root 的引擎
气候（干旱类约 38%），云是 GCM 的、地是引擎的，两种口径混在同一颗星球上，
北半球中纬度会多出一圈不该有的荒漠带。

第 273 帧是当前样片选定的时刻（云系形态完整、热带气旋活跃）；换时刻改 `--frame`
即可。`--weather-pack` 会让视角中心默认对准该帧的太阳直射点（受光半球朝向镜头），
云量与双层云壳分配也来自该帧（前后各一帧的加权平均再高斯平滑）。纹理网格默认
4096×2048（视频链工作纹理 2048 宽，4K 静帧绰绰有余）、噪声种子默认 7、气旋种子
默认 31，渲染为分钟级。需要印刷级 8K 静帧时显式加 `--grid 8192x4096`——注意风暴版
在 8K 下的模板评估内存峰值可超过 20 GB，内存不宽裕时留在 4K。

## 2. 云流视频（cloud_flow_video）

云纹理沿气象包自身的 6 小时风场平流（低层云壳走中层风、卷云壳走高层风），
相机与恒星固定、晨昏线不动。`--sim-hours 24` 表示 8 秒画面压缩 24 小时演化。
两版都以**无风暴静帧**为输入：无风暴版 `--storm-mode none`；风暴版走默认的
`--storm-mode rigid`——风暴模板每帧按真实轨迹重新合成，云盾大小与顺风卷云幡
由该帧局地风场求解（弱风内热带是宽而缓的涡旋，靠近急流的是拖长幡的紧凑核），
热带旋臂以图案自转速度（约 0.3–1 圈/天）刚性旋转，24 小时内保持结构而不被
差速卷绕。

```bash
# 无风暴版
uv run --with imageio-ffmpeg python scripts/media/cloud_flow_video.py \
    exports/globe/nacrea-gcm-t42-712-f273-clear \
    -o exports/video/cloudflow/flow-f273-24h-clear.mp4 \
    --res 720 --width 1280 --height 720 --seconds 8 --sim-hours 24 \
    --texture-width 2048 --storm-mode none \
    --weather-pack exports/weather/nacrea-gcm-t42-712 \
    --poster exports/video/cloudflow/flow-f273-24h-clear-poster

# 风暴版（rigid 为默认，显式写出便于阅读）
uv run --with imageio-ffmpeg python scripts/media/cloud_flow_video.py \
    exports/globe/nacrea-gcm-t42-712-f273-clear \
    -o exports/video/cloudflow/flow-f273-24h-cyclones.mp4 \
    --res 720 --width 1280 --height 720 --seconds 8 --sim-hours 24 \
    --texture-width 2048 --storm-mode rigid --storm-seed 33 \
    --weather-pack exports/weather/nacrea-gcm-t42-712 \
    --poster exports/video/cloudflow/flow-f273-24h-cyclones-poster
```

`--poster` 会把首帧/末帧各存一张 PNG 在输出旁边，方便发图不发视频。
`--storm-seed` 覆盖热带气旋抽样种子（默认继承静帧 `meta.json` 的 `cyclones.seed`，
无风暴静帧未记录时为 31）：生成位置由 GPI 场加权、只落在洋面（静帧目录的
`ocean_fraction.npy` 是陆海掩膜），云盾与卷云幡随局地风场求解，所以换种子只是换
「这一幕在哪片海出现风暴」。当前样片用 33（风暴在 15°N 附近的洋面上加强）。
720p、24 小时窗口一版约 50–90 分钟。

## 3. 自转视频（spin_video，含 19.9° 轴倾角）

相机与恒星固定、整颗星球刚性自转一周后定格，晨昏线不动。`--axis-tilt 19.9`
应用 nacrea 正典自转轴倾角（与 GCM 太阳直射点 ±19.9° 的年摆动一致），
轴向默认倾向画面右侧（可用 `--axis-azimuth` 覆盖）。

```bash
uv run --with imageio-ffmpeg python scripts/media/spin_video.py \
    exports/globe/nacrea-gcm-t42-712-f273-clear \
    -o exports/video/spin/nacrea_spin_720p.mp4 \
    --res 720 --width 1280 --height 720 --seconds 8 --fps 30 \
    --axis-tilt 19.9 \
    --poster exports/video/spin/nacrea_spin_720p-poster
```

倾斜路径在 1/4 分辨率网格上做球面旋转再由渲染器上采样（对 720p 镜头绰绰有余），
单帧约 1.5–5 秒，整片约 20 分钟；不带 `--axis-tilt` 的纯经度平移快路径整片几十秒。
云在片中不演化（刚性旋转），与云流视频互补。

## 4. 掩食视频（Aegis 掩恒星，从始至终）

nacrea 潮汐锁定于 Aegis（Aegis 天顶固定在经度 0°、赤道），所以相机随地表固定、
不画自转；太阳沿气象包的直射点轨迹横穿天空，掩食深度由太阳与 Aegis 天顶的角距
实时驱动（`b = D_MOON·sin ψ`）。Aegis 的角半径（5.65°）比整颗星球的视半径还大，
掩甚前后整个昼半球都落入全食。三种运动（太阳、掩食、云平流）共用气象包同一时钟。

```bash
# 单帧静图（b = 70,000 km 的偏食构图，QA 用）
uv run python scripts/media/render_satellite_still.py \
    --export-dir exports/globe/nacrea-gcm-t42-712-f273-clear \
    --out exports/video/eclipse/nacrea_eclipse_b70000.png

# 全过程视频：自动在气象包里搜掩甚帧（当前包约在第 863 帧附近），
# 前后各 1.8 小时覆盖接触始→全食→复圆
uv run --with imageio-ffmpeg python scripts/media/eclipse_flow_video.py \
    exports/globe/nacrea-gcm-t42-712-f273-clear \
    -o exports/video/eclipse/nacrea_eclipse_flow.mp4 \
    --weather-pack exports/weather/nacrea-gcm-t42-712 --sim-hours 3.6 \
    --poster exports/video/eclipse/nacrea_eclipse_flow-poster
```

掩食几何（精确圆透镜交叠，非圆形暗斑近似）在
`src/dreamulator/media/eclipse_geometry.py`，实现说明见
[../design/pipelines/orbital-weather-globe.md](../design/pipelines/orbital-weather-globe.md)。

## 5. 板块运动视频（paleo_solve → paleo_render）

两步链：先解大陆块回溯运动（150 Myr、30 个阶段），再按解渲染摩尔威德投影动画
（1920×1080、20 fps、每帧 0.5 Myr；转换断层金黄描边、洋脊海沟白描边，
板块归属按 ±2 帧多数投票抑制重采样闪烁）。

```bash
# ① 求解（约 5 分钟；地形重新生成后旧 solve.npz 失效，必须重解）
uv run python scripts/geology/paleo_solve.py \
    data/worlds/nacrea/maps/satellite_nacrea \
    --out-dir exports/video/plates/solve --end 150 --plot

# ② 渲染 + 编码（301 帧约 18 分钟）
uv run --with imageio-ffmpeg python scripts/geology/paleo_render.py \
    data/worlds/nacrea/maps/satellite_nacrea \
    --solve-dir exports/video/plates/solve \
    --out-dir exports/video/plates
```

成品为 `exports/video/plates/plate_motion.mp4`（发布时可改名，当前样片叫
`plate_motion_nacrea_150myr.mp4`）。只调渲染参数时用 `--encode-only` 复用已渲帧、
`--epochs` 出几个时刻的静帧做 QA，不必整片重渲。

## 6. 速查表

| 成品 | 输入 | 命令入口 | 耗时量级 |
|------|------|----------|----------|
| 静帧（clear / cyclones） | 气象包 + 构建地图 | `dreamulator export globe` | 分钟级 |
| 云流视频 24 h | 静帧 + 气象包 | `scripts/media/cloud_flow_video.py` | ~30–60 分钟 |
| 自转视频（倾斜 19.9°） | 静帧 | `scripts/media/spin_video.py` | ~20 分钟 |
| 掩食静图 / 视频 | 静帧 + 气象包 | `scripts/media/render_satellite_still.py` / `eclipse_flow_video.py` | 秒级 / ~20 分钟 |
| 板块运动 150 Myr | 构建地图 | `scripts/geology/paleo_solve.py` + `paleo_render.py` | ~5 + ~18 分钟 |

注意所有视频的构图（视角中心、太阳位置）默认继承静帧 `meta.json` 里的设定，
想换构图先在静帧命令里用 `--center-lon/--center-lat/--sun-lon/--sun-lat` 覆盖，
再从新静帧出视频。
