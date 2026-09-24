"""④ v2 两层 Gill 定常波模块单测（roadmap ④ v2）。

物理基准 = Lee, Wang & Mapes 2009 (J. Climate 22:272) 论文自检：
- Case-1（静止基本态）：正压方程严格解耦（ψ ≡ 0）、模型退化为 Matsuno-Gill；
- Case-4（背景剪切）：赤道源南北两侧正压反气旋对（论文摘要原句的数值版）。
R&H 签名断言在 **ω 场**（消费量：季风加热 → 撒哈拉/中东下沉舌），在 rest /
论文 Case-4 / 现实急流三种基本态下符号不变——「斜压响应基本不受背景流影响」
（论文原文）的实现检验。ψ 的西翼符号在两模态分配下与 v1 纯正压视图不同
（正压反气旋位于源区上空 = Tibetan-High 型，见 test 5），不作 R&H 断言。
"""

from __future__ import annotations

import numpy as np
import pytest

import dreamulator.map.stationary_wave_two_level as tl
from dreamulator.engine.climate_physics import (
    _SUBSIDENCE_GATE_F_MIN,
    subsidence_rainout_gate,
)
from dreamulator.map.stationary_wave import make_wave_grid
from dreamulator.map.stationary_wave_two_level import (
    compute_omega_wave_anomaly,
    precip_to_heating,
    solve_two_level_month,
    wet_trough_slp_anomaly,
    zonal_mean_basic_state,
)

R_EARTH = 6.371e6
OMEGA_EARTH = 7.2921e-5
DAY_S = 86400.0


def _gauss_source(grid, lam0, lat0, lam_sigma, lat_sigma, q_k_per_day):
    """高斯加热（K/day → K/s），返回已扣纬向环均值的 (nlat, nlon) 场。"""
    dlon = (grid.lon_deg[None, :] - lam0 + 180.0) % 360.0 - 180.0
    dlat = grid.lat_deg[:, None] - lat0
    q = (q_k_per_day / DAY_S) * np.exp(-((dlon / lam_sigma) ** 2) - ((dlat / lat_sigma) ** 2))
    return q - q.mean(axis=1, keepdims=True)


def _boxmean(field, grid, lon0, lon1, lat0, lat1):
    m = (
        (grid.lon_deg[None, :] >= lon0)
        & (grid.lon_deg[None, :] <= lon1)
        & (grid.lat_deg[:, None] >= lat0)
        & (grid.lat_deg[:, None] <= lat1)
    )
    return float(field[m].mean())


def _profiles_realistic(grid):
    """现实廓线：下层 = v1 解析（急流 30 @38N + TEJ −12 @15N + 南半球急流），
    上层 = 下层 + 30cosφ（对流层西风剪切，LWM09 Case-4 量级）。"""
    lat = grid.lat_deg
    lower = np.zeros(grid.nlat)
    nh = lat >= 0
    lower[nh] = 30.0 * np.exp(-(((lat[nh] - 38.0) / 12.0) ** 2)) - 12.0 * np.exp(
        -(((lat[nh] - 15.0) / 9.0) ** 2)
    )
    lower[~nh] = 12.5 * np.exp(-(((lat[~nh] + 30.0) / 12.0) ** 2))
    upper = lower + 30.0 * np.cos(np.radians(lat))
    return 0.5 * (lower + upper), 0.5 * (lower - upper)


def _profiles_case4(grid):
    """论文 Case-4：U = 25cosφ、Û = −15cosφ。"""
    lat = grid.lat_deg
    return 25.0 * np.cos(np.radians(lat)), -15.0 * np.cos(np.radians(lat))


def _width_1e(field_col, grid):
    """|field| 列的 1/e 半宽（度）：最北超过 peak/e 的纬度（含源宽度的整宽度量）。"""
    pk = float(np.abs(field_col).max())
    above = np.flatnonzero(np.abs(field_col) > pk / np.e)
    return float(grid.lat_deg[above[-1]] - grid.lat_deg[above[0]])


EQ = 45  # 赤道行索引（lat 0° @2° 网格）


def test_zero_heating_zero_response():
    grid = make_wave_grid()
    sol = solve_two_level_month(
        np.zeros((grid.nlat, grid.nlon)), *(_profiles_realistic(grid)), grid, OMEGA_EARTH, R_EARTH
    )
    for name in ("psi", "psi_hat", "chi_hat", "phi_hat", "omega_mid"):
        assert np.abs(sol[name]).max() < 1e-12, name


