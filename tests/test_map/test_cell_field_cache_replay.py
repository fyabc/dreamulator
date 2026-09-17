"""Regression test: cache-hit runs must replay every in-place cell field.

Bug (2026-09-17, nacrea): stage pickles captured only part of each stage's
in-place cell side effects — ``boundaries.pkl`` stored just
``boundary_cell_ids`` (losing ``distance_to_boundary_km`` /
``convergence_rate_cm_yr`` / ``tangential_fraction``), ``terrain.pkl`` stored
an (elev, crust, btype) triple (losing ``landform``), and ``tectonics.pkl``
stored (plates, cell_plate_map) (losing the cumulative convergence /
divergence fields).  Any all-cache-hit rebuild then exported a mesh with
these fields empty (inf distance → null), blanking the frontend landform /
tectonic layers — while the elevation shapes survived (the cached arrays),
so the loss was invisible until someone opened the layer panel.

The guard: a fresh run and a fully cached replay must produce **identical
cells — every VoronoiCell field**.  Any future stage that gains an in-place
cell field without extending its cache payload fails here.
"""

import gzip
import json

from dreamulator.map.pipeline_types import TerrainPipelineConfig


def _read_exported_mesh(output_dir):
    mesh_files = list(output_dir.glob("**/cvt_mesh.json"))
    assert mesh_files, "export did not write cvt_mesh.json"
    raw = mesh_files[0].read_bytes()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


class TestCellFieldCacheReplay:
    def test_replay_matches_fresh_cells_field_for_field(self, tmp_path):
        from dreamulator.map.terrain_cache import CacheConfig
        from dreamulator.map.terrain_pipeline import run_terrain_pipeline

        cfg = TerrainPipelineConfig(
            num_nodes=2000,
            seed=42,
            lloyd_iterations=2,
            num_plates=8,
            tectonic_steps=8,
            export_width=128,
            export_height=64,
        )
        cache = CacheConfig(enabled=True, geography_hash="")

        # Run 1: fresh — executes every stage and populates the caches.
        r1 = run_terrain_pipeline(cfg, tmp_path, cache=cache)

        # Preconditions: the fresh run must actually exercise the fields this
        # bug emptied — otherwise the comparison below is vacuous.
        finite_dist = sum(
            1
            for c in r1.mesh.cells
            if c.distance_to_boundary_km is not None and c.distance_to_boundary_km != float("inf")
        )
        assert finite_dist > 0, "fixture produced no finite boundary distances"
        assert any(c.landform for c in r1.mesh.cells), (
            "fixture too small to carve interior landforms — enlarge it so the "
            "landform comparison stays non-vacuous"
        )
        assert any(c.convergence_rate_cm_yr for c in r1.mesh.cells)
        assert any(c.cumulative_convergence_km for c in r1.mesh.cells)

        # Run 2: every stage cache-hits — in-place side effects must replay.
        r2 = run_terrain_pipeline(cfg, tmp_path, cache=cache)

        dumps1 = [c.model_dump() for c in r1.mesh.cells]
        dumps2 = [c.model_dump() for c in r2.mesh.cells]
        assert len(dumps1) == len(dumps2) > 0
        mismatched = [
            (i, key)
            for i, (a, b) in enumerate(zip(dumps1, dumps2, strict=True))
            for key in a
            if a[key] != b[key]
        ]
        assert not mismatched, (
            f"cache-hit run diverged from fresh run in {len(mismatched)} cell "
            f"fields; first few: {mismatched[:5]}"
        )

        # And the exported mesh JSON (what the frontend reads) carries them.
        data = _read_exported_mesh(tmp_path)
        exported_landform = sum(1 for c in data["cells"] if c.get("landform"))
        exported_dist = sum(
            1 for c in data["cells"] if c.get("distance_to_boundary_km") is not None
        )
        exported_conv = sum(
            1 for c in data["cells"] if c.get("convergence_rate_cm_yr") not in (None, 0.0)
        )
        assert exported_landform > 0, "exported cvt_mesh.json lost landform values"
        assert exported_dist > 0, "exported cvt_mesh.json lost boundary distances"
        assert exported_conv > 0, "exported cvt_mesh.json lost convergence rates"

    def test_schema_version_invalidates_old_payloads(self, tmp_path):
        """A schema bump must change fingerprints, so old pickles cannot hit."""
        from dreamulator.map.terrain_cache import _STAGE_SCHEMA_VERSIONS, build_stage_fingerprint

        cfg = TerrainPipelineConfig(num_nodes=10, seed=1)
        for stage in ("tectonics", "boundaries", "terrain"):
            fp = build_stage_fingerprint(stage, cfg)
            assert _STAGE_SCHEMA_VERSIONS[stage] >= 2
            assert f"schema-v{_STAGE_SCHEMA_VERSIONS[stage]}" not in fp  # hashed, not literal
            # The version must participate: same config, different version →
            # different fingerprint.  Verify by hashing with a forced version.
            import dreamulator.map.terrain_cache as tcache

            original = tcache._STAGE_SCHEMA_VERSIONS.get(stage, 1)
            try:
                tcache._STAGE_SCHEMA_VERSIONS[stage] = original + 1
                bumped = build_stage_fingerprint(stage, cfg)
            finally:
                tcache._STAGE_SCHEMA_VERSIONS[stage] = original
            assert bumped != fp, f"{stage}: schema version not in fingerprint"
