"""Ecology physics — pure functions for Whittaker biome classification, NPP, and
domesticable-species tagging.

All functions are deterministic (no RNG), self-contained (no IO), and unit-testable.
They map from climate outputs (temperature, precipitation) to ecological properties.

References
----------
- Whittaker, R. H. (1975). *Communities and Ecosystems*, 2nd ed. Macmillan.
- Lieth, H. (1975). "Modeling the primary productivity of the world."
  In *Primary Productivity of the Biosphere*, Springer, pp. 237–263.
- Diamond, J. (1997). *Guns, Germs, and Steel*. W. W. Norton.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

# ---------------------------------------------------------------------------
# Biome classification
# ---------------------------------------------------------------------------


class WhittakerBiome(StrEnum):
    """Whittaker biome classes, ordered from wettest to driest within each thermal band."""

    # Tropical (T > 18 °C)
    TROPICAL_RAINFOREST = "tropical_rainforest"
    TROPICAL_SEASONAL_FOREST = "tropical_seasonal_forest"
    TROPICAL_SAVANNA = "tropical_savanna"
    TROPICAL_DESERT = "tropical_desert"

    # Temperate (5 < T <= 18 °C)
    TEMPERATE_RAINFOREST = "temperate_rainforest"
    TEMPERATE_FOREST = "temperate_forest"
    TEMPERATE_GRASSLAND = "temperate_grassland"
    TEMPERATE_DESERT = "temperate_desert"

    # Boreal / cold (T <= 5 °C)
    BOREAL_FOREST = "boreal_forest"
    BOREAL_SHRUBLAND = "boreal_shrubland"
    TUNDRA = "tundra"
    ICE = "ice"

    # Ocean sentinel
    OCEAN = "ocean"


# Whittaker biome lookup table: (thermal_band, precip_range) -> WhittakerBiome
# thermal_band is determined by mean annual temperature (°C).
# precip_range is determined by annual precipitation (mm/yr).

_TROPICAL = (
    (2000.0, WhittakerBiome.TROPICAL_RAINFOREST),
    (1000.0, WhittakerBiome.TROPICAL_SEASONAL_FOREST),
    (400.0, WhittakerBiome.TROPICAL_SAVANNA),
    (0.0, WhittakerBiome.TROPICAL_DESERT),
)

_TEMPERATE = (
    (1500.0, WhittakerBiome.TEMPERATE_RAINFOREST),
    (700.0, WhittakerBiome.TEMPERATE_FOREST),
    (300.0, WhittakerBiome.TEMPERATE_GRASSLAND),
    (0.0, WhittakerBiome.TEMPERATE_DESERT),
)

_BOREAL = (
    (500.0, WhittakerBiome.BOREAL_FOREST),
    (200.0, WhittakerBiome.BOREAL_SHRUBLAND),
    (float("-inf"), WhittakerBiome.TUNDRA),
)


def classify_whittaker_biome(
    temperature_c: float,
    precipitation_mm: float,
    is_ocean: bool = False,
) -> WhittakerBiome:
    """Classify a cell into a Whittaker biome from temperature and precipitation.

    Parameters
    ----------
    temperature_c:
        Mean annual temperature in °C.
    precipitation_mm:
        Annual precipitation in mm.
    is_ocean:
        If ``True``, return ``OCEAN`` regardless of climate values.

    Returns
    -------
    WhittakerBiome
    """
    if is_ocean:
        return WhittakerBiome.OCEAN

    # Select thermal band
    if temperature_c > 18.0:
        band: tuple[tuple[float, WhittakerBiome], ...] = _TROPICAL
    elif temperature_c > 5.0:
        band = _TEMPERATE
    else:
        # Boreal/cold band — ice cap when T <= -10 °C regardless of precip
        if temperature_c <= -10.0:
            return WhittakerBiome.ICE
        band = _BOREAL

    for threshold, biome in band:
        if precipitation_mm > threshold:
            return biome

    # Fallback (should never happen — last threshold catches everything)
    return band[-1][1]


# ---------------------------------------------------------------------------
# Net Primary Productivity (Miami model)
# ---------------------------------------------------------------------------


#: Scaling factor applied to NPP for non-solar-standard stars.
#: The Miami model was calibrated for Earth's solar constant.
#: For stars with very different luminosities, multiply by PAR_ratio = (S / S_earth).
#: This is applied at the engine level, not in the pure function.


def miami_npp(
    temperature_c: float | None,
    precipitation_mm: float | None,
    *,
    par_ratio: float = 1.0,
) -> float | None:
    """Estimate Net Primary Productivity from temperature and precipitation.

    Uses the Miami model (Lieth 1975), which computes two independent limits —
    one from temperature, one from precipitation — and takes the minimum.

    .. math::

        NPP_T &= \\frac{3000}{1 + e^{1.315 - 0.119 T}}
        NPP_P &= 3000 (1 - e^{-0.000664 P})
        NPP   &= \\min(NPP_T, NPP_P)

    Parameters
    ----------
    temperature_c:
        Mean annual temperature in °C.  If ``None``, returns ``None``.
    precipitation_mm:
        Annual precipitation in mm.  If ``None``, returns ``None``.
    par_ratio:
        Photosynthetically-active radiation ratio relative to Earth
        (S / S_earth).  Default 1.0 (Earth-normal).

    Returns
    -------
    NPP in gC / m² / yr, or ``None`` if either input is ``None``.
    """
    if temperature_c is None or precipitation_mm is None:
        return None

    npp_t = 3000.0 / (1.0 + math.exp(1.315 - 0.119 * temperature_c))
    npp_p = 3000.0 * (1.0 - math.exp(-0.000664 * precipitation_mm))
    return min(npp_t, npp_p) * par_ratio


# ---------------------------------------------------------------------------
# Domesticable-species tagging
# ---------------------------------------------------------------------------


class DomesticableTag(StrEnum):
    """Tags describing a cell's potential for domestication."""

    LARGE_HERBIVORES_HIGH = "large_herbivores_high"
    LARGE_HERBIVORES_MODERATE = "large_herbivores_moderate"
    LARGE_HERBIVORES_LOW = "large_herbivores_low"
    STAPLE_CROPS_HIGH = "staple_crops_high"
    STAPLE_CROPS_MODERATE = "staple_crops_moderate"
    STAPLE_CROPS_LOW = "staple_crops_low"
    DRAFT_ANIMALS_HIGH = "draft_animals_high"
    DRAFT_ANIMALS_MODERATE = "draft_animals_moderate"
    DRAFT_ANIMALS_LOW = "draft_animals_low"