def test_case1_reduces_to_matsuno_gill():
    """静止基本态：ψ ≡ 0（论文 Case-1 精确解耦）+ Gill 解结构（符号约定锁定）。"""
    grid = make_wave_grid()
    z = np.zeros(grid.nlat)
    q = _gauss_source(grid, 90.0, 0.0, 25.0, 5.0, 2.15)  # 论文 (22) 几何
    sol = solve_two_level_month(q, z, z, grid, OMEGA_EARTH, R_EARTH)
    # ① 正压方程解耦：ψ 精确为零
    assert np.abs(sol["psi"]).max() < 1e-9
    # ② 热源：中层上升（ω<0）；χ̂ > 0（高层辐散符号——本实现的 (ψ̂,χ̂) 约定）
    #    φ̂ < 0（下层符号静力：加热 → 层厚上界面抬升 → 下层减半位势降）
    assert sol["omega_mid"][EQ, 45] < -1e-3
    assert sol["chi_hat"][EQ, 45] > 0
    assert sol["phi_hat"][EQ, 45] < 0
    # ③ 源西侧 Rossby 双涡：ψ̂ 关于赤道反对称（两半球反气旋旋转相反）
    nh = sol["psi_hat"][int((12 + 90) / 2), 20]
    sh = sol["psi_hat"][int((-12 + 90) / 2), 20]
    assert nh < 0 and sh > 0 and abs(nh + sh) < 0.05 * abs(nh)
    # ④ 赤道俘获：源经度上 |χ̂| 随 |纬度| 衰减（±45° < 25% 峰值；L_R = 14.6°
    #    的阻尼+源宽稀释后核区 e 折 ~29°，此处取有裕度的单调衰减断言）
    chi_col = np.abs(sol["chi_hat"][:, 45])
    pk = float(chi_col.max())
    assert chi_col[int((45 + 90) / 2)] < 0.25 * pk
    assert chi_col[int((-45 + 90) / 2)] < 0.25 * pk
    # ⑤ 数值自查：带状解残差
    assert float(sol["residual"]) < 1e-8


def test_kelvin_eastward_decay():
    """赤道信号沿经度东传单调衰减（Kelvin 尾，窗口避开西翼 Rossby 与环回）。"""
    grid = make_wave_grid()
    z = np.zeros(grid.nlat)
    q = _gauss_source(grid, 90.0, 0.0, 25.0, 5.0, 2.15)
    sol = solve_two_level_month(q, z, z, grid, OMEGA_EARTH, R_EARTH)
    chi_eq = np.abs(sol["chi_hat"][EQ, int(110 / 2) : int(170 / 2) + 1])
    assert np.all(np.diff(chi_eq) <= 1e-9), "东传窗口应单调衰减"
    assert chi_eq[-1] < 0.5 * chi_eq[0]


@pytest.mark.parametrize("state", ["rest", "case4", "realistic"])
def test_rodwell_hoskins_signature(state):
    """印度季风源 → 撒哈拉/中东下沉舌（消费量 ω 的 R&H 签名，基本态不变式）。"""
    grid = make_wave_grid()
    profiles = {
        "rest": (np.zeros(grid.nlat), np.zeros(grid.nlat)),
        "case4": _profiles_case4(grid),
        "realistic": _profiles_realistic(grid),
    }[state]
    q = _gauss_source(grid, 75.0, 18.0, 20.0, 8.0, 3.0)
    sol = solve_two_level_month(q, *profiles, grid, OMEGA_EARTH, R_EARTH)
    om = sol["omega_mid"]
    src = _boxmean(om, grid, 65, 85, 10, 25)
    sahara = _boxmean(om, grid, 0, 25, 15, 30)
    mideast = _boxmean(om, grid, 35, 60, 20, 35)
    assert src < -1e-3, f"[{state}] 源区应上升，实际 {src:+.2e}"
    assert sahara > 1e-4, f"[{state}] 撒哈拉应下沉，实际 {sahara:+.2e}"
    assert mideast > 1e-4, f"[{state}] 中东应下沉，实际 {mideast:+.2e}"


