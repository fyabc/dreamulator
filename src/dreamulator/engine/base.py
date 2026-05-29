"""Base engine class and engine result model."""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

from dreamulator.models.layers import Layer
from dreamulator.utils.rng import create_rng


class EngineResult(BaseModel):
    """Standard output from any engine run."""

    engine_name: str
    success: bool
    output_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class BaseEngine(ABC):
    """Abstract base class for all simulation engines.

    Every engine must declare:
    - name: unique identifier
    - version: semver version string
    - layer: which layer this engine belongs to
    - requires: list of engine names that must run before this one
    - input_files: paths relative to layer input dir that this engine reads
    - output_files: paths relative to layer derived dir that this engine writes

    Engines must be deterministic: given the same inputs and seed, they must
    produce identical outputs.
    """

    name: str = "base"
    version: str = "0.1.0"
    layer: Layer = Layer.PHYSICS  # Which layer this engine belongs to
    requires: list[str] = []
    input_files: list[str] = []
    output_files: list[str] = []

    def __init__(
        self,
        world_dir: Path,
        seed: int,
        *,
        layer_input_dirs: dict[str, Path] | None = None,
        layer_derived_dirs: dict[str, Path] | None = None,
        layer_output_dir: Path | None = None,
    ) -> None:
        """Initialize engine with layer-aware paths.

        Args:
            world_dir: Path to the root world directory.
            seed: RNG seed for reproducibility.
            layer_input_dirs: Map of layer name -> effective input path (resolved).
            layer_derived_dirs: Map of layer name -> derived path (from prior engines).
            layer_output_dir: Path to write derived output for this engine's layer.
        """
        self.world_dir = world_dir
        self.seed = seed
        self.rng = create_rng(seed)

        # Layer-aware paths
        self.layer_input_dirs = layer_input_dirs or {}
        self.layer_derived_dirs = layer_derived_dirs or {}
        self.layer_output_dir = layer_output_dir or (
            world_dir / "layers" / self.layer.value / "derived"
        )

    def find_input(self, relative_path: str) -> Path | None:
        """Find an input file by searching layer input and derived directories.

        Searches from this engine's layer upwards through the layer chain.
        For each layer, checks derived (computed outputs) first, then input.

        Args:
            relative_path: Path relative to a layer directory.

        Returns:
            Resolved Path if found, None otherwise.
        """
        from dreamulator.models.layers import LAYER_ORDER

        # Build search order: this engine's layer first, then reverse layer order
        search_layers = []
        if self.layer.value in self.layer_input_dirs or self.layer.value in self.layer_derived_dirs:
            search_layers.append(self.layer.value)
        for layer in reversed(LAYER_ORDER):
            if layer.value != self.layer.value:
                search_layers.append(layer.value)

        for layer_name in search_layers:
            # Check derived (computed) outputs first
            if layer_name in self.layer_derived_dirs:
                path = self.layer_derived_dirs[layer_name] / relative_path
                if path.exists():
                    return path
            # Then check input directories
            if layer_name in self.layer_input_dirs:
                path = self.layer_input_dirs[layer_name] / relative_path
                if path.exists():
                    return path

        return None

    def validate_inputs(self) -> list[str]:
        """Check that required input files exist.

        Returns:
            List of error messages. Empty list means all inputs are present.
        """
        errors: list[str] = []
        for f in self.input_files:
            if self.find_input(f) is None:
                errors.append(f"Missing input file: {f}")
        return errors

    def output_path(self, relative_path: str) -> Path:
        """Get the output path for a file in this engine's layer.

        Args:
            relative_path: Path relative to the layer derived directory.

        Returns:
            Full path where the output should be written.
        """
        return self.layer_output_dir / relative_path

    @abstractmethod
    def run(self, parameters: dict | None = None) -> EngineResult:
        """Execute the computation.

        Must be a pure function of inputs + seed — no side effects beyond
        writing declared output_files.

        Args:
            parameters: Optional engine-specific parameters.

        Returns:
            EngineResult describing what happened.
        """
        ...
