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

    # Seasonal-shape harmonics of the precipitation mass over circular time
    # (v2-α candidates).  q_j = P_j·Δt_j / P_total, φ_j = bin-centre phase
    # (2π·cumulative-time fraction).  ``p_harmonic1`` = |Σ q_j e^{iφ_j}| —
    # unimodal concentration (≈1 when all rain falls in one season, ≈1/M for
    # uniform rain); ``p_harmonic2`` = |Σ q_j e^{2iφ_j}| — half-period
    # (two-season) concentration.  ``p_harmonic2 > p_harmonic1`` marks a
    # bimodal regime (e.g. equinox double wet seasons), which C_TV and its
    # single-number kin cannot distinguish from unimodal.  None when P_total=0.
    p_harmonic1: float | None = None
    p_harmonic2: float | None = None

    # Rain–demand phase: signed circular phase difference between the
    # precipitation mass and the reference-demand mass, as a fraction of the
    # seasonal cycle in (−0.5, 0.5] — 0 = rain peaks with demand (monsoon-like
    # 雨热同季), ±0.5 = rain peaks half a cycle away from demand
    # (Mediterranean-like 雨热反季).  Partial validity (``p_phase_status``):
    # missing_input without a demand series; not_applicable when either axis
    # has no dominant seasonal cycle (first-harmonic amplitude below
    # PHASE_CONCENTRATION_GATE) — a constant-temperature world can still have
    # a precipitation season (§7.1), it just cannot be in/out of phase with
    # demand; out_of_domain inherits the demand-model domain gates.
    p_phase: float | None = None
    p_phase_status: str = MISSING_INPUT


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

    # Seasonal shape / phase (v2-α): circular bin-centre phases weighted by dt.
    cum = np.cumsum(dt) - 0.5 * dt
    phi = 2.0 * np.pi * cum / dt.sum()
    p_harmonic1: float | None = None
    p_harmonic2: float | None = None
    if p_total > 0.0:
        q_p = p_rate * dt / p_total
        p_harmonic1 = float(np.abs(np.sum(q_p * np.exp(1j * phi))))
        p_harmonic2 = float(np.abs(np.sum(q_p * np.exp(2j * phi))))
    p_phase, p_phase_status = _p_phase(p_rate, et_rate, dt, p_total, phi, p_harmonic1)

    # Demand-model validity domain (ucc-review §2.3/§4.4): the Hamon reference
    # demand is an empirical formula for evaporation from *liquid* water
    # surfaces.  Cold side: when no bin-mean temperature reaches the freeze
    # threshold (no liquid water all year — ice-cap climates), the reference
    # demand is undefined in physical terms: Eref collapses toward zero while
    # sublimation physics takes over, and P/Eref inflates into a meaningless
    # "humid" ice sheet.  Hot side (v2-α gate, symmetric with the cold one):
    # when no bin-mean temperature falls below HOT_DOMAIN_GATE_C, the whole
    # year sits beyond the hottest Earth monthly means (~36 °C) — the formula
    # is pure arithmetic extrapolation there with no calibration anchor
    # (declared empirical candidate; Venus flips Ra-w → Rn under it).
    # MISSING_INPUT (no PET at all) takes precedence over both gates.
    if t_max < freeze_threshold_c or t_min > HOT_DOMAIN_GATE_C:
        if ai_status != MISSING_INPUT:
            ai, ai_status = None, OUT_OF_DOMAIN
        if deficit_status != MISSING_INPUT:
            deficit, deficit_status = None, OUT_OF_DOMAIN
        if p_phase_status != MISSING_INPUT:
            p_phase, p_phase_status = None, OUT_OF_DOMAIN

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
        p_harmonic1=p_harmonic1,
        p_harmonic2=p_harmonic2,
        p_phase=p_phase,
        p_phase_status=p_phase_status,
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


#: Gate on the first-harmonic amplitude below which an axis has no dominant
#: seasonal cycle, so a phase between the two axes is not well defined.
#: Uniform over M=12 bins gives 1/12 ≈ 0.083; a declared empirical candidate
#: (calibrated against the L2 observation set in the v2-α experiment).
PHASE_CONCENTRATION_GATE = 0.25