def test_shear_excites_barotropic():
    """论文：斜压→正压激发只能经垂直背景剪切（ψF ∝ Û）。"""
    grid = make_wave_grid()
    q = _gauss_source(grid, 90.0, 0.0, 25.0, 5.0, 2.15)
    u_baro, _ = _profiles_case4(grid)
    zero_shear = np.zeros(grid.nlat)
    s1 = solve_two_level_month(q, u_baro, zero_shear, grid, OMEGA_EARTH, R_EARTH)
    ratio0 = np.abs(s1["psi"]).max() / max(np.abs(s1["psi_hat"]).max(), 1e-30)
    assert ratio0 < 1e-6, "无剪切时正压模态必须不被激发（论文 Case-2）"
    _, u_shear = _profiles_case4(grid)
    s2 = solve_two_level_month(q, u_baro, u_shear, grid, OMEGA_EARTH, R_EARTH)
    assert np.abs(s2["psi"]).max() > 1e-2 * np.abs(s2["psi_hat"]).max()
    # 论文 Case-4（赤道源）：正压响应在源南北两侧为反气旋（两半球旋转相反）
    psi = s2["psi"]
    assert psi[int((25 + 90) / 2), int(70 / 2) : int(110 / 2)].mean() > 0
    assert psi[int((-25 + 90) / 2), int(70 / 2) : int(110 / 2)].mean() < 0


@pytest.mark.parametrize("scale", [0.5, 2.0])
def test_damping_robustness(scale, monkeypatch):
    """r₀/r₁ ×0.5/×2：R&H 下沉签名符号不变（论文敏感性结论：阻尼只变幅度）。"""
    monkeypatch.setattr(tl, "R_BAROTROPIC_INV_S", tl.R_BAROTROPIC_INV_S * scale)
    monkeypatch.setattr(tl, "R_BAROCLINIC_INV_S", tl.R_BAROCLINIC_INV_S * scale)
    grid = make_wave_grid()
    q = _gauss_source(grid, 75.0, 18.0, 20.0, 8.0, 3.0)
    sol = solve_two_level_month(q, *_profiles_realistic(grid), grid, OMEGA_EARTH, R_EARTH)
    om = sol["omega_mid"]
    assert _boxmean(om, grid, 65, 85, 10, 25) < -1e-3
    assert _boxmean(om, grid, 0, 25, 15, 30) > 1e-4
    assert _boxmean(om, grid, 35, 60, 20, 35) > 1e-4


def test_gamma_robustness(monkeypatch):
    """热力阻尼 γ 2d → 5d：签名符号不变。"""
    monkeypatch.setattr(tl, "GAMMA_THERMAL_INV_S", 1.0 / (5.0 * DAY_S))
    grid = make_wave_grid()
    q = _gauss_source(grid, 75.0, 18.0, 20.0, 8.0, 3.0)
    sol = solve_two_level_month(q, *_profiles_realistic(grid), grid, OMEGA_EARTH, R_EARTH)
    om = sol["omega_mid"]
    assert _boxmean(om, grid, 0, 25, 15, 30) > 1e-4
    assert _boxmean(om, grid, 65, 85, 10, 25) < -1e-3


def test_k0_removed_and_finiteness():
    """强迫含大纬向均值分量：k=0 构造性为零（响应行均 ≈ 0）+ 全场有限护栏。"""
    grid = make_wave_grid()
    q = _gauss_source(grid, 75.0, 18.0, 20.0, 8.0, 3.0)
    q = q + 1e-4 * np.cos(np.radians(grid.lat_deg))[:, None]  # 大 zonal 分量
    q = q - q.mean(axis=1, keepdims=True)  # 调用方闭合（同 compute_omega_wave_anomaly）
    sol = solve_two_level_month(q, *_profiles_realistic(grid), grid, OMEGA_EARTH, R_EARTH)
    for name in ("psi", "psi_hat", "chi_hat", "phi_hat", "omega_mid"):
        f = sol[name]
        assert np.isfinite(f).all(), name
        assert np.abs(f).max() < 1e8, name
        assert np.abs(f.mean(axis=1)).max() < 1e-6 * max(np.abs(f).max(), 1e-30), name


