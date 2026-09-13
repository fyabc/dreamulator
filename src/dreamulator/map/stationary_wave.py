"""④ 定常波响应：线性定常正压涡度求解器（roadmap ④，副高经度结构）。

物理链（proposal §2「定常波响应」节；Sardeshmukh & Hoskins 1988 JAS 45:1228；
Rodwell & Hoskins 2001 J. Climate 14:3192）：

    月度 P → 柱潜热 Q = L_v·P_rate                       （加热 = 引擎自身降水场）
    → ω_mid = −Q·g/(Δp_heat·c_p·σ_T)                     （定常热成平衡；σ_T 静力稳定度）
    → D = −ω_mid/Δp_div                                   （质量连续，三角 ω 廓线）
    → S = −ζ̄ₐ D − β_e v_χ                                （RWS：拉伸 + 辐散风平流）
    → ū ∂x ζ' + β_e v' = S − r ζ'                         （定常线性正压涡度方程）
    → ΔSLP_wave = ρ_s·f·ψ'                                （等价正压投影，S&H 1996）

机制：加热区高层辐散外流穿越绝对涡度梯度 → Rossby 波源 → 定常波列；源西侧
反气旋脊（= 下沉、副高增强，撒哈拉/中东沙漠的维持机制），下游气旋异常。
给引擎补上纬向对称框架缺失的**经度结构**维度。

原型（2026-09-13）验证的两条硬约束：

1. **∮D dA = 0**（闭球面质量守恒）——D 必须扣面积加权均值，否则 ∇²χ = D 的
   近零模发散；
2. **RHS 的 k=0（纬向平均）分量必须剔除**——纬向对称响应归 Hadley 环流管
   （引擎已有纬向对称下沉），定常正压模式对 k=0 只有 r∇² 阻尼、被 1/(rμ²)
   放大失真。

设计约定：

- 纯函数模块，无 IO / RNG（stellar_physics 同款纪律），可独立单测。
- 求解在自带纬向网格（2°×2°）：定常波算子（β_e∂λ + ū∂λ∇²）在纬向网格天然
  结构化，CVT 图网格上 ∂λ 无良定义、极地病态；ψ' 是平滑大尺度场，双线性
  插值回 cell 的损失可忽略。
- 基本态 (ū,v̄)(φ, λ, month) = 引擎逐月地表风 + **局域**热成风修正（引擎
  T 场派生，零新参数）。zonal 平均基本态被首跑证伪：TEJ 型热带东风被抹平
  → 季风源落进临界线 → R&H 响应消失/翻号（详 upper_level_basic_state）。
- 阻尼 r⁻¹ = 10 d（文献惯例；引擎水分 τ = 9 d 同量级，非调参项）。
- 高纬 |φ| ≥ 80° Dirichlet 墙（ψ'=0；极地响应不是本机制目标）。
- 赤道 f→0：ΔSLP = ρfψ' 自然退化（Gill 赤道动力学 = v2+ 范围）。

v1 范围限定：海洋链（Stommel/SST）不随 two-pass 重跑（洋流消费 pass-1 风场）；
T↔P 无耦合（与引擎既有 single-pass 近似一致）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.linalg import SuperLU, splu

from dreamulator.engine.climate_physics import moist_lapse_rate

# ── 物理常数（SI；与引擎各处字面量一致） ──
R_DRY = 287.0  # 干空气气体常数 J/(kg·K)
C_P_AIR = 1004.0  # 干空气定压比热 J/(kg·K)
GRAV = 9.81  # m/s²
L_V = 2.5e6  # 水汽化潜热 J/kg（climate_simulator 同值）
PRESSURE_SCALE_HEIGHT_M = 8500.0  # 与 monsoon_circulation 同约定

# ── 求解器结构常数（非物理调参项，各有文献/推导出处） ──
GRID_DEG = 2.0  # 纬向网格分辨率
WALL_LAT_DEG = 80.0  # Dirichlet 墙纬度
P_TOP_RATIO = 0.25  # 热成风积分顶层 p_top = 0.25·p_s（辐散层顶）
DP_HEAT_FRACTION = 0.7  # 加热层质量深度份额（深对流加热整层对流层）
DP_DIV_FRACTION = 0.3  # 高层辐散层质量深度份额（三角 ω 廓线上支）
F_CLIP_LAT_DEG = 7.5  # 热成风 f 正则化下限（赤道防奇异）
UBAR_CAP_MS = 80.0  # 基本态数值护栏（≈2× 急流极值）
# 基本态行星尺度平滑 σ（度）：真实月均 200hPa 流场是行星尺度平滑场；地表 T
# 代理在 <1000 km 尺度的梯度对层均热成风是噪声（2D 首跑实锤：bin 噪声 +
# 中尺度 T 梯度 → ū 摆动 ±40-80 m/s → ∂xζ̄ₐ 病态 → ψ 放大到 960e6）。
BASIC_SMOOTH_DEG = 10.0
# 热成风修正帽（m/s）：地表-T × ln(p_s/p_top) 代理的有效域——真实高层风
# 非极夜急流上限 ~30-35 m/s；|corr| 超过即代理失效（2D 首跑实锤：0E 扇区
# 10N corr −72 m/s，真实 AEJ 只有 −10~−15）。
CORR_CAP_MS = 30.0
# 热成风修正的高纬 taper：|φ| ≤ 45° 全量、≥ 60° 归零。物理依据：极区/副极
# 高层流由极涡/平流层动力学主导，不是地表经向温度梯度的热成风平衡；EBM 冰
# 盖边缘的 T 梯度外推 × ln(p_s/p_top)/f 在极区给出 +67 m/s 级垃圾急流 →
# 高纬近共振（首跑实锤：max|ψ'| 91e6 m²/s @72N，ΔSLP 174 hPa）。
TAPER_FULL_LAT_DEG = 45.0
TAPER_ZERO_LAT_DEG = 60.0
# ΔSLP 投影有效域帽（hPa）：NCEP 定常涡 SLP 距平气候学上界（冬季阿留申低压
# ~−8 hPa、副高 +2~5）；同时是线性理论有效域护栏——等价正压投影在高纬把高层
# 异常全额投到地面（真实斜压结构地面只有 1/3-1/5，首跑 |φ|~48 处 ΔSLP 30-50
# hPa 即此失真）。超出部分裁剪，裁剪占比进 debug 监控。
DP_CAP_HPA = 8.0
# 赤道消费掩膜（v1 范围声明的执行）：|φ| ≤ 10° 零消费、≥ 20° 全量。
# 依据：① 赤道动力学是 Gill/Kelvin 体制（v1 声明范围外）；② ITCZ 季节迁移
# 带 ±10-15°，其辐合降水不得被范围外机制扰动；③ ΔSLP 异常在边界层风里被
# 1/f 放大——首次全量构建实锤：±10° 带 ΔP −858/−1110、P R² 0.354→0.079，
# 而副热带（20-40°）仅 −148~−287 且澳洲/卡拉哈里/波斯湾/萨赫勒方向正确。
EQ_MASK_ZERO_DEG = 10.0
EQ_MASK_FULL_DEG = 20.0
# 临界层阻尼标度（m/s）：线性定常响应在 ū→0 的临界纬按 1/(ū−c) 发散，
# r=10d 的线性阻尼压不住（首跑实锤：夏季中纬 ū +2~8 m/s → max|ψ'| 64e6
# m²/s @54N，共振腔模带偏整个副热带图案）。真实临界层吸收波活动（非线性
# /边界层阻尼在几 m/s 尺度接管）——线性模式的文献惯例是临界纬附近附加
# Rayleigh 阻尼：r_eff = r·(1 + (U_CRIT/|ū|)²)，急流区（|ū|≥15）扰动 <10%。
U_CRIT_MS = 5.0
R_ENHANCE_CAP = 100.0  # r_eff/r 数值上限（ū→0 时）
SIGMA_T_FLOOR = 1e-4  # K/Pa；σ_T ≤ 0 = 超干绝热（非物理），钳制
T0_K = 273.15


@dataclass(frozen=True)
class WaveGrid:
    """自带纬向求解网格（等距圆柱，经度周期，高纬 Dirichlet 墙）。"""

    nlat: int
    nlon: int
    lat_deg: np.ndarray  # (nlat,)
    lon_deg: np.ndarray  # (nlon,)
    dlat: float  # rad
    dlon: float  # rad
    cosf: np.ndarray  # (nlat,)
    sinf: np.ndarray  # (nlat,)
    wall: np.ndarray  # (nlat,) bool — Dirichlet 行


def make_wave_grid(deg: float = GRID_DEG) -> WaveGrid:
    """等距圆柱网格：lat −90..90、lon 0..360−deg（经度周期）。"""
    nlat = int(round(180.0 / deg)) + 1
    nlon = int(round(360.0 / deg))
    lat = np.linspace(-90.0, 90.0, nlat)
    lon = np.arange(nlon) * deg
    latr = np.radians(lat)
    return WaveGrid(
        nlat=nlat,
        nlon=nlon,
        lat_deg=lat,
        lon_deg=lon,
        dlat=np.deg2rad(deg),
        dlon=np.deg2rad(deg),
        cosf=np.cos(latr),
        sinf=np.sin(latr),
        wall=np.abs(lat) >= WALL_LAT_DEG,
    )


def _interior_rows(grid: WaveGrid) -> np.ndarray:
    return np.flatnonzero(~grid.wall)


def _smooth_planetary(field: np.ndarray, grid: WaveGrid) -> np.ndarray:
    """高斯平滑到行星尺度（σ = BASIC_SMOOTH_DEG；经度周期、纬度反射）。"""
    sigma_bins = BASIC_SMOOTH_DEG / (grid.lat_deg[1] - grid.lat_deg[0])
    s = gaussian_filter1d(field, sigma_bins, axis=1, mode="wrap")
    return np.asarray(gaussian_filter1d(s, sigma_bins, axis=0, mode="nearest"))


def _laplacian_stencil(grid: WaveGrid, radius_m: float) -> tuple[np.ndarray, ...]:
    """Laplacian 五点模板逐纬系数 (a_p, a_m, a_c, a_lon)；墙行为 0。

    ∇²ψ = (1/(a²c))∂φ(c∂φψ) + (1/(a²c²))∂λλψ 的中心差分。
    """
    nlat = grid.nlat
    i = np.arange(nlat)
    c = grid.cosf
    c_p = np.roll(c, -1)
    c_m = np.roll(c, 1)
    ok = (~grid.wall) & (i > 0) & (i < nlat - 1)
    safe = np.where(ok, c, 1.0)
    denom_phi = radius_m**2 * safe * grid.dlat**2
    denom_lon = radius_m**2 * safe**2 * grid.dlon**2
    a_p = np.where(ok, c_p / denom_phi, 0.0)
    a_m = np.where(ok, c_m / denom_phi, 0.0)
    a_c = np.where(ok, -(c_p + c_m) / denom_phi, 0.0)
    a_lon = np.where(ok, 1.0 / denom_lon, 0.0)
    return a_p, a_m, a_c, a_lon


def _dirichlet_rows(grid: WaveGrid, inner: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """墙行的单位阵三元组（rows, cols, vals）。"""
    rest = np.setdiff1d(np.arange(grid.nlat), inner)
    j = np.arange(grid.nlon)
    idx = (rest[:, None] * grid.nlon + j[None, :]).ravel()
    return idx, idx, np.ones(idx.size)


def assemble_laplacian(grid: WaveGrid, radius_m: float) -> csr_matrix:
    """∇² 稀疏矩阵（墙行 = 单位阵 → ψ=0 Dirichlet）。"""
    n = grid.nlat * grid.nlon
    a_p, a_m, a_c, a_lon = _laplacian_stencil(grid, radius_m)
    inner = _interior_rows(grid)
    j = np.arange(grid.nlon)[None, :]
    k = inner[:, None] * grid.nlon + j

    rows_l: list[np.ndarray] = []
    cols_l: list[np.ndarray] = []
    vals_l: list[np.ndarray] = []

    def _add(di: int, dj: int, vv: np.ndarray) -> None:
        rows_l.append(k.ravel())
        cols_l.append(((inner + di)[:, None] * grid.nlon + ((j + dj) % grid.nlon)).ravel())
        vals_l.append(np.broadcast_to(vv[:, None], k.shape).ravel())

    _add(0, 0, a_c[inner] - 2.0 * a_lon[inner])
    _add(1, 0, a_p[inner])
    _add(-1, 0, a_m[inner])
    _add(0, 1, a_lon[inner])
    _add(0, -1, a_lon[inner])
    wr, wc, wv = _dirichlet_rows(grid, inner)
    rows_l.append(wr)
    cols_l.append(wc)
    vals_l.append(wv)

    coo = coo_matrix(
        (np.concatenate(vals_l), (np.concatenate(rows_l), np.concatenate(cols_l))), shape=(n, n)
    )
    return csr_matrix(coo)


def basic_state_vorticity(
    ubar: np.ndarray, vbar: np.ndarray, grid: WaveGrid, omega_planet: float, radius_m: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2D 基本态绝对涡度 ζ̄ₐ(φ,λ) 及其梯度 (∂xζ̄ₐ, ∂yζ̄ₐ)。

    ζ̄ = (1/(a cosφ))·[∂λv̄ − ∂φ(ū cosφ)]；ζ̄ₐ = f + ζ̄。
    v̄=0 且 ū 仅纬向时严格退化为 zonal 形式 −ū_φ/a + ū tanφ/a。
    """
    c_safe = np.where(grid.cosf > 0.05, grid.cosf, 1.0)[:, None]
    dv_dl = np.gradient(vbar, grid.dlon, axis=1)
    duc_dphi = np.gradient(ubar * grid.cosf[:, None], grid.dlat, axis=0)
    zbar = (dv_dl - duc_dphi) / (radius_m * c_safe)
    f2d = np.broadcast_to((2.0 * omega_planet * grid.sinf)[:, None], ubar.shape)
    zeta_a = f2d + zbar
    dzdx = np.gradient(zeta_a, grid.dlon, axis=1) / (radius_m * c_safe)
    dzdy = np.gradient(zeta_a, grid.dlat, axis=0) / radius_m
    bad = grid.cosf[:, None] <= 0.05
    zeta_a = np.where(bad, f2d, zeta_a)
    dzdx = np.where(bad, 0.0, dzdx)
    dzdy = np.where(bad, 0.0, dzdy)
    return zeta_a, dzdx, dzdy