@dataclass(frozen=True)
class DomesticableProfile:
    """Domestication potential for a single cell.

    Generated from biome + latitude — purely a rules-based lookup, no RNG.
    """

    large_herbivores: str  # "high" | "moderate" | "low"
    staple_crops: str
    draft_animals: str

    def to_tags(self) -> list[str]:
        """Flatten the profile into a list of ``DomesticableTag`` values."""
        return [
            f"large_herbivores_{self.large_herbivores}",
            f"staple_crops_{self.staple_crops}",
            f"draft_animals_{self.draft_animals}",
        ]


# Biome → domestication profile lookup table.
# Based on Jared Diamond's framework (Guns, Germs, and Steel, 1997) with
# adjustments for non-Earth generalisation:
#   - Tropical rainforests have high NPP but few large domesticable animals
#     (low carbohydrate staple, high disease pressure).
#   - Temperate grasslands are the "cradle of civilisation" — highest scores.
#   - Deserts and ice are effectively uninhabitable.
#   - Boreal forests have low agricultural potential but moderate large game.

_DOMESTICATION_TABLE: dict[WhittakerBiome, DomesticableProfile] = {
    WhittakerBiome.TROPICAL_RAINFOREST: DomesticableProfile("low", "moderate", "low"),
    WhittakerBiome.TROPICAL_SEASONAL_FOREST: DomesticableProfile("moderate", "high", "low"),
    WhittakerBiome.TROPICAL_SAVANNA: DomesticableProfile("high", "moderate", "low"),
    WhittakerBiome.TROPICAL_DESERT: DomesticableProfile("low", "low", "low"),
    WhittakerBiome.TEMPERATE_RAINFOREST: DomesticableProfile("moderate", "moderate", "moderate"),
    WhittakerBiome.TEMPERATE_FOREST: DomesticableProfile("moderate", "high", "moderate"),
    WhittakerBiome.TEMPERATE_GRASSLAND: DomesticableProfile("high", "high", "high"),
    WhittakerBiome.TEMPERATE_DESERT: DomesticableProfile("low", "low", "low"),
    WhittakerBiome.BOREAL_FOREST: DomesticableProfile("moderate", "low", "low"),
    WhittakerBiome.BOREAL_SHRUBLAND: DomesticableProfile("low", "low", "low"),
    WhittakerBiome.TUNDRA: DomesticableProfile("low", "low", "low"),
    WhittakerBiome.ICE: DomesticableProfile("low", "low", "low"),
    WhittakerBiome.OCEAN: DomesticableProfile("low", "low", "low"),
}