def test_no_rotation_limit():
    """Ω→0：有限、无涡旋响应（ψ̂ → 0——无旋转无 Rossby 涡）、热源仍上升。"""
    grid = make_wave_grid()
    z = np.zeros(grid.nlat)
    q = _gauss_source(grid, 90.0, 0.0, 25.0, 5.0, 2.15)
    sol_rot = solve_two_level_month(q, z, z, grid, OMEGA_EARTH, R_EARTH)
    sol0 = solve_two_level_month(q, z, z, grid, 1e-13, R_EARTH)
    for name in ("psi", "psi_hat", "chi_hat", "phi_hat", "omega_mid"):
        assert np.isfinite(sol0[name]).all(), name
    assert np.abs(sol0["psi_hat"]).max() < 0.05 * np.abs(sol_rot["psi_hat"]).max()
    assert sol0["omega_mid"][EQ, 45] < 0


def test_slow_rotation_nacrea():
    """Ω = 0.318 Ω⊕（nacrea）：赤道波导按 L_R ∝ Ω^(-1/2) 加宽（14.6° → ~26°；
    实测 ψ̂ 1/e 宽比 1.54 vs 理论 1.77——源宽+阻尼稀释，断言取 1.3）。"""
    grid = make_wave_grid()
    z = np.zeros(grid.nlat)
    q = _gauss_source(grid, 90.0, 0.0, 25.0, 5.0, 2.15)
    w_earth = _width_1e(
        solve_two_level_month(q, z, z, grid, OMEGA_EARTH, R_EARTH)["psi_hat"][:, 45], grid
    )
    w_nacrea = _width_1e(
        solve_two_level_month(q, z, z, grid, 0.318 * OMEGA_EARTH, R_EARTH)["psi_hat"][:, 45], grid
    )
    assert w_nacrea > 1.3 * w_earth, f"慢自转波导未加宽：{w_nacrea:.1f}° vs {w_earth:.1f}°"


class TestSubsidenceRainoutGate:
    """④ v2 消费门：k_rain × f(w_mid)，陆地 only，上升恒 1。"""

    def test_ascent_never_suppressed(self) -> None:
        w = np.array([0.01, 0.001, 0.0, -0.001])
        f = subsidence_rainout_gate(w, np.ones(4, dtype=bool))
        assert f[0] == 1.0 and f[1] == 1.0 and f[2] == 1.0
        assert f[3] < 1.0

    def test_monotone_and_floor(self) -> None:
        # 域扩到 0.1 m/s（超物理极值）以触达外推段的 floor 钳制。
        dw = np.concatenate([np.zeros(4), np.geomspace(1e-5, 1e-1, 40)])
        w = -dw  # 下沉为负
        f = subsidence_rainout_gate(w, np.ones(44, dtype=bool))
        assert np.all(np.diff(f) <= 1e-12), "下沉越强门越压制（单调）"
        assert f[-1] == pytest.approx(_SUBSIDENCE_GATE_F_MIN)
        assert f.min() >= _SUBSIDENCE_GATE_F_MIN - 1e-12

    def test_ocean_untouched(self) -> None:
        w = np.full(4, -0.01)
        oc = np.array([True, True, False, False])
        f = subsidence_rainout_gate(w, ~oc)
        assert f[0] == 1.0 and f[1] == 1.0 and f[2] < 1.0

    def test_monthly_consistent_with_annual(self) -> None:
        rng = np.random.default_rng(7)
        w12 = -rng.random((20, 12)) * 2e-3
        land = rng.random(20) > 0.3
        f12 = subsidence_rainout_gate(w12, land)
        for m in range(12):
            fm = subsidence_rainout_gate(w12[:, m], land)
            assert np.allclose(f12[:, m], fm)
        assert f12.shape == (20, 12)


def test_precip_to_heating_units():
    """10 mm/day @海平面 → ~3.4 K/day（LWM09 El Niño 强迫 2.15 K/day 同量级）。"""
    sea = np.zeros(4)
    q10 = precip_to_heating(np.full(4, 10.0 / DAY_S), 101325.0, sea)
    assert 3.0 < q10.mean() * DAY_S < 4.0
    q20 = precip_to_heating(np.full(4, 20.0 / DAY_S), 101325.0, sea)
    assert np.allclose(q20, 2.0 * q10), "加热率严格线性于降水率"
    assert np.all(precip_to_heating(np.zeros(4), 101325.0, sea) == 0.0)
    # 高原：柱压小 → 同降水率加热更强（p_s 指数衰减）
    q_plateau = precip_to_heating(np.full(2, 10.0 / DAY_S), 101325.0, np.full(2, 5000.0))
    assert np.all(q_plateau > q10[:2])


