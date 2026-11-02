"""S4 seam-consistency checks on synthetic canvases (no real world data)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np

from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.media.canvas_seam import run_seam_check

if TYPE_CHECKING:
    from pathlib import Path

TILE = 8


def _make_canvas(
    root: Path,
    geom: CanvasGeometry,
    elevations: dict[tuple[int, int], int],
    *,
    ice: dict[tuple[int, int], float] | None = None,
    conditioning: bool = False,
) -> None:
    (root / "chunks").mkdir(parents=True)
    meta: dict[str, object] = {"geometry": geom.to_dict(), "chunks": [[0, 0]]}
    if conditioning:
        meta["sea_mask"] = {"version": "connected-sea-inland-low-20261031-v1"}
    (root / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
    dem = np.zeros((TILE, TILE), dtype=np.int16)
    for (row, col), value in elevations.items():
        dem[row, col] = value
    np.save(root / "chunks" / "r000_c000.npy", dem)
    if ice is not None:
        ice_dir = root / "surface" / "ice_chunks"
        ice_dir.mkdir(parents=True)
        thickness = np.zeros((TILE, TILE), dtype=np.float32)
        for (row, col), value in ice.items():
            thickness[row, col] = value
        np.save(ice_dir / "r000_c000.npy", thickness)
    if conditioning:
        # One 23 km cell covers the whole 8-px tile: geological ocean in it.
        height = np.full((geom.ncell, geom.ncell), 100.0, dtype=np.float32)
        height[0, 0] = -100.0
        cond_dir = root / "conditioning"
        cond_dir.mkdir(parents=True)
        np.save(cond_dir / "heightmap.npy", height)


def _write_hydro(
    root: Path,
    *,
    lake_cells: list[tuple[int, int]],
    river_flow: float | None,
    geom: CanvasGeometry,
) -> None:
    if lake_cells:
        sparse = root / "hydro" / "lakes.sparse"
        sparse.mkdir(parents=True)
        idx = np.asarray([r * TILE + c for r, c in lake_cells], dtype=np.uint32)
        np.savez(
            sparse / "lake.r000_c000.npz",
            idx=idx,
            lake_id=np.ones(idx.size, dtype=np.uint16),
        )
    else:
        (root / "hydro" / "lakes.sparse").mkdir(parents=True)
    if river_flow is not None:
        # A segment through the first sample point in the product's own frame.
        px = geom.px_km
        x = 3.5 * px
        y = (geom.size_px - 1.0 - 2.5) * px
        line = np.asarray([[[x - 2 * px, y], [x + 2 * px, y]]], dtype=np.float32)
        (root / "hydro").mkdir(parents=True, exist_ok=True)
        np.save(root / "hydro" / "rivers.line.npy", line)
        np.save(root / "hydro" / "rivers.flow.npy", np.asarray([river_flow], dtype=np.float32))


def test_seam_check_reports_disagreement_and_gaps(tmp_path: Path) -> None:
    canvases = tmp_path / "canvases"
    canvases.mkdir()
    geom = CanvasGeometry(10.0, 20.0, 6816.97, 16)

    def latlon(row: float, col: float) -> tuple[float, float]:
        lat, lon = geom.pixel_to_latlon(np.asarray([row]), np.asarray([col]))
        return float(np.ravel(lat)[0]), float(np.ravel(lon)[0])

    alpha = canvases / "alpha"
    beta = canvases / "beta"
    alpha.mkdir()
    beta.mkdir()
    # alpha carries 100 m of ice at the second sample point, beta none.
    _make_canvas(alpha, geom, {(2, 3): 100, (3, 3): 200, (4, 3): 50}, ice={(3, 3): 100.0})
    _make_canvas(beta, geom, {(2, 3): 110, (3, 3): 300}, ice={})
    _write_hydro(alpha, lake_cells=[(2, 3)], river_flow=10.0, geom=geom)
    _write_hydro(beta, lake_cells=[], river_flow=12.0, geom=geom)

    lat1, lon1 = latlon(2.5, 3.5)
    lat2, lon2 = latlon(3.5, 3.5)
    lat3, lon3 = latlon(4.5, 3.5)

    def loc(canvas: str, row: float, col: float, chunk: tuple[int, int]) -> dict[str, object]:
        return {"canvas": canvas, "row_px": row, "col_px": col, "chunk": list(chunk)}

    pairs = {
        "format": "seam-pairs-v1",
        "pairs": [
            {
                "canvases": ["alpha", "beta"],
                "samples": [
                    {
                        "cell_ids": [1, 2],
                        "latitude_deg": lat1,
                        "longitude_deg": lon1,
                        "locations": [
                            loc("alpha", 2.5, 3.5, (0, 0)),
                            loc("beta", 2.5, 3.5, (0, 0)),
                        ],
                    },
                    {
                        "cell_ids": [3, 4],
                        "latitude_deg": lat2,
                        "longitude_deg": lon2,
                        "locations": [
                            loc("alpha", 3.5, 3.5, (0, 0)),
                            loc("beta", 3.5, 3.5, (0, 0)),
                        ],
                    },
                    {
                        # beta has no chunk here: elevation is unverified.
                        "cell_ids": [5, 6],
                        "latitude_deg": lat3,
                        "longitude_deg": lon3,
                        "locations": [
                            loc("alpha", 4.5, 3.5, (0, 0)),
                            loc("beta", 4.5, 3.5, (1, 0)),
                        ],
                    },
                ],
            }
        ],
    }
    (canvases / "seam_pairs.json").write_text(json.dumps(pairs), encoding="utf-8")

    report = run_seam_check(canvases)
    assert report["canvases_with_chunks"] == ["alpha", "beta"]
    (pair,) = report["pairs"]
    assert pair["samples"] == 3
    # Two samples had terrain on both sides; the third is unverified.
    assert pair["counts"]["elevation"] == 2
    assert pair["surface_delta"]["n"] == 2
    assert pair["surface_delta"]["max_abs_m"] == 100.0
    # Bed = surface minus ice: the 100 m of ice on alpha doubles sample 2's
    # delta (200 - 100 = 100 vs 300); sample 1 keeps its surface delta.
    assert pair["counts"]["bedrock"] == 2
    assert pair["bed_delta"]["n"] == 2
    assert pair["bed_delta"]["max_abs_m"] == 200.0
    worst_by_lat = {w["lat"]: w for w in pair["worst"]}
    icy = next(w for w in pair["worst"] if w["ice_m"] == [100.0, 0.0])
    assert icy["surface_delta_m"] == -100.0
    assert icy["bed_delta_m"] == -200.0
    assert len(worst_by_lat) == 2
    # Neither canvas ships a conditioning grid: land/sea stays unverified.
    assert pair["counts"]["landsea"] == 0
    assert pair["landsea_disagree"] == 0
    # alpha alone marks sample 1 as lake: one water disagreement.
    assert pair["water_disagree"] == 1
    # Both sides carry a river at the first sample: flow ratio 1.2.
    assert pair["flow_ratio"] is not None
    assert abs(pair["flow_ratio"]["max"] - 1.2) < 1e-6
    # Recorded coordinates re-derive from lat/lon on both canvases.
    assert pair["coord_mismatch_px"] < 1.0


def test_seam_check_flags_landsea_disagreement(tmp_path: Path) -> None:
    canvases = tmp_path / "canvases"
    canvases.mkdir()
    geom = CanvasGeometry(10.0, 20.0, 6816.97, 16)

    def latlon(row: float, col: float) -> tuple[float, float]:
        lat, lon = geom.pixel_to_latlon(np.asarray([row]), np.asarray([col]))
        return float(np.ravel(lat)[0]), float(np.ravel(lon)[0])

    land = {(r, c): 100 for r in range(TILE) for c in range(TILE)}
    sea_column = {**land, **{(r, 3): -50 for r in range(TILE)}}
    gamma = canvases / "gamma"  # a sea column that reaches the canvas edge
    delta = canvases / "delta"  # the same point on land
    gamma.mkdir()
    delta.mkdir()
    _make_canvas(gamma, geom, sea_column, conditioning=True)
    _make_canvas(delta, geom, land, conditioning=True)

    lat_sea, lon_sea = latlon(5.5, 3.5)
    lat_land, lon_land = latlon(1.5, 6.5)

    def loc(canvas: str, row: float, col: float) -> dict[str, object]:
        return {"canvas": canvas, "row_px": row, "col_px": col, "chunk": [0, 0]}

    pairs = {
        "format": "seam-pairs-v1",
        "pairs": [
            {
                "canvases": ["gamma", "delta"],
                "samples": [
                    {
                        "cell_ids": [7, 8],
                        "latitude_deg": lat_sea,
                        "longitude_deg": lon_sea,
                        "locations": [loc("gamma", 5.5, 3.5), loc("delta", 5.5, 3.5)],
                    },
                    {
                        "cell_ids": [9, 10],
                        "latitude_deg": lat_land,
                        "longitude_deg": lon_land,
                        "locations": [loc("gamma", 1.5, 6.5), loc("delta", 1.5, 6.5)],
                    },
                ],
            }
        ],
    }
    (canvases / "seam_pairs.json").write_text(json.dumps(pairs), encoding="utf-8")

    report = run_seam_check(canvases)
    (pair,) = report["pairs"]
    # Both samples carry the anchored determination; the sea/land point
    # disagrees, the land/land point does not.
    assert pair["counts"]["landsea"] == 2
    assert pair["landsea_disagree"] == 1
    (point,) = pair["landsea_points"]
    assert point["sides"] == [True, False]
    # No ice product on either side: the bedrock caliber stays unverified
    # rather than silently equalling the surface.
    assert pair["counts"]["bedrock"] == 0
    assert pair["bed_delta"] is None
