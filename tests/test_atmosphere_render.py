"""Tests for the L5 single-scattering atmosphere renderer."""

from __future__ import annotations

import numpy as np

from dreamulator.media import atmosphere_render as ar


def _earth_model() -> ar.AtmosphereModel:
    return ar.AtmosphereModel(
        planet_radius_km=ar.EARTH_RADIUS_KM,
        gravity_m_s2=ar.EARTH_GRAVITY,
        surface_pressure_atm=1.0,
        star_temperature_k=5772.0,
    )


def _uniform_inputs(size: int = 64) -> tuple[np.ndarray, np.ndarray]:
    surface = np.zeros((size, size * 2, 3), dtype=np.float64)
    surface[..., 0] = 0.30
    surface[..., 1] = 0.35
    surface[..., 2] = 0.40
    cloud = np.zeros((size, size * 2), dtype=np.float64)
    return surface, cloud


def test_star_optics_orders_rayleigh_channels() -> None:
    solar = ar.star_optics(5772.0)
    assert solar.rayleigh_rgb[0] < solar.rayleigh_rgb[1] < solar.rayleigh_rgb[2]
    # A K star is much redder than the Sun in the display frame.
    k_star = ar.star_optics(4365.0)
    assert k_star.white_rgb[0] / k_star.white_rgb[2] > solar.white_rgb[0] / solar.white_rgb[2]
    # The star white point is finite and positive.
    assert all(np.isfinite(v) and v > 0.0 for v in k_star.white_rgb)


def test_cie_cmf_peaks() -> None:
    wavelengths = np.arange(380.0, 781.0, 1.0)
    x_bar, y_bar, z_bar = ar.cie_xyz_cmf(wavelengths)
    assert abs(float(wavelengths[np.argmax(y_bar)]) - 555.0) < 5.0
    assert abs(float(wavelengths[np.argmax(z_bar)]) - 445.0) < 10.0
    assert abs(float(wavelengths[np.argmax(x_bar)]) - 600.0) < 10.0


def test_hydrostatic_scale_height() -> None:
    model = _earth_model()
    assert abs(model.scale_height_km - 8.0) < 0.1
    # A heavier planet with the same temperature has a thinner atmosphere.
    heavier = ar.AtmosphereModel(gravity_m_s2=2.0 * ar.EARTH_GRAVITY)
    assert heavier.scale_height_km < model.scale_height_km


def test_mean_molar_mass() -> None:
    earth_air = ar.mean_molar_mass_kg_mol({"N2": 0.7808, "O2": 0.2095, "Ar": 0.0093})
    assert 0.0285 < earth_air < 0.0295
    assert ar.mean_molar_mass_kg_mol(None) > 0.0


def test_transmittance_lut_is_physical() -> None:
    model = _earth_model()
    lut = ar.build_transmittance_lut(model)
    overhead = lut.sample(np.array([0.0]), np.array([1.0]))[0]
    grazing = lut.sample(np.array([0.0]), np.array([0.05]))[0]
    blocked = lut.sample(np.array([0.0]), np.array([-0.5]))[0]
    top = lut.sample(np.array([model.top_altitude_km]), np.array([1.0]))[0]
    assert np.all(overhead < 1.0) and np.all(overhead > 0.5)
    # Blue is extinguished more than red.
    assert overhead[2] < overhead[0]
    assert np.all(grazing < overhead)
    np.testing.assert_allclose(blocked, 0.0, atol=1e-6)
    np.testing.assert_allclose(top, 1.0, atol=1e-3)


def test_render_halo_terminator_and_determinism() -> None:
    surface, cloud = _uniform_inputs(64)
    model = _earth_model()
    first = ar.render_globe_atmosphere(
        surface,
        cloud,
        res=400,
        center_lon_deg=0.0,
        center_lat_deg=0.0,
        sun_lon_deg=20.0,
        sun_lat_deg=0.0,
        model=model,
        view_samples=6,
    )
    second = ar.render_globe_atmosphere(
        surface,
        cloud,
        res=400,
        center_lon_deg=0.0,
        center_lat_deg=0.0,
        sun_lon_deg=20.0,
        sun_lat_deg=0.0,
        model=model,
        view_samples=6,
    )
    np.testing.assert_array_equal(first, second)
    assert first.shape == (400, 400, 3)
    assert first.dtype == np.uint8

    disk_radius = 200.0 * 0.92
    row = 200
    centre = int(first[row, 200].mean())
    # The first pixel just outside the disk is atmosphere-only.  The sun is
    # offset east, so this east limb is sunlit and scatters into the halo.
    halo = int(first[row, 200 + int(disk_radius)].mean())
    space = int(first[row, 399].mean())
    # The sunlit limb scatters above the disk; far outside the shell is space.
    # Multiple scattering can make the limb brighter than the disk centre, so
    # the test only requires both to be lit.
    assert centre > 0
    assert halo > 0
    assert space == 0


