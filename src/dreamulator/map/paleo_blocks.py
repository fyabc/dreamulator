"""Continental blocks and weld relations for the geological timeline (G1).

Design: ``docs/design/proposals/geological-timeline.md`` §4.0, §4.5, §4.6.  The
present continental crust is cut into rigid blocks along the present plate
boundaries and the author's sutures.  Two blocks are *welded* while they move as
one rigid body:

* blocks of one present plate separated by sutures are welded until the
  youngest of those sutures' collision ages (before it they were apart);
* blocks of two plates across a continental rift are welded before the rift's
  onset (going back past the onset the rift has closed).

The weld groups at a time are the continental plates of that time.  This module
also composes stage rotations into finite rotations and derives a snapshot from
the blocks' motions (``block_snapshot``).  Pure functions on numpy arrays, no IO.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from dreamulator.map.paleo_kinematics import RewoundState, rewind_rotated, rotation_matrices

if TYPE_CHECKING:
    from dreamulator.map.paleo_kinematics import PlateKinematics
    from dreamulator.map.paleo_sutures import AuthorSuture


@dataclass(frozen=True)
class Weld:
    """Two blocks moving as one rigid body over an interval of time.

    Attributes:
        a, b: block indices.
        kind: ``suture`` or ``rift``.
        until_myr: welded for t ≤ until_myr (a suture's collision age), or None.
        since_myr: welded for t ≥ since_myr (a rift's onset), or None.
    """

    a: int
    b: int
    kind: str
    until_myr: float | None = None
    since_myr: float | None = None

    def active(self, t_myr: float) -> bool:
        """Whether the weld holds at ``t_myr`` (Myr before present)."""
        if self.until_myr is not None and t_myr > self.until_myr:
            return False
        return not (self.since_myr is not None and t_myr < self.since_myr)


@dataclass(frozen=True)
class Blocks:
    """Rigid continental blocks of the present map.

    Attributes:
        block: (N,) block of each continental cell, −1 on oceanic cells.
        plate: (B,) present plate of each block.
        welds: weld relations between blocks.
        names: (B,) readable labels, ``p<plate>`` plus the sutures whose
            leaving side holds the block.
    """

    block: np.ndarray
    plate: np.ndarray
    welds: list[Weld] = field(default_factory=list)
    names: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return int(self.plate.size)

    def groups(self, t_myr: float) -> np.ndarray:
        """(B,) weld group of each block at ``t_myr`` (smallest block index)."""
        parent = np.arange(self.n)

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = int(parent[i])
            return i

        for w in self.welds:
            if w.active(t_myr):
                ra, rb = find(w.a), find(w.b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
        return np.array([find(i) for i in range(self.n)])


def build_blocks(
    kin: PlateKinematics,
    sutures: list[AuthorSuture] | None = None,
    rift_onsets: dict[tuple[int, int], float] | None = None,
) -> Blocks:
    """Cut the present continental crust into blocks and list their welds.

    A cell's block is fixed by its present plate and by which sutures' leaving
    sides contain it (``paleo_sutures.check_suture``); sutures that do not sever
    their continent, or have no age, cut nothing.  ``rift_onsets`` maps a plate
    pair (smaller, larger) to its rift onset (``paleo_walk.continental_rifts``);
    blocks touching across that pair's continental boundary are welded before
    the onset.
    """
    from dreamulator.map.paleo_sutures import check_suture

    cont = kin.continental
    usable: list[tuple[AuthorSuture, np.ndarray]] = []
    for s in sutures or []:
        if s.collision_age_myr is None:
            continue
        c = check_suture(kin, s)
        if c.severed and c.leaving.any() and c.staying.any():
            usable.append((s, c.leaving))
    # signature of a continental cell: present plate + the sutures that move it away
    sig_bits = np.zeros((kin.n, len(usable)), dtype=bool)
    for k, (_, leaving) in enumerate(usable):
        sig_bits[:, k] = leaving
    keys: dict[tuple[int, tuple[int, ...]], int] = {}
    block = np.full(kin.n, -1)
    plates: list[int] = []
    sigs: list[tuple[int, ...]] = []
    for i in np.flatnonzero(cont):
        sig = tuple(np.flatnonzero(sig_bits[i]).tolist())
        key = (int(kin.plate[i]), sig)
        if key not in keys:
            keys[key] = len(plates)
            plates.append(key[0])
            sigs.append(sig)
        block[i] = keys[key]
    plate = np.array(plates, dtype=np.int64)
    names = [
        f"p{p}" + "".join(f"+{usable[k][0].id}" for k in sig)
        for p, sig in zip(plates, sigs, strict=True)
    ]
    welds: list[Weld] = []
    # suture welds: blocks of one plate stay together until the youngest suture
    # that separates them
    for a in range(len(plates)):
        for b in range(a + 1, len(plates)):
            if plates[a] != plates[b]:
                continue
            between = set(sigs[a]) ^ set(sigs[b])
            if between:
                age = min(float(usable[k][0].collision_age_myr or 0.0) for k in between)
                welds.append(Weld(a, b, "suture", until_myr=age))
    # rift welds: blocks touching across a continental rift, before its onset
    if rift_onsets:
        rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
        cols = kin.nbr_idx
        m = (rows < cols) & cont[rows] & cont[cols] & (kin.plate[rows] != kin.plate[cols])
        pairs = {
            (int(min(x, y)), int(max(x, y)))
            for x, y in zip(block[rows[m]], block[cols[m]], strict=True)
        }
        for a, b in sorted(pairs):
            pa, pb = int(plate[a]), int(plate[b])
            onset = rift_onsets.get((min(pa, pb), max(pa, pb)))
            if onset is not None:
                welds.append(Weld(a, b, "rift", since_myr=float(onset)))
    return Blocks(block=block, plate=plate, welds=welds, names=names)


def finite_rotations(stage_omega: np.ndarray, stage_myr: float, t_myr: float) -> np.ndarray:
    """Finite rotations taking present positions back to ``t_myr``.

    ``stage_omega`` is (S, K, 3): the rotation vector (rad/yr) of each of K
    bodies in each stage of ``stage_myr``, stage 0 nearest the present.  Stage
    rotations are applied from the present backwards (stage 0 first).  Returns
    (K, 3, 3).
    """
    s_count, k_count, _ = stage_omega.shape
    out = np.repeat(np.eye(3)[None], k_count, axis=0)
    remaining = t_myr
    for s in range(s_count):
        if remaining <= 0:
            break
        dt = min(stage_myr, remaining)
        step = rotation_matrices(stage_omega[s], -dt * 1.0e6)
        out = np.einsum("kij,kjl->kil", step, out)
        remaining -= dt
    if remaining > 1e-9:
        raise ValueError(f"stages cover {s_count * stage_myr} Myr, need {t_myr}")
    return out


def block_snapshot(
    kin: PlateKinematics,
    age_myr: np.ndarray,
    blocks: Blocks,
    block_rotation: np.ndarray,
    ocean_rotation: np.ndarray,
    t_myr: float,
) -> RewoundState:
    """Snapshot at ``t_myr`` from the blocks' finite rotations (§4.6, first step).

    Continental cells move with their block (``block_rotation``, (B, 3, 3));
    oceanic cells move with their present plate (``ocean_rotation``, (P, 3, 3)),
    which is the memory-window treatment of the present ocean plates.  Oceanic
    crust younger than ``t_myr`` is dropped; resampling, gaps and overlaps as in
    ``paleo_kinematics.rewind``.
    """
    cont = blocks.block >= 0
    rot = ocean_rotation[kin.plate].copy()
    rot[cont] = block_rotation[blocks.block[cont]]
    body = np.where(cont, kin.plate.max() + 1 + blocks.block, kin.plate)
    return rewind_rotated(kin, age_myr, t_myr, rot, body=body)
