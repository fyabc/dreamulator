# ExoPlaSim GCM 参照臂运行指南与踩坑记录

本文说明如何为一个 dreamulator 世界运行 ExoPlaSim 全球气候模式（GCM），并读取
结果与 EBM 气候引擎对比；运行中遇到过的坑与处理方法集中在 §2.3（环境变量）、
§4.3（对齐配置的归因）、§4.4（T42 的已知数值问题）、§7（读结果的口径）、§8（与 EBM 对比的已知限制）和 §10（常见问题）。

ExoPlaSim 是 PlaSim 的系外行星扩展版本（Paradise et al., MNRAS 2022），能显式求解
大气原始方程，因此副热带高压、急流、季风等大尺度特征会自然涌现。在本项目里它的
角色是**离线参照**：用来检验 EBM 引擎在 Ω、倾角、温室强度等杠杆上的响应是否
合理，它不进入 `dreamulator build` 管线，也不写回任何世界数据。

为什么要接 GCM、各后端如何取舍、nacrea 需要哪些特化输入，这些设计讨论在
[`../design/proposals/climate-gcm-plan.md`](../design/proposals/climate-gcm-plan.md)；
nacrea 的正式定标配置与结论数字在
[`data/worlds/nacrea/design-notes/0012-climate-gcm-calibration.md`](../../data/worlds/nacrea/design-notes/0012-climate-gcm-calibration.md)。

---

## 1. 代码与脚本位置

| 位置 | 作用 |
|---|---|
| `scripts/climate/gcm/bootstrap.sh` | 在任意 Ubuntu 机器或 WSL 上准备 Fortran 工具链和 Python 虚拟环境 |
| `scripts/climate/gcm/run_exoplasim.py` | 命令行入口：参数映射、运行模式、写 manifest、提取诊断、出概览图 |
| `scripts/climate/gcm/make_landmap.py` | 把世界网格重采样成 ExoPlaSim 的 `.sra` 地表文件：海陆掩膜，以及可选的地表位势（地形） |
| `src/dreamulator/gcm/mapping.py` | 世界输入到 ExoPlaSim 参数的纯函数映射，所有单位换算都集中在这里 |
| `src/dreamulator/gcm/runner.py` | 运行编排：环境自检、多年连续积分、续算、manifest |
| `src/dreamulator/gcm/diagnostics.py` | 从 NetCDF 输出提取急流、Hadley 环流边界、全球均温等指标 |
| `src/dreamulator/gcm/plotting.py` | 生成全球概览图 `overview.png` |

ExoPlaSim 的版本固定为 3.4.2（`pyproject.toml` 的 `[gcm]` 可选依赖组），适配层的
所有修复都是针对这个版本验证的，不要随意升级。

## 2. 准备环境

### 2.1 一键引导

在仓库根目录执行：

```bash
bash scripts/climate/gcm/bootstrap.sh private/gcm/venv
```

脚本分四步：用 apt 安装 gfortran、gcc 和 make；在指定目录建立 Python 虚拟环境并安装
`exoplasim==3.4.2`、netCDF4、matplotlib、meson、ninja、pyyaml、scipy，以及参数映射要用到的
dreamulator 引擎核心依赖（安装时锁住 numpy 版本）；强制编译 ExoPlaSim 的 pyfft 扩展并验证
能导入；最后对 nacrea 做一次参数映射冒烟（不运行模式）。