#: Hot-side domain gate for the reference-demand model (v2-α): when *no*
#: bin-mean temperature falls below this value, the whole year is hotter than
#: any Earth monthly mean (~36 °C, e.g. Assab in the earth worked examples
#: peaks at t_max = 34.5 °C), i.e. beyond the Hamon formula's calibration
#: envelope — declared empirical candidate, same epistemic category as the
#: cold-side freeze rule.
HOT_DOMAIN_GATE_C = 35.0

#: World-level climate-state vocabulary (axis F — taxonomy §6.2, evidence A).
#: A *world-archive declaration*, not a per-cell axis: it names the bulk
#: regime the cell-level classes live inside, which is the first root cause
#: of the homogeneous solar-body maps (Venus is all-`An` *because* it is a
#: runaway greenhouse; Mars is all-`Pn` because it is a thin cold CO2
#: regime).  Assigned by whoever writes the file — solar importers state a
#: literature fact, engine worlds carry the declared default — travels with
#: provenance, and never touches the cell-level shared thresholds (the
#: plan/archive separation principle).  Open-ended vocabulary: new states are
#: added by declaration and documented here, not by a profile bump.
CLIMATE_STATES = (
    "temperate",  # Earth-like N2–H2O hydrology (earth obs, engine default)
    "runaway_greenhouse",  # Venus (Wolf 2017 / Goldblatt 2015 lineage)
    "thin_co2_cold",  # Mars (p ∼ 6 hPa, CO2, cold — Haberle 2001 domain)
    "methane_hydrology",  # Titan (Schneider 2012 methane cycle)
    "airless",  # Moon / Mercury-type (no atmosphere, no lapse rate)
)


def _p_phase(
    p_rate: np.ndarray,
    et_rate: np.ndarray | None,
    dt: np.ndarray,
    p_total: float,
    phi: np.ndarray,
    p_harmonic1: float | None,
) -> tuple[float | None, str]:
    """Signed rain–demand phase (fraction of the seasonal cycle, (−0.5, 0.5])."""
    if et_rate is None:
        return None, MISSING_INPUT
    et_rate = np.asarray(et_rate, dtype=np.float64)
    et_total = float(np.sum(et_rate * dt))
    if p_total <= 0.0 or et_total <= 0.0:
        return None, NOT_APPLICABLE
    if p_harmonic1 is None or p_harmonic1 < PHASE_CONCENTRATION_GATE:
        return None, NOT_APPLICABLE
    q_e = et_rate * dt / et_total
    r1_e = float(np.abs(np.sum(q_e * np.exp(1j * phi))))
    if r1_e < PHASE_CONCENTRATION_GATE:
        return None, NOT_APPLICABLE
    q_p = p_rate * dt / p_total
    arg_p = np.angle(np.sum(q_p * np.exp(1j * phi)))
    arg_e = np.angle(np.sum(q_e * np.exp(1j * phi)))
    delta = (arg_p - arg_e) / (2.0 * np.pi)
    # wrap into (−0.5, 0.5]
    delta = (delta + 0.5) % 1.0 - 0.5
    if delta == -0.5:
        delta = 0.5
    return float(delta), VALID


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


def _thermal_band_for_extremes(t_max: float, t_min: float) -> str:
    """Thermal band from bin-extreme temperatures (the v0 node ladder).

    Shared by the main classification path and the sea-level reduction check
    of the v2 highland modifier — both must answer "which band do these
    extremes fall in" with the same thresholds.
    """
    if t_max < T_NODE_POLAR_C_V0:
        return THERMAL_BANDS_V0[0]
    if t_min < T_NODE_COLD_C_V0:
        return THERMAL_BANDS_V0[1]
    if t_min < T_NODE_TROPICAL_C_V0:
        return THERMAL_BANDS_V0[2]
    return THERMAL_BANDS_V0[3]


