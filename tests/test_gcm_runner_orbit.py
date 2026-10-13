"""Orbit verification of GCM runs (dreamulator.gcm.runner.parse_orbit_block / verify_orbit)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from dreamulator.gcm.mapping import ExoPlaSimParams
from dreamulator.gcm.runner import parse_orbit_block, verify_orbit

BERGER = """ *       Using Berger orbit   nfixorb=0           *
 *****************************************
 *     Computed Orbital Parameters       *
 *****************************************
 * Year AD           =                 1 *
 * Eccentricity      =          0.017465 *
 * Obliquity (deg)   =         23.695250 *
 * Obliquity (rad)   =          0.413560 *
 * Long of perh(deg) =         68.836615 *
 * Long of perh(rad) =          4.343018 *
 * Long at v.e.(rad) =         -0.032728 *
 *****************************************
"""

FIXED = (
    BERGER.replace(" *       Using Berger orbit   nfixorb=0           *\n", "")
    .replace("0.017465", "0.067863")
    .replace("23.695250", "19.900000")
    .replace("68.836615", "262.677744")
)

PARAMS = ExoPlaSimParams(
    radius=1.07, gravity=10.28, rotationperiod=3.1336, obliquity=19.9, eccentricity=0.06786252,
    flux=1254.85, year=99.82, pressure=1.014, lonvernaleq=262.677744,
)  # fmt: skip


def test_parse_orbit_block_reads_printed_values() -> None:
    got = parse_orbit_block(BERGER)
    assert got == {
        "Eccentricity": 0.017465,
        "Obliquity (deg)": 23.69525,
        "Long of perh(deg)": 68.836615,
    }
    assert parse_orbit_block("no block here") == {}


def test_verify_orbit_rejects_the_berger_earth_orbit() -> None:
    with pytest.raises(RuntimeError, match="Berger"):
        verify_orbit(BERGER, PARAMS)


def test_verify_orbit_accepts_the_requested_fixed_orbit() -> None:
    verify_orbit(FIXED, PARAMS)


def test_verify_orbit_reports_each_mismatch() -> None:
    with pytest.raises(RuntimeError, match="Obliquity"):
        verify_orbit(FIXED, replace(PARAMS, obliquity=23.44))


def test_manifest_records_command_paths_and_code_version(tmp_path) -> None:  # noqa: ANN001
    import json

    from dreamulator.gcm.runner import write_manifest

    land = tmp_path / "land.sra"
    land.write_bytes(b"x")
    write_manifest(
        tmp_path / "manifest.json",
        params=PARAMS,
        input_files={"landmap": land},
        model_options={"years": 1},
        command=["python", "run.py", "--configure", '{"twobandalbedo": true}'],
    )
    m = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert m["command"] == "python run.py --configure '{\"twobandalbedo\": true}'"
    assert m["input_paths"] == {"landmap": str(land)}
    assert "code_version" in m
