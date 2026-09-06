# 轨道稳定性（N-body 验证）

## 核心概念

解析的轨道根数（`stellar.yaml` 里的半长轴、偏心率、倾角）只能描述**单天体开普勒轨道**，
无法描述多体系统的真实演化。当世界含**共振链**、**紧密轨道卫星**、**长期摄动**时，
仅凭开普勒根数判断「系统稳不稳定」是危险的——需要 N-body 数值积分来验证。

dreamulator 用 REBOUND（Rein & Liu 2012）做这件事。脚本 `scripts/rebound_nbody.py` 是
最小骨架，后续会扩展出自旋-轨道耦合（Cassini 态）与百年~千年进动周期标定。

## 工具：`scripts/rebound_nbody.py`

### 怎么跑

```bash
uv run python scripts/rebound_nbody.py
```

依赖在 `pyproject.toml` 的 `dev` extra（`rebound>=4.0`），`uv sync --all-extras` 安装，
**不是**默认运行时依赖。

### 单位

REBOUND 默认单位：`G=1`，长度 AU、质量 M☉、时间 yr。质量换算 `M⊕ = 3.003×10⁻⁶ M☉`
（脚本里的 `MEARTH_MSUN` 常量）。

### 怎么改成别的世界

改 `build_nacrea_system()`：

1. `sim.add(m=...)` 加恒星（质量 M☉）。
2. 行星 `sim.add(m=..., a=..., e=...)` 绕恒星（`primary` 省略 = 恒星）。
3. 卫星 `sim.add(m=..., a=..., e=..., inc=..., primary=sim.particles[母星索引])` 绕行星。
   `inc` 用弧度。
4. `sim.integrate(t_end)` 改积分时长（短时验证稳定、长时标进动）。

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

### 希尔球稳定上限（顺行卫星更脆弱）

卫星绕行星的稳定性上限用希尔半径 $r_H = a_p (m_p / 3 M_\star)^{1/3}$ 衡量。数值研究
（Hamilton & Burns 1991）给出的经验上限：**顺行 ~0.4 r_H、逆行 ~0.7 r_H**。Nacrea 的
Vigil 在 **0.48 r_H**，已越过顺行稳定上限——它本来就卡在悬崖边，共振一扰动就逃逸。
这也是为什么 `stellar.yaml` 里 Vigil 要「顺带验 0.48 r_H」。

## 设计其他世界的流程

1. **搭系统**：恒星 + 行星（含共振链）+ 卫星，写进 `build_*_system()`。
2. **短时积分**（~10 yr，覆盖内层天体数百圈）：看偏心率是否暴涨、卫星是否逃逸 → 判断
   「初始条件是否落在稳定区」。
3. **长时积分**（~kyr，后台跑）：标定进动周期（近日点进动、交点进动、气候岁差拍频）。
4. **迭代**：不稳定就调共振角（扫两个 2:1 角找同时天平动）、调半长轴（离开稳定边缘）、
   或调偏心率。

**判断标准**：短时积分内偏心率稳定（不单调暴涨）、无天体逃逸（e 始终 < 1），即视为
「当前初始条件可行」。

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