def _classify(
    d: ClimateDescriptors,
    *,
    is_land: bool,
    ai_edges: tuple[float, ...],
    supply_bands: tuple[str, ...],
    profile: str,
) -> UCCClassV0:
    """Shared classification core: thermal nodes + AI digitize + modifiers."""
    thermal = _thermal_band_for_extremes(d.t_max, d.t_min)

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
    """Classify under profile v1 (= v0 + arid split at AI 0.2) — kept for
    reproducibility alongside v0."""
    return _classify(
        d, is_land=is_land, ai_edges=AI_EDGES_V1, supply_bands=SUPPLY_BANDS_V1, profile=PROFILE_V1
    )


# ---------------------------------------------------------------------------
# Classification profile v2 (ucc-v2, frozen 2026-10-04 after the seasonality
# L2 ablation — private/reviews/ucc-v2-seasonality-l2-2026-10-04.py)
# ---------------------------------------------------------------------------

PROFILE_V2 = "ucc-v2"
"""Current profile.  v2 = v1's band structure + the seasonality suffix letters
+ the reworked display alphabet:

- Main classes and thresholds are unchanged from v1 (thermal nodes 10/−3/18 °C,
  AI edges 0.2/0.5/1.0, modifier gates t_range 25 °C / deficit 0.5).
- Alphabet rework (breaking, sanctioned by the 2026-09-24 no-compat ruling):
  thermal letters follow Köppen's direction — ``A`` tropical (hottest) …
  ``E`` polar (coldest) — with ``B`` permanently reserved-blank (Köppen's B is
  the dry group; in UCC dryness lives on the lowercase supply axis, so a
  thermal ``B`` would be a standing misread trap and is never issued).
- Supply letters: ``a`` arid / ``p`` semi-arid (stePpe — echoing Köppen BS's
  *concept* in a non-colliding glyph) / ``t`` transitional / ``u`` humid.
  ``s`` and ``h`` are retired: with v2's thermal C meaning temperate (same as
  Köppen), a UCC ``Cs`` (temperate·semi-arid) would read as a near-synonym of
  Köppen ``Cs`` (temperate·dry-summer); ``h`` doubled as the in-phase suffix
  letter and echoed Köppen's *hot* (BWh) against our humid.  Bonus:
  a < p < t < u ascends the alphabet with wetness, so legends read monotone.
- Modifiers: continental → ``l`` (陆, replaces ``x`` — x is the wildcard
  convention in climate-classification practice and must not be a formal
  letter); water_stress → ``g`` (干季, replaces ``w`` to stop the echo of
  Köppen's winter-dry ``w``), display name 干季/seasonal dry; highland →
  ``H`` (uppercase, Köppen/Trewartha pedigree — design-anchors §3.7): fires
  when the sea-level-reduced thermal band differs from the actual one, i.e.
  the cell's band is *elevation-made* rather than latitude-made.  Parameter-
  gated (needs cell elevation + a declared lapse rate; airless worlds carry
  no lapse rate, so the modifier is not applicable there).  Cause marker
  only — never changes the main class.
- Suffix zones (never change the main class; hyphen-separated, each headed
  by an uppercase letter — see the ZONE registry and ``parse_ucc_code``):
  - ``S`` seasonality — followers ``l``/``g`` (the modifiers above), then
    precipitation-season shape (gate C_TV ≥ 0.25): ``m`` unimodal wet season /
    ``d`` bimodal (two wet seasons half a cycle apart, R2 > R1; below the gate
    the letter is silent — "u"-niform is the default, not printed), then
    rain–demand phase (valid only where both axes carry a dominant seasonal
    cycle — an extratropical instrument; see the phase descriptor): ``h``
    in-phase (|Δφ| ≤ 1/12 cycle, 雨热同季) / ``o`` anti-phase (|Δφ| ≥ 3/12,
    雨热反季, Mediterranean-type; mid-range and not-applicable are silent).
  - ``H`` altitude — the highland zone above (no followers yet).
- Evidence: shape letter compresses within-class C_TV variance by 65.7 %
  (v1 modifier benchmarks: x 42 %, w 14 %); phase letter recovers Köppen's
  precipitation letters almost perfectly (w→98.7 % h, s→61 % o); perturbation
  swap-rate cost +0.03 pp.
"""