def assemble_wave_operator(
    ubar: np.ndarray,
    vbar: np.ndarray,
    r_inv_s: float,
    grid: WaveGrid,
    omega_planet: float,
    radius_m: float,
) -> csr_matrix:
    """定常线性化正压算子 L（2D 基本态；v̄=0 时严格退化为 zonal 形式）：

    L ψ' = ū ∂x(∇²ψ') + v̄ ∂y(∇²ψ') + ∂xζ̄ₐ·∂yψ' + ∂yζ̄ₐ·∂xψ' + r_eff ∇²ψ'

    ∂x = (1/(a cosφ))∂λ、∂y = (1/a)∂φ；u' = −∂yψ'、v' = ∂xψ'。
    r_eff = r·(1 + (U_C/|v̄₂ᴰ|)²)（临界层附加阻尼，见常数注释）。
    """
    n = grid.nlat * grid.nlon
    a_p, a_m, a_c, a_lon = _laplacian_stencil(grid, radius_m)
    _, dzdx, dzdy = basic_state_vorticity(ubar, vbar, grid, omega_planet, radius_m)
    inner = _interior_rows(grid)
    j = np.arange(grid.nlon)[None, :]
    k = inner[:, None] * grid.nlon + j
    c_i = np.maximum(grid.cosf[inner], 1e-6)[:, None]  # (ni, 1)
    u_in = ubar[inner]  # (ni, nlon)
    v_in = vbar[inner]
    speed = np.sqrt(u_in**2 + v_in**2)
    adv_x = u_in / (radius_m * c_i * 2.0 * grid.dlon)  # ū ∂x 中心差分系数
    adv_y = v_in / (radius_m * 2.0 * grid.dlat)  # v̄ ∂y
    beta_c = dzdy[inner] / (2.0 * radius_m * c_i * grid.dlon)  # ∂yζ̄ₐ·∂xψ'
    cx_c = dzdx[inner] / (2.0 * radius_m * grid.dlat)  # −∂xζ̄ₐ·u' = +∂xζ̄ₐ·∂yψ'
    r_eff = r_inv_s * np.minimum(1.0 + (U_CRIT_MS / np.maximum(speed, 0.1)) ** 2, R_ENHANCE_CAP)

    rows_l: list[np.ndarray] = []
    cols_l: list[np.ndarray] = []
    vals_l: list[np.ndarray] = []

    def _add(di: int, dj: int, vv: np.ndarray) -> None:
        rows_l.append(k.ravel())
        cols_l.append(((inner + di)[:, None] * grid.nlon + ((j + dj) % grid.nlon)).ravel())
        vals_l.append(np.broadcast_to(vv, k.shape).ravel())

    lap_c = (a_c - 2.0 * a_lon)[inner][:, None]  # (ni, 1)
    lap = (
        (0, 0, lap_c),
        (1, 0, a_p[inner][:, None]),
        (-1, 0, a_m[inner][:, None]),
        (0, 1, a_lon[inner][:, None]),
        (0, -1, a_lon[inner][:, None]),
    )
    for di, dj, vv in lap:
        _add(di, dj, r_eff * vv)  # r_eff ∇²ψ'
        _add(di, dj + 1, adv_x * vv)  # ū ∂x(∇²ψ') 的 j+1 半支
        _add(di, dj - 1, -adv_x * vv)  # j−1 半支
        _add(di + 1, dj, adv_y * vv)  # v̄ ∂y(∇²ψ') 的 i+1 半支
        _add(di - 1, dj, -adv_y * vv)  # i−1 半支
    _add(0, 1, beta_c)  # ∂yζ̄ₐ·∂xψ'
    _add(0, -1, -beta_c)
    _add(1, 0, cx_c)  # ∂xζ̄ₐ·∂yψ'
    _add(-1, 0, -cx_c)
    wr, wc, wv = _dirichlet_rows(grid, inner)
    rows_l.append(wr)
    cols_l.append(wc)
    vals_l.append(wv)

    coo = coo_matrix(
        (np.concatenate(vals_l), (np.concatenate(rows_l), np.concatenate(cols_l))), shape=(n, n)
    )
    return csr_matrix(coo)


