"""Source-stage capture preserves synthesis and exports its actual references."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.island_source import VolcanicCone, catalogue_geometry
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_cache import CacheConfig
from dreamulator.map.terrain_pipeline import run_terrain_pipeline
from dreamulator.map.terrain_source_export import (
    capture_source_field,
    load_terrain_source_fields,
    save_terrain_source_fields,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_capture_replays_cached_inputs_and_preserves_surface_and_source_envelope(
    tmp_path: Path,
) -> None:
    cfg = TerrainPipelineConfig(
        num_nodes=2000,
        num_plates=8,
        lloyd_iterations=1,
        tectonic_duration_my=30,
        seed=7,
        export_width=64,
        export_height=32,
    )
    stages = ["mesh", "plates", "tectonics", "boundaries", "terrain", "export"]
    cache = CacheConfig(enabled=True)
    original = run_terrain_pipeline(cfg, tmp_path, stages=stages, cache=cache)
    fields: dict[str, np.ndarray] = {}
    captured = run_terrain_pipeline(cfg, tmp_path, stages=stages, cache=cache, source_fields=fields)
    np.testing.assert_array_equal(
        [c.elevation for c in original.mesh.cells],
        [c.elevation for c in captured.mesh.cells],
    )
    components = [v for k, v in fields.items() if k.startswith("orogen.segment.")]
    assert components
    np.testing.assert_array_equal(np.maximum.reduce(components), fields["active_orogen_m"])
    np.testing.assert_array_equal(
        np.maximum(fields["active_orogen_m"], fields["paleo_orogen_m"]),
        fields["combined_orogen_m"],
    )
    assert all(not a.flags.writeable for a in fields.values())
    restored, meta = load_terrain_source_fields(tmp_path / "terrain_sources.npz")
    assert meta["cell_count"] == cfg.num_nodes
    assert meta["source"]["polarity_stage"] == "terrain-crust"
    assert meta["fields"]["cell_area_km2"]["units"] == "km²"
    np.testing.assert_array_equal(
        fields["cell_area_km2"], [cell.area_km2 for cell in captured.mesh.cells]
    )
    assert np.sum(fields["cell_area_km2"]) == pytest.approx(4 * np.pi * cfg.radius_km**2)
    assert meta["fields"]["coastal_lowland_target_m"]["units"] == "m"
    assert meta["fields"]["volcano_cell_mean_m"]["units"] == "m"
    assert meta["fields"]["arc_platform_m"]["units"] == "m"
    assert meta["fields"]["shelf_coast_width_m"]["units"] == "m"
    assert meta["fields"]["shelf_coast_drowned_width_m"]["units"] == "m"
    assert meta["fields"]["shelf_coast_type_width_m"]["units"] == "m"
    assert meta["fields"]["shelf_coast_type_active_mask"]["units"] == "boolean"
    assert meta["fields"]["shelf_continental_crust_mask"]["units"] == "boolean"
    assert "earlier tectonic labels" in meta["fields"]["shelf_continental_crust_mask"]["basis"]
    np.testing.assert_array_equal(
        fields["shelf_continental_crust_mask"],
        [cell.crust_type == "continental" for cell in captured.mesh.cells],
    )
    assert "global means" in meta["fields"]["shelf_coast_type_width_m"]["basis"]
    reachable = fields["shelf_coast_cell_id"] >= 0
    np.testing.assert_array_equal(
        fields["shelf_coast_width_m"][reachable],
        np.maximum(
            fields["shelf_coast_drowned_width_m"][reachable],
            fields["shelf_coast_type_width_m"][reachable],
        ),
    )
    np.testing.assert_array_equal(
        fields["shelf_coast_type_width_m"][reachable],
        np.where(fields["shelf_coast_type_active_mask"][reachable], 31000, 88000),
    )
    assert meta["fields"]["shelf_noise_fraction"]["units"] == "dimensionless"
    assert meta["fields"]["shelf_coast_cell_id"]["units"] == "source cell index; -1 is unavailable"
    np.testing.assert_array_equal(fields["after_shelf_m"], fields["before_coastal_plain_m"])
    from dreamulator.map.orogen_profile import apply_orogen_cap

    np.testing.assert_array_equal(
        apply_orogen_cap(
            fields["after_initial_sea_level_m"], fields["orogen_cap_m"], cfg.sea_level_offset_m
        ),
        fields["after_orogen_cap_m"],
    )
    assert fields["interior_lowland_clamped_mask"].dtype == bool
    assert meta["fields"]["interior_lowland_clamped_mask"]["units"] == "boolean"
    assert "above the sea-level" in meta["fields"]["orogen_cap_m"]["basis"]
    assert "initial sea-level" in meta["fields"]["final_forearc_surface_m"]["basis"]
    np.testing.assert_array_equal(fields["after_deposition_fill_m"], fields["before_shelf_m"])
    np.testing.assert_array_equal(
        np.minimum(fields["after_coastal_plain_m"], fields["final_forearc_surface_m"]),
        fields["after_forearc_m"],
    )
    shift = fields["after_final_sea_level_m"] - fields["after_deep_ocean_clamp_m"]
    np.testing.assert_allclose(shift, shift[0], rtol=0, atol=1e-8)
    np.testing.assert_array_equal(
        fields["after_overlay_archipelago_m"], fields["final_elevation_m"]
    )
    assert captured.island_catalog is not None
    geometry = meta["source"]["island_geometry"]
    assert geometry == catalogue_geometry(captured.island_catalog)
    for record in geometry["profiles"]:
        assert VolcanicCone.from_record(record).to_record() == record
    for name in fields:
        np.testing.assert_array_equal(restored[name], fields[name])
    # A later cache replay exports the same surface after capture populated terrain.
    replay = run_terrain_pipeline(cfg, tmp_path, stages=stages, cache=cache)
    np.testing.assert_array_equal(
        [c.elevation for c in original.mesh.cells],
        [c.elevation for c in replay.mesh.cells],
    )
    assert (tmp_path / "terrain_sources.npz").exists()
    with pytest.raises(ValueError, match="fingerprint"):
        load_terrain_source_fields(
            tmp_path / "terrain_sources.npz", expected_terrain_fingerprint="another"
        )
    cfg.coastal_plain_width_km += 10
    run_terrain_pipeline(cfg, tmp_path, stages=stages, cache=cache)
    assert not (tmp_path / "terrain_sources.npz").exists()
    assert not (tmp_path / "terrain_sources.json").exists()


def test_source_capture_freezes_arrays_and_archive_rejects_corruption(tmp_path: Path) -> None:
    fields: dict[str, np.ndarray] = {}
    xyz = np.eye(3)
    capture_source_field(fields, "xyz", xyz)
    capture_source_field(fields, "final_elevation_m", np.array([1.0, 2.0, 3.0]))
    xyz[:] = 0
    np.testing.assert_array_equal(fields["xyz"], np.eye(3))
    path = tmp_path / "sources.npz"
    save_terrain_source_fields(path, fields, radius_km=6371, source={"seed": 7})
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        load_terrain_source_fields(path)
    assert meta["fields"]["final_elevation_m"]["units"] == "m"