def test_monthly_linearity():
    """同基本态下解的叠加原理（k-块求解器无跨模态/跨月状态泄漏）。"""
    grid = make_wave_grid()
    prof = _profiles_realistic(grid)
    q1 = _gauss_source(grid, 75.0, 18.0, 15.0, 7.0, 2.0)
    q2 = _gauss_source(grid, 240.0, -5.0, 20.0, 6.0, 1.5)
    s1 = solve_two_level_month(q1, *prof, grid, OMEGA_EARTH, R_EARTH)
    s2 = solve_two_level_month(q2, *prof, grid, OMEGA_EARTH, R_EARTH)
    s12 = solve_two_level_month(q1 + q2, *prof, grid, OMEGA_EARTH, R_EARTH)
    for name in ("psi", "psi_hat", "chi_hat", "phi_hat", "omega_mid"):
        assert np.allclose(s12[name], s1[name] + s2[name], rtol=1e-8, atol=1e-12), name


class TestZonalMeanBasicState:
    def test_scale_and_thermal_wind_sign(self) -> None:
        """现实纬向 T 梯度 → 副热带西风剪切 10-45 m/s；墙行零。"""
        grid = make_wave_grid()
        t = 288.0 - 40.0 * grid.sinf[:, None] ** 2 * np.ones((1, grid.nlon))
        u = np.zeros((grid.nlat, grid.nlon))
        u_baro, u_shear = zonal_mean_basic_state(u, t, grid, OMEGA_EARTH, R_EARTH)
        # 剪切 = U₁ − U₂ = −2Û（下层符号）
        shear = -2.0 * u_shear
        i30 = int((30 + 90) / 2)
        assert 10.0 < shear[i30] < 45.0, f"30°N 剪切 {shear[i30]:.1f} m/s 超出有效域"
        assert shear[i30] > 0, "NH 极向降温 → 西风随高度增强（热成风符号）"
        assert np.all(u_baro[grid.wall] == 0.0) and np.all(u_shear[grid.wall] == 0.0)
        assert np.abs(shear).max() <= tl.SHEAR_CAP_MS + 1e-9

    def test_no_rotation_degenerate(self) -> None:
        grid = make_wave_grid()
        t = 288.0 - 40.0 * grid.sinf[:, None] ** 2 * np.ones((1, grid.nlon))
        u = np.zeros((grid.nlat, grid.nlon))
        u_baro, u_shear = zonal_mean_basic_state(u, t, grid, 1e-13, R_EARTH)
        assert np.all(u_shear == 0.0), "无自转：热成风无定义 → Û ≡ 0"


