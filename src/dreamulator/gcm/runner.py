"""ExoPlaSim run orchestration: environment guard, execution, provenance.

Design points (2026-10-05 harness decision):

- **No silent failure.**  ExoPlaSim's ``compile_pyfft`` prints a status and
  has its exception commented out, and ``Model._crash`` moves outputs to
  ``_crashed/`` without raising by default.  This runner :func:`ensure_environment`
  *verifies* the ``exoplasim.pyfft`` extension imports and raises with a fix
  pointer if not, and :func:`run_gcm` fails loudly when postprocessing did
  not produce the NetCDF file.
- **Raw output is always kept** (``clean=False``) so failed postprocessing is
  recoverable offline (``pyburn`` can be re-run by hand).
- **Multi-year integration** uses the ``N_RUN_YEARS`` namelist knob so the
  Fortran binary integrates continuously in a single process —
  ``Model.run(years=N)`` restarts a fresh process per year and historically
  reset the spun-up wind state.  ``N_RUN_STEPS`` **must** be forced to 0
  alongside it: ``configure()`` writes ``N_RUN_STEPS=11520`` (one 360-day
  year) whenever ``rotationperiod != 1.0``, and the Fortran main loop
  returns unconditionally when the step countdown reaches zero
  (``plasim.f90``: ``if (nscd == 0) return``), silently truncating any
  ``N_RUN_YEARS`` to a single year.  The 2026-10-06 "greenhouse failure"
  and "snowball basin lock" narratives were both this truncation: every
  harness run had integrated 1 year (12 *monthly* records), not 12-50.
- **Manifest** records world-input hashes, mapped parameters, versions and
  wall-clock timing next to the outputs, matching the repo's reproducibility
  discipline.
- **Warm starts / continuations** must go through
  ``configure(restartfile=<path>)`` (passed via ``params.extras``): ExoPlaSim
  copies the seed to ``workdir/plasim_restart`` itself, and *deletes* any
  pre-placed ``plasim_restart`` when ``restartfile`` is falsy
  (``exoplasim/__init__.py`` 3.4.2, L2643-2646) — a silently
  cold-started run otherwise (verify via the ``Found N variables in file``
  line in ``MOST_DIAG``, or a year-1 temperature sanity check).
- **Serial make.**  ``exoplasim.Model()`` compiles PlaSim with ``make``, and
  PlaSim's makefile does not declare all Fortran module dependencies.  An
  inherited ``MAKEFLAGS=-jN`` (common on shared servers) races the build and
  fails with ``Cannot open module file 'landmod.mod'``; :func:`run_gcm`
  strips the parallel-make variables before constructing the model.
- **Linear-time raw reader.**  ``pyburn.readallvariables`` grows each
  variable with ``np.append`` per Fortran record (quadratic copying) after
  unpacking every value into a Python float.  On a 15-year T21 run (918 MB
  raw) it took 680 s; :func:`fast_readallvariables` reads the same buffer
  with ``np.frombuffer`` in under 1 s and returns bit-identical arrays.
  :func:`install_pyburn_patches` swaps it in for both the regular and the
  snapshot postprocessing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import struct
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dreamulator.gcm.mapping import ExoPlaSimParams

logger = logging.getLogger(__name__)

_REQUIREMENT = (
    "pip install 'exoplasim==3.4.2' netCDF4 matplotlib meson ninja pyyaml scipy "
    "&& scripts/climate/gcm/bootstrap.sh"
)


def ensure_environment() -> None:
    """Verify the ExoPlaSim Python environment is actually usable.

    Guards against the 2026-10-05 trap: on Python ≥3.12 numpy's f2py uses the
    meson backend, and if ``meson`` is missing (or the venv ``bin`` directory
    is not on ``PATH``) the ``pyfft`` extension silently fails to compile —
    ``import exoplasim.pyfft`` then breaks *every* postprocessing call while
    runs themselves appear to succeed.
    """
    try:
        import exoplasim  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "exoplasim is not installed in this environment "
            f"([gcm] extra missing). Fix: uv sync --extra gcm ({_REQUIREMENT})"
        ) from exc

    try:
        import exoplasim.pyfft  # noqa: F401
    except ImportError:
        # Retry the compilation with the venv's executables reachable —
        # the meson/ninja backends are found via PATH, not via site-packages.
        venv_bin = str(Path(sys.executable).parent)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = venv_bin + os.pathsep + old_path
        try:
            import exoplasim as _ex

            _ex.compile_pyfft()
        finally:
            os.environ["PATH"] = old_path
        try:
            import exoplasim.pyfft  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                f"exoplasim.pyfft failed to compile (numpy f2py meson backend). Fix: {_REQUIREMENT}"
            ) from exc


_PARALLEL_MAKE_VARS = ("MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS")


def serial_make_environment() -> list[str]:
    """Remove inherited parallel-make flags from ``os.environ``.

    Returns the names that were removed.  See the module docstring for why
    PlaSim must be built serially.
    """
    return [name for name in _PARALLEL_MAKE_VARS if os.environ.pop(name, None) is not None]


def fast_readallvariables(fbuffer: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drop-in replacement for ``exoplasim.pyburn.readallvariables``.

    Returns the same ``(headers, variables)`` pair with bit-identical values:
    data records are read with ``np.frombuffer`` and concatenated once per
    variable, then widened to float64 exactly as the upstream
    ``np.array(struct.unpack(...))`` path does.
    """
    import numpy as np
    from exoplasim import pyburn as pb

    en = pb._getEndian(fbuffer)
    ml, mf = pb._getwordlength(fbuffer, 0, en)
    n = 0
    mainheader, zsig, n = pb.readrecord(fbuffer, n, en, ml, mf)
    headers: dict[str, Any] = {"main": mainheader}
    variables: dict[str, Any] = {"main": zsig}
    variables["sigmah"] = zsig[: mainheader[6]]
    variables["time"] = []

    chunks: dict[str, list[Any]] = {}
    marker = en + mf
    while n < len(fbuffer):
        wl, fmt = pb._getknownwordlength(fbuffer, n, en, ml, mf)
        header_words = struct.unpack(marker, fbuffer[n : n + ml])[0] // 4
        n += ml
        header = struct.unpack(en + header_words * "i", fbuffer[n : n + header_words * 4])
        n += header_words * 4 + ml
        data_words = struct.unpack(marker, fbuffer[n : n + ml])[0] // wl
        n += ml
        field = np.frombuffer(fbuffer, dtype=en + fmt, count=data_words, offset=n)
        n += data_words * wl + ml
        kcode = str(header[0])
        if kcode == "139":
            variables["time"].append(header[6])  # nstep-nstep1, as upstream
        if kcode not in chunks:
            chunks[kcode] = []
            headers[kcode] = header
        chunks[kcode].append(field)
    for kcode, parts in chunks.items():
        variables[kcode] = np.concatenate(parts).astype(np.float64)
    return headers, variables


