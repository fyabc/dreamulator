"""Procedural cloud texture — layer L2 of the orbital weather-globe chain.

Requirement spec: the orbital weather-globe requirement notes.
The GCM layer pack (L1: per-layer cloud fraction, cloud-top height, vorticity)
is still pending; until it arrives this module derives a
**placeholder large-scale cloud-cover field** from the engine climate fields
already on the mesh (annual precipitation and sea-level-pressure anomaly), so
the look of the procedural texture can be settled now.  The texture synthesis
itself — spherical fBm, wind-flow domain warp, cirrus streak taps — is the
permanent part; only ``large_scale_cover`` is expected to be replaced by real
GCM cloud fields later.

Design notes:

* All noise is sampled in 3D at the pixel's unit-sphere position, so the
  equirectangular output is seamless at the antimeridian and has no polar
  pinch — the two classic failure modes of 2D noise on a map grid.
* The noise kernel is the terrain pipeline's per-point Perlin fBm
  (``map.noise_kernels.fbm_on_points``, numba-parallel).  The
  ``opensimplex`` package used elsewhere in the repo only offers
  grid-product sampling (``noise3array`` builds the full z×y×x volume),
  which cannot do the per-pixel domain warps this module needs.
* Wind-flow warp follows flow noise (Perlin & Neyret 2001): the sampling
  position is displaced along the smoothed surface wind, so cloud streaks
  bend with the circulation instead of lying on a static lattice.
* Cloud typing is deliberately minimal for the prototype: one billow layer
  (fair-weather cumulus / stratocumulus texture, thresholded by the cover
  field) and one cirrus layer (double-tap streaks elongated along the wind,
  strengthening with wind speed).  Cyclone morphology is layer L3
  (``media/cyclone_render.py``), composited by :func:`clouds_globe` when a
  track set is supplied.

Epistemic status (per engine discipline §9): the noise machinery is a
standard graphics technique; the cover-field coefficients in
``large_scale_cover`` are observation-fitted placeholders (tuned so the
Hadley-cell band structure of nacrea reads correctly) and must be replaced
by the GCM layer-pack contract when it lands.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.map.noise_kernels import fbm_on_points, worley_on_points

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from dreamulator.map.models import CVTMesh
    from dreamulator.media.cyclone_render import Cyclone

# ---------------------------------------------------------------------------
# Texture constants (lengths in km on the planet surface)
# ---------------------------------------------------------------------------

#: Shape layer of the billow texture: sets WHICH pixels are cloudy.  Long
#: base wavelength + low gain → continent-scale coherent masses; threshold
#: crossings of a full-bandwidth fBm are dominated by the highest octaves
#: and read as uniform crumble at disk scale (proto3/proto4 lesson).
BILLOW_WAVELENGTH_KM = 1800.0
BILLOW_OCTAVES = 4
BILLOW_GAIN = 0.45

#: Billow elongation: the shape field is averaged over two taps ± this arc
#: length along the wind (scaled by wind speed), stretching cloud masses into
#: flow-following bands — the Blue-Marble reference shows streaks/bands
#: dominating over isotropic blobs (user QA proto9).
BILLOW_STREAK_KM = 300.0  # cloud streets / frontal bands stretch along the flow
BILLOW_STREAK_REF_WIND_M_S = 10.0

#: Detail layer: fine fBm that ERODES cloud edges (Frostbite 2016 convention:
#: shape noise defines the mass, high-frequency noise carves the margins) —
#: subtractive near alpha≈0.5, leaving cores intact.  Gives frayed,
#: cauliflower-edged cloud boundaries instead of smooth cutouts.  The
#: wavelength must be a TEXTURE scale (~15 px at the 16K target grid): at
#: 220 km the "detail" was a mid-scale structure and carved visible swirl
#: notches across every mid-alpha deck (proto13 lesson).
DETAIL_WAVELENGTH_KM = 18.0
DETAIL_OCTAVES = 4
DETAIL_ERODE = 0.32

#: System-size diversity: a very-low-frequency field CROSSFADES between two
#: billow fields of different scales (big coherent systems ↔ small clusters),
#: so system size varies regionally (user QA proto10).  Crossfade, NOT a
#: spatially-varying coordinate multiplier — multiplying sample coords by a
#: field shears iso-contours into full-disk marbling (proto11–14 lesson).
SIZE_MOD_WAVELENGTH_KM = 6000.0
SIZE_SMALL_FACTOR = 3.2  # small-cluster scale = billow base / 3.2 (~560 km)

#: Deck layer: very-low-frequency (λ≈4200 km) continuous cloud SHEETS gated
#: by the cover field — the big frontal/deck systems spanning thousands of
#: km that the billow bands alone don't form (user QA proto19: no
#: planet-scale cloud systems).  Combined with the cluster layer by alpha
#: over-blend; the deck wins where both fire.
DECK_WAVELENGTH_KM = 7000.0
DECK_OCTAVES = 2
#: Deck sheet area gate: fraction of locally cloudy area (superlinear in
#: cover — deserts get ~none, storm tracks get coherent sheets).
DECK_AREA_SHARE = 0.6
DECK_AREA_EXP = 1.2
#: Deck brightness boost over the cluster alpha_max.
DECK_THICK_BOOST = 1.35
#: Deck thickness truncation (flatter than the cluster exponential).
DECK_EXP_EPS = 0.05
#: Planet-scale shield layer (very large coherent frontal systems).
SHIELD_WAVELENGTH_KM = 9000.0
SHIELD_OCTAVES = 2
SHIELD_AREA_SHARE = 0.20
SHIELD_THICK_BOOST = 1.45

FBM_GAIN = 0.5
FBM_LACUNARITY = 2.0

#: Persistence of the VISIBLE density layers (billow/detail/deck/cirrus/
#: haze).  Observed cloud radiance fields have a 1D power spectrum of
#: k^-5/3 (Cahalan & Joseph 1989, via Davis et al. 1997), i.e. a 2D slope
#: of 8/3, which for fBm means persistence 2^(-1/3) ~ 0.79; the graphics
#: default 0.5 (2D slope 4) starves mid frequencies — measured 2-3x power
#: deficit vs Blue Marble at 20-200 cycles/disk.  0.70 is the engineering
#: compromise (the observed slope is of radiance, post tau->R saturation).
#: See docs/knowledge/climatology/cloud_field_statistics.md.
DENSITY_GAIN = 0.80

#: Synoptic "weather-system" modulation: the conditioning cover field varies
#: only at mesh-cell scale (~50 km, smoothed), and thresholding it directly
#: fragments everything into uniform crumble — real skies organise into
#: coherent cloud systems (cyclones, fronts, ITCZ segments) of 1000s of km
#: with clear slots between.  A low-frequency fBm multiplies the cover field
#: (locally 0.2×–2.6×) so cloud bunches into systems at this scale.
SYNOPTIC_WAVELENGTH_KM = 2800.0
SYNOPTIC_OCTAVES = 2
SYNOPTIC_BASE = 0.2
SYNOPTIC_AMP = 2.4

#: Low-frequency fBm vector warp: bends cloud bands into swirls at synoptic
#: scale (~3500 km, the nacrea storm-track eddy scale — the slow rotation
#: gives a deformation radius ~3× Earth's).
WARP_WAVELENGTH_KM = 3500.0
WARP_AMPLITUDE_KM = 150.0  # global swirl warp read as liquid marble (proto59 QA);
#: real flow organisation is straight streets/bands, swirls only near cyclones
WARP_OCTAVES = 2

#: Wind advection warp: sampling positions are displaced downwind by this
#: many km per (m/s) of surface wind, so texture streaks follow the flow.
WIND_WARP_KM_PER_M_S = 28.0

#: Cirrus streaks: the noise field is sampled twice, ± this arc length along
#: the wind (scaled by wind speed relative to CIRRIUS_REF_WIND), and averaged.
CIRRUS_STREAK_KM = 380.0
CIRRUS_REF_WIND_M_S = 12.0
CIRRUS_WAVELENGTH_KM = 1400.0
CIRRUS_OCTAVES = 3

#: Cover-field thresholds (placeholder for the L1 GCM layer pack — see module
#: docstring).  ``p_norm`` below the floor maps to clear sky; calibrated on
#: the gcm-t42-712 field distribution for a global mean cover ≈ 0.24 (cirrus
#: adds a thin haze on top — Earth-for-reference satellite means run ≈ 0.67
#: including thin high cloud, but the opaque low fraction is ~0.3).
COVER_PRECIP_FLOOR = 0.50  # p_norm ≈ 0.53 ↔ ~1300 mm/yr
COVER_PRECIP_SPAN = 0.35
COVER_DP_CENTRE_HPA = 0.55  # c_dyn = clip(CENTRE - dp/SPAN, 0, 1)
COVER_DP_SPAN_HPA = 12.0
COVER_DYN_FLOOR = 0.35  # moisture leg scaled by (FLOOR + (1-FLOOR)·c_dyn)
#: Hard ceiling on the locally-modulated cover: even the ITCZ core keeps
#: ~10% clear breaks — without it the synoptic multiplier saturates whole
#: tropical belts at 1.0 and they render as solid white (user QA proto8).
COVER_LOCAL_MAX = 0.90

#: Cloud optical look: within-cloud alpha follows the density field
#: continuously — alpha = alpha_max·core^γ with alpha_max = 1−exp(−k·cov).
#: γ > 1 concentrates opacity in dense cores (distinct clouds with
#: translucent fringes); γ < 1 spreads it into a uniform grey wash
#: (proto16 lesson: 0.6 read as greasy haze everywhere).  k=4 gives thin
#: systems (cov≈0.25) peak ≈0.63, wet systems ≈0.86, ITCZ cores ≈0.97.
#: A faint veil (15% × cov) fringes just below the threshold.
#: Truncation of the exponential alpha law.  Fitted to the Blue Marble
#: reference histogram slope (log-count vs linear alpha decays with scale
#: theta ~ 0.15): eps = exp(-alpha_max/theta) at a typical alpha_max ~0.75
#: gives ~0.007.  eps=1e-4 (proto24-26) made the median alpha 0.075*amax -
#: the whole field starved thin and the mid-tone/gradient metrics collapsed.
ALPHA_EXP_EPS = 0.008
#: Cap on per-region peak alpha: the reference histogram has little mass
#: above ~0.85 excess luminance even in cyclone cores.
ALPHA_MAX_CAP = 0.85
#: Element edge softness (fraction of band sigma): crisp element boundaries
#: — wide spatial ramps read as fog (user QA proto32).
EDGE_SOFTNESS_SIGMA = 0.50
#: Meso-scale field (lambda ~1200 km) whose rank drives per-element optical
#: thickness through the exponential inverse CDF.
MESO_WAVELENGTH_KM = 1200.0
MESO_OCTAVES = 2
#: Fringe veil amplitude just outside element edges (small — wide veils are
#: the fog artefact).
VEIL_AMP = 0.10
#: Multiplicative grain amplitude inside cloud masses.
GRAIN_AMP = 0.18
#: Mesoscale cellular convection (MCC, Agee et al. 1973): marine low-cloud
#: regimes organise into open cells (bright walls, clear centres, ~40-80 km)
#: and closed cells (bright centres, ~5-50 km).  Ridged noise gives the cell
#: walls; a low-frequency field mixes open/closed.  Pure fBm grain lacks this
#: geometric organisation (second research pass, 2026-10-19).
MCC_WAVELENGTH_KM = 60.0
MCC_OCTAVES = 2
MCC_AMP = 0.55
MCC_GATE_LO = 0.15
MCC_GATE_HI = 0.50
#: Worley cellular shaping of convective/trade elements: convex crisp blobs
#: with clear inter-cell gaps (the shape language of real cumulus aggregates,
#: reference crop 2) — Perlin iso-contours yield wavy interlocked shapes
#: instead.  Second research pass 2026-10-19.
WORLEY_WAVELENGTH_KM = 80.0
WORLEY_MIX = 0.60
#: Sub-grid broken-cloud layer (partial pixel coverage at satellite scale).
SUB_WAVELENGTH_KM = 250.0
SUB_OCTAVES = 3
SUB_AREA_FACTOR = 1.5
SUB_MAX_ALPHA = 0.18
#: Compact bright-core layer (convective towers / comma heads); area set by
#: the 97-99.5% quantiles of the smoothed density within the gated regime.
CORE_ALPHA = 0.97
#: Spatial coherence scale of bright cores (km).
CORE_SMOOTH_KM = 60.0
#: Intermittency cascade (multifractal cloud model, Lovejoy & Schertzer):
#: a multiplicative field applied to the density BEFORE the rank/threshold
#: mapping, so cloud masks break into discrete sub-elements with dark
#: gaps at every scale below ~600 km.  Without it mid-scale masses are
#: smooth airbrushed blobs (user QA proto40 vs real satellite crops:
#: convective clusters are aggregates of crisp cells, sheets carry
#: cellular substructure).
CASCADE_WAVELENGTH_KM = 600.0
CASCADE_STREAK_KM = 180.0
MESO_STREAK_KM = 300.0
CASCADE_OCTAVES = 5  # Rossow et al. 2002: cloud structure at all scales down to km
CASCADE_GAIN = 0.65
CASCADE_FLOOR = 0.45
CASCADE_AMP = 1.10
CASCADE_POWER = 1.2
LOWCLOUD_OPACITY_K = 5.0
LOWCLOUD_CORE_GAMMA = 1.0
#: Cirrus: thin veil concentrated in and around cloudy systems (strong cover
#: gating — an ungated widespread veil aliases into full-disk marbling under
#: the preview emboss, proto11 lesson), stronger along fast winds.  Never
#: occludes.
CIRRUS_THRESHOLD_LO = 0.66
CIRRUS_THRESHOLD_HI = 0.92
CIRRUS_BASE_ALPHA = 0.14
CIRRUS_WIND_ALPHA = 0.40

#: Diffuse haze floor: a very thin (≤5%) fine-textured veil everywhere, weakly
#: gated by cover — real imagery has micro-texture even in "clear" sky (dust,
#: thin cirrus, sub-visible cloud); without it our clear regions are
#: gradient-free and read as detail-poor vs the reference (p50 |∇luma| 0.014
#: vs 0.025, cloud-compare metric).
HAZE_WAVELENGTH_KM = 120.0
HAZE_OCTAVES = 4
HAZE_MAX_ALPHA = 0.08

#: Preview-shading knobs (module-level so diagnostics can monkeypatch them).
#: Relief gain: alpha-gradient → cloud-top normal strength.
PREVIEW_RELIEF = 8.0
PREVIEW_EMBOSS_SMOOTH_PX = 3.0
PREVIEW_THICK_BASE = 0.80
PREVIEW_THICK_AMP = 0.40

#: Cloud tint (sRGB, straight alpha).  Slightly warm white — the K-dwarf
#: illumination shift is a render-time (L5) concern, not baked in here.
CLOUD_RGB = (252, 250, 245)

#: Neighbour-averaging rounds on the mesh graph before rasterising the
#: conditioning fields — removes Voronoi plateaus uniformly in km (a
#: pixel-space blur would over-smooth the poles on an equirect grid).
MESH_SMOOTH_ROUNDS = 2

#: Row-band height for chunked texture synthesis (bounds peak memory).
BAND_ROWS = 256


# ---------------------------------------------------------------------------
# Conditioning fields (placeholder for the L1 GCM layer pack)
# ---------------------------------------------------------------------------


def smooth_mesh_field(mesh: CVTMesh, values: np.ndarray, rounds: int) -> np.ndarray:
    """Diffusive smoothing on the cell adjacency graph (uniform in km).

    Each round sets ``v_i ← (2·v_i + Σ_neighbours v) / (2 + degree)`` —
    a graph-Laplacian step weighted toward self so two rounds approximate a
    Gaussian of ~one cell pitch without washing out the Hadley banding.
    """
    n = mesh.num_cells
    offsets = np.zeros(n + 1, dtype=np.int64)
    for i in range(n):
        offsets[i + 1] = offsets[i] + len(mesh.adjacency.get(str(i), ()))
    flat = np.empty(int(offsets[-1]), dtype=np.int64)
    pos = 0
    for i in range(n):
        nb = mesh.adjacency.get(str(i), ())
        for j in nb:
            flat[pos] = j
            pos += 1
    deg = np.diff(offsets).astype(np.float64)

    out = values.astype(np.float64, copy=True)
    for _ in range(rounds):
        sums = np.add.reduceat(out[flat], offsets[:-1])
        out = (2.0 * out + sums) / (2.0 + deg)
    return out


def large_scale_cover(precip_mm: np.ndarray, dp_hpa: np.ndarray) -> np.ndarray:
    """Placeholder cloud-cover field ∈ [0, 1] from precipitation + Δp.

    Moisture leg: log-scaled annual precipitation (same normalisation as the
    frontend precip layer) above a floor.  Dynamics leg: low SLP anomaly
    (ascent) amplifies, subtropical highs (subsidence) suppress — the legs
    combine multiplicatively (cloud needs both moisture AND ascent), not
    additively, or subtropical deserts stay hazy.  Coefficients are
    observation-fitted placeholders — to be replaced by the GCM layer pack's
    per-layer cloud fraction when it lands.
    """
    p_norm = np.log10(np.clip(precip_mm, 0.0, None) + 1.0) / math.log10(30001.0)
    c_moist = np.clip((p_norm - COVER_PRECIP_FLOOR) / COVER_PRECIP_SPAN, 0.0, 1.0)
    c_dyn = np.clip(COVER_DP_CENTRE_HPA - dp_hpa / COVER_DP_SPAN_HPA, 0.0, 1.0)
    cover = c_moist * (COVER_DYN_FLOOR + (1.0 - COVER_DYN_FLOOR) * c_dyn)
    return np.asarray(np.clip(cover, 0.0, 1.0), dtype=np.float64)


# ---------------------------------------------------------------------------
# Sphere sampling helpers
# ---------------------------------------------------------------------------


def _band_xyz(width: int, lat_rad: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unit-sphere xyz for one row band, matching map.export's convention:
    x = cos φ·cos λ, y = sin φ, z = cos φ·sin λ (λ ∈ [−π, π] left to right)."""
    lon = (np.arange(width, dtype=np.float64) + 0.5) / width * (2.0 * math.pi) - math.pi
    cos_lat = np.cos(lat_rad)[:, None]
    x = cos_lat * np.cos(lon)[None, :]
    y = np.broadcast_to(np.sin(lat_rad)[:, None], x.shape)
    z = cos_lat * np.sin(lon)[None, :]
    return (
        np.ascontiguousarray(x.ravel()),
        np.ascontiguousarray(np.asarray(y, dtype=np.float64).ravel()),
        np.ascontiguousarray(z.ravel()),
    )


