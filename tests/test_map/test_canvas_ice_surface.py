"""Physical invariants for the local shallow-ice surface trial."""

import numpy as np
import pytest

from dreamulator.map.canvas_ice_surface import (
    redistribute_ice,
    source_ice_bed,
    subgrid_ice_relaxation_fraction,
    subgrid_ice_surface_level,
)


def test_ice_bed_uses_native_mean_and_relief_instead_of_td_amplitude():
    rng = np.random.default_rng(18)
    td = 2500 + rng.normal(0, 1000, (96, 96))
    condition = np.full(td.shape, 2500.0)
    ice = np.full(td.shape, 2200.0)
    ice[:, :8] = 0
    result = source_ice_bed(
        td,
        condition,
        ice,
        np.full(td.shape, 40.0),
        spacing_m=1000,
        source_spacing_m=50_000,
    )
    np.testing.assert_array_equal(result[:, :8], td[:, :8])
    assert result[:, 8:].mean() == pytest.approx(300, abs=1e-10)
    assert result[:, 8:].std() == pytest.approx(40, rel=0.06)


def test_native_ice_fraction_connects_bed_sources_continuously():
    td = np.full((6, 9), 2800.0)
    condition = np.full(td.shape, 2500.0)
    ice = np.full(td.shape, 100.0)
    fraction = np.broadcast_to(np.linspace(0, 1, 9), td.shape)
    bed = source_ice_bed(
        td,
        condition,
        ice,
        np.zeros(td.shape),
        spacing_m=1000,
        source_spacing_m=50_000,
        ice_fraction=fraction,
    )
    surface = bed + ice
    assert np.max(np.abs(np.diff(surface, axis=1))) == pytest.approx(37.5)
    np.testing.assert_array_equal(surface[:, 0], td[:, 0])
    np.testing.assert_array_equal(surface[:, -1], condition[:, -1])


def test_ice_flows_into_dry_valley_without_clipping_or_volume_loss():
    bed = np.zeros((9, 11))
    ice = np.zeros_like(bed)
    ice[3:6, 3:6] = 800.0
    land = np.ones_like(bed, dtype=bool)
    land[:, -1] = False
    result, budget = redistribute_ice(
        bed, ice, land, spacing_m=500.0, elapsed_yr=0.1, gravity_m_s2=9.81
    )
    assert result.min() >= 0
    assert result.max() < ice.max()
    assert result[4, 6] > 0
    np.testing.assert_array_equal(result[:, -1], 0)
    assert budget.final_volume_m3 == pytest.approx(budget.initial_volume_m3, rel=1e-12)
    assert np.sum(result**2) < np.sum(ice**2)


def test_flat_ice_surface_over_rough_bed_is_stationary():
    y, x = np.indices((8, 10))
    bed = 400 * np.sin(x) * np.cos(y)
    ice = 900.0 - bed
    result, budget = redistribute_ice(
        bed,
        ice,
        np.ones_like(bed, dtype=bool),
        spacing_m=1000.0,
        elapsed_yr=100,
        gravity_m_s2=10.28,
    )
    np.testing.assert_array_equal(result, ice)
    assert budget.residual_m3 == 0


def test_bare_rock_has_no_mobile_ice():
    bed = np.arange(35, dtype=float).reshape(5, 7) * 100
    result, budget = redistribute_ice(
        bed,
        np.zeros_like(bed),
        np.ones_like(bed, dtype=bool),
        spacing_m=500,
        elapsed_yr=100,
        gravity_m_s2=9.81,
    )
    np.testing.assert_array_equal(result, 0)
    assert budget.initial_volume_m3 == budget.final_volume_m3 == 0


def test_subgrid_level_preserves_volume_and_exposes_peaks_in_thin_ice():
    bed = np.array([[0.0, 30.0, 100.0, 400.0]] * 3)
    ice = np.array([0.0, 20.0, 500.0])
    level = subgrid_ice_surface_level(bed, ice)
    thickness = np.maximum(level[:, None] - bed, 0)
    np.testing.assert_allclose(thickness.mean(axis=-1), ice)
    assert np.count_nonzero(thickness[1]) == 2
    assert np.all(thickness[2] > 0)
    response = subgrid_ice_relaxation_fraction(
        np.array([50.0, 2000.0]),
        np.array([200.0, 200.0]),
        spacing_m=5750,
        elapsed_yr=10,
        gravity_m_s2=10.28,
    )
    assert response[0] < 0.001
    assert response[1] > 0.99


def test_partial_cells_use_support_thickness_and_conserve_volume():
    bed = np.zeros((6, 6))
    land = np.ones(bed.shape, bool)
    fraction = np.ones(bed.shape)
    fraction[:, 3:] = 0.5
    # Equal surfaces on support: half-area cells hold half the cell-mean volume.
    still, _ = redistribute_ice(
        bed,
        np.where(fraction < 1, 400.0, 800.0),
        land,
        spacing_m=5750,
        elapsed_yr=10,
        gravity_m_s2=10.28,
        support_fraction=fraction,
    )
    np.testing.assert_allclose(still, np.where(fraction < 1, 400.0, 800.0), atol=1e-6)
    stepped = np.where(fraction < 1, 100.0, 800.0)
    result, budget = redistribute_ice(
        bed,
        stepped,
        land,
        spacing_m=5750,
        elapsed_yr=50,
        gravity_m_s2=10.28,
        support_fraction=fraction,
    )
    assert abs(budget.residual_m3) < 1e-6 * budget.initial_volume_m3
    assert result[:, 3:].mean() > 100
    full, _ = redistribute_ice(
        bed, stepped, land, spacing_m=5750, elapsed_yr=50, gravity_m_s2=10.28
    )
    same, _ = redistribute_ice(
        bed,
        stepped,
        land,
        spacing_m=5750,
        elapsed_yr=50,
        gravity_m_s2=10.28,
        support_fraction=np.ones(bed.shape),
    )
    np.testing.assert_array_equal(full, same)


