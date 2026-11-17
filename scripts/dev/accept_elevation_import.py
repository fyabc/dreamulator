"""Build small imported worlds and export reviewable elevation/climate acceptance evidence.

Run from the repository root with uv. Optional --earth-map reads an existing reference
raster without building the Earth root. Outputs and scratch worlds live under exports/.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from scipy.spatial import cKDTree

from dreamulator.api_routes import maps
from dreamulator.engine.astronomy import AstronomyEngine
from dreamulator.engine.climate import ClimateEngine
from dreamulator.engine.geological import GeologicalEngine
from dreamulator.engine.pipeline import run_pipeline
from dreamulator.map.elevation_codec import decode_elevation
from dreamulator.map.export import MESH_FILENAME, load_cvt_mesh
from dreamulator.map.importer import import_heightmap_metres
from dreamulator.map.models import ElevationMapping
from dreamulator.world_manager import WorldManager


def png8(values: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(values.astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


def build_case(manager, client, name, data, mapping, size, *, climate=False):
    world = manager.create_world(name, template="earthlike", seed=42)
    geo = world / "layers" / "geological" / "input"
    planets = yaml.safe_load((geo / "planets.yaml").read_text(encoding="utf-8"))
    planets["planets"][0]["lithosphere"].pop("num_plates", None)
    (geo / "planets.yaml").write_text(yaml.safe_dump(planets), encoding="utf-8")
    (geo / "terrain_config.yaml").write_text(
        yaml.safe_dump(
            {"num_nodes": 2048, "lloyd_iterations": 1, "export_width": 512, "export_height": 256}
        ),
        encoding="utf-8",
    )
    target = world / "maps" / "planet_gaia"
    target.mkdir(parents=True)
    (target / "map.yaml").write_text(
        yaml.safe_dump({"planet_id": "planet_gaia", "width": size[0], "height": size[1]}),
        encoding="utf-8",
    )
    response = client.post(
        f"/api/worlds/{name}/maps/planet_gaia/import-elevation",
        files={"file": ("source.png", data, "image/png")},
        data=mapping.model_dump(),
    )
    response.raise_for_status()
    engines = (
        [AstronomyEngine, GeologicalEngine, ClimateEngine]
        if climate
        else [AstronomyEngine, GeologicalEngine]
    )
    results = run_pipeline(engines, world, 42, start_layer=None if climate else "geological")
    if not all(r.success for r in results):
        raise RuntimeError([r.model_dump() for r in results])
    mesh = load_cvt_mesh(target / MESH_FILENAME)
    return response.json(), mesh, world


def coast_points(mask):
    edge = mask != np.roll(mask, 1, axis=1)
    edge[1:] |= mask[1:] != mask[:-1]
    rows, cols = np.nonzero(edge)
    lat = np.radians(90 - (rows + 0.5) * 180 / mask.shape[0])
    lon = np.radians(-180 + (cols + 0.5) * 360 / mask.shape[1])
    return np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])


def compare(reference, candidate, mesh):
    ref_land, new_land = reference > 0, candidate.land
    weights = np.cos(
        np.radians(90 - (np.arange(reference.shape[0]) + 0.5) * 180 / reference.shape[0])
    )[:, None]
    area = weights.sum() * reference.shape[1]
    a, b = coast_points(ref_land), coast_points(new_land)
    shifts = np.concatenate([cKDTree(a).query(b)[0], cKDTree(b).query(a)[0]])
    shifts = 2 * 6371 * np.arcsin(np.clip(shifts / 2, 0, 1))
    cells = mesh["cells"]
    cols = np.clip(
        ((np.array([c["lon"] for c in cells]) + 180) / 360 * reference.shape[1]).astype(int),
        0,
        reference.shape[1] - 1,
    )
    rows = np.clip(
        ((90 - np.array([c["lat"] for c in cells])) / 180 * reference.shape[0]).astype(int),
        0,
        reference.shape[0] - 1,
    )
    heights = reference[rows, cols]
    errors = np.array([c["elevation"] for c in cells]) - heights
    bands = []
    for low, high in [(-12000, 0), (0, 200), (200, 1000), (1000, 3000), (3000, 10000)]:
        selected = np.abs(errors[(heights >= low) & (heights < high)])
        bands.append(
            {
                "height_range_m": [low, high],
                "cells": selected.size,
                "absolute_error_p95_m": float(np.percentile(selected, 95))
                if selected.size
                else None,
            }
        )
    return {
        "reference_land_area_fraction": float((ref_land * weights).sum() / area),
        "imported_land_area_fraction": float((new_land * weights).sum() / area),
        "changed_land_sea_area_fraction": float(((ref_land != new_land) * weights).sum() / area),
        "shoreline_symmetric_nearest_p95_km": float(np.percentile(shifts, 95)),
        "shoreline_symmetric_nearest_max_km": float(shifts.max()),
        "mesh_absolute_error_max_m": float(np.abs(errors).max()),
        "mesh_error_by_height": bands,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--earth-map", type=Path, help="Existing reference maps/planet_earth directory; read only"
    )
    args = parser.parse_args()
    output = args.output_dir or Path("exports/elevation-import") / datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )
    output.mkdir(parents=True, exist_ok=True)
    manager = WorldManager(output / "worlds")
    app = FastAPI()
    app.include_router(maps.router)
    previous_manager = maps._manager
    report = {
        "scope": "Backend import and climate integration; frontend review is separate.",
        "reference": "Earth elevation raster, not independent climate validation.",
        "cases": {},
    }
    try:
        maps._manager = manager
        client = TestClient(app)
        grey = np.zeros((128, 256), dtype=np.uint8)
        grey[:, :128] = np.linspace(1, 255, 128).astype(np.uint8)
        data = png8(grey)
        (output / "sample.png").write_bytes(data)
        mapping = ElevationMapping(mode="threshold", max_m=6000, seafloor_m=-3000)
        body, mesh, world = build_case(
            manager, client, "sample", data, mapping, (256, 128), climate=True
        )
        assert all(c["water_class"] == ("land" if c["lon"] < 0 else "ocean") for c in mesh["cells"])
        assert all(
            math.isfinite(c["temperature_C"]) and math.isfinite(c["precipitation_mm"])
            for c in mesh["cells"]
        )
        report["sample"] = {
            "import": body,
            "world": str(world),
            "cells": mesh["num_cells"],
            "passed": True,
        }
        if args.earth_map:
            png = args.earth_map / "elevation.png"
            raw = png.read_bytes()
            before = hashlib.sha256(raw).hexdigest()
            metadata = yaml.safe_load((args.earth_map / "map.yaml").read_text(encoding="utf-8"))
            lo, hi = metadata["elevation_min_m"], metadata["elevation_max_m"]
            normalized = decode_elevation(raw)
            reference = lo + normalized * (hi - lo)
            height, width = reference.shape
            cases = [
                ("range16", raw, ElevationMapping(min_m=lo, max_m=hi)),
                ("range8", png8(np.rint(normalized * 255)), ElevationMapping(min_m=lo, max_m=hi)),
                (
                    "land8",
                    png8(np.rint(np.clip(reference / max(hi, 1), 0, 1) * 255)),
                    ElevationMapping(mode="threshold", max_m=hi, seafloor_m=-3800),
                ),
            ]
            for name, image, contract in cases:
                body, mesh, _ = build_case(manager, client, name, image, contract, (width, height))
                imported = import_heightmap_metres(image, contract)
                stats = compare(reference, imported, mesh)
                if name == "range16":
                    assert stats["mesh_absolute_error_max_m"] <= (hi - lo) / 65535 + 0.0001
                if name == "range8":
                    assert stats["mesh_absolute_error_max_m"] <= (hi - lo) / 510 + 0.0001
                report["cases"][name] = {"import": body, "comparison": stats}
            assert hashlib.sha256(png.read_bytes()).hexdigest() == before
            report["earth_source_sha256"] = before
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 3, figsize=(15, 4), constrained_layout=True)
        axes[0].imshow(grey, extent=(-180, 180, -90, 90), cmap="gray")
        axes[0].set_title("Authored heightmap (west: land)")
        for ax, field, label, cmap in [
            (axes[1], "temperature_C", "Annual temperature (deg C)", "RdYlBu_r"),
            (axes[2], "precipitation_mm", "Annual precipitation (mm)", "YlGnBu"),
        ]:
            cells = load_cvt_mesh(world / "maps" / "planet_gaia" / MESH_FILENAME)["cells"]
            dots = ax.scatter(
                [c["lon"] for c in cells],
                [c["lat"] for c in cells],
                c=[c[field] for c in cells],
                s=7,
                cmap=cmap,
            )
            ax.set_title(label)
            fig.colorbar(dots, ax=ax)
        for ax in axes:
            ax.set(
                xlabel="Longitude (deg)", ylabel="Latitude (deg)", xlim=(-180, 180), ylim=(-90, 90)
            )
        fig.savefig(output / "sample-climate.png", dpi=150)
        plt.close(fig)
        print(f"Acceptance passed. Review {output / 'report.json'}")
        print(f"Climate preview: {output / 'sample-climate.png'}")
    finally:
        maps._manager = previous_manager


if __name__ == "__main__":
    main()