def solve_wave_month(
    div_grid: np.ndarray,
    ubar: np.ndarray,
    vbar: np.ndarray,
    lap_lu: SuperLU,
    grid: WaveGrid,
    omega_planet: float,
    radius_m: float,
    r_inv_s: float,
) -> np.ndarray:
    """单月定常线性解 → ψ'（nlat, nlon）。

    步骤：① ∮D dA = 0 扣均值；② ∇²χ = D 反解辐散风势函数；③ 2D RWS
    S = −ζ̄ₐD − u_χ·∂xζ̄ₐ − v_χ·∂yζ̄ₐ；④ k=0（纬向平均）剔除——2D 基本态下
    模态不再严格解耦，此投影是近似（去掉正压模式无法承载的 Hadley 型强迫
    分量），解的行均由探针监控；⑤ L ψ' = S 稀疏直解。
    """
    nlon = grid.nlon
    w = grid.cosf
    # ① 全球面积均值扣除（闭球面质量守恒；见模块 docstring 硬约束 1）
    d = div_grid - (div_grid * w[:, None]).sum() / (w.sum() * nlon)
    d = np.where(grid.wall[:, None], 0.0, d)
    # ② χ 反解（lap_lu = splu(assemble_laplacian(...))）
    chi = np.asarray(lap_lu.solve(d.ravel())).reshape(grid.nlat, nlon)
    c_safe = np.where(grid.cosf > 0.05, grid.cosf, 1.0)[:, None]
    u_chi = np.gradient(chi, grid.dlon, axis=1) / (radius_m * c_safe)
    v_chi = np.gradient(chi, grid.dlat, axis=0) / radius_m
    # ③ 2D RWS
    zeta_a, dzdx, dzdy = basic_state_vorticity(ubar, vbar, grid, omega_planet, radius_m)
    rhs = -zeta_a * d - u_chi * dzdx - v_chi * dzdy
    # ④ k=0（纬向平均）剔除（见模块 docstring 硬约束 2；2D 下为近似投影）
    rhs = rhs - rhs.mean(axis=1, keepdims=True)
    rhs = np.where(grid.wall[:, None], 0.0, rhs)
    # ⑤ 算子求解
    op = assemble_wave_operator(ubar, vbar, r_inv_s, grid, omega_planet, radius_m)
    lu = splu(op)
    psi = np.asarray(lu.solve(rhs.ravel())).reshape(grid.nlat, nlon)
    # ⑥ 解出行均投影：消费只取 eddy 分量（纬向平均归 Hadley/既有纬向气压场）。
    # 2D 基本态下算子耦合 k 模态，RHS 行均剔除不再是精确投影——出口再投影
    # 一次，k=0 无论怎么被泵都出不了口（2D 首跑实锤：行均 832e6 m²/s）。
    return np.asarray(psi - psi.mean(axis=1, keepdims=True))