这里刻意使用 pip 加 venv，而不是 uv。原因是仓库里的 `uv.toml` 会覆盖包索引配置，
在安装 meson 等构建依赖时出过两次问题。国内网络可以设置镜像：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash scripts/climate/gcm/bootstrap.sh private/gcm/venv
```

虚拟环境和所有运行输出建议放在 `private/` 下，该目录已被 git 忽略。

### 2.2 多核运行需要 MPI

`--ncpus` 大于 1 时，ExoPlaSim 会用 `mpif90` 编译并行版本，需要先安装 OpenMPI：
`apt-get install openmpi-bin libopenmpi-dev`。以 root 身份运行时，还要设置
`OMPI_ALLOW_RUN_AS_ROOT=1` 和 `OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1`。

### 2.3 环境变量

PlaSim 的 makefile 没有声明完整的 Fortran 模块依赖，必须串行编译。共享服务器上常见的
`MAKEFLAGS=-j<N>` 会导致 `Cannot open module file 'landmod.mod'` 一类错误。引导脚本和
`run_gcm` 在编译前都会自动清掉 `MAKEFLAGS`、`MFLAGS` 和 `GNUMAKEFLAGS`，不需要手动处理。

如果环境用 `LD_PRELOAD` 预加载了 libiomp5 或 jemalloc 等库，建议运行前执行
`unset LD_PRELOAD`，避免干扰 Fortran 程序。

## 3. 快速上手：两年纯海洋行星冒烟

```bash
source private/gcm/venv/bin/activate
python scripts/climate/gcm/run_exoplasim.py \
    --world data/worlds/nacrea --planet satellite_nacrea \
    --years 2 --workdir private/gcm/runs/nacrea_smoke
```

不传 `--landmap` 时，模式按全海洋表面运行。第一次运行会先编译对应分辨率和核数的
Fortran 程序，约需两分钟；之后同样的配置直接复用编译结果。

判断冒烟是否通过，看三点：命令退出码为 0；`summary.json` 里 `wind_alive` 为 `true`；
`overview.png` 里能看到中纬度的两支急流和赤道附近集中的降水带。纯海洋行星的
平均场呈纬向条带状，这是对称强迫下的正确结果，不是故障。

## 4. 正式运行：带海陆分布

### 4.1 生成海陆掩膜和地形

地表文件从世界网格生成，所以要先构建该世界的地质层：

```bash
uv run dreamulator build nacrea --only geological
uv run python scripts/climate/gcm/make_landmap.py --world nacrea --planet satellite_nacrea \
    --mesh data/worlds/nacrea/maps/satellite_nacrea/cvt_mesh.msgpack.gz --resolution T21 \
    --out private/gcm/surf/nacrea_N032_surf_0172.sra \
    --topo-out private/gcm/surf/nacrea_N032_surf_0129.sra
```

`make_landmap.py` 依赖 dreamulator 的地图模块，用项目的 uv 环境运行即可。

- `--out` 是海陆掩膜（代码 172），用最近邻重采样；脚本会打印陆地占比，nacrea 在 T21
  下约为 0.30。
- `--topo-out` 是地表位势（代码 129，单位 m²/s²），等于格点框内陆地格点的面积加权平均
  高程乘以该行星的重力加速度，海洋为 0。重力由 `--planet` 从世界输入算出，保证和运行用的
  重力一致。nacrea 在 T21 下陆地平均高程约 670 m；地球的结果和 ExoPlaSim 自带的地球地形
  逐格点相关系数为 0.995。

地球参照臂也用同样的流程从 earth root 网格生成地表文件，不使用 ExoPlaSim 自带的地球文件，
这样两边只差输入数据，不差处理方法。

### 4.2 运行

```bash
source private/gcm/venv/bin/activate
export OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1   # 仅 root 需要
python scripts/climate/gcm/run_exoplasim.py \
    --world data/worlds/nacrea --planet satellite_nacrea --years 30 --ncpus 8 \
    --landmap private/gcm/surf/nacrea_N032_surf_0172.sra \
    --topomap private/gcm/surf/nacrea_N032_surf_0129.sra \
    --configure '{"twobandalbedo": true}' \
    --override '{"lonvernaleq": 180}' \
    --workdir private/gcm/runs/nacrea_aligned
