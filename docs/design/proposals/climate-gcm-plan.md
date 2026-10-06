# 气候层 GCM 方案（远期备选）

> 状态：远期提案。当前主线是「诊断式单向 DAG + 聪明预设」（见
> `climate-layer-improvement.md`）。本文件是**全动力学 GCM** 的备选路线，
> 大致列出做法，重点在「涌现 vs 高效」的平衡。不排优先级、不承诺时间。
> **已实现部分**：ExoPlaSim offline-oracle 薄适配层（`src/dreamulator/gcm/`，
> 2026-10-05 入库，见 §「ExoPlaSim harness（已实现）」）——GCM 在当前阶段
> 的角色是**验证 oracle**而非运行时引擎，本文件的远期方案不受影响。

## 定位

诊断式 DAG 用预设逼近 GCM 的涌现特征（副热带高压、静止波、干沙漠偏热、季风反转），
每个特征都需要一个「聪明预设」，且预设之间可能互相打架（如地转风打崩降水）。
GCM 方案是**换一种方式**：用完整原始方程显式求解，让这些特征**涌现**出来，
而不是逐个复刻。

核心权衡：**涌现的收益 vs 高效的代价**。GCM 涌现（物理自洽、特征天然正确）
换来了复杂度（耦合求解、时间步进、参数化标定、慢）。诊断式 DAG 高效（单向、秒级）
换来了「每个涌现特征都要手写预设、且预设会打架」。

## 大致做法（粗略）

1. **动力核心**：原始方程（或浅水 + 静力近似），谱方法（球谐变换）或有限体积。
   参考 ExoPlaSim（PlaSim 扩展，MNRAS 2022，PoC 已在 nacrea 参数上跑通）。
2. **物理参数化**：辐射（短波/长波）、对流（干/湿对流调整）、边界层、
   **地表能量平衡 + 土壤湿度（bucket model）**、冰川。
3. **地形**：CVT 网格 → 谱/栅格重采样（ExoPlaSim T21≈620km、T42≈310km，
   比 dreamulator 200k/51km 粗 6–12 倍——地形细节会损失，这是 GCM 换涌现的代价之一）。
4. **输出对齐**：Köppen、风场、降水、海平面气压，与诊断式 DAG 的输出 schema 对齐，
   前端/导出无需重写。

## 涌现 vs 高效 的关键取舍

| 维度 | 诊断式 DAG（现状） | GCM（本方案） |
|------|-------------------|--------------|
| 副热带高压/静止波 | 需手写预设（地转风/方向性大陆度） | 涌现 |
| 干沙漠偏热 | 需 bucket model 预设 | 涌现（地表能量平衡） |
| 季风反转 | 需 ΔP 热源 + 胞圈迁移预设 | 涌现 |
| 计算成本 | 秒级（单向 DAG） | 分钟～小时（耦合 + 时间步进） |
| 物理自洽 | 预设之间可能打架 | 天然自洽 |
| 标定 | 逐特征标定 | 参数化方案标定（更标准） |

**判断准则**：当诊断式预设的「边际收益递减 + 预设打架」超过 GCM 的「复杂度 + 慢」，
才值得切 GCM。在此之前，GCM 可用作**离线校准参照**（跑几个世界，验证诊断式预设的
物理合理性，不接入主线）。

## 后端引擎矩阵（2026-09-27 查证版）

**CPU 阵营**（成熟度按降序）：

