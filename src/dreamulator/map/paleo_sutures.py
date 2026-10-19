"""Author-given paleo-sutures for the plate topology walk.

Design: ``docs/design/proposals/geological-timeline.md`` §5.1.  A suture is a
polyline of [lon, lat] points (GeoJSON order) in the optional
``layers/geological/input/plate_history.yaml``; going back past its collision
age the plate holding it splits along it.  This module reads the file, measures
the sides of a polyline on the mesh and checks, on the present map, that a
suture cuts a continent into two pieces.  Pure functions on numpy arrays apart
from ``load_sutures``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

    from dreamulator.map.paleo_kinematics import PlateKinematics

# compass directions as (east, north) unit vectors
_COMPASS = {
    "north": (0.0, 1.0),
    "south": (0.0, -1.0),
    "east": (1.0, 0.0),
    "west": (-1.0, 0.0),
    "northeast": (0.7071, 0.7071),
    "northwest": (-0.7071, 0.7071),
    "southeast": (0.7071, -0.7071),
    "southwest": (-0.7071, -0.7071),
}


@dataclass(frozen=True)
class AuthorSuture:
    """One suture from ``plate_history.yaml``.

    Attributes:
        id: stable identifier.
        name: display name.
        collision_age_myr: collision age (Myr before present), or None while the
            author has not set it.
        path: (m, 2) [lon, lat] degrees.
        width_km: half-width of the belt marked along the path.
        moving_side: side that leaves going back: ``left`` / ``right`` (relative to
            the path direction), a compass direction, or None for the smaller side.
        closing_rate_cm_yr: convergence rate before the collision, or None.
    """

    id: str
    name: str
    collision_age_myr: float | None
    path: np.ndarray
    width_km: float = 150.0
    moving_side: str | None = None
    closing_rate_cm_yr: float | None = None


def load_sutures(path: Path) -> list[AuthorSuture]:
    """Read the ``sutures`` list of a ``plate_history.yaml`` (empty if absent)."""
    import yaml

    if not path.exists():
        return []
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for item in data.get("sutures") or []:
        side = item.get("moving_side")
        if side is not None and side not in ("left", "right") and side not in _COMPASS:
            raise ValueError(f"suture {item['id']}: unknown moving_side {side!r}")
        age = item.get("collision_age_myr")
        rate = item.get("closing_rate_cm_yr")
        out.append(
            AuthorSuture(
                id=str(item["id"]),
                name=str(item.get("name", item["id"])),
                collision_age_myr=None if age is None else float(age),
                path=np.asarray(item["path"], dtype=float),
                width_km=float(item.get("width_km", 150.0)),
                moving_side=side,
                closing_rate_cm_yr=None if rate is None else float(rate),
            )
        )
    return out


def lonlat_to_xyz(lonlat: np.ndarray) -> np.ndarray:
    """Unit vectors in the engine convention (y north, lon = atan2(z, x))."""
    lon, lat = np.radians(lonlat[:, 0]), np.radians(lonlat[:, 1])
    return np.stack([np.cos(lat) * np.cos(lon), np.sin(lat), np.cos(lat) * np.sin(lon)], axis=1)


def polyline_geometry(xyz: np.ndarray, path_lonlat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Angular distance (rad) to a great-circle polyline and the side of each point.

    The side is +1 left, −1 right of the travel direction, read from the
    nearest segment (beyond the ends, from the great circle of the end segment).
    """
    v = lonlat_to_xyz(path_lonlat)
    best = np.full(len(xyz), np.inf)
    side = np.zeros(len(xyz))
    for a, b in zip(v[:-1], v[1:], strict=True):
        n = np.cross(a, b)
        n /= np.linalg.norm(n)
        s = xyz @ n
        proj = xyz - s[:, None] * n
        proj /= np.maximum(np.linalg.norm(proj, axis=1, keepdims=True), 1e-15)
        ab = np.arccos(np.clip(a @ b, -1.0, 1.0))
        on = (
            np.arccos(np.clip(proj @ a, -1.0, 1.0)) + np.arccos(np.clip(proj @ b, -1.0, 1.0))
            <= ab + 1e-9
        )
        d = np.where(
            on,
            np.abs(np.arcsin(np.clip(s, -1.0, 1.0))),
            np.minimum(np.arccos(np.clip(xyz @ a, -1, 1)), np.arccos(np.clip(xyz @ b, -1, 1))),
        )
        closer = d < best
        best = np.where(closer, d, best)
        # engine frame is left-handed: a × b points to the right of a → b
        side = np.where(closer, -np.sign(s), side)
    return best, side


