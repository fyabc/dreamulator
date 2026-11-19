"""Internal subprocess entry for one local web refinement."""

from __future__ import annotations

import json
import resource
import shutil
import subprocess
import sys
from pathlib import Path


def main(request: Path) -> None:
    work = json.loads(request.read_text(encoding="utf-8"))
    root = request.parent
    output = root / "pack"
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

    from dreamulator.media.terrain_refine import refine_region_pack

    def stage(name: str) -> None:
        (root / "stage").write_text(name, encoding="utf-8")

    refine_region_pack(output, Path(work["td"]), on_stage=stage)
    shutil.rmtree(output / "refine-tmp", ignore_errors=True)
    if not (output / "refined-out" / "height.meters.npy").is_file():
        raise RuntimeError("Refinement did not produce a numeric elevation raster")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
