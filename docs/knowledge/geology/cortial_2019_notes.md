# Cortial et al. 2019 *Procedural Tectonic Planets* 论文解读

> **引用**: Yann Cortial, Adrien Peytavie, Éric Galin, Éric Guérin.
> *Procedural Tectonic Planets*. Computer Graphics Forum (Eurographics 2019),
> Vol. 38, No. 2. DOI: [10.1111/cgf.13614](https://doi.org/10.1111/cgf.13614)
>
> **HAL 全文**: [hal-02136820](https://hal.science/hal-02136820/)
> **视频**: [Eurographics 2019 Presentation (YouTube)](https://www.youtube.com/watch?v=GJQVl6Xld0w)
> **后续**: Cortial 获 2020 CNRS 最佳博士论文奖，现为 Arkane Studios 图形程序员。

> **来源说明**：本文自 `docs/design/terrain-pipeline.md` 附录 D 整体上浮（2026-08）。
> 小节编号沿用原附录 D；原文档中重复的编号（两个 D.11 / 两个 D.12）已重排为
> D.13–D.15，原 D.10 表格被正文截断的尾行已并回 D.10。文中 §x 引用均指
> `docs/design/terrain-pipeline.md` 章节；设计文档 §17（时间演化与威尔逊循环）
> 以本文为核心参考。

---

## D.1 论文定位

这篇论文是**程序化星球生成**领域的里程碑工作。它不追求物理精确模拟（不计算地幔对流 PDE），
而是用**现象学方法（phenomenological approach）** 捕捉板块构造的大尺度地貌效应。
核心贡献：

1. **首次实现完整的交互式程序化板块星球**：用户可实时控制板块运动、触发裂解事件
2. **四大构造现象的程序化建模**：俯冲、大陆碰撞、洋壳创生、板块裂解
3. **双层放大管线**：粗分辨率构造模型 → GPU 放大至 ~100m 分辨率

## D.2 网格与数据结构

### 球面采样与三角剖分

- **Fibonacci 采样**：近似均匀的球面点分布
- **STRIPACK 算法**（Renka 1997）：全局球面 Delaunay 三角剖分
- **默认 500,000 采样点**（6,370km 半径行星 → ~35km 分辨率）
- 三角剖分按 Voronoi cell 归属划分为板块

### 重采样策略（关键设计决策）

- 采样/网格化作为**离线预处理**完成
- **不在每步重新网格化**（太贵），而是每 10-60 步执行一次全局重采样
- 离散板块之间的新点从洋壳生成方法获取参数
- 其他点使用重心插值从所属板块获取

## D.3 地壳参数化

每个板块上的每个采样点存储以下属性：

| 属性 | 海洋地壳 | 大陆地壳 |
|------|---------|---------|
| 地壳类型 $x_C$ | oceanic | continental |
| 地壳厚度 $e$ | ~7km | ~35-50km |
| 地形高程 $z$ | -1 到 -10km | 0 到 10km |
| 地壳年龄 $a_o$ | ✓（自洋中脊创生） | — |
| 洋脊方向 $r$ | ✓ | — |
| 造山年龄 $a_c$ | — | ✓ |
| 造山类型 $o$ | — | Andean / Himalayan |
| 褶皱方向 $f$ | — | ✓ |

## D.4 四大构造现象

### 俯冲（Subduction）

**触发条件**：
- 洋-洋汇聚 → 较老板块俯冲
- 洋-陆汇聚 → 洋壳始终俯冲
- 陆-陆汇聚 → 部分强制俯冲，随后转为碰撞

**上隆公式**（上方板块点 $p$ 的高程增量）：

$$u_j(p) = u_0 \cdot f(d(p)) \cdot g(v(p)) \cdot h(\tilde{z}_i(p))$$

其中：
- $u_0 = 0.6$ mm/y — 基准上隆速率
- $f(d)$ — 分段三次曲线：在控制距离处达峰值，在 $r_s = 1800$ km 处衰减至 0
- $g(v) = v / v_0$ — 线性速度传递（$v_0 = 100$ mm/y 为最大板块速度）
- $h(\tilde{z}_i) = \tilde{z}_i^2$ — **二次**高程影响（海平面以上特征主导）

**Slab Pull（欧拉极修改）**：

$$\mathbf{w}_i(t+\delta t) = \mathbf{w}_i(t) + \varepsilon \sum_{k} \frac{\mathbf{c}_i \times \mathbf{q}_k}{\|\mathbf{c}_i \times \mathbf{q}_k\|} \cdot \delta t$$

俯冲带动态修改板块旋转轴，使长俯冲前线对板块运动方向产生显著影响。

### 大陆碰撞（Continental Collision）

- **触发**：两板块互穿距离 > 300km
- **影响半径**：$r = r_c \cdot \sqrt{v/v_0} \cdot (A/A_0)^\beta$，$r_c = 4200$ km
- **离散高程跃升**：$\Delta z(p) = \Delta_c \cdot A \cdot (1 - d/r)^2{}^2$，$\Delta_c = 1.3 \times 10^{-5}$ km$^{-1}$
- **地体缝合**：碰撞地体从俯冲板块脱离，附着到上覆板块

### 洋壳创生（Oceanic Crust Generation）

- 在离散边界自动形成洋中脊
- **高程混合**：$z = \alpha \cdot \bar{z} + (1-\alpha) \cdot z_\Gamma$
  - $\bar{z}$：两板块间线性插值
  - $z_\Gamma$：模板洋中脊剖面函数
  - $\alpha$：到洋脊距离 / (到洋脊距离 + 到最近板块边界距离)
- 每 10-60 步执行一次（涉及采样和网格化）

### 板块裂解（Plate Rifting）

- **Poisson 概率模型**：$P = \lambda e^{-\lambda}$，$\lambda = \lambda_0 \cdot f(x_P) \cdot A/A_0$
- 大板块更容易裂解（防止超级大陆永久存在）
- 裂解为 2-4 个子板块，各自获得随机离散方向
- 支持用户手动触发（指定位置、断裂线、时机）

## D.5 侵蚀与衰减

**每步**应用的简化模型：

| 过程 | 公式 | 常数 |
|------|------|------|
| 大陆侵蚀 | $z \mathrel{-}= (z/z_c) \cdot \varepsilon_c \cdot \delta t$ | $\varepsilon_c = 0.03$ mm/y, $z_c = 10$ km |
| 洋壳沉降 | $z \mathrel{-}= (1 - z/z_t) \cdot \varepsilon_o \cdot \delta t$ | $\varepsilon_o = 0.04$ mm/y, $z_t = -10$ km |
| 海沟沉积 | $z \mathrel{+}= \varepsilon_t \cdot \delta t$ | $\varepsilon_t = 0.3$ mm/y |

**无**水力侵蚀、热侵蚀、冰川侵蚀或风蚀——设计为与后续侵蚀方法兼容。

## D.6 放大管线（Amplification）

| 区域 | 方法 | 技术 |
|------|------|------|
| 海洋地壳 | 程序化 | 3D Gabor 噪声（沿洋脊方向定向，模拟转换断层）+ 高频梯度噪声 |
| 大陆地形 | 基于样例 | USGS SRTM90 真实地形原语，按造山类型分类（Andean/Himalayan/古山/平原），沿褶皱方向旋转对齐 |

使用 19 个真实地形样例集：7 个喜马拉雅型、11 个安第斯型、6 个古山脉。

## D.7 完整常数表

| 符号 | 含义 | 值 |
|------|------|-----|
| $\delta t$ | 时间步长 | 2 My |
| $R$ | 行星半径 | 6,370 km |
| $z_r$ | 洋中脊最高高程 | -1 km |
| $z_a$ | 深海平原高程 | -6 km |
| $z_t$ | 海沟高程 | -10 km |
| $z_c$ | 大陆最高海拔 | 10 km |
| $r_s$ | 俯冲影响距离 | 1,800 km |
| $r_c$ | 碰撞影响距离 | 4,200 km |
| $\Delta_c$ | 碰撞系数 | $1.3 \times 10^{-5}$ km$^{-1}$ |
| $v_0$ | 最大板块速度 | 100 mm/y |
| $\varepsilon_o$ | 洋壳沉降率 | $0.04$ mm/y |
| $\varepsilon_c$ | 大陆侵蚀率 | $0.03$ mm/y |
| $\varepsilon_t$ | 海沟沉积率 | $0.3$ mm/y |
| $u_0$ | 俯冲上隆率 | $0.6$ mm/y |

## D.8 性能数据

| 指标 | 值 |
|------|-----|
| 语言 | C++（CPU 构造计算）+ GPU（放大渲染） |
| 硬件 | Intel i7-6700K @ 4GHz, 16GB RAM, GTX 1080 |
| 分辨率 | 35-500km（构造层），~100m（放大层） |
| 默认采样 | 500,000 点 |
| 完成行星 | ~125-250 步（≈250-500 My 模拟时间） |
| 帧率 | 37-145 Hz（自适应网格 + GPU 渲染） |
| 每步耗时 (35km) | 1.9s 总计（俯冲 0.65s + 碰撞 0.63s + 高程 0.62s） |
| 洋壳生成 | 13.1s（每 20-120 My 执行一次） |
| 板块裂解 | 7.7s（离散事件） |

## D.9 已知局限（作者自评 + 地质专家评审）

1. **无热点**：不生成火山岛链（如夏威夷），但可作为特殊采样点实现
2. **无被动大陆边缘**：未建模大陆架浅水区
3. **无排水网络**：但与现有河流生成方法兼容
4. **无气候/大气模型**：明确列为未来工作
5. **过度强制俯冲**：大型地体的俯冲检测/防止计算成本过高
6. **板块裂解不够自然**：旋转轴沿裂谷线，非真实物理断裂

## D.10 对 dreamulator 的启示

| Cortial 2019 特性 | dreamulator 对应 | 状态 |
|-------------------|-----------------|------|
| Euler pole 运动学 | §4 欧拉极与板块运动学 | ✓ 基础管线已覆盖 |
| 地壳参数化表 | §14 数据模型变更 | ✓ 已设计 |
| 俯冲上隆公式 | §5 边界检测 + §6 地形合成 | ✓ 已覆盖（简化版） |
| Slab pull 反馈 | §17.3.B 俯冲消亡 | § 进阶功能 |
| 大陆碰撞造山 | §17.3.C 大陆拼合 | § 进阶功能 |
| 洋壳创生 + 年龄 | §17.3.A 洋壳创生 | § 进阶功能 |
| 板块裂解 | `tectonic_simulator.py::_rift_plates` | ✓ 已实现 (§D.11) |
| 板块裂解 Poisson | §17.3.D 板块裂解 | § 进阶功能 |
| 侵蚀/衰减 | §10 侵蚀 | 基础版已覆盖 |
| 放大管线 | §13 Gaea 局部精细化 | 使用 Gaea 替代 |
| 热点 | 未来工作 | ✗ |
| 气候/大气 | §8 气候模拟 | ✓ 基础管线已覆盖 |
| 河流网络 | §9 河流水文 | ✓ 基础管线已覆盖 |

## D.11 dreamulator 板块裂解实现

**算法** (`tectonic_simulator.py::_rift_plates`):

1. **Poisson 概率模型**: P ∝ λ₀ · (A/A₀)，λ₀ = `rift_base_rate` (默认 **0.01**)
2. **超大盘 boost**: 板 >2× 均值时线性提权（max 3×），＞1.5× 时温和提权（1.3×）。确保半板块级别的超大陆不可避免地裂解（Gondwana 模式）
3. **冷却期**: 正常板 5 步内不再裂解；超大板（>2× 均值）豁免冷却期
4. **cell 刷新**: 裂解前用当前 map 刷新 cell_ids，消除 Voronoi 边界漂移
5. **加权 Dijkstra 分区**: 随机 2-3 种子，每个种子抽取对数均匀生长权重
   （e^{U(-0.9,0.9)}），多源 Dijkstra 产生**不等大碎片**（一两个大碎片 + 若干小碎片），
   避免均匀 BFS 的等大碎片；空 partition 自动过滤
6. **分区安全网**: 分区后 cell 数不完整 → 回退恢复父板块
7. **子板块欧拉极扰动**: 轴偏转 ~10-20°、ω 变幅 ±15% → 相邻子板 >2 cm/yr → 边界检测可识别
8. **微板块清理**: `_cleanup_empty` 每步移除 0-cell 空壳（≥2 板保护）
9. **重分区间隔**: 固定 10 步（与总步数无关），裂解后立即重分
10. **加权 Voronoi 重分区（保持大小偏态）**: 重分区不是无权重的最近种子
    Voronoi（= Lloyd 迭代，吸引子为等面积 CVT，会洗掉偏态），而是**乘法加权
    Voronoi**：每个板块持有出生时确定的持久权重（初始板块取初始剖分面积、
    裂解碎片取碎片面积，`plate_weight` 字典随裂解/清理同步），波前代价
    cost/wᵢ，面积比 ∝ 权重比。规定权重的 Lloyd 型迭代吸引子是**加权 CVT**，
    偏态在质心旋转/边界迁移中保持。最终的 boundary warp 也传入同一权重，
    避免末次重分区再次均匀化。实现：`plate_generator.py::voronoi_partition_warped`
    （`plate_speed`/`locked` 参数）、`tectonic_simulator.py::_plate_speeds`
11. **海沟/造山带小圆弧（Frank 1968 / Tovish 1978，涌现式）**: Voronoi 平分线
    只能是测地线，产不出岛弧的小圆弧——真实机制是俯冲刚性球壳与球面的交线
    （Frank 1968 *Curvature of Island Arcs*），弧半径与俯冲角/汇聚速率相关
    （Tovish 1978）。每次 resample 后 `_trench_arc_relaxation` 从**当前**运动学
    状态推断目标弧（欧拉极相对速度 → 汇聚速率 → 倾角 → 弧矢比 0.10–0.30），
    把汇聚边界段松弛向该弧：洋壳俯冲凸向俯冲板（日本/阿留申式），陆陆碰撞
    凸向 indenter（喜马拉雅/阿尔卑斯式，弧矢 ×0.7）。弧矢在 arc_state 中逐步
    生长（每次 resample ×0.3 松弛）→ 弧度随演化涌现而非初始规定。弯折边界
    先经 `_split_bent_segment` 在拐点拆成更直子段、各带独立弧。配置
    `trench_arc`（0=关，默认 1）。gaia-m 实测：plate_002/016 碰撞带
    sagitta/chord 0.14 → 0.18+（日本弧类比 ≈0.2）。

## D.12 自适应裂解率与真实地球数据

### 参考数据：地球板块数量历史

基于 Matthews et al. (2016) 的 410 My 全球板块重建：

| 时期 | 板块数 | 状态 |
|------|:---:|------|
| 410–260 Ma | 16–20 | 分散状态 |
| 260–160 Ma（Pangea 聚合） | **9** | 超大陆极值 |
| 150 Ma–现今 | 20–45 | 裂解+分散 |
| 现今 | ~15 | 7-8 大板 + 若干小板 |

**关键规律**：板块数在 9–45 之间随超大陆旋回自然振荡。大板（≥10⁷·⁵ km²）始终约 5–8 块，小板数量波动更大。
系统稳定目标：平均 ~15 板，可接受 8–25 板的自然波动。

*Matthews et al. (2016). "Global plate boundary evolution and kinematics since the late Paleozoic." Global and Planetary Change, 146, 226–250. https://doi.org/10.1016/j.gloplacha.2016.10.002*
*Cao et al. (2024). "Earth's tectonic and plate boundary evolution over 1.8 billion years." Geoscience Frontiers, 15(6), 101922. https://doi.org/10.1016/j.gsf.2024.101922*

### PID 控制器（实验性，当前未启用）

超大盘 boost（§D.11-2）已提供足够的自稳定性，无需全局 PID。
如需启用，PID 实现代码已就绪：`tectonic_simulator.py` 中可按步调节
`config.rift_base_rate`。设计模式参考 `docs/worldbuilding/design_patterns.md` §模式 6。

## D.13 研究谱系

```
2016  Cordonnier et al. — 构造隆起 + 河流侵蚀（高度图，非球面）
       Eurographics 2016 / CGF 35(2)
  ▼
2019  Cortial et al. — 完整球面交互式板块星球 ← 本文
       Eurographics 2019 / CGF 38(2)
  ▼
2020  Cortial et al. — 实时超放大（低分辨率行星 → 高分辨率细节）
       The Visual Computer 36(10-12)
  ▼
2026  Borg et al. — 扩散模型生成类地行星（ML + 四叉球）
       Eurographics 2026 / CGF 45(2)
```

## D.14 相关开源实现

| 项目 | 语言 | 与论文关系 |
|------|------|-----------|
| [Arches-Team/Real-Time-Hyper-Amplification-of-Planets](https://github.com/Arches-Team/Real-Time-Hyper-Amplification-of-Planets) | C++/GLSL | 官方 2020 后续论文代码（仅放大，非构造引擎） |
| [FioDev/Procedural-Tectonics](https://github.com/FioDev/Procedural-Tectonics) | C#/HLSL | 社区实现，模拟板块族 + 俯冲 + 岛链 |
| [hecubah/driftworld-tectonics](https://github.com/hecubah/driftworld-tectonics) | Unity/C# | 明确引用 Cortial 2019 |
| [SecondSystem Plate Tectonics](https://second-system.de/2022/03/01/tectonics_1) | — | "深受 Cortial 启发"，统一 Delaunay 网格 + 弹簧-阻尼力 |
| Blender Tectonic Tools | Python | 明确引用论文方法论 |

## D.15 科普与可视化资源

| 资源 | 链接 | 与本项目的关系 |
|------|------|---------------|
| **Fractal Philosophy**: *Maps: Fractals, Tectonics and the Fourth Dimension* | [B站中字](https://www.bilibili.com/video/BV1n2i7BrEmq)（BV1n2i7BrEmq） | 系统讲解分形几何、板块动力学模拟与高维空间映射的科普视频。其中关于地貌特征如何受数学规则驱动、板块运动的可视化呈现，与本管线的 fBm 噪声叠加（§6.4）和板块构造模拟（§3-§5）思路高度契合。对本项目的设计理念有较大启发。 |

---

## 参考资料

- 本文为 `docs/design/terrain-pipeline.md` 附录 D 的整体上浮（2026-08）
- Cortial, Y., Peytavie, A., Galin, E., & Guérin, É. (2019). *Procedural Tectonic Planets*.
  Computer Graphics Forum, 38(2). DOI: [10.1111/cgf.13614](https://doi.org/10.1111/cgf.13614)
- Frank, F. (1968). *Curvature of Island Arcs*. Nature.（D.11-11 海沟小圆弧机制）
- Tovish, A., & Schubert, G. (1978). *Island Arc Curvature, Subducting Slab Dip*.
- Matthews, N.J. et al. (2016). Global and Planetary Change, 146, 226–250.
- Cao, J. et al. (2024). Geoscience Frontiers, 15(6), 101922.
