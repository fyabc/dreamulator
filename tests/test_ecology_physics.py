"""Tests for ecology_physics — Whittaker, Miami NPP, domesticable tags."""

import math

import pytest

from dreamulator.engine.ecology_physics import (
    DomesticableProfile,
    SoilOrder,
    WhittakerBiome,
    classify_cell_ecology,
    classify_soil,
    classify_whittaker_biome,
    get_domesticable_profile,
    miami_npp,
)

# ---------------------------------------------------------------------------
# Whittaker biome classification
# ---------------------------------------------------------------------------

BIOME_CASES: list[tuple[float, float, bool, WhittakerBiome]] = [
    # Tropical band (T > 18)
    (28.0, 3000.0, False, WhittakerBiome.TROPICAL_RAINFOREST),
    (25.0, 1500.0, False, WhittakerBiome.TROPICAL_SEASONAL_FOREST),
    (30.0, 700.0, False, WhittakerBiome.TROPICAL_SAVANNA),
    (35.0, 200.0, False, WhittakerBiome.TROPICAL_DESERT),
    # Temperate band (5 < T <= 18)
    (12.0, 2000.0, False, WhittakerBiome.TEMPERATE_RAINFOREST),
    (10.0, 1000.0, False, WhittakerBiome.TEMPERATE_FOREST),
    (8.0, 500.0, False, WhittakerBiome.TEMPERATE_GRASSLAND),
    (15.0, 150.0, False, WhittakerBiome.TEMPERATE_DESERT),
    # Boreal / cold (T <= 5)
    (3.0, 600.0, False, WhittakerBiome.BOREAL_FOREST),
    (0.0, 300.0, False, WhittakerBiome.BOREAL_SHRUBLAND),
    (-3.0, 100.0, False, WhittakerBiome.TUNDRA),
    # Ice cap (T <= -10)
    (-15.0, 800.0, False, WhittakerBiome.ICE),
    (-25.0, 50.0, False, WhittakerBiome.ICE),
    # Ocean sentinel
    (20.0, 1000.0, True, WhittakerBiome.OCEAN),
    (-5.0, 0.0, True, WhittakerBiome.OCEAN),
    # Boundary: exactly at threshold
    (18.0, 2000.0, False, WhittakerBiome.TEMPERATE_RAINFOREST),  # T=18 not >18 → temperate
    (18.1, 2000.0, False, WhittakerBiome.TROPICAL_SEASONAL_FOREST),  # T>18, P≤2000
    (18.1, 2100.0, False, WhittakerBiome.TROPICAL_RAINFOREST),  # T>18, P>2000
    (5.0, 1500.0, False, WhittakerBiome.BOREAL_FOREST),  # T=5 not >5 → boreal
    (5.1, 500.0, False, WhittakerBiome.TEMPERATE_GRASSLAND),  # T>5, P∈[300,700)
    (4.9, 500.0, False, WhittakerBiome.BOREAL_SHRUBLAND),  # T=4.9 <=5, P=500 not >500 → shrubland
]


@pytest.mark.parametrize("t, p, ocean, expected", BIOME_CASES)
def test_whittaker_biome_classification(
    t: float,
    p: float,
    ocean: bool,
    expected: WhittakerBiome,
) -> None:
    assert classify_whittaker_biome(t, p, is_ocean=ocean) == expected


# ---------------------------------------------------------------------------
# Miami NPP model
# ---------------------------------------------------------------------------


NPP_CASES: list[tuple[float | None, float | None, float | None, float | None]] = [
    # (T, P, par_ratio, expected) — expected=None means approx. check
    (25.0, 2000.0, 1.0, None),  # just check it's finite
    (None, 1000.0, 1.0, None),
    (25.0, None, 1.0, None),
    (None, None, 1.0, None),
]


def test_miami_npp_returns_none_for_missing_inputs() -> None:
    assert miami_npp(None, 1000.0) is None
    assert miami_npp(25.0, None) is None
    assert miami_npp(None, None) is None


def test_miami_npp_earth_tropical_rainforest() -> None:
    """25 °C, 3000 mm/yr → high NPP."""
    npp = miami_npp(25.0, 3000.0)
    assert npp is not None
    assert 1800.0 <= npp <= 2800.0  # typical tropical rainforest


def test_miami_npp_desert() -> None:
    """30 °C, 100 mm/yr → low NPP."""
    npp = miami_npp(30.0, 100.0)
    assert npp is not None
    assert npp < 300.0


def test_miami_npp_tundra() -> None:
    """-5 °C, 200 mm/yr → temperature-limited, moderate NPP despite low precip."""
    npp = miami_npp(-5.0, 200.0)
    assert npp is not None
    assert npp < 400.0  # temp-limited, not precip-limited at -5°C


def test_miami_npp_temperature_limited() -> None:
    """Cold + wet → temperature-limited (not precip-limited)."""
    npp_t = miami_npp(-3.0, 3000.0)
    npp_p = miami_npp(25.0, 3000.0)
    assert npp_t is not None and npp_p is not None
    assert npp_t < npp_p  # cold limits more than precip


def test_miami_npp_precip_limited() -> None:
    """Hot + dry → precip-limited (30°C, 200mm)."""
    npp = miami_npp(30.0, 200.0)
    assert npp is not None
    # Miami precip: 3000*(1-exp(-0.000664*200)) ≈ 373 gC/m²/yr
    assert 200.0 <= npp <= 400.0


