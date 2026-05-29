"""Simulation models — seeds, runs, computation manifests for provenance tracking."""

from datetime import datetime

from pydantic import BaseModel, Field


class SimulationSeed(BaseModel):
    """Reproducible randomness seed."""

    seed: int = Field(ge=0, description="Integer seed for numpy.random.Generator")


class EngineInfo(BaseModel):
    """Information about a simulation engine."""

    name: str
    version: str
    parameters: dict = Field(default_factory=dict)


class StepRecord(BaseModel):
    """Record of a single computation step in the pipeline."""

    engine: str = Field(description="Engine name that ran this step")
    input_files: dict[str, str] = Field(
        default_factory=dict, description="Mapping of file path -> sha256 checksum"
    )
    output_files: dict[str, str] = Field(
        default_factory=dict, description="Mapping of file path -> sha256 checksum"
    )
    parameters: dict = Field(default_factory=dict)
    started: datetime
    completed: datetime
    success: bool
    notes: str = ""


class ComputationManifest(BaseModel):
    """Tracks the full computation history for a world's derived data."""

    world_name: str
    seed: int
    steps: list[StepRecord] = Field(default_factory=list)
    input_checksum: str = Field(default="", description="Combined checksum of all input files")
    generated: datetime
    reproducible: bool = Field(
        default=True,
        description="True if all steps used seeded RNG and deterministic algorithms",
    )


class SimulationRun(BaseModel):
    """A time-series simulation run."""

    run_id: str = Field(description="Unique run identifier")
    config: dict = Field(default_factory=dict, description="Parameters for this run")
    manifest: ComputationManifest | None = None
    num_steps: int = Field(default=0, ge=0)
    dt_years: float = Field(default=1.0, gt=0, description="Time step size in years")
    summary: dict = Field(default_factory=dict, description="Aggregated results and metrics")
