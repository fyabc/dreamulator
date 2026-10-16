"""Plate kinematics for paleogeographic reconstruction (geological timeline M1).

Pure functions: numpy arrays in, numpy arrays out.  No IO, no RNG, and the inputs
are never modified, so a reconstruction cannot touch the present-day mesh it
reads (design: ``docs/design/proposals/geological-timeline.md`` §4, §7).

Every present-day cell is treated as a crust parcel that rides on its plate.

* :func:`reconstruction_plates` builds the plate model the reconstruction rides
  on.  A generated world's present plates are partitioned independently of its
  crust, so their boundaries can run through continents; the reconstruction model
  keeps each continental block rigid, attaches it to the plate that owns most of
  its area, and fits every plate's Euler pole to the present velocity field
  (proposal §4.0).
* :func:`synthesize_seafloor_age` gives each oceanic parcel an age: the time the
  spreading half-rate of its plate's ridge needs to carry crust from the ridge to
  the parcel.  Both ridge flanks are measured the same way, so the isochrons come
  out symmetric about the ridge.
* :func:`rewind` moves the parcels back to time ``t``: oceanic parcels younger
  than ``t`` are dropped, the rest are rotated back about their plate's Euler pole
  and resampled onto the same mesh.  Cells that no parcel reaches are gaps (crust
  subducted after ``t``); cells that parcels of two plates both claim are overlaps
  (margins stretched after ``t``).
* :func:`paleo_fields` turns a rewound state into crust type, age and elevation
  at ``t``.  Ocean depth follows the same plate-cooling law as the terrain
  synthesizer, applied as an increment on the present elevation, so ``t = 0``
  returns the present field exactly.

M1 holds the present Euler poles fixed over the whole interval (one stage pole
per plate).  Velocities follow the engine convention v = ω × P on the unit sphere
(``boundary_detector.plate_velocity_at``), and a forward step of ``dt`` years is a
rotation by ``omega_rad_yr · dt`` about the pole axis, so going back is the same
rotation with the opposite sign.

Epistemic class (CLAUDE.md §9): rotations and parcel bookkeeping are kinematics;
the age-depth law is an observational fit (Earth ocean floor); holding the poles
fixed is an M1 approximation, replaced by stage poles in M2.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

#: 1 cm/yr = 10 km/Myr.
_KM_PER_MYR_PER_CM_YR = 10.0
#: Radius km → surface speed cm/yr for an angular speed in rad/yr.
_CM_PER_KM = 1.0e5


@dataclass(frozen=True)
class PlateKinematics:
    """Flat arrays describing the present-day mesh and its plates.

    Attributes:
        xyz: (N, 3) unit vectors of the cell centres (engine convention, y north).
        nbr_ptr: (N + 1,) CSR row pointer of the cell adjacency.
        nbr_idx: (E,) CSR column indices of the cell adjacency.
        plate: (N,) plate index of each cell, into ``omega``.
        omega: (P, 3) rotation vectors (pole axis × omega_rad_yr), rad/yr.
        continental: (N,) True for continental crust.
        area_km2: (N,) cell areas.
        radius_km: planet radius.
    """

    xyz: np.ndarray
    nbr_ptr: np.ndarray
    nbr_idx: np.ndarray
    plate: np.ndarray
    omega: np.ndarray
    continental: np.ndarray
    area_km2: np.ndarray
    radius_km: float

    @property
    def n(self) -> int:
        return int(self.xyz.shape[0])

    @property
    def spacing_km(self) -> float:
        """Typical cell spacing: square root of the median cell area."""
        return float(np.sqrt(np.median(self.area_km2)))

    def neighbors(self, i: int) -> np.ndarray:
        nb: np.ndarray = self.nbr_idx[self.nbr_ptr[i] : self.nbr_ptr[i + 1]]
        return nb


def adjacency_csr(neighbors: list[list[int]]) -> tuple[np.ndarray, np.ndarray]:
    """CSR arrays (row pointer, column indices) of a neighbour list."""
    counts = np.fromiter((len(nb) for nb in neighbors), dtype=np.int64, count=len(neighbors))
    ptr = np.zeros(len(neighbors) + 1, dtype=np.int64)
    np.cumsum(counts, out=ptr[1:])
    idx = np.fromiter((j for nb in neighbors for j in nb), dtype=np.int64, count=int(ptr[-1]))
    return ptr, idx


def arc_km(a: np.ndarray, b: np.ndarray, radius_km: float) -> np.ndarray:
    """Great-circle distance between unit vectors (row-wise), km."""
    dots = np.clip(np.einsum("...j,...j->...", a, b), -1.0, 1.0)
    d: np.ndarray = radius_km * np.arccos(dots)
    return d


def boundary_cells(kin: PlateKinematics) -> np.ndarray:
    """(N,) True for cells with at least one neighbour on another plate."""
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cross = kin.plate[rows] != kin.plate[kin.nbr_idx]
    out = np.zeros(kin.n, dtype=bool)
    out[rows[cross]] = True
    return out


def fit_rotation(xyz: np.ndarray, velocity: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Rotation vector ω minimising Σ w |ω × x − v|² (weighted least squares).

    ω × x = −[x]× ω is linear in ω, so the fit is a 3-unknown linear problem.  For
    cells that already move rigidly with one rotation it returns that rotation.
    """
    x0, x1, x2 = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    zero = np.zeros_like(x0)
    a = np.stack(
        [
            np.stack([zero, x2, -x1], axis=1),
            np.stack([-x2, zero, x0], axis=1),
            np.stack([x1, -x0, zero], axis=1),
        ],
        axis=1,
    )
    sw = np.sqrt(weight)
    lhs = (a * sw[:, None, None]).reshape(-1, 3)
    rhs = (velocity * sw[:, None]).reshape(-1)
    omega: np.ndarray = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
    return omega


