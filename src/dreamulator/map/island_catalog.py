"""Sub-grid island catalogue: hotspots, island arcs, heat-pipe provinces, seamounts (debt 44, A–C).

Design: ``docs/design/proposals/island-catalog.md``.  Almost every oceanic island is smaller
than a 54 km cell, so volcanoes are kept as a catalogue (position, age, volume, relief above
the surrounding seafloor) and the cells only receive the volcano volume as a cell mean plus
summary fields computed on the final surface (``summarise_islands``).  Pure functions: the
same mesh, plates and config always give the same catalogue.

Hotspot chains.  Each hotspot is fixed in the mantle; the plate it sits on is traced back
along its present Euler pole for ``_BACKTRACK_MY``.  A new volcano opens every ``λ`` along the
track, where the flexural stress of the previous edifice vanishes (ten Brink 1991; Hieronymus &
Bercovici 1999): ``λ = c·α``, α the flexural parameter of the oceanic plate
(``trench_flexure.flexural_parameter_km``, Te 25 km), so ``λ ∝ g^(−¼)`` and does not depend on
plate speed.  The eruption interval is λ / plate speed; the volcano's volume above the original
seafloor is the hotspot's magma flux times that interval times the share not sunk into the
flexural root.  The edifice is a cone of mean flank slope ``_FLANK_DEG``; its
relief above the surrounding seafloor is capped at ``_MAX_RELIEF_EARTH_M`` × g_Earth/g.  Above
sea level the summit decays towards sea level with e-folding time ``_SUBAERIAL_DECAY_MY``
(erosion plus subsidence); below sea level it subsides with the plate.

Island arcs.  On ocean–ocean margins the arc stands on the overriding plate where the slab is
~105 km deep.  The arc magma budget splits into an intrusive share that thickens the arc crust
(a cell-scale platform, ``arc_platform``, accumulated over the arc's age and lifted by submerged
Airy isostasy) and an extrusive share that builds the arc volcanoes of the catalogue, placed
along the axis as a one-dimensional Poisson process (arcs have no characteristic spacing).

Heat-pipe provinces (tidally heated bodies with a ``tidal_heat_history``).  The heating
pattern, the province partition and the magma rate are in ``heat_pipe``.  Sustained heat-pipe
resurfacing buries the crust and returns it to the mantle, so the crust is in a steady state:
the magma adds no plateau relative to the rest of the planet (the uniform part belongs to the
datum, and Io resurfaces ~1 cm/yr without plateaus at its heating maxima).  The provinces show
through their volcanoes.  Every parcel of crust is traced back along its plate's Euler pole;
in each segment of the timeline (a quiet stretch or a tidal phase) vents open as densely as the
local heat-pipe flux needs, each carrying ``_HEAT_PIPE_VENT_POWER_W``, and each builds an
edifice from the share ``_HEAT_PIPE_EDIFICE_SHARE`` of its magma (half of it in the flexural
root).  The vent is fixed in the tidal frame and
the plate moves over it, so, as on a hotspot track, one edifice grows only while its site
crosses one edifice spacing λ (time λ / plate speed); the rest of the magma spreads as flows
that bury the edifices of earlier segments.  Heat-pipe lavas are fluid and erupt fast, so the
edifices are broad low shields (flank slope ``_HEAT_PIPE_FLANK_DEG``), wider than the flexural
wavelength and compensated while they grow: they get no later edifice subsidence.  The parcel
keeps its tallest standing edifice.

Closures (observation fits):

* hotspot count = 49 per Earth surface area (Courtillot et al. 2003), placed with a seeded
  Poisson-disc rule over the whole sphere; only those on oceanic crust build islands;
* c = 0.70: Hawaii's ~45 km volcano spacing over α ≈ 65 km;
* magma flux lognormal, median 0.017 km³/yr, σ_ln 1.0 — Hawaii (~0.1 km³/yr) about six times
  the median buoyancy flux (Sleep 1990), so near the top of the distribution;
* flank slope 5°: Mauna Loa's ~9 km over a ~100 km base radius; relief cap ~9 km on Earth;
* subaerial decay 5 Myr: Kauai still ~1.6 km high after ~5 Myr from ~4.2 km, Midway at sea
  level after ~28 Myr; edifice subsidence 2 km with an e-folding time of 0.8 Myr (initial rate
  ~2.5 mm/yr, Hawaii's drowned reefs), applied to the cell means and to submerged summits;
* thermal subsidence of submerged summits 0.02 mm/yr (old lithosphere, uncertain);
* heat carried per heat-pipe vent ~2.4×10¹¹ W: Io's ~1.0×10¹⁴ W (Veeder et al. 2012) over its
  ~417 paterae (Radebaugh et al. 2001);
* heat-pipe shield flank slope 0.4°: Io's shield-like volcanoes stand less than 3 km high with
  slopes of 0.2–0.6° (Schenk et al. 2004);
* heat-pipe edifice share 0.2 of the magma, borrowed from the extrusive share of Earth's
  volcanic systems (intrusive : extrusive ≈ 5 : 1, White et al. 2006); not calibrated for heat
  pipes, so the heat-pipe edifice heights carry a factor-of-two uncertainty;
* seamounts taller than 1 km: 39 000 per Earth ocean area (Hillier & Watts 2007) on the abyssal
  floor (deeper than 2 km), heights exponential above 1 km with e-folding 0.5 km (form after
  Smith & Jordan 1988; scale uncertain).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import cKDTree

from dreamulator.map.trench_flexure import flexural_parameter_km

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh, TectonicPlate
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

_EARTH_AREA_KM2 = 4.0 * np.pi * 6371.0**2
_EARTH_OCEAN_AREA_KM2 = 3.61e8
_G_EARTH = 9.80665
_HOTSPOTS_PER_EARTH = 49.0
_SPACING_PER_ALPHA = 0.70
_FLUX_MEDIAN_KM3_YR = 0.017
_FLUX_SIGMA_LN = 1.0
#: Share of the erupted volume above the original seafloor: the load bends the plate and about
#: half the edifice sits in its own flexural root (Hawaii: 213×10³ km³ with the root, about
#: twice the volume above the seafloor; Robinson & Eakins 2006).  Observation fit.
_ABOVE_FLOOR_SHARE = 0.5
_FLANK_DEG = 5.0
_MAX_RELIEF_EARTH_M = 9000.0
_SUBAERIAL_DECAY_MY = 5.0
#: Subsidence of an edifice relative to the surrounding floor after it leaves the hotspot
#: (its own and its successors' load, swell decay): S(t) = S∞·(1 − e^(−t/τ)), initial rate
#: S∞/τ ≈ 2.5 mm/yr as measured on Hawaii's drowned reefs; most islands drown within 5–15 Myr.
#: Observation fit.
_EDIFICE_SUBSIDENCE_M = 2000.0
_EDIFICE_SUBSIDENCE_MY = 0.8
_THERMAL_SUBSIDENCE_M_PER_MY = 20.0
_BACKTRACK_MY = 20.0
_SEAMOUNTS_PER_EARTH_OCEAN = 39000.0
_SEAMOUNT_MIN_M = 1000.0
_SEAMOUNT_SCALE_M = 500.0
#: Only seamounts whose summit comes within this depth of the sea surface are exported.
_SEAMOUNT_KEEP_DEPTH_M = 2000.0
#: The seamount census counts edifices on the abyssal floor; seamounts drawn on oceanic
#: cells shallower than this (coast rings, margin belts) are dropped.
_SEAMOUNT_MIN_FLOOR_DEPTH_M = 2000.0
# ---- island arcs (phase B) ----
#: Arc axis distance from the trench (km): the mean arc–trench distance (Perrin et al. 2018,
#: 240 ± 62 km), where the slab is ~105 km deep (Syracuse & Abers 2006).  Observation fit.
_ARC_TRENCH_KM = 240.0
#: Half-width of the thickened arc crust (km): seismic sections of the Izu–Bonin–Mariana arc
#: show crust thicker than oceanic from the forearc to the rear arc, ~250 km across, thickest
#: under the volcanic front (Takahashi et al. 2007; Kodaira et al. 2007).  Observation fit.
_ARC_HALF_WIDTH_KM = 125.0
#: Magma added to an intra-oceanic arc per unit arc length (km³ per km per Myr): 30–95
#: (Dimalanta et al. 2002), long-term 20–40 (Reymer & Schubert 1984).  Observation fit.
_ARC_GROWTH_KM3_KM_MY = 40.0
#: Extruded share (intrusive : extrusive ≈ 5 : 1 in arcs, White et al. 2006).
_ARC_EXTRUSIVE_SHARE = 0.2
#: Mean spacing (km) of arc volcanoes along the axis — no characteristic spacing (de Bremond
#: d'Ars et al. 1995); Mariana front 35 ± 16 km (Baker et al. 2008), older estimates 50–70.
_ARC_SPACING_KM = 50.0
#: Building time of one arc edifice (Myr) and the age range of the catalogued edifices.
_ARC_EDIFICE_MY = 1.0
#: Airy rise of submerged crust per km of thickening, (ρm − ρc)/(ρm − ρw).
_SUBMARINE_AIRY = (3300.0 - 2800.0) / (3300.0 - 1030.0)
#: Arc age: the continuous convergent stretch of the evolution is read from the nearest
#: evolution-convergent cell within this radius (as the history contract does, km).
_ARC_AGE_TRANSFER_KM = 400.0
# ---- heat-pipe provinces (phase C) ----
_HEAT_PIPE_EDIFICE_SHARE = 0.2
_HEAT_PIPE_FLANK_DEG = 0.4
#: Heat carried by one heat-pipe vent (W): Io, the one observed heat-pipe body, loses ~1.0×10¹⁴ W
#: (Veeder et al. 2012) through ~417 volcanic paterae (Radebaugh et al. 2001).  Vents are as dense
#: as the local heat-pipe flux needs.  Observation fit.
_HEAT_PIPE_VENT_POWER_W = 1.0e14 / 417.0
#: Time step of the parcel back-tracking (Myr) and of the plate-membership check.
_HEAT_PIPE_PIECE_MY = 0.1
_HEAT_PIPE_PLATE_CHECK_MY = 0.5


@dataclass
class Volcano:
    """One edifice of the catalogue (summit and area are filled on the final surface)."""

    id: str
    kind: str  # "hotspot", "arc", "heatpipe" or "seamount"
    source: str
    cell: int
    lon: float
    lat: float
    age_myr: float
    volume_km3: float
    base_radius_km: float
    relief_m: float  # relief above the surrounding seafloor when built
    summit_m: float = float("nan")  # relative to the sea surface, at the present day
    emergent_area_km2: float = 0.0
    status: str = ""


@dataclass
class IslandCatalog:
    volcanoes: list[Volcano] = field(default_factory=list)


def _cone(volume_km3: float, g: float) -> tuple[float, float]:
    """(relief_m, base_radius_km) of a cone of the given volume and flank slope.

    Above the strength cap the relief stays at the cap and the edifice widens so the volume
    is kept (a large edifice spreads instead of growing taller).
    """
    t = np.tan(np.radians(_FLANK_DEG))
    h_km = (3.0 * volume_km3 * t * t / np.pi) ** (1.0 / 3.0)
    cap_km = _MAX_RELIEF_EARTH_M / 1000.0 * _G_EARTH / g
    if h_km <= cap_km:
        return 1000.0 * h_km, h_km / t
    return 1000.0 * cap_km, float(np.sqrt(3.0 * volume_km3 / (np.pi * cap_km)))


def _sinking_m(v: Volcano) -> float:
    """Later subsidence of an edifice relative to its floor (none for compensated shields)."""
    return 0.0 if v.kind == "heatpipe" else edifice_subsidence_m(v.age_myr)


def edifice_subsidence_m(age_myr: float) -> float:
    """Subsidence S(t) of a hotspot edifice relative to the surrounding floor (m)."""
    if not age_myr > 0.0:
        return 0.0
    return float(_EDIFICE_SUBSIDENCE_M * (1.0 - np.exp(-age_myr / _EDIFICE_SUBSIDENCE_MY)))


def _lonlat(v: np.ndarray) -> tuple[float, float]:
    lat = float(np.degrees(np.arcsin(np.clip(v[1], -1.0, 1.0))))
    lon = float(np.degrees(np.arctan2(v[2], v[0])))
    return lon, lat


def _rotate(v: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues rotation of v about the unit axis by angle (rad)."""
    c, s = np.cos(angle), np.sin(angle)
    out: np.ndarray = v * c + np.cross(axis, v) * s + axis * float(axis @ v) * (1.0 - c)
    return out


