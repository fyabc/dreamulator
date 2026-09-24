"""UCC continuous climate descriptors (ucc-review §4.2 — "freeze semantics").

The first step of UCC-01 is to *freeze the semantics* of a climate sequence
without committing to a classification alphabet: define the time/flux contract
(§4.1) and compute a few independent, complementary *continuous* descriptions
(§4.2).  Classification profiles and their thresholds are a later step (§4.3).

Key review constraints honoured here:

- Time is first: bins carry durations ``dt``; nothing is hard-wired to 12 equal
  "months" (§4.1).  Precipitation is a *rate*, and totals are ``Σ P_i·Δt_i``.
- Missing demand / missing precipitation must NOT drop the other valid fields —
  a field is either ``"valid"`` or carries an applicability status (§4.4).
- ``P=0, Eref>0`` → AI=0; ``P=Eref=0`` → AI undefined; ``P>0, Eref=0`` →
  "no positive reference demand", never an ``inf`` smuggled into a wet class.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Applicability states (§4.4).  A None value is only meaningful when paired with
# a non-``valid`` status — the field is absent/undefined, not the whole record.
VALID = "valid"
MISSING_INPUT = "missing_input"  # e.g. no PET model → AI not computable
NOT_APPLICABLE = "not_applicable"  # e.g. P=Eref=0 → AI undefined
NO_POSITIVE_DEMAND = "no_positive_demand"  # P>0, Eref=0 → not a finite wet/dry ratio
OUT_OF_DOMAIN = "out_of_domain"  # demand model outside its validity domain (see below)

# Canonical status ordering — the uint8 codes embedded in climate_yearly.msgpack
# index into this list; both exporters and the experiment scripts share it.
STATUS_CODES = (VALID, MISSING_INPUT, NOT_APPLICABLE, NO_POSITIVE_DEMAND, OUT_OF_DOMAIN)


@dataclass
class ClimateDescriptors:
    """The continuous descriptions of one climate sequence (§4.2)."""

    # Temperature — duration-weighted over the window.
    t_mean: float  # °C, Σ w_i·t_i
    t_min: float  # °C, min bin-mean
    t_max: float  # °C, max bin-mean
    t_range: float  # °C, t_max − t_min (explicitly a *range*, not half-amplitude)
    t_below_frac: float  # time-fraction of bin means below the threshold (§4.2 note)

    # Precipitation — mean rate and window total.
    p_mean_rate: float  # mean flux over the window
    p_total: float  # Σ P_i·Δt_i

    # Supply–demand: AI = P_total / Eref_total over the *same* window.
    ai: float | None
    ai_status: str

    # Same-period seasonal deficit: Σ max(Eref_i − P_i, 0)·Δt_i / Σ Eref_i·Δt_i.
    deficit: float | None
    deficit_status: str

    # Precipitation concentration C_TV = 0.5 Σ |q_i − w_i| (None when P_total=0).
    concentration: float | None


def compute_descriptors(
    t: np.ndarray,
    p_rate: np.ndarray,
    et_rate: np.ndarray | None = None,
    dt: np.ndarray | None = None,
    *,
    freeze_threshold_c: float = 0.0,
) -> ClimateDescriptors:
    """Compute the continuous descriptors from a climate sequence.

    Args:
        t: (M,) bin-mean temperature (°C).
        p_rate: (M,) precipitation *rate* (mm per unit time) — not cumulative.
        et_rate: (M,) reference-demand *rate* (mm per unit time); None = no PET.
        dt: (M,) positive bin durations; None = equal bins.
        freeze_threshold_c: threshold for the time-fraction-below statistic.

    Returns:
        ClimateDescriptors — undefined fields carry a status and a None value.
    """
    t = np.asarray(t, dtype=np.float64)
    p_rate = np.asarray(p_rate, dtype=np.float64)
    m = t.shape[0]
    dt = np.ones(m, dtype=np.float64) if dt is None else np.asarray(dt, dtype=np.float64)
    if dt.shape != (m,) or p_rate.shape != (m,):
        raise ValueError("t, p_rate, dt must share the same bin count")

    w = dt / dt.sum()  # time weights

    t_mean = float(np.sum(w * t))
    t_min = float(np.min(t))
    t_max = float(np.max(t))
    t_range = t_max - t_min
    t_below_frac = float(np.sum(w[t < freeze_threshold_c]))

    p_total = float(np.sum(p_rate * dt))
    p_mean_rate = float(np.sum(w * p_rate))

    ai, ai_status = _supply_demand(p_rate, et_rate, dt)
    deficit, deficit_status = _seasonal_deficit(p_rate, et_rate, dt)
    concentration = _concentration(p_rate, dt, p_total)

    # Demand-model validity domain (ucc-review §2.3/§4.4): the Hamon reference
    # demand is an empirical formula for evaporation from *liquid* water
    # surfaces.  When no bin-mean temperature reaches the freeze threshold
    # (no liquid water all year — ice-cap climates), the reference demand is
    # undefined in physical terms: Eref collapses toward zero while sublimation
    # physics takes over, and P/Eref inflates into a meaningless "humid" ice
    # sheet.  Mark the supply–demand statistics out-of-domain there instead of
    # reporting a number.  MISSING_INPUT (no PET at all) takes precedence.
    if t_max < freeze_threshold_c:
        if ai_status != MISSING_INPUT:
            ai, ai_status = None, OUT_OF_DOMAIN
        if deficit_status != MISSING_INPUT:
            deficit, deficit_status = None, OUT_OF_DOMAIN

    return ClimateDescriptors(
        t_mean=t_mean,
        t_min=t_min,
        t_max=t_max,
        t_range=t_range,
        t_below_frac=t_below_frac,
        p_mean_rate=p_mean_rate,
        p_total=p_total,
        ai=ai,
        ai_status=ai_status,
        deficit=deficit,
        deficit_status=deficit_status,
        concentration=concentration,
    )


def _supply_demand(
    p_rate: np.ndarray, et_rate: np.ndarray | None, dt: np.ndarray
) -> tuple[float | None, str]:
    p_total = float(np.sum(p_rate * dt))
    if et_rate is None:
        return None, MISSING_INPUT
    et_total = float(np.sum(np.asarray(et_rate, dtype=np.float64) * dt))
    if et_total <= 0.0:
        # P>0, Eref=0 → "no positive demand"; P=Eref=0 → undefined.  Neither is a
        # finite AI; do not smuggle an inf into a wet class (§4.4).
        return None, NO_POSITIVE_DEMAND if p_total > 0.0 else NOT_APPLICABLE
    return p_total / et_total, VALID


def _seasonal_deficit(
    p_rate: np.ndarray, et_rate: np.ndarray | None, dt: np.ndarray
) -> tuple[float | None, str]:
    if et_rate is None:
        return None, MISSING_INPUT
    et_rate = np.asarray(et_rate, dtype=np.float64)
    et_total = float(np.sum(et_rate * dt))
    if et_total <= 0.0:
        return None, NOT_APPLICABLE
    deficit = np.sum(np.maximum(et_rate - p_rate, 0.0) * dt) / et_total
    return float(deficit), VALID


def _concentration(p_rate: np.ndarray, dt: np.ndarray, p_total: float) -> float | None:
    if p_total <= 0.0:
        return None  # undefined when there is no precipitation (§4.2)
    q = p_rate * dt / p_total  # precipitation mass fraction per bin
    w = dt / dt.sum()  # uniform-rate reference
    return float(0.5 * np.sum(np.abs(q - w)))


# ---------------------------------------------------------------------------
# Classification profile v0 (ucc-review §4.3 / §7 第二步; frozen 2026-09-20
# after the L2 candidate comparison — see docs/ucc/research/ucc-l2-classify-2026-09-20.md)
# ---------------------------------------------------------------------------

PROFILE_V0 = "ucc-v0"
"""Frozen classification profile identifier.  Bump on any threshold change.