def _tangent_wind3(
    width: int,
    lat_rad: np.ndarray,
    u_east: np.ndarray,
    v_north: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project per-pixel (east, north) wind [m/s] into 3D tangent vectors."""
    lon = (np.arange(width, dtype=np.float64) + 0.5) / width * (2.0 * math.pi) - math.pi
    sin_lon = np.sin(lon)[None, :]
    cos_lon = np.cos(lon)[None, :]
    sin_lat = np.sin(lat_rad)[:, None]
    cos_lat = np.cos(lat_rad)[:, None]
    # east = (−sin λ, 0, cos λ); north = (−sin φ·cos λ, cos φ, −sin φ·sin λ)
    wx = u_east * (-sin_lon) + v_north * (-sin_lat * cos_lon)
    wy = v_north * cos_lat
    wz = u_east * cos_lon + v_north * (-sin_lat * sin_lon)
    return (
        np.ascontiguousarray(wx.ravel()),
        np.ascontiguousarray(wy.ravel()),
        np.ascontiguousarray(wz.ravel()),
    )


def _smoothstep(lo: float | np.ndarray, hi: float | np.ndarray, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return np.asarray(t * t * (3.0 - 2.0 * t))


def _streak_pair(
    bx: np.ndarray,
    by: np.ndarray,
    bz: np.ndarray,
    dirx: np.ndarray,
    diry: np.ndarray,
    dirz: np.ndarray,
    elong: np.ndarray,
    seed: int,
    octaves: int,
    persistence: float,
) -> np.ndarray:
    """Sum of two fBm taps at ±elong along the wind (caller adds 0.5 base)."""
    d1 = fbm_on_points(
        bx + dirx * elong,
        by + diry * elong,
        bz + dirz * elong,
        seed=seed,
        octaves=octaves,
        persistence=persistence,
    )
    d2 = fbm_on_points(
        bx - dirx * elong,
        by - diry * elong,
        bz - dirz * elong,
        seed=seed,
        octaves=octaves,
        persistence=persistence,
    )
    return np.asarray(d1 + d2)


def _streaked_fbm(
    bx: np.ndarray,
    by: np.ndarray,
    bz: np.ndarray,
    dirx: np.ndarray,
    diry: np.ndarray,
    dirz: np.ndarray,
    elong: np.ndarray,
    fscale: float,
    seed: int,
    octaves: int,
    persistence: float,
) -> np.ndarray:
    """fBm averaged over two taps ±elong·fscale along the wind direction.

    Streak-elongates the sampled field along the flow (cloud masses become
    bands).  Module-level with explicit arguments so the synthesis loop stays
    lint-clean (no closure over per-band locals).
    """
    e = elong * fscale
    xa, ya, za = bx * fscale, by * fscale, bz * fscale
    d1 = fbm_on_points(
        xa + dirx * e,
        ya + diry * e,
        za + dirz * e,
        seed=seed,
        octaves=octaves,
        persistence=persistence,
    )
    d2 = fbm_on_points(
        xa - dirx * e,
        ya - diry * e,
        za - dirz * e,
        seed=seed,
        octaves=octaves,
        persistence=persistence,
    )
    return np.asarray(0.5 * (d1 + d2))


# ---------------------------------------------------------------------------
# Texture synthesis
# ---------------------------------------------------------------------------


@dataclass
class CloudProducts:
    """Outputs of the equirectangular cloud synthesis."""

    alpha: np.ndarray  # (h, w) float64 ∈ [0, 1] — effective opacity
    cover: np.ndarray  # (h, w) float64 ∈ [0, 1] — large-scale cover field
    width: int
    height: int


def cloud_texture_equirect(
    cover_grid: np.ndarray,
    wind_east_grid: np.ndarray,
    wind_north_grid: np.ndarray,
    ocean_grid: np.ndarray | None = None,
    dp_grid: np.ndarray | None = None,
    *,
    radius_km: float,
    seed: int,
) -> CloudProducts:
    """Synthesise the procedural cloud opacity on an equirectangular grid.

    Two-pass synthesis.  Pass A stores the billow density on a global grid so
    the coverage threshold can be read off a GLOBAL rank distribution — the
    per-band thresholds left visible horizontal seams at band boundaries
    (native-resolution crop QA, proto60).  Pass B recomputes the modulation
    fields and assembles alpha; all texture blocks (erosion / grain / MCC /
    Worley) run AFTER the deck and shield max-blends so every layer receives
    them (proto60 showed flat untextured sheet patches).

    ``cover_grid``/``wind_*_grid`` are (h, w) fields already rasterised onto
    the output grid (conditioning from the mesh is the caller's job).  All
    noise is sampled on the unit sphere — seamless at the antimeridian, no
    polar pinch.  Deterministic given (fields, radius, seed).
    """
    height, width = cover_grid.shape
    if ocean_grid is None:
        ocean_grid = np.ones((height, width), dtype=np.float64)
    if dp_grid is None:
        dp_grid = np.zeros((height, width), dtype=np.float64)

    # Noise frequencies: cycles around the sphere for a given surface
    # wavelength — sampling at p·freq gives the wavelength at the equator.
    circ_km = 2.0 * math.pi * radius_km
    f_billow = circ_km / BILLOW_WAVELENGTH_KM
    f_detail = circ_km / DETAIL_WAVELENGTH_KM
    f_warp = circ_km / WARP_WAVELENGTH_KM
    f_cirrus = circ_km / CIRRUS_WAVELENGTH_KM
    f_synoptic = circ_km / SYNOPTIC_WAVELENGTH_KM
    f_size = circ_km / SIZE_MOD_WAVELENGTH_KM
    f_deck = circ_km / DECK_WAVELENGTH_KM
    f_meso = circ_km / MESO_WAVELENGTH_KM
    f_casc = circ_km / CASCADE_WAVELENGTH_KM
    f_mcc = circ_km / MCC_WAVELENGTH_KM
    f_worley = circ_km / WORLEY_WAVELENGTH_KM
    f_sub = circ_km / SUB_WAVELENGTH_KM
    warp_amp = WARP_AMPLITUDE_KM / radius_km  # radians of arc on unit sphere

    # Each noise layer gets its own seed offset (the kernels derive their
    # permutation tables from the seed; layers stay independent).
    seed_warp = seed + 11
    seed_synoptic = seed + 14
    seed_detail = seed + 15
    seed_cirrus = seed + 16
    seed_size = seed + 17
    seed_deck = seed + 19
    seed_meso = seed + 21
    seed_casc = seed + 22
    seed_mcc = seed + 24

    def _band_basis(row0: int, row1: int) -> dict[str, Any]:
        """Per-band geometry, wind, regime weights and flow displacement."""
        lat = (0.5 - (np.arange(row0, row1, dtype=np.float64) + 0.5) / height) * math.pi
        x, y, z = _band_xyz(width, lat)
        cov = np.ascontiguousarray(cover_grid[row0:row1].ravel())
        oce = np.ascontiguousarray(ocean_grid[row0:row1].ravel())
        dpg = np.ascontiguousarray(dp_grid[row0:row1].ravel())
        lat_abs = np.abs(90.0 - (np.arange(row0, row1, dtype=np.float64) + 0.5) / height * 180.0)
        wx, wy, wz = _tangent_wind3(
            width, lat, wind_east_grid[row0:row1], wind_north_grid[row0:row1]
        )
        wmag = np.sqrt(wx * wx + wy * wy + wz * wz)
        # Cloud-regime weights (ISCCP-style weather states; second research
        # pass 2026-10-19): each regime gets its own texture recipe via
        # spatially-varying knobs (elongation / cascade contrast / scale
        # bias / cellularity).  User QA proto56: real clouds are not one
        # shape-and-texture everywhere.
        lat_fac = np.broadcast_to(lat_abs[:, None], (row1 - row0, width)).ravel()
        trades = (
            oce
            * _smoothstep(35.0, 25.0, lat_fac)
            * np.clip(cov / 0.30, 0.0, 1.0)
            * np.clip(-wx / 3.0, 0.0, 1.0)
        )
        frontal = (
            oce
            * _smoothstep(30.0, 45.0, lat_fac)
            * np.clip(-dpg / 3.0, 0.0, 1.0)
            * np.clip(wmag / 8.0, 0.0, 1.0)
        )
        convect = np.clip((cov - 0.45) / 0.30, 0.0, 1.0)
        stratus = (
            oce * np.clip(dpg / 3.0, 0.0, 1.0) * np.clip(cov / 0.20, 0.0, 1.0) * (1.0 - convect)
        )
        jet = np.clip((wmag - 10.0) / 8.0, 0.0, 1.0)
        # Low-frequency vector warp (synoptic swirl).
        dx = fbm_on_points(
            x * f_warp,
            y * f_warp,
            z * f_warp,
            seed=seed_warp,
            octaves=WARP_OCTAVES,
            persistence=FBM_GAIN,
        )
        dy = fbm_on_points(
            x * f_warp,
            y * f_warp,
            z * f_warp,
            seed=seed_warp + 1,
            octaves=WARP_OCTAVES,
            persistence=FBM_GAIN,
        )
        dz = fbm_on_points(
            x * f_warp,
            y * f_warp,
            z * f_warp,
            seed=seed_warp + 2,
            octaves=WARP_OCTAVES,
            persistence=FBM_GAIN,
        )
        # Wind advection warp (flow noise): displace downwind ∝ wind speed.
        wind_disp = WIND_WARP_KM_PER_M_S / radius_km  # arc per (m/s)
        disp_x = dx * warp_amp + wx * wind_disp
        disp_y = dy * warp_amp + wy * wind_disp
        disp_z = dz * warp_amp + wz * wind_disp
        # Synoptic modulation: bunch the cover field into coherent systems.
        syn = 0.5 + 0.5 * fbm_on_points(
            (x + disp_x) * f_synoptic,
            (y + disp_y) * f_synoptic,
            (z + disp_z) * f_synoptic,
            seed=seed_synoptic,
            octaves=SYNOPTIC_OCTAVES,
            persistence=FBM_GAIN,
        )
        cov_local = np.clip(cov * (SYNOPTIC_BASE + SYNOPTIC_AMP * syn), 0.0, COVER_LOCAL_MAX)
        safe = np.maximum(wmag, 1e-6)
        return {
            "lat": lat,
            "x": x,
            "y": y,
            "z": z,
            "cov": cov,
            "cov_local": cov_local,
            "wmag": wmag,
            "wx": wx,
            "dirx": wx / safe,
            "diry": wy / safe,
            "dirz": wz / safe,
            "disp_x": disp_x,
            "disp_y": disp_y,
            "disp_z": disp_z,
            "trades": trades,
            "frontal": frontal,
            "convect": convect,
            "stratus": stratus,
            "jet": jet,
            "shape": (row1 - row0, width),
        }

    def _cascade(b: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        """Intermittency cascade field (casc_n in [0,1], cascade multiplier).

        Breaks masks into discrete sub-elements; half the wind displacement
        (full warp makes sub-elements anisotropic wisps).  Constant floor —
        a cover-dependent floor smoothed high-cover regions into uniform
        painted-smear sheets (proto46 QA).
        """
        x, y, z = b["x"], b["y"], b["z"]
        casc_elong = (
            (CASCADE_STREAK_KM / radius_km)
            * np.clip(b["wmag"] / BILLOW_STREAK_REF_WIND_M_S, 0.0, 1.5)
            * f_casc
        )
        casc_n = 0.5 + 0.25 * (
            _streak_pair(
                (x + b["disp_x"]) * f_casc,
                (y + b["disp_y"]) * f_casc,
                (z + b["disp_z"]) * f_casc,
                b["dirx"],
                b["diry"],
                b["dirz"],
                casc_elong,
                seed_casc,
                CASCADE_OCTAVES,
                CASCADE_GAIN,
            )
        )
        # Convective regimes get crisper cascade contrast (cauliflower),
        # trade/stratocumulus regimes softer (type diversity).
        casc_amp = CASCADE_AMP * np.clip(
            (0.75 + 0.60 * np.clip(b["cov_local"] / 0.5, 0.0, 1.0))
            * (
                1.0
                + 0.35 * b["convect"]
                + 0.30 * b["trades"]
                - 0.45 * b["stratus"]
                - 0.35 * b["frontal"]
            ),
            0.35,
            2.0,
        )
        cascade = CASCADE_FLOOR + casc_amp * np.power(np.clip(casc_n, 0.0, 1.0), CASCADE_POWER)
        return casc_n, cascade

    # ---------------- pass A: global density field ----------------
    density_g = np.empty((height, width), dtype=np.float32)
    sum_, sumsq_ = 0.0, 0.0
    for row0 in range(0, height, BAND_ROWS):
        row1 = min(row0 + BAND_ROWS, height)
        b = _band_basis(row0, row1)
        _, cascade = _cascade(b)
        # Size crossfade biased toward small clusters — big coherent systems
        # are the deck/shield layers' job, clusters supply the fine grain.
        size_mix = np.clip(
            0.1
            + 0.30 * b["trades"]
            - 0.30 * b["frontal"]
            + 1.2
            * (
                0.5
                + 0.5
                * fbm_on_points(
                    b["x"] * f_size,
                    b["y"] * f_size,
                    b["z"] * f_size,
                    seed=seed_size,
                    octaves=2,
                    persistence=FBM_GAIN,
                )
            ),
            0.0,
            1.0,
        )
        # Directional organisation: cloud streets (trades), frontal bands and
        # jet cirrus stretch along the flow; deep convection stays isotropic.
        elong_mult = np.clip(
            1.0 + 1.2 * b["trades"] + 0.8 * b["frontal"] + 1.0 * b["jet"] - 0.7 * b["convect"],
            0.25,
            3.0,
        )
        elong = (
            (BILLOW_STREAK_KM / radius_km)
            * np.clip(b["wmag"] / BILLOW_STREAK_REF_WIND_M_S, 0.0, 1.5)
            * elong_mult
            * f_billow
        )
        bx = (b["x"] + b["disp_x"]) * f_billow
        by = (b["y"] + b["disp_y"]) * f_billow
        bz = (b["z"] + b["disp_z"]) * f_billow
        d_big = _streaked_fbm(
            bx,
            by,
            bz,
            b["dirx"],
            b["diry"],
            b["dirz"],
            elong,
            1.0,
            seed,
            BILLOW_OCTAVES,
            DENSITY_GAIN,
        )
        d_small = _streaked_fbm(
            bx,
            by,
            bz,
            b["dirx"],
            b["diry"],
            b["dirz"],
            elong,
            SIZE_SMALL_FACTOR,
            seed + 18,
            BILLOW_OCTAVES,
            DENSITY_GAIN,
        )
        density = (0.5 + 0.5 * (d_big * (1.0 - size_mix) + d_small * size_mix)) * cascade
        band = density.reshape(b["shape"])
        density_g[row0:row1] = band.astype(np.float32)
        sum_ += float(density.sum())
        sumsq_ += float((density * density).sum())

    n_total = height * width
    g_mean = sum_ / n_total
    g_sigma = max(float(np.sqrt(max(sumsq_ / n_total - g_mean * g_mean, 0.0))), 1e-3)
    # Global rank distribution: threshold field is continuous across bands.
    sorted_g = np.sort(density_g.ravel())
    npts_g = sorted_g.size

    # ---------------- pass B: alpha assembly ----------------
    alpha = np.empty((height, width), dtype=np.float64)
    for row0 in range(0, height, BAND_ROWS):
        row1 = min(row0 + BAND_ROWS, height)
        b = _band_basis(row0, row1)
        x, y, z = b["x"], b["y"], b["z"]
        disp_x, disp_y, disp_z = b["disp_x"], b["disp_y"], b["disp_z"]
        dirx, diry, dirz = b["dirx"], b["diry"], b["dirz"]
        wmag = b["wmag"]
        cov_local = b["cov_local"]
        casc_n, cascade = _cascade(b)
        density = density_g[row0:row1].ravel().astype(np.float64)
        npts = density.size

        # ELEMENT-based opacity: cover = the CLEAR fraction (pixels below the
        # per-pixel global-rank threshold stay sky — exact by construction);
        # thickness = exponential inverse-CDF over the rank of a MESO-scale
        # field, so the pooled alpha histogram stays log-linear (Blue Marble
        # QA) while individual elements keep crisp edges and coarse interiors.
        rank = np.clip((1.0 - np.clip(cov_local, 1e-4, 0.999)) * npts_g, 0, npts_g - 1).astype(
            np.int64
        )
        t = sorted_g[rank]
        mask = _smoothstep(
            t - EDGE_SOFTNESS_SIGMA * g_sigma, t + EDGE_SOFTNESS_SIGMA * g_sigma, density
        )
        meso_elong = (
            (MESO_STREAK_KM / radius_km)
            * np.clip(wmag / BILLOW_STREAK_REF_WIND_M_S, 0.0, 1.5)
            * f_meso
        )
        meso = 0.5 + 0.25 * (
            _streak_pair(
                (x + disp_x) * f_meso,
                (y + disp_y) * f_meso,
                (z + disp_z) * f_meso,
                dirx,
                diry,
                dirz,
                meso_elong,
                seed_meso,
                MESO_OCTAVES,
                DENSITY_GAIN,
            )
        )
        u_m = np.clip(np.searchsorted(np.sort(meso), meso) / npts, 0.0, 1.0)
        thick = np.log1p(-u_m * (1.0 - ALPHA_EXP_EPS)) / math.log(ALPHA_EXP_EPS)
        alpha_max = np.minimum(1.0 - np.exp(-LOWCLOUD_OPACITY_K * cov_local), ALPHA_MAX_CAP)
        a_low = alpha_max * thick * mask
        # Faint fringe just outside element edges (kept small — a wide veil
        # is exactly the fog artefact the user flagged).
        veil = (
            VEIL_AMP
            * cov_local
            * _smoothstep(t - 3.0 * g_sigma, t - EDGE_SOFTNESS_SIGMA * g_sigma, density)
        )
        a_low = np.clip(a_low + veil, 0.0, 1.0)

        # Deck layer: planet-scale bright sheets as a SEPARATE alpha layer,
        # max-blended (over-blending two exponentials piles a histogram
        # shelf, proto37 QA).  Coherent cascade-modulated mask at lambda
        # 7000 km, area superlinear in cover, thickness bright with internal
        # texture — the India-size systems of the reference.
        deck = (
            0.5
            + 0.5
            * fbm_on_points(
                (x + disp_x) * f_deck,
                (y + disp_y) * f_deck,
                (z + disp_z) * f_deck,
                seed=seed_deck,
                octaves=DECK_OCTAVES,
                persistence=DENSITY_GAIN,
            )
        ) * cascade
        deck_cov = np.clip(
            DECK_AREA_SHARE * np.power(np.clip(cov_local, 0.0, 1.0), DECK_AREA_EXP),
            0.0,
            0.85,
        )
        sd = max(float(deck.std()), 1e-3)
        rank_k = np.clip((1.0 - np.clip(deck_cov, 1e-4, 0.999)) * npts, 0, npts - 1).astype(
            np.int64
        )
        t_k = np.sort(deck)[rank_k]
        m_deck = _smoothstep(t_k - EDGE_SOFTNESS_SIGMA * sd, t_k + EDGE_SOFTNESS_SIGMA * sd, deck)
        u_k = np.clip(
            (np.searchsorted(np.sort(deck), deck) / npts - (1.0 - deck_cov))
            / np.maximum(deck_cov, 1e-4),
            0.0,
            1.0,
        )
        thick_k = np.log1p(-u_k * (1.0 - DECK_EXP_EPS)) / math.log(DECK_EXP_EPS)
        a_deck = (
            np.minimum(alpha_max * DECK_THICK_BOOST, ALPHA_MAX_CAP)
            * (0.35 + 0.65 * thick_k)
            * m_deck
        )
        a_low = np.maximum(a_low, a_deck)

        # Shield layer: the VERY large coherent systems (India-size frontal
        # shields / cyclone commas) that the fully cascade-shredded deck never
        # forms (proto47 QA).  Light cascade modulation keeps coherence while
        # retaining internal texture; the band-pass cover gate keeps it out of
        # the ITCZ (cellular convection regime) and the deserts.
        shield_f = circ_km / SHIELD_WAVELENGTH_KM
        shield = (
            0.5
            + 0.5
            * fbm_on_points(
                (x + disp_x) * shield_f,
                (y + disp_y) * shield_f,
                (z + disp_z) * shield_f,
                seed=seed + 23,
                octaves=SHIELD_OCTAVES,
                persistence=DENSITY_GAIN,
            )
        ) * (0.80 + 0.40 * np.clip(casc_n, 0.0, 1.0))
        band_gate = np.clip((cov_local - 0.20) / 0.20, 0.0, 1.0) * np.clip(
            (0.80 - cov_local) / 0.25, 0.0, 1.0
        )
        shield_cov = np.clip(SHIELD_AREA_SHARE * band_gate, 0.0, 0.60)
        ss = max(float(shield.std()), 1e-3)
        rank_s = np.clip((1.0 - np.clip(shield_cov, 1e-4, 0.999)) * npts, 0, npts - 1).astype(
            np.int64
        )
        t_s = np.sort(shield)[rank_s]
        m_shield = _smoothstep(
            t_s - EDGE_SOFTNESS_SIGMA * ss, t_s + EDGE_SOFTNESS_SIGMA * ss, shield
        )
        a_shield = (
            np.minimum(alpha_max * SHIELD_THICK_BOOST, ALPHA_MAX_CAP)
            * (0.35 + 0.65 * np.clip(0.25 + 0.75 * casc_n, 0.0, 1.0))
            * m_shield
        )
        a_low = np.maximum(a_low, a_shield)

        # ---- texture blocks: applied to the BLENDED field so every layer
        # ---- (cluster, deck, shield) receives erosion/grain/MCC/Worley.
        # Detail layer: edge erosion + interior carving (Frostbite
        # shape/erosion split; interior weight keeps sheet interiors from
        # reading as flat paint, native-crop QA proto60).
        detail = fbm_on_points(
            (x + disp_x) * f_detail,
            (y + disp_y) * f_detail,
            (z + disp_z) * f_detail,
            seed=seed_detail,
            octaves=DETAIL_OCTAVES,
            persistence=DENSITY_GAIN,
        )
        edge_weight = np.clip(0.35 + 0.65 * (1.0 - 2.0 * np.abs(a_low - 0.5)), 0.0, 1.0)
        a_low = np.clip(a_low - DETAIL_ERODE * (0.5 + 0.5 * detail) * edge_weight, 0.0, 1.0)
        # Multiplicative grain, stronger in bright cores (cloud-top relief).
        grain_amp = GRAIN_AMP * (0.6 + 0.8 * np.clip(a_low / 0.5, 0.0, 1.0))
        a_low = np.clip(a_low * (1.0 + grain_amp * detail), 0.0, ALPHA_MAX_CAP)

        # MCC cellular organisation in marine low-cloud regimes.
        n_mcc = fbm_on_points(
            (x + 0.5 * disp_x) * f_mcc,
            (y + 0.5 * disp_y) * f_mcc,
            (z + 0.5 * disp_z) * f_mcc,
            seed=seed_mcc,
            octaves=MCC_OCTAVES,
            persistence=FBM_GAIN,
        )
        walls = np.exp(-((n_mcc / 0.18) ** 2))  # ridged: cell walls near n=0
        mix_field = 0.5 + 0.5 * fbm_on_points(
            x * f_mcc / 6.0,
            y * f_mcc / 6.0,
            z * f_mcc / 6.0,
            seed=seed_mcc + 1,
            octaves=2,
            persistence=FBM_GAIN,
        )
        # closed cells: bright centres (1-walls); open cells: bright walls.
        cell = (1.0 - 2.0 * walls) * (1.0 - 2.0 * mix_field)
        gate = (
            _smoothstep(MCC_GATE_LO, MCC_GATE_LO + 0.10, cov_local)
            * _smoothstep(MCC_GATE_HI, MCC_GATE_HI - 0.15, cov_local)
            * (0.25 + 0.75 * b["stratus"])
        )
        a_low = np.clip(
            a_low * (1.0 + MCC_AMP * cell * gate * np.clip(a_low / 0.15, 0.0, 1.0)),
            0.0,
            ALPHA_MAX_CAP,
        )

        # Worley cellular shaping: carve gaps along cell rims in convective
        # and trade regimes so elements read as discrete convex blobs.
        w1 = worley_on_points(
            (x + disp_x) * f_worley,
            (y + disp_y) * f_worley,
            (z + disp_z) * f_worley,
            seed=seed + 25,
            jitter=0.85,
        )
        blob = np.power(np.clip(1.0 - w1 / 0.75, 0.0, 1.0), 0.7)
        w_regime = np.clip(b["trades"] + b["convect"], 0.0, 1.0)
        a_low = np.clip(
            a_low * (1.0 - WORLEY_MIX * w_regime * (1.0 - blob) * np.clip(a_low / 0.2, 0.0, 1.0)),
            0.0,
            ALPHA_MAX_CAP,
        )

        # Sub-grid broken cloud: unresolved small cumulus / thin margins that
        # at satellite pixel scale (2-10 km) produce PARTIAL coverage — the
        # physical source of the reference's abundant 0.02-0.2 opacity
        # population (histogram decomposition 2026-10-19: the element
        # restructure + fog-fix veil/haze cuts collapsed our low bins ~10x).
        # Textured (cascade-modulated, fine wavelength), NOT a smooth veil —
        # the smooth-veil version was the fog artefact.
        sub_d = (
            0.5
            + 0.5
            * fbm_on_points(
                (x + disp_x) * f_sub,
                (y + disp_y) * f_sub,
                (z + disp_z) * f_sub,
                seed=seed + 26,
                octaves=SUB_OCTAVES,
                persistence=DENSITY_GAIN,
            )
        ) * (0.6 + 0.8 * np.clip(casc_n, 0.0, 1.0))
        f_sub_frac = np.clip(cov_local * SUB_AREA_FACTOR, 1e-4, 0.85)
        rank_sub = np.clip((1.0 - f_sub_frac) * npts, 0, npts - 1).astype(np.int64)
        t_sub = np.sort(sub_d)[rank_sub]
        sd_sub = max(float(sub_d.std()), 1e-3)
        m_sub = _smoothstep(t_sub - 1.0 * sd_sub, t_sub + 1.0 * sd_sub, sub_d)
        a_sub = (
            SUB_MAX_ALPHA
            * m_sub
            * (0.3 + 0.7 * np.clip(casc_n, 0.0, 1.0))
            * np.clip((cov_local - 0.05) / 0.15, 0.0, 1.0)
        )
        a_low = 1.0 - (1.0 - a_low) * (1.0 - a_sub)

        # Compact bright cores: the top ~1% density rank in deep-cloud
        # regions — convective towers / comma heads.  Real imagery keeps a
        # small near-white population (excess >0.8) that our alpha cap and
        # exponential tail starved (proto64 QA: >0.8 fraction 0 vs ref 2e-4).
        # Coherent bright cores: rank on a ~25 km-SMOOTHED density so cores
        # are 50-100 km blobs (comma heads / MCS towers), not single-pixel
        # spikes that alias away at any preview scale (proto66 QA).
        from scipy.ndimage import gaussian_filter as _gf

        sig_px = max(CORE_SMOOTH_KM / (circ_km / width), 1.0)
        density_s = _gf(density.reshape(b["shape"]), sig_px).ravel()
        # Band-pass gate: bright cores belong to BROKEN-cloud regimes (isolated
        # towers over dark ocean, system margins) — cores embedded in shield
        # interiors get their local baseline lifted by the surrounding cloud
        # and never produce excess >0.8 (v3-8k fine-bin QA: 0.8-0.9 empty vs
        # ref 2.1e-4).
        gate_core = _smoothstep(0.08, 0.15, cov_local) * _smoothstep(0.32, 0.22, cov_local)
        # Cores = top quantiles of the smoothed density WITHIN the gated
        # regime, not band-global ranks: band-global top ranks fall inside
        # shields/ITCZ where the gate is zero, so cores never fired in
        # broken-cloud regimes (proto68-73 QA: >0.8 excess stayed empty).
        reg = gate_core > 0.5
        if int(reg.sum()) > 1000:
            q_lo_c = float(np.quantile(density_s[reg], 0.97))
            q_hi_c = float(np.quantile(density_s[reg], 0.995))
        else:
            q_lo_c, q_hi_c = 1.0, 0.0
        m_core = np.clip((density_s - q_lo_c) / max(q_hi_c - q_lo_c, 1e-6), 0.0, 1.0) * gate_core
        a_low = np.maximum(a_low, CORE_ALPHA * m_core)

        # Cirrus layer: two taps ±streak along the wind direction, averaged —
        # elongates the texture along the flow.  Concentrated in/around cloudy
        # systems (strong cover gating; proto11 showed an ungated veil reads
        # as full-disk marbling), stronger where wind is fast, never occludes.
        scale = np.clip(wmag / CIRRUS_REF_WIND_M_S, 0.0, 2.0)
        streak = (CIRRUS_STREAK_KM / radius_km) * scale * (1.0 + 1.0 * b["jet"]) * f_cirrus
        cx = (x + disp_x) * f_cirrus
        cy = (y + disp_y) * f_cirrus
        cz = (z + disp_z) * f_cirrus
        c1 = fbm_on_points(
            cx + dirx * streak,
            cy + diry * streak,
            cz + dirz * streak,
            seed=seed_cirrus,
            octaves=CIRRUS_OCTAVES,
            persistence=DENSITY_GAIN,
        )
        c2 = fbm_on_points(
            cx - dirx * streak,
            cy - diry * streak,
            cz - dirz * streak,
            seed=seed_cirrus,
            octaves=CIRRUS_OCTAVES,
            persistence=DENSITY_GAIN,
        )
        density_c = 0.5 + 0.25 * (c1 + c2)
        a_cir = (
            _smoothstep(CIRRUS_THRESHOLD_LO, CIRRUS_THRESHOLD_HI, density_c)
            * (CIRRUS_BASE_ALPHA + CIRRUS_WIND_ALPHA * np.clip(wmag / CIRRUS_REF_WIND_M_S, 0, 1))
            * (0.25 + 0.75 * cov_local)
        )

        # Diffuse haze floor: thin fine-textured veil everywhere (weakly
        # cover-gated), gives clear sky the micro-texture the reference has.
        haze = fbm_on_points(
            (x + disp_x) * (circ_km / HAZE_WAVELENGTH_KM),
            (y + disp_y) * (circ_km / HAZE_WAVELENGTH_KM),
            (z + disp_z) * (circ_km / HAZE_WAVELENGTH_KM),
            seed=seed + 20,
            octaves=HAZE_OCTAVES,
            persistence=DENSITY_GAIN,
        )
        # Squared: patchy veil with dark gaps between — a uniform haze floor
        # lifts the clear-ocean luminance base and caps achievable excess
        # at ~0.75, erasing the >0.8 population (proto72 probe).
        a_haze = HAZE_MAX_ALPHA * (0.5 + 0.5 * haze) ** 2 * (0.50 + 0.50 * cov_local)

        alpha[row0:row1] = (1.0 - (1.0 - a_low) * (1.0 - a_cir) * (1.0 - a_haze)).reshape(
            row1 - row0, width
        )

    return CloudProducts(alpha=alpha, cover=cover_grid, width=width, height=height)


# ---------------------------------------------------------------------------
# Conditioning: mesh fields → equirect grids
# ---------------------------------------------------------------------------


def conditioning_grids(
    mesh: CVTMesh,
    indices: np.ndarray,
    *,
    smooth_rounds: int = MESH_SMOOTH_ROUNDS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Rasterise (cover, wind_east, wind_north, ocean, dp) onto the export grid.

    Fields are smoothed on the mesh adjacency graph first (uniform in km),
    then sampled nearest-cell — no Voronoi plateaus survive at output scale.
    ``indices`` comes from ``map.export.export_cell_index_grid``.  ``ocean``
    and ``dp`` (SLP anomaly, hPa) feed the cloud-regime weights.
    """

    def col(field: str, default: float = 0.0) -> np.ndarray:
        return np.array(
            [
                default if getattr(c, field, None) is None else float(getattr(c, field))
                for c in mesh.cells
            ],
            dtype=np.float64,
        )

    precip = smooth_mesh_field(mesh, col("precipitation_mm"), smooth_rounds)
    dp = smooth_mesh_field(mesh, col("pressure_anomaly_annual_hpa"), smooth_rounds)
    u = smooth_mesh_field(mesh, col("wind_east_m_s"), smooth_rounds)
    v = smooth_mesh_field(mesh, col("wind_north_m_s"), smooth_rounds)
    ocean = np.asarray([c.elevation < 0.0 for c in mesh.cells], dtype=np.float64)
    cover = large_scale_cover(precip, dp)
    return cover[indices], u[indices], v[indices], ocean[indices], dp[indices]


# ---------------------------------------------------------------------------
# Globe preview (orthographic composite over a quick surface base)
# ---------------------------------------------------------------------------


#: Surface micro-texture for the placeholder base map: real full-disk imagery
#: carries surface detail (vegetation mottle, desert pattern, ocean colour
#: variation) at 10–100 km scales, which dominates the reference's mid-band
#: gradient statistics in clear-sky areas; a flat cell fill leaves our
#: gradient p50 at a quarter of the reference (cloud-compare metric).
SURFACE_LAND_TEX_KM = 60.0
SURFACE_LAND_TEX_AMP = 0.10
SURFACE_OCEAN_TEX_KM = 200.0
SURFACE_OCEAN_TEX_AMP = 0.06


def surface_base_rgb(
    mesh: CVTMesh,
    indices: np.ndarray,
    sea_level_m: float,
    *,
    radius_km: float = 6371.0,
    seed: int = 99,
    texture: bool = True,
) -> np.ndarray:
    """Quick global surface base map (h, w, 3) float ∈ [0, 1].

    Biome colours on land (same table as the satellite chain), a two-stop
    bathymetric gradient at sea, flat ice white, plus a spherical-fBm
    luminance micro-texture (land finer/stronger than ocean).  Deliberately
    utilitarian — the look-dev subject here is the cloud layer, not the
    surface (the authoritative surface comes from the global-canvas chain,
    S5); the texture exists so preview gradient statistics are commensurable
    with real imagery.
    """
    from dreamulator.media.satellite_color import (
        BIOME_COLORS,
        ICE_COLOR,
        MISSING_COLOR,
        SEA_DEEP,
        SEA_SHALLOW,
    )

    n = mesh.num_cells
    rgb = np.zeros((n, 3), dtype=np.float64)
    for i, c in enumerate(mesh.cells):
        if c.elevation >= sea_level_m:
            name = c.biome if isinstance(c.biome, str) else None
            rgb[i] = BIOME_COLORS.get(name or "", MISSING_COLOR)
        else:
            depth = sea_level_m - c.elevation
            t = min(depth / 400.0, 1.0)
            shallow = np.array(SEA_SHALLOW, dtype=np.float64)
            deep = np.array(SEA_DEEP, dtype=np.float64)
            rgb[i] = shallow + (deep - shallow) * t
    ice = np.array([c.biome == "ice" for c in mesh.cells], dtype=bool)
    rgb[ice] = np.array(ICE_COLOR, dtype=np.float64)
    base = rgb[indices] / 255.0
    if not texture:
        return np.asarray(base, dtype=np.float64)

    height, width = indices.shape
    land = np.asarray([c.elevation >= sea_level_m for c in mesh.cells], dtype=bool)[indices]
    circ = 2.0 * math.pi * radius_km
    f_land = circ / SURFACE_LAND_TEX_KM
    f_ocean = circ / SURFACE_OCEAN_TEX_KM
    lon = ((np.arange(width, dtype=np.float64) + 0.5) / width) * (2.0 * math.pi) - math.pi
    mod = np.ones((height, width), dtype=np.float64)
    for row0 in range(0, height, 512):
        row1 = min(row0 + 512, height)
        lat = (0.5 - (np.arange(row0, row1, dtype=np.float64) + 0.5) / height) * math.pi
        cos_lat = np.cos(lat)[:, None]
        x = np.ascontiguousarray((cos_lat * np.cos(lon)[None, :]).ravel())
        y = np.ascontiguousarray(
            np.broadcast_to(np.sin(lat)[:, None], (row1 - row0, width)).ravel()
        )
        z = np.ascontiguousarray((cos_lat * np.sin(lon)[None, :]).ravel())
        t_land = fbm_on_points(
            x * f_land, y * f_land, z * f_land, seed=seed, octaves=4, persistence=DENSITY_GAIN
        )
        t_ocean = fbm_on_points(
            x * f_ocean,
            y * f_ocean,
            z * f_ocean,
            seed=seed + 1,
            octaves=3,
            persistence=DENSITY_GAIN,
        )
        band_land = land[row0:row1].ravel()
        tex = np.where(
            band_land,
            SURFACE_LAND_TEX_AMP * t_land,
            SURFACE_OCEAN_TEX_AMP * t_ocean,
        )
        mod[row0:row1] = (1.0 + tex).reshape(row1 - row0, width)
    return np.asarray(np.clip(base * mod[..., None], 0.0, 1.0), dtype=np.float64)


def render_globe_preview(
    surface_rgb: np.ndarray,
    cloud_alpha: np.ndarray,
    *,
    res: int = 1600,
    center_lon_deg: float = 90.0,
    center_lat_deg: float = 15.0,
    sun_lon_deg: float | None = None,
    sun_lat_deg: float = 20.0,
    cloud_rgb: tuple[int, int, int] = CLOUD_RGB,
) -> np.ndarray:
    """Orthographic globe view, compositing clouds over the surface base.

    Returns an (res, res, 3) uint8 sRGB image.  Lighting is a Lambert term
    with a soft terminator; a thin limb glow stands in for the atmosphere
    shell (Bruneton/Hillaire scattering is layer L5, out of prototype scope).
    """
    from scipy.ndimage import map_coordinates

    h, w = surface_rgb.shape[:2]
    lam_c = math.radians(center_lon_deg)
    phi_c = math.radians(center_lat_deg)
    if sun_lon_deg is None:
        sun_lon_deg = center_lon_deg - 25.0
    lam_s = math.radians(sun_lon_deg)
    phi_s = math.radians(sun_lat_deg)

    # Camera basis in the mesh xyz convention (x=cosφcosλ, y=sinφ, z=cosφsinλ).
    f = np.array(
        [math.cos(phi_c) * math.cos(lam_c), math.sin(phi_c), math.cos(phi_c) * math.sin(lam_c)]
    )
    r = np.array([-math.sin(lam_c), 0.0, math.cos(lam_c)])  # screen right = east
    u = np.cross(r, f)  # screen up = north
    sun = np.array(
        [math.cos(phi_s) * math.cos(lam_s), math.sin(phi_s), math.cos(phi_s) * math.sin(lam_s)]
    )

    half = res / 2.0
    py, px = np.mgrid[0:res, 0:res].astype(np.float64)
    vx = (px + 0.5 - half) / (half * 0.92)  # globe fills 92% of the frame
    vy = (half - py - 0.5) / (half * 0.92)
    rr = vx * vx + vy * vy
    disk = rr <= 1.0
    vz = np.sqrt(np.clip(1.0 - rr, 0.0, None))

    # View-space (vx, vy, vz) → world xyz.
    n_w = vx[..., None] * r + vy[..., None] * u + vz[..., None] * f
    lon = np.arctan2(n_w[..., 2], n_w[..., 0])
    lat = np.arcsin(np.clip(n_w[..., 1], -1.0, 1.0))
    col = (lon + math.pi) / (2.0 * math.pi) * w - 0.5
    row = (0.5 - lat / math.pi) * h - 0.5

    def sample(img: np.ndarray) -> np.ndarray:
        if img.ndim == 2:
            return np.asarray(
                map_coordinates(img, [row, col], order=1, mode="grid-wrap"), dtype=np.float64
            )
        chans = [
            map_coordinates(img[..., c], [row, col], order=1, mode="grid-wrap")
            for c in range(img.shape[2])
        ]
        return np.stack(chans, axis=-1)

    surf = sample(surface_rgb)
    a_cloud = np.clip(sample(cloud_alpha), 0.0, 1.0)[..., None]
    tint = np.array(cloud_rgb, dtype=np.float64) / 255.0

    # Lighting: soft-terminator Lambert, floor of 16% on the night side —
    # real full-disk imagery keeps the night hemisphere readable (user QA:
    # 6% reads as a black bite).  City lights are L5, not here.
    cos_i = np.zeros((res, res))
    cos_i[disk] = (n_w[..., 0] * sun[0] + n_w[..., 1] * sun[1] + n_w[..., 2] * sun[2])[disk]
    light = 0.16 + 0.84 * _smoothstep(-0.06, 0.22, cos_i)[..., None]

    # Clouds: lambert with a slight forward-scatter brightening (clouds are
    # brighter than lambertian near the limb on the day side).  Night-side
    # clouds get no additive lift — a floor term here reads as star-field
    # noise on the dark hemisphere.
    light_cloud = np.clip(light * 1.08, 0.0, 1.1)

    # Pseudo-3D cloud-top lighting (preview only — L5 does real volumetrics):
    # alpha as a cloud-top height proxy, screen-space normals from its
    # gradient, Lambert against the sun vector.  Much of the perceived
    # "texture" in real satellite imagery is this lighting (sunlit walls,
    # shadowed flanks), not the alpha pattern alone — second research pass
    # 2026-10-19.  Normals read a SMOOTHED alpha (σ a few tex px): responding
    # to the fine erosion notches marbles the whole disk (proto11/12 lesson).
    from scipy.ndimage import gaussian_filter

    h_tex = gaussian_filter(cloud_alpha, PREVIEW_EMBOSS_SMOOTH_PX)
    h0 = sample(h_tex)
    hx = np.asarray(
        map_coordinates(h_tex, [row, col + 1.0], order=1, mode="grid-wrap"), dtype=np.float64
    )
    hy = np.asarray(
        map_coordinates(h_tex, [row + 1.0, col], order=1, mode="grid-wrap"), dtype=np.float64
    )
    a_flat = np.clip(h0, 0.0, 1.0)
    s_scr = np.array([np.dot(sun, r), np.dot(sun, u), np.dot(sun, f)])
    s_scr = s_scr / max(np.linalg.norm(s_scr), 1e-9)
    nx = -(hx - h0) * PREVIEW_RELIEF
    ny = -(hy - h0) * PREVIEW_RELIEF
    nlen = np.sqrt(nx * nx + ny * ny + 1.0)
    shade = np.clip((nx * s_scr[0] + ny * s_scr[1] + s_scr[2]) / nlen, 0.0, 1.0)
    term = 0.40 + 1.10 * np.power(shade, 0.9)
    # Gate by local alpha: shading thin haze marbles the whole disk (proto11).
    gate = np.clip(a_flat / 0.15, 0.0, 1.0)
    thickness = PREVIEW_THICK_BASE + PREVIEW_THICK_AMP * a_flat
    light_cloud = np.clip(
        light_cloud * (1.0 + gate * (term * thickness - 1.0))[..., None], 0.0, 1.30
    )

    rgb = surf * light * (1.0 - a_cloud) + tint * light_cloud * a_cloud

    # Atmosphere limb glow: thin blue-ish shell fading with (1 − n·view).
    limb = np.zeros((res, res))
    limb[disk] = 1.0 - vz[disk]
    glow = np.clip(1.0 - limb / 0.06, 0.0, 1.0) ** 2
    atmo = np.array([0.45, 0.62, 0.85])
    rgb = rgb + atmo * glow[..., None] * 0.35 * np.clip(light, 0.0, 1.0)

    rgb[~disk] = 0.0
    return np.asarray(np.clip(rgb, 0.0, 1.0) * 255.0, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Orchestration (CLI leg)
# ---------------------------------------------------------------------------


def clouds_globe(
    mesh: CVTMesh,
    out_dir: Path,
    *,
    radius_km: float,
    sea_level_m: float = 0.0,
    width: int = 8192,
    height: int = 4096,
    seed: int = 7,
    globe_res: int = 1600,
    center_lon_deg: float = 90.0,
    center_lat_deg: float = 15.0,
    sun_lon_deg: float | None = None,
    sun_lat_deg: float = 20.0,
    cover_scale: float = 1.0,
    cyclones: Sequence[Cyclone] | None = None,
    cyclone_seed: int = 41,
    provenance: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Run the full L2 prototype: texture + cover field + globe preview.

    ``cyclones`` optionally overlays L3 parametric cyclone templates on the
    texture (a synthetic track set is a QA placeholder until the L1 layer pack
    provides real tracks).

    Writes ``clouds.png`` (RGBA straight-alpha equirect), ``cloud_cover.png``
    (8-bit greyscale placeholder cover field), ``surface.png`` (equirect
    surface base), ``globe.png`` (orthographic preview) and ``meta.json``
    (seed, parameters, source) to ``out_dir``.  ``cover_scale`` multiplies the
    conditioning cover field — 0 skips texture synthesis entirely (surface /
    biome QA mode: only ``surface.png`` + cloud-free ``globe.png``).
    """
    from PIL import Image

    from dreamulator.map.export import build_export_tree, export_cell_index_grid, save_rgba_png

    tree = build_export_tree(mesh)
    indices = export_cell_index_grid(mesh, width, height, tree=tree)
    out_dir.mkdir(parents=True, exist_ok=True)

    surface = surface_base_rgb(mesh, indices, sea_level_m, radius_km=radius_km)
    surf8 = np.asarray(np.clip(surface, 0.0, 1.0) * 255.0, dtype=np.uint8)
    Image.fromarray(surf8, "RGB").save(str(out_dir / "surface.png"))

    paths: dict[str, Path] = {"surface": out_dir / "surface.png"}
    if cover_scale > 0.0:
        cover, u, v, oce, dp = conditioning_grids(mesh, indices)
        cover = np.clip(cover * cover_scale, 0.0, 1.0)
        products = cloud_texture_equirect(cover, u, v, oce, dp, radius_km=radius_km, seed=seed)
        alpha = products.alpha
        if cyclones:
            from dreamulator.media.cyclone_render import (
                cyclone_alpha,
                cyclone_clear,
                cyclone_envelope,
            )

            # Synthetic tracks do not know the coastline; drop tropical
            # centres that land on a continent (L1 tracks never do).
            rows = np.clip(
                ((90.0 - np.array([c.lat_deg for c in cyclones])) / 180.0 * height), 0, height - 1
            ).astype(int)
            cols = np.clip(
                ((np.array([c.lon_deg for c in cyclones]) + 180.0) / 360.0 * width), 0, width - 1
            ).astype(int)
            cyclones = [
                c
                for c, r, q in zip(cyclones, rows, cols, strict=True)
                if c.kind != "tropical" or oce[r, q] > 0.5
            ]
        if cyclones:
            template = cyclone_alpha(
                list(cyclones),
                height=height,
                width=width,
                radius_km=radius_km,
                seed=cyclone_seed,
            )
            clear = cyclone_clear(list(cyclones), height=height, width=width, radius_km=radius_km)
            envelope = cyclone_envelope(
                list(cyclones),
                height=height,
                width=width,
                radius_km=radius_km,
                seed=cyclone_seed,
            )
            # Inside a storm the ambient deck is modulated (not replaced) by the
            # template: band troughs thin the deck, crests brighten it, so the
            # cyclone reads without punching a clear moat in the cloud field.
            base = alpha * (1.0 - clear)
            # Inside the (irregular) storm footprint the template may only
            # brighten: max() keeps the ambient deck where the template is thin,
            # so there is no dark ring or painted halo around the edge.
            alpha = np.clip(
                base * (1.0 - envelope) + envelope * np.maximum(base, template), 0.0, 1.0
            )
            Image.fromarray((template * 255.0).astype(np.uint8), "L").save(
                str(out_dir / "cyclone_template.png")
            )
            paths["cyclone_template"] = out_dir / "cyclone_template.png"
            Image.fromarray((envelope * 255.0).astype(np.uint8), "L").save(
                str(out_dir / "cyclone_envelope.png")
            )
            paths["cyclone_envelope"] = out_dir / "cyclone_envelope.png"
        rgba = np.empty((height, width, 4), dtype=np.uint8)
        rgba[..., 0] = CLOUD_RGB[0]
        rgba[..., 1] = CLOUD_RGB[1]
        rgba[..., 2] = CLOUD_RGB[2]
        rgba[..., 3] = (np.clip(alpha, 0.0, 1.0) * 255.0).astype(np.uint8)
        save_rgba_png(rgba, out_dir / "clouds.png")
        Image.fromarray((products.cover * 255.0).astype(np.uint8), "L").save(
            str(out_dir / "cloud_cover.png")
        )
        paths["clouds"] = out_dir / "clouds.png"
        paths["cover"] = out_dir / "cloud_cover.png"
    else:
        alpha = np.zeros((height, width), dtype=np.float64)

    globe = render_globe_preview(
        surface,
        alpha,
        res=globe_res,
        center_lon_deg=center_lon_deg,
        center_lat_deg=center_lat_deg,
        sun_lon_deg=sun_lon_deg,
        sun_lat_deg=sun_lat_deg,
    )
    Image.fromarray(globe, "RGB").save(str(out_dir / "globe.png"))
    paths["globe"] = out_dir / "globe.png"

    meta = {
        "chain": "L2 procedural cloud texture (prototype)",
        "spec": "orbital weather-globe L2 procedural cloud texture",
        "radius_km": radius_km,
        "grid": [width, height],
        "seed": seed,
        "globe": {
            "res": globe_res,
            "center_lon_deg": center_lon_deg,
            "center_lat_deg": center_lat_deg,
            "sun_lon_deg": sun_lon_deg if sun_lon_deg is not None else center_lon_deg - 25.0,
            "sun_lat_deg": sun_lat_deg,
        },
        "params": {
            "billow_wavelength_km": BILLOW_WAVELENGTH_KM,
            "billow_octaves": BILLOW_OCTAVES,
            "warp_wavelength_km": WARP_WAVELENGTH_KM,
            "warp_amplitude_km": WARP_AMPLITUDE_KM,
            "wind_warp_km_per_m_s": WIND_WARP_KM_PER_M_S,
            "cirrus_streak_km": CIRRUS_STREAK_KM,
            "cirrus_ref_wind_m_s": CIRRUS_REF_WIND_M_S,
        },
        "cover_field": "PLACEHOLDER (precip + SLP-anomaly proxy) — replace with GCM layer pack",
        "cover_scale": cover_scale,
        "cyclones": {
            "count": len(cyclones) if cyclones else 0,
            "source": "synthetic placeholder (L1 tracks pending)" if cyclones else None,
            "seed": cyclone_seed if cyclones else None,
        },
        "provenance": provenance or {},
    }
    with (out_dir / "meta.json").open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    paths["meta"] = out_dir / "meta.json"
    return paths