def build_island_catalog(
    mesh: CVTMesh, plates: list[TectonicPlate], config: TerrainPipelineConfig
) -> IslandCatalog:
    """Hotspot-chain volcanoes and seamounts of the present map."""
    cat = IslandCatalog()
    if not config.island_catalog_enabled:
        return cat
    rng = np.random.default_rng(int(config.seed) + 4400)
    cells = mesh.cells
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    tree = cKDTree(xyz)
    oceanic = np.array([c.crust_type == "oceanic" for c in cells])
    plate_of = {p.id: p for p in plates}
    radius_km = config.radius_km
    g = config.gravity_m_s2

    # ---- hotspots: seeded Poisson-disc over the sphere ----
    area_km2 = 4.0 * np.pi * radius_km**2
    n_hot = int(round(_HOTSPOTS_PER_EARTH * area_km2 / _EARTH_AREA_KM2))
    min_sep = float(np.sqrt(4.0 * np.pi / max(n_hot, 1)) * 0.5)
    seeds: list[np.ndarray] = []
    for _ in range(50 * max(n_hot, 1)):
        if len(seeds) >= n_hot:
            break
        v = rng.standard_normal(3)
        v /= np.linalg.norm(v)
        if all(np.arccos(np.clip(v @ s, -1.0, 1.0)) >= min_sep for s in seeds):
            seeds.append(v)
    fluxes = _FLUX_MEDIAN_KM3_YR * np.exp(_FLUX_SIGMA_LN * rng.standard_normal(len(seeds)))
    spacing_km = _SPACING_PER_ALPHA * flexural_parameter_km(g)
    for h, (hs, flux) in enumerate(zip(seeds, fluxes, strict=True)):
        _, ci = tree.query(hs)
        cell0 = cells[int(ci)]
        if not oceanic[ci] or cell0.plate_id not in plate_of:
            continue
        ep = plate_of[cell0.plate_id].euler_pole
        axis = np.array([ep.x, ep.y, ep.z])
        axis /= np.linalg.norm(axis)
        omega = float(ep.omega_rad_yr)  # rad/yr
        speed_km_yr = abs(omega) * float(np.linalg.norm(np.cross(axis, hs))) * radius_km
        if speed_km_yr <= 1e-9:
            continue
        interval_yr = spacing_km / speed_km_yr
        k = 0
        while (age_yr := k * interval_yr) <= _BACKTRACK_MY * 1e6:
            # the volcano built age_yr ago has since moved with the plate: rotate forward
            pos = _rotate(hs, axis, omega * age_yr)
            _, cj = tree.query(pos)
            cj = int(cj)
            if cells[cj].plate_id != cell0.plate_id or not oceanic[cj]:
                break  # the track left the plate or ran onto continental crust
            volume = float(flux * interval_yr) * _ABOVE_FLOOR_SHARE
            relief, radius = _cone(volume, g)
            lon, lat = _lonlat(pos)
            cat.volcanoes.append(
                Volcano(
                    id=f"hs{h:02d}_{k:03d}",
                    kind="hotspot",
                    source=f"hs{h:02d}",
                    cell=cj,
                    lon=lon,
                    lat=lat,
                    age_myr=age_yr / 1e6,
                    volume_km3=volume,
                    base_radius_km=radius,
                    relief_m=relief,
                )
            )
            k += 1

    # ---- island arcs: volcanoes along the arc axis of ocean–ocean margins ----
    dist, _age, _ = _arc_geometry(mesh, plates, radius_km)
    dx = float(np.sqrt(4.0 * np.pi * radius_km**2 / len(cells)))
    axis_cells = np.flatnonzero(np.isfinite(dist) & (np.abs(dist - _ARC_TRENCH_KM) < 0.5 * dx))
    arc_volume = _ARC_GROWTH_KM3_KM_MY * _ARC_EXTRUSIVE_SHARE * _ARC_SPACING_KM * _ARC_EDIFICE_MY
    m = 0
    for ci in axis_cells:
        for _ in range(int(rng.poisson(dx / _ARC_SPACING_KM))):
            relief, radius = _cone(arc_volume, g)
            lon, lat = _lonlat(xyz[ci])
            cat.volcanoes.append(
                Volcano(
                    id=f"arc{m:05d}",
                    kind="arc",
                    source="arc",
                    cell=int(ci),
                    lon=lon,
                    lat=lat,
                    age_myr=float(rng.uniform(0.0, _ARC_EDIFICE_MY)),
                    volume_km3=arc_volume,
                    base_radius_km=radius,
                    relief_m=relief,
                )
            )
            m += 1

    # ---- heat-pipe provinces: the tallest standing edifice of every parcel ----
    cat.volcanoes.extend(_heat_pipe_volcanoes(mesh, plates, config, xyz, tree))

    # ---- seamounts: Poisson on oceanic crust, exponential heights above 1 km ----
    ocean_area = float(sum(c.area_km2 for c, o in zip(cells, oceanic, strict=True) if o))
    n_sm = int(rng.poisson(_SEAMOUNTS_PER_EARTH_OCEAN * ocean_area / _EARTH_OCEAN_AREA_KM2))
    oc_idx = np.flatnonzero(oceanic)
    if oc_idx.size and n_sm:
        weights = np.array([cells[i].area_km2 for i in oc_idx], dtype=np.float64)
        picks = rng.choice(oc_idx, size=n_sm, p=weights / weights.sum())
        heights = _SEAMOUNT_MIN_M + rng.exponential(_SEAMOUNT_SCALE_M, size=n_sm)
        t = np.tan(np.radians(_FLANK_DEG))
        for m, (ci, hgt) in enumerate(zip(picks, heights, strict=True)):
            radius = hgt / 1000.0 / t
            volume = float(np.pi * radius**2 * hgt / 1000.0 / 3.0)
            lon, lat = _lonlat(xyz[ci])
            cat.volcanoes.append(
                Volcano(
                    id=f"sm{m:05d}",
                    kind="seamount",
                    source="seamount",
                    cell=int(ci),
                    lon=lon,
                    lat=lat,
                    age_myr=float("nan"),
                    volume_km3=volume,
                    base_radius_km=float(radius),
                    relief_m=float(hgt),
                )
            )
    return cat