```

### 4.3 对齐配置

GCM 与 EBM 比较、或与地球参照臂比较时，尽量只让输入数据不同、处理方法相同。下面这些
设置构成当前的对齐配置，地球参照臂和 nacrea 运行都使用它：

| 设置 | 取值 | 理由 |
|---|---|---|
| 海陆掩膜与地形 | 都从世界网格生成（§4.1） | EBM 和观测都带地形；GCM 平地表会系统性偏暖约 1.5 K（地球陆地平均高程约 0.8 km） |
| 双波段反照率 | `twobandalbedo: true` | EBM 对非太阳型恒星使用光谱冰反照率；冰在近红外反照率低，K 型星近红外份额高，宽带反照率会高估冰面反照 |
| 平流层臭氧 | 保持默认（关闭） | ExoPlaSim 默认配置在地球上已基本校准，内部参数吸收了「无臭氧」；打开后地球参照臂偏暖约 3.7 K |
| 物理滤波 | 保持默认（关闭） | 属于数值稳定手段，却使地球参照臂偏暖约 2.9 K；T21 带地形不开滤波也稳定 |
| 近日点相位 | nacrea `lonvernaleq: 180`，地球保留默认 102.7° | 见下文 |
| 混合层深度 | 50 m（默认） | 与 EBM 的 `ocean_mixed_layer_depth_m` 相同 |

**近日点相位。** PlaSim 的 `MVELP` 是从春分点量起的近日点经度，内部按 `MVELP + 180°`
使用，所以近日点落在春分时 `MVELP = 180°`。映射函数会用 EBM 的同一套推导
（`resolve_perihelion_day`）计算它；推导不出来时（地球，以及 26-10-11 定版后的 nacrea）
映射会给出警告，ExoPlaSim 退回地球的 102.7°，而 EBM 退回「近日点在春分」。nacrea 的
春分方向随约 10 年周期的轨道锥摆轮转，不存在固定相位，「近日点在春分」对南北半球是中性
的选择，所以 nacrea 运行显式传 `lonvernaleq: 180` 与 EBM 对齐。

两边都没有考虑的因素：宿主行星造成的食、宿主行星的反照光和红外辐射、内部热流（约
0.5 W/m²，相对日照可忽略）。陆地冰盖在 GCM 里没有掩膜，只靠积雪体现。

### 4.4 运行耗时参考

以下数字在 nacrea、T21、10 层配置下测得，换机器会有出入：

| 分辨率与核数 | 每个模式年的墙钟时间 | 30 年积分耗时 |
|---|---|---|
| T21，1 核 | 约 4 分钟 | 约 2 小时 |
| T21，4 核（MPI） | 约 1.5 分钟 | 约 45 分钟 |
| T21，8 核（MPI） | 约 1 分钟 | 约 30 分钟 |
| T42，16 核（MPI），45 分钟步长 | 约 2.3 分钟 | 约 70 分钟 |

T42 的数字来自 1 年试跑，测量时机器接近满载；带地形和物理滤波的 30 年运行实测约 2.2 小时
（16 核，含后处理）。

**T42 必须打开物理滤波**：`--configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}'`，
45 分钟步长即可。不开滤波时，多年积分会在短波辐射子程序 `swr_` 中崩溃（SIGFPE），单双波段、
有无地形都会发生，气候越暖越早（712 ppm 约第 8–10 年，2000 ppm 约第 7 年），缩短步长只能推迟；
陷阱位置是 `radmod.f90:1783` 的 `SQRT(273./dt)`，说明某格点气温已在上游发散成非物理值，物理
滤波抑制了这种网格尺度的噪声。打开滤波后，地球参照臂与 nacrea 冷暖双臂（最长 40 年）全部稳定，
地球偏差（−0.6 K）与 T21 不开滤波时（−0.8 K）几乎相同，扩散系数不需重标。注意 T21 不要开滤波：
它在 T21 会使地球偏暖约 2.9 K。