class TestPlasticMarginThickness:
    """塑性冰缘剖面：冰缘为零、按距离开方上升、随 ρg 跨世界变化。"""

    def test_zero_at_the_margin_and_square_root_inland(self) -> None:
        from dreamulator.map.canvas_ice_surface import plastic_margin_thickness

        d = np.array([0.0, 90.0, 360.0, 5750.0])
        h = plastic_margin_thickness(d, gravity_m_s2=10.28)
        assert h[0] == 0.0
        # 90 m 处约 39 m，5750 m 处约 312 m（τ₀ = 80 kPa，nacrea 的 g）
        assert 35.0 < h[1] < 43.0
        assert 300.0 < h[3] < 325.0
        # 四倍距离给两倍厚度
        assert h[2] / h[1] == pytest.approx(2.0, rel=1e-9)

    def test_negative_distance_clips_and_gravity_scales(self) -> None:
        from dreamulator.map.canvas_ice_surface import plastic_margin_thickness

        assert float(plastic_margin_thickness(np.array([-5.0]), gravity_m_s2=9.81)[0]) == 0.0
        weak = plastic_margin_thickness(np.array([1000.0]), gravity_m_s2=5.0)
        earth = plastic_margin_thickness(np.array([1000.0]), gravity_m_s2=9.81)
        assert weak[0] > earth[0]  # 重力弱 → 同样的屈服应力支撑更厚的冰


class TestMarginTaper:
    """冰缘锥度：带外逐位不变、带内取塑性剖面、冰量只减不增。"""

    def test_interior_is_bit_identical_beyond_the_band(self) -> None:
        """这是锥度的结构保证，不是近似——带外表达式归约为 min(h, h)。"""
        from dreamulator.map.canvas_ice_surface import MARGIN_BAND_LIMIT_M, margin_taper

        h = np.array([800.0, 1680.0, 2500.0])
        d = np.full(3, MARGIN_BAND_LIMIT_M * 1.001)
        np.testing.assert_array_equal(margin_taper(h, d, gravity_m_s2=10.28), h)

    def test_thin_ice_follows_the_plastic_profile_exactly(self) -> None:
        """薄冰（带内 h·√(d/L) 低于塑性剖面）的结果与 h 无关，正是塑性剖面本身。"""
        from dreamulator.map.canvas_ice_surface import margin_taper, plastic_margin_thickness

        d = np.array([90.0, 360.0, 2000.0])
        expected = plastic_margin_thickness(d, gravity_m_s2=10.28)
        for thickness in (200.0, 300.0, 440.0):
            got = margin_taper(np.full(3, thickness), d, gravity_m_s2=10.28)
            np.testing.assert_allclose(got, np.minimum(thickness, expected), rtol=1e-12)

    def test_band_limit_keeps_thick_ice_above_the_profile(self) -> None:
        """厚冰的带宽被钉在 L：若不钉，2000 m 的冰会被一路削到 240 km 以内。"""
        from dreamulator.map.canvas_ice_surface import (
            MARGIN_BAND_LIMIT_M,
            margin_taper,
            plastic_margin_thickness,
        )

        d = np.array([MARGIN_BAND_LIMIT_M * 0.25])
        thick = np.array([2000.0])
        got = margin_taper(thick, d, gravity_m_s2=10.28)
        assert got[0] == pytest.approx(1000.0)  # √0.25 = 0.5
        assert got[0] > plastic_margin_thickness(d, gravity_m_s2=10.28)[0]

    def test_margin_wall_comes_down_and_volume_only_falls(self) -> None:
        from dreamulator.map.canvas_ice_surface import (
            MARGIN_BAND_LIMIT_M,
            margin_taper,
            plastic_margin_thickness,
        )

        rng = np.random.default_rng(7)
        h = rng.uniform(100.0, 1500.0, size=512)
        d = rng.uniform(0.0, 50_000.0, size=512)
        got = margin_taper(h, d, gravity_m_s2=10.28)
        assert np.all(got <= h + 1e-9)
        assert got.sum() < h.sum()
        # 最外一圈像素（90 m）至多留下原厚度的 √(90/L)，即削掉九成以上
        edge = margin_taper(h, np.full(512, 90.0), gravity_m_s2=10.28)
        bound = np.maximum(
            plastic_margin_thickness(np.full(512, 90.0), gravity_m_s2=10.28),
            h * np.sqrt(90.0 / MARGIN_BAND_LIMIT_M),
        )
        assert np.all(edge <= bound + 1e-9)
        assert edge.max() < 140.0  # 最厚的 1500 m 冰给 130 m，实测画布均值为 51 m

    def test_invalid_inputs_raise(self) -> None:
        from dreamulator.map.canvas_ice_surface import margin_taper

        with pytest.raises(ValueError, match="band_limit_m"):
            margin_taper(np.ones(3), np.ones(3), gravity_m_s2=10.28, band_limit_m=0.0)
        with pytest.raises(ValueError, match="shape mismatch"):
            margin_taper(np.ones(3), np.ones(4), gravity_m_s2=10.28)