@dataclass(frozen=True)
class ReconstructionPlates:
    """Plate model for the reconstruction (proposal §4.0).

    Attributes:
        plate: (N,) plate index of each cell, into ``omega`` (same indices as the
            present plates; a plate can lose or gain continental blocks).
        omega: (P, 3) Euler rotation vectors fitted to the present velocity field.
        block: (N,) continental block label, −1 on oceanic crust.
        misfit_cm_yr: (N,) |velocity under ``omega`` − present velocity|.
    """

    plate: np.ndarray
    omega: np.ndarray
    block: np.ndarray
    misfit_cm_yr: np.ndarray


def reconstruction_plates(kin: PlateKinematics, suture: np.ndarray) -> ReconstructionPlates:
    """Make continents rigid: one plate per continental block, poles refitted.

    1. Continental blocks are the connected components of continental crust, cut
       only along suture edges: neighbour pairs on different present plates whose
       cells are both flagged in ``suture``.  The default caller flags convergent
       boundary cells, so a block splits only where a present orogen cuts it
       through; boundaries that cut it partly, or that are divergent or transform,
       are treated as inactive inside the block.
    2. Every block joins the present plate that owns most of its area; oceanic
       cells keep their present plate.
    3. Every plate's Euler pole is refitted (:func:`fit_rotation`, area-weighted)
       to the present velocity field of its new cells, so present motions are
       kept on average.  A plate whose membership did not change gets its present
       pole back.

    Args:
        kin: present-day kinematics.
        suture: (N,) cells allowed to separate two continental blocks.
    """
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    cont = kin.continental
    cut = (kin.plate[rows] != kin.plate[cols]) & suture[rows] & suture[cols]
    keep = cont[rows] & cont[cols] & ~cut
    graph = csr_matrix((np.ones(int(keep.sum())), (rows[keep], cols[keep])), shape=(kin.n, kin.n))
    _, label = connected_components(graph, directed=False)
    block = np.where(cont, label, -1)
    # relabel blocks 0..B-1 in order of first appearance
    _, block_ids = np.unique(block[cont], return_inverse=True)
    block[cont] = block_ids

    n_plates = kin.omega.shape[0]
    plate = kin.plate.copy()
    for b in range(int(block_ids.max()) + 1 if block_ids.size else 0):
        m = block == b
        owner = np.bincount(kin.plate[m], weights=kin.area_km2[m], minlength=n_plates)
        plate[m] = int(np.argmax(owner))

    velocity = np.cross(kin.omega[kin.plate], kin.xyz)
    omega = kin.omega.copy()
    for p in range(n_plates):
        m = plate == p
        if m.any():
            omega[p] = fit_rotation(kin.xyz[m], velocity[m], kin.area_km2[m])
    misfit = np.linalg.norm(np.cross(omega[plate], kin.xyz) - velocity, axis=1)
    misfit *= kin.radius_km * _CM_PER_KM
    return ReconstructionPlates(plate=plate, omega=omega, block=block, misfit_cm_yr=misfit)