def install_pyburn_patches() -> None:
    """Swap the linear-time raw reader into ``exoplasim.pyburn``."""
    from exoplasim import pyburn as pb

    pb.readallvariables = fast_readallvariables


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    manifest_path: Path,
    *,
    params: ExoPlaSimParams,
    input_files: dict[str, Path],
    model_options: dict[str, Any],
) -> None:
    """Write the provenance manifest for one GCM run."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        exoplasim_version = version("exoplasim")
    except PackageNotFoundError:
        exoplasim_version = None
    manifest = {
        "params": asdict(params),
        "configure_kwargs": params.to_configure_kwargs(),
        "input_hashes": {name: _hash_file(path) for name, path in input_files.items()},
        "model_options": model_options,
        "versions": {
            "python": sys.version.split()[0],
            "exoplasim": exoplasim_version,
            "platform": platform.platform(),
        },
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def multi_year_otherargs(years: int) -> dict[str, str]:
    """Namelist overrides for a continuous single-process multi-year run.

    ``N_RUN_STEPS=0`` disables the step countdown that would otherwise
    silently cap the integration at ``configure()``'s default of one
    360-day year (see module docstring); the month countdown derived from
    ``N_RUN_YEARS`` then controls the duration (``plasim.f90`` main loop:
    ``do while (mocd > 0 .or. nscd > 0)`` with an early ``return`` only
    when the *step* countdown hits zero).
    """
    return {
        "N_RUN_YEARS@plasim_namelist": str(years),
        "N_RUN_STEPS@plasim_namelist": "0",
    }


def run_gcm(
    params: ExoPlaSimParams,
    workdir: str | Path,
    model_name: str = "gcm_run",
    *,
    years: int = 2,
    resolution: str = "T21",
    layers: int = 10,
    ncpus: int = 1,
    input_files: dict[str, Path] | None = None,
    landmap: str | Path | None = None,
) -> dict[str, Path]:
    """Run ExoPlaSim for ``years`` model years and return output paths.

    Returns a dict with ``workdir``, ``nc`` (NetCDF, may be missing on
    postprocessing failure — in which case a ``RuntimeError`` is raised),
    ``raw`` (unpacked Fortran output) and ``diag`` paths.  ``_crash`` is
    replaced by a hard raise: output preservation is *not* a substitute for
    an error.

    ``landmap`` is a ``.sra`` land-mask file (see :mod:`dreamulator.gcm.surface`);
    when given, the run uses it instead of the aquaplanet surface.
    """
    ensure_environment()
    import exoplasim

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    def _hard_crash(self: Any) -> None:  # noqa: ANN001
        raise RuntimeError(
            f"ExoPlaSim reported a crash for {self.workdir}; see its log files "
            "under the workdir for the Fortran-side reason"
        )

    exoplasim.Model._crash = _hard_crash
    install_pyburn_patches()

    removed = serial_make_environment()
    if removed:
        logger.info("unset %s: PlaSim must be built with serial make", ", ".join(removed))
    model = exoplasim.Model(
        workdir=str(workdir),
        modelname=model_name,
        resolution=resolution,
        layers=layers,
        ncpus=ncpus,
        outputtype=".nc",
    )
    kwargs = params.to_configure_kwargs()
    model.configure(
        aquaplanet=landmap is None,
        landmap=str(landmap) if landmap is not None else None,
        otherargs=multi_year_otherargs(years),
        **kwargs,
    )
    # pyburn defaults to timeaverage=True with times=12: it would squash the
    # whole integration into 12 equally spaced records regardless of length
    # (a 1-year run's records look monthly, a 50-year run's are 50-month
    # means — the 2026-10-06 "12 months per run" confusion).  Request one
    # record per model month instead.  The extension must be re-stated:
    # cfgpostprocessor's default would silently switch the output to .npz.
    model.cfgpostprocessor(extension=".nc", times=years * 12)
    started = time.time()
    model.run(clean=False)  # keep raw MOST.* for postprocessing cross-checks

    nc_candidates = sorted(workdir.glob("MOST.?????.nc"))
    raw_candidates = sorted(p for p in workdir.glob("MOST.?????") if p.suffix == "")
    diag_candidates = sorted(workdir.glob("MOST_DIAG.?????"))
    if not nc_candidates:
        raise RuntimeError(
            f"no NetCDF output appeared under {workdir} — postprocessing failed "
            "(see burnout log; after fixing the environment, re-run via "
            "exoplasim.pyburn.postprocess on the kept raw output)"
        )
    all_inputs = dict(input_files or {})
    if landmap is not None:
        all_inputs["landmap"] = Path(landmap)
    write_manifest(
        workdir / "manifest.json",
        params=params,
        input_files=all_inputs,
        model_options={
            "years": years,
            "resolution": resolution,
            "layers": layers,
            "ncpus": ncpus,
            "aquaplanet": landmap is None,
            "wall_seconds": round(time.time() - started, 1),
        },
    )
    return {
        "workdir": workdir,
        "nc": nc_candidates[0],
        "raw": raw_candidates[0] if raw_candidates else None,  # type: ignore[dict-item]
        "diag": diag_candidates[0] if diag_candidates else None,  # type: ignore[dict-item]
    }


def postprocess_raw(raw: str | Path, out_nc: str | Path, params: ExoPlaSimParams) -> Path:
    """Re-run pyburn on a kept raw output (recovery path for failed runs)."""
    ensure_environment()
    import exoplasim.pyburn as pb

    install_pyburn_patches()
    pb.postprocess(
        str(raw),
        str(out_nc),
        logfile=None,
        variables=None,
        mode="grid",
        radius=params.radius,
        gravity=params.gravity,
    )
    return Path(out_nc)


def subprocess_env_hint() -> str:
    """One-liner for running the CLI under the right interpreter/venv."""
    return f"PATH prefix for meson/ninja: {Path(sys.executable).parent}"


__all__ = [
    "ensure_environment",
    "fast_readallvariables",
    "install_pyburn_patches",
    "multi_year_otherargs",
    "postprocess_raw",
    "run_gcm",
    "serial_make_environment",
    "subprocess_env_hint",
    "write_manifest",
    "_REQUIREMENT",
]