THERMAL_CODE_LETTERS_V2 = {"tropical": "A", "temperate": "C", "cold": "D", "polar": "E"}
#: v2 supply letters (a/p/t/u, alphabetically ascending with wetness).  The
#: v1 map above stays for v0/v1 reproducibility — their codes never change.
SUPPLY_CODE_LETTERS_V2 = {"arid": "a", "semi_arid": "p", "transitional": "t", "humid": "u"}
MOD_CODE_LETTERS_V2 = {"continental": "l", "water_stress": "g"}
#: Zone grammar (specification §5.4): the suffix is a sequence of
#: hyphen-separated *zones*, each headed by an uppercase letter whose
#: lowercase followers are scoped to the zone (letters may repeat across
#: zones without ambiguity).  Registry, in canonical order:
#: - ``S`` seasonality — followers l g (modifiers), then m/d (wet-season
#:   shape), then h/o (rain–demand phase);
#: - ``H`` altitude/pressure — no followers yet (a future triple-point /
#:   pressure marker would land here).
#: ``B`` is globally retired (the Köppen-B misread trap applies to the whole
#: code, not just the thermal slot).
ZONE_HEAD_SEASONALITY = "S"
ZONE_HEAD_HIGHLAND = "H"
#: Canonical within-zone order for the seasonality followers, as ranks:
#: strictly increasing ranks = a well-formed zone (m and d share a rank, so
#: both cannot appear; same for h and o).
_SEASONALITY_FOLLOWER_RANKS = {"l": 0, "g": 1, "m": 2, "d": 2, "h": 3, "o": 3}
SHAPE_CODE_LETTERS_V2 = {"unimodal": "m", "bimodal": "d"}
PHASE_CODE_LETTERS_V2 = {"in_phase": "h", "anti_phase": "o"}
#: C_TV gate for the shape letter (declared empirical candidate; L2 scan
#: 0.15/0.20/0.25 → 0.25 wins compression and matches the phase gate).
SHAPE_GATE_C_TV_V2 = 0.25
PHASE_LETTER_IN_CYCLE = 1.0 / 12.0
PHASE_LETTER_ANTI_CYCLE = 3.0 / 12.0

PROFILE_CURRENT = PROFILE_V2
THERMAL_BANDS_CURRENT = THERMAL_BANDS_V0
SUPPLY_BANDS_CURRENT = SUPPLY_BANDS_V1
THERMAL_CODE_LETTERS_CURRENT = THERMAL_CODE_LETTERS_V2
MOD_CODE_LETTERS_CURRENT = MOD_CODE_LETTERS_V2


@dataclass(frozen=True)
class UCCClassV2:
    """One cell's classification under profile v2.

    Same main-class semantics as v1 (thermal/supply bands, modifier gates);
    adds the seasonality suffixes ``shape`` (unimodal/bimodal wet season, None
    when C_TV is below the gate) and ``phase`` (in_phase/anti_phase, None when
    the phase descriptor is not valid or mid-range), plus the ``highland``
    modifier (elevation-made band, parameter-gated).  Like the other
    modifiers, none of these ever change the main class.
    """

    profile: str
    thermal: str
    supply: str | None
    supply_status: str
    is_land: bool
    continental: bool
    water_stress: bool | None
    shape: str | None = None
    phase: str | None = None
    #: -H (design-anchors §3.7): True when reducing the bin extremes to sea
    #: level with the declared lapse rate moves the cell to a *different*
    #: thermal band — the band is elevation-made.  False when no elevation /
    #: lapse rate was supplied (airless worlds: no lapse rate exists) as well
    #: as when the reduction leaves the band unchanged.
    highland: bool = False

    @property
    def label(self) -> str:
        return self.thermal if self.supply is None else f"{self.thermal}/{self.supply}"

    @property
    def code(self) -> str:
        """Compact v2 code (zone grammar, §5.4), e.g. ``Dp-Slgmo-H`` (cold·
        semi-arid, seasonality zone fully lit, elevation-made band), ``An``
        (hot-side OOD Venus), ``Eo`` (polar ocean).  Silent zones are simply
        absent, so codes stay compact."""
        return UCCCodeParts(
            thermal=self.thermal,
            supply=self.supply,
            slot=None
            if self.supply is not None
            else (LAND_NA_CODE_LETTER if self.is_land else OCEAN_CODE_LETTER),
            continental=self.continental,
            water_stress=bool(self.water_stress),
            shape=self.shape,
            phase=self.phase,
            highland=self.highland,
        ).render()