另一个已知问题：高 CO₂ 下 Kuo 对流方案会溢出，T42 在 6000 ppm 第 5 年崩溃（此测试未开滤波）。
高 CO₂ 端用 T21。

积分结束后还有单线程的后处理：ExoPlaSim 自带的 pyburn 把原始输出转成 NetCDF，
主输出和快照各处理一遍。15 年运行的后处理约需 3 分钟。上游 pyburn 读取原始文件的
写法是平方复杂度，同样的工作原本要十几分钟；`run_gcm` 已换用线性时间的读取函数
（`runner.fast_readallvariables`），输出与上游逐位一致。

`--ncpus` 应取能整除模式纬圈数的值。T21 有 32 个纬圈，可选 1、2、4、8、16；T42 有 64 个纬圈，
可选到 32。同时启动多个运行时，如果某个核数的程序还没编译过，先单独启动一个运行让它完成编译，
再启动其余运行：所有运行共用 venv 里的同一棵源码树，并发编译会互相干扰。

## 5. 命令行参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--world` | 必填 | 世界目录，或 `data/worlds/` 下的世界名 |
| `--planet` | 必填 | `planets.yaml` 中的天体 ID，例如 `satellite_nacrea` |
| `--host` | 自动 | 卫星所绕的行星 ID，用于计算日照；默认从轨道关系解析 |
| `--years` | 2 | 连续积分的模式年数 |
| `--resolution` | T21 | 谱分辨率；T21 网格约 620 km，T42 约 310 km |
| `--layers` | 10 | 垂直层数 |
| `--ncpus` | 1 | MPI 进程数，大于 1 时需要 OpenMPI |
| `--workdir` | `gcm_runs/<天体>_<分辨率>` | 运行目录，建议显式指定到 `private/` 下 |
| `--landmap` | 无 | `.sra` 海陆掩膜；不传时为纯海洋行星 |
| `--topomap` | 无 | `.sra` 地表位势（地形），必须和 `--landmap` 一起使用 |
| `--configure` | `{}` | 以 JSON 传入额外的 `Model.configure` 参数，例如对齐配置的三个开关 |
| `--namelist` | `{}` | 以 JSON 传入额外的 namelist 项，格式为 `"键@namelist文件": "值"`，例如平板海洋水平扩散 `{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "5.0E4"}` |
| `--greenhouse-mode` | none | 温室处理方式，见下文 |
| `--pco2-bar` | 无 | `pco2` 模式下显式给定的 CO₂ 分压，单位 bar |
| `--flux-boost-factor` | 无 | `flux_boost` 模式下的恒星通量放大倍数 |
| `--override` | `{}` | 以 JSON 覆盖映射结果中的字段，例如 `'{"obliquity": 0}'`、`'{"lonvernaleq": 180}'` |
| `--nc` | 无 | 只诊断一个已有的 NetCDF 文件，不重新运行 |
| `--no-plot` | 关 | 不生成概览图 |

**温室模式。** 默认的 `none` 模式会按世界大气成分里的 CO₂ 比例自动换算 pCO2
传给模式（nacrea 约 720 ppm），这就是定标所用的配置。此时日志里出现的
`greenhouse_factor ... is the EBM parametrisation and is not mapped` 只是提示 EBM 的
温室参数没有对应物，可以忽略。`pco2` 模式用 `--pco2-bar` 显式指定 CO₂ 分压，用于做 pCO2 扫描。
`flux_boost` 是早期原型阶段放大恒星通量的做法，现在不推荐使用。

**参数映射的单位约定。** `radius` 以地球半径为单位而不是米，`year` 以 24 小时
地球日为单位。这些换算都由 `mapping.py` 完成，用 `--override` 改字段时也要遵守同样的
单位。完整对照表见 `mapping.py` 的模块说明。

## 6. 输出文件

运行目录里会保留模式的全部原始输出，主要关注以下几个：

