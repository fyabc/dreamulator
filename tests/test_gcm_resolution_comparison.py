"""Scientific contracts for resolution diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from scripts.climate.gcm.compare_resolution import diffusion_decay_per_day, effective_parameters

if TYPE_CHECKING:
    from pathlib import Path


def test_diffusion_transfer_preserves_each_resolved_mode() -> None:
    parameters = {
        "critical_wavenumber": 15,
        "power": 2,
        "TDISST_days": 5.6,
        "TDISSQ_days": 0.1,
        "TDISSZ_days": 1.1,
        "TDISSD_days": 0.2,
    }
    transferred = dict(parameters)
    for key in ["TDISST_days", "TDISSQ_days", "TDISSZ_days", "TDISSD_days"]:
        transferred[key] *= (70 / 27) ** 2
    for n in range(43):
        expected = diffusion_decay_per_day(parameters, 85, n)
        actual = diffusion_decay_per_day(transferred, 42, n)
        np.testing.assert_allclose(list(actual.values()), list(expected.values()), atol=1e-14)


def test_effective_fortran_presets_have_explicit_time_units(tmp_path: Path) -> None:
    # T42's printed presets are seconds; generic presets are printed in days
    # and announce their conversion after the namelist block.
    seconds = """&PLASIM_NL
 MPSTEP=45,
 NDEL=10*4,
 NHDIFF=16,
 TDISST=10*65664,
 TDISSQ=10*8640,
 TDISSZ=10*25920,
 TDISSD=10*5184,
 /"""
    (tmp_path / "MOST_DIAG.00000").write_text(seconds, encoding="utf-8")
    first = effective_parameters(tmp_path)
    assert first["TDISST_days"] == 0.76
    assert first["power"] == 4
    days = seconds.replace("10*65664", "10*5.6")
    days += "\n old maxval(tdisst) = 5.6\n assuming [days] - converting to [sec]"
    (tmp_path / "MOST_DIAG.00000").write_text(days, encoding="utf-8")
    second = effective_parameters(tmp_path)
    assert second["TDISST_days"] == 5.6
    assert second["TDISSQ_days"] == 0.1