def precip_to_divergence(
    p_rate_kg_m2_s: np.ndarray,
    t_annual_mean_c: np.ndarray,
    elevation_m: np.ndarray,
    surface_pressure_pa: float,
) -> np.ndarray:
    """降水 → 高层辐散 D 闭合（全派生量，无自由参数）。

    Q_col = L_v·P_rate；ω_mid = −Q·g/(Δp_heat·c_p·σ_T)（定常热成平衡，
    σ_T = (RT/p)(1/c_p − Γ/g) 从年均 T + 湿绝热递减率派生）；
    D = −ω_mid/Δp_div（三角 ω 廓线 → 上支辐散层）。

    Args:
        p_rate_kg_m2_s: 降水率 (n, 12) 或 (n,)，1 mm/month 已换算 kg/m²/s。
        t_annual_mean_c: 年均表面温度 °C (n,)。
        elevation_m: 海拔 (n,)。
        surface_pressure_pa: 海平面气压 Pa。

    Returns:
        D (与 p_rate 同形)，单位 1/s。
    """
    p_s = surface_pressure_pa * np.exp(-elevation_m / PRESSURE_SCALE_HEIGHT_M)  # (n,)
    gamma_kkm = np.clip(moist_lapse_rate(t_annual_mean_c), 4.5, 6.5)  # K/km（引擎同约定）
    gamma_km = gamma_kkm / 1000.0  # K/m
    t_k = t_annual_mean_c + T0_K
    z_mid = (R_DRY * t_k / GRAV) * np.log(2.0)  # p_mid = 0.5·p_s 的高度（静力学）
    t_mid = t_k - gamma_km * z_mid
    p_mid = 0.5 * p_s
    sigma_t = (R_DRY * t_mid / p_mid) * (1.0 / C_P_AIR - gamma_km / GRAV)
    sigma_t = np.maximum(sigma_t, SIGMA_T_FLOOR)
    p_arr = np.asarray(p_rate_kg_m2_s)
    single = p_arr.ndim == 1
    p_in = p_arr[:, None] if single else p_arr  # (n, M)
    q_col = L_V * p_in  # W/m²
    denom = DP_HEAT_FRACTION * DP_DIV_FRACTION * (p_s**2)[:, None] * C_P_AIR * sigma_t[:, None]
    out = q_col * GRAV / denom
    return np.asarray(out[:, 0] if single else out)


