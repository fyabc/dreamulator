"""Habitability & agriculture classification — pure functions for the civilization
layer's two derived maps (宜居海岸 / 农业核心区).

All functions are deterministic (no RNG), self-contained (no IO), and unit-testable.
They map climate outputs (temperature, precipitation, distance-to-coast) to two
independent land-suitability booleans that distinguish the *settle* line from the
*farm* line (roadmap §七 "文明宜居/农业图层"):

- ``habitable_coast`` (宜居海岸)  — settleable: annual T > 0 °C, annual P > 500 mm,
  and within a coastal distance threshold.  This deliberately INCLUDES cool-wet
  oceanic ET (Faroese / Inuit-type) — liveable, but too cold for trees or crops.
- ``agricultural_core`` (农业核心区) — farmable: hottest-month T > 10 °C, the
  Köppen C/D tree-line.  Trees and staple crops need at least one month above
  10 °C to complete their growth cycle.

The two lines are independent and partially overlap.  A coastal warm-wet cell is
both habitable and agricultural (the civilisation "cradle"); a cool-wet coastal
cell is habitable but not agricultural; an inland warm cell is agricultural but
not coastal-habitable.  See ``docs/knowledge/climatology/energy_balance.md`` §5.

References
----------
- Köppen, W. (1936). "Das geographische System der Klimate." *Handbuch der
  Klimatologie* (the 10 °C warm-month tree-line separating C/D from E polar).
- Peel, M. C., Finlayson, B. L., & McMahon, T. A. (2007). "Updated world map of
  the Köppen–Geiger climate classification." *Hydrol. Earth Syst. Sci.* 11:1633.
- Xu, C., Kohler, T. A., Lenton, T. M., Svenning, J.-C., & Scheffer, M. (2020).
  "Future of the human climate niche." *PNAS* 117(21):11350–11355.
- McMaster, G. S., & Wilhelm, W. W. (1997). "Growing degree-days: one equation,
  two interpretations." *Agricultural and Forest Meteorology* 87(4):291–300.
- Small, C., & Nicholls, R. J. (2003). "A global analysis of human settlement in
  coastal zones." *Journal of Coastal Research* 19(3):584–599.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Thresholds (physical where possible; settlement heuristics follow the roadmap)
# ---------------------------------------------------------------------------

#: Annual-mean temperature below which permanent settlement is not viable
#: (permafrost / too cold).  Roadmap spec ("年均温 >0°C").  Conservative relative
#: to Earth's northernmost settlements (Fairbanks AK ~−2.7 °C), intentionally
#: marking only *comfortably* habitable coast.
T_MIN_C: float = 0.0

#: Annual precipitation below which rain-fed settlement fails (~semi-arid
#: boundary; below this a settlement needs irrigation).  Roadmap spec ("降水 >500mm").
P_MIN_MM: float = 500.0

#: Coastal-access threshold (km) for the "宜居海岸" layer.  Settlement heuristic:
#: ~40% of humanity lives within 100 km of a coast and a large majority within
#: 200 km; the value is deliberately generous to capture the maritime-moderated
#: coastal fringe (cf. seasonal heat-capacity ``coastal_scale_km=500``).
COAST_THRESHOLD_KM: float = 200.0

#: Hottest-month mean temperature separating tree/crop climates (Köppen C/D)
#: from polar climates (E).  Physically grounded — the 10 °C warm-month isotherm
#: is the standard tree-line (Köppen 1936; Peel et al. 2007).
TREE_LINE_C: float = 10.0


def classify_habitable_coast(
    temperature_c: float | None,
    precipitation_mm: float | None,
    distance_to_coast_km: float | None,
    *,
    is_ocean: bool = False,
    t_min_c: float = T_MIN_C,
    p_min_mm: float = P_MIN_MM,
    coast_threshold_km: float = COAST_THRESHOLD_KM,
) -> bool:
    """Classify a cell as habitable coast (宜居海岸).

    A land cell is settleable when all three hold:
        annual mean T > ``t_min_c`` (above freezing),
        annual P > ``p_min_mm`` (rain-fed), and
        distance to coast ≤ ``coast_threshold_km`` (coastal access).

    Ocean cells and cells missing any input are ``False``.

    Parameters
    ----------
    temperature_c:
        Mean annual temperature (°C).  ``None`` → ``False``.
    precipitation_mm:
        Annual precipitation (mm).  ``None`` → ``False``.
    distance_to_coast_km:
        Distance to nearest ocean (km).  ``None`` → ``False`` (treated as interior).
    is_ocean:
        If ``True``, returns ``False`` regardless of inputs.
    t_min_c, p_min_mm, coast_threshold_km:
        Threshold overrides (defaults are the roadmap-spec values).

    Returns
    -------
    bool
    """
    if is_ocean:
        return False
    if temperature_c is None or precipitation_mm is None or distance_to_coast_km is None:
        return False
    return (
        temperature_c > t_min_c
        and precipitation_mm > p_min_mm
        and distance_to_coast_km <= coast_threshold_km
    )


def classify_agricultural_core(
    temperature_hottest_month_c: float | None,
    *,
    is_ocean: bool = False,
    tree_line_c: float = TREE_LINE_C,
) -> bool:
    """Classify a cell as agricultural core (农业核心区).

    A land cell can support trees and staple crops when its hottest-month mean
    temperature exceeds the Köppen C/D tree-line (``tree_line_c`` = 10 °C).
    This is independent of the habitable-coast layer: a cool-wet coastal ET
    (Faroese/Inuit-type) is habitable but NOT agricultural because its warm
    month stays below the tree-line.

    Ocean cells and cells missing the warm-month temperature are ``False``.

    Parameters
    ----------
    temperature_hottest_month_c:
        Hottest-month mean temperature (°C).  ``None`` → ``False``.
    is_ocean:
        If ``True``, returns ``False`` regardless of inputs.
    tree_line_c:
        Warm-month tree-line threshold override (default 10 °C).

    Returns
    -------
    bool
    """
    if is_ocean or temperature_hottest_month_c is None:
        return False
    return temperature_hottest_month_c > tree_line_c


# ---------------------------------------------------------------------------
# Graded suitability scores (0–100) — the continuous counterpart to the booleans
# above.  The booleans feed summary counts and seed-region thresholding; the
# scores drive the frontend's progressive colour ramps, giving much better
# discrimination on warm-wet worlds where the hard thresholds are nearly
# everywhere satisfied.
# ---------------------------------------------------------------------------

#: Human climate niche centre (°C) — the MAT mode humans historically clustered
#: around (Xu et al. 2020, PNAS).
NICHE_CENTER_C: float = 13.0
#: Cold-side niche half-width (°C) — the niche declines steeply toward the poles.
NICHE_COLD_SIGMA_C: float = 6.0
#: Hot-side niche half-width (°C) — gentler decline (a secondary tropical cluster
#: at 20–25 °C makes the hot side much wider).
NICHE_HOT_SIGMA_C: float = 18.0

#: Agriculture: water-sufficiency (mm) above which f_water saturates — a P-only
#: proxy for the aridity index (P/PET with PET ≈ 1000 mm in warm climates).
AGRI_P_SUFFICIENT_MM: float = 1000.0
#: Agriculture: thermal ramp (°C above the tree-line to reach full grade) — a
#: monthly-resolution proxy for growing degree-days (GDD, base 10 °C).
AGRI_T_FULL_C: float = 15.0

#: Soil fertility → agricultural weight (mollisols/alfisols = breadbasket).
FERTILITY_WEIGHT: dict[str, float] = {"high": 1.0, "medium": 0.5, "low": 0.25}


def _climate_niche(t: float) -> float:
    """Asymmetric human-climate-niche factor peaking at ~13 °C MAT (Xu et al. 2020).

    Steep decline on the cold side (few people below ~10 °C MAT), gentle decline
    on the hot side (a secondary tropical cluster at 20–25 °C keeps it wide).
    """
    sigma = NICHE_COLD_SIGMA_C if t <= NICHE_CENTER_C else NICHE_HOT_SIGMA_C
    return math.exp(-0.5 * ((t - NICHE_CENTER_C) / sigma) ** 2)


def habitability_score(
    temperature_c: float | None,
    precipitation_mm: float | None,
    *,
    is_ocean: bool = False,
) -> float:
    """Graded settleability 0–100 (宜居等级).

    A climate-based suitability index (the human climate niche is defined by
    temperature and water, not by coastal access — Xu et al. 2020):

        f_T (thermal niche band) × f_P (aridity ramp).

    - f_T is an asymmetric band peaking ~13 °C MAT (Xu et al. 2020): steep cold
      side, gentle hot side (secondary tropical cluster).
    - f_P = min(1, P / 500 mm) — rain-fed settlement's water floor.

    Coastal access is intentionally NOT a factor here: it is an economic/trade
    advantage (Small & Nicholls 2003 describes *where* people concentrate, not a
    settleability limit) and is captured separately by ``distance_to_coast_km``.
    """
    if is_ocean or temperature_c is None or precipitation_mm is None:
        return 0.0
    f_t = _climate_niche(temperature_c)
    f_p = min(1.0, precipitation_mm / P_MIN_MM)
    return 100.0 * f_t * f_p


def agriculture_score(
    temperature_hottest_month_c: float | None,
    precipitation_mm: float | None,
    soil_fertility: str | None,
    *,
    is_ocean: bool = False,
) -> float:
    """Graded agricultural suitability 0–100 (农业等级).

    Hard zero below the Köppen C/D tree-line (``t_hot ≤ 10 °C`` — the 10 °C
    warm-month isotherm, Köppen 1936 / Peel et al. 2007).  Above it, the grade
    is a product of:

    - f_thermal — a monthly-resolution growing-degree-day proxy (GDD base 10 °C,
      McMaster & Wilhelm 1997);
    - f_water — a P-only aridity proxy; and
    - f_soil — a soil-fertility weight (USDA taxonomy grading).

    This preserves the "Faroese-type is liveable but not farmable" distinction
    while grading how *good* the farmable land actually is.
    """
    if is_ocean or temperature_hottest_month_c is None:
        return 0.0
    if temperature_hottest_month_c <= TREE_LINE_C:
        return 0.0
    f_thermal = min(1.0, (temperature_hottest_month_c - TREE_LINE_C) / AGRI_T_FULL_C)
    f_water = min(1.0, (precipitation_mm or 0.0) / AGRI_P_SUFFICIENT_MM)
    f_soil = FERTILITY_WEIGHT.get(soil_fertility or "", 0.5)
    return 100.0 * f_thermal * f_water * f_soil