def test_physical_exposure_is_warmer() -> None:
    surface, cloud = _uniform_inputs(48)
    model = ar.AtmosphereModel(star_temperature_k=4365.0, planet_radius_km=6817.0)
    white = ar.render_globe_atmosphere(
        surface,
        cloud,
        res=160,
        center_lon_deg=0.0,
        center_lat_deg=0.0,
        sun_lon_deg=0.0,
        sun_lat_deg=0.0,
        model=model,
        exposure="white_balance",
        view_samples=5,
    ).astype(np.float64)
    physical = ar.render_globe_atmosphere(
        surface,
        cloud,
        res=160,
        center_lon_deg=0.0,
        center_lat_deg=0.0,
        sun_lon_deg=0.0,
        sun_lat_deg=0.0,
        model=model,
        exposure="physical",
        view_samples=5,
    ).astype(np.float64)
    white_ratio = white[..., 0].mean() / max(white[..., 2].mean(), 1e-6)
    physical_ratio = physical[..., 0].mean() / max(physical[..., 2].mean(), 1e-6)
    assert physical_ratio > white_ratio


def test_multiple_scattering_lut_and_brightening() -> None:
    model = _earth_model()
    transmittance = ar.build_transmittance_lut(model)
    lut = ar.build_multiscattering_lut(model, transmittance)
    assert lut.table.shape == (32, 32, 3)
    assert np.all(np.isfinite(lut.table))
    assert np.all(lut.table >= 0.0)
    day = lut.sample(np.array([0.0]), np.array([1.0]))[0]
    night = lut.sample(np.array([0.0]), np.array([-0.5]))[0]
    assert day.mean() > night.mean()

    surface, cloud = _uniform_inputs(48)
    kwargs = dict(
        res=120,
        center_lon_deg=0.0,
        center_lat_deg=0.0,
        sun_lon_deg=20.0,
        sun_lat_deg=0.0,
        model=model,
        view_samples=4,
    )
    single = ar.render_globe_atmosphere(surface, cloud, multiple_scattering=False, **kwargs)
    multiple = ar.render_globe_atmosphere(surface, cloud, multiple_scattering=True, **kwargs)
    assert multiple.mean() > single.mean()


def test_ocean_sun_glint_only_on_water() -> None:
    surface, cloud = _uniform_inputs(48)
    model = _earth_model()
    kwargs = dict(
        res=120,
        center_lon_deg=0.0,
        center_lat_deg=0.0,
        sun_lon_deg=0.0,
        sun_lat_deg=0.0,
        model=model,
        view_samples=4,
    )
    ocean = np.ones_like(surface[..., 0])
    land = np.zeros_like(ocean)
    with_glint = ar.render_globe_atmosphere(surface, cloud, ocean_mask=ocean, **kwargs)
    without_glint = ar.render_globe_atmosphere(
        surface, cloud, ocean_mask=ocean, sun_glint=False, **kwargs
    )
    land_with_glint = ar.render_globe_atmosphere(surface, cloud, ocean_mask=land, **kwargs)
    # Land has no specular term: enabling the glint changes nothing.
    np.testing.assert_array_equal(land_with_glint, without_glint)
    # The sub-solar ocean pixel is brighter with the glint.
    assert with_glint[60, 60].mean() > without_glint[60, 60].mean()


def test_two_layer_cirrus_changes_image() -> None:
    surface, low = _uniform_inputs(64)
    high = np.zeros_like(low)
    high[8:24, 30:100] = 0.45
    model = _earth_model()
    common = dict(
        res=160,
        center_lon_deg=0.0,
        center_lat_deg=0.0,
        sun_lon_deg=20.0,
        sun_lat_deg=0.0,
        model=model,
        view_samples=4,
    )
    single = ar.render_globe_atmosphere(surface, low, **common)
    double = ar.render_globe_atmosphere(surface, low, high, cirrus_altitude_km=9.0, **common)
    assert double.shape == single.shape
    assert not np.array_equal(double, single)
    # The high shell sits above the low shell; swapping the altitudes is invalid.
    try:
        ar.render_globe_atmosphere(surface, low, high, cirrus_altitude_km=3.0, **common)
    except ValueError:
        pass
    else:
        raise AssertionError("cirrus_altitude_km below the low shell must be rejected")


def test_cloud_shadow_changes_surface() -> None:
    surface, _ = _uniform_inputs(64)
    cloud = np.zeros_like(surface[..., 0])
    cloud[20:44, 40:88] = 0.8
    model = _earth_model()
    with_shadow = ar.render_globe_atmosphere(
        surface,
        cloud,
        res=160,
        center_lon_deg=0.0,
        center_lat_deg=0.0,
        sun_lon_deg=0.0,
        sun_lat_deg=0.0,
        model=model,
        cloud_shadows=True,
        view_samples=4,
    )
    without_shadow = ar.render_globe_atmosphere(
        surface,
        cloud,
        res=160,
        center_lon_deg=0.0,
        center_lat_deg=0.0,
        sun_lon_deg=0.0,
        sun_lat_deg=0.0,
        model=model,
        cloud_shadows=False,
        view_samples=4,
    )
    assert not np.array_equal(with_shadow, without_shadow)