def resolve_side(
    moving_side: str | None,
    xyz: np.ndarray,
    side: np.ndarray,
    weights: np.ndarray,
    path_lonlat: np.ndarray,
) -> int:
    """The leaving side (+1 left, −1 right) for a ``moving_side`` value.

    Compass directions pick the side whose weighted centroid lies farther that
    way from the path midpoint; None picks the side with less weight.
    """
    if moving_side == "left":
        return 1
    if moving_side == "right":
        return -1
    if moving_side is None:
        return 1 if weights[side > 0].sum() <= weights[side < 0].sum() else -1
    mid = lonlat_to_xyz(path_lonlat[[len(path_lonlat) // 2]])[0]
    lon, lat = np.arctan2(mid[2], mid[0]), np.arcsin(mid[1])
    east = np.array([-np.sin(lon), 0.0, np.cos(lon)])
    north = np.array([-np.sin(lat) * np.cos(lon), np.cos(lat), -np.sin(lat) * np.sin(lon)])
    ce, cn = _COMPASS[moving_side]
    want = ce * east + cn * north
    score = {}
    for sgn in (1, -1):
        m = side == sgn
        c = (xyz[m] * weights[m, None]).sum(axis=0) if m.any() else np.zeros(3)
        score[sgn] = float(c @ want / max(float(np.linalg.norm(c)), 1e-15))
    return 1 if score[1] >= score[-1] else -1


@dataclass(frozen=True)
class SutureCheck:
    """A suture measured on the present map.

    Attributes:
        plate: plate holding most of the belt's continental cells.
        plate_share: that plate's share of the belt's continental cells.
        belt: (N,) cells within ``width_km`` of the path.
        leaving: (N,) continental cells of the plate on the leaving side.
        staying: (N,) continental cells of the plate on the other side.
        severed: no block of the continent outside the belt lies in force on both
            sides near the path (the continent does not go round an end).
        leaving_km2, staying_km2: continental areas of the two sides.
        leak_cells: (N,) cells near the path where the continent goes round the
            belt (the minority side of a block lying on both sides).
        orogeny_share: share of the belt's continental cells that are
            paleo-orogeny belt cells (``landform == "orogeny"`` or ``"basin"``).
        warnings: human-readable findings.
    """

    plate: int
    plate_share: float
    belt: np.ndarray
    leaving: np.ndarray
    staying: np.ndarray
    severed: bool
    leaving_km2: float
    staying_km2: float
    leak_cells: np.ndarray
    orogeny_share: float
    warnings: list[str]


def check_suture(
    kin: PlateKinematics,
    suture: AuthorSuture,
    landform: np.ndarray | None = None,
    min_cells: int | None = None,
) -> SutureCheck:
    """Measure a suture on the present mesh (§5.1 consistency checks).

    The two sides are the plate's continental cells left and right of the path,
    restricted to the continent the belt lies on.  The suture severs that
    continent when no chain of neighbouring continental cells outside the belt
    joins a left cell to a right cell; each side must reach the enclave rule's
    size (``max(50, 0.3 %)`` cells).
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    min_cells = min_cells or max(50, int(0.003 * kin.n))
    dist, side = polyline_geometry(kin.xyz, suture.path)
    belt = dist * kin.radius_km <= suture.width_km
    cont = kin.continental
    warnings: list[str] = []
    bc = belt & cont
    if not bc.any():
        empty = np.zeros(kin.n, dtype=bool)
        return SutureCheck(
            -1, 0.0, belt, empty, empty, False, 0.0, 0.0, empty, 0.0, ["no continental crust"]
        )
    plate = int(np.bincount(kin.plate[bc]).argmax())
    share = float(np.mean(kin.plate[bc] == plate))
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    land = cont & (kin.plate == plate)
    # the continent the belt lies on: plate continent linked to the belt
    m = land[rows] & land[cols]
    g = csr_matrix((np.ones(int(m.sum())), (rows[m], cols[m])), shape=(kin.n, kin.n))
    _, lab = connected_components(g, directed=False)
    on_belt = np.unique(lab[bc & land])
    continent = land & np.isin(lab, on_belt)
    rest = continent & ~belt
    m2 = rest[rows] & rest[cols]
    g2 = csr_matrix((np.ones(int(m2.sum())), (rows[m2], cols[m2])), shape=(kin.n, kin.n))
    _, lab2 = connected_components(g2, directed=False)
    # Sides are read only near the path (within two half-widths, and at least two
    # spacings beyond the belt on coarse meshes): far away the
    # nearest-segment side flips between the bisectors of a winding path, which
    # says nothing about the cut.  A block of the continent outside the belt
    # takes the side of its near cells; it leaks when its near cells sit on both
    # sides in force, i.e. the continent goes round an end of the belt.
    reach_km = max(2.0 * suture.width_km, suture.width_km + 2.0 * kin.spacing_km)
    near = rest & (dist * kin.radius_km <= reach_km)
    block_side = np.zeros(int(lab2.max()) + 1)
    big_leak = []
    leak_cells = np.zeros(kin.n, dtype=bool)
    for c in np.unique(lab2[near]):
        nl = int(np.sum(near & (lab2 == c) & (side > 0)))
        nr = int(np.sum(near & (lab2 == c) & (side < 0)))
        block_side[c] = 1.0 if nl >= nr else -1.0
        if min(nl, nr) >= 5:
            minority = 1.0 if nl < nr else -1.0
            leak_cells |= near & (lab2 == c) & (side == minority)
            if min(nl, nr) >= max(5, min_cells // 10):
                big_leak.append(int(c))
    severed = not big_leak
    cell_side = np.where(rest, block_side[lab2], 0.0)
    sgn = resolve_side(suture.moving_side, kin.xyz, cell_side, kin.area_km2 * rest, suture.path)
    leaving = rest & (cell_side == sgn)
    staying = rest & (cell_side == -sgn)
    a_leave = float(kin.area_km2[leaving].sum())
    a_stay = float(kin.area_km2[staying].sum())
    if share < 0.5:
        warnings.append(f"belt spans several plates (plate {plate} holds {share:.0%})")
    if not severed:
        warnings.append("does not sever the continent: the two sides join around the belt")
    elif leak_cells.any():
        warnings.append(f"continent goes round the belt in {int(leak_cells.sum())} cells (minor)")
    if min(leaving.sum(), staying.sum()) < min_cells:
        warnings.append(f"a side is smaller than the enclave size ({min_cells} cells)")
    if a_leave > a_stay:
        warnings.append("leaving side is the larger one")
    oro = 0.0
    if landform is not None:
        oro = float(np.mean(np.isin(landform[bc], ["orogeny", "basin"])))
    if suture.collision_age_myr is None:
        warnings.append("collision_age_myr not set")
    return SutureCheck(
        plate, share, belt, leaving, staying, severed, a_leave, a_stay, leak_cells, oro, warnings
    )


def author_suture_belts(
    kin: PlateKinematics, sutures: list[AuthorSuture], landform: np.ndarray | None = None
) -> tuple[list[Any], list[tuple[str, SutureCheck]]]:
    """Author sutures as ``paleo_walk.SutureBelt`` events, with their checks.

    Sutures without a collision age, or that do not sever their continent on the
    present map, are left out (their checks say why).
    """
    from dreamulator.map.paleo_walk import SutureBelt

    belts = []
    checks = []
    for s in sutures:
        c = check_suture(kin, s, landform)
        checks.append((s.id, c))
        if s.collision_age_myr is None or not c.severed or not c.leaving.any():
            continue
        belts.append(
            SutureBelt(
                age_myr=s.collision_age_myr,
                cells=np.flatnonzero(c.belt),
                age_source="author",
                leaving_cells=np.flatnonzero(c.leaving),
                closing_rate_cm_yr=s.closing_rate_cm_yr,
                id=s.id,
            )
        )
    return sorted(belts, key=lambda b: b.age_myr), checks
