"""Internal subprocess entry for one local web refinement."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

if sys.platform != "win32":
    # Windows has no resource limits; the POSIX job runner caps RSS itself.
    import resource


def main(request: Path) -> None:
    work = json.loads(request.read_text(encoding="utf-8"))
    root = request.parent
    output = root / "pack"
    if sys.platform != "win32":
        resource.setrlimit(resource.RLIMIT_DATA, (work["limit"], work["limit"]))
    if work["pack"] is not None:
        shutil.copytree(Path(work["pack"]) / "input", output / "input")
    else:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "dreamulator.cli",
                "region",
                "pack",
                *work["export_args"],
                "--output",
                str(output),
            ],
            check=True,
        )

    from dreamulator.media.terrain_blend import RefinementMode
    from dreamulator.media.terrain_refine import refine_region_pack

    def stage(name: str) -> None:
        (root / "stage").write_text(name, encoding="utf-8")

    refine_region_pack(
        output,
        Path(work["td"]) if work["td"] is not None else None,
        mode=RefinementMode(work["mode"]),
        native_resolution_km=work["native_resolution_km"],
        preserve_wavelength_km=work["preserve_wavelength_km"],
        river_threshold=work["river_threshold"],
        on_stage=stage,
    )
    shutil.rmtree(output / "refine-tmp", ignore_errors=True)
    if not (output / "refined-out" / "height.meters.npy").is_file():
        raise RuntimeError("Refinement did not produce a numeric elevation raster")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