def get_domesticable_profile(biome: WhittakerBiome) -> DomesticableProfile:
    """Return the domestication profile for a Whittaker biome."""
    return _DOMESTICATION_TABLE[biome]


# ---------------------------------------------------------------------------
# Batch cell-level classification
# ---------------------------------------------------------------------------


@dataclass
class EcologyCellOutput:
    """Per-cell ecology outputs."""

    biome: WhittakerBiome
    npp_gc_m2_yr: float | None
    domesticable_tags: list[str]


def classify_cell_ecology(
    temperature_c: float | None,
    precipitation_mm: float | None,
    elevation_m: float | None,
    *,
    is_ocean: bool = False,
    par_ratio: float = 1.0,
) -> EcologyCellOutput:
    """Run the full ecology P0 pipeline for a single cell.

    Parameters
    ----------
    temperature_c:
        Mean annual temperature (°C).  ``None`` for cells without climate data.
    precipitation_mm:
        Annual precipitation (mm).  ``None`` for cells without climate data.
    elevation_m:
        Cell elevation in metres (unused in P0, reserved for P1 altitudinal belts).
    is_ocean:
        Whether the cell is ocean (elevation < 0 or crust type oceanic).
    par_ratio:
        PAR scaling factor for non-solar-standard stars.

    Returns
    -------
    EcologyCellOutput
    """
    biome = classify_whittaker_biome(
        temperature_c=temperature_c or 0.0,
        precipitation_mm=precipitation_mm or 0.0,
        is_ocean=is_ocean,
    )
    # Miami NPP is a terrestrial model (T + precipitation); marine NPP depends
    # on upwelling / nutrients / light, not on precipitation over the ocean.
    # Until Phase 3A.5 (Longhurst ocean provinces), ocean cells get None.
    npp = None if is_ocean else miami_npp(temperature_c, precipitation_mm, par_ratio=par_ratio)
    profile = get_domesticable_profile(biome)
    return EcologyCellOutput(
        biome=biome,
        npp_gc_m2_yr=npp,
        domesticable_tags=profile.to_tags(),
    )


# ---------------------------------------------------------------------------
# Soil classification (USDA Soil Taxonomy)
# ---------------------------------------------------------------------------


class SoilOrder(StrEnum):
    """USDA Soil Taxonomy 12 soil orders (complete, not simplified).

    Only 9 of the 12 orders are assigned by the temperature/precipitation
    lookup in :func:`classify_soil`; the remaining three require inputs the
    ecology layer does not yet have and are reserved for later refinement:
    - ``entisol``  — very young soils (steep slopes / new deposits) → needs slope
    - ``histosol`` — organic wetland soils → needs a drainage/wetland flag
    - ``andisol``  — volcanic-ash soils → needs a volcanic-activity flag
    """

    GELISOL = "gelisol"  # permafrost (high lat / altitude)
    HISTOSOL = "histosol"  # organic wetland
    SPODOSOL = "spodosol"  # cool humid acidic, Fe/Al leaching (boreal forest)
    ANDISOL = "andisol"  # volcanic ash
    OXISOL = "oxisol"  # intensely weathered (tropical rainforest)
    VERTISOL = "vertisol"  # shrink-swell clay (dry-wet seasonal)
    ARIDISOL = "aridisol"  # arid (desert)
    ULTISOL = "ultisol"  # warm humid, strongly leached (subtropical)
    MOLLISOL = "mollisol"  # deep organic, fertile (temperate grassland)
    ALFISOL = "alfisol"  # temperate, moderately leached (temperate forest)
    INCEPTISOL = "inceptisol"  # weakly developed
    ENTISOL = "entisol"  # very young (steep slope / new deposit / dune)