def classify_v2(
    d: ClimateDescriptors,
    *,
    is_land: bool,
    elevation_m: float | None = None,
    lapse_rate_c_per_km: float | None = None,
) -> UCCClassV2:
    """Classify under profile v2 (v1 band structure + seasonality letters).

    ``elevation_m`` + ``lapse_rate_c_per_km`` (both or neither) enable the
    ``-H`` highland modifier: the bin extremes are reduced to sea level with
    the declared lapse rate, and a band change marks an elevation-made band.
    The lapse rate is a *world-level declared quantity* (epistemology:
    observed/model-fitted environmental value — Earth ISA 6.5, Venus VIRA
    ~8 near-adiabatic, Mars ~2.5 dust-softened vs 4.5 dry adiabat, Titan
    ~1.38 Lindal/HASI); airless worlds declare none, so the modifier stays
    off there by construction.
    """
    base = _classify(
        d, is_land=is_land, ai_edges=AI_EDGES_V1, supply_bands=SUPPLY_BANDS_V1, profile=PROFILE_V2
    )
    highland = False
    if (
        is_land
        and elevation_m is not None
        and lapse_rate_c_per_km is not None
        and elevation_m != 0.0
    ):
        delta = float(lapse_rate_c_per_km) * float(elevation_m) / 1000.0
        band_reduced = _thermal_band_for_extremes(d.t_max + delta, d.t_min + delta)
        highland = band_reduced != base.thermal
    shape: str | None = None
    if (
        d.concentration is not None
        and d.concentration >= SHAPE_GATE_C_TV_V2
        and d.p_harmonic1 is not None
        and d.p_harmonic2 is not None
    ):
        # Tolerance: a delta spike carries *every* harmonic at amplitude 1 —
        # float noise must not flip a pure spike to "bimodal".
        shape = "bimodal" if d.p_harmonic2 > d.p_harmonic1 + 1e-9 else "unimodal"
    phase: str | None = None
    if d.p_phase_status == VALID and d.p_phase is not None:
        abs_phase = abs(d.p_phase)
        if abs_phase <= PHASE_LETTER_IN_CYCLE:
            phase = "in_phase"
        elif abs_phase >= PHASE_LETTER_ANTI_CYCLE:
            phase = "anti_phase"
    return UCCClassV2(
        profile=base.profile,
        thermal=base.thermal,
        supply=base.supply,
        supply_status=base.supply_status,
        is_land=base.is_land,
        continental=base.continental,
        water_stress=base.water_stress,
        shape=shape,
        phase=phase,
        highland=highland,
    )


# ---------------------------------------------------------------------------
# Zone grammar: canonical parts + parser (specification §5.4)
#
# code   := main ( "-" zone )*
# main   := thermal supply | thermal slot          # exactly two characters
# zone   := head followers?                        # head uppercase, followers
#                                                   # zone-scoped lowercase
# ---------------------------------------------------------------------------


class UCCGrammarError(ValueError):
    """A code string violates the v2 zone grammar (§5.4)."""


