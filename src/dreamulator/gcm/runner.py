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
  reset the spun-up wind state.
- **Manifest** records world-input hashes, mapped parameters, versions and
  wall-clock timing next to the outputs, matching the repo's reproducibility
  discipline.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dreamulator.gcm.mapping import ExoPlaSimParams

_REQUIREMENT = (
    "pip install 'exoplasim==3.4.2' netCDF4 matplotlib meson ninja "
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
        otherargs={"N_RUN_YEARS@plasim_namelist": str(years)},
        **kwargs,
    )
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
    "postprocess_raw",
    "run_gcm",
    "subprocess_env_hint",
    "write_manifest",
    "_REQUIREMENT",
]