def rotation_matrices(omega: np.ndarray, t_yr: float) -> np.ndarray:
    """(P, 3, 3) Rodrigues matrices rotating each plate by ``omega · t_yr``.

    A positive ``t_yr`` moves plates forward in time; a negative one moves them back.
    """
    rate = np.linalg.norm(omega, axis=1)
    axis = np.zeros_like(omega)
    moving = rate > 0
    axis[moving] = omega[moving] / rate[moving, None]
    theta = rate * t_yr
    c, s = np.cos(theta), np.sin(theta)
    kx, ky, kz = axis[:, 0], axis[:, 1], axis[:, 2]
    zero = np.zeros_like(kx)
    k = np.stack(
        [
            np.stack([zero, -kz, ky], axis=1),
            np.stack([kz, zero, -kx], axis=1),
            np.stack([-ky, kx, zero], axis=1),
        ],
        axis=1,
    )
    eye = np.broadcast_to(np.eye(3), k.shape)
    rot: np.ndarray = eye + s[:, None, None] * k + (1.0 - c)[:, None, None] * (k @ k)
    return rot


def boundary_opening_rates(
    kin: PlateKinematics, cells: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Signed opening rate (cm/yr) across the plate boundary at the given cells.

    The opening rate is the relative velocity (own plate minus the mean rotation of
    the across-boundary neighbours' plates) projected on the boundary normal:
    positive where the plates separate, negative where they converge.  The normal
    is the gradient of plate membership over the two-ring neighbourhood (centroid
    of own-plate cells minus centroid of the other plates' cells), in the tangent
    plane.  The nearest across-boundary neighbours alone tilt it by tens of
    degrees on an irregular mesh, and projecting on each neighbour direction then
    averaging shrinks the rate by the cosine of their spread.

    Args:
        kin: present-day kinematics.
        cells: (N,) cells to evaluate; cells without an across-boundary neighbour
            stay NaN.

    Returns:
        (opening_cm_yr, half_gap_km): half_gap is half the distance to the nearest
        across-boundary neighbour (the boundary lies between the two centres).
    """
    opening = np.full(kin.n, np.nan)
    half_gap = np.full(kin.n, np.nan)
    cm_per_rad = kin.radius_km * _CM_PER_KM
    for i in np.flatnonzero(cells):
        nb = kin.neighbors(int(i))
        across = nb[kin.plate[nb] != kin.plate[i]]
        if across.size == 0:
            continue
        x = kin.xyz[i]
        ring = np.unique(np.concatenate([nb] + [kin.neighbors(int(j)) for j in nb]))
        own = kin.plate[ring] == kin.plate[i]
        normal = kin.xyz[ring[own]].mean(axis=0) - kin.xyz[ring[~own]].mean(axis=0)
        normal -= (normal @ x) * x
        norm = float(np.linalg.norm(normal))
        if norm < 1e-15:
            continue
        normal /= norm
        omega_across = kin.omega[kin.plate[across]].mean(axis=0)
        v_rel = np.cross(kin.omega[kin.plate[i]] - omega_across, x) * cm_per_rad
        opening[i] = float(v_rel @ normal)
        half_gap[i] = 0.5 * float(arc_km(x, kin.xyz[across], kin.radius_km).min())
    return opening, half_gap


def ridge_half_rates(
    kin: PlateKinematics,
    divergent: np.ndarray,
    min_opening_cm_yr: float = 0.2,
) -> tuple[np.ndarray, np.ndarray]:
    """Spreading half-rate (cm/yr) and ridge offset (km) of each ridge cell.

    A ridge cell is an oceanic cell flagged divergent whose plate boundary opens
    faster than ``min_opening_cm_yr`` (:func:`boundary_opening_rates`); the
    half-rate is half the opening rate.  The offset is half the distance to the
    nearest across-boundary neighbour, because the boundary (age 0) lies between
    the two cell centres.

    Args:
        kin: present-day kinematics.
        divergent: (N,) True where the boundary detector flagged a divergent boundary.
        min_opening_cm_yr: cells opening slower than this are not ridges.

    Returns:
        (half_rate, offset_km), both NaN outside ridge cells.
    """
    opening, half_gap = boundary_opening_rates(kin, divergent & ~kin.continental)
    ridge = opening >= min_opening_cm_yr
    half = np.where(ridge, 0.5 * opening, np.nan)
    offset = np.where(ridge, half_gap, np.nan)
    return half, offset


def synthesize_seafloor_age(
    kin: PlateKinematics,
    half_rate: np.ndarray,
    offset_km: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Seafloor age (Myr) of every oceanic cell, grown outward from the ridges.

    Label-setting search over the oceanic cells of each plate: a front starts at
    every ridge cell with age = offset / half-rate and spreads to neighbours on the
    same plate, adding edge length / half-rate of the ridge it started from.  Each
    cell keeps the smallest age it receives.  Path length through the plate
    approximates the flowline distance where ridges run roughly perpendicular to
    the spreading direction.

    Oceanic cells on a plate without a ridge are left NaN ("unconstrained"): their
    age is not fixed by the kinematics, and :func:`rewind` keeps them at every time.

    Returns:
        (age_myr, ridge_cell): age NaN for continental and unconstrained cells;
        ridge_cell is the index of the ridge cell whose front reached the cell, −1
        where none did.
    """
    age = np.full(kin.n, np.nan)
    source = np.full(kin.n, -1, dtype=np.int64)
    ocean = ~kin.continental
    heap: list[tuple[float, int, int]] = []
    for r in np.flatnonzero(np.isfinite(half_rate)).tolist():
        a0 = float(offset_km[r]) / (float(half_rate[r]) * _KM_PER_MYR_PER_CM_YR)
        heap.append((a0, r, r))
    heapq.heapify(heap)
    done = np.zeros(kin.n, dtype=bool)
    while heap:
        a, i, src = heapq.heappop(heap)
        if done[i]:
            continue
        done[i] = True
        age[i] = a
        source[i] = src
        speed = float(half_rate[src]) * _KM_PER_MYR_PER_CM_YR
        nb = kin.neighbors(i)
        nb = nb[ocean[nb] & (kin.plate[nb] == kin.plate[i]) & ~done[nb]]
        if nb.size == 0:
            continue
        steps = arc_km(kin.xyz[i], kin.xyz[nb], kin.radius_km) / speed
        for j, dt in zip(nb.tolist(), steps.tolist(), strict=True):
            heapq.heappush(heap, (a + dt, j, src))
    return age, source


@dataclass(frozen=True)
class RewoundState:
    """Parcels moved back to ``t_myr`` and resampled onto the present mesh.

    Attributes:
        t_myr: reconstruction time (Myr before present, ≥ 0).
        src: (N,) present-day cell (parcel) sampled by each mesh cell, −1 at gaps.
        gap: (N,) no parcel within the gap distance.
        overlap: (N,) parcels of two plates both lie close to the cell centre.
        dropped: (N,) present cells whose parcel did not exist at ``t``.
    """

    t_myr: float
    src: np.ndarray
    gap: np.ndarray
    overlap: np.ndarray
    dropped: np.ndarray


def rewind(
    kin: PlateKinematics,
    age_myr: np.ndarray,
    t_myr: float,
    gap_factor: float = 1.0,
    overlap_factor: float = 0.35,
) -> RewoundState:
    """Move all parcels that existed at ``t_myr`` back to their positions then.

    Args:
        kin: present-day kinematics.
        age_myr: seafloor age from :func:`synthesize_seafloor_age` (NaN = keep).
        t_myr: time before present.
        gap_factor: a cell whose nearest parcel is farther than this many cell
            spacings is a gap.
        overlap_factor: a cell is an overlap when parcels of two different plates
            both lie within this many cell spacings of its centre.  Regularly
            spaced parcels sit about one spacing apart, so two parcels inside
            0.35 spacings of one point are closer than the mesh allows.
    """
    dropped = ~kin.continental & np.isfinite(age_myr) & (age_myr < t_myr)
    keep = np.flatnonzero(~dropped)
    rot = rotation_matrices(kin.omega, -t_myr * 1.0e6)
    moved = np.einsum("nij,nj->ni", rot[kin.plate[keep]], kin.xyz[keep])

    tree = cKDTree(moved)
    spacing = kin.spacing_km
    k = min(4, len(keep))
    chord, idx = tree.query(kin.xyz, k=k)
    chord = chord.reshape(kin.n, k)
    idx = idx.reshape(kin.n, k)
    dist_km = 2.0 * kin.radius_km * np.arcsin(np.clip(chord / 2.0, 0.0, 1.0))

    nearest = keep[idx[:, 0]]
    gap = dist_km[:, 0] > gap_factor * spacing

    close = dist_km < overlap_factor * spacing
    plates_k = kin.plate[keep[idx]]
    other_plate_close = close & (plates_k != plates_k[:, :1]) & close[:, :1]
    overlap = other_plate_close.any(axis=1) & ~gap

    # In an overlap a continental parcel wins over an oceanic one: the ocean side
    # is the one that will be consumed.
    src = nearest.copy()
    cont_k = kin.continental[keep[idx]] & close
    pick_cont = overlap & ~kin.continental[nearest] & cont_k.any(axis=1)
    if pick_cont.any():
        first_cont = np.argmax(cont_k[pick_cont], axis=1)
        src[pick_cont] = keep[idx[pick_cont, first_cont]]
    src[gap] = -1
    return RewoundState(t_myr=t_myr, src=src, gap=gap, overlap=overlap, dropped=dropped)


def ocean_depth_m(
    age_myr: np.ndarray,
    ridge_depth_m: float,
    subsidence_coeff: float,
    max_depth_m: float,
) -> np.ndarray:
    """Plate-cooling depth (positive metres): ridge + coeff · √age, capped."""
    d: np.ndarray = np.minimum(
        ridge_depth_m + subsidence_coeff * np.sqrt(np.maximum(age_myr, 0.0)), max_depth_m
    )
    return d


@dataclass(frozen=True)
class PaleoFields:
    """Cell fields of a reconstructed time slice (same mesh as the present).

    Attributes:
        plate: (N,) plate index, −1 at gaps.
        continental: (N,) continental crust.
        age_myr: (N,) seafloor age at ``t`` (NaN on continents, gaps, unconstrained).
        elevation_m: (N,) elevation relative to the present datum.
    """

    plate: np.ndarray
    continental: np.ndarray
    age_myr: np.ndarray
    elevation_m: np.ndarray


def paleo_fields(
    kin: PlateKinematics,
    state: RewoundState,
    elevation_m: np.ndarray,
    age_myr: np.ndarray,
    *,
    ridge_depth_m: float,
    subsidence_coeff: float,
    max_depth_m: float,
    gap_depth_m: float | None = None,
) -> PaleoFields:
    """Crust type, age and elevation of each cell at ``state.t_myr``.

    Continental parcels keep their present elevation (orogen restoration is M2).
    An oceanic parcel of present age ``a`` had age ``a − t``; it was shallower by
    the difference of the cooling depths, added to its present elevation so that
    seamounts and other detail survive and ``t = 0`` is an identity.  Gaps are
    filled with old ocean at ``gap_depth_m`` (default: the capped cooling depth);
    M2 replaces this with tracer-based ages.
    """
    t = state.t_myr
    ok = state.src >= 0
    src = np.where(ok, state.src, 0)

    plate = np.where(ok, kin.plate[src], -1)
    continental = ok & kin.continental[src]

    a0 = age_myr[src]
    aged = ok & ~continental & np.isfinite(a0)
    age_t = np.full(kin.n, np.nan)
    age_t[aged] = a0[aged] - t

    elev = elevation_m[src].astype(float)
    if t > 0 and aged.any():
        rise = ocean_depth_m(a0[aged], ridge_depth_m, subsidence_coeff, max_depth_m) - (
            ocean_depth_m(age_t[aged], ridge_depth_m, subsidence_coeff, max_depth_m)
        )
        elev[aged] += rise
    elev[~ok] = -(max_depth_m if gap_depth_m is None else gap_depth_m)
    return PaleoFields(plate=plate, continental=continental, age_myr=age_t, elevation_m=elev)
