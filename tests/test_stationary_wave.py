"""④ 定常波响应模块单测（roadmap ④）。

签名基准 = 离线原型（2026-09-13 验证轮）：印度季风源（75E/18N 高层辐散）
→ Rodwell & Hoskins 2001 型响应——源西侧（撒哈拉/中东）反气旋异常
ψ' > 0、下游（西太）气旋异常 ψ' < 0。数值与原型逐盒一致（±舍入）。
"""

from __future__ import annotations

import numpy as np
from scipy.sparse.linalg import splu

from dreamulator.map.stationary_wave import (
    assemble_laplacian,
    bin_to_grid,
    cell_grid_indices,
    compute_slp_wave_anomaly,
    make_wave_grid,
    precip_to_divergence,
    sample_grid_to_cells,
    solve_wave_month,
    upper_level_basic_state,
    zonal_mean_to_lat,
)

R_EARTH = 6.371e6
OMEGA_EARTH = 7.2921e-5
DAY_S = 86400.0


def _idealized_ubar(grid, jet_scale: float = 1.0) -> np.ndarray:
    """原型同款解析基本态（2D 广播）：副热带急流 30 m/s @38N + 热带东风 −12 @15N。"""
    lat = grid.lat_deg
    nh = lat >= 0
    u = np.zeros(grid.nlat)
    jet = 30.0 * np.exp(-(((lat[nh] - 38.0) / 12.0) ** 2))
    tejet = -12.0 * np.exp(-(((lat[nh] - 15.0) / 9.0) ** 2))
    u[nh] = jet + tejet
    u[~nh] = 12.5 * np.exp(-(((lat[~nh] + 30.0) / 12.0) ** 2))
    return np.tile((u * jet_scale)[:, None], (1, grid.nlon))


def _indian_source(grid, amp: float = 2.0e-6) -> np.ndarray:
    dlon = (grid.lon_deg[None, :] - 75.0 + 180.0) % 360.0 - 180.0
    dlat = grid.lat_deg[:, None] - 18.0
    return amp * np.exp(-(dlon**2) / (2 * 12.0**2) - (dlat**2) / (2 * 8.0**2))


def _boxmean(field: np.ndarray, grid, lon0, lon1, lat0, lat1) -> float:
    m = (
        (grid.lon_deg[None, :] >= lon0)
        & (grid.lon_deg[None, :] <= lon1)
        & (grid.lat_deg[:, None] >= lat0)
        & (grid.lat_deg[:, None] <= lat1)
    )
    return float(field[m].mean())


def _solve(grid, d, ubar, r_days=10.0):
    lap_lu = splu(assemble_laplacian(grid, R_EARTH))
    vbar = np.zeros_like(ubar)
    return solve_wave_month(
        d, ubar, vbar, lap_lu, grid, OMEGA_EARTH, R_EARTH, 1.0 / (r_days * DAY_S)
    )


def test_zero_forcing_zero_response():
    grid = make_wave_grid()
    psi = _solve(grid, np.zeros((grid.nlat, grid.nlon)), _idealized_ubar(grid))
    assert np.allclose(psi, 0.0, atol=1e-3)


def test_rodwell_hoskins_signature():
    """印度源 → 撒哈拉/中东反气旋（ψ'>0）、西太气旋（ψ'<0）；量级 ~1e6 m²/s。"""
    grid = make_wave_grid()
    psi = _solve(grid, _indian_source(grid), _idealized_ubar(grid))
    sahara = _boxmean(psi, grid, 0, 25, 15, 30)
    mideast = _boxmean(psi, grid, 35, 60, 20, 35)
    wpac = _boxmean(psi, grid, 120, 140, 10, 25)
    assert sahara > 1e6, f"撒哈拉应为反气旋脊，实际 {sahara:.2e}"
    assert mideast > 1e6, f"中东应为反气旋脊，实际 {mideast:.2e}"
    assert wpac < -1e6, f"西太应为气旋异常，实际 {wpac:.2e}"
    # 基线值（±10%）：+4.05/+4.13 (×1e6 m²/s)。原型（无临界层阻尼）为
    # +4.70/+4.42/−4.09；r_eff = r(1+(U_C/|ū|)²) 在理想基本态的零线处吸收
    # 7-14% 波活动——结构不变、幅度合法衰减，基准随之更新。
    assert abs(sahara / 4.05e6 - 1.0) < 0.10
    assert abs(mideast / 4.13e6 - 1.0) < 0.10