def _cone_relief_m(volume_km3: np.ndarray, g: float, flank_deg: float) -> np.ndarray:
    """Vectorised relief (m) of ``_cone`` for an array of volumes and a flank slope."""
    t = np.tan(np.radians(flank_deg))
    h_km = (3.0 * np.maximum(volume_km3, 0.0) * t * t / np.pi) ** (1.0 / 3.0)
    out: np.ndarray = 1000.0 * np.minimum(h_km, _MAX_RELIEF_EARTH_M / 1000.0 * _G_EARTH / g)
    return out


def _heat_pipe_volcanoes(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
    xyz: np.ndarray,
    tree: cKDTree,
) -> list[Volcano]:
    """The tallest standing heat-pipe edifice of every parcel, one per vent catchment."""
    from dreamulator.engine.tidal_physics import plate_heat_flux_w_m2
    from dreamulator.map.heat_pipe import (
        PROVINCES,
        heat_pipe_rate_km_my,
        heat_segments,
        province_index,
    )

    hist = config.tidal_heat_history
    if hist is None:
        return []
    rng = np.random.default_rng(int(config.seed) + 4410)
    cells = mesh.cells
    n = len(cells)
    g = config.gravity_m_s2
    radius_km = config.radius_km
    land_frac = float(np.mean([c.crust_type != "oceanic" for c in cells]))
    q_plate = plate_heat_flux_w_m2(config.plate_speed_mean_cm_yr, land_frac)
    from dreamulator.map.heat_pipe import KM_PER_MY_PER_W_M2

    # magma of one vent (km³/Myr): its power over ρ·L, as for the flux density
    vent_km3_my = _HEAT_PIPE_VENT_POWER_W * KM_PER_MY_PER_W_M2 * 1e-6  # W·km/(Myr·W/m²) → km³
    spacing_km = _SPACING_PER_ALPHA * flexural_parameter_km(g)
    segments = heat_segments(hist, _BACKTRACK_MY, rng)

    # per-cell rotation axis and rate of its plate (back-tracking rotates by −ω·t)
    plate_ids = [c.plate_id or "" for c in cells]
    plate_of = {p.id: p for p in plates}
    axis = np.zeros((n, 3))
    omega = np.zeros(n)
    for pid_, p in plate_of.items():
        sel = np.array([q == pid_ for q in plate_ids])
        ep = p.euler_pole
        a = np.array([ep.x, ep.y, ep.z], dtype=np.float64)
        axis[sel] = a / max(float(np.linalg.norm(a)), 1e-12)
        omega[sel] = float(ep.omega_rad_yr)
    pid_arr = np.array(plate_ids)
    # a vent is fixed in the tidal frame while the plate moves over it: like a hotspot volcano,
    # one edifice grows only while its site crosses one edifice spacing (λ / plate speed)
    speed_km_my = np.abs(omega) * np.linalg.norm(np.cross(axis, xyz), axis=1) * radius_km * 1e6
    build_my = spacing_km / np.maximum(speed_km_my, 1e-6)

    def back(t_myr: float) -> np.ndarray:
        ang = -omega * t_myr * 1e6
        c, s = np.cos(ang)[:, None], np.sin(ang)[:, None]
        dot = np.einsum("ij,ij->i", xyz, axis)[:, None]
        out: np.ndarray = xyz * c + np.cross(axis, xyz) * s + axis * dot * (1.0 - c)
        return out

    alive = np.ones(n, dtype=bool)
    next_check = _HEAT_PIPE_PLATE_CHECK_MY
    burial_km = np.zeros(n)  # flows of younger segments
    best = np.zeros(n)  # standing relief (m) of the parcel's tallest edifice
    best_relief = np.zeros(n)
    best_volume = np.zeros(n)
    best_age = np.zeros(n)
    best_prov = np.zeros(n, dtype=np.int64)
    best_flux = np.zeros(n)  # heat-pipe flux (W/m²) of the segment that built the edifice
    for seg in segments:  # newest first
        span = seg.old_myr - seg.young_myr
        k = max(1, int(np.ceil(span / _HEAT_PIPE_PIECE_MY)))
        column = np.zeros(n)
        act = np.asarray(seg.activity, dtype=np.float64)
        pos = xyz
        for j in range(k):
            t = seg.young_myr + (j + 0.5) * span / k
            pos = back(t)
            if t >= next_check:  # crust that was not yet on its plate did not exist
                _, near = tree.query(pos)
                alive &= pid_arr[near] == pid_arr
                next_check += _HEAT_PIPE_PLATE_CHECK_MY
            column += heat_pipe_rate_km_my(pos, seg.heat_w_m2, act, q_plate) * (span / k)
        column[~alive] = 0.0
        flux = column / max(span, 1e-12) / KM_PER_MY_PER_W_M2
        feeding = np.where(column > 0.0, np.minimum(build_my, span), 0.0)
        volume = _HEAT_PIPE_EDIFICE_SHARE * _ABOVE_FLOOR_SHARE * vent_km3_my * feeding
        relief = _cone_relief_m(volume, g, _HEAT_PIPE_FLANK_DEG)
        standing = relief - 1000.0 * burial_km
        better = alive & (standing > best)
        best[better] = standing[better]
        best_relief[better] = relief[better]
        best_volume[better] = volume[better]
        best_age[better] = seg.mid_myr
        best_prov[better] = province_index(pos[better])
        best_flux[better] = flux[better]
        burial_km += (1.0 - _HEAT_PIPE_EDIFICE_SHARE) * column

    out: list[Volcano] = []
    area = np.array([c.area_km2 for c in cells], dtype=np.float64)
    cell_km = np.sqrt(area) / radius_km  # cell size (rad) for jittering vents
    m = 0
    for ci in np.flatnonzero(best > 0.0):
        frac = best[ci] / best_relief[ci]  # exposed top of the cone, by similarity
        vol = float(best_volume[ci] * frac**3)
        stand_m = float(best[ci])
        radius = stand_m / 1000.0 / np.tan(np.radians(_HEAT_PIPE_FLANK_DEG))
        n_vents = area[ci] * 1e6 * best_flux[ci] / _HEAT_PIPE_VENT_POWER_W
        for _ in range(int(rng.poisson(n_vents))):
            off = rng.standard_normal(3)
            off -= (off @ xyz[ci]) * xyz[ci]
            v = xyz[ci] + 0.5 * cell_km[ci] * rng.uniform() * off / max(np.linalg.norm(off), 1e-12)
            v /= np.linalg.norm(v)
            lon, lat = _lonlat(v)
            out.append(
                Volcano(
                    id=f"hp{m:06d}",
                    kind="heatpipe",
                    source=f"hp_{PROVINCES[int(best_prov[ci])]}",
                    cell=int(ci),
                    lon=lon,
                    lat=lat,
                    age_myr=float(best_age[ci]),
                    volume_km3=vol,
                    base_radius_km=radius,
                    relief_m=stand_m,
                )
            )
            m += 1
    return out


