"""Stage boundaries observed while executing a pipeline."""

from dataclasses import dataclass
from enum import StrEnum

from dreamulator.models.layers import Layer


class StageState(StrEnum):
    """States reported by the pipeline and its API observer."""

    PENDING = "pending"
    VALIDATING = "validating"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class PipelineEvent:
    """An actual engine boundary, including source-context preparation."""

    engine: str
    layer: Layer
    state: StageState
    bootstrap: bool = False
    errors: tuple[str, ...] = ()