| 引擎 | 定位 | 算力 | 备注 |
|------|------|------|------|
| [ExoPlaSim](https://exoplasim.readthedocs.io/)（EMIC 级） | 系外行星 GCM 入口 | T21 8 核 1-5 min/模拟年 | 本项目 PoC 已在 nacrea 参数跑通；潮汐锁定/非太阳光谱原生支持 |
| [Isca](https://www.exeter.ac.uk/research/isca/)（Exeter） | 理想化 GCM，理论扫描 | 工作站可跑 | 快速验证「慢自转下哈德利宽度/急流形态」类问题 |
| [ExoCAM](https://github.com/storyofthewolf/ExoCAM) | CESM 系外分支，全复杂度 | HPC 级 | 云微物理/辐射最精；海洋模块简化 |
| [ROCKE-3D](https://www.giss.nasa.gov/tools/rocke-3d/)（NASA GISS） | 耦合 GCM，古气候/系外 | HPC 级 | 支持自定义底边界条件（潮汐热流注入点） |
| MITgcm | 海洋王者 | HPC-超算级 | 深海热液环流类问题唯一解；大气需外挂耦合 |

**GPU-native 阵营**（Julia 生态，2026 查证属实）：

| 引擎 | GPU 状态 | 关键特性 | 采用注意 |
|------|---------|---------|---------|
| [SpeedyWeather.jl](https://github.com/SpeedyWeather/SpeedyWeather.jl)（Klöwer et al. 2024, JOSS） | 谱变换 + fused GPU kernels，CPU/GPU 同码 | 可微分是官方路线图（ML/参数反演） | 理想化物理（SPEEDY 谱系），系外行星辐射需自写 |
| [CliMA / ClimaAtmos.jl](https://clima.github.io/)（Caltech） | CPU/GPU 同码，GPU 弱扩展 >92%；2025-11 已发 km 级 8192-GPU 全地球系统论文 | 面向 km 级下一代 ESM | 地球聚焦，系外/非地球光谱需魔改；耦合器成熟中 |

**EBM 阵营**（与我们引擎同类的参照，非采用对象）：EOS-ESTM（Biasiotti, Simonetti, Vladilo et al. 2022，
季节-纬向 EBM + 辐射柱耦合，快是因为 EBM 架构本身，**无 GPU 实现**——外部聊天声称的
「EOS 母体 GPU 加速」查无实据）；HEXTOR（2026 新出的宜居系外行星 EBM，TRAPPIST-1
气候态研究，THAI 语境关联但非 THAI 参比者）。

**神经代理**（Earth-2 MIP / GraphCast / FNO 一族）：概念真实且有 H200 级算力加持，但
代理模型只在训练分布内插值可靠——对未见强迫域（如 11 kyr 潮汐加热扫描）外推不成立，
只可作加速器不可作真值源。

## GPU 加速杠杆与本机资源

- 谱方法（球谐变换）和有限体积在 GPU 上可大规模并行（FFT/球谐、批处理）。
- **可用资源（2026-09-27 登记）：本机 RTX 3060 6GB（PoC 级）+ 可获取 8×H200 服务器
  （单卡 141GB HBM3e）**——后者把 GPU-native GCM 的「慢」从障碍变成可选项，
  也让「自研简化引擎 + GPU 内核」成为现实选项。
- 传统 Fortran CPU GCM 无法利用 GPU；若走 GCM 路线且要 GPU，候选收窄到
  SpeedyWeather.jl / CliMA（均需系外辐射魔改）或神经代理（需先有真值生成器）。
- **本机 S6 PoC 判负（2026-09-27，RTX 3060 Laptop 6GB）**：真实预算矩阵
  （n=200k、nnz=1.4M、MMD 排序后 nnz(L+U)=22.6M）上 CuPy splu 分解+求解
  7.2 s vs scipy SuperLU 2.0 s（**3.5× 慢**）；精度等价（rel 5e-15）、VRAM
  2.15 GB 装得下、传输 0.22 s——瓶颈是填充因子的散射访存，GPU 不擅长。
  结论：本地 GPU 直接稀疏 LU 无收益，不集成求解路径；H200（带宽 ~50× +
  cuDSS）留作未来服务器实验。已验证的安装配方固化在 pyproject `gpu`
  可选组（cupy-cuda12x[ctk] + nvidia DLL wheels，Windows 下缺一不可）。
- 作为备选：只有当 GCM 涌现的收益确立、且 GPU 加速能把成本压到可接受时，才投入。

## 自研简化引擎（可选路线）

不自研完整 GCM，把现有诊断式 DAG 演化成「粗网格动力迭代 + cell 尺度次网格参数化」：
粗网格（2°-5.6°）上跑风/波/ΔP/水汽预算的迭代（EMIC 形态），细尺度物理
（D1 Fr 阻挡、Smith-Barstad 型代数地形雨、冷阱）留在 cell 尺度作为次网格参数化，
守恒 remap 回 cell。详见待办登记的 S5（粗网格预算提案）。与采用外部 GCM 相比：
同物理纪律天然满足、输出 schema 零迁移、nacrea 特化输入（下节）无需 Fortran 魔改；
代价是要自己承担动力学正确性证明（对照 ExoPlaSim/THAI 类基准）。

## nacrea 特化输入（潮汐卫星型世界的 GCM 需求清单）

无论采用外部 GCM 还是自研，nacrea 类世界需要四项非标准输入（外部聊天 :992-1010 的
工程建议，物理上成立）：

1. **固定次级辐射源**：潮汐锁定 → 巨行星在天空固定（亚巨行星面），其红外辐射 +
   反射星光是一个空间固定、随相位缓变的辐射源，需硬编码进辐射方案（恒星之外的
   第二热源；Aegis 大气 1000 atm、albedo 0.343 → 反射分量可观）。
2. **日食掩码**：轨道面 ±0.65° 的 4.7 年摆动 → 食季位置漂移；生成时间-空间掩码
   进日照强迫（慢自转行星上一次食 = 数十小时连续降温，脉冲效应强）。公式参照
   [WBP #41](https://worldbuildingpasta.blogspot.com/2025/09/day-and-night-on-habitable-moons.html)：
   全食最大时长 =（行星角径 − 恒星角径）/360° × 日长；行星角径常规带 5-15°；
   太阳日 = 轨道周期 ×（1 ± 1/行星年周期比）（顺/逆行差一个符号）。
3. **动态海底热流边界**：11 kyr 周期 0.05→1.85 W/m²（用户已裁决压低 e_max 至
   0.005），空间分布集中洋脊/热点——海洋底边界的时间插值 4D 输入。
4. **慢自转参数组**：Ω = 1/3 地球、g = 1.05g；罗斯贝变形半径大增 → 网格分辨率
   需按天气系统尺度放大（粗网格可接受度反而更好）。

## 与现有 DAG 的关系

- GCM 是**替换**而非叠加：若切 GCM，诊断式 DAG（温度→风→水汽→降水）整体替换为
  GCM 的单次耦合求解。
- 中间态：GCM 作为「校准参照」离线运行，不替换主线（见上「判断准则」）。

## ExoPlaSim harness（已实现，2026-10-05）

GCM 当前作为**气候引擎的 offline oracle**使用（验证 Ω 依赖、倾角分支、
慢自转夹具的动力学侧证），不进 build 管线。入库形态 = 薄适配层：

- `src/dreamulator/gcm/mapping.py` — 世界输入 → `Model.configure` 参数的
  **纯函数映射**（零 exoplasim 依赖、可单测）。单位换算集中在这一处：
  `radius` 期望 **R⊕ 不是米**（exoplasim `__init__.py` 写 `PLARAD =
  radius*6371220.0`；2026-09-07「风场死寂」悬案即传米所致，2026-10-05 破案，
  回归测试 `tests/test_gcm_mapping.py::test_radius_never_in_metres_regression`
  钉死）。恒星有效温度经 `temperature` 键传入 `startemp`（ExoPlaSim 据此
  算两带光谱分割——K 星 NIR 份额高，漏传会按 G2 光谱算温室）。温室映射：
  `greenhouse_mode=none|flux_boost|pco2`；nacrea 辐射身份已经路线 1 裁决
  （pCO2 成分驱动，见 `nacrea-insolation-recalibration.md`）。
- `src/dreamulator/gcm/runner.py` — 运行编排：`ensure_environment()` 把
  pyfft/meson 静默失败（上游把异常注释了）变成显式报错；连续多年积分走
  `N_RUN_YEARS` namelist（`run(years=N)` 每年重启冷 Fortran 进程）——
  **必须同时清零 `N_RUN_STEPS`**（`multi_year_otherargs()`）：configure 对
  rotationperiod≠1 写死 11520 步，Fortran 主循环步数倒计时归零即无条件
  return，N_RUN_YEARS 被静默截断成 1 年（2026-10-06 破案，回归测试钉死）；
  后处理经 `cfgpostprocessor(times=years*12)` 输出真月度记录（pyburn 默认
  `times=12` 会把任意时长聚合成 12 条）。**暖起动/续算走
  `configure(restartfile=<path>)`**（一等 API，configure 自己把种子 cp 成
  workdir/plasim_restart，Fortran `restart_ini` 按存在性加载，证据行
  "Found N variables in file" 落 MOST_DIAG）——**预置 workdir/plasim_restart
  会被 configure 静默删除**（restartfile 为空即 `rm`，`__init__.py`
  L2643-2646；2026-10-07 暖支实验首跑因此变成冷起动，yr1 温度体检抓获）。
  原始 MOST 保留；manifest 记 input 哈希/参数/版本。
- `src/dreamulator/gcm/diagnostics.py` — 从 .nc 提取急流纬度/强度、Hadley
  边界（质量流函数，**勿用速度势 psi**——其零线在 ITCZ）、热力对比、涡动
  方差。注意 pyburn 的 lat/lon **本来就是度**（units: deg），勿再 rad2deg。
  `t_global_c` 用 **tas（2m 气温）**——ta 全层平均含 −100°C 级平流层，会
  误报 ~40 K 冷偏（旧口径保留为 `t_global_column_c`）。能量收支：净 TOA =
  `rst + rlut`（PlaSim 通量正向下；rlut=−OLR；rsut 与 rst 不闭合，短波
  收支科学暂勿用）。**模型日历漂移**：N_DAYS_PER_YEAR 由自转周期取整
  （nacrea 120 模型日/年 vs 真实轨道年 99.8 日），季节在 record 索引里
  漂移——季节分析用 `orbital_phase_of_records()` 按轨道相位重对齐。
- `src/dreamulator/gcm/plotting.py` — 全球概览图（中文 caption + CJK 字体
  回退链；平均场条带状是 aquaplanet 对称强迫的正确物理，涡动看时间 std）。
- `scripts/climate/gcm/run_exoplasim.py` — CLI 入口；`bootstrap.sh` — 任意
  Ubuntu 容器/WSL 的环境引导（刻意不用 uv：仓库树内 uv.toml 覆盖 index 的坑）。
- 依赖走 `[gcm]` 可选 extra（钉 exoplasim==3.4.2）。

当前状态（2026-10-06）：harness 四层 bug 破案后（时长截断/输出聚合/ta 诊断/
恒星光谱），earth 参照臂 50 yr 收敛 +4.1°C（配置冷偏 −9.6 K，主体 = slab
海洋无动力热输送 → 海冰过量 → 反照率锁；绝对 Ts 对标需 earth 参照偏差订正）。
nacrea 标定走路线 1 新恒星参数 × pCO2 网格（SoT = `private/plans/
gcm-calibration-round-01.md`，判据与偏差订正协议见 `nacrea-insolation-
recalibration.md` §3.7）。早期 aquaplanet 对照数字（2026-10-05 批）因时长
截断作废。

## 参考

- ExoPlaSim（alphaparrot/ExoPlaSim，Paradise et al. MNRAS 2022）：PlaSim 扩展，潮汐锁定/非太阳光谱/超地球。
- ExoCAM（storyofthewolf/ExoCAM）：CESM 系外行星分支，全复杂度。
- SpeedyWeather.jl（Klöwer et al. 2024, JOSS）：Julia 谱大气模型，GPU + 可微分路线图。
- ClimaAtmos.jl / ClimaCore.jl（CliMA, Caltech）：GPU-native 下一代 ESM 框架。
- EOS-ESTM（Biasiotti et al. 2022, arXiv:2206.05103）：宜居系外行星 EBM（同类型参照）。
- Fauchez et al. 2020 / Sergeev et al. 2022 / Turbet et al. 2022（GMD）：THAI 系外 GCM 互比基准。
- worldbuildingpasta 实践者参照（2026-09-27 全站调研）：① [ExoPlaSim 参数扫描画廊](https://worldbuildingpasta.blogspot.com/2022/07/climate-explorations-supplement-climate.html)
  + 断点续跑跑批 harness——离线参照臂的实施范本（安装/基准手册见其
  Apple Pie VI 教程）；② 公共 GCM 对照数据：Li et al. 2022（显生宙 CESM，
  [Köppen 序列](https://worldbuildingpasta.blogspot.com/2023/08/hurried-thoughts-phanerozoic-koppen.html)）、
  Farnsworth et al. 2023（[Pangea Proxima HadCM3](https://worldbuildingpasta.blogspot.com/2026/07/public-climate-data-explorations-pangea.html)，
  含低分辨率 GCM 半干旱偏差记录——做 GCM 对照时先校准预期）；③
  [多体潮汐叠加式](https://worldbuildingpasta.blogspot.com/2024/05/hurried-thoughts-multiple-moon-tides.html)
  （分量正弦和，Earth 校验 36/60 cm）→ 待办 11 卫星轮参照。
- Miyasaka & Nakamura (2010, J. Climate)：副热带反气旋的海陆热力对比生成机制。
- 外部聊天核查记录：`private/chats/chat-撒哈拉沙漠干湿周期驱动力.txt`（2026-09-27
  核查：GPU 段 CliMA/SpeedyWeather 属实；EOS-ESTM「GPU 加速」与 HEXTOR「THAI 广泛
  使用」两处为幻觉/夸大；神经代理外推限制已注记）。
