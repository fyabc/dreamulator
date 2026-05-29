"""Base engine class and engine result model."""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

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
    - requires: list of engine names that must run before this one
    - input_files: paths relative to world dir that this engine reads
    - output_files: paths relative to world dir that this engine writes

    Engines must be deterministic: given the same inputs and seed, they must
    produce identical outputs.
    """

    name: str = "base"
    version: str = "0.1.0"
    requires: list[str] = []
    input_files: list[str] = []
    output_files: list[str] = []

    def __init__(self, world_dir: Path, seed: int) -> None:
        self.world_dir = world_dir
        self.seed = seed
        self.rng = create_rng(seed)

    def validate_inputs(self) -> list[str]:
        """Check that required input files exist.

        Returns:
            List of error messages. Empty list means all inputs are present.
        """
        errors: list[str] = []
        for f in self.input_files:
            path = self.world_dir / f
            if not path.exists():
                errors.append(f"Missing input file: {f}")
        return errors

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