| 文件 | 内容 |
|---|---|
| `MOST.00000.nc` | 后处理后的 NetCDF，每个模式月一条记录 |
| `summary.json` | 诊断指标：急流纬度与强度、Hadley 边界、全球与赤道和极区均温、`wind_alive` 等 |
| `overview.png` | 全球概览图：地表气温、降水、海平面气压、低层纬向风、纬向平均风、涡动方差、经向流函数 |
| `manifest.json` | 可复现性记录：输入文件哈希、映射参数、版本、墙钟耗时 |
| `MOST.00000`、`MOST_DIAG.00000` | 原始 Fortran 输出和诊断日志，后处理失败时可用来恢复 |
| `MOST_REST.00000` | 积分结束时的重启文件，可作为续算的起点 |

只想重新诊断或重画图时，用 `--nc` 指向已有的 NetCDF 即可，不必重跑模式。

## 7. 读结果时要注意的口径

- **全球均温看 `t_global_c`。** 它用的是 2 米气温 `tas`。`t_global_column_c`、`t_eq_c` 和
  `t_pole_c` 基于整层大气温度，包含很冷的平流层，比地表低几十度，不能与 EBM 的
  地表温度直接比较。
- **绝对温度要先做偏差订正。** ExoPlaSim 使用无动力热输送的平板海洋，海冰偏多，
  导致系统性冷偏。用地球参照臂测得的偏差为 −9.6 ± 3 K，读绝对温度时要先加回
  这个量。同一协议下不同运行之间的差值不受这个偏差影响，是更可靠的量。
- **冷启动需要足够长的积分。** 两年的结果仍在调整期，只用于确认模式能跑。正式比较
  至少用 15 年，并取最后几年的平均。
- **模式日历与真实轨道年不一致。** 模式年的日数由自转周期取整得到（nacrea 为 120 个
  模式日），而真实轨道年是 99.8 天，所以季节在记录序号上会漂移。做季节分析时
  用 `diagnostics.orbital_phase_of_records()` 按轨道相位重新对齐。
- **能量收支只看净 TOA。** 净 TOA 辐射等于 `rst + rlut`（PlaSim 的通量以向下为正）。
  短波各分量之间不闭合，暂不要用来做短波收支分析。

## 8. 与 EBM 对比：投影到网格并导出图层

为了让 GCM 和 EBM 用完全相同的配色、投影和分辨率比较，先把 GCM 结果投影到世界的 CVT 网格上，
再用 `dreamulator export layers` 渲染：

```bash
source private/gcm/venv/bin/activate
python scripts/climate/gcm/gcm_to_mesh.py --world data/worlds/nacrea --planet satellite_nacrea \
    --nc private/gcm/runs/t42f/cold/MOST.00000.nc \
    --out private/gcm/mesh/nacrea_t42_712/cvt_mesh.msgpack.gz
deactivate
G=private/gcm/mesh/nacrea_t42_712/cvt_mesh.msgpack.gz
E=data/worlds/nacrea/maps/satellite_nacrea/cvt_mesh.msgpack.gz
uv run dreamulator export layers nacrea -l koppen,temperature,precipitation,pressure \
    --mesh $G -o private/gcm/export/gcm
uv run dreamulator export layers nacrea -l koppen,temperature,precipitation,pressure \
    -o private/gcm/export/ebm
uv run dreamulator export layers nacrea -l temperature_diff,precipitation_diff,koppen_agreement \
    --mesh $G --compare-mesh $E -o private/gcm/export/diff
```

投影（`src/dreamulator/gcm/to_mesh.py`）取运行最后 5 年，按轨道相位分成 12 个「月」，双线性
插值到每个格点，写出与引擎构建同格式的网格，并在旁边写一个 `.gcm.json` 记录来源和摘要：

