#!/usr/bin/env python3
"""Geological timeline G3, step 2: compare an earth solve with a published reconstruction.

Reads a solve of ``paleo_solve.py`` on the earth map and a published plate
model (rotation files plus static polygons, e.g. Müller et al. 2019, read with
pyGPlates from the ``validation`` extra).  Continental cells get their plate ID
from the static polygons and are reconstructed with the published rotations;
the same cells are moved with the solved block rotations and, as a baseline,
with the present poles held fixed.  Absolute reference frames differ (the
solver keeps the frame of the present poles), so at each epoch the best-fit
global rotation between the two sets is removed before measuring the
area-weighted angular misfit, overall and for the large continents.  Also
reports the distance between the South American and African continental
centroids and the contact welds of the solve (§9, item 3).

Usage::

    uv run python scripts/geology/paleo_earth_compare.py data/worlds/earth/maps/planet_earth \\
        --solve-dir /tmp/earth_solve \\
        --rotations SimplifiedFiles/Muller_etal_2019_CombinedRotations.rot \\
        --static-polygons SimplifiedFiles/Muller_etal_2019_Global_StaticPlatePolygons.gpmlz \\
        --out-dir /tmp/earth_compare
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from paleo_rewind import World

from dreamulator.map.paleo_blocks import build_blocks, finite_rotations
from dreamulator.map.paleo_kinematics import (
    continental_speed_poles,
    no_net_rotation,
    rotation_matrices,
)
from dreamulator.map.paleo_walk import continental_rifts

PLATES = ("NA", "SA", "EU", "AF", "IN", "AU", "AN")
EPOCHS = (30.0, 60.0, 90.0, 120.0, 150.0)


def to_lonlat(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Engine convention: y north, lon = atan2(z, x)."""
    lon = np.degrees(np.arctan2(xyz[:, 2], xyz[:, 0]))
    lat = np.degrees(np.arcsin(np.clip(xyz[:, 1], -1.0, 1.0)))
    return lon, lat


def from_lonlat(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    lo, la = np.radians(lon), np.radians(lat)
    return np.stack([np.cos(la) * np.cos(lo), np.sin(la), np.cos(la) * np.sin(lo)], axis=1)


def published(
    rotation_files: list[Path],
    static_polygons: Path,
    lon: np.ndarray,
    lat: np.ndarray,
    epochs: tuple[float, ...],
) -> tuple[np.ndarray, dict[float, np.ndarray]]:
    """Plate IDs of the points and their positions at each epoch (engine xyz)."""
    import pygplates

    model = pygplates.RotationModel([str(p) for p in rotation_files])
    partitioner = pygplates.PlatePartitioner(str(static_polygons), model)
    pid = np.full(lon.size, -1, dtype=np.int64)
    for i, (lo, la) in enumerate(zip(lon, lat, strict=True)):
        poly = partitioner.partition_point(pygplates.PointOnSphere(float(la), float(lo)))
        if poly is not None:
            pid[i] = poly.get_feature().get_reconstruction_plate_id()
    out: dict[float, np.ndarray] = {}
    for t in epochs:
        lon_t, lat_t = lon.copy(), lat.copy()
        for p in np.unique(pid[pid >= 0]):
            rot = model.get_rotation(float(t), int(p))
            for i in np.flatnonzero(pid == p):
                q = rot * pygplates.PointOnSphere(float(lat[i]), float(lon[i]))
                lat_t[i], lon_t[i] = q.to_lat_lon()
        out[t] = from_lonlat(lon_t, lat_t)
    return pid, out


def best_fit(a: np.ndarray, b: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Rotation R minimising Σ w |R a − b|² (Kabsch)."""
    h = (a * w[:, None]).T @ b
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r: np.ndarray = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    return r


def misfit_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    out: np.ndarray = np.degrees(np.arccos(np.clip(np.sum(a * b, axis=1), -1.0, 1.0)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_dir", type=Path)
    ap.add_argument("--solve-dir", type=Path, required=True)
    ap.add_argument("--rotations", type=Path, nargs="+", required=True)
    ap.add_argument("--static-polygons", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--points", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    summary = json.loads((args.solve_dir / "summary.json").read_text(encoding="utf-8"))
    stage = summary["config"]["stage_myr"]
    stage_omega = np.load(args.solve_dir / "solve.npz")["stage_omega"]
    w = World(args.map_dir)
    # absolute speeds refer to the no-net-rotation frame (PB2002 holds the Pacific fixed)
    w.kin = replace(w.kin, omega=no_net_rotation(w.kin))
    kin = replace(w.kin, omega=continental_speed_poles(w.kin))
    _, onsets = continental_rifts(kin, 300.0)
    blocks = build_blocks(kin, [], onsets)

    rng = np.random.default_rng(args.seed)
    cont = np.flatnonzero(blocks.block >= 0)
    pick = np.sort(rng.choice(cont, size=min(args.points, cont.size), replace=False))
    x0 = kin.xyz[pick]
    area = kin.area_km2[pick]
    lon, lat = to_lonlat(x0)
    pid, pub = published(args.rotations, args.static_polygons, lon, lat, EPOCHS)
    ok = pid >= 0
    plate_codes = [
        p["id"] for p in json.loads((args.map_dir / "plates.json").read_text(encoding="utf-8"))
    ]
    code = np.array([plate_codes[i] for i in w.kin.plate[pick]])

    t_max = stage * stage_omega.shape[0]
    rows = []
    for t in EPOCHS:
        if t > t_max + 1e-9:
            continue
        solved = np.einsum(
            "pij,pj->pi", finite_rotations(stage_omega, stage, t)[blocks.block[pick]], x0
        )
        fixed = np.einsum(
            "pij,pj->pi", rotation_matrices(w.kin.omega, -t * 1.0e6)[w.kin.plate[pick]], x0
        )
        row: dict[str, object] = {"t_myr": t}
        for name, pos in (("solver", solved), ("fixed_present_poles", fixed), ("no_motion", x0)):
            r = best_fit(pos[ok], pub[t][ok], area[ok])
            err = misfit_deg(pos @ r.T, pub[t])
            row[name] = {
                "mean_deg": round(float(np.average(err[ok], weights=area[ok])), 1),
                **{
                    c: round(
                        float(np.average(err[ok & (code == c)], weights=area[ok & (code == c)])), 1
                    )
                    for c in PLATES
                    if (ok & (code == c)).any()
                },
            }

        def centroid(pos: np.ndarray, c: str) -> np.ndarray:
            m = ok & (code == c)
            v = (pos[m] * area[m, None]).sum(axis=0)
            out: np.ndarray = v / np.linalg.norm(v)
            return out

        row["SA_AF_centroid_deg"] = {
            "solver": round(
                float(misfit_deg(centroid(solved, "SA")[None], centroid(solved, "AF")[None])[0]), 1
            ),
            "published": round(
                float(misfit_deg(centroid(pub[t], "SA")[None], centroid(pub[t], "AF")[None])[0]), 1
            ),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    welds = [
        c
        for c in summary.get("contact_welds", [])
        if any(
            f"p{plate_codes.index(x)}" in (c["a"].split("+")[0], c["b"].split("+")[0])
            for x in ("SA", "AF")
        )
    ]
    out = {
        "epochs": rows,
        "contact_welds_SA_AF": welds,
        "all_contact_welds": summary.get("contact_welds", []),
    }
    print(json.dumps({"contact_welds_SA_AF": welds}, ensure_ascii=False))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "earth_compare.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