def cell_grid_indices(
    cell_lat_deg: np.ndarray, cell_lon_deg: np.ndarray, grid: WaveGrid
) -> tuple[np.ndarray, np.ndarray]:
    """cell → 最近网格索引（binning 用）。"""
    step = grid.lat_deg[1] - grid.lat_deg[0]
    i = np.rint((cell_lat_deg - grid.lat_deg[0]) / step).astype(int).clip(0, grid.nlat - 1)
    j = (np.rint((cell_lon_deg - grid.lon_deg[0]) / step).astype(int)) % grid.nlon
    return i, j


def _fill_empty_bins(field: np.ndarray, filled: np.ndarray) -> np.ndarray:
    """空 bin 用已填邻居的迭代 Jacobi 均值补齐（经度周期）。

    状态场（T/u/v）的空 bin 回退 0 是毒值（0 °C 洞破坏梯度 → 基本态垃圾）；
    D 强迫场不适用本函数（空 bin = 无降水信息，0 是物理中性值）。
    """
    out = field.copy()
    m = filled.copy()
    for _ in range(64):
        if m.all():
            break
        nb_sum = np.zeros_like(out)
        nb_cnt = np.zeros(out.shape, dtype=np.int32)
        for axis, shift in ((0, 1), (0, -1), (1, 1), (1, -1)):
            ms = np.roll(m, shift, axis=axis).astype(np.int32)
            nb_sum += np.roll(out, shift, axis=axis) * ms
            nb_cnt += ms
        fill = (~m) & (nb_cnt > 0)
        if not fill.any():
            break
        out[fill] = nb_sum[fill] / nb_cnt[fill]
        m = m | fill
    return out