v0 semantics (all thresholds declared *empirical candidates*, shared across
worlds — never per-world quantiles; §4.3):

- Thermal bands (from bin-mean min/max): ``t_max < 10 °C`` → polar;
  ``t_min < −3 °C`` → cold; ``t_min < 18 °C`` → temperate; else tropical
  (Köppen thermal nodes, evaluated on the descriptors, not on geometry).
- Supply–demand bands (land only): AI < 0.5 → arid; AI < 1.0 → transitional;
  else humid.  Ocean cells carry the thermal band only — the land-oriented
  wet/dry axis is ``not_applicable`` there (§4.4).
- Modifiers (optional, never change the main class): ``continental`` when
  ``t_range ≥ 25 °C``; ``water_stress`` when ``deficit ≥ 0.5``.
- Demand model: hamon-1961 (12 h daylength; declared, not FAO-56-calibrated).
"""

PROFILE_V1 = "ucc-v1"
"""Current classification profile.  v1 = v0 with the arid band split at
AI = 0.2 (arid / semi_arid), separating desert cores from steppe margins —
the evidence (L2 experiments + map readability: ~23 % of land sat in one arid
band, ~51 % of it below AI 0.2) was recorded in the 2026-09-20 L2 comparison
and the split was deferred from v0 to exactly this evaluation point.
Everything else (thermal nodes, modifiers, validity states, demand model) is
unchanged from v0."""

T_NODE_POLAR_C_V0 = 10.0
T_NODE_COLD_C_V0 = -3.0
T_NODE_TROPICAL_C_V0 = 18.0
AI_EDGES_V0 = (0.5, 1.0)
AI_EDGES_V1 = (0.2, 0.5, 1.0)
MOD_T_RANGE_C_V0 = 25.0
MOD_DEFICIT_V0 = 0.5

THERMAL_BANDS_V0 = ("polar", "cold", "temperate", "tropical")
SUPPLY_BANDS_V0 = ("arid", "transitional", "humid")
SUPPLY_BANDS_V1 = ("arid", "semi_arid", "transitional", "humid")

#: The profile current exports are written with.
PROFILE_CURRENT = PROFILE_V1
THERMAL_BANDS_CURRENT = THERMAL_BANDS_V0
SUPPLY_BANDS_CURRENT = SUPPLY_BANDS_V1

# Compact display codes (the profile's short alphabet, versioned with it).
# Letters + hyphen only — speakable and safe in URLs/shells/filenames.
# Thermal: one uppercase letter; supply: one lowercase letter, ``o`` for the
# ocean slot and ``n`` for land whose supply axis is not applicable (ice caps
# out of the demand model's domain, missing PET, …; the status field carries
# the reason) — a bare thermal letter never occurs.  Modifiers append after a
# hyphen: ``x`` continental, ``w`` water_stress (combinable: ``-xw``).  The
# codes are self-namespaced — they are NOT Köppen letters ("Cs" here is
# cold·semi-arid, not Köppen's temperate dry-summer).
THERMAL_CODE_LETTERS = {"polar": "P", "cold": "C", "temperate": "T", "tropical": "R"}
SUPPLY_CODE_LETTERS = {"arid": "a", "semi_arid": "s", "transitional": "t", "humid": "h"}
OCEAN_CODE_LETTER = "o"
LAND_NA_CODE_LETTER = "n"
MOD_CODE_LETTERS = {"continental": "x", "water_stress": "w"}

# Short display forms for the applicability statuses (§3) — for table cells in
# worked-example / fixture docs where the full snake_case name is too wide.
# ``valid`` needs no short form (the numeric value is shown instead), so it is
# absent here and ``status_short`` falls back to the input for anything unmapped.
STATUS_SHORT_CODES = {
    MISSING_INPUT: "MI",
    NOT_APPLICABLE: "NA",
    NO_POSITIVE_DEMAND: "NPD",
    OUT_OF_DOMAIN: "OOD",
}


def status_short(status: str) -> str:
    """Compact display form of an applicability status (see STATUS_SHORT_CODES).

    Unknown / ``valid`` statuses pass through unchanged, so callers can apply it
    unconditionally and pair it with a legend in the document header.
    """
    return STATUS_SHORT_CODES.get(status, status)


@dataclass(frozen=True)
class UCCClassV0:
    """One cell's classification under a frozen profile (v0/v1 share the record).

    ``supply``/``water_stress`` are None with a non-``valid`` status when the
    supply–demand axis does not apply (ocean, missing PET, undefined AI) —
    partial validity, mirroring the descriptor contract (§4.4).
    """

    profile: str
    thermal: str  # one of THERMAL_BANDS_V0
    supply: str | None  # one of the profile's supply bands, or None
    supply_status: str
    is_land: bool  # ocean cells never carry a supply grade
    continental: bool  # t_range ≥ MOD_T_RANGE_C_V0
    water_stress: bool | None  # deficit ≥ MOD_DEFICIT_V0, or None

    @property
    def label(self) -> str:
        """Human-readable main class, e.g. ``temperate/arid`` or ``polar``."""
        return self.thermal if self.supply is None else f"{self.thermal}/{self.supply}"

    @property
    def code(self) -> str:
        """Compact display code, e.g. ``Ta``, ``Rh``, ``Cs-xw``, ``Pn``, ``Ro``.

        Supply ``o`` marks ocean; land without a valid supply axis gets ``n``
        (the status field carries the reason) — a bare thermal letter never
        occurs, so ``P`` alone cannot be misread as "unclassified".
        """
        if self.supply is not None:
            s = SUPPLY_CODE_LETTERS[self.supply]
        else:
            s = LAND_NA_CODE_LETTER if self.is_land else OCEAN_CODE_LETTER
        code = THERMAL_CODE_LETTERS[self.thermal] + s
        mods = ""
        if self.continental:
            mods += MOD_CODE_LETTERS["continental"]
        if self.water_stress:
            mods += MOD_CODE_LETTERS["water_stress"]
        return code + ("-" + mods if mods else "")


def _classify(
    d: ClimateDescriptors,
    *,
    is_land: bool,
    ai_edges: tuple[float, ...],
    supply_bands: tuple[str, ...],
    profile: str,
) -> UCCClassV0:
    """Shared classification core: thermal nodes + AI digitize + modifiers."""
    if d.t_max < T_NODE_POLAR_C_V0:
        thermal = THERMAL_BANDS_V0[0]
    elif d.t_min < T_NODE_COLD_C_V0:
        thermal = THERMAL_BANDS_V0[1]
    elif d.t_min < T_NODE_TROPICAL_C_V0:
        thermal = THERMAL_BANDS_V0[2]
    else:
        thermal = THERMAL_BANDS_V0[3]

    supply: str | None = None
    supply_status = NOT_APPLICABLE
    if is_land:
        supply_status = d.ai_status
        if d.ai_status == VALID and d.ai is not None:
            band = 0
            for edge in ai_edges:
                if d.ai >= edge:
                    band += 1
            supply = supply_bands[band]

    water_stress: bool | None = None
    if is_land and d.deficit_status == VALID and d.deficit is not None:
        water_stress = d.deficit >= MOD_DEFICIT_V0

    return UCCClassV0(
        profile=profile,
        thermal=thermal,
        supply=supply,
        supply_status=supply_status,
        is_land=is_land,
        continental=d.t_range >= MOD_T_RANGE_C_V0,
        water_stress=water_stress,
    )


def classify_v0(d: ClimateDescriptors, *, is_land: bool) -> UCCClassV0:
    """Classify under the frozen profile v0 (kept for reproducibility)."""
    return _classify(
        d, is_land=is_land, ai_edges=AI_EDGES_V0, supply_bands=SUPPLY_BANDS_V0, profile=PROFILE_V0
    )


def classify_v1(d: ClimateDescriptors, *, is_land: bool) -> UCCClassV0:
    """Classify under profile v1 (= v0 + arid split at AI 0.2) — the current
    export profile."""
    return _classify(
        d, is_land=is_land, ai_edges=AI_EDGES_V1, supply_bands=SUPPLY_BANDS_V1, profile=PROFILE_V1
    )
