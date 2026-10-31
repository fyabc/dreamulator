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


def _make_canvas(root: Path, geom: CanvasGeometry, elevations: dict[tuple[int, int], int]) -> None:
    (root / "chunks").mkdir(parents=True)
    (root / "canvas.json").write_text(
        json.dumps({"geometry": geom.to_dict(), "chunks": [[0, 0]]}), encoding="utf-8"
    )
    dem = np.zeros((TILE, TILE), dtype=np.int16)
    for (row, col), value in elevations.items():
        dem[row, col] = value
    np.save(root / "chunks" / "r000_c000.npy", dem)


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
    _make_canvas(alpha, geom, {(2, 3): 100, (3, 3): 200, (4, 3): 50})
    _make_canvas(beta, geom, {(2, 3): 110, (3, 3): 300})
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
    assert pair["elevation"]["n"] == 2
    assert pair["elevation"]["max_abs_m"] == 100.0
    # alpha alone marks sample 1 as lake: one water disagreement.
    assert pair["water_disagree"] == 1
    # Both sides carry a river at the first sample: flow ratio 1.2.
    assert pair["flow_ratio"] is not None
    assert abs(pair["flow_ratio"]["max"] - 1.2) < 1e-6
    # Recorded coordinates re-derive from lat/lon on both canvases.
    assert pair["coord_mismatch_px"] < 1.0