def test_full_chain_synthetic_world():
    """compute_omega_wave_anomaly 全链（合成世界，7 月印度季风）。"""
    grid = make_wave_grid()
    rng = np.random.default_rng(3)
    # cell 网格：4° 等距格点展平（纬度余弦面积权）
    lat_c = np.repeat(grid.lat_deg[4:-4:2], grid.nlon // 2)
    lon_c = np.tile(np.arange(0, 360, 4), len(range(4, grid.nlat - 4, 2)))
    n = len(lat_c)
    area = np.full(n, 16.0) * np.cos(np.radians(lat_c))
    land = np.ones(n, dtype=bool)
    # 7 月季风降水（mm/month），其余月 20%
    p_month = np.full((n, 12), 30.0)
    dl = (lon_c - 75.0 + 180.0) % 360.0 - 180.0
    dn = lat_c - 18.0
    p_jul = 350.0 * np.exp(-((dl / 18.0) ** 2) - ((dn / 7.0) ** 2))
    p_month[:, 6] = p_jul
    t_month = 25.0 - 30.0 * np.sin(np.radians(lat_c)) ** 2
    t_month = np.broadcast_to(t_month[:, None], (n, 12)).copy()
    wind = np.zeros((n, 12))

    sol = compute_omega_wave_anomaly(
        p_monthly_mm=p_month,
        t_monthly_c=t_month,
        elevation_m=np.zeros(n),
        cell_lat_deg=lat_c,
        cell_lon_deg=lon_c,
        cell_area_km2=area,
        wind_east_monthly=wind,
        wind_north_monthly=wind,
        surface_pressure_hpa=1013.25,
        rotation_period_days=1.0,
        radius_km=6371.0,
        orbital_period_days=365.25,
    )
    w = sol.w_mid_m_s
    assert w.shape == (n, 12) and np.isfinite(w).all()
    assert np.abs(w).max() < 0.05, f"|w| 过大：{np.abs(w).max():.2e} m/s"
    # 7 月：源区上升、撒哈拉下沉
    src = w[(np.abs(dn) < 6) & (np.abs(dl) < 10), 6].mean()
    sah = w[(lat_c > 15) & (lat_c < 30) & (lon_c < 25), 6].mean()
    assert src > 0, f"7 月源区应上升 {src:+.2e}"
    assert sah < 0, f"7 月撒哈拉应下沉 {sah:+.2e}"
    # 门：陆地下沉区压制、上升区 1、全域 [floor, 1]
    gate = subsidence_rainout_gate(w, land)
    assert gate.min() >= 0.2 - 1e-12 and gate.max() <= 1.0 + 1e-12
    assert gate[(lat_c > 15) & (lat_c < 30) & (lon_c < 25)].min() < 1.0
    assert gate[(np.abs(dn) < 6) & (np.abs(dl) < 10)].min() >= 1.0 - 1e-12
    del rng


class TestWetTroughSlp:
    """湿季风槽 SLP 分量（W 供给路线轮 1 主闭合）。

    物理锚：深对流加热 → φ̂（下层符号，<0 = 加热）→ 静力映射 δp_s = c·φ̂。
    幅度带参照 2026-09-24 真实场探针（恒河 7 月 −1.4 hPa @ pass-1 P）与规定
    ΔP 干预实验（机制链自洽点 = −2~−3 hPa）；Rossby 西移在场内（合成实测：
    最小值 68°E vs 源 75°E）。文献：Boos & Kuang 2013；Chiang et al. 2001；
    Gill 1980。
    """

    @staticmethod
    def _synthetic(p_peak: float = 350.0):
        grid = make_wave_grid()
        lat_c = np.repeat(grid.lat_deg[4:-4:2], grid.nlon // 2)
        lon_c = np.tile(np.arange(0, 360, 4), len(range(4, grid.nlat - 4, 2)))
        n = len(lat_c)
        area = np.full(n, 16.0) * np.cos(np.radians(lat_c))
        p_month = np.full((n, 12), 30.0)
        dl = (lon_c - 75.0 + 180.0) % 360.0 - 180.0
        dn = lat_c - 18.0
        p_month[:, 6] = p_peak * np.exp(-((dl / 18.0) ** 2) - ((dn / 7.0) ** 2))
        t_month = np.broadcast_to(
            (25.0 - 30.0 * np.sin(np.radians(lat_c)) ** 2)[:, None], (n, 12)
        ).copy()
        return lat_c, lon_c, area, dl, dn, p_month, t_month

    @staticmethod
    def _run(lat_c, lon_c, area, p_month, t_month, weight=None):
        return wet_trough_slp_anomaly(
            p_monthly_mm=p_month,
            t_monthly_c=t_month,
            elevation_m=np.zeros(len(lat_c)),
            cell_lat_deg=lat_c,
            cell_lon_deg=lon_c,
            cell_area_km2=area,
            wind_east_monthly=np.zeros_like(p_month),
            surface_pressure_hpa=1013.25,
            rotation_period_days=1.0,
            radius_km=6371.0,
            heating_weight=weight,
        )

    def test_zero_precip_zero_slp(self) -> None:
        lat_c, lon_c, area, dl, dn, _, t_month = self._synthetic()
        n = len(lat_c)
        dp, _, _ = self._run(lat_c, lon_c, area, np.zeros((n, 12)), t_month)
        assert dp.shape == (n, 12)
        assert np.abs(dp).max() < 1e-12

    def test_source_low_sign_and_amplitude(self) -> None:
        lat_c, lon_c, area, dl, dn, p_month, t_month = self._synthetic()
        dp, _, _ = self._run(lat_c, lon_c, area, p_month, t_month)
        jul = dp[:, 6]
        assert np.isfinite(dp).all()
        src = jul[(np.abs(dn) < 6) & (np.abs(dl) < 10)].mean()
        # 低气压在源区；幅度带 = 物理推导常数的预期域（非 −60 hPa 荒谬局地平衡）
        assert src < -0.3, f"源区应低压，实际 {src:+.2f} hPa"
        assert -6.0 < jul.min() < -0.3, f"7 月幅度 {jul.min():+.2f} 超出物理域"
        # 年均 = 单月强迫的 1/12（月份守恒：其余月只剩均匀背景的 eddy≈0）
        ann = dp[(np.abs(dn) < 6) & (np.abs(dl) < 10)].mean()
        assert abs(ann - src / 12.0) < 0.15

    def test_rossby_westward_displacement(self) -> None:
        """Gill 结构：低压中心西移出加热中心（合成实测 68°E vs 源 75°E）。"""
        lat_c, lon_c, area, dl, dn, p_month, t_month = self._synthetic()
        dp, _, _ = self._run(lat_c, lon_c, area, p_month, t_month)
        jul = dp[:, 6]
        imin = int(np.argmin(jul))
        assert lon_c[imin] < 75.0, f"低压中心应在源以西，实际 {lon_c[imin]:.0f}°E"

    def test_remote_not_deeper_than_source(self) -> None:
        """无雨的撒哈拉框不得比源区更深（自引用增防：远场遥相关弱于局地）。"""
        lat_c, lon_c, area, dl, dn, p_month, t_month = self._synthetic()
        dp, _, _ = self._run(lat_c, lon_c, area, p_month, t_month)
        jul = dp[:, 6]
        src = jul[(np.abs(dn) < 6) & (np.abs(dl) < 10)].mean()
        sah = jul[(lat_c > 15) & (lat_c < 30) & (lon_c < 25)].mean()
        assert sah > src, f"撒哈拉 {sah:+.2f} 不应比源 {src:+.2f} 深"

    def test_heating_weight_linear(self) -> None:
        lat_c, lon_c, area, dl, dn, p_month, t_month = self._synthetic()
        n = len(lat_c)
        dp0, _, _ = self._run(lat_c, lon_c, area, p_month, t_month)
        dp_half, _, _ = self._run(
            lat_c, lon_c, area, p_month, t_month, weight=np.full((n, 12), 0.5)
        )
        dp_zero, _, _ = self._run(lat_c, lon_c, area, p_month, t_month, weight=np.zeros((n, 12)))
        assert np.abs(dp_zero).max() < 1e-12
        assert np.allclose(dp_half, 0.5 * dp0, rtol=1e-9, atol=1e-12)

    def test_linear_in_precipitation(self) -> None:
        lat_c, lon_c, area, dl, dn, p_month, t_month = self._synthetic()
        dp1, _, _ = self._run(lat_c, lon_c, area, p_month, t_month)
        dp2, _, _ = self._run(lat_c, lon_c, area, 2.0 * p_month, t_month)
        assert np.allclose(dp2, 2.0 * dp1, rtol=1e-9, atol=1e-12)

    def test_lower_wind_structure(self) -> None:
        """下层风：零强迫→零；印度源 → 源以南季风流入（+v），幅度物理域。"""
        lat_c, lon_c, area, dl, dn, p_month, t_month = self._synthetic()
        _, v_lo_zero, _ = self._run(lat_c, lon_c, area, np.zeros_like(p_month), t_month)
        assert np.abs(v_lo_zero).max() < 1e-12
        _, v_lo, _ = self._run(lat_c, lon_c, area, p_month, t_month)
        jul = v_lo[:, 6, :]
        assert np.isfinite(jul).all()
        mag = np.hypot(jul[:, 0], jul[:, 1])
        # 求解器动量阻尼下的幅度域（对照：边界层链在赤道洋面无界放大 ~30 m/s）
        assert 0.05 < np.percentile(mag, 99) < 15.0, f"|v| p99 = {np.percentile(mag, 99):.2f}"
        # 源以南（2–12N，55–85E）季风流入：向北分量
        m_in = (lat_c > 2) & (lat_c < 12) & (lon_c > 55) & (lon_c < 85)
        v_mer = jul[m_in, 1].mean()
        assert v_mer > 0.05, f"源以南应有向北季风流入，实际 v = {v_mer:+.3f} m/s"