def bin_to_grid(
    values: np.ndarray,
    weights: np.ndarray,
    ii: np.ndarray,
    jj: np.ndarray,
    grid: WaveGrid,
    fill_empty: bool = False,
) -> np.ndarray:
    """cell 场 → 网格（面积加权 bin 均值）。

    空 bin 默认 0（D 强迫场的物理中性值）；fill_empty=True 时用邻居迭代
    补齐（T/u/v 等状态场——0 回退会产生毒梯度）。
    """
    idx = ii * grid.nlon + jj
    num = np.bincount(idx, weights=values * weights, minlength=grid.nlat * grid.nlon)
    den = np.bincount(idx, weights=weights, minlength=grid.nlat * grid.nlon)
    out = np.divide(num, den, out=np.zeros_like(num), where=den > 1e-12)
    out = out.reshape(grid.nlat, grid.nlon)
    if fill_empty:
        out = _fill_empty_bins(out, (den > 1e-12).reshape(grid.nlat, grid.nlon))
    return out


def zonal_mean_to_lat(
    values: np.ndarray, weights: np.ndarray, ii: np.ndarray, grid: WaveGrid
) -> np.ndarray:
    """cell 场 → 纬向均值 (nlat,)（面积加权）。"""
    num = np.bincount(ii, weights=values * weights, minlength=grid.nlat)
    den = np.bincount(ii, weights=weights, minlength=grid.nlat)
    return np.divide(num, den, out=np.zeros_like(num), where=den > 1e-12)


def sample_grid_to_cells(
    field: np.ndarray, cell_lat_deg: np.ndarray, cell_lon_deg: np.ndarray, grid: WaveGrid
) -> np.ndarray:
    """网格场 → cell（双线性；经度周期，纬度钳制）。field (nlat, nlon)。"""
    step = grid.lat_deg[1] - grid.lat_deg[0]
    y = (cell_lat_deg - grid.lat_deg[0]) / step
    x = (cell_lon_deg - grid.lon_deg[0]) / step
    i0 = np.floor(y).astype(int).clip(0, grid.nlat - 2)
    j0 = np.floor(x).astype(int)
    fy = np.clip(y - i0, 0.0, 1.0)
    fx = x - np.floor(x)
    j0 = j0 % grid.nlon
    j1 = (j0 + 1) % grid.nlon
    return np.asarray(
        (1.0 - fy) * (1.0 - fx) * field[i0, j0]
        + (1.0 - fy) * fx * field[i0, j1]
        + fy * (1.0 - fx) * field[i0 + 1, j0]
        + fy * fx * field[i0 + 1, j1]
    )


