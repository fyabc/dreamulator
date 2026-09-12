"""Regression test: cache-hit runs must re-apply cell plate assignments.

Bug (2026-09-12, nacrea): a build whose plates/tectonics stages hit the
terrain cache restores ``(plates, cell_plate_map)`` from the pickles, but the
in-place ``cell.plate_id = ...`` side effects of ``generate_plates`` /
``run_tectonic_evolution`` are never replayed — and ``mesh.pkl`` was saved
*before* the plates stage, so its cells carry ``plate_id = None``.  The
exported ``cvt_mesh.json`` then loses all 200k per-cell plate assignments
while ``plates.json`` (written from ``result.plates``) stays intact, blanking
the frontend plate layer / inspector plate info.
"""

import gzip
import json

from dreamulator.map.pipeline_types import TerrainPipelineConfig


def _read_exported_mesh(output_dir):
    mesh_files = list(output_dir.glob("**/cvt_mesh.json"))
    assert mesh_files, "export did not write cvt_mesh.json"
    raw = mesh_files[0].read_bytes()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


class TestPlateIdCacheReplay:
    def test_cache_hit_preserves_cell_plate_id(self, tmp_path):
        from dreamulator.map.terrain_cache import CacheConfig
        from dreamulator.map.terrain_pipeline import run_terrain_pipeline

        cfg = TerrainPipelineConfig(
            num_nodes=300,
            seed=42,
            lloyd_iterations=2,
            num_plates=6,
            tectonic_steps=5,
            export_width=64,
            export_height=32,
        )
        cache = CacheConfig(enabled=True, geography_hash="")

        # Run 1: fresh — executes plates/tectonics and populates the caches.
        r1 = run_terrain_pipeline(cfg, tmp_path, cache=cache)
        assert r1.plates, "fresh run produced no plates"
        assert all(c.plate_id is not None for c in r1.mesh.cells)

        # Run 2: every stage cache-hits (mesh.pkl predates the plates stage).
        r2 = run_terrain_pipeline(cfg, tmp_path, cache=cache)
        assert len(r2.plates) == len(r1.plates)
        assert all(
            c.plate_id is not None for c in r2.mesh.cells
        ), "cache-hit run lost cell plate_id (re-apply of cell_plate_map missing)"
        # The in-memory assignment must match run 1 cell-for-cell.
        assert [c.plate_id for c in r2.mesh.cells] == [c.plate_id for c in r1.mesh.cells]

        # And the exported mesh JSON (what the frontend reads) must carry it.
        data = _read_exported_mesh(tmp_path)
        missing = sum(1 for c in data["cells"] if not c.get("plate_id"))
        assert missing == 0, f"exported cvt_mesh.json: {missing} cells without plate_id"
