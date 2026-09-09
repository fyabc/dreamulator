# 轨道稳定性（N-body 验证）

## 核心概念

解析的轨道根数（`stellar.yaml` 里的半长轴、偏心率、倾角）只能描述**单天体开普勒轨道**，
无法描述多体系统的真实演化。当世界含**共振链**、**紧密轨道卫星**、**长期摄动**时，
仅凭开普勒根数判断「系统稳不稳定」是危险的——需要 N-body 数值积分来验证。

dreamulator 用 REBOUND（Rein & Liu 2012）做这件事。脚本 `scripts/astro/rebound_nbody.py`
是完整验证工具：直读目标世界 `stellar.yaml`（轨道要素 + 质量/半径/自转倾角），
支持 J2 长期摄动与常数 Q 潮汐 e 阻尼算子（Lie 分裂）。**卫星系统的物理判据**
（互希尔间距、恒星潮汐极限、共振链冷启动陷阱、潮汐自洽核算）见姊妹篇
[satellite_system_stability.md](satellite_system_stability.md)。

## 工具：`scripts/astro/rebound_nbody.py`

### 怎么跑

```bash
uv run python scripts/astro/rebound_nbody.py                     # 落地构型判定（IAS15 20 kyr + MEGNO）
uv run python scripts/astro/rebound_nbody.py --baseline          # 10 yr 健全性对照
uv run python scripts/astro/rebound_nbody.py --sat-scan          # θ₁×θ₂ 共振相位扫描（36 点 × 300 yr）
uv run python scripts/astro/rebound_nbody.py --j2 0.008 --tides  # + J2 进动与潮汐阻尼算子
uv run python scripts/astro/rebound_nbody.py --t-end 1e5         # 自定义时长（IAS15 ~16 yr/s）
```

依赖在 `pyproject.toml` 的 `dev` extra（`rebound>=4.0`），`uv sync --all-extras` 安装，
**不是**默认运行时依赖。REBOUND 5.x API 与数值方法教训（WHFast 对卫星系统无效、
additional_forces 不可靠等）见 satellite_system_stability.md §7。

### 单位

REBOUND 默认单位：`G=1`，长度 AU、质量 M☉、时间 yr。质量换算 `M⊕ = 3.003×10⁻⁶ M☉`
（脚本里的 `MEARTH_MSUN` 常量）。

### 怎么改成别的世界

脚本直读 `stellar.yaml`：`load_system()` 联结 `orbits`（要素）与 `bodies`
（mass_earth / radius_km / axial_tilt_deg），`build_landed_system()` 按 yaml 逐体
构建**真实构型**（含 mean_anomaly_epoch_deg——不再有硬编码要素）。`_STELLAR_YAML_RELPATH`
指向 nacrea，其他世界改此常量或给 `load_system(yaml_path=...)` 传路径。
卫星经 `primary=` 绕行星；角度从 yaml 的度自动转弧度。

报告用 `p.orbit(primary=...)` 取轨道根数——**REBOUND 5.x 里 `orbit` 是方法**，要显式传
`primary`（行星相对恒星、卫星相对母星），否则默认相对质心会算出错的根数。

## 关键物理：共振链不是「设对半长轴就行」

### 1:2:4 拉普拉斯共振有两个共振角

Nacrea : Cadence : Vigil = 1:2:4（伽利略卫星 Io:Europa:Ganymede 类比）的共振角有两个：

$$\phi_{12} = \lambda_1 - 2\lambda_2,\qquad \phi_{23} = \lambda_2 - 2\lambda_3$$

其中 $\lambda = \Omega + \omega + M$（平经度）。链稳定要求**两个角都天平动**（librate），
不是某一个组合角等于某值。

### `M=0` 是不稳定初始条件

`stellar.yaml` 全天体 `mean_anomaly_epoch_deg: 0.0`，即所有天体同相位起跑 → 两个共振角
都落在 0°。实测（10 年积分）卫星链快速失稳：Vigil 被弹出（e>1）、Cadence 偏心率暴涨 35×。

### 单改相位到 180° 不够

实测把组合角 $\phi_L = \phi_{12} - \phi_{23}$ 设成 180°（如 Nacrea M=180°）**仍不稳定**：
$\phi_{23}$ 仍是 0°（不稳定的 2:1 角没动）。Vigil 照旧逃逸。

### 全相位扫描的更新（2026-09-08）

