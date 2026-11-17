"""Checks for held-out calibration independence and unsupported flat reaches."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.geology.manning_channel_depth import manning_mean_depth
from scripts.media import check_manning_channel_depth as check


def test_predictions_do_not_use_heldout_width_or_depth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = Path(__file__).parents[1] / "scripts/geology/data"
    observations = data / "usgs_mean_channel_geometry.csv"
    slopes = data / "usgs_mean_channel_slopes.csv"
    monkeypatch.setattr(check, "plot_comparison", lambda *args: None)
    monkeypatch.setattr(check, "plot_examples", lambda *args: None)
    baseline = check.evaluate(observations, slopes, tmp_path / "baseline")
    with observations.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if row["use"] == "validation":
            row["width_ft"] = str(float(row["width_ft"]) * 3)
            row["mean_depth_ft"] = str(float(row["mean_depth_ft"]) * 10)
    changed = tmp_path / "changed.csv"
    with changed.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    perturbed = check.evaluate(changed, slopes, tmp_path / "perturbed")
    assert perturbed["calibration"] == baseline["calibration"]
    results = []
    for name in ("baseline", "perturbed"):
        with (tmp_path / name / "station-results.csv").open(encoding="utf-8") as stream:
            results.append([row["manning_depth_m"] for row in csv.DictReader(stream)])
    assert results[0] == results[1]
    assert (
        json.loads((tmp_path / "perturbed/report.json").read_text(encoding="utf-8"))["groups"][
            "validation"
        ]["manning"]["rough_estimate_pass"]
        is False
    )


def test_flowing_reach_requires_real_positive_slope() -> None:
    with pytest.raises(ValueError, match="requires positive width and slope"):
        manning_mean_depth(np.array([20.0]), np.array([40.0]), np.array([0.0]), 0.06)


def test_dry_reach_does_not_require_an_invented_slope() -> None:
    depth = manning_mean_depth(np.array([0.0]), np.array([0.0]), np.array([0.0]), 0.06)
    np.testing.assert_array_equal(depth, [0.0])