@dataclass(frozen=True)
class UCCCodeParts:
    """Parsed v2 code — the semantic content behind the letter display.

    ``parse_ucc_code`` fills this from a string; ``render`` re-emits the
    canonical code.  ``UCCClassV2.code`` renders through this type, so the
    grammar has exactly one implementation.
    """

    thermal: str
    supply: str | None  # band name; None → the slot letter was used
    slot: str | None  # "o" ocean / "n" land supply-NA; None when supply present
    continental: bool
    water_stress: bool
    shape: str | None
    phase: str | None
    highland: bool
    #: Reserved extension slot (spec §5.4): braced lowercase words carried in
    #: the seasonality zone after its registered letters, alphabetically.
    #: No vocabulary is registered — classify never emits them; the parser
    #: accepts and round-trips them so downstream tooling can adopt the hatch
    #: without a grammar change.
    extensions: tuple[str, ...] = ()

    def render(self) -> str:
        t = THERMAL_CODE_LETTERS_V2[self.thermal]
        if self.supply is not None:
            main = t + SUPPLY_CODE_LETTERS_V2[self.supply]
        else:
            main = t + (self.slot or OCEAN_CODE_LETTER)
        season = ZONE_HEAD_SEASONALITY
        if self.continental:
            season += MOD_CODE_LETTERS_V2["continental"]
        if self.water_stress:
            season += MOD_CODE_LETTERS_V2["water_stress"]
        if self.shape is not None:
            season += SHAPE_CODE_LETTERS_V2[self.shape]
        if self.phase is not None:
            season += PHASE_CODE_LETTERS_V2[self.phase]
        for word in self.extensions:
            season += "{" + word + "}"
        zones = []
        if len(season) > 1:
            zones.append(season)
        if self.highland:
            zones.append(ZONE_HEAD_HIGHLAND)
        return "-".join([main, *zones])


_THERMAL_LETTER_TO_BAND = {v: k for k, v in THERMAL_CODE_LETTERS_V2.items()}
_SUPPLY_LETTER_TO_BAND = {v: k for k, v in SUPPLY_CODE_LETTERS_V2.items()}
#: Zone registry in canonical order (spec §5.4); B globally retired.
_ZONE_ORDER = {ZONE_HEAD_SEASONALITY: 0, ZONE_HEAD_HIGHLAND: 1}


def parse_ucc_code(code: str) -> UCCCodeParts:
    """Parse a v2 zone-grammar code, validating structure and letter order.

    Raises :class:`UCCGrammarError` on any violation — unknown/retired
    letters, a zone without followers' content where none is allowed,
    followers in non-canonical order, duplicate zones, or zones out of
    registry order.  Round-trip guarantee: ``parse_ucc_code(c).render()``
    re-emits any canonical code unchanged.
    """
    segs = code.split("-")
    main = segs[0]
    if len(main) != 2:
        raise UCCGrammarError(f"main segment {main!r} must be exactly 2 characters")
    thermal = _THERMAL_LETTER_TO_BAND.get(main[0])
    if thermal is None:
        raise UCCGrammarError(f"unknown thermal letter {main[0]!r} (B is retired)")
    supply: str | None = None
    slot: str | None = None
    if main[1] == OCEAN_CODE_LETTER:
        slot = OCEAN_CODE_LETTER
    elif main[1] == LAND_NA_CODE_LETTER:
        slot = LAND_NA_CODE_LETTER
    else:
        supply = _SUPPLY_LETTER_TO_BAND.get(main[1])
        if supply is None:
            raise UCCGrammarError(f"unknown supply letter {main[1]!r}")

    continental = water_stress = highland = False
    shape: str | None = None
    phase: str | None = None
    extensions: list[str] = []
    last_zone_rank = -1
    for zone in segs[1:]:
        if not zone:
            raise UCCGrammarError("empty zone (trailing or doubled hyphen)")
        head, followers = zone[0], zone[1:]
        if head not in _ZONE_ORDER:
            raise UCCGrammarError(f"unknown zone head {head!r}")
        if _ZONE_ORDER[head] <= last_zone_rank:
            raise UCCGrammarError(f"zone {head!r} out of registry order or duplicated")
        last_zone_rank = _ZONE_ORDER[head]
        if head == ZONE_HEAD_HIGHLAND:
            if followers:
                raise UCCGrammarError("the H zone has no followers in the registry")
            highland = True
            continue
        # Seasonality zone: followers must be known letters or reserved
        # extension words (``{word}``, spec §5.4), and in strictly increasing
        # canonical order — l < g < m|d < h|o < extensions, the latter
        # alphabetical among themselves.
        if not followers:
            raise UCCGrammarError("the S zone must carry at least one letter")
        tokens: list[str] = []
        i = 0
        while i < len(followers):
            ch = followers[i]
            if ch == "{":
                end = followers.find("}", i + 1)
                if end < 0:
                    raise UCCGrammarError(f"unterminated extension word in {followers!r}")
                tokens.append(followers[i : end + 1])
                i = end + 1
            elif ch.isalpha() and ch.islower():
                tokens.append(ch)
                i += 1
            else:
                raise UCCGrammarError(f"invalid seasonality follower {ch!r}")
        extension_base = len(_SEASONALITY_FOLLOWER_RANKS)
        rank_keys: list[tuple[int, str]] = []
        for tok in tokens:
            if tok.startswith("{"):
                word = tok[1:-1]
                if not word or not (word.isalpha() and word.islower()):
                    raise UCCGrammarError(
                        f"invalid extension word {tok!r} — lowercase letters only"
                    )
                rank_keys.append((extension_base, word))
                extensions.append(word)
                continue
            rank = _SEASONALITY_FOLLOWER_RANKS.get(tok)
            if rank is None:
                raise UCCGrammarError(f"unknown seasonality letter {tok!r}")
            rank_keys.append((rank, ""))
        if any(rank_keys[k + 1] <= rank_keys[k] for k in range(len(rank_keys) - 1)):
            raise UCCGrammarError(f"seasonality followers {followers!r} not in canonical order")
        continental = "l" in tokens
        water_stress = "g" in tokens
        if "m" in tokens:
            shape = "unimodal"
        elif "d" in tokens:
            shape = "bimodal"
        if "h" in tokens:
            phase = "in_phase"
        elif "o" in tokens:
            phase = "anti_phase"
    return UCCCodeParts(
        thermal=thermal,
        supply=supply,
        slot=slot,
        continental=continental,
        water_stress=water_stress,
        shape=shape,
        phase=phase,
        highland=highland,
        extensions=tuple(extensions),
    )