def test_damping_robustness():
    """r = 5/20 d 符号不变（文献惯例范围内的鲁棒性）。"""
    grid = make_wave_grid()
    d, ubar = _indian_source(grid), _idealized_ubar(grid)
    signs = []
    for rd in (5.0, 20.0):
        psi = _solve(grid, d, ubar, rd)
        signs.append(
            (
                np.sign(_boxmean(psi, grid, 0, 25, 15, 30)),
                np.sign(_boxmean(psi, grid, 120, 140, 10, 25)),
            )
        )
    assert signs[0] == signs[1] == (1.0, -1.0)


def test_jet_strength_robustness():
    """基本态急流 ×0.5/×2 符号不变。"""
    grid = make_wave_grid()
    d = _indian_source(grid)
    for js in (0.5, 2.0):
        psi = _solve(grid, d, _idealized_ubar(grid, js))
        assert _boxmean(psi, grid, 0, 25, 15, 30) > 0


def test_k0_removed_and_mean_blown_up_guard():
    """k=0 剔除（行均 ≈ 0）+ 非零均值 D 不发散（∮D dA=0 内部扣除生效）。"""
    grid = make_wave_grid()
    d = _indian_source(grid)  # 全球均值显著非零
    psi = _solve(grid, d, _idealized_ubar(grid))
    assert np.all(np.isfinite(psi))
    assert np.abs(psi).max() < 1e8, "k=0/均值未剔除时会到 1e13 量级"
    assert np.abs(psi.mean(axis=1)).max() < 1e-2


def test_no_rotation_and_equator_finite():
    """2D 基本态：赤道行无 NaN（f_reg 符号护栏）、无自转回退地表风、墙外归零。"""
    grid = make_wave_grid()
    t_zon = np.tile((30.0 - 40.0 * np.sin(np.radians(grid.lat_deg)) ** 2)[:, None], (1, grid.nlon))
    u_sfc = np.full((grid.nlat, grid.nlon), -5.0)
    v_sfc = np.zeros((grid.nlat, grid.nlon))
    ub, vb = upper_level_basic_state(u_sfc, v_sfc, t_zon, grid, OMEGA_EARTH, R_EARTH)
    assert np.all(np.isfinite(ub)) and np.all(np.isfinite(vb))
    assert np.abs(ub).max() <= 80.0 + 1e-9  # 数值护栏
    assert np.all(ub[grid.wall] == 0.0) and np.all(vb[grid.wall] == 0.0)
    ub0, vb0 = upper_level_basic_state(u_sfc, v_sfc, t_zon, grid, 0.0, R_EARTH)
    assert np.allclose(ub0, -5.0) and np.allclose(vb0, 0.0)
    # zonal T → corr_v = 0（∂T/∂x = 0）
    assert np.allclose(vb[~grid.wall], 0.0, atol=1e-10)


def test_divergence_closure_scale():
    """D 闭合量级：5 mm/d → ~1e-6/s；线性于 P；高原放大（p_s² 分母）。"""
    t28, z0, p0 = np.array([28.0]), np.array([0.0]), 101325.0
    p5 = precip_to_divergence(np.array([5.0 / DAY_S]), t28, z0, p0)
    p50 = precip_to_divergence(np.array([50.0 / DAY_S]), t28, z0, p0)
    assert p5.shape == (1,) and p50.shape == (1,)
    assert 1e-7 < float(p5[0]) < 1e-5
    assert abs(float(p50[0]) / float(p5[0]) - 10.0) < 1e-6  # 严格线性
    hi = precip_to_divergence(
        np.array([5.0 / DAY_S]), np.array([5.0]), np.array([4000.0]), 101325.0
    )
    assert float(hi[0]) > float(p5[0])  # 薄气柱 → 同 P 率更强辐散


def test_bin_sample_roundtrip():
    grid = make_wave_grid()
    rng = np.random.default_rng(42)
    n = 50000
    clat = rng.uniform(-89, 89, n)
    clon = rng.uniform(0, 360, n)
    ii, jj = cell_grid_indices(clat, clon, grid)
    fld = bin_to_grid(np.ones(n), np.ones(n), ii, jj, grid)
    # 有 cell 落入的 bin 恢复 1；空 bin 回退 0
    hit = np.zeros(grid.nlat * grid.nlon, dtype=bool)
    hit[ii * grid.nlon + jj] = True
    assert np.allclose(fld.ravel()[hit], 1.0)
    back = sample_grid_to_cells(np.ones((grid.nlat, grid.nlon)), clat, clon, grid)
    assert np.allclose(back[np.abs(clat) < 79.0], 1.0, atol=1e-9)
    # zonal mean of constant = constant
    zm = zonal_mean_to_lat(np.full(n, 3.0), np.ones(n), ii, grid)
    occ = np.bincount(ii, minlength=grid.nlat) > 0
    assert np.allclose(zm[occ], 3.0)


