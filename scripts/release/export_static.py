"""Export world data as static JSON for GitHub Pages deployment.

Reads all worlds from data/worlds/ and exports their data as JSON files
to frontend/public/data/ for static site hosting.

Build jobs are process-local execution state and are not exported. The static
client rejects startBuildJob and getBuildJob instead of requesting stale job files.
Engine step timings and counters are part of the same non-exported snapshots.
Local region packs, numeric elevations, and recorded TD conditions are not exported.
The browser extracts static regional heightmaps from the published global PNGs.
Published worlds also ship their scientific TD inputs, independently of local results.
Local refinement plans, job settings, and the compute device require the local
runtime and are not exported. The browser sets parameters and runs WebGPU independently.
Full world snapshots include private inputs and local build outputs. This exporter
publishes no snapshot archives, and the static client exposes no download URL.
The static heightmap creation workflow keeps new worlds and climate experiments in
the browser. Its private creation artifacts are not published by this exporter.

Usage:
    python scripts/release/export_static.py
    python scripts/release/export_static.py --output frontend/public/data
    python scripts/release/export_static.py --worlds earth nacrea
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import yaml

# Ensure dreamulator package is importable when running as a script
_SCRIPT_DIR = Path(__file__).resolve().parent


def _ensure_importable() -> None:
    """Add src/ and this script's dir to sys.path (for dreamulator / local_branches)."""
    root = _SCRIPT_DIR.parents[1]  # repo root (script lives in scripts/release/)
    src = root / "src"
    for p in (str(src), str(_SCRIPT_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_importable()

from local_branches import local_only_branches  # noqa: E402

from dreamulator import doc_render  # noqa: E402
from dreamulator.civmap.manager import CivMapManager  # noqa: E402
from dreamulator.climate_trial import (  # noqa: E402
    BROWSER_TRIAL_MAX_CELLS,
    TrialForcing,
    TrialUnavailableError,
    resolve_trial_source,
)
from dreamulator.io.loader import load_world  # noqa: E402
from dreamulator.map.koppen_product import (  # noqa: E402
    OBSERVED_KOPPEN_FILE,
    resolve_koppen_product,
)
from dreamulator.map.manager import MapManager  # noqa: E402
from dreamulator.map.models import map_metadata_result, sanitize_nonfinite  # noqa: E402
from dreamulator.map.pipeline_types import TerrainPipelineConfig  # noqa: E402
from dreamulator.models.planet import Planet  # noqa: E402
from dreamulator.resolver import LayerResolver  # noqa: E402
from dreamulator.world_manager import STARTER_TEMPLATES, _templates_dir  # noqa: E402
from dreamulator.world_parameters import (  # noqa: E402
    MAX_BUILD_CELLS,
    MIN_BUILD_CELLS,
    WorldParameters,
    read_world_parameters,
)


def find_project_root() -> Path:
    """Find the project root (contains pyproject.toml)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find project root (no pyproject.toml found)")


def load_yaml(path: Path) -> dict | list | None:
    """Load a YAML file, returning None if it doesn't exist."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_KM_PER_EARTH_RADIUS = 6371.0


def _normalize_body(body: dict, orbit_lookup: dict) -> dict:
    """Normalize an OrbitingBody to PlanetData-compatible format for frontend."""
    orbit = orbit_lookup.get(body.get("id", ""), {})
    normalized = {
        "id": body.get("id"),
        "name": body.get("name"),
        "planet_type": body.get("body_type", "natural_satellite"),
        "mass": body.get("mass_earth", 0),
        "radius": body.get("radius_km", 0) / _KM_PER_EARTH_RADIUS,
        "orbits": orbit.get("parent_id", ""),
    }
    for key in ("rotation_period_days", "axial_tilt_deg", "albedo"):
        if key in body and body[key] is not None:
            normalized[key] = body[key]
    if "surface" in body:
        normalized["surface"] = body["surface"]
    if "description" in body:
        normalized["description"] = body["description"]
    return normalized


def _export_dir_documents(directory: Path, render_context: dict | None) -> list[dict] | None:
    """Export .md files from a directory, rendering template bodies.

    Returns a list of document metadata dicts with frontmatter, filename,
    and full (rendered) content. Returns None if no documents found.
    The ``rendered`` flag is False when the body has placeholders but no
    render context was available (see ``dreamulator.doc_render``).
    """
    if not directory.exists():
        return None
    md_files = sorted(directory.glob("*.md"))
    if not md_files:
        return None

    documents = []
    for fp in md_files:
        with fp.open("r", encoding="utf-8") as f:
            content = f.read()
        fm, body = doc_render.parse_frontmatter(content)
        body, rendered = doc_render.render_body(body, render_context)
        documents.append(
            {
                "filename": fp.name,
                "title": fm.get("title", fp.stem),
                "type": fm.get("type", ""),
                "period": fm.get("period", ""),
                "tags": fm.get("tags", []),
                "status": str(fm.get("status", "") or ""),
                "date": str(fm.get("date", "") or ""),
                "frontmatter": fm,
                "content": body,
                "rendered": rendered,
            }
        )
    return documents


def _local_only_branches(root: Path, world_dir: Path) -> set[str]:
    """Gitignored local-only branches (see ``local_branches``), with a log line."""
    ignored = local_only_branches(root, world_dir)
    if ignored:
        print(f"    (skipping local-only branches: {', '.join(sorted(ignored))})")
    return ignored


def _export_layer_documents(
    resolver: LayerResolver, layer: str, render_context: dict | None
) -> list[dict] | None:
    """Export .md files from any layer's input directory.

    Returns a list of document metadata dicts with frontmatter, filename,
    and full content. Returns None if no documents found.
    """
    md_files = resolver.list_input_files(layer, "*.md")
    if not md_files:
        return None
    return _export_dir_documents(md_files[0].parent, render_context)


def _export_layer_data(world_dir: Path, branch: str | None = None) -> dict:
    """Export layer data for a world or branch using the resolver.

    Handles _inherit: true merge for input files.
    The complete resolved system catalog is exported, including its optional reference epoch.
    """
    resolver = LayerResolver(world_dir, branch)
    result: dict = {}

    try:
        config = load_world(world_dir)
        settings = read_world_parameters(
            resolver,
            config.seed.seed,
            reference=branch is None and (config.reference_anchor or world_dir.name == "earth"),
            published=True,
        )
    except (FileNotFoundError, ValueError, yaml.YAMLError):
        settings = WorldParameters(reuses_mesh=False, read_only="published")
    result["world-parameters"] = settings.model_dump()

    # Render context for markdown documents (entity-addressed fact context:
    # system_catalog.yaml + per-layer summaries); loaded once per world/branch
    # and passed to each document exporter.
    render_context = doc_render.load_render_context(world_dir, branch)

    # 1. Stellar system (input + derived merged)
    stellar_input = resolver.load_layer_yaml("astronomy", "stellar.yaml")
    if stellar_input and isinstance(stellar_input, dict):
        stellar = dict(stellar_input)

        # Merge derived star data if available
        derived_dir = resolver.get_derived_dir("astronomy")
        if derived_dir is not None:
            stellar_derived = load_yaml(derived_dir / "stellar_derived.yaml")
            if stellar_derived and "stars" in stellar_derived:
                derived_by_id = {s["id"]: s for s in stellar_derived["stars"] if "id" in s}
                if "stars" in stellar:
                    for star in stellar["stars"]:
                        star_id = star.get("id")
                        if star_id and star_id in derived_by_id:
                            star["derived"] = derived_by_id[star_id]

        result["stellar"] = stellar

        # Normalize bodies (moons, asteroids) to planet-compatible format
        bodies = stellar.get("bodies", [])
        if bodies:
            from dreamulator.models.stellar import overlay_planet_physicals

            planets_data = resolver.load_layer_yaml("geological", "planets.yaml")
            if isinstance(planets_data, dict) and isinstance(planets_data.get("planets"), list):
                overlay_planet_physicals(bodies, planets_data["planets"])
            orbit_lookup = {o["body_id"]: o for o in stellar.get("orbits", []) if "body_id" in o}
            stellar["bodies"] = [_normalize_body(b, orbit_lookup) for b in bodies]

    # 2. Habitable zones (derived only — no inheritance)
    derived_dir = resolver.get_derived_dir("astronomy")
    if derived_dir is not None:
        hz_data = load_yaml(derived_dir / "habitable_zones.yaml")
        if hz_data:
            result["habitable_zones"] = hz_data

        # System catalog (merged stellar.yaml + planets.yaml, derived)
        catalog = load_yaml(derived_dir / "system_catalog.yaml")
        if catalog:
            result["system_catalog"] = catalog
            result["sky_background"] = load_yaml(derived_dir / "sky_background.yaml")
            civilization = resolver.get_derived_dir("civilization")
            result["sky_culture"] = (
                load_yaml(civilization / "sky_culture.yaml") if civilization is not None else None
            )

    # 3. Planets
    planets_data = resolver.load_layer_yaml("geological", "planets.yaml")
    if planets_data and isinstance(planets_data, dict) and "planets" in planets_data:
        result["planets"] = planets_data["planets"]

    # 4. Climate
    climate_data = resolver.load_layer_yaml("climate", "climate.yaml")
    if climate_data:
        result["climate"] = climate_data

    # 5. Ecology
    ecology_data = resolver.load_layer_yaml("ecology", "ecology.yaml")
    if ecology_data:
        result["ecology"] = ecology_data

    # 6. CivMap territory data (countries, snapshots, assignments)
    civ_territory = resolver.load_layer_yaml("civilization", "civ_territory.yaml")
    if civ_territory:
        # The frontend decides from civ_territory.json itself; a separate flag file had no
        # reader and was written once per world.
        result["civ_territory"] = civ_territory

    # 8. Layer documents (.md files) — export for all layers
    for layer in ("astronomy", "geological", "climate", "ecology", "civilization"):
        layer_docs = _export_layer_documents(resolver, layer, render_context)
        if layer_docs:
            result[f"{layer}_documents"] = layer_docs

    # 9. Design notes (non-layer, from design-notes/ directory)
    dn_dir = world_dir / "design-notes"
    if branch:
        branch_dn = world_dir / "branches" / branch / "design-notes"
        if branch_dn.exists():
            dn_dir = branch_dn
    if dn_dir.exists():
        dn_docs = _export_dir_documents(dn_dir, render_context)
        if dn_docs:
            result["design-notes_documents"] = dn_docs

    return result


def _export_browser_trial(
    world_dir: Path,
    planet: str,
    branch: str | None,
    output: Path,
    displayed_mesh: Path | None,
    displayed_cells: int | None,
) -> None:
    from dreamulator.map.export import MESH_FILENAME, load_cvt_mesh

    manifest: dict[str, object] = {"version": 1}
    try:
        source = resolve_trial_source(world_dir, planet, branch)
        same_mesh = source.mesh_path == displayed_mesh and displayed_cells is not None
        cells = displayed_cells if same_mesh else load_cvt_mesh(source.mesh_path)["num_cells"]
        if cells > BROWSER_TRIAL_MAX_CELLS:
            raise TrialUnavailableError("browser_grid_limit")
        mesh_name = MESH_FILENAME if same_mesh else "climate_trial_mesh.bin"
        config = asdict(source.config)
        forcing = TrialForcing.from_config(source.config).model_dump(mode="json")
        ready = json.dumps(
            {**manifest, "cells": cells, "mesh": mesh_name, "forcing": forcing, "config": config},
            allow_nan=False,
            separators=(",", ":"),
        )
        if not same_mesh:
            shutil.copyfile(source.mesh_path, output / mesh_name)
    except TrialUnavailableError as error:
        ready = json.dumps({**manifest, "reason": str(error)})
    except (OSError, TypeError, ValueError, KeyError) as error:
        scope = f"{world_dir.name}/{branch}/{planet}"
        print(f"\n  WARNING: Browser trial unavailable for {scope}: {error}")
        ready = json.dumps({**manifest, "reason": "build_inputs"})
    (output / "climate_trial.json").write_text(ready, encoding="utf-8")


def _export_browser_solver(root: Path, output: Path) -> None:
    source = root / "src"
    with ZipFile(output / "climate_solver.zip", "w", ZIP_DEFLATED) as archive:
        package = source / "dreamulator"
        files = [*package.rglob("*.py"), *package.rglob("*.json")]
        for path in sorted(files):
            archive.write(path, path.relative_to(source))


def _same_bytes(path_a: Path, path_b: Path) -> bool:
    """True when both files exist and hold identical bytes."""
    try:
        if path_a.stat().st_size != path_b.stat().st_size:
            return False
        return path_a.read_bytes() == path_b.read_bytes()
    except OSError:
        return False


def _write_map_copy(src: Path, dest: Path, root_dest: Path | None) -> bool:
    """Copy a map file, omitting it when it duplicates the root world's copy.

    Branch map directories only carry files that differ from the root world:
    an identical copy is pure weight against the 1 GB Pages limit.  The
    omitted paths are listed in the branch's ``maps/shared.json`` so the
    static client reads the root file directly instead of provoking a 404.
    ``root_dest`` is None for root exports and for callers with no root
    output to compare against.  Returns whether the file was omitted.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if root_dest is not None and _same_bytes(src, root_dest):
        dest.unlink(missing_ok=True)
        return True
    dest.write_bytes(src.read_bytes())
    return False


def _write_map_bytes(data: bytes, dest: Path, root_dest: Path | None) -> bool:
    """Write generated map bytes unless they equal the root world's copy.

    Returns whether the file was omitted (see :func:`_write_map_copy`).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if root_dest is not None and root_dest.is_file() and root_dest.read_bytes() == data:
        dest.unlink(missing_ok=True)
        return True
    dest.write_bytes(data)
    return False


def _drop_duplicate(dest: Path, root_dest: Path | None) -> bool:
    """Remove *dest* when it equals the root world's file; return whether it did."""
    if root_dest is not None and _same_bytes(dest, root_dest):
        dest.unlink()
        return True
    return False


def _export_map_data(
    world_dir: Path,
    maps_out_dir: Path,
    branch: str | None = None,
    root_maps_out: Path | None = None,
) -> list[str]:
    """Export map data for a world or branch.

    Since v0.10.0, map data lives in a top-level ``maps/{planet_id}/``
    directory: ``{world}/maps/`` for root worlds and
    ``{world}/branches/{branch}/maps/`` for branches. Copies each planet's
    data (elevation PNG, map.yaml → meta.json, cvt_mesh, plates, features)
    to the static output directory.

    MapManager supplies the same complete, branch-first planet list as the API.
    Each branch export includes inherited planets and fills missing overlay
    files from root; files whose bytes equal the root export are omitted so
    the branch directory only carries real differences.  The static client
    resolves a missing branch file by falling back to the root path, which
    serves the identical bytes.  ``cvt_mesh.msgpack.gz``, the observed Köppen
    raster and the browser-trial files always stay in the branch directory:
    the browser climate trial loads its mesh straight from that directory.

    Args:
        world_dir: Path to the world root directory.
        maps_out_dir: Output directory for map data.
        branch: Branch name (None for root world).
        root_maps_out: Root world's export directory, used to detect
            duplicates.  None disables deduplication.

    Returns:
        List of planet IDs that have map data.
    """
    from dreamulator.map.td_world_source import (
        native_terrain_key,
        terrain_source,
        write_native_terrain,
    )

    manager = MapManager(world_dir, branch)
    root_manager = MapManager(world_dir)
    planets_with_maps = manager.list_planets_with_maps()
    # Branch files omitted because they equal the root copy, as
    # ``<planet>/<filename>``.  Written to maps/shared.json so the static
    # client fetches the root file directly (no 404 round trip).
    shared_files: list[str] = []

    for planet_id in planets_with_maps:
        planet_dir = manager._map_input_dir(planet_id)
        if planet_dir is None:
            continue

        planet_out = maps_out_dir / planet_id
        planet_out.mkdir(parents=True, exist_ok=True)
        root_planet_out = (
            root_maps_out / planet_id if branch is not None and root_maps_out is not None else None
        )

        root_planet_dir = root_manager._map_input_dir(planet_id) if branch is not None else None
        sources = [planet_dir]
        if root_planet_dir is not None and root_planet_dir != planet_dir:
            sources.append(root_planet_dir)
        koppen, observed_raster = resolve_koppen_product(sources)
        raster_out = planet_out / OBSERVED_KOPPEN_FILE
        if observed_raster is None:
            raster_out.unlink(missing_ok=True)
        else:
            shutil.copyfile(observed_raster, raster_out)

        def _inherit(
            name: str,
            _dir: Path = planet_dir,
            _root: Path | None = root_planet_dir,
        ) -> Path | None:
            """Branch overlay file, else the root world's (per-file branch
            inheritance — a climate-fork branch's terrain products live only
            in root)."""
            p = _dir / name
            if p.exists():
                return p
            if _root is not None:
                p = _root / name
                if p.exists():
                    return p
            return None

        # Copy elevation PNG (binary), with root inheritance for overlays.
        elevation_src = _inherit("elevation.png")
        if elevation_src is not None and _write_map_copy(
            elevation_src,
            planet_out / "elevation.png",
            root_planet_out / "elevation.png" if root_planet_out is not None else None,
        ):
            shared_files.append(f"{planet_id}/elevation.png")

        # Copy monthly climate MessagePack (Phase 4 monthly display), if present.
        monthly_msgpack = _inherit("climate_monthly.msgpack")
        if monthly_msgpack is not None and _write_map_copy(
            monthly_msgpack,
            planet_out / "climate_monthly.msgpack",
            root_planet_out / "climate_monthly.msgpack" if root_planet_out is not None else None,
        ):
            shared_files.append(f"{planet_id}/climate_monthly.msgpack")

        try:
            td_packet, retained = terrain_source(manager, planet_id)
            if retained is not None:
                world_out = maps_out_dir.parents[2] if branch else maps_out_dir.parent
                native_name = f"{native_terrain_key(retained[0])}.bin.gz"
                native_file = world_out / "td-elevation" / native_name
                if not native_file.is_file():
                    native_file.parent.mkdir(parents=True, exist_ok=True)
                    temp = native_file.with_suffix(".tmp")
                    try:
                        with temp.open("wb") as stream:
                            write_native_terrain(stream, retained)
                        temp.replace(native_file)
                    finally:
                        temp.unlink(missing_ok=True)
        except (OSError, ValueError) as error:
            scope = f"{world_dir.name}/{branch}/{planet_id}"
            print(f"\n  WARNING: TD inputs unavailable for {scope}: {error}")
            (planet_out / "td-source.msgpack").unlink(missing_ok=True)
        else:
            if _write_map_bytes(
                td_packet,
                planet_out / "td-source.msgpack",
                root_planet_out / "td-source.msgpack" if root_planet_out is not None else None,
            ):
                shared_files.append(f"{planet_id}/td-source.msgpack")

        # Copy yearly climate descriptors (UCC-01), if present.
        yearly_msgpack = _inherit("climate_yearly.msgpack")
        if yearly_msgpack is not None and _write_map_copy(
            yearly_msgpack,
            planet_out / "climate_yearly.msgpack",
            root_planet_out / "climate_yearly.msgpack" if root_planet_out is not None else None,
        ):
            shared_files.append(f"{planet_id}/climate_yearly.msgpack")

        # Export map metadata (map.yaml → meta.json) + result-contract metadata
        # (format_version + time convention, CONTRACT-01).
        map_yaml = _inherit("map.yaml")
        if map_yaml is not None:
            meta = load_yaml(map_yaml)
            if meta:
                meta = map_metadata_result(meta)
                meta["koppen"] = koppen
                if _write_map_bytes(
                    json.dumps(meta, ensure_ascii=False, separators=(",", ":"), default=str).encode(
                        "utf-8"
                    ),
                    planet_out / "meta.json",
                    root_planet_out / "meta.json" if root_planet_out is not None else None,
                ):
                    shared_files.append(f"{planet_id}/meta.json")

        # Export JSON map files (voronoi, plates, features).
        # Each is read-validated-rewritten to catch LFS pointers or corrupt
        # files early instead of crashing the whole export.
        #
        # The CVT mesh is different: it ships as the canonical
        # cvt_mesh.msgpack.gz (the frontend fetches the blob, gunzips and
        # decodes in a worker — no main-thread JSON.parse of a 300 MB text).
        # Legacy gzip-JSON meshes convert once here, so static exports and
        # the dev API converge on one wire format.
        from dreamulator.map.export import (
            FIELDS_FILENAME,
            GEOMETRY_FILENAME,
            MESH_FILENAME,
            find_mesh_file,
            load_cvt_mesh,
            save_cvt_mesh,
        )

        mesh_src = find_mesh_file(planet_dir)
        if mesh_src is None and root_planet_dir is not None and root_planet_dir.is_dir():
            # Branch overlay without its own mesh inherits root terrain.
            mesh_src = find_mesh_file(root_planet_dir)
        displayed_cells = None
        if mesh_src is not None:
            try:
                mesh = sanitize_nonfinite(load_cvt_mesh(mesh_src))
                save_cvt_mesh(planet_out / MESH_FILENAME, mesh)
                displayed_cells = mesh["num_cells"]
                del mesh
                if root_planet_out is not None:
                    # The combined mesh stays (the browser trial reads it from
                    # this directory); the split pair is a transport twin and
                    # can fall back to root when identical.
                    for split_name in (GEOMETRY_FILENAME, FIELDS_FILENAME):
                        if _drop_duplicate(planet_out / split_name, root_planet_out / split_name):
                            shared_files.append(f"{planet_id}/{split_name}")
            except Exception:
                print(
                    f"\n  WARNING: {mesh_src} is not a loadable mesh "
                    f"(possible LFS pointer) — skipping",
                )
        _export_browser_trial(world_dir, planet_id, branch, planet_out, mesh_src, displayed_cells)

        for filename in ("voronoi.json", "plates.json"):
            src_path = _inherit(filename)
            if src_path is None:
                continue
            try:
                data = sanitize_nonfinite(json.loads(src_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError):
                print(
                    f"\n  WARNING: {src_path} is not valid JSON (possible LFS pointer) — skipping",
                )
                continue
            if _write_map_bytes(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                planet_out / filename,
                root_planet_out / filename if root_planet_out is not None else None,
            ):
                shared_files.append(f"{planet_id}/{filename}")

        # Write placeholders for optional files the frontend may request
        # (avoids 404 console noise — same philosophy as _write_branch_defaults).
        # Root only: on a branch a placeholder would answer 200-empty and
        # shadow the root world's real file — the frontend's branch→root
        # fallback only fires on 404.
        for placeholder_name, placeholder in (("plates.json", {"plates": []}),):
            if branch is not None:
                break
            placeholder_path = planet_out / placeholder_name
            if not placeholder_path.exists():
                with placeholder_path.open("w", encoding="utf-8") as f:
                    json.dump(placeholder, f)

    # Write maps index (always, even when empty — the frontend's branch→root
    # fallback requests this path and a missing file is pure 404 noise)
    maps_out_dir.mkdir(parents=True, exist_ok=True)
    with maps_out_dir.joinpath("maps.json").open("w", encoding="utf-8") as f:
        json.dump(planets_with_maps, f, ensure_ascii=False)

    # Only branches deduplicate; root has nothing to point at.
    if branch is not None:
        with maps_out_dir.joinpath("shared.json").open("w", encoding="utf-8") as f:
            json.dump(sorted(shared_files), f, ensure_ascii=False)

    return planets_with_maps


def _write_branch_defaults(branch_out_dir: Path, branch_data: dict) -> None:
    """Write empty placeholder JSON files for data a branch doesn't have.

    Prevents 404 console noise when the frontend queries for optional data
    (civ_territory, civ_documents, maps) on branches that don't have it.
    """
    defaults = {
        "civ_territory": {
            "countries": [],
            "snapshots": [],
            "active_snapshot": None,
            "assignments": {},
        },
        "astronomy_documents": [],
        "geological_documents": [],
        "climate_documents": [],
        "ecology_documents": [],
        "civilization_documents": [],
        "design-notes_documents": [],
    }
    for key, default_value in defaults.items():
        if key not in branch_data:
            out_file = branch_out_dir / f"{key}.json"
            if not out_file.exists():
                with out_file.open("w", encoding="utf-8") as f:
                    json.dump(default_value, f, ensure_ascii=False)

    # maps/maps.json (inside maps/ subdirectory)
    maps_json = branch_out_dir / "maps" / "maps.json"
    if not maps_json.exists():
        maps_json.parent.mkdir(parents=True, exist_ok=True)
        with maps_json.open("w", encoding="utf-8") as f:
            json.dump([], f)


def _export_civmap_reference(
    world_dir: Path,
    world_out_dir: Path,
) -> None:
    """Export shared reference boundaries from the same location as the live API."""
    manager = CivMapManager(world_dir)
    ref_dir = manager.reference_dir()
    levels = manager.list_available_levels()
    if ref_dir is None or not levels:
        return

    civmap_out = world_out_dir / "civmap"
    civmap_out.mkdir(parents=True, exist_ok=True)

    for level in levels:
        shutil.copyfile(ref_dir / f"{level}.geojson", civmap_out / f"{level}.geojson")

    # Copy metadata
    meta_src = ref_dir / "metadata.json"
    meta: dict = {}
    if meta_src.exists():
        with meta_src.open("r", encoding="utf-8") as f:
            meta = json.load(f)
    level_metadata = meta.get("levels", {})
    meta["levels"] = {level: level_metadata.get(level, {}) for level in levels}
    with civmap_out.joinpath("metadata.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))

    # Generate and export country→province mapping from ADM1
    if "adm1" in levels:
        mapping = manager.get_country_province_mapping()
        with civmap_out.joinpath("mapping.json").open("w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False)


def export_world(world_dir: Path, skip_branches: set[str] | None = None) -> dict:
    """Export all data for a single world (root, no branch).

    Saved local climate trials are private world data. The public static export
    excludes them; the full world snapshot preserves them.

    Returns a dict with keys:
      - world: world.yaml contents
      - branches: list of branch metadata (excluding ``skip_branches``)
      - stellar, habitable_zones, planets, climate, ecology, civilizations (from _export_layer_data)
    """
    result: dict = {}
    skip = skip_branches or set()

    # 1. World config (world.yaml) — keep the same layer summary fields as the live API.
    world_data = load_yaml(world_dir / "world.yaml")
    if world_data is None:
        print(f"  WARNING: {world_dir.name}/world.yaml not found, skipping")
        return result
    layers = world_data.get("layers")
    if isinstance(layers, dict) and layers:
        from dreamulator.world_layer_status import enrich_layer_summaries

        seed = (world_data.get("seed") or {}).get("seed")
        world_data["layers"] = enrich_layer_summaries(
            world_dir, layers, seed=seed if isinstance(seed, int) else None
        )
    result["world"] = world_data

    # 2. Branches metadata
    branches: list[dict] = []
    branches_dir = world_dir / "branches"
    if branches_dir.exists():
        for branch_dir in sorted(branches_dir.iterdir()):
            if not branch_dir.is_dir() or branch_dir.name in skip:
                continue
            branch_yaml = branch_dir / "branch.yaml"
            if branch_yaml.exists():
                branch_data = load_yaml(branch_yaml)
                if branch_data:
                    branches.append(branch_data)
    result["branches"] = branches

    # 3. Layer data (root world, no branch)
    result.update(_export_layer_data(world_dir, branch=None))

    return result


def _export_starter_templates(output_dir: Path) -> None:
    templates = {}
    for name in STARTER_TEMPLATES:
        source = _templates_dir() / name
        root = yaml.safe_load((source / "world.yaml").read_text(encoding="utf-8"))
        inputs = {
            path.relative_to(source).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(source.glob("layers/*/input/*.yaml"))
        }
        templates[name] = {"root": root, "inputs": inputs}
    (output_dir / "starter-templates.json").write_text(
        json.dumps(templates, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "world-grid-defaults.json").write_text(
        json.dumps(
            {
                "num_cells": TerrainPipelineConfig().num_nodes,
                "min_cells": MIN_BUILD_CELLS,
                "max_cells": MAX_BUILD_CELLS,
                "planet": {
                    key: Planet.model_fields[key].default
                    for key in ("rotation_period_days", "albedo")
                },
            }
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export static world data and browser climate inputs, but not local results."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: frontend/public/data)",
    )
    parser.add_argument(
        "--worlds",
        nargs="*",
        default=None,
        help="Specific worlds to export (default: all)",
    )
    args = parser.parse_args()

    import os

    root = find_project_root()
    env_dir = os.environ.get("DREAMULATOR_DATA_DIR")
    worlds_dir = Path(env_dir).resolve() if env_dir else root / "data" / "worlds"
    output_dir = args.output or (root / "frontend" / "public" / "data")

    if not worlds_dir.exists():
        print(f"ERROR: worlds directory not found at {worlds_dir}", file=sys.stderr)
        sys.exit(1)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    _export_starter_templates(output_dir)
    _export_browser_solver(root, output_dir)

    # Discover worlds
    all_worlds = sorted(
        d.name for d in worlds_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
    )

    if args.worlds:
        # Filter to requested worlds
        selected = set(args.worlds)
        unknown = selected - set(all_worlds)
        if unknown:
            print(f"WARNING: unknown worlds: {unknown}", file=sys.stderr)
        all_worlds = [w for w in all_worlds if w in selected]

    if not all_worlds:
        print("No worlds to export.")
        sys.exit(0)

    print(f"Exporting {len(all_worlds)} world(s) to {output_dir}/")

    # Export each world
    for world_name in all_worlds:
        world_dir = worlds_dir / world_name
        print(f"  {world_name}...", end=" ", flush=True)

        local_only = _local_only_branches(root, world_dir)
        data = export_world(world_dir, skip_branches=local_only)
        if not data:
            print("SKIPPED (no world.yaml)")
            continue

        # Write each data type as a separate JSON file
        world_out_dir = output_dir / "worlds" / world_name
        world_out_dir.mkdir(parents=True, exist_ok=True)

        for key, value in data.items():
            out_file = world_out_dir / f"{key}.json"
            with out_file.open("w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False, separators=(",", ":"), default=str)

        # Publish actual grid sizes in map metadata. The live build-grid preview
        # is not exported because a static site cannot start a build.
        maps_out_dir = world_out_dir / "maps"
        map_planets = _export_map_data(world_dir, maps_out_dir, branch=None)

        # Export CivMap reference data (GeoJSON + mapping)
        _export_civmap_reference(world_dir, world_out_dir)

        # Export per-branch data (with _inherit: true merge)
        branch_count = 0
        branches_dir = world_dir / "branches"
        if branches_dir.exists():
            for branch_dir in sorted(branches_dir.iterdir()):
                if not (branch_dir / "branch.yaml").is_file():
                    continue
                branch_name = branch_dir.name
                if branch_name in local_only:
                    continue
                branch_data = _export_layer_data(world_dir, branch=branch_name)
                branch_out_dir = world_out_dir / "branches" / branch_name
                # Always create branch dir with empty placeholders
                # to avoid 404 console noise in static mode
                branch_out_dir.mkdir(parents=True, exist_ok=True)
                for key, value in branch_data.items():
                    out_file = branch_out_dir / f"{key}.json"
                    with out_file.open("w", encoding="utf-8") as f:
                        json.dump(value, f, ensure_ascii=False, separators=(",", ":"), default=str)
                # Write empty defaults for missing data
                _write_branch_defaults(branch_out_dir, branch_data)
                # Export branch-specific map data
                branch_maps_out = branch_out_dir / "maps"
                branch_map_planets = _export_map_data(
                    world_dir, branch_maps_out, branch=branch_name, root_maps_out=maps_out_dir
                )
                if branch_data or branch_map_planets:
                    branch_count += 1

        print(
            f"OK ({len(data)} files, {len(map_planets)} map(s), {branch_count} branch(es))",
            flush=True,
        )

    # Write worlds index
    index_file = output_dir / "worlds.json"
    with index_file.open("w", encoding="utf-8") as f:
        json.dump(all_worlds, f, ensure_ascii=False)

    print(f"\nDone! Worlds index: {index_file}")
    print(f"Total: {len(all_worlds)} world(s) exported.")


if __name__ == "__main__":
    main()