# ---------------------------------------------------------------------------
# Shared per-cell yearly computation (used by both writers: the engine export
# path in map/export.py and the solar/obs path in import_solar_common.py)
# ---------------------------------------------------------------------------


def yearly_cell_arrays(
    t_monthly: np.ndarray,
    p_monthly: np.ndarray,
    et_monthly: np.ndarray | None,
    is_land: np.ndarray,
    elevation_m: np.ndarray | None = None,
    lapse_rate_c_per_km: float | None = None,
) -> dict[str, np.ndarray]:
    """Compute the per-cell descriptor + classification arrays in one pass.

    Args:
        t_monthly: (N, M) bin-mean temperatures (°C).
        p_monthly: (N, M) precipitation per bin (rate or total — with equal
            bins the distinction is a constant factor that cancels in every
            ratio; ``p_total`` follows the value basis of the inputs).
        et_monthly: (N, M) reference demand per bin, same basis as p; None =
            no demand model (AI/deficit/phase → missing_input).
        is_land: (N,) bool land mask (ocean cells keep the thermal band and
            take the n/a supply slot).
        elevation_m: (N,) cell elevations for the -H modifier; None disables.
        lapse_rate_c_per_km: declared world-level lapse rate; None disables.

    Returns:
        float32/uint8 arrays keyed by the ``climate_yearly.msgpack`` payload
        names (``.tobytes()`` by the caller).  Undefined descriptor values are
        NaN; ``ucc_supply``/``ucc_shape``/``ucc_phase`` use 255 for n/a;
        ``ucc_modifiers`` bitmask: bit 0 continental, bit 1 water_stress,
        bit 2 highland.
    """
    t_monthly = np.asarray(t_monthly, dtype=np.float64)
    p_monthly = np.asarray(p_monthly, dtype=np.float64)
    n = t_monthly.shape[0]
    is_land = np.asarray(is_land, dtype=bool)

    status_index = {s: i for i, s in enumerate(STATUS_CODES)}
    thermal_index = {b: i for i, b in enumerate(THERMAL_BANDS_CURRENT)}
    supply_index = {b: i for i, b in enumerate(SUPPLY_BANDS_CURRENT)}
    shape_codes = list(SHAPE_CODE_LETTERS_V2)
    shape_index = {c: i for i, c in enumerate(shape_codes)}
    phase_codes = list(PHASE_CODE_LETTERS_V2)
    phase_index = {c: i for i, c in enumerate(phase_codes)}

    out: dict[str, np.ndarray] = {
        "t_mean_c": np.empty(n, np.float32),
        "t_min_c": np.empty(n, np.float32),
        "t_max_c": np.empty(n, np.float32),
        "t_range_c": np.empty(n, np.float32),
        "t_below_frac": np.empty(n, np.float32),
        "p_mean_mm_per_month": np.empty(n, np.float32),
        "p_total_mm": np.empty(n, np.float32),
        "ai": np.full(n, np.nan, np.float32),
        "ai_status": np.empty(n, np.uint8),
        "deficit": np.full(n, np.nan, np.float32),
        "deficit_status": np.empty(n, np.uint8),
        "concentration": np.full(n, np.nan, np.float32),
        "p_harmonic1": np.full(n, np.nan, np.float32),
        "p_harmonic2": np.full(n, np.nan, np.float32),
        "p_phase": np.full(n, np.nan, np.float32),
        "p_phase_status": np.empty(n, np.uint8),
        "ucc_thermal": np.empty(n, np.uint8),
        "ucc_supply": np.empty(n, np.uint8),
        "ucc_supply_status": np.empty(n, np.uint8),
        "ucc_modifiers": np.empty(n, np.uint8),
        "ucc_shape": np.empty(n, np.uint8),
        "ucc_phase": np.empty(n, np.uint8),
    }

    elev_arr: np.ndarray | None = None
    cell_lapse: float | None = None
    if elevation_m is not None and lapse_rate_c_per_km is not None:
        elev_arr = np.asarray(elevation_m, dtype=np.float64)
        cell_lapse = float(lapse_rate_c_per_km)
    for i in range(n):
        et_i = None if et_monthly is None else et_monthly[i]
        d = compute_descriptors(t_monthly[i], p_monthly[i], et_i)
        out["t_mean_c"][i] = d.t_mean
        out["t_min_c"][i] = d.t_min
        out["t_max_c"][i] = d.t_max
        out["t_range_c"][i] = d.t_range
        out["t_below_frac"][i] = d.t_below_frac
        out["p_mean_mm_per_month"][i] = d.p_mean_rate
        out["p_total_mm"][i] = d.p_total
        if d.ai is not None:
            out["ai"][i] = d.ai
        out["ai_status"][i] = status_index[d.ai_status]
        if d.deficit is not None:
            out["deficit"][i] = d.deficit
        out["deficit_status"][i] = status_index[d.deficit_status]
        if d.concentration is not None:
            out["concentration"][i] = d.concentration
        if d.p_harmonic1 is not None:
            out["p_harmonic1"][i] = d.p_harmonic1
        if d.p_harmonic2 is not None:
            out["p_harmonic2"][i] = d.p_harmonic2
        if d.p_phase is not None:
            out["p_phase"][i] = d.p_phase
        out["p_phase_status"][i] = status_index[d.p_phase_status]
        cls = classify_v2(
            d,
            is_land=bool(is_land[i]),
            elevation_m=float(elev_arr[i]) if elev_arr is not None else None,
            lapse_rate_c_per_km=cell_lapse,
        )
        out["ucc_thermal"][i] = thermal_index[cls.thermal]
        out["ucc_supply"][i] = supply_index[cls.supply] if cls.supply is not None else 255
        out["ucc_supply_status"][i] = status_index[cls.supply_status]
        out["ucc_modifiers"][i] = (
            (1 if cls.continental else 0)
            | (2 if cls.water_stress else 0)
            | (4 if cls.highland else 0)
        )
        out["ucc_shape"][i] = shape_index[cls.shape] if cls.shape is not None else 255
        out["ucc_phase"][i] = phase_index[cls.phase] if cls.phase is not None else 255
    return out