def test_full_chain_synthetic_world():
    """compute_slp_wave_anomaly 全链：合成 cell 集 → ΔSLP 有限、量级护栏、符号。

    合成世界：20k 随机 cell；7 月（month 4）季风降水集中于 75E/18N 高斯块，
    其余月份/区域弱降水。验收：无 NaN、|ΔSLP| < 15 hPa、撒哈拉带（源西侧）
    7 月 ΔSLP > 0。
    """
    rng = np.random.default_rng(7)
    n = 20000
    clat = np.degrees(np.arcsin(rng.uniform(-1, 1, n)))  # 等面积纬度采样
    clon = rng.uniform(0, 360, n)
    area = np.full(n, 510.9e6 / n)  # km²，全球均分
    elev = np.zeros(n)
    p = np.zeros((n, 12))
    dlon = (clon - 75.0 + 180.0) % 360.0 - 180.0
    bump = np.exp(-(dlon**2) / (2 * 12.0**2) - (clat - 18.0) ** 2 / (2 * 8.0**2))
    p[:, 4] = 300.0 * bump + 30.0  # mm/month
    p[:, 3] = p[:, 5] = 100.0 * bump + 30.0
    for m in range(12):
        if m not in (3, 4, 5):
            p[:, m] = 30.0
    # 七月式纬向 T：副热带陆地加热峰（~20N）→ 热带高层东风 + 副热带西风急流
    # （R&H 波导结构）。单调递减廓线会给 15N 西风、源嵌入西风带 → 响应变号
    # （test 首版实锤）——真实引擎 T 场自带副热带夏季峰，此处与之对齐。
    t_lat = (
        28.0 - 38.0 * np.sin(np.radians(clat)) ** 2 + 6.0 * np.exp(-(((clat - 20.0) / 15.0) ** 2))
    )
    t = np.tile(t_lat[:, None], (1, 12))
    u_east = np.full((n, 12), -5.0)
    v_north = np.zeros((n, 12))

    sol = compute_slp_wave_anomaly(
        p_monthly_mm=p,
        t_monthly_c=t,
        elevation_m=elev,
        cell_lat_deg=clat,
        cell_lon_deg=clon,
        cell_area_km2=area,
        wind_east_monthly=u_east,
        wind_north_monthly=v_north,
        surface_pressure_hpa=1013.25,
        rotation_period_days=1.0,
        radius_km=6371.0,
        orbital_period_days=365.25,
    )
    dp = sol.dp_hpa
    assert dp.shape == (n, 12)
    assert np.all(np.isfinite(dp))
    assert np.abs(dp).max() < 15.0, f"|ΔSLP| 超护栏: {np.abs(dp).max():.1f} hPa"
    # 7 月撒哈拉带（0-25E, 15-30N）应为正异常（脊）
    sah = (clon >= 0) & (clon <= 25) & (clat >= 15) & (clat <= 30)
    assert dp[sah, 4].mean() > 0.0
    # 零降水月（本合成场无）之外的月均有限且赤道退化（f→0 → ΔSLP→0）
    eq = np.abs(clat) < 1.0
    assert np.abs(dp[eq, 4]).max() < 0.5


def test_thermal_wind_units():
    """热成风量纲/符号：NH 温度向极递减 → 高层西风增强（∂u/∂z > 0）。"""
    grid = make_wave_grid()
    t_zon = np.tile((30.0 - 40.0 * np.sin(np.radians(grid.lat_deg)) ** 2)[:, None], (1, grid.nlon))
    z = np.zeros((grid.nlat, grid.nlon))
    ub, _ = upper_level_basic_state(z, z, t_zon, grid, OMEGA_EARTH, R_EARTH)
    i38 = int(np.argmin(np.abs(grid.lat_deg - 38.0)))
    assert ub[i38, 0] > 10.0, "38N 高层应为西风急流量级"
    assert ub[i38, 0] <= 80.0
