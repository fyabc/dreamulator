"""The small subset of world snapshots accepted by the browser creation workflow."""

import hashlib
import json
import re
from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from dreamulator.io.loader import load_world, load_yaml_model
from dreamulator.map.elevation_input import load_elevation_sources
from dreamulator.map.models import MapMetadata
from dreamulator.models.planet import Planet
from dreamulator.models.stellar import StellarSystem

MAX_CREATION_BYTES = 38 * 1024**2
PLANET = "planet_terra"
CREATION = "browser-creation.json"
GEO_INPUT = "layers/geological/input"
EXPERIMENT = "layers/climate/derived/browser-temperature"
ARTIFACTS = ("manifest.json", "heightmap.png", "temperature.json")


def browser_creation_files(world: Path) -> dict[str, Path]:
    manifest = world / CREATION
    if not manifest.is_file() or manifest.stat().st_size > 8192:
        return {}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        return {}
    digest = data.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        return {}
    files = {
        ARTIFACTS[0]: manifest,
        ARTIFACTS[1]: world / GEO_INPUT / "elevation_sources" / f"{digest}.bin",
    }
    if data.get("temperature") is True:
        files[ARTIFACTS[2]] = world / EXPERIMENT / "temperature.json"
    return {
        name: path
        for name, path in files.items()
        if path.is_file() and path.resolve().is_relative_to(world.resolve())
    }


def validate_browser_creation(staged: Path, world_id: str) -> None:
    if world_id.casefold() == "earth" or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", world_id):
        raise ValueError("Invalid new world ID")
    artifacts = browser_creation_files(staged)
    if not set(ARTIFACTS[:2]).issubset(artifacts):
        raise ValueError("Missing world creation manifest or original image")
    original = artifacts[ARTIFACTS[1]]
    original_path = original.relative_to(staged).as_posix()
    has_temperature = ARTIFACTS[2] in artifacts
    derived_path = f"maps/{PLANET}/elevation.png"
    try:
        manifest = json.loads(artifacts[ARTIFACTS[0]].read_text(encoding="utf-8"))
        sources = load_elevation_sources(staged / GEO_INPUT / "elevation_imports.yaml")
    except (ValidationError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Invalid new-world inputs") from error
    source = sources.get(PLANET)
    # A threshold mapping is a piecewise GREY→metres contract that the linear map scale
    # cannot decode, so such snapshots carry a derived metres raster at the map path.
    threshold = (
        source is not None
        and source.provenance.mapping is not None
        and source.provenance.mapping.mode == "threshold"
    )
    expected = {
        "world.yaml",
        CREATION,
        "layers/astronomy/input/stellar.yaml",
        f"{GEO_INPUT}/planets.yaml",
        f"{GEO_INPUT}/terrain_config.yaml",
        f"{GEO_INPUT}/elevation_imports.yaml",
        f"maps/{PLANET}/map.yaml",
        original_path,
    }
    if threshold:
        expected.add(derived_path)
    if has_temperature:
        expected.update({f"{EXPERIMENT}/metadata.json", f"{EXPERIMENT}/temperature.json"})
    actual = {path.relative_to(staged).as_posix() for path in staged.rglob("*") if path.is_file()}
    if actual != expected:
        raise ValueError("Unexpected content in new-world snapshot")
    for path in expected - {f"{EXPERIMENT}/temperature.json", original_path, derived_path}:
        if (staged / path).stat().st_size > 8192:
            raise ValueError("World creation metadata is too large")
    if original.stat().st_size > 32 * 1024**2:
        raise ValueError("Original heightmap is too large")
    try:
        if manifest.get("id") != world_id or manifest.get("temperature") is not has_temperature:
            raise ValueError("Incorrect world creation manifest")
        config = load_world(staged)
        if (
            config.reference_anchor
            or config.metadata.name != world_id
            or config.planet_ids != [PLANET]
        ):
            raise ValueError("Invalid world configuration")
        if set(sources) != {PLANET} or source is None or source.sha256 != manifest["sha256"]:
            raise ValueError("Incorrect elevation source declaration")
        with original.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != source.sha256:
                raise ValueError("Original heightmap checksum mismatch")
        with Image.open(original, formats=["PNG"]) as image:
            if (
                image.width != 2 * image.height
                or image.width > 8192
                or image.mode not in {"L", "I;16", "I"}
                or image.info.get("interlace")
                or list(image.size) != source.provenance.output_resolution
                or list(image.size) != source.provenance.source_resolution
            ):
                raise ValueError("Expected a 2:1 8- or 16-bit grayscale PNG")
            image.verify()
        if threshold:
            with Image.open(staged / derived_path, formats=["PNG"]) as raster:
                if (
                    raster.mode not in {"I;16", "I"}
                    or raster.info.get("interlace")
                    or list(raster.size) != source.provenance.output_resolution
                ):
                    raise ValueError("Expected a 16-bit grayscale elevation raster")
                raster.verify()
        load_yaml_model(staged / "layers/astronomy/input/stellar.yaml", StellarSystem)
        catalog = json.loads((staged / GEO_INPUT / "planets.yaml").read_text(encoding="utf-8"))
        planets = catalog.get("planets") if isinstance(catalog, dict) else None
        if not isinstance(planets, list) or len(planets) != 1:
            raise ValueError("Expected one planet in new-world inputs")
        if Planet.model_validate(planets[0]).id != PLANET:
            raise ValueError("Invalid planet ID")
        load_yaml_model(staged / "maps" / PLANET / "map.yaml", MapMetadata)
    except (ValidationError, Image.DecompressionBombError, SyntaxError) as error:
        raise ValueError("Invalid new-world inputs") from error