- **气温**按 6.5 K/km 的递减率从 GCM 的平滑地表订正到格点自身的高程（认识论类别：近似推导）；
- **降水**按地球年口径（每月 365.25/12 天）累计，与引擎的 `precipitation_mm` 一致；
- **Köppen** 用引擎自己的 `koppen_classify` 和同样的季节输入，两边分类器完全相同；
- **气压异常**按引擎的 ΔP 定义（海平面气压减去同月同纬带海洋平均，取年平均）；GCM 地表高度
  不低于 1500 m 的陆地格点标记 `slp_reduction_unreliable`；
- **风**取 10 米风，输出里没有时取最低模式层；
- 平板海洋给不出、或引擎在自身气候之下派生的字段（洋流、海温距平、生物群系、NPP、农业、
  宜居度）被清空，避免被误读为 GCM 结果。

**已知限制**：

- 即使是 T42（约 310 km），插值到网格后的场也比 EBM 平滑得多，差值图里的小尺度差异大多反映
  分辨率差，不是物理差。
- **GCM 的气压异常图层目前不可用于比较。** 谱模式的海平面气压在 T42 下被地形激发的吉布斯振荡
  整体污染，振荡从高原一直扩散到海洋，屏蔽高原格点只能去掉核心。可能的改进是先做谱截断平滑，
  或改用 850 hPa 位势高度距平，尚未实现。
- 风场图层与逐月图层暂不导出。

## 9. 续算与暖启动

命令行入口目前没有续算参数，需要在 Python 里调用 `run_gcm`，通过映射结果的
`extras` 传入 `restartfile`：

```python
from dreamulator.gcm.mapping import map_world
from dreamulator.gcm.runner import run_gcm

params = map_world("data/worlds/nacrea", "satellite_nacrea")
params.extras["restartfile"] = "private/gcm/runs/nacrea_land15/MOST_REST.00000"
run_gcm(params, "private/gcm/runs/nacrea_land15_cont", years=10, ncpus=8,
        landmap="private/gcm/surf/nacrea_N032_surf_0172.sra")
```

不要手动把重启文件复制成运行目录里的 `plasim_restart`。ExoPlaSim 在没有收到
`restartfile` 参数时会删除这个文件，结果悄悄变成冷启动。确认续算生效的办法是在
`MOST_DIAG` 里找 `Found N variables in file` 这一行，或者检查第一年的温度是否延续了
上一段运行。

## 10. 常见问题

| 现象 | 原因与处理 |
|---|---|
| 编译时报 `Cannot open module file 'landmod.mod'` | make 在并行编译。`run_gcm` 会自动清掉 `MAKEFLAGS` 等变量；如果是绕过 `run_gcm` 直接调用 exoplasim，需要手动 `unset MAKEFLAGS` |
| T42 运行在 `swr_` 中报 `SIGFPE` | T42 没开物理滤波；加上 `"physicsfilter": "gp\|exp\|sp"`（根源未修，见 roadmap 技术债） |
| `ModuleNotFoundError: No module named 'yaml'` | 虚拟环境是旧版引导脚本建的，执行 `pip install pyyaml scipy` |
| 报 `exoplasim.pyfft failed to compile` | 虚拟环境缺 meson 或 ninja，或者它们不在 `PATH` 上；激活虚拟环境后重新运行引导脚本 |
| 报 `ExoPlaSim reported a crash` | Fortran 侧出错，查看运行目录里的 `plasim_diag`、`plasim_output` 和运行日志 |
| MPI 拒绝以 root 运行 | 设置 `OMPI_ALLOW_RUN_AS_ROOT=1` 和 `OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1` |
| `wind_alive` 为 false，风速接近零 | 多半是半径单位传错（米而不是地球半径）；检查 `--override` 是否改了 `radius` |
| 运行了多年，输出却只有 12 条记录 | 说明绕过了 `run_gcm`。多年积分必须同时设置 `N_RUN_YEARS` 并把 `N_RUN_STEPS` 清零，后处理时 `times` 也要设为年数乘以 12；`run_gcm` 已经处理好这些 |
