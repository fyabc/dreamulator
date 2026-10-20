"""Satellite true-color compositor — step ③ of the video chain.

Climate-authoritative colouring: the base land colour comes from the ENGINE's
biome classification (region-pack ``biome.codes.npy``, nearest-neighbour
upsampled onto the Gaea output grid); Gaea 2's masks only modulate texture
(slope → exposed rock, wear, alluvium, rivers, sea depth).  This mirrors the
dayside.studio finding that production chains colour by slope + elevation +
drainage + Köppen — except our climate layer is engine-computed, not painted
(``docs/design/proposals/gaea-refinement.md`` §7 point 3).

Inputs (all on the same square grid — pack ``--out-res`` and the Gaea build
share the window, registration is by construction):

* region pack: ``meta.json``, ``biome.codes.npy``, ``ice.m.npy``;
* Gaea build: ``rivers-h.exr`` (final terrain, 0..1 over the TD Height),
  ``rivers.png`` / ``rivers-depth.png``, ``sea-water.png`` / ``sea-depth.png``,
  ``flow.png`` / ``wear.png`` / ``deposits.png``.

Outputs: ``albedo.png`` (pure colour, for Blender's texture input) and
``preview.png`` (albedo × soft hillshade, for quick eyeballing — lighting is
Blender's job, never bake it into the albedo).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Colour tables (cartographic choices — satellite-imagery style, sRGB)
# ---------------------------------------------------------------------------

#: Whittaker biome → base colour.  Values aim for the hue families seen in
#: true-colour Earth satellite mosaics (e.g. NASA Blue Marble), tuned per
#: biome; they are deliberately muted — modulation layers add the variation.
BIOME_COLORS: dict[str, tuple[int, int, int]] = {
    "tropical_rainforest": (30, 84, 40),
    "tropical_seasonal_forest": (58, 110, 55),
    "tropical_savanna": (150, 148, 86),
    "tropical_desert": (214, 192, 150),
    "temperate_forest": (70, 115, 64),
    "temperate_rainforest": (44, 92, 58),
    "temperate_grassland": (148, 150, 100),
    "temperate_desert": (199, 178, 136),
    "boreal_forest": (56, 90, 68),
    "boreal_shrubland": (118, 128, 100),
    "ice": (240, 244, 247),
    "lake": (58, 110, 158),
    "ocean": (18, 52, 90),  # fallback; sea pixels are depth-graded instead
}

#: Colour for biome code 0 (missing) — neutral mid-grey, easy to spot in QA.
MISSING_COLOR = (128, 128, 128)

#: Sea depth gradient endpoints (shallow → deep) and the depth (m) at which
#: the deep colour is fully reached.
SEA_SHALLOW = (47, 127, 168)
SEA_DEEP = (14, 41, 74)
SEA_DEEP_M = 400.0

#: River colour endpoints (shallow → deep) and reference depth (m).
RIVER_SHALLOW = (110, 141, 158)
RIVER_DEEP = (46, 95, 134)
RIVER_DEEP_M = 8.0

#: Glacier/snow colour and the ice thickness at which it is fully opaque.
ICE_COLOR = (238, 242, 245)
ICE_FULL_M = 5.0

#: Exposed-rock colour and the slope window (rise/run) over which rock fades in.
ROCK_COLOR = (107, 97, 90)
ROCK_SLOPE_LO = 0.35
ROCK_SLOPE_HI = 0.60
ROCK_MAX_WEIGHT = 0.70

#: Boundary de-quantization: engine biomes live on ~54 km Voronoi cells, and a
#: plain blur only softens the straight polygon edges — they still read as
#: polygons.  A coherent-noise domain warp (true amplitude 0.5 cell, wavelength
#: ~1.5 cells, 3 fBm octaves) bends the boundaries into organic ecotone
#: shapes.  Each pixel's class still comes from a nearby engine cell
#: (climate authority is preserved); only the boundary geometry is perturbed.
#: Deterministic via the fixed seed.
WARP_AMPLITUDE_CELLS = 0.65
WARP_WAVELENGTH_CELLS = 1.5
WARP_SEED = 42

#: Post-warp softening of the biome colour layer (the warp bends edges, this
#: gives them ecotone fuzziness — σ20 at 8K ≈ 23 km transition zones).
#: Ice edges get a gentler pass.
BIOME_BLUR_SIGMA_PX = 20.0
ICE_BLUR_SIGMA_PX = 4.0

#: Wear (erosion) modulation: desaturate toward rock.  Deposits (alluvium):
#: warm floodplain tint.  Both normalised to their p99 (masks are
#: heavy-tailed — see the handbook's mask note) and capped at these weights.
WEAR_MAX_WEIGHT = 0.25
DEPOSIT_COLOR = (194, 180, 154)
DEPOSIT_MAX_WEIGHT = 0.30
DEPOSIT_SLOPE_CAP = 0.15  # alluvium only settles on gentle ground

#: Lake rendering: lakes are engine cell unions with no bathymetry, so a flat
#: fill reads as a polygon.  A distance-transform pseudo-depth (centre deep,
#: shore shallow) plus a 2 px edge feather makes them read as water bodies.
#: Palette is freshwater-light — deep-navy lakes read as sea (user-reported).
LAKE_SHALLOW = (128, 166, 196)
LAKE_DEEP = (74, 116, 156)
LAKE_FEATHER_PX = 2.0
#: Channel polylines whose midpoint falls inside a lake (within this
#: distance of its water) are dropped at load time: the lake surface is
#: the water truth there.  Nothing NEAR the lake is clipped — with river
#: and lake inks in one family per sheet (user ruling 2026-10-17, the
#: survey sheet's single-water-colour convention), a channel on the rim
#: land simply reads as a river, and cutting it broke passing rivers into
#: pieces (断续河道).  Hydrology's proper fix — terminus semantics for
#: endorheic basins — is registered separately.
RIVER_LAKE_WATER_KM = 0.3


#: NPP (Miami net primary productivity) drives continuous WITHIN-biome
#: variation: each biome's pixels are brightness-modulated around that biome's
#: own region median, so humid valleys read lusher and dry fringes more
#: stressed — continuous colouring underlain by the engine's T/P fields,
#: without duplicating the classifier (real satellite colour works the same
#: way: hue family from vegetation type, intensity from vigour/NDVI).
NPP_MOD_STRENGTH = 0.22  # ±22% brightness across a biome's 2× NPP spread
NPP_MIN_CELLS = 50  # skip modulation for biomes with too little valid data

#: Vegetation/surface texture (Sentinel-2 / Blue Marble reference: real
#: imagery is never a flat fill — forest canopy mottles at the kilometre
#: scale, dune fields streak at several kilometres, ice sheets barely vary).
#: Per-biome (wavelength_km, amplitude): a seeded fBm brightness field
#: modulates each class's pixels around 1.0.  Amplitudes are deliberately
#: asymmetric to the dark side (shadowed canopy clumps dominate visually).
TEXTURE_SEED = 1234
TEXTURE_PARAMS: dict[str, tuple[float, float]] = {
    "tropical_rainforest": (1.0, 0.16),
    "temperate_rainforest": (1.0, 0.15),
    "tropical_seasonal_forest": (1.3, 0.13),
    "temperate_forest": (1.3, 0.13),
    "boreal_forest": (1.5, 0.12),
    "tropical_savanna": (2.2, 0.11),
    "temperate_grassland": (2.2, 0.10),
    "boreal_shrubland": (2.5, 0.09),
    "tropical_desert": (4.5, 0.09),
    "temperate_desert": (4.5, 0.08),
    "tundra": (2.5, 0.07),
    "ice": (6.0, 0.03),
}
TEXTURE_DEFAULT = (2.0, 0.08)
#: Universal fine grain on all land (sub-pixel-scale soil/canopy speckle —
#: without it smooth plains read as vector fills at full zoom).
TEXTURE_FINE_WAVELENGTH_PX = 3.0
TEXTURE_FINE_AMPLITUDE = 0.025


#: Kilometres per degree of latitude on Earth (πR/180, R = 6371 km — the
#: same default as ``region_export.read_radius_km``).  Fallback for packs
#: whose meta predates the ``radius_km`` field.
EARTH_KM_PER_DEG = math.pi * 6371.0 / 180.0


@dataclass
class ColorizeInputs:
    """All channels on one square grid (N×N); float32 everywhere (8K memory)."""

    height_m: np.ndarray  # physical metres (f32)
    km_per_px: float
    biome_codes: np.ndarray  # uint8
    biome_legend: dict[int, str]  # code → biome name
    sea_water: np.ndarray  # bool
    sea_depth_m: np.ndarray  # f32, ≥ 0
    rivers: np.ndarray  # bool
    river_depth_m: np.ndarray  # f32, ≥ 0
    flow: np.ndarray  # f32 raw Gaea mask values
    wear: np.ndarray
    deposits: np.ndarray
    ice_m: np.ndarray  # f32, ≥ 0
    npp_gc_m2_yr: np.ndarray  # f32, NaN where missing
    # Vector channel segments (M, 2, 2) in km + flows (M,); written by the
    # programmatic-erosion leg for artefact-free river rendering.  None on
    # Gaea builds (mask-contour fallback there).
    river_segments: np.ndarray | None = None
    river_segment_flows: np.ndarray | None = None
    # Per-segment flow regime, uint8 (0 perennial / 1 non-perennial,
    # prog_erosion's RIVER_REGIME_*); None when the leg wrote
    # no regime channel (legacy packs — render everything solid).
    river_segment_regimes: np.ndarray | None = None
    # Endorheic lakes from the programmatic chain (lake.png).  None/empty
    # on Gaea builds.
    lake: np.ndarray | None = None
    # Engine cell pitch in grid pixels (set by load_inputs; 0.0 when
    # unknown).  Sheet legs scale their ecotone blur to this so transitions
    # keep a fixed fraction of a cell at any resolution.
    cell_px: float = 0.0
    # Kilometres per degree of latitude (π·radius/180; set by load_inputs
    # from meta ``radius_km``) — graticule and axis math are planet-correct.
    km_per_deg: float = EARTH_KM_PER_DEG
    # Window projection from meta (pack v4+: "azimuthal_equidistant"; legacy
    # packs and pre-v4 builders: "equirect").  Graticule legs dispatch on it.
    projection: str = "equirect"
    # Lake freeze regime: months per year with monthly mean air temperature
    # below 0 °C (uint8 0-12), nearest-sampled onto the grid — a class
    # channel, never smoothed.  12 = perennially ice-covered.  None on packs
    # exported without a monthly climate series.
    lake_ice_months: np.ndarray | None = None


def _to_rgb(colors: list[tuple[int, int, int]]) -> np.ndarray:
    # float32 everywhere below: at 8K an f64 RGB layer is 1.5 GB and the
    # blends would hold several at once — f32 halves that with no visual cost.
    return np.asarray(colors, dtype=np.float32) / 255.0


def _smoothstep(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def _p99_normalize(mask: np.ndarray) -> np.ndarray:
    """Heavy-tailed Gaea mask → 0..1 by its 99th percentile (0 mask → 0)."""
    nz = mask[mask > 0]
    if nz.size == 0:
        return np.zeros(mask.shape, dtype=np.float32)
    return np.clip(mask / float(np.percentile(nz, 99)), 0.0, 1.0).astype(np.float32)


def upsample_nearest(grid: np.ndarray, factor: int) -> np.ndarray:
    """Integer-factor nearest-neighbour upsampling (pack grid → Gaea grid)."""
    if factor < 1:
        raise ValueError(f"factor must be ≥ 1, got {factor}")
    return np.repeat(np.repeat(grid, factor, axis=0), factor, axis=1)


def _fbm_field(n: int, wavelength_px: float, seed: int, octaves: int = 3) -> np.ndarray:
    """fBm noise field (n×n), normalised to span exactly [-1, 1].

    opensimplex's raw range is roughly ±0.7 and fBm octave-stacking shrinks it
    further — without normalisation the warp amplitude constant ends up
    ~2.5× weaker than nominal (measured: p90 boundary displacement 23 px
    instead of the designed 63 px), which is why the first pass left the
    polygons plainly visible.
    """
    import opensimplex

    rng = opensimplex.OpenSimplex(seed=seed)
    freq = 1.0 / wavelength_px
    total = np.zeros((n, n))
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        coords = np.arange(n) * freq * (2**o)
        total += amp * rng.noise2array(coords, coords)
        norm += amp
        amp *= 0.5
    total /= norm
    peak = float(np.abs(total).max())
    if peak > 0:
        total /= peak
    return np.asarray(total)


def apply_boundary_warp(
    grid: np.ndarray, cell_px: float, *, order: int, seed: int = WARP_SEED
) -> np.ndarray:
    """Domain-warp ``grid`` by a coherent fBm displacement field.

    ``order=0`` for categorical rasters (nearest), 1 for continuous ones.
    The displacement amplitude/wavelength scale with the engine cell pitch so
    polygon edges become organic at any resolution.
    """
    from scipy.ndimage import map_coordinates

    n = grid.shape[0]
    amp_px = WARP_AMPLITUDE_CELLS * cell_px
    wave_px = WARP_WAVELENGTH_CELLS * cell_px
    wy = _fbm_field(n, wave_px, seed) * amp_px
    wx = _fbm_field(n, wave_px, seed + 1) * amp_px
    base = np.arange(n)
    rows = base[:, None] + wy
    cols = base[None, :] + wx
    return np.asarray(map_coordinates(grid, [rows, cols], order=order, mode="nearest"))


def reconcile_ocean_on_land(
    biome_codes: np.ndarray,
    legend: dict[int, str],
    sea_water: np.ndarray,
    *,
    fill_water: bool = False,
) -> np.ndarray:
    """Dry engine-ocean pixels get the nearest land biome's code.

    The pack's biome grid is engine-truth; the Gaea sea mask is the rendered
    water truth (consistent with the terrain Blender displaces by).  C1
    interpolation + erosion can lift engine-ocean cells above the waterline —
    painting them with the ocean fallback colour shows navy blobs on land
    (user-reported).  The rendered water surface is authoritative for water;
    dry-ex-ocean land is filled from the nearest land biome (distance-
    transform nearest fill).

    With ``fill_water=True``, sea-COVERED ocean cells are filled as well:
    the satellite compositor paints the sea from its depth channel, so any
    ocean fallback left in the base layer only serves to bleed navy into
    the coastal ecotone blur (blue-tinted shores, user-reported).
    """
    ocean_codes = [c for c, nm in legend.items() if nm == "ocean"]
    if not ocean_codes:
        return biome_codes
    from scipy.ndimage import distance_transform_edt

    is_ocean = np.isin(biome_codes, ocean_codes)
    dry_ocean = is_ocean if fill_water else (is_ocean & ~sea_water)
    land = ~is_ocean & (biome_codes != 0)
    if not dry_ocean.any() or not land.any():
        return biome_codes
    nearest = distance_transform_edt(~land, return_indices=True)[1]
    return np.where(dry_ocean, biome_codes[tuple(nearest)], biome_codes)


def _vegetation_texture(
    n: int,
    km_per_px: float,
    biome: np.ndarray,
    legend: dict[int, str],
    land: np.ndarray,
    *,
    gain: float = 1.0,
) -> np.ndarray:
    """Per-biome fBm brightness texture (1.0 = neutral), land only.

    Each class gets its own wavelength/amplitude and seed offset (see
    TEXTURE_PARAMS), so the Amazon-grade rainforest mottles tightly while
    dune fields streak broadly.  Applied as a brightness multiplier — hue
    stays climate-authoritative, only luminance gains the canopy/soil grain.
    ``gain`` scales every amplitude together: sheet legs with baked
    hillshade run a reduced gain, where the full uncorrelated mottle
    measured LARGER than the relief signal itself and drowned the terrain.
    """
    tex = np.ones((n, n), dtype=np.float32)
    for code in np.unique(biome[land]):
        if code == 0:
            continue
        wl_km, amp = TEXTURE_PARAMS.get(legend.get(int(code), ""), TEXTURE_DEFAULT)
        wl_px = max(wl_km / km_per_px, 2.0)
        field = _fbm_field(n, wl_px, TEXTURE_SEED + int(code)).astype(np.float32)
        sel = land & (biome == code)
        tex[sel] = 1.0 + amp * gain * field[sel]
    fine = _fbm_field(n, TEXTURE_FINE_WAVELENGTH_PX, TEXTURE_SEED + 999).astype(np.float32)
    tex[land] *= 1.0 + TEXTURE_FINE_AMPLITUDE * gain * fine[land]
    return tex


def colorize(
    inp: ColorizeInputs,
    *,
    texture: bool = True,
    ecotone_sigma_px: float | None = None,
    texture_gain: float = 1.0,
) -> np.ndarray:
    """Composite the albedo; returns (N, N, 3) uint8 sRGB.

    ``texture`` adds the per-biome vegetation/surface grain (Sentinel-2-like
    mottling); turn it off for a flat fill (debug or downstream re-texturing).
    ``ecotone_sigma_px`` overrides the ecotone blur width (both the base
    colour layer and the NPP vigour field); the sheet legs pass a wider one
    scaled to the engine cell pitch for imagery-style transitions.
    ``texture_gain`` scales the grain amplitudes (sheet legs run a reduced
    gain — see :func:`_vegetation_texture`).
    """
    from scipy.ndimage import gaussian_filter

    n = inp.height_m.shape[0]
    sigma = BIOME_BLUR_SIGMA_PX if ecotone_sigma_px is None else ecotone_sigma_px

    biome = reconcile_ocean_on_land(
        inp.biome_codes, inp.biome_legend, inp.sea_water, fill_water=True
    )

    # Base layer: engine biome colours, lightly blurred so cell boundaries
    # become ecotone-style transitions instead of crisp polygons.
    # Palette must cover every legend code, even ones no pixel currently
    # carries (reconciliation can erase a class from the raster).
    max_code = max(
        [int(biome.max()) if biome.size else 0, *inp.biome_legend.keys()],
    )
    palette = [MISSING_COLOR] * (max_code + 1)
    for code, name in inp.biome_legend.items():
        palette[code] = BIOME_COLORS.get(name, MISSING_COLOR)
    base = _to_rgb(palette)[biome].reshape(n, n, 3)
    for ch in range(3):
        base[..., ch] = gaussian_filter(base[..., ch], sigma)

    # Continuous within-biome variation from engine NPP (per-biome median
    # normalisation, land only — water/ice/missing stay untouched).  The
    # factor is blurred with the ecotone sigma: the per-biome normalisation
    # makes it piecewise-constant, and an unsmoothed vigour field re-etches
    # the very class boundaries the base blur just softened.
    npp_factor = np.ones((n, n), dtype=np.float32)
    for code in np.unique(biome):
        if code == 0:
            continue
        sel = biome == code
        vals = inp.npp_gc_m2_yr[sel]
        vals = vals[~np.isnan(vals)]
        if vals.size < NPP_MIN_CELLS:
            continue
        median = float(np.median(vals))
        if median <= 0:
            continue
        rel = np.clip(inp.npp_gc_m2_yr[sel] / median, 0.0, 2.0)
        rel = np.where(np.isnan(rel), 1.0, rel)
        npp_factor[sel] = 1.0 + NPP_MOD_STRENGTH * (rel - 1.0)
    npp_factor = gaussian_filter(npp_factor, sigma)
    base = np.clip(base * npp_factor[..., None], 0.0, 1.0)

    # Vegetation/surface grain (Sentinel-2-style mottling), land only.
    if texture:
        land_mask = ~inp.sea_water & (biome != 0)
        tex = _vegetation_texture(
            n, inp.km_per_px, biome, inp.biome_legend, land_mask, gain=texture_gain
        )
        base = np.clip(base * tex[..., None], 0.0, 1.0)

    # Slope from the physical height field (rise/run).
    step_m = inp.km_per_px * 1000.0
    gy, gx = np.gradient(inp.height_m, step_m)
    slope = np.hypot(gx, gy).astype(np.float32)
    del gy, gx

    rgb = base  # base is not needed past this point — alias, don't copy

    # Wear: subtle desaturation toward rock where water stripped material.
    wear_w = _p99_normalize(inp.wear) * WEAR_MAX_WEIGHT
    rock = np.asarray(ROCK_COLOR, dtype=np.float32) / 255.0
    rgb = rgb * (1 - wear_w[..., None]) + rock * wear_w[..., None]

    # Alluvium: warm tint on gentle ground where sediment settled.
    dep_w = (
        _p99_normalize(inp.deposits)
        * DEPOSIT_MAX_WEIGHT
        * (1.0 - _smoothstep(slope, 0.0, DEPOSIT_SLOPE_CAP))
    ).astype(np.float32)
    dep = np.asarray(DEPOSIT_COLOR, dtype=np.float32) / 255.0
    rgb = rgb * (1 - dep_w[..., None]) + dep * dep_w[..., None]

    # Ice cover: clipped thickness → blend weight, edges softened like the
    # biome layer.
    ice_cover = np.clip(inp.ice_m / ICE_FULL_M, 0.0, 1.0).astype(np.float32)
    ice_cover = gaussian_filter(ice_cover, ICE_BLUR_SIGMA_PX)

    # Exposed rock on steep slopes (suppressed where ice-covered).
    rock_w = _smoothstep(slope, ROCK_SLOPE_LO, ROCK_SLOPE_HI) * ROCK_MAX_WEIGHT
    rock_w *= 1.0 - ice_cover
    rgb = rgb * (1 - rock_w[..., None]) + rock * rock_w[..., None]

    # Glaciers / permanent ice.
    ice_rgb = np.asarray(ICE_COLOR, dtype=np.float32) / 255.0
    rgb = rgb * (1 - ice_cover[..., None]) + ice_rgb * ice_cover[..., None]

    # Rivers: depth-graded water colour over the channel mask.
    river_t = np.clip(inp.river_depth_m / RIVER_DEEP_M, 0.0, 1.0).astype(np.float32)
    river_rgb = (
        np.asarray(RIVER_SHALLOW, dtype=np.float32) / 255.0 * (1 - river_t[..., None])
        + np.asarray(RIVER_DEEP, dtype=np.float32) / 255.0 * river_t[..., None]
    )
    rgb = np.where(inp.rivers[..., None], river_rgb, rgb)

    # Lakes: pseudo-depth from the shoreline distance transform, edges
    # feathered into the shore.  Two lake sources, unioned: the biome-code
    # lake sentinel (engine classification) and the explicit ``lake`` mask
    # (programmatic-chain endorheic fills, exported as lake.png — packs
    # whose legend carries no lake code rendered no lakes at all).
    lake_codes = [c for c, nm in inp.biome_legend.items() if nm == "lake"]
    lake_mask: np.ndarray | None = np.isin(biome, lake_codes) if lake_codes else None
    if inp.lake is not None and inp.lake.any():
        lake_mask = inp.lake if lake_mask is None else (lake_mask | inp.lake)
    if lake_mask is not None and lake_mask.any():
        from scipy.ndimage import distance_transform_edt

        dist = distance_transform_edt(lake_mask)
        t = (dist / max(float(dist.max()), 1e-9)).astype(np.float32)[..., None]
        lake_rgb = (
            np.asarray(LAKE_SHALLOW, dtype=np.float32) / 255.0 * (1 - t)
            + np.asarray(LAKE_DEEP, dtype=np.float32) / 255.0 * t
        )
        alpha = gaussian_filter(lake_mask.astype(np.float32), LAKE_FEATHER_PX)[..., None]
        rgb = rgb * (1 - alpha) + lake_rgb * alpha

    # Sea: depth-graded blue, authoritative over everything it covers.
    sea_t = np.clip(inp.sea_depth_m / SEA_DEEP_M, 0.0, 1.0).astype(np.float32)
    sea_rgb = (
        np.asarray(SEA_SHALLOW, dtype=np.float32) / 255.0 * (1 - sea_t[..., None])
        + np.asarray(SEA_DEEP, dtype=np.float32) / 255.0 * sea_t[..., None]
    )
    rgb = np.where(inp.sea_water[..., None], sea_rgb, rgb)

    return (np.clip(rgb, 0.0, 1.0) * 255.0).round().astype(np.uint8)


def hillshade(
    height_m: np.ndarray, km_per_px: float, azimuth_deg: float = 315.0, altitude_deg: float = 45.0
) -> np.ndarray:
    """Classic hillshade (0..1) for the preview composite — never baked into
    the albedo."""
    step_m = km_per_px * 1000.0
    gy, gx = np.gradient(height_m, step_m)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az = np.radians(azimuth_deg)
    alt = np.radians(altitude_deg)
    hs = np.sin(alt) * np.sin(slope) + np.cos(alt) * np.cos(slope) * np.cos(az - aspect)
    return np.asarray(np.clip(hs, 0.0, 1.0))


def compose_preview(albedo: np.ndarray, height_m: np.ndarray, km_per_px: float) -> np.ndarray:
    """Albedo × soft hillshade for quick inspection."""
    hs = hillshade(height_m, km_per_px)
    shade = (0.55 + 0.45 * hs).astype(np.float32)[..., None]
    out: np.ndarray = np.clip(albedo.astype(np.float32) * shade, 0, 255).round().astype(np.uint8)
    return out


# ---------------------------------------------------------------------------
# IO layer (region pack + Gaea build directory)
# ---------------------------------------------------------------------------


def _read_exr_y(path: Path) -> np.ndarray:
    """Read a single-channel (Y) Gaea EXR as float32; clear error if OpenEXR
    is not installed (``uv sync --extra media``)."""
    try:
        import Imath
        import OpenEXR
    except ImportError as exc:
        raise RuntimeError(
            "Reading Gaea EXR needs the 'media' extra: uv sync --extra media"
        ) from exc
    fh = OpenEXR.InputFile(str(path))
    header = fh.header()
    dw = header["dataWindow"]
    w, h = dw.max.x - dw.min.x + 1, dw.max.y - dw.min.y + 1
    raw = fh.channel("Y", Imath.PixelType(Imath.PixelType.FLOAT))
    return np.frombuffer(raw, dtype=np.float32).reshape(h, w)


def _read_mask16(path: Path) -> np.ndarray:
    """16-bit PNG mask → float32 0..1 (accepts 1-bit/8-bit too)."""
    from PIL import Image

    img = Image.open(path)
    arr = np.asarray(img)
    if arr.dtype == bool:
        return arr.astype(np.float32)
    if arr.dtype == np.uint8:
        return arr.astype(np.float32) / np.float32(255.0)
    return arr.astype(np.float32) / np.float32(65535.0)


def _read_mask_bool(path: Path) -> np.ndarray:
    return _read_mask16(path) > 0.5


def load_inputs(pack_dir: Path, gaea_dir: Path) -> ColorizeInputs:
    """Load pack + build outputs (Gaea or programmatic) onto the build grid.

    ``gaea_dir`` holds either a Gaea build (``rivers-h.exr`` + masks, 8K)
    or a programmatic-erosion run (``prog-out/``: float32 metres
    ``height.meters.npy`` + masks at the pack resolution).  The pack
    rasters are ``--out-res`` (default 2048); codes are nearest-upsampled
    by the integer factor between the two grids.
    """
    meta = json.loads((pack_dir / "meta.json").read_text(encoding="utf-8"))
    gaea_min, gaea_max = (float(v) for v in meta["height_gaea_png_range_m"])
    span_m = gaea_max - gaea_min

    if (gaea_dir / "rivers-h.exr").exists():
        height01 = _read_exr_y(gaea_dir / "rivers-h.exr")
        n = height01.shape[0]
        height_m = (height01 * span_m + gaea_min).astype(np.float32)
    elif (gaea_dir / "height.meters.npy").exists():
        height_m = np.load(gaea_dir / "height.meters.npy").astype(np.float32)
        n = height_m.shape[0]
    else:
        raise FileNotFoundError(
            f"no heightfield in {gaea_dir} (need rivers-h.exr or height.meters.npy)"
        )

    biome_codes = np.load(pack_dir / "biome.codes.npy")
    factor, rem = divmod(n, biome_codes.shape[0])
    if rem != 0 or biome_codes.shape[0] * factor != n:
        raise ValueError(
            f"Gaea grid {n} is not an integer multiple of pack grid "
            f"{biome_codes.shape[0]} — rebuild both from the same pack "
            "(gaea build at out_res × 2^k)"
        )
    biome_codes = upsample_nearest(biome_codes, factor)
    legend = {int(k): v for k, v in meta["climate"]["biome"]["legend"].items()}

    # Boundary de-quantization: warp engine-sourced channels so Voronoi
    # polygon edges become organic ecotones (see WARP_* constants).
    km_per_px = float(meta["extent_km"]["x"]) / n
    cell_pitch_km = float(meta.get("cell_pitch_km", 0.0))
    # Fallback for packs exported before v3.1: measured nacrea pitch ≈ 180 px @ 8K.
    cell_px = cell_pitch_km / km_per_px if cell_pitch_km > 0 else 180.0 * n / 8192.0
    biome_codes = apply_boundary_warp(biome_codes, cell_px, order=0).astype(np.uint8)
    ice_grid = apply_boundary_warp(
        np.nan_to_num(upsample_nearest(np.load(pack_dir / "ice.m.npy"), factor), nan=0.0),
        cell_px,
        order=1,
    )
    # NPP warped identically so its variation tracks the warped biome
    # boundaries (both describe the same climate cells).
    npp_grid = apply_boundary_warp(
        upsample_nearest(np.load(pack_dir / "npp.gc_m2_yr.npy"), factor),
        cell_px,
        order=1,
    )

    # Depth masks are in heightfield units (0..1 over the TD span) in Gaea
    # builds; programmatic runs only write the masks they have — missing
    # files read as zero (flat sea, no depth channels, no wear/deposits).
    def mask16_or_zero(name: str) -> np.ndarray:
        p = gaea_dir / name
        return _read_mask16(p) if p.exists() else np.zeros((n, n), dtype=np.float32)

    sea = (
        _read_mask_bool(gaea_dir / "sea-water.png")
        if (gaea_dir / "sea-water.png").exists()
        else height_m <= 0.0
    )
    rivers_path = gaea_dir / "rivers.png"
    rivers = _read_mask_bool(rivers_path) if rivers_path.exists() else np.zeros((n, n), dtype=bool)
    lake_path = gaea_dir / "lake.png"
    lake = _read_mask_bool(lake_path) if lake_path.exists() else None
    seg_path = gaea_dir / "rivers.line.npy"
    river_segs = np.load(seg_path) if seg_path.exists() else None
    river_flows = (
        np.load(gaea_dir / "rivers.flow.npy") if (gaea_dir / "rivers.flow.npy").exists() else None
    )
    regime_path = gaea_dir / "rivers.regime.npy"
    river_regimes = np.load(regime_path) if regime_path.exists() else None

    # Lake clip: only strictly-in-water geometry goes (see
    # RIVER_LAKE_WATER_KM).  Everything on the rim land stays — with the
    # per-sheet single water family, a near-shore channel just reads as a
    # river instead of doubled shore ink.
    if lake is not None and lake.any() and river_segs is not None:
        from scipy.ndimage import distance_transform_edt

        dist_km: np.ndarray = np.asarray(distance_transform_edt(~lake) * km_per_px)
        col: np.ndarray = np.clip(
            (river_segs[..., 0].mean(axis=1) / km_per_px).astype(int), 0, n - 1
        )
        row: np.ndarray = np.clip(
            (n - 1 - (river_segs[..., 1].mean(axis=1) / km_per_px)).astype(int), 0, n - 1
        )
        keep = dist_km[row, col] > RIVER_LAKE_WATER_KM
        river_segs = river_segs[keep]
        if river_flows is not None:
            river_flows = river_flows[keep]
        if river_regimes is not None:
            river_regimes = river_regimes[keep]
        rivers = rivers & ~lake
    return ColorizeInputs(
        height_m=height_m,
        km_per_px=km_per_px,
        biome_codes=biome_codes,
        biome_legend=legend,
        sea_water=sea,
        sea_depth_m=mask16_or_zero("sea-depth.png") * span_m,
        rivers=rivers,
        river_depth_m=mask16_or_zero("rivers-depth.png") * span_m,
        flow=mask16_or_zero("flow.png"),
        wear=mask16_or_zero("wear.png"),
        deposits=mask16_or_zero("deposits.png"),
        ice_m=ice_grid,
        npp_gc_m2_yr=npp_grid,
        river_segments=river_segs,
        river_segment_flows=river_flows,
        river_segment_regimes=river_regimes,
        lake=lake,
        cell_px=float(cell_px),
        km_per_deg=math.pi * float(meta.get("radius_km", 6371.0)) / 180.0,
        projection=str(meta.get("projection", "equirect")),
        lake_ice_months=(
            upsample_nearest(np.load(pack_dir / "lake_ice.months.npy"), factor)
            if (pack_dir / "lake_ice.months.npy").exists()
            else None
        ),
    )


def colorize_region(
    pack_dir: Path, gaea_dir: Path, out_dir: Path, *, texture: bool = True
) -> dict[str, Path]:
    """Full step-③ pass: load → composite → write albedo.png + preview.png.

    ``pack_dir`` is the pack ROOT; channels are read from its ``input/``
    subdirectory (pack layout: ``input/`` + ``gaea-out/`` + ``color/``).
    ``texture`` toggles the per-biome vegetation grain (default on).
    """
    from PIL import Image

    inp = load_inputs(pack_dir / "input", gaea_dir)
    albedo = colorize(inp, texture=texture)
    preview = compose_preview(albedo, inp.height_m, inp.km_per_px)

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"albedo": out_dir / "albedo.png", "preview": out_dir / "preview.png"}
    Image.fromarray(albedo, "RGB").save(paths["albedo"])
    Image.fromarray(preview, "RGB").save(paths["preview"])
    return paths
