# 气候层 GCM 方案（远期备选）

> 状态：远期提案。当前主线是「诊断式单向 DAG + 聪明预设」（见
> `climate-layer-improvement.md`）。本文件是**全动力学 GCM** 的备选路线，
> 大致列出做法，重点在「涌现 vs 高效」的平衡。不排优先级、不承诺时间。
> **已实现部分**：ExoPlaSim 离线参照适配层，见下文 §「ExoPlaSim harness（✅ 已实现）」。
> GCM 在当前阶段的角色是验证参照而非运行时引擎，本文件的远期方案不受影响。

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

## 后端引擎矩阵（2026-10-12 更新）

**CPU 阵营**（成熟度按降序）：

| 引擎 | 定位 | 算力 | 备注 |
|------|------|------|------|
| [ExoPlaSim](https://exoplasim.readthedocs.io/)（EMIC 级） | 系外行星 GCM 入口，本项目现役参照臂 | 本机实测 T21 8 核约 1 min/模式年，T42 16 核约 2.3 min/模式年 | 潮汐锁定和非太阳光谱原生支持；海洋只有平板混合层，没有动力海洋（PlaSim 的 LSG 海洋在 ExoPlaSim 中只是空壳），极向热输送只能靠混合层水平扩散或给定热通量补 |
| [Isca](https://www.exeter.ac.uk/research/isca/)（Exeter） | 理想化 GCM，理论扫描 | 工作站可跑 | 快速验证「慢自转下哈德利宽度/急流形态」类问题 |
| [ExoCAM](https://github.com/storyofthewolf/ExoCAM) | CESM 系外分支，全复杂度 | HPC 级 | 云微物理/辐射最精；海洋模块简化 |
| [ROCKE-3D](https://www.giss.nasa.gov/tools/rocke-3d/)（NASA GISS） | 耦合 GCM，古气候/系外 | CPU 集群级，动力海洋需数百模式年起转 | 完整耦合的动力海洋与海冰；支持非太阳光谱、任意地形与海底地形；THAI 互比参与者；支持自定义底边界条件（潮汐热流注入点）；公开版需在 GISS 注册下载 |
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

**神经代理**（Earth-2 MIP / GraphCast / FNO 一族）：概念真实且有 GPU 服务器级算力加持，但
代理模型只在训练分布内插值可靠——对未见强迫域（如 11 kyr 潮汐加热扫描）外推不成立，
只可作加速器不可作真值源。

### 分层策略

选型按四条标准排序：第一，有动力海洋和海冰，这是 ExoPlaSim 最大的短板，平板海洋会让海冰
偏多、高纬偏冷，直接影响冰反照率反馈和双稳态判断；第二，支持系外行星设定（K 型星光谱、
任意自转与倾角、自定义地形与海底地形）；第三，有维护、有互比基准；第四，能用上本机资源。
按这四条，没有单一后端能兼顾扫描成本和物理完整度，所以分三层使用：

| 层级 | 后端 | 用途 | 状态 |
|---|---|---|---|
| 扫描层 | ExoPlaSim（对齐配置，混合层水平扩散） | CO₂、倾角等参数的大规模扫描与冷暖双臂滞后扫描；单次 30 年运行约半小时 | 现役，运行手册见 `docs/usage/exoplasim-gcm.md` |
| 验证层 | ROCKE-3D | 在扫描层选出的少数关键点上做动力海洋验证，检验平板海洋的结论（双稳态、冰缘位置、敏感度）是否成立 | 待引入：需注册下载源码，评估编译与地球冒烟 |
| GPU 层 | CliMA 系列（ClimaAtmos、Oceananigans、ClimaSeaIce 与耦合器） | 高分辨率或长时间的耦合积分，用满 8 张 GPU | 远期观望：大气辐射需改造以处理非太阳光谱，耦合系统仍在成熟中 |

不选的后端及理由：ExoCAM 的海洋通常仍是平板加给定热通量，补不上动力海洋这块短板，
CESM 构建体系又很重；Isca 同样只有平板海洋；SpeedyWeather.jl 的物理过程过于简化，算不准
冰反照率一类问题。三层都用现成后端，符合 CLAUDE.md 引擎纪律第 7 条（需要更强动力学时转向
现成后端，而非自建小 GCM）。

## GPU 加速杠杆与本机资源

- 谱方法（球谐变换）和有限体积在 GPU 上可大规模并行（FFT/球谐、批处理）。
- **可用资源**：开发笔记本（消费级 6 GB GPU，PoC 级）；计算资源（2026-10-12 实测）为
  多卡 GPU 服务器（单卡百 GB 级显存、双精度完整可用）+ 多核服务器 CPU（配额数十核）
  + TB 级内存。GPU 让 GPU-native GCM 的「慢」从障碍变成可选项，
  也让「自研简化引擎 + GPU 内核」成为现实选项；CPU 配额决定了 Fortran CPU 模式（ExoPlaSim、
  ROCKE-3D）的并发上限，可同时支撑多个 T21 级运行。
- 传统 Fortran CPU GCM 无法利用 GPU；若走 GCM 路线且要 GPU，候选收窄到
  SpeedyWeather.jl / CliMA（均需系外辐射魔改）或神经代理（需先有真值生成器）。
- **本机 S6 PoC 判负（2026-09-27，RTX 3060 Laptop 6GB）**：真实预算矩阵
  （n=200k、nnz=1.4M、MMD 排序后 nnz(L+U)=22.6M）上 CuPy splu 分解+求解
  7.2 s vs scipy SuperLU 2.0 s（**3.5× 慢**）；精度等价（rel 5e-15）、VRAM
  2.15 GB 装得下、传输 0.22 s——瓶颈是填充因子的散射访存，GPU 不擅长。
  结论：本地 GPU 直接稀疏 LU 无收益，不集成求解路径；GPU 服务器（带宽约
  50 倍，可用 cuDSS）上的复测尚未进行。已验证的安装配方固化在 pyproject `gpu`
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

## ExoPlaSim harness（✅ 已实现）

GCM 当前作为气候引擎的离线参照使用，不进 build 的模拟管线，代码在 `src/dreamulator/gcm/`。
例外是作者指定的固定气候分支（`climate_source: gcm`）：build 只导入一次 GCM 运行预先算好的
逐格字段，不运行 GCM。
运行步骤、参数和输出口径见 [`../../usage/exoplasim-gcm.md`](../../usage/exoplasim-gcm.md)；
各个已知陷阱的机理和源码证据写在 `runner.py`、`mapping.py`、`diagnostics.py` 的模块说明里；
nacrea 的定标配置与结论见 `data/worlds/nacrea/design-notes/0012-climate-gcm-calibration.md`。

固定气候分支输出长期月字段，降水通过原生父格与目标球面足迹的交叠保持分量预算。
运行摘要使用近地面变量、高斯面积及轨道相位权重，分辨率参照以辐射收支分析平衡差异。
频繁输出的湿度缓存和重启状态由隔离适配器维护，补丁及二进制随来源记录。
当前生产接口与采用边界见 [气候管线 14 节](../pipelines/climate-pipeline.md#14-gcm-与参数化管线的定位后续开发)。

### 上游维护状况与 fork 策略（2026-10-12 核查）

ExoPlaSim 处于低维护状态。最后一次发版是 3.4.2（2025-01），之后作者只零星合并小改动，
最近一次在 2026-09。2026-08 一位外部贡献者提交了 14 个实质性修复，至今没有合并，其中几项
直接影响本项目：

| 上游编号 | 内容 | 对本项目的影响 | 处理 |
|---|---|---|---|
| PR #52 | pyburn 读取原始输出的复杂度是平方级 | 后处理耗时从约 16 分钟降到约 3 分钟 | 已在本地 Python 层用同样思路修复，输出逐位一致 |
| PR #62 | 短波气体吸收按太阳光谱拟合，非太阳型主星需要重新加权 | nacrea 的主星是 K6 型，温室与水汽吸收可能有系统偏差 | 未处理，需要改 Fortran |
| Issue #69 | 自转周期不等于 1 天时，日照在经向上有固定偏差 | nacrea 自转 3.13 天；纬向平均不受影响，海陆空间分布会受影响 | 未处理，需要改 Fortran |
| PR #53、#54 | MPI 广播缺失、重启时累加器丢失，可能死锁或静默损坏输出 | 多核运行和暖启动续算都会用到 | 上游问题按其路径核验；本地河流库重启保留由独立补丁处理。 |

不自研 GCM 的理由有三条：GCM 的作用是独立检验 EBM，自研模型与 EBM 出自同一套假设就失去了
参照意义；引擎纪律第 7 条要求需要更强动力学时转向现成后端；
当前适配器维护 Python 包装、Fortran 河流稳定积分及诊断输出，物理方案按对应来源验收。按情况分级处理：

| 情况 | 做法 |
|---|---|
| 补丁涉及包装与诊断输出 | 在 `runner.py` 中维护隔离构建，注明上游依据并记录源码及二进制哈希。 |
| 需要修改 Fortran 物理部分（#62、#69 很可能需要，T42 短波浮点异常也属此类） | 维护一个固定 commit 的 fork，选择性合入外部贡献者的修复，从 fork 安装 |
| 上游停止维护，或 fork 负担过重 | 按上文的分层策略换用其他现成后端，系外行星辐射部分需要自行补齐 |

是否建立 fork 的决定登记在 `docs/design/roadmap.md` 的技术债表里，目前按作者裁决先只做问题
定位，修复往后放。

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
- 外部聊天核查（2026-09-27）：GPU 段 CliMA/SpeedyWeather 属实；EOS-ESTM「GPU 加速」与 HEXTOR「THAI 广泛
  使用」两处为幻觉/夸大；神经代理外推限制已注记。
