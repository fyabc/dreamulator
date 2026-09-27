# 气候层 GCM 方案（远期备选）

> 状态：远期提案。当前主线是「诊断式单向 DAG + 聪明预设」（见
> `climate-layer-improvement.md`）。本文件是**全动力学 GCM** 的备选路线，
> 大致列出做法，重点在「涌现 vs 高效」的平衡。不排优先级、不承诺时间。

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
   进日照强迫（慢自转行星上一次食 = 数十小时连续降温，脉冲效应强）。
3. **动态海底热流边界**：11 kyr 周期 0.05→1.85 W/m²（用户已裁决压低 e_max 至
   0.005），空间分布集中洋脊/热点——海洋底边界的时间插值 4D 输入。
4. **慢自转参数组**：Ω = 1/3 地球、g = 1.05g；罗斯贝变形半径大增 → 网格分辨率
   需按天气系统尺度放大（粗网格可接受度反而更好）。

## 与现有 DAG 的关系

- GCM 是**替换**而非叠加：若切 GCM，诊断式 DAG（温度→风→水汽→降水）整体替换为
  GCM 的单次耦合求解。
- 中间态：GCM 作为「校准参照」离线运行，不替换主线（见上「判断准则」）。

## 参考

- ExoPlaSim（alphaparrot/ExoPlaSim，Paradise et al. MNRAS 2022）：PlaSim 扩展，潮汐锁定/非太阳光谱/超地球。
- ExoCAM（storyofthewolf/ExoCAM）：CESM 系外行星分支，全复杂度。
- SpeedyWeather.jl（Klöwer et al. 2024, JOSS）：Julia 谱大气模型，GPU + 可微分路线图。
- ClimaAtmos.jl / ClimaCore.jl（CliMA, Caltech）：GPU-native 下一代 ESM 框架。
- EOS-ESTM（Biasiotti et al. 2022, arXiv:2206.05103）：宜居系外行星 EBM（同类型参照）。
- Fauchez et al. 2020 / Sergeev et al. 2022 / Turbet et al. 2022（GMD）：THAI 系外 GCM 互比基准。
- Miyasaka & Nakamura (2010, J. Climate)：副热带反气旋的海陆热力对比生成机制。
- 外部聊天核查记录：`private/chats/chat-撒哈拉沙漠干湿周期驱动力.txt`（2026-09-27
  核查：GPU 段 CliMA/SpeedyWeather 属实；EOS-ESTM「GPU 加速」与 HEXTOR「THAI 广泛
  使用」两处为幻觉/夸大；神经代理外推限制已注记）。
