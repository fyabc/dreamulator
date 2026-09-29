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


class TestMeshSplitRoundTrip:
    """Geometry/fields split (P1 分离存储, 2026-09-29): the pair must carry
    every VoronoiCell field between them and round-trip the values."""

    def _tiny_mesh(self) -> CVTMesh:
        # 30 cells on a Fibonacci spiral with plausible mixed-type fields.
        import math

        n = 30
        golden = math.pi * (3.0 - math.sqrt(5.0))
        cells = []
        for i in range(n):
            y = 1.0 - 2.0 * i / (n - 1)
            r = math.sqrt(max(0.0, 1.0 - y * y))
            th = golden * i
            x, z = r * math.cos(th), r * math.sin(th)
            land = i % 3 != 0
            cells.append(
                VoronoiCell(
                    id=i,
                    lon=math.degrees(math.atan2(z, x)),
                    lat=math.degrees(math.asin(y)),
                    x=x,
                    y=y,
                    z=z,
                    area_km2=2500.0 + i,
                    elevation=(400.0 + i * 7) if land else (-3000.0 - i * 5),
                    crust_type="continental" if land else "oceanic",
                    plate_id=f"plate_{i % 4}",
                    water_class="land" if land else "ocean",
                    neighbors=[(i + 1) % n, (i + 2) % n],
                    temperature_C=15.0 - 0.4 * i if land else None,
                    koppen_class=["Af", "BWk", "EF", None][i % 4],
                    wind_east_m_s=-1.5 + 0.1 * i,
                    is_lake=(i % 7 == 0),
                    river_id=f"river_{i}" if i % 5 == 0 else None,
                    ice_thickness_m=120.0 if (land and i % 6 == 0) else None,
                    domesticable_tags=(["large_herbivores_low"] if i % 4 == 1 else []),
                    habitable_coast=True if land and i % 2 == 0 else None,
                )
            )
        return CVTMesh(
            seed=7,
            num_cells=n,
            jitter_sigma=0.3,
            lloyd_iterations=2,
            cells=cells,
            adjacency={},
            vertices=[[c.x, c.y, c.z] for c in cells],
            regions=[[i, (i + 1) % n] for i in range(n)],
        )

    def test_registry_covers_all_cell_fields(self):
        # Every VoronoiCell field is either a static column, a dynamic
        # column, neighbors, or id (implicit) — nothing silently dropped.
        from dreamulator.map.export import DYNAMIC_CELL_FIELDS, STATIC_CELL_COLUMNS
        from dreamulator.map.models import VoronoiCell as VoronoiCellModel

        known = set(STATIC_CELL_COLUMNS) | set(DYNAMIC_CELL_FIELDS) | {"neighbors"}
        model_fields = set(VoronoiCellModel.model_fields)
        missing = model_fields - known
        assert not missing, f"fields absent from the split: {sorted(missing)}"

    def test_split_round_trip_preserves_values(self, tmp_path):
        import json

        from dreamulator.map.export import (
            FIELDS_FILENAME,
            GEOMETRY_FILENAME,
            _mesh_json_bytes,
            load_mesh_fields,
            load_mesh_geometry,
            save_mesh_split,
        )

        mesh = self._tiny_mesh()
        obj = json.loads(_mesh_json_bytes(mesh))
        save_mesh_split(tmp_path, obj)

        geo = load_mesh_geometry(tmp_path / GEOMETRY_FILENAME)
        flds = load_mesh_fields(tmp_path / FIELDS_FILENAME)
        src_cells = obj["cells"]

        # Static columns (floats carry f32 precision vs the 4-decimal text)
        for name, vals in geo["columns"].items():
            for i in (0, 1, 4, 29):
                src = src_cells[i][name]
                if isinstance(src, float):
                    assert vals[i] is not None and abs(src - vals[i]) <= 1e-3 * max(
                        1.0, abs(src)
                    ), (name, i)
                else:
                    assert src == vals[i], (name, i)
        # Dynamic columns (floats compared with f32 tolerance)
        for name, vals in flds.items():
            for i in (0, 1, 4, 29):
                src = src_cells[i].get(name)
                dec = vals[i]
                if isinstance(src, float):
                    assert dec is not None and abs(src - dec) <= 1e-3 * max(1.0, abs(src)), (
                        name,
                        i,
                    )
                else:
                    assert src == dec, (name, i, src, dec)
        # Topology + metadata
        assert geo["num_cells"] == 30 and geo["seed"] == 7
        assert geo["neighbors"][5] == [6, 7]
        assert geo["regions"][3] == [3, 4]
        assert abs(geo["vertices"][10][0] - src_cells[10]["x"]) < 1e-5

    def test_save_cvt_mesh_writes_split_pair(self, tmp_path):
        from dreamulator.map.export import (
            FIELDS_FILENAME,
            GEOMETRY_FILENAME,
            MESH_FILENAME,
            save_cvt_mesh,
        )

        mesh = self._tiny_mesh()
        save_cvt_mesh(tmp_path / MESH_FILENAME, mesh)
        assert (tmp_path / GEOMETRY_FILENAME).exists()
        assert (tmp_path / FIELDS_FILENAME).exists()

    def test_split_matches_combined_cells(self, tmp_path):
        import json

        from dreamulator.map.export import (
            FIELDS_FILENAME,
            GEOMETRY_FILENAME,
            MESH_FILENAME,
            _mesh_json_bytes,
            load_cvt_mesh,
            load_mesh_fields,
            load_mesh_geometry,
            save_cvt_mesh,
        )

        mesh = self._tiny_mesh()
        save_cvt_mesh(tmp_path / MESH_FILENAME, mesh)
        combined = json.loads(_mesh_json_bytes(load_cvt_mesh(tmp_path / MESH_FILENAME)))
        geo = load_mesh_geometry(tmp_path / GEOMETRY_FILENAME)
        flds = load_mesh_fields(tmp_path / FIELDS_FILENAME)
        for i in (0, 7, 13, 29):
            rebuilt = {k: v[i] for k, v in geo["columns"].items()}
            rebuilt.update({k: v[i] for k, v in flds.items()})
            rebuilt["neighbors"] = geo["neighbors"][i]
            for k, v in combined["cells"][i].items():
                if k == "neighbors":
                    assert rebuilt[k] == v
                elif isinstance(v, float):
                    assert rebuilt[k] is not None and abs(v - rebuilt[k]) <= 1e-3 * max(
                        1.0, abs(v)
                    ), (i, k)
                else:
                    assert rebuilt[k] == v, (i, k, v, rebuilt[k])
