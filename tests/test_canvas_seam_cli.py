"""The S4 CLI distinguishes missing evidence, disagreements and measurement-only runs."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from dreamulator.media.canvas_seam import PairReport


def invoke(monkeypatch: pytest.MonkeyPatch, pair: PairReport, *args: str) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts/dev/check_canvas_seams.py"
    namespace = runpy.run_path(str(script))
    main = namespace["main"]
    monkeypatch.setitem(
        main.__globals__,
        "run_seam_check",
        lambda _, **kwargs: {"canvases_with_chunks": ["alpha", "beta"], "pairs": [pair.summary()]},
    )
    monkeypatch.setattr(sys, "argv", [str(script), "unused", *args])
    main()


@pytest.fixture
def complete_pair() -> PairReport:
    pair = PairReport(canvases=("alpha", "beta"), samples=1)
    pair.counts = {k: 1 for k in ("elevation", "bedrock", "landsea", "water", "river")}
    pair.surface_delta_m = [0.0]
    pair.bed_delta_m = [0.0]
    return pair


def test_missing_current_hydrology_is_incomplete(
    monkeypatch: pytest.MonkeyPatch, complete_pair: PairReport
) -> None:
    complete_pair.counts["water"] = 0
    complete_pair.counts["river"] = 0
    with pytest.raises(SystemExit) as caught:
        invoke(monkeypatch, complete_pair)
    assert caught.value.code == 2


@pytest.mark.parametrize("field", ["landsea_disagree", "water_disagree", "river_disagree"])
def test_categorical_disagreement_fails(
    monkeypatch: pytest.MonkeyPatch, complete_pair: PairReport, field: str
) -> None:
    setattr(complete_pair, field, 1)
    with pytest.raises(SystemExit) as caught:
        invoke(monkeypatch, complete_pair)
    assert caught.value.code == 1


def test_missing_evidence_takes_precedence_over_a_measured_disagreement(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    complete_pair: PairReport,
) -> None:
    complete_pair.counts["water"] = 0
    complete_pair.river_disagree = 1
    with pytest.raises(SystemExit) as caught:
        invoke(monkeypatch, complete_pair)
    assert caught.value.code == 2
    output = capsys.readouterr().out
    assert "river presence disagreements" in output
    assert "INCOMPLETE" in output


def test_unrequested_numeric_limits_report_only_measurement(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], complete_pair: PairReport
) -> None:
    invoke(monkeypatch, complete_pair)
    text = capsys.readouterr().out
    assert "measurement report" in text
    assert "within thresholds" not in text


def test_requested_flow_ratio_requires_a_paired_sample(
    monkeypatch: pytest.MonkeyPatch, complete_pair: PairReport
) -> None:
    with pytest.raises(SystemExit) as caught:
        invoke(monkeypatch, complete_pair, "--max-flow-ratio", "2")
    assert caught.value.code == 2