θ₁×θ₂ 网格 36 个初始相位 @300 yr **全灭**（33 个 300 yr 内弹射，最优幸存者
725 yr 仍死）：对大质量卫星链（μ~2.4×10⁻³、互希尔间距 4.9 r_H,m），
**不存在可存活的冷启动相位**——调相位救不了架构问题。机理（锁定共振需迁移史
绝热捕获 + 潮汐老化，冷启动到不了吸引子）与 GJ 876 / 伽利略对照见
satellite_system_stability.md §3。

### 终局（2026-09-09）：nacrea 卫星架构放弃共振链

后续 ~50 次积分（完整矩阵见 nacrea 设计笔记 0009 附录）证明：在 μ~2.4×10⁻³、
K8 宜居带（恒星潮汐场 ∝ M_*/a_*³，比木星系强 ~3200×）的系统里，顺行外卫、
双逆行共动对、层级双星、双单体、倾斜保护、质量/距离/阻尼杠杆全部无法给出
Gyr 级多卫构型——「e 带重叠定理」使带内（0.2–0.5 r_H）多居住者结构性禁绝
（satellite_system_stability.md §8.7）。nacrea 最终裁决 = 采用**双单体逆行
捕获卫**天空 + **卫星动力学层硬度豁免**（设定内恒常、轨迹级判决 24.5 kyr
存档设计笔记）；设定值取设计意图带（Nacrea 受迫 e 0.002–0.007），实测晚期
尖峰不采用。本节及上文保留为共振链冷启动的方法学教训。

### 希尔球稳定上限（顺行卫星更脆弱）

卫星绕行星的稳定性上限用希尔半径 $r_H = a_p (m_p / 3 M_\star)^{1/3}$ 衡量
（瞬时轨道乘 $(1-e_p)$）。数值研究（Hamilton & Burns 1991；Domingos, Winter &
Yokoyama 2006）：**顺行 ~0.48 r_H、逆行 ~0.93 r_H**。临界带之下仍有快速失稳
混沌区——Nacrea 实测：顺行 0.37 r_H 存活 ≥6000 yr、0.41 r_H 25 yr 内弹射；
逆行 0.458 r_H 存活（工程安全线：顺行 ≤0.38、逆行 ≤0.5）。

## 设计其他世界的流程

1. **搭系统**：恒星 + 行星（含共振链）+ 卫星，写进 `build_*_system()`。
2. **短时积分**（~10 yr，覆盖内层天体数百圈）：看偏心率是否暴涨、卫星是否逃逸 → 判断
   「初始条件是否落在稳定区」。
3. **长时积分**（~kyr，后台跑）：标定进动周期（近日点进动、交点进动、气候岁差拍频）。
4. **迭代**：不稳定时先跑**对照实验**（同方法积分已知稳定的真实系统，如伽利略卫星——
   对照活而设定死才说明是架构问题而非方法问题），再按 satellite_system_stability.md
   排查四条约束：互希尔间距（§1）、恒星潮汐极限（§2）、共振冷启动陷阱（§3）、
   多外卫混沌散射区 + 宜居卫星加热预算（§8）。
   调相位/共振角通常救不了架构性不稳定（Nacrea 36 相位全灭实测）。

**判断标准**：短时积分内偏心率稳定（不单调暴涨）、无天体逃逸（e 始终 < 1），即视为
「当前初始条件可行」。注意两条混沌区红线（§8.2）：单次「存活」可能只是相位彩票
（被认证的是精确实现而非参数区间）；认证窗口必须显著长于关注寿命，否则「存活」
可能是截断伪影。多卫构型还必须并列检查宜居卫星的受迫 e 加热预算（§8.4）——
它比弹射判据更早触发。

## 现实参考数据

| 系统 | 共振链 | 关键值 |
|------|--------|--------|
| 伽利略卫星 | Io:Europa:Ganymede = 1:2:4 拉普拉斯共振 | 共振角 $\phi_L$ 天平动于 ~180° |
| GJ 876 | 行星 2:1 共振链 | 受迫偏心率 e=0.03–0.26 |
| 土星卫星系 | 多共振 + Cassini 态 | 自转轴随轨道面进动、倾角恒定 |

## 参考

- Rein, H., & Liu, S.-F. (2012). REBOUND: an open-source multi-purpose N-body code. *A&A*, 537, A128.
- Rivera, E. J., et al. (2010). The Lick-Carnegie Exoplanet Survey: A Uranus-mass Fourth Planet for GJ 876. *ApJ*, 719, 890.
- Peale, S. J. (1976). Orbital resonances in the solar system. *ARAA*, 14, 215.
- Hamilton, D. P., & Burns, J. A. (1991). Orbital stability zones about asteroids. *Icarus*, 92, 118.
