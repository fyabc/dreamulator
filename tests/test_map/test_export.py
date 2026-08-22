"""Regression tests for map export (save_outputs).

v0.14.0 regression: the export step only "updated" ``map.yaml``.  When a
world was regenerated from scratch (no prior map.yaml existed), required
fields such as ``planet_id`` were silently missing and
``MapMetadata.model_validate`` crashed the maps API with a pydantic
ValidationError.  The export must write a self-contained map.yaml.
"""

import numpy as np
import yaml

from dreamulator.map.export import save_outputs
from dreamulator.map.models import (
    CVTMesh,
    EulerPole,
    MapMetadata,
    TectonicPlate,
    VoronoiCell,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig


def _tiny_mesh() -> CVTMesh:
    cells = []
    for i in range(8):
        lon = i * 45.0 - 180.0
        cells.append(
            VoronoiCell(
                id=i,
                lon=lon,
                lat=0.0,
                x=1.0,
                y=0.0,
                z=0.0,
                elevation=100.0 if i % 2 == 0 else -2000.0,
            )
        )
    return CVTMesh(seed=42, num_cells=len(cells), cells=cells)


def _one_plate() -> list[TectonicPlate]:
    return [
        TectonicPlate(
            id="plate_000",
            name="Test plate",
            cell_ids=list(range(8)),
            euler_pole=EulerPole(x=0.0, y=1.0, z=0.0, omega_rad_yr=1e-9),
        )
    ]


def test_save_outputs_writes_self_contained_map_yaml(tmp_path):
    """A fresh export (no pre-existing map.yaml) must validate on its own."""
    output_dir = tmp_path / "maps" / "planet_test"
    config = TerrainPipelineConfig(seed=7, num_nodes=8)
    grid = np.array([[100.0, -2000.0], [50.0, -1500.0]], dtype=np.float64)

    save_outputs(_tiny_mesh(), _one_plate(), grid, output_dir, config)

    map_yaml = output_dir / "map.yaml"
    assert map_yaml.exists()
    data = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))

    # Must pass MapMetadata validation without any pre-existing file.
    meta = MapMetadata.model_validate(data)
    assert meta.planet_id == "planet_test"  # derived from output dir name
    assert meta.voronoi_seed == 7
    assert meta.voronoi_num_cells == 8
    assert meta.width == config.export_width
    assert meta.height == config.export_height
