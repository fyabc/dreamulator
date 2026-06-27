"""World directory management — CRUD operations on world instances."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import yaml

from dreamulator import __version__
from dreamulator.models.world import WorldConfig


def _data_dir() -> Path:
    """Return the project-level data/worlds directory."""
    # Walk up from this file to find the project root (has pyproject.toml)
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current / "data" / "worlds"
        current = current.parent
    raise RuntimeError("Could not find project root (no pyproject.toml found)")


def _templates_dir() -> Path:
    """Return the project-level data/templates directory."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current / "data" / "templates"
        current = current.parent
    raise RuntimeError("Could not find project root (no pyproject.toml found)")


class WorldManager:
    """Manages world directories — create, list, info, delete, validate."""

    def __init__(self, worlds_dir: Path | None = None) -> None:
        self.worlds_dir = worlds_dir or _data_dir()
        self.worlds_dir.mkdir(parents=True, exist_ok=True)

    def create_world(
        self,
        name: str,
        *,
        seed: int | None = None,
        template: str = "minimal",
    ) -> Path:
        """Create a new world directory from a template.

        Args:
            name: World name (used as directory name).
            seed: RNG seed. Random if not provided.
            template: Template name to use (e.g. 'minimal', 'earthlike').

        Returns:
            Path to the created world directory.

        Raises:
            FileExistsError: If a world with this name already exists.
            FileNotFoundError: If the template does not exist.
        """
        world_dir = self.worlds_dir / name
        if world_dir.exists():
            raise FileExistsError(f"World '{name}' already exists at {world_dir}")

        template_dir = _templates_dir() / template
        if not template_dir.exists():
            raise FileNotFoundError(f"Template '{template}' not found at {template_dir}")

        # Copy template
        shutil.copytree(template_dir, world_dir)

        # Generate seed if needed (must be plain int, not numpy int)
        if seed is None:
            import time

            seed = int(time.time_ns() % (2**31))

        # Update world.yaml with actual values
        now = datetime.now(UTC).isoformat()
        world_yaml = world_dir / "world.yaml"
        data: dict = {}
        if world_yaml.exists():
            with world_yaml.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

        data.setdefault("metadata", {})
        data["metadata"]["name"] = name
        data["metadata"]["dreamulator_version"] = __version__
        data["metadata"]["created"] = now
        data["metadata"]["modified"] = now
        data["seed"] = {"seed": seed}

        with world_yaml.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return world_dir

    def list_worlds(self) -> list[str]:
        """List all world names.

        Returns:
            Sorted list of world directory names.
        """
        if not self.worlds_dir.exists():
            return []
        return sorted(
            d.name for d in self.worlds_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
        )

    def world_dir(self, name: str) -> Path:
        """Get the path to a world directory.

        Raises:
            FileNotFoundError: If the world does not exist.
        """
        world_dir = self.worlds_dir / name
        if not world_dir.exists():
            raise FileNotFoundError(f"World '{name}' not found")
        return world_dir

    def load_world(self, name: str) -> WorldConfig:
        """Load a world's configuration.

        Args:
            name: World name.

        Returns:
            Validated WorldConfig instance.
        """
        from dreamulator.io.loader import load_world

        return load_world(self.world_dir(name))

    def delete_world(self, name: str) -> None:
        """Delete a world directory.

        Args:
            name: World name.

        Raises:
            FileNotFoundError: If the world does not exist.
        """
        world_dir = self.world_dir(name)
        shutil.rmtree(world_dir)

    def validate_world(self, name: str) -> list[str]:
        """Validate a world's files against expected structure.

        Args:
            name: World name.

        Returns:
            List of validation error messages. Empty list means valid.
        """
        errors: list[str] = []
        world_dir = self.world_dir(name)

        # Check required files
        required = ["world.yaml"]
        for f in required:
            if not (world_dir / f).exists():
                errors.append(f"Missing required file: {f}")

        # Try to load and validate world.yaml
        if (world_dir / "world.yaml").exists():
            try:
                self.load_world(name)
            except Exception as e:
                errors.append(f"world.yaml validation error: {e}")

        # Check layer input files
        layers_dir = world_dir / "layers"
        if layers_dir.exists():
            for layer_dir in sorted(layers_dir.iterdir()):
                if not layer_dir.is_dir():
                    continue
                input_dir = layer_dir / "input"
                if input_dir.exists():
                    for yaml_file in input_dir.glob("*.yaml"):
                        try:
                            with yaml_file.open("r", encoding="utf-8") as f:
                                yaml.safe_load(f)
                        except Exception as e:
                            errors.append(
                                f"layers/{layer_dir.name}/input/{yaml_file.name} parse error: {e}"
                            )

        return errors