def test_miami_npp_par_ratio() -> None:
    """Half-sunlight → half NPP."""
    npp_full = miami_npp(25.0, 2000.0, par_ratio=1.0)
    npp_half = miami_npp(25.0, 2000.0, par_ratio=0.5)
    assert npp_full is not None and npp_half is not None
    assert math.isclose(npp_half, npp_full * 0.5, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Domesticable tags
# ---------------------------------------------------------------------------


def test_temperate_grassland_high_everything() -> None:
    """Temperate grassland = Diamond's cradle of civilisation."""
    profile = get_domesticable_profile(WhittakerBiome.TEMPERATE_GRASSLAND)
    assert profile.large_herbivores == "high"
    assert profile.staple_crops == "high"
    assert profile.draft_animals == "high"


def test_tropical_rainforest_low_large_herbivores() -> None:
    profile = get_domesticable_profile(WhittakerBiome.TROPICAL_RAINFOREST)
    assert profile.large_herbivores == "low"


def test_desert_low_all() -> None:
    for biome in [
        WhittakerBiome.TROPICAL_DESERT,
        WhittakerBiome.TEMPERATE_DESERT,
        WhittakerBiome.ICE,
    ]:
        profile = get_domesticable_profile(biome)
        assert profile.large_herbivores == "low"
        assert profile.staple_crops == "low"
        assert profile.draft_animals == "low"


def test_domesticable_profile_to_tags() -> None:
    profile = DomesticableProfile("high", "moderate", "low")
    tags = profile.to_tags()
    assert "large_herbivores_high" in tags
    assert "staple_crops_moderate" in tags
    assert "draft_animals_low" in tags


# ---------------------------------------------------------------------------
# Full cell ecology pipeline
# ---------------------------------------------------------------------------


def test_classify_cell_ecology_ocean() -> None:
    result = classify_cell_ecology(15.0, 1000.0, -500.0, is_ocean=True)
    assert result.biome == WhittakerBiome.OCEAN
    # Ocean NPP is None by design: Miami NPP is a terrestrial model;
    # marine NPP depends on upwelling / nutrients / light and will be
    # handled in Phase 3A.5 (Longhurst ocean provinces).
    assert result.npp_gc_m2_yr is None


def test_classify_cell_ecology_land() -> None:
    result = classify_cell_ecology(12.0, 800.0, 200.0, is_ocean=False)
    assert result.biome == WhittakerBiome.TEMPERATE_FOREST
    assert result.npp_gc_m2_yr is not None
    assert len(result.domesticable_tags) >= 3


def test_classify_cell_ecology_missing_climate() -> None:
    """Cells without climate data still get a biome (ocean or unknown)."""
    result = classify_cell_ecology(None, None, 100.0, is_ocean=False)
    # Without temp/precip, defaults to 0.0 → ICE or TUNDRA
    assert result.npp_gc_m2_yr is None
    assert len(result.domesticable_tags) == 3  # always returns tags


# ---------------------------------------------------------------------------
# Soil classification (USDA Soil Taxonomy)
# ---------------------------------------------------------------------------


def test_soil_order_has_all_12_orders() -> None:
    """The SoilOrder enum must contain the complete USDA 12 orders."""
    expected = {
        "gelisol",
        "histosol",
        "spodosol",
        "andisol",
        "oxisol",
        "vertisol",
        "aridisol",
        "ultisol",
        "mollisol",
        "alfisol",
        "inceptisol",
        "entisol",
    }
    assert {s.value for s in SoilOrder} == expected


SOIL_CASES: list[tuple[float | None, float | None, str, bool, str | None, str | None]] = [
    # (T, P, crust_type, is_ocean, expected_soil, expected_fertility)
    # Permafrost / tundra
    (-15.0, 800.0, "continental", False, "gelisol", "low"),
    (-3.0, 300.0, "continental", False, "gelisol", "low"),
    # Arid
    (30.0, 100.0, "continental", False, "aridisol", "low"),
    (20.0, 200.0, "continental", False, "aridisol", "low"),
    # Tropical rainforest → intense weathering
    (28.0, 3000.0, "continental", False, "oxisol", "low"),
    # Tropical strongly leached
    (25.0, 1500.0, "continental", False, "ultisol", "low"),
    # Tropical savanna, dry-wet seasonal
    (30.0, 700.0, "continental", False, "vertisol", "high"),
    # Temperate rainforest → leached
    (12.0, 2000.0, "continental", False, "ultisol", "low"),
    # Temperate forest
    (10.0, 1000.0, "continental", False, "alfisol", "high"),
    # Temperate grassland → fertile breadbasket
    (8.0, 500.0, "continental", False, "mollisol", "high"),
    # Boreal forest
    (3.0, 600.0, "continental", False, "spodosol", "low"),
    # Boreal shrubland
    (1.0, 300.0, "continental", False, "inceptisol", "medium"),
    # Ocean sentinel
    (20.0, 1000.0, "oceanic", False, None, None),
    (20.0, 1000.0, "continental", True, None, None),
    # Missing climate → weakly developed
    (None, None, "continental", False, "inceptisol", "medium"),
]


@pytest.mark.parametrize("t, p, crust, ocean, soil, fertility", SOIL_CASES)
def test_classify_soil(
    t: float | None,
    p: float | None,
    crust: str,
    ocean: bool,
    soil: str | None,
    fertility: str | None,
) -> None:
    assert classify_soil(t, p, 100.0, crust_type=crust, is_ocean=ocean) == (soil, fertility)


def test_classify_soil_transitional_crust_is_not_soil() -> None:
    """Transitional crust (not continental) yields no soil."""
    assert classify_soil(20.0, 1000.0, 100.0, crust_type="transitional") == (None, None)


def test_classify_soil_fertility_gradient() -> None:
    """Mollisols (grassland) are more fertile than Oxisols (rainforest)."""
    _, grassland_fertility = classify_soil(8.0, 500.0, 200.0)
    _, rainforest_fertility = classify_soil(28.0, 3000.0, 200.0)
    assert grassland_fertility == "high"
    assert rainforest_fertility == "low"