def _arc_geometry(
    mesh: CVTMesh, plates: list[TectonicPlate], radius_km: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Distance (km) from the ocean–ocean trench on the overriding plate, the arc age (Myr) of
    the nearest contact, and the overriding contact mask (all (N,); inf / 0 elsewhere)."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra

    from dreamulator.map.orogen_contract import contact_polarity

    cells = mesh.cells
    n = len(cells)
    dist = np.full(n, np.inf)
    age = np.zeros(n)
    over_contact = np.zeros(n, dtype=bool)
    pol = contact_polarity(mesh, plates, radius_km)
    for k, (kind, _down, over) in pol.items():
        if kind == "ocean" and cells[k].plate_id == over:
            over_contact[k] = True
    if not over_contact.any():
        return dist, age, over_contact
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    rows = np.repeat(np.arange(n), [len(c.neighbors) for c in cells])
    cols = np.array([j for c in cells for j in c.neighbors], dtype=np.int64)
    w = np.arccos(np.clip(np.einsum("ij,ij->i", xyz[rows], xyz[cols]), -1.0, 1.0)) * radius_km
    plate_arr = np.array([c.plate_id or "" for c in cells])
    oceanic = np.array([c.crust_type == "oceanic" for c in cells])
    same = (plate_arr[rows] == plate_arr[cols]) & oceanic[rows] & oceanic[cols]
    graph = csr_matrix((w[same], (rows[same], cols[same])), shape=(n, n))
    src = np.flatnonzero(over_contact)
    d, _, pred = dijkstra(
        graph,
        indices=src,
        min_only=True,
        limit=_ARC_TRENCH_KM + 2.0 * _ARC_HALF_WIDTH_KM,
        return_predecessors=True,
    )
    dist = d
    run = np.array([c.convergent_duration_my for c in cells])
    had = np.flatnonzero(run > 0.0)
    src_age = np.zeros(n)
    if had.size:
        dd, jj = cKDTree(xyz[had]).query(
            xyz[src], distance_upper_bound=_ARC_AGE_TRANSFER_KM / radius_km
        )
        ok = np.isfinite(dd)
        src_age[src[ok]] = run[had[jj[ok]]]
    reach = np.isfinite(d)
    age[reach] = src_age[pred[reach]]
    return dist, age, over_contact


def arc_platform(
    mesh: CVTMesh, plates: list[TectonicPlate], config: TerrainPipelineConfig
) -> np.ndarray:
    """Cell-mean rise (m) of the arc crust of ocean–ocean margins (the intrusive arc magma).

    The intrusive share of the arc growth, accumulated over the arc's age, thickens the crust
    over a triangular belt of half-width ``_ARC_HALF_WIDTH_KM`` around the arc axis
    (``_ARC_TRENCH_KM`` from the trench on the overriding plate); submerged Airy isostasy
    turns the thickening into relief.
    """
    out = np.zeros(len(mesh.cells))
    if not config.island_catalog_enabled:
        return out
    dist, age, _ = _arc_geometry(mesh, plates, config.radius_km)
    ok = np.isfinite(dist)
    x = np.abs(dist[ok] - _ARC_TRENCH_KM) / _ARC_HALF_WIDTH_KM
    shape = np.maximum(1.0 - x, 0.0)  # triangle of unit height, area = half-width
    intrusive = _ARC_GROWTH_KM3_KM_MY * (1.0 - _ARC_EXTRUSIVE_SHARE) * age[ok]  # km³ per km
    thickening_km = intrusive * shape / _ARC_HALF_WIDTH_KM
    out[ok] = 1000.0 * _SUBMARINE_AIRY * thickening_km
    return out


def volcano_cell_mean(mesh: CVTMesh, cat: IslandCatalog, radius_km: float) -> np.ndarray:
    """Cell-mean elevation added by the catalogue's hotspot volcanoes (m).

    Each cone's volume is spread over the cells under it in proportion to the cone height at
    the cell centre (the centre cell alone when the cone is smaller than a cell), so the cell
    means carry the edifice volume.  Where the cones of a chain overlap, a cell's rise is capped
    at the tallest edifice covering it: a new shield grows on its neighbour's flank and a ridge
    is no taller than its volcanoes, whose relief the lithosphere's strength limits.  Hotspot and
    arc volcanoes enter; seamounts are catalogue-only.
    """
    cells = mesh.cells
    n = len(cells)
    out = np.zeros(n, dtype=np.float64)
    area = np.array([c.area_km2 for c in cells], dtype=np.float64)
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    tree = cKDTree(xyz)
    tallest = np.zeros(n, dtype=np.float64)
    for v in cat.volcanoes:
        if v.kind == "seamount":
            continue
        nb = np.array(tree.query_ball_point(xyz[v.cell], v.base_radius_km / radius_km), dtype=int)
        if nb.size == 0:
            nb = np.array([v.cell])
        d = np.arccos(np.clip(xyz[nb] @ xyz[v.cell], -1.0, 1.0)) * radius_km
        w = np.maximum(1.0 - d / max(v.base_radius_km, 1e-9), 0.0)
        if w.sum() <= 0.0:
            nb, w = np.array([v.cell]), np.array([1.0])
        # an old edifice has sunk relative to the floor around it
        standing = max(v.relief_m - _sinking_m(v), 0.0)
        share = standing / max(v.relief_m, 1e-9)
        vol_m3_per_km2 = v.volume_km3 * share * 1e9 / 1e6  # km³ → m·km²
        out[nb] += vol_m3_per_km2 * (w / w.sum()) / area[nb]
        tallest[nb] = np.maximum(tallest[nb], standing)
    capped: np.ndarray = np.minimum(out, tallest)
    return capped


def summarise_islands(
    mesh: CVTMesh, cat: IslandCatalog, contribution: np.ndarray, sea_level_m: float
) -> dict[str, np.ndarray]:
    """Fill summits, emergent areas and statuses on the final surface; per-cell summaries.

    The seafloor under a volcano is the final cell mean minus the catalogue's own cell-mean
    contribution there.  Returns ``island_count``, ``island_area_frac`` and
    ``island_peak_m`` (NaN where a cell has no emergent island).  An island whose above-water
    footprint is wider than its cell is resolved by the grid and enters none of the three.
    """
    cells = mesh.cells
    n = len(cells)
    z = np.array([c.elevation for c in cells], dtype=np.float64)
    area = np.array([c.area_km2 for c in cells], dtype=np.float64)
    count = np.zeros(n, dtype=np.int64)
    land_km2 = np.zeros(n, dtype=np.float64)
    peak = np.full(n, np.nan)
    cell_km = np.sqrt(area)
    for v in cat.volcanoes:
        floor = z[v.cell] - contribution[v.cell] - sea_level_m
        if v.kind == "seamount" and floor > -_SEAMOUNT_MIN_FLOOR_DEPTH_M:
            v.status = "dropped"
            continue
        summit0 = floor + v.relief_m
        age = 0.0 if np.isnan(v.age_myr) else v.age_myr
        if floor > 0.0:  # a volcano standing on land, not an island
            v.summit_m = float(floor + v.relief_m * np.exp(-age / _SUBAERIAL_DECAY_MY))
            v.status = "land volcano"
            continue
        if summit0 > 0.0:  # erosion and subsidence together (calibrated on Kauai)
            summit = summit0 * float(np.exp(-age / _SUBAERIAL_DECAY_MY))
        else:
            summit = summit0 - _sinking_m(v) - _THERMAL_SUBSIDENCE_M_PER_MY * age
        v.summit_m = float(summit)
        if summit > 0.0:
            r = summit / max(v.relief_m, 1e-9) * v.base_radius_km  # same flank slope
            v.emergent_area_km2 = float(np.pi * r * r)
            v.status = "volcanic island" if summit > 300.0 else "low island"
            if r > 0.5 * cell_km[v.cell]:
                continue  # emerged part wider than its cell: resolved by the grid, not sub-grid
            count[v.cell] += 1
            land_km2[v.cell] += v.emergent_area_km2
            peak[v.cell] = summit if np.isnan(peak[v.cell]) else max(peak[v.cell], summit)
        else:
            v.status = "seamount" if summit0 <= 0.0 else "guyot"
    return {
        "island_count": count,
        "island_area_frac": np.minimum(land_km2 / np.maximum(area, 1e-9), 1.0),
        "island_peak_m": peak,
    }


def catalog_to_json(cat: IslandCatalog) -> list[dict[str, object]]:
    """Plain records for ``island_catalog.json`` (emergent and near-surface edifices)."""
    out: list[dict[str, object]] = []
    for v in cat.volcanoes:
        if v.status == "dropped" or (
            v.kind in ("seamount", "heatpipe") and not (v.summit_m > -_SEAMOUNT_KEEP_DEPTH_M)
        ):
            continue
        out.append(
            {
                "id": v.id,
                "kind": v.kind,
                "source": v.source,
                "lon": round(v.lon, 4),
                "lat": round(v.lat, 4),
                "age_myr": None if np.isnan(v.age_myr) else round(v.age_myr, 3),
                "volume_km3": round(v.volume_km3, 1),
                "base_radius_km": round(v.base_radius_km, 2),
                "summit_m": round(v.summit_m, 1),
                "emergent_area_km2": round(v.emergent_area_km2, 1),
                "status": v.status,
            }
        )
    return out