def upper_level_basic_state(
    u_sfc_grid: np.ndarray,
    v_sfc_grid: np.ndarray,
    t_surf_grid_c: np.ndarray,
    grid: WaveGrid,
    omega_planet: float,
    radius_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """2D 基本态 (ū,v̄)(φ,λ) = 地表风 + **局域**热成风修正（p_s → 0.25·p_s）。

    ∂u/∂lnp = (R/f)·∂T/∂y → corr_u = −(R ln(1/P_TOP)/f)·∂T/∂y

    **v̄ 不做热成风修正**（只用 bin 后的地表 v）：热成风关系适用准地转的
    纬向分量；经圈环流支（Hadley/季风翻转）是梯度流非地转——季风大陆的
    强局域 ∂T/∂x（海陆对比 ~15 K/1000 km）会给 corr_v ~ +80 m/s 垃圾值
    （2D 首跑实锤：ΔSLP capped 占比 19%→81%）。真实高层 v̄ ~ ±2-5 m/s，
    地表 v 的正压延伸是保守近似。

    为什么 u 修正必须 2D（zonal 平均首跑证伪链）：R&H 机制要求季风源嵌在
    热带东风（TEJ）里——局域 ∂T/∂y > 0（夏季大陆加热峰在源以北）给出东风
    修正，而纬向平均把 TEJ 抹成 ū ≈ 0 → 源区落进临界线被 r_eff 钉死 →
    撒哈拉响应翻负。f 正则化 |f| ≥ f(7.5°)（赤道防奇异，0 取 + 号）；高纬
    taper 45→60°（极区高层流非地表热成风平衡）。
    """
    if omega_planet < 1e-12:  # 无自转：无热成风，基本态 = 地表风
        return u_sfc_grid.copy(), v_sfc_grid.copy()
    # 行星尺度平滑（BASIC_SMOOTH_DEG 常数的物理依据见其上注释）：bin 噪声与
    # 中尺度 T 梯度对层均热成风是噪声，且会经 ∂xζ̄ₐ 项病态化算子。
    u_s = _smooth_planetary(u_sfc_grid, grid)
    v_s = _smooth_planetary(v_sfc_grid, grid)
    t_k = _smooth_planetary(t_surf_grid_c + T0_K, grid)
    f = np.broadcast_to((2.0 * omega_planet * grid.sinf)[:, None], t_k.shape)
    f_min = 2.0 * omega_planet * np.sin(np.deg2rad(F_CLIP_LAT_DEG))
    # f=0（赤道行）符号取 +1 — np.sign 会给 0 → 除零。
    f_reg = np.where(f >= 0.0, 1.0, -1.0) * np.maximum(np.abs(f), f_min)
    dtdy = np.gradient(t_k, grid.dlat, axis=0) / radius_m
    taper = np.clip(
        (TAPER_ZERO_LAT_DEG - np.abs(grid.lat_deg)) / (TAPER_ZERO_LAT_DEG - TAPER_FULL_LAT_DEG),
        0.0,
        1.0,
    )[:, None]
    coef = R_DRY * np.log(1.0 / P_TOP_RATIO) * taper / f_reg
    corr = np.clip(-coef * dtdy, -CORR_CAP_MS, CORR_CAP_MS)  # 代理有效域帽
    ubar = np.clip(u_s + corr, -UBAR_CAP_MS, UBAR_CAP_MS)
    vbar = np.clip(v_s, -UBAR_CAP_MS, UBAR_CAP_MS)
    ubar = np.where(grid.wall[:, None], 0.0, ubar)
    vbar = np.where(grid.wall[:, None], 0.0, vbar)
    return np.asarray(ubar), np.asarray(vbar)


@dataclass(frozen=True)
class WaveSolution:
    """④ 求解结果（供 stage-3 two-pass 集成与诊断脚本消费）。"""

    dp_hpa: np.ndarray  # (n, 12) ΔSLP_wave = ρ_s·f·ψ'（hPa，已含有效域帽，未含松弛）
    psi: np.ndarray  # (12, nlat, nlon) 流函数 m²/s
    ubar: np.ndarray  # (12, nlat, nlon) 基本态纬向风 m/s
    vbar: np.ndarray  # (12, nlat, nlon) 基本态经圈风 m/s
    div_grid: np.ndarray  # (12, nlat, nlon) 辐散强迫 1/s


def compute_slp_wave_anomaly(
    p_monthly_mm: np.ndarray,
    t_monthly_c: np.ndarray,
    elevation_m: np.ndarray,
    cell_lat_deg: np.ndarray,
    cell_lon_deg: np.ndarray,
    cell_area_km2: np.ndarray,
    wind_east_monthly: np.ndarray,
    wind_north_monthly: np.ndarray,
    *,
    surface_pressure_hpa: float,
    rotation_period_days: float,
    radius_km: float,
    orbital_period_days: float,
    damping_days: float = 10.0,
) -> WaveSolution:
    """顶层入口：引擎月度降水/温度/风场 → ΔSLP_wave（逐 cell 逐月，hPa）。

    Args:
        p_monthly_mm: (n, 12) 逐月降水 mm/month（two-pass 的 pass-1 产物）。
        t_monthly_c: (n, 12) 逐月表面温度 °C。
        elevation_m / cell_lat_deg / cell_lon_deg / cell_area_km2: (n,) 网格几何。
        wind_east_monthly / wind_north_monthly: (n, 12) 逐月地表风分量 m/s
            （pass-1 wind_monthly 的切向分解；2D 基本态的地表项，含季风
            异常的经度结构）。
        surface_pressure_hpa / rotation_period_days / radius_km /
        orbital_period_days: 行星参数（config）。
        damping_days: 线性阻尼时间尺度（文献惯例 10 d）。
    """
    grid = make_wave_grid()
    radius_m = radius_km * 1000.0
    omega_planet = 2.0 * np.pi / (rotation_period_days * 86400.0)
    n, n_months = p_monthly_mm.shape
    month_s = orbital_period_days * 86400.0 / n_months

    # ① 降水 → 辐散（逐 cell 闭合 → bin 到网格）
    p_rate = p_monthly_mm / month_s  # 1 mm = 1 kg/m²
    d_cells = precip_to_divergence(
        p_rate, t_monthly_c.mean(axis=1), elevation_m, surface_pressure_hpa * 100.0
    )
    ii, jj = cell_grid_indices(cell_lat_deg, cell_lon_deg, grid)
    div_grid = np.stack(
        [bin_to_grid(d_cells[:, m], cell_area_km2, ii, jj, grid) for m in range(n_months)]
    )

    # ② 逐月 2D 基本态：地表风 bin + 局域热成风修正
    lap_lu = splu(assemble_laplacian(grid, radius_m))
    r_inv_s = 1.0 / (damping_days * 86400.0)
    ubars = np.empty((n_months, grid.nlat, grid.nlon))
    vbars = np.empty((n_months, grid.nlat, grid.nlon))
    psis = []
    for m in range(n_months):
        u_g = bin_to_grid(wind_east_monthly[:, m], cell_area_km2, ii, jj, grid, True)
        v_g = bin_to_grid(wind_north_monthly[:, m], cell_area_km2, ii, jj, grid, True)
        t_g = bin_to_grid(t_monthly_c[:, m], cell_area_km2, ii, jj, grid, True)
        ubar_m, vbar_m = upper_level_basic_state(u_g, v_g, t_g, grid, omega_planet, radius_m)
        ubars[m] = ubar_m
        vbars[m] = vbar_m
        # ③ 求解
        psis.append(
            solve_wave_month(
                div_grid[m], ubar_m, vbar_m, lap_lu, grid, omega_planet, radius_m, r_inv_s
            )
        )
    psi = np.stack(psis)

    # ④ ψ' → ΔSLP_wave = ρ_s·f·ψ'（hPa；随 cell 密度自然含海拔衰减，f→0 赤道退化）
    p_s = surface_pressure_hpa * 100.0 * np.exp(-elevation_m / PRESSURE_SCALE_HEIGHT_M)
    t_k = t_monthly_c.mean(axis=1) + T0_K
    rho_s = p_s / (R_DRY * t_k)
    f_cell = 2.0 * omega_planet * np.sin(np.radians(cell_lat_deg))
    dp_hpa = np.empty((n, n_months), dtype=np.float64)
    for m in range(n_months):
        psi_c = sample_grid_to_cells(psi[m], cell_lat_deg, cell_lon_deg, grid)
        dp_hpa[:, m] = rho_s * f_cell * psi_c / 100.0
    # 赤道消费掩膜（EQ_MASK 常数的物理依据见其上注释）：v1 范围外体制
    # （Gill/ITCZ）不得被扰动。
    eq_taper = np.clip(
        (np.abs(cell_lat_deg) - EQ_MASK_ZERO_DEG) / (EQ_MASK_FULL_DEG - EQ_MASK_ZERO_DEG),
        0.0,
        1.0,
    )
    dp_hpa = dp_hpa * eq_taper[:, None]
    # 有效域帽（DP_CAP_HPA 的物理依据见常数注释）：等价正压投影在高纬高估
    # 地面表现（真实斜压结构 1/3-1/5），线性理论在 |ΔSLP| 超过气候学定常涡
    # 幅度处失效——裁剪到有效域内，裁剪占比由集成侧 debug 监控。
    dp_hpa = np.asarray(np.clip(dp_hpa, -DP_CAP_HPA, DP_CAP_HPA))
    return WaveSolution(dp_hpa=dp_hpa, psi=psi, ubar=ubars, vbar=vbars, div_grid=div_grid)
