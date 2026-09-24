"""④ v2 定常波响应：两层 Gill 型响应（Lee-Wang-Mapes 两模态模型）。

物理链（proposal §2「定常波响应」v2；Lee, Wang & Mapes 2009, J. Climate 22:272,
doi:10.1175/2008JCLI2303.1；Gill 1980 QJRMS 106:447）：

    月度 P → 柱潜热加热 Q̇ = g·L_v·P_rate/(c_p·Δp_heat)   （零自由参数闭合）
    → Q_eddy = Q̇ − 纬向环均值                             （k=0 构造性为零——
                                                             v1 教训②自动满足；
                                                             Walker 经度结构保留）
    → 两模态定常线性系统：正压 ψ + 斜压 (ψ̂, χ̂, φ̂)        （论文 eq 11/13/15/17）
    → ω_mid = p_m·∇²χ̂ → w_mid = −ω_mid/(ρ_m·g)           （中层垂直运动，>0 上升）
    → 陆地 k_rain 下沉干燥门（engine/climate_physics.subsidence_rainout_gate）

v1（正压 + S&H RWS + 地表-T 热成风 2D 代理）2026-09-13 七版否证：根因 = 代理基本态
保真度低于机制需求。v2 按 proposal 注册前提①换两层 Gill 架构：**静止基本态下正压
方程解耦（ψF ≡ 0），模型严格退化为 Matsuno-Gill（论文 Case-1）；斜压响应基本不受
背景流影响**（论文原文）——基本态保真度不再是瓶颈。基本态 = 纬向平均（表面纬向风 +
热成风剪切），v1 的三类病灶（bin 噪声、地形污染、非地转 v̄ 修正）在纬向平均下结构
性消失。经度结构由 Q_eddy 强迫与 Gill 响应本身承载，不依赖基本态。

**k-块对角求解**：纬向平均基本态 ⇒ 全部算子系数与经度无关 ⇒ 经度 rFFT 后按 zonal
wavenumber k 完全块对角——每 k 一个 4·ni 复未知数稠密小系统（ni=79 → 316），12 月 ×
90 k ≈ 1080 次稠密 solve ≈ 2-4 s（v1 全 2D 稀疏 LU 是 35 s）。

**消费点换道**（v1 伤害放大器切断）：不产出 ΔSLP→边界层风（1/f 放大路径），只取
w_mid 作降水效率门（质量守恒 k_rain 调制，仿 §5-α SST 门）；风场保持 pass-1。

**符号约定**（Case-1 单测为最终锚，实现内逐项自查）：
- 斜压分量取下层符号（Gill 1980 约定）：ψ₁=ψ−ψ̂（上层）、ψ₂=ψ+ψ̂（下层）；χ₁=−χ̂、
  χ₂=+χ̂（正压缩散 ≡ 0）；Û = (U₂−U₁)/2（>0 = 低层东风切变）。
- 离散：∂x → diag(ik/(a cosφ))、∂xx → −k²/(a²cos²φ)、∇² → 𝓛_k = 𝓛_φ − k²c₂、
  ∇⁴ → 𝓛_k²、∂y → 纬向中心差分 𝓓（墙邻=0）。
- 阻尼符号按 v1 已验证约定：涡度方程 LHS +r∇²ψ、扩散 −A∇⁴ψ（论文转录的两处符号
  疑点以本约定为准，测试 2/3 仲裁）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import solve_banded
from scipy.ndimage import gaussian_filter1d

from dreamulator.engine.climate_physics import moist_lapse_rate
from dreamulator.map.stationary_wave import (
    C_P_AIR,
    DP_HEAT_FRACTION,
    F_CLIP_LAT_DEG,
    GRAV,
    L_V,
    PRESSURE_SCALE_HEIGHT_M,
    R_DRY,
    R_ENHANCE_CAP,
    T0_K,
    U_CRIT_MS,
    UBAR_CAP_MS,
    WaveGrid,
    _laplacian_stencil,
    bin_to_grid,
    cell_grid_indices,
    make_wave_grid,
    sample_grid_to_cells,
)
from dreamulator.result_contract import REFERENCE_MONTH_DAYS

# ── 文献锚定常数（Lee, Wang & Mapes 2009 §3；全部论文值，非调参项） ──
C_GRAVITY_WAVE_MS = 60.0  # 内重力波速 c_g（Kleeman 1989; Zebiak 1986; LWM09）
GAMMA_THERMAL_INV_S = 1.0 / (2.0 * 86400.0)  # 热力 Newton 阻尼 γ（Gill 1980）
R_BAROCLINIC_INV_S = 1.0 / (10.0 * 86400.0)  # 斜带动量 Rayleigh 阻尼 r₁
R_BAROTROPIC_INV_S = 1.0 / (20.0 * 86400.0)  # 正压动量 Rayleigh 阻尼 r₀
A_MOMENTUM_DIFF_M2S = 1.0e6  # 水平动量扩散 A₀ = A₁（m²/s）
# 斜压位势-温度转换：φ̂ = Λ·T′_mid（静力学层厚扰动，p₂/p₁ = 3）
LAMBDA_GEO_K = R_DRY * np.log(3.0) / 2.0  # ≈ 157.6 m²/s²/K
# ── 基本态护栏（同 v1 性质：有效域帽，非物理调参项） ──
SHEAR_CAP_MS = 40.0  # 热成风剪切有效域帽（真实副热带急流剪切 ~25-35 m/s 量级）
TAPER2_FULL_LAT_DEG = 55.0  # 高纬剪切 taper：|φ| ≤ 55° 全量…
TAPER2_ZERO_LAT_DEG = 75.0  # …≥ 75° 归零（极区高层流非热成风平衡，v1 教训）


@dataclass(frozen=True)
class TwoLevelSolution:
    """④ v2 求解结果（供 two-pass 集成、标定脚本与诊断消费）。"""

    w_mid_m_s: np.ndarray  # (n, 12) cell 中层垂直速度 m/s，>0 上升——门消费量
    psi: np.ndarray  # (12, nlat, nlon) 正压流函数 m²/s（诊断）
    psi_hat: np.ndarray  # (12, nlat, nlon) 斜压流函数 m²/s（下层符号）
    chi_hat: np.ndarray  # (12, nlat, nlon) 斜压速度势 m²/s
    phi_hat: np.ndarray  # (12, nlat, nlon) 斜压位势 m²/s²
    omega_mid_pa_s: np.ndarray  # (12, nlat, nlon) 中层 ω（Pa/s，<0 上升）
    u_baro: np.ndarray  # (12, nlat) 基本态正压风 m/s
    u_shear: np.ndarray  # (12, nlat) 基本态斜压半剪切 Û m/s（下层符号）


def precip_to_heating(
    p_rate_kg_m2_s: np.ndarray,
    surface_pressure_pa: float,
    elevation_m: np.ndarray,
) -> np.ndarray:
    """降水率 → 柱潜热加热率 Q̇（K/s；全派生量，无自由参数）。

    Q̇ = g·L_v·P_rate / (c_p·Δp_heat)，Δp_heat = DP_HEAT_FRACTION·p_s（深对流
    加热整层对流层——与 v1 ``precip_to_divergence`` 同一物理）。量级锚：海平面
    10 mm/day → ≈ 3.4 K/day（LWM09 El Niño 强迫 Q₀ = 2.15 K/day 同量级）。

    Args:
        p_rate_kg_m2_s: 降水率 kg/m²/s（1 mm/day = 1.157e-5），(n,) 或 (n, 12)。
        surface_pressure_pa: 海平面气压 Pa。
        elevation_m: 海拔 m（高原柱压小 → 同降水率加热更强）。

    Returns:
        Q̇（K/s），与输入同形。
    """
    p_s = surface_pressure_pa * np.exp(-elevation_m / PRESSURE_SCALE_HEIGHT_M)
    p_arr = np.asarray(p_rate_kg_m2_s, dtype=np.float64)
    denom = C_P_AIR * DP_HEAT_FRACTION * p_s
    single = p_arr.ndim == 1
    q = GRAV * L_V * (p_arr[:, None] if single else p_arr) / denom[:, None]
    return np.asarray(q[:, 0] if single else q)


def zonal_mean_basic_state(
    u_sfc_grid: np.ndarray,
    t_grid: np.ndarray,
    grid: WaveGrid,
    omega_planet: float,
    radius_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """月度 (nlat, nlon) 地表 u/T → 基本态 (U, Û)（(nlat,)，纬向平均）。

    - 低层风 U₂ = 地表纬向风的环均值（高斯 σ=2 bins 平滑防高纬稀 bin 噪声）；
    - 热成风剪切 ΔU = U₁−U₂ = −(R·ln3/f̂)·∂T̄/∂y（f̂ = sign⁺(f)·max(|f|, f(7.5°))，
      剪切帽 ±SHEAR_CAP_MS，高纬 taper 55°→75° 归零——极区高层流非地表热成风
      平衡，v1 教训）；T 取环均值（纬向平均杀掉 bin 噪声与地形污染 = v1 病灶）；
    - U = (U₁+U₂)/2（正压）、Û = (U₂−U₁)/2（斜压半剪切，下层符号）；
    - Ω < 1e-12（无自转）：热成风无定义 → Û ≡ 0（退化为论文 Case-1 纯 Gill）。

    量级预期（docstring 即测试锚）：副热带 ∂T̄/∂y ≈ −5e-6 K/m（~0.45 K/deg）→
    ΔU ≈ 20-25 m/s @30°N（真实副热带急流剪切量级）。
    """
    u_lat = gaussian_filter1d(u_sfc_grid.mean(axis=1), 2.0)
    t_lat = gaussian_filter1d(t_grid.mean(axis=1), 2.0)
    if omega_planet < 1e-12:
        u_baro = np.clip(u_lat, -UBAR_CAP_MS, UBAR_CAP_MS)
        u_baro = np.where(grid.wall, 0.0, u_baro)
        return np.asarray(u_baro), np.zeros_like(u_baro)

    t_k = t_lat + T0_K
    f = 2.0 * omega_planet * grid.sinf
    f_min = 2.0 * omega_planet * np.sin(np.deg2rad(F_CLIP_LAT_DEG))
    f_reg = np.where(f >= 0.0, 1.0, -1.0) * np.maximum(np.abs(f), f_min)
    dtdy = np.gradient(t_k, grid.dlat) / radius_m
    taper = np.clip(
        (TAPER2_ZERO_LAT_DEG - np.abs(grid.lat_deg)) / (TAPER2_ZERO_LAT_DEG - TAPER2_FULL_LAT_DEG),
        0.0,
        1.0,
    )
    shear = np.clip(-R_DRY * np.log(3.0) / f_reg * dtdy * taper, -SHEAR_CAP_MS, SHEAR_CAP_MS)
    u_baro = np.clip(u_lat + 0.5 * shear, -UBAR_CAP_MS, UBAR_CAP_MS)
    u_shear = -0.5 * shear  # Û = (U₂−U₁)/2（下层符号）
    u_baro = np.where(grid.wall, 0.0, u_baro)
    u_shear = np.where(grid.wall, 0.0, u_shear)
    return np.asarray(u_baro), np.asarray(u_shear)


def _zonal_relative_vorticity(u_lat: np.ndarray, grid: WaveGrid, radius_m: float) -> np.ndarray:
    """纬向风廓线的相对涡度 ζ = −(1/(a cosφ))·d(U cosφ)/dφ（v1 zonal 约定）。"""
    c = np.maximum(grid.cosf, 0.05)
    return np.asarray(-np.gradient(u_lat * grid.cosf, grid.dlat) / (radius_m * c))


def _meridional_operators(
    grid: WaveGrid, radius_m: float, inner: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """纬向离散算子（interior-only，墙邻 = 0 Dirichlet）：

    T = 纬向 Laplacian 三对角（``_laplacian_stencil`` 的 a_p/a_m/a_c），
    D = ∂y 中心差分 (1/(2a·Δφ))。
    """
    a_p, a_m, a_c, _ = _laplacian_stencil(grid, radius_m)
    ni = len(inner)
    idx = np.arange(ni)
    t_op = np.zeros((ni, ni))
    t_op[idx, idx] = a_c[inner]
    up_ok = ~grid.wall[inner + 1]
    dn_ok = ~grid.wall[inner - 1]
    t_op[idx[up_ok], idx[up_ok] + 1] = a_p[inner][up_ok]
    t_op[idx[dn_ok], idx[dn_ok] - 1] = a_m[inner][dn_ok]
    d_op = np.zeros((ni, ni))
    d_op[idx[up_ok], idx[up_ok] + 1] = 1.0 / (2.0 * radius_m * grid.dlat)
    d_op[idx[dn_ok], idx[dn_ok] - 1] = -1.0 / (2.0 * radius_m * grid.dlat)
    return t_op, d_op


def solve_two_level_month(
    q_eddy_grid: np.ndarray,
    u_baro: np.ndarray,
    u_shear: np.ndarray,
    grid: WaveGrid,
    omega_planet: float,
    radius_m: float,
    surface_pressure_pa: float = 101325.0,
) -> dict[str, np.ndarray]:
    """单月两模态求解：rfft(Q_eddy) → 逐 k 组装 4 场块矩阵 → 稠密 solve → irfft。

    方程组（论文 eq 11/13/15/17；阻尼符号按 v1 已验证约定；谱化符号见模块 docstring）：

        E1 (11) U∂x∇²ψ + β_e∂xψ + Û∂x∇²ψ̂ + β̂(∂xψ̂+∂yχ̂) + r₀∇²ψ − A₀∇⁴ψ = 0
        E2 (13) Û∂x∇²ψ + β̂∂xψ + U∂x∇²ψ̂ + β_e(∂xψ̂+∂yχ̂) + f∇²χ̂
                + r₁∇²ψ̂ − A₁∇⁴ψ̂ = 0
        E3 (15) (∂yÛ)k²c₂ψ + [(∂yU)k²c₂ − f∇² − β_e∂y]ψ̂
                + [U∂x∇² + (∂yU)∂x∂y + r₁∇² − A₁∇⁴]χ̂ + ∇²φ̂ = 0
        E4 (17) c²_g∇²χ̂ + γφ̂ = −Λ·Q̇_k

    Args:
        q_eddy_grid: (nlat, nlon) 加热率 Q̇（K/s），已扣纬向环均值（k=0 ≡ 0）。
        u_baro / u_shear: (nlat,) 基本态（``zonal_mean_basic_state`` 产物）。
        grid / omega_planet / radius_m: 几何与行星参数。

    Returns:
        dict：psi / psi_hat / chi_hat / phi_hat / omega_mid（均 (nlat, nlon)，
        墙行 0）+ residual（最大 ‖Ax−b‖，数值自查量）。
    """
    inner = np.flatnonzero(~grid.wall)
    ni = len(inner)
    nlon_h = grid.nlon // 2 + 1  # rfft bins（含 k=0 与 Nyquist）
    t_op, d_op = _meridional_operators(grid, radius_m, inner)
    eye = np.eye(ni)

    # 基本态廓线（interior 切片）
    f_full = 2.0 * omega_planet * grid.sinf
    zeta_b = _zonal_relative_vorticity(u_baro, grid, radius_m)
    zeta_s = _zonal_relative_vorticity(u_shear, grid, radius_m)
    q_full = f_full + zeta_b
    beta_e = np.gradient(q_full, grid.dlat) / radius_m
    beta_h = np.gradient(zeta_s, grid.dlat) / radius_m
    dudy = np.gradient(u_baro, grid.dlat) / radius_m
    dudyh = np.gradient(u_shear, grid.dlat) / radius_m
    f_i = f_full[inner]
    u_i = u_baro[inner]
    uh_i = u_shear[inner]
    be_i = beta_e[inner]
    bh_i = beta_h[inner]
    dy_u = dudy[inner]
    dy_uh = dudyh[inner]
    # 正压临界层增强阻尼（v1 惯例：仅正压方程；ū→0 临界纬的线性共振吸收）
    r0_eff = R_BAROTROPIC_INV_S * np.minimum(
        1.0 + (U_CRIT_MS / np.maximum(np.abs(u_i), 0.1)) ** 2, R_ENHANCE_CAP
    )
    c2 = 1.0 / (radius_m * grid.cosf[inner]) ** 2  # ∂xx 的谱系数
    sb = 1.0 / (radius_m * grid.cosf[inner])  # ∂x 的谱系数（× ik）

    q_spec = np.fft.rfft(q_eddy_grid, axis=1)  # (nlat, nlon_h)

    spectra: dict[str, np.ndarray] = {
        name: np.zeros((grid.nlat, nlon_h), dtype=np.complex128)
        for name in ("psi", "psi_hat", "chi_hat", "phi_hat", "omega")
    }
    residual = 0.0

    # 交织排列 [ψ_i, ψ̂_i, χ̂_i, φ̂_i]：所有场块带宽 ≤2（三对角/五对角）→ 全矩阵
    # 带宽 |4e+(rb−cb)| ≤ 11。带状求解器 O(n·b²)（本机 BLAS 慢路径下稠密 zgesv
    # 一次 126 ms = 单月 11 s；带状版亚毫秒）。
    l_bw = u_bw = 11
    diag_rows4 = 4 * np.arange(ni)

    def _place(ab: np.ndarray, rb: int, cb: int, block: np.ndarray) -> None:
        """把 (ni, ni) 带状场块放进交织 banded 存储（scipy ab[u+d, col] = a[row,col]）。"""
        for e in range(-2, 3):
            i0, i1 = max(0, e), min(ni, ni + e)
            if i0 >= i1:
                continue
            d = 4 * e + (rb - cb)
            if -l_bw <= d <= u_bw:
                ii_ = np.arange(i0, i1)
                cols4 = diag_rows4[ii_] - 4 * e + cb  # = 4j + cb, j = i − e
                ab[u_bw + d, cols4] = block[ii_, ii_ - e]

    def _banded_matvec(ab: np.ndarray, x: np.ndarray) -> np.ndarray:
        y = np.zeros_like(x)
        n_tot = x.size
        for d in range(-l_bw, u_bw + 1):
            j = np.arange(max(0, -d), min(n_tot, n_tot - d))
            y[j + d] += ab[u_bw + d, j] * x[j]
        return y

    for k in range(1, nlon_h):
        s = 1j * k * sb  # ∂x 谱对子
        lap_k = t_op - k * k * np.diag(c2)  # 𝓛_k = 𝓛_φ − k²c₂（三对角）
        lap2_k = lap_k @ lap_k  # ∇⁴_k（五对角）

        # 对角缩放算子（diag 乘在左侧 = 作用于算子输出的行）
        u_s_lap = (u_i * s)[:, None] * lap_k
        uh_s_lap = (uh_i * s)[:, None] * lap_k
        be_s = np.diag(be_i * s)
        bh_s = np.diag(bh_i * s)
        f_lap = f_i[:, None] * lap_k
        be_d = be_i[:, None] * d_op
        bh_d = bh_i[:, None] * d_op
        r0_lap = r0_eff[:, None] * lap_k
        r1_lap = R_BAROCLINIC_INV_S * lap_k
        diff2_b = A_MOMENTUM_DIFF_M2S * lap2_k
        k2_c2 = k * k * np.diag(c2)

        ab = np.zeros((l_bw + u_bw + 1, 4 * ni), dtype=np.complex128)
        # ── E1（正压涡度；阻尼 +r₀∇²ψ、扩散 −A₀∇⁴ψ = v1 约定）──
        _place(ab, 0, 0, u_s_lap + be_s + r0_lap - diff2_b)
        _place(ab, 0, 1, uh_s_lap + bh_s)
        _place(ab, 0, 2, bh_d)
        # ── E2（斜压涡度）──
        _place(ab, 1, 0, uh_s_lap + bh_s)
        _place(ab, 1, 1, u_s_lap + be_s + r1_lap - diff2_b)
        _place(ab, 1, 2, be_d + f_lap)
        # ── E3（斜压缩散；∂xx → −k²c₂ 已代入，−(∂y·)∂xx → +(∂y·)k²c₂）──
        _place(ab, 2, 0, dy_uh[:, None] * k2_c2)
        _place(ab, 2, 1, dy_u[:, None] * k2_c2 - f_lap - be_d)
        _place(ab, 2, 2, u_s_lap + (dy_u * s)[:, None] * d_op + r1_lap - diff2_b)
        _place(ab, 2, 3, lap_k)
        # ── E4（WTG 热力学：c²_g∇²χ̂ + γφ̂ = −Λ·Q̇）──
        _place(ab, 3, 2, C_GRAVITY_WAVE_MS**2 * lap_k)
        _place(ab, 3, 3, GAMMA_THERMAL_INV_S * eye)

        rhs = np.zeros(4 * ni, dtype=np.complex128)
        rhs[3::4] = -LAMBDA_GEO_K * q_spec[inner, k]

        x = solve_banded((l_bw, u_bw), ab, rhs)
        residual = max(residual, float(np.abs(_banded_matvec(ab, x) - rhs).max()))
        xf = x.reshape(ni, 4)
        spectra["psi"][inner, k] = xf[:, 0]
        spectra["psi_hat"][inner, k] = xf[:, 1]
        spectra["chi_hat"][inner, k] = xf[:, 2]
        spectra["phi_hat"][inner, k] = xf[:, 3]
        # ω_mid = p_m·∇²χ̂（p_m = 0.5·p_s；全球均值，行星可移植）
        spectra["omega"][inner, k] = 0.5 * surface_pressure_pa * (lap_k @ xf[:, 2])

    out = {name: np.fft.irfft(spec, n=grid.nlon, axis=1) for name, spec in spectra.items()}
    for name, field in out.items():
        field_res = np.asarray(field)
        field_res[grid.wall, :] = 0.0
        out[name] = field_res
    out["omega_mid"] = out.pop("omega")
    out["residual"] = np.asarray(residual)
    return out


def compute_omega_wave_anomaly(
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
) -> TwoLevelSolution:
    """顶层入口：引擎月度降水/温度/风场 → w_mid（逐 cell 逐月，m/s，>0 上升）。

    签名刻意对齐 v1 ``compute_slp_wave_anomaly`` 便于接线与测试复用。月度循环：
    加热闭合 → bin → 扣环均值 → 纬向平均基本态 → k-块求解 → ω 采样回 cell → w。
    """
    del wind_north_monthly  # 纬向平均基本态不用 v（v1 教训：非地转 v̄ 是毒项）
    del orbital_period_days  # 月度序列 = 参考年切片（CLIM-01），非轨道月
    grid = make_wave_grid()
    radius_m = radius_km * 1000.0
    omega_planet = 2.0 * np.pi / (rotation_period_days * 86400.0)
    n, n_months = p_monthly_mm.shape
    # Rate conversion needs seconds-per-stored-month: the monthly series is
    # a *reference-year* slice (CLIM-01/M2-A0④: 365.25/12-day months for
    # every world — nacrea's ~8.3-day orbital month must not divide here,
    # that would over-state the heating rate 3.65×).
    month_s = REFERENCE_MONTH_DAYS * 86400.0

    ii, jj = cell_grid_indices(cell_lat_deg, cell_lon_deg, grid)
    # 中层密度（cell 上，从年均 T 派生——同 v1 σ_T 路径）
    t_ann_k = t_monthly_c.mean(axis=1) + T0_K
    gamma_km = np.clip(moist_lapse_rate(t_monthly_c.mean(axis=1)), 4.5, 6.5) / 1000.0
    z_mid = (R_DRY * t_ann_k / GRAV) * np.log(2.0)
    rho_mid = (0.5 * surface_pressure_hpa * 100.0) / (
        R_DRY * np.maximum(t_ann_k - gamma_km * z_mid, 180.0)
    )

    p_rate = p_monthly_mm / month_s  # kg/m²/s
    q_cells = precip_to_heating(p_rate, surface_pressure_hpa * 100.0, elevation_m)

    field_names = ("psi", "psi_hat", "chi_hat", "phi_hat", "omega_mid")
    fields: dict[str, list[np.ndarray]] = {name: [] for name in field_names}
    u_baros = np.empty((n_months, grid.nlat))
    u_shears = np.empty((n_months, grid.nlat))
    w_mid = np.empty((n, n_months))
    for m in range(n_months):
        q_grid = bin_to_grid(q_cells[:, m], cell_area_km2, ii, jj, grid)
        q_eddy = q_grid - q_grid.mean(axis=1, keepdims=True)  # k=0 构造性为零
        u_grid = bin_to_grid(wind_east_monthly[:, m], cell_area_km2, ii, jj, grid, True)
        t_grid = bin_to_grid(t_monthly_c[:, m], cell_area_km2, ii, jj, grid, True)
        u_baro, u_shear = zonal_mean_basic_state(u_grid, t_grid, grid, omega_planet, radius_m)
        u_baros[m] = u_baro
        u_shears[m] = u_shear
        sol = solve_two_level_month(
            q_eddy,
            u_baro,
            u_shear,
            grid,
            omega_planet,
            radius_m,
            surface_pressure_pa=surface_pressure_hpa * 100.0,
        )
        for name in fields:
            fields[name].append(sol[name])
        w_mid[:, m] = -sample_grid_to_cells(sol["omega_mid"], cell_lat_deg, cell_lon_deg, grid) / (
            rho_mid * GRAV
        )

    return TwoLevelSolution(
        w_mid_m_s=w_mid,
        psi=np.stack(fields["psi"]),
        psi_hat=np.stack(fields["psi_hat"]),
        chi_hat=np.stack(fields["chi_hat"]),
        phi_hat=np.stack(fields["phi_hat"]),
        omega_mid_pa_s=np.stack(fields["omega_mid"]),
        u_baro=u_baros,
        u_shear=u_shears,
    )


def wet_trough_slp_anomaly(
    p_monthly_mm: np.ndarray,
    t_monthly_c: np.ndarray,
    elevation_m: np.ndarray,
    cell_lat_deg: np.ndarray,
    cell_lon_deg: np.ndarray,
    cell_area_km2: np.ndarray,
    wind_east_monthly: np.ndarray,
    *,
    surface_pressure_hpa: float,
    rotation_period_days: float,
    radius_km: float,
    heating_weight: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, TwoLevelSolution]:
    """湿季风槽 SLP 分量（hPa，(n, 12)）——W 场供给路线轮 1 的主闭合。

    深对流降水的潜热加热强迫已验证的两模态求解器，斜压位势 φ̂ 经静力映射读出
    海平面气压的湿分量（规定 ΔP 干预实验 2026-09-23 裁决 H1/H4：ΔP 结构是水汽
    路由的主杠杆、海洋侧定常结构必需——陆 + 洋的对流加热都进 Q）。文献：
    Boos & Kuang 2013（Sci. Rep. 3:1192，深对流降水维持季风槽的自由对流层温度
    极大值）；Chiang, Zebiak & Cane 2001（JAS 58:1371，elevated heating 主导热带
    地表风响应）；Gill 1980（非赤道加热 → Rossby 低压在加热西北侧——恒河风向
    修复的几何，规定 ΔP 实验实测验证）。

    静力映射（近似推导类，全常数、零新参数）：

        δp_s = −(p_s·ln(p_s/p_t)/T̄_col)·δT_v,ln        （顶边界静力）
        δT_v,ln = T′_mid·ln3/ln(p_s/p_t)               （两模态层只占柱的 ln3）
        T′_mid = −φ̂/Λ，Λ = R·ln3/2（下层符号，φ̂<0 = 加热）
        ⇒ δp_s = +c·φ̂，c = p_s·ln3/(T̄_col·Λ)

    ln(p_s/p_t) 因子相消；T̄_col = 255 K（标准大气对数气压加权柱平均）。量级核
    （2026-09-24 探针，earth 真实构建场）：孟加拉 7 月 300–430 W/m² → 恒河湿项
    −1.4 hPa（pass-1 P 下），定点迭代随 P 增长推向 −2~−3 hPa——与规定 ΔP 实验
    D_half 臂（0.5×观测全场 = 机制链增益自洽点）的实证需求量级一致。

    Args:
        p_monthly_mm: 引擎月度降水（mm/参考月，CLIM-01 基准），(n, 12)。
        t_monthly_c: 月度温度（°C），(n, 12)。
        elevation_m / cell_lat_deg / cell_lon_deg / cell_area_km2: 网格几何。
        wind_east_monthly: 月度纬向风（m/s），(n, 12)——纬向平均基本态的低层项。
        surface_pressure_hpa / rotation_period_days / radius_km: 行星参数。
        heating_weight: 可选 (n, 12) 深对流份额权重 ∈ [0, 1]（如 NPH09 pickup
            因子 f(W/W_sat)——亚饱和毛雨柱不加热自由对流层）。``None`` → 全量 P。

    Returns:
        (δp_s_wet (n, 12) hPa, v_lower (n, 12, 2) 下层风分量（赤道波导内的
        湿项风响应——见 _lower_level_wind_components）, 求解器完整解
        TwoLevelSolution——诊断/测试消费)。
    """
    grid = make_wave_grid()
    radius_m = radius_km * 1000.0
    omega_planet = 2.0 * np.pi / (rotation_period_days * 86400.0)
    n, n_months = p_monthly_mm.shape
    # 月度序列 = 参考年切片（CLIM-01：所有世界 365.25/12 天/月——轨道月做分母
    # 会把 nacrea 的加热率过计 3.65×）。
    month_s = REFERENCE_MONTH_DAYS * 86400.0

    # 静力映射常数（hPa per m²/s²）；p_s·ln3 的 p_s 用海平面值（SLP 语义）。
    c_hpa = surface_pressure_hpa * np.log(3.0) / (255.0 * LAMBDA_GEO_K)

    ii, jj = cell_grid_indices(cell_lat_deg, cell_lon_deg, grid)
    p_rate = p_monthly_mm / month_s  # kg/m²/s
    q_cells = precip_to_heating(p_rate, surface_pressure_hpa * 100.0, elevation_m)
    if heating_weight is not None:
        q_cells = q_cells * np.clip(np.asarray(heating_weight, dtype=np.float64), 0.0, 1.0)

    field_names = ("psi", "psi_hat", "chi_hat", "phi_hat", "omega_mid")
    fields: dict[str, list[np.ndarray]] = {name: [] for name in field_names}
    u_baros = np.empty((n_months, grid.nlat))
    u_shears = np.empty((n_months, grid.nlat))
    dp_wet = np.empty((n, n_months))
    v_lower = np.empty((n, n_months, 2))
    for m in range(n_months):
        q_grid = bin_to_grid(q_cells[:, m], cell_area_km2, ii, jj, grid)
        q_eddy = q_grid - q_grid.mean(axis=1, keepdims=True)  # k=0 ≡ 0
        u_grid = bin_to_grid(wind_east_monthly[:, m], cell_area_km2, ii, jj, grid, True)
        t_grid = bin_to_grid(t_monthly_c[:, m], cell_area_km2, ii, jj, grid, True)
        u_baro, u_shear = zonal_mean_basic_state(u_grid, t_grid, grid, omega_planet, radius_m)
        u_baros[m] = u_baro
        u_shears[m] = u_shear
        sol = solve_two_level_month(
            q_eddy,
            u_baro,
            u_shear,
            grid,
            omega_planet,
            radius_m,
            surface_pressure_pa=surface_pressure_hpa * 100.0,
        )
        for name in fields:
            fields[name].append(sol[name])
        phi_cells = sample_grid_to_cells(sol["phi_hat"], cell_lat_deg, cell_lon_deg, grid)
        dp_wet[:, m] = c_hpa * phi_cells
        u_lo, v_lo = _lower_level_wind_components(
            sol["psi"], sol["psi_hat"], sol["chi_hat"], grid, radius_m
        )
        v_lower[:, m, 0] = sample_grid_to_cells(u_lo, cell_lat_deg, cell_lon_deg, grid)
        v_lower[:, m, 1] = sample_grid_to_cells(v_lo, cell_lat_deg, cell_lon_deg, grid)

    solution = TwoLevelSolution(
        w_mid_m_s=np.full((n, n_months), np.nan),  # ω 未消费——见 compute_omega_wave_anomaly
        psi=np.stack(fields["psi"]),
        psi_hat=np.stack(fields["psi_hat"]),
        chi_hat=np.stack(fields["chi_hat"]),
        phi_hat=np.stack(fields["phi_hat"]),
        omega_mid_pa_s=np.stack(fields["omega_mid"]),
        u_baro=u_baros,
        u_shear=u_shears,
    )
    return dp_wet, v_lower, solution


def _lower_level_wind_components(
    psi: np.ndarray,
    psi_hat: np.ndarray,
    chi_hat: np.ndarray,
    grid: WaveGrid,
    radius_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """两模态解 → 下层风分量 (u, v)（m/s，(nlat, nlon)；Gill 下层符号）。

        v₂ = k̂×∇ψ₂ + ∇χ̂，ψ₂ = ψ + ψ̂（下层流函数），χ₂ = +χ̂（正压缩散 ≡ 0）

    有限差分（2° 网格；场本身 ≥行星尺度，且下游还有 175 km 图平滑——差分
    精度足够）。物理角色：赤道波导内湿项的风响应（代替 f→0 病态放大的
    边界层 Ekman 链——轮 1/2 的暖池撕裂病根，求解器动量阻尼 r₁=(10 d)⁻¹
    使风幅度有界）。
    """
    psi2 = psi + psi_hat
    lat_rad = np.radians(grid.lat_deg)
    # 经度方向是周期坐标——np.gradient 的单侧端点差分在 lon=0/358° 接缝处
    # 是错的，用 roll 中心差分（周期 wrap）。纬度方向保持 np.gradient
    # （端点是 Dirichlet 墙行，场为零，单侧差分无害）。
    two_dlon = 2.0 * grid.dlon
    dpsi_dlon = (np.roll(psi2, -1, axis=1) - np.roll(psi2, 1, axis=1)) / two_dlon
    dchi_dlon = (np.roll(chi_hat, -1, axis=1) - np.roll(chi_hat, 1, axis=1)) / two_dlon
    dpsi_dlat = np.gradient(psi2, lat_rad, axis=0)
    dchi_dlat = np.gradient(chi_hat, lat_rad, axis=0)
    cosf = np.maximum(grid.cosf, 0.05)
    # k̂×∇ψ₂ = (−(1/a)∂ψ₂/∂φ, (1/(a cosφ))∂ψ₂/∂λ)；∇χ̂ 直取
    u = dchi_dlon / (radius_m * cosf[:, None]) - dpsi_dlat / radius_m
    v = dpsi_dlon / (radius_m * cosf[:, None]) + dchi_dlat / radius_m
    return u, v
