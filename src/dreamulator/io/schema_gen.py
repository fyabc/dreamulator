"""Generate JSON Schema files from Pydantic models."""

import json
from pathlib import Path

from pydantic import BaseModel

from dreamulator.models.civilization import Civilization, Settlement
from dreamulator.models.ecology import Ecosystem, Species
from dreamulator.models.planet import Planet
from dreamulator.models.simulation import ComputationManifest, SimulationRun
from dreamulator.models.stellar import StellarSystem
from dreamulator.models.world import WorldConfig

# Registry of models to generate schemas for
SCHEMA_MODELS: list[tuple[str, type[BaseModel]]] = [
    ("world", WorldConfig),
    ("stellar_system", StellarSystem),
    ("planet", Planet),
    ("species", Species),
    ("ecosystem", Ecosystem),
    ("civilization", Civilization),
    ("settlement", Settlement),
    ("computation_manifest", ComputationManifest),
    ("simulation_run", SimulationRun),
]


def generate_schemas(output_dir: Path) -> list[Path]:
    """Generate JSON Schema files for all registered models.

    Args:
        output_dir: Directory to write schema files to.

    Returns:
        List of generated schema file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    for name, model_class in SCHEMA_MODELS:
        schema = model_class.model_json_schema()
        path = output_dir / f"{name}.schema.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
            f.write("\n")
        generated.append(path)

    return generated