class SoilFertility(StrEnum):
    """Coarse soil-fertility grade — the direct agriculture-potential input."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


#: Soil order → fertility grade. Mollisols/Alfisols/Andisols are the breadbaskets;
#: heavily-weathered or frozen soils are poor.
_SOIL_FERTILITY: dict[SoilOrder, SoilFertility] = {
    SoilOrder.MOLLISOL: SoilFertility.HIGH,
    SoilOrder.ALFISOL: SoilFertility.HIGH,
    SoilOrder.VERTISOL: SoilFertility.HIGH,
    SoilOrder.ANDISOL: SoilFertility.HIGH,
    SoilOrder.HISTOSOL: SoilFertility.MEDIUM,
    SoilOrder.INCEPTISOL: SoilFertility.MEDIUM,
    SoilOrder.ENTISOL: SoilFertility.MEDIUM,
    SoilOrder.ULTISOL: SoilFertility.LOW,
    SoilOrder.OXISOL: SoilFertility.LOW,
    SoilOrder.SPODOSOL: SoilFertility.LOW,
    SoilOrder.ARIDISOL: SoilFertility.LOW,
    SoilOrder.GELISOL: SoilFertility.LOW,
}


def classify_soil(
    temperature_c: float | None,
    precipitation_mm: float | None,
    elevation_m: float | None,
    *,
    crust_type: str = "continental",
    is_ocean: bool = False,
) -> tuple[str | None, str | None]:
    """Classify a cell into a USDA soil order + fertility grade.

    Parent material (crust type) and climate (temperature / precipitation) are
    the primary drivers. ``elevation_m`` is accepted for future wetland/slope
    refinement but is not yet used by the lookup.

    Parameters
    ----------
    temperature_c:
        Mean annual temperature (°C).  ``None`` for cells without climate data.
    precipitation_mm:
        Annual precipitation (mm).  ``None`` for cells without climate data.
    elevation_m:
        Cell elevation in metres (reserved for wetland/slope refinement).
    crust_type:
        Cell crust type; anything other than ``"continental"`` yields ``None``.
    is_ocean:
        If ``True``, returns ``(None, None)`` regardless of other inputs.

    Returns
    -------
    (soil_type, soil_fertility) — both ``None`` for ocean cells.
    """
    if is_ocean or crust_type != "continental":
        return None, None

    if temperature_c is None or precipitation_mm is None:
        # Without climate data fall back to a weakly-developed soil.
        return SoilOrder.INCEPTISOL.value, SoilFertility.MEDIUM.value

    t = temperature_c
    p = precipitation_mm

    if t <= 0.0:
        soil = SoilOrder.GELISOL  # permafrost / tundra
    elif p < 250.0:
        soil = SoilOrder.ARIDISOL  # arid
    elif t > 18.0:  # tropical
        if p >= 2000.0:
            soil = SoilOrder.OXISOL  # rainforest, intense weathering
        elif p >= 1000.0:
            soil = SoilOrder.ULTISOL  # strongly leached
        else:
            soil = SoilOrder.VERTISOL  # savanna, dry-wet seasonal
    elif t > 5.0:  # temperate
        if p >= 1500.0:
            soil = SoilOrder.ULTISOL  # temperate rainforest, leached
        elif p >= 700.0:
            soil = SoilOrder.ALFISOL  # temperate forest
        elif p >= 300.0:
            soil = SoilOrder.MOLLISOL  # grassland — fertile
        else:
            soil = SoilOrder.ARIDISOL
    else:  # boreal / cold (0 < T <= 5)
        if p >= 500.0:
            soil = SoilOrder.SPODOSOL  # boreal forest
        elif p >= 200.0:
            soil = SoilOrder.INCEPTISOL  # boreal shrubland
        else:
            soil = SoilOrder.GELISOL

    return soil.value, _SOIL_FERTILITY[soil].value
