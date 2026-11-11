"""``dreamulator canvas`` — the global terrain-diffusion canvas chain.

One subcommand per stage, in chain order; per-canvas commands take a canvas
directory or a layout root (every canvas, or those ``--canvas`` names):

* ``plan``      S1 layout, ownership tables and per-canvas inputs (``canvas_layout.yaml``);
                ``--backfill mesh-sea-lake`` adds that field to planned canvases instead
* ``refine``    S1 native mountain-source selection, integration and accepted reference statistics
* ``generate``  S1 chunk generation with terrain-diffusion, one worker per GPU, resumable
* ``status``    per-canvas progress and checksums
* ``erode``     erosion and deposition, written as ``surface_process/`` increments
* ``hydrology`` S2 out-of-core fill, lakes and river segments on the installed surface
* ``run``       erode (optional) then hydrology, skipping finished steps
* ``window``    S3 region window pack for ``dreamulator render`` (runs hydrology first if needed)
* ``mosaic``    full-resolution overview image

Library code lives in ``map/td_canvas*.py`` (S1) and ``media/canvas_*.py`` (S2, S3); this module
only parses options and reports.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, cast

import typer
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from dreamulator.map.td_canvas_build import CanvasLayoutConfig

canvas_app = typer.Typer(
    help="Global canvas chain: plan → generate → erode → hydrology → window, "
    "plus status, run (erode + hydrology) and mosaic.",
    no_args_is_help=True,
)
console = Console()
LAYOUT_FILE = "canvas_layout.yaml"


def _set_data_dir(data_dir: Path | None) -> None:
    if data_dir is not None:
        os.environ["DREAMULATOR_DATA_DIR"] = str(data_dir.resolve())


def _canvas_ids(root: Path) -> list[str]:
    layout = json.loads((root / "layout.json").read_text(encoding="utf-8"))
    return [str(c["id"]) for c in layout["canvases"]]


def _select(root: Path, canvas: str) -> list[str]:
    ids = _canvas_ids(root)
    if canvas == "all":
        return ids
    wanted = [c.strip() for c in canvas.split(",") if c.strip()]
    unknown = [c for c in wanted if c not in ids]
    if unknown:
        console.print(f"[red]Unknown canvas id(s): {', '.join(unknown)}[/red]")
        raise typer.Exit(code=2) from None
    return wanted


def _targets(path: Path, canvas: str = "all") -> list[Path]:
    """Canvas directories a per-canvas command runs on.

    ``path`` is one canvas (``canvas.json``) or a layout root (``layout.json``);
    a root expands to its canvases, filtered by ``canvas`` (``all`` or ids).
    """
    if (path / "canvas.json").is_file():
        if canvas != "all":
            console.print("[red]--canvas selects within a layout root, not a canvas dir[/red]")
            raise typer.Exit(code=2) from None
        return [path]
    if (path / "layout.json").is_file():
        out = [path / cid for cid in _select(path, canvas)]
        missing = [p.name for p in out if not (p / "canvas.json").is_file()]
        if missing:
            console.print(f"[red]Canvas inputs missing for {', '.join(missing)}[/red]")
            raise typer.Exit(code=2) from None
        return out
    console.print(f"[red]{path} is neither a canvas dir (canvas.json) nor a layout root[/red]")
    raise typer.Exit(code=2) from None


_TARGET_HELP = "A canvas dir, or a layout root (all its canvases, or those --canvas names)"
_CANVAS_SELECT_HELP = "With a layout root: all, or comma-separated canvas ids"


def _require_canvas_dir(canvas: Path) -> None:
    if not (canvas / "canvas.json").is_file():
        console.print(f"[red]No canvas.json in {canvas} — is this a canvas dir?[/red]")
        raise typer.Exit(code=2) from None


def _repo_commit() -> str:
    repo = Path(__file__).resolve().parents[2]
    try:
        res = subprocess.run(
            ["git", "-C", str(repo), "describe", "--always", "--dirty", "--abbrev=12"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    return res.stdout.strip() or "unknown"


def _plan_world(
    world: str, branch: str | None, planet: str | None, cfg: CanvasLayoutConfig
) -> tuple[Any, Any, float, Path, Path, dict[str, Any]]:
    """(mesh, layout, radius, map_dir, world_dir, source) for a world's canvas layout."""
    from dreamulator.gcm.fields import mesh_fingerprint
    from dreamulator.map import td_canvas_build as tb
    from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model
    from dreamulator.map.manager import MapManager
    from dreamulator.map.region_export import read_radius_km
    from dreamulator.world_manager import WorldManager

    try:
        world_dir = WorldManager().world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None
    mm = MapManager(world_dir, branch)
    planet_id = planet or cfg.planet
    if planet_id is None:
        planets = mm.list_planets_with_maps()
        if not planets:
            console.print("[red]No map data found for this world.[/red]")
            raise typer.Exit(code=1) from None
        planet_id = planets[0]
    map_dir = mm._maps_dir(planet_id)
    mesh_file = find_mesh_file(map_dir) if map_dir is not None else None
    if map_dir is None or mesh_file is None:
        console.print(f"[red]No mesh file found for planet '{planet_id}'.[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"Loading {mesh_file}")
    mesh = load_cvt_mesh_model(mesh_file)
    radius = read_radius_km(map_dir, world_dir)
    try:
        layout = tb.plan_world_layout(mesh, radius, cfg)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    clim = map_dir / "climate_monthly.msgpack"
    source = {
        "world": world,
        "branch": branch,
        "planet": planet_id,
        "mesh_fingerprint": mesh_fingerprint(mesh)[:12],
        "mesh_sha256": tb.sha256_file(mesh_file)[:12],
        "climate_monthly_sha256": tb.sha256_file(clim)[:12] if clim.exists() else None,
        "repo_commit": _repo_commit(),
    }
    return mesh, layout, radius, map_dir, world_dir, source


def canvas_plan(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(
        None, "--branch", "-b", help="Branch (default: the layout config's branch)"
    ),
    planet: str | None = typer.Option(None, "--planet", "-p", help="Planet ID"),
    config: Path | None = typer.Option(
        None, "--config", help=f"Layout config (default: <world>/{LAYOUT_FILE})"
    ),
    root: Path | None = typer.Option(
        None, "--root", help="Layout root (default: <world>/canvases/<branch or root>)"
    ),
    canvas: str = typer.Option(
        "all", "--canvas", help="Canvases whose inputs to write: all, or comma-separated ids"
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite inputs even where generated chunks would go stale"
    ),
    precipitation_field: Path | None = typer.Option(
        None, "--precipitation-field", help="Complete native Gaussian monthly precipitation archive"
    ),
    backfill: str | None = typer.Option(
        None,
        "--backfill",
        help="Only add a field to the planned canvases under the root instead of planning: "
        "mesh-sea-lake (the mesh's sea-class lakes S2 reads as sea)",
    ),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """S1 plan: canvas layout, ownership tables and per-canvas TD inputs."""
    from dreamulator.map import td_canvas_build as tb
    from dreamulator.map.export import load_climate_monthly
    from dreamulator.world_manager import WorldManager

    _set_data_dir(data_dir)
    try:
        world_dir = WorldManager().world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None
    cfg_file = config or world_dir / LAYOUT_FILE
    cfg = tb.CanvasLayoutConfig.load(cfg_file) if cfg_file.exists() else tb.CanvasLayoutConfig()
    native_precipitation = None
    if precipitation_field is not None:
        from dreamulator.gcm.native_partition import NativePrecipitationField

        native_precipitation = NativePrecipitationField.load(precipitation_field)
    branch = branch or cfg.branch
    if backfill is not None:
        if backfill != "mesh-sea-lake":
            console.print(f"[red]Unknown --backfill {backfill!r}; use mesh-sea-lake[/red]")
            raise typer.Exit(code=2) from None
        layout_root = root or world_dir / "canvases" / (branch or "root")
        for path in _targets(layout_root, canvas):
            console.print(f"[bold]{path.name}[/bold]")
            backfill_mesh_sea_lake(path, data_dir)
        return
    mesh, layout, _r, map_dir, world_dir, source = _plan_world(world, branch, planet, cfg)
    root = root or world_dir / "canvases" / (branch or "root")
    total = sum(len(p.chunks) for p in layout.plans)
    console.print(f"Layout: {len(layout.plans)} canvases, {total} chunks")
    table = Table(title=f"Canvases — {root}")
    for col in ("id", "centre", "ncell", "chunks", "anisotropy", "land (M km²)"):
        table.add_column(col)

    root.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".canvas-plan-", dir=root.parent) as temporary:
        staged = Path(temporary)
        tb.write_layout(staged, layout, cfg, source)
        ids = _select(staged, canvas)
        t_m, p_m = load_climate_monthly(map_dir)
        cols = tb.MeshColumns.from_mesh(mesh, t_m, p_m)
        astronomy = tb.load_astronomy(map_dir)
        if astronomy is None:
            console.print(
                "[yellow]climate_metadata.json lacks the orbit: no lake_evaporation channel; "
                "S2 falls back to the Hamon lake demand[/yellow]"
            )
        stale = []
        for plan in layout.plans:
            if plan.canvas_id not in ids:
                continue
            out = root / plan.canvas_id
            old_file = out / "canvas.json"
            old = json.loads(old_file.read_text(encoding="utf-8")) if old_file.exists() else None
            planned = tb.write_canvas_inputs(
                staged,
                plan,
                cols,
                cfg.generation_params(),
                source,
                structure=cfg.structure,
                precipitation_field=native_precipitation,
                astronomy=astronomy,
            )
            if old is not None:
                new = json.loads((planned / "canvas.json").read_text(encoding="utf-8"))
                why = _stale_reason(old, new, out)
                if why is not None:
                    stale.append((plan.canvas_id, why))
            g = plan.geometry
            table.add_row(
                plan.canvas_id,
                f"{g.center_lat:.2f}, {g.center_lon:.2f}",
                str(g.ncell),
                str(len(plan.chunks)),
                f"{plan.max_anisotropy:.3f}",
                f"{plan.land_km2 / 1e6:.2f}",
            )
        console.print(table)
        if stale:
            names = ", ".join(f"{cid} ({why})" for cid, why in stale)
            msg = f"existing chunks no longer match the new inputs: {names}"
            if not force:
                console.print(
                    f"[red]{msg}. Original inputs were retained. Choose another --root or move "
                    "their chunks/ and chunks.sha256 aside before planning.[/red]"
                )
                raise typer.Exit(code=1) from None
            console.print(f"[yellow]{msg} (--force)[/yellow]")
        tb.install_planned_inputs(staged, root)


def _stale_reason(old: dict[str, Any], new: dict[str, Any], out: Path) -> str | None:
    """Which input field changed under existing chunks (None when none did or no chunks exist)."""
    if not any((out / "chunks").glob("r*_c*.npy")):
        return None
    for key in ("geometry", "conditioning_sha256", "generation", "structure", "coarse_source"):
        if old.get(key) != new.get(key):
            return key
    return None


def _parse_gpus(gpus: str) -> list[str]:
    out: list[str] = []
    for part in gpus.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.extend(str(k) for k in range(int(a), int(b) + 1))
        elif part:
            out.append(part)
    return out


def canvas_refine(
    world: str = typer.Argument(help="World whose geological sources to use"),
    reference: Path = typer.Argument(help="Original S3 layout root"),
    output: Path = typer.Argument(help="New independent layout root"),
    config: Path = typer.Option(
        ...,
        "--config",
        help="Native mountain sources and accepted statistical references by canvas",
    ),
    td: Path = typer.Option(..., "--td", help="terrain-diffusion clone with its .venv"),
    branch: str | None = typer.Option(
        None, "--branch", "-b", help="Source branch (config or reference by default)"
    ),
    source_map: Path | None = typer.Option(
        None,
        "--source-map",
        help="Geological map directory with native source archive and contract",
    ),
    gpu: str = typer.Option("0", "--gpu", help="GPU used once for each shared statistics batch"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """S1 refine: native continuous mountain sources with accepted reference statistics."""
    from dreamulator.map import td_canvas_worker
    from dreamulator.map.canvas_orogen_refinement import (
        CanvasRefinementConfig,
        load_native_inputs,
        refine_canvas_layout,
    )
    from dreamulator.map.manager import MapManager
    from dreamulator.media.terrain_refine import _td_python
    from dreamulator.resolver import LayerResolver
    from dreamulator.world_manager import WorldManager

    _set_data_dir(data_dir)
    try:
        cfg = CanvasRefinementConfig.load(config)
        world_dir = WorldManager().world_dir(world)
        layout = json.loads((reference / "layout.json").read_text(encoding="utf-8"))
        source = layout.get("source", {})
        if source.get("world") and source["world"] != world:
            raise ValueError("reference layout belongs to a different world")
        branch = branch or cfg.branch or source.get("branch")
        planet = cfg.planet or source.get("planet")
        if not planet:
            raise ValueError("select a planet in the refinement config or reference layout")
        if source.get("planet") and source["planet"] != planet:
            raise ValueError("reference layout belongs to a different planet")
        if source_map is None:
            origin = LayerResolver(world_dir, branch).resolve_layer("geological").source
            geological_branch = (
                origin.removeprefix("branch:") if origin.startswith("branch:") else None
            )
            source_map = MapManager(world_dir, geological_branch)._maps_dir(planet)
        if source_map is None:
            raise FileNotFoundError("no native geological map found; provide --source-map")
        native = load_native_inputs(world_dir, source_map, branch=branch, planet=planet)
        td = td.resolve()
        python = _td_python(td)
        worker = Path(td_canvas_worker.__file__).resolve()
        env = {
            **os.environ,
            "CUDA_VISIBLE_DEVICES": gpu,
            "PYTHONUNBUFFERED": "1",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        }

        def prepare_statistics(original: Path, candidate: Path, out: Path) -> None:
            console.print(f"{candidate.parent.name}: preparing fixed reference statistics")
            log = out.parent / "prepare.log"
            with log.open("w", encoding="utf-8") as stream:
                subprocess.run(
                    [
                        str(python),
                        str(worker),
                        "--prepare-coarse",
                        str(original.resolve()),
                        str(candidate.resolve()),
                        str(out.resolve()),
                    ],
                    cwd=td,
                    env=env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            log.replace(out / "prepare.log")

        result = refine_canvas_layout(
            reference, output, cfg, native, prepare_statistics=prepare_statistics
        )
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"Prepared native mountain inputs: {result}")


def canvas_generate(
    root: Path = typer.Argument(help="Layout root written by `canvas plan`"),
    td: Path = typer.Option(..., "--td", help="terrain-diffusion clone (with its .venv)"),
    canvas: str = typer.Option("all", "--canvas", help="all, or comma-separated canvas ids"),
    gpus: str = typer.Option("0", "--gpus", help="GPU ids, e.g. 0-7 or 0,2,3 (one worker each)"),
    check: bool = typer.Option(
        False, "--check", help="Also regenerate one chunk per worker boundary into chunks/check/"
    ),
) -> None:
    """S1 generate: the canvases' chunks with terrain-diffusion (resumable)."""
    from dreamulator.map import td_canvas_build as tb
    from dreamulator.map import td_canvas_worker
    from dreamulator.media.terrain_refine import _td_python

    if not (root / "layout.json").is_file():
        console.print(f"[red]No layout.json in {root} — run `canvas plan` first[/red]")
        raise typer.Exit(code=2) from None
    td = td.resolve()  # the workers run with cwd = td, so every path must be absolute
    py = _td_python(td)
    worker = Path(td_canvas_worker.__file__).resolve()
    devices = _parse_gpus(gpus)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    # pinned, not inherited: a host-wide value may carry options the TD venv's torch rejects
    env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    failed = []
    for cid in _select(root, canvas):
        cdir = (root / cid).resolve()
        _require_canvas_dir(cdir)
        st = tb.canvas_status(cdir)
        if st["done"] == st["chunks"]:
            console.print(f"{cid}: {st['chunks']} chunks already done")
            continue
        console.print(f"{cid}: {st['chunks'] - st['done']} of {st['chunks']} chunks to generate")
        t0 = time.time()
        procs = []
        for k, dev in enumerate(devices):
            cmd = [str(py), str(worker), str(cdir), str(k), str(len(devices))]
            if check:
                cmd.append("--check")
            out = open(cdir / f"worker{k}.out", "w", encoding="utf-8")  # noqa: SIM115
            procs.append(
                (
                    subprocess.Popen(
                        cmd,
                        cwd=td,
                        env={**env, "CUDA_VISIBLE_DEVICES": dev},
                        stdout=out,
                        stderr=subprocess.STDOUT,
                    ),
                    out,
                )
            )
        codes = []
        for p, out in procs:
            codes.append(p.wait())
            out.close()
        st = tb.canvas_status(cdir)
        console.print(
            f"  {st['done']}/{st['chunks']} done in {time.time() - t0:.0f} s"
            + (f" · worker exit codes {codes}" if any(codes) else "")
        )
        if any(codes) or st["done"] != st["chunks"]:
            failed.append(cid)
    if failed:
        console.print(
            f"[red]Incomplete: {', '.join(failed)} (see worker*.out); rerun to resume[/red]"
        )
        raise typer.Exit(code=1) from None


def canvas_status_cmd(
    root: Path = typer.Argument(help="Layout root"),
    verify: bool = typer.Option(False, "--verify", help="Recompute every chunk's SHA-256"),
) -> None:
    """Per-canvas progress: done, missing and corrupt chunks."""
    from dreamulator.map import td_canvas_build as tb

    if not (root / "layout.json").is_file():
        console.print(f"[red]No layout.json in {root}[/red]")
        raise typer.Exit(code=2) from None
    table = Table(title=f"Canvas status — {root}")
    for col in ("id", "chunks", "done", "missing", "corrupt"):
        table.add_column(col)
    tot = {"chunks": 0, "done": 0, "missing": 0, "corrupt": 0}
    for cid in _canvas_ids(root):
        if not (root / cid / "canvas.json").is_file():
            table.add_row(cid, "—", "—", "—", "no inputs")
            continue
        st = tb.canvas_status(root / cid, verify=verify)
        for k in tot:
            tot[k] += st[k]
        table.add_row(cid, *(str(st[k]) for k in ("chunks", "done", "missing", "corrupt")))
    table.add_row("total", *(str(tot[k]) for k in ("chunks", "done", "missing", "corrupt")))
    console.print(table)


def _run_hydrology(
    canvas: Path,
    *,
    resume: bool,
    force: bool,
    threshold_cells: int,
    workers: int | None = None,
    surface: str = "auto",
) -> None:
    from dreamulator.media.canvas_pipeline import CanvasStore, run_canvas_fill, run_canvas_rivers
    from dreamulator.media.canvas_surface_process import read_surface_tag

    store = CanvasStore.load(canvas, surface=surface)
    filled_on = read_surface_tag(store.work)
    if filled_on is not None and filled_on != store.surface:
        console.print(
            f"[yellow]{store.work.name} was built on {filled_on}; recomputing on "
            f"{store.surface}[/yellow]"
        )
        force, resume = True, False
    finals = list((store.work / "final").glob("r*_c*.npy"))
    if force or len(finals) < len(store.chunks):
        console.print(f"Running hydrology on {canvas.name} ({len(store.chunks)} chunks)")
        stats = run_canvas_fill(store, resume=resume, workers=workers)
        console.print(f"  {int(stats['watersheds'])} watersheds · {stats['stages_seconds']:.1f} s")
    else:
        console.print(f"Hydrology already complete under {store.work}")
    hydro = canvas / "hydro"
    if (
        force
        or not (hydro / "rivers.line.npy").exists()
        or read_surface_tag(hydro) != store.surface
    ):
        run_canvas_rivers(store, threshold_cells=threshold_cells)


_SURFACE_HELP = (
    "Installed surface: auto (TD chunks + surface_process increments when that product is "
    "complete), td, or surface-process"
)

_THRESHOLD_HELP = (
    "Channel onset in runoff-weighted cells (27000 ≈ 2.1 m³/s mean discharge at 90 m — the "
    "region chain's calibrated onset; lower values give a denser network)"
)


def canvas_hydrology(
    target: Path = typer.Argument(help=_TARGET_HELP),
    canvas: str = typer.Option("all", "--canvas", help=_CANVAS_SELECT_HELP),
    resume: bool = typer.Option(
        True, "--resume/--no-resume", help="Resume from checksummed work files"
    ),
    force: bool = typer.Option(False, "--force", help="Re-run even when work files are complete"),
    river_threshold: int = typer.Option(
        27000, "--river-threshold", "--threshold-cells", help=_THRESHOLD_HELP
    ),
    workers: int | None = typer.Option(
        None, "--workers", help="Processes for the per-chunk fill stages (default: CPUs, max 16)"
    ),
    surface: str = typer.Option("auto", "--surface", help=_SURFACE_HELP),
) -> None:
    """S2 hydrology: out-of-core fill, lakes and river segments (per canvas)."""
    for path in _targets(target, canvas):
        _run_hydrology(
            path,
            resume=resume,
            force=force,
            threshold_cells=river_threshold,
            workers=workers,
            surface=surface,
        )


def backfill_mesh_sea_lake(
    canvas: Path,
    data_dir: Path | None = None,
) -> None:
    """Backfill geometry_fields/mesh_sea_lake.npy (mesh sea-class lakes) on a planned canvas.

    S1 writes the field for new canvases.  The mesh is located from canvas.json's
    source and must still carry the fingerprint the canvas was planned from.
    """
    import numpy as np

    from dreamulator.gcm.fields import mesh_fingerprint
    from dreamulator.map import td_canvas as tc
    from dreamulator.map import td_canvas_build as tb
    from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model
    from dreamulator.map.manager import MapManager
    from dreamulator.world_manager import WorldManager

    _require_canvas_dir(canvas)
    _set_data_dir(data_dir)
    meta_path = canvas / "canvas.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    source = meta.get("source", {})
    try:
        world_dir = WorldManager().world_dir(source["world"])
        map_dir = MapManager(world_dir, source.get("branch"))._maps_dir(source["planet"])
    except (KeyError, FileNotFoundError):
        console.print("[red]canvas.json source does not name an existing world and planet[/red]")
        raise typer.Exit(code=1) from None
    mesh_file = find_mesh_file(map_dir) if map_dir is not None else None
    if mesh_file is None:
        console.print(f"[red]No mesh file for planet '{source['planet']}'[/red]")
        raise typer.Exit(code=1) from None
    mesh = load_cvt_mesh_model(mesh_file)
    fingerprint = mesh_fingerprint(mesh)[:12]
    if source.get("mesh_fingerprint") not in (None, fingerprint):
        console.print(
            f"[red]Mesh fingerprint {fingerprint} differs from the planned "
            f"{source['mesh_fingerprint']}: re-plan the canvas instead[/red]"
        )
        raise typer.Exit(code=1) from None
    g = meta["geometry"]
    geom = tc.CanvasGeometry(
        float(g["center_lat"]), float(g["center_lon"]), float(g["radius_km"]), int(g["ncell"])
    )
    cells = mesh.cells
    lat = np.array([c.lat for c in cells])
    lon = np.array([c.lon for c in cells])
    sea_lake = np.array([bool(c.is_lake) and c.water_class == "ocean" for c in cells])
    meta["mesh_sea_lake"] = tb.write_mesh_sea_lake(
        canvas, geom, sea_lake, tc.unit_vectors(lat, lon)
    )
    meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    grid = np.load(canvas / tb.MESH_SEA_LAKE_PATH)
    console.print(
        f"Wrote {tb.MESH_SEA_LAKE_PATH}: {int(grid.sum())} of {grid.size} cells sea-class lake"
    )


def _erode_one(
    canvas: Path,
    block: int,
    t_max_myr: float,
    native: bool,
    native_time_myr: float,
    workers: int | None,
    data_dir: Path | None,
    cells_per_step: float = 5.0,
) -> None:
    """Erosion and deposition of one canvas (TD surface -> surface_process/ increments)."""
    import numpy as np

    from dreamulator.engine.geological import GeologicalEngine
    from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model
    from dreamulator.map.incision_time import effective_incision_time_myr
    from dreamulator.map.manager import MapManager
    from dreamulator.map.orogen_contract import load_orogen_contract
    from dreamulator.map.surface_process import SurfaceProcessParams
    from dreamulator.map.td_canvas import unit_vectors
    from dreamulator.media.canvas_surface_process import (
        CanvasSurfaceConfig,
        run_canvas_surface_process,
    )
    from dreamulator.models.layers import LAYER_ORDER
    from dreamulator.resolver import LayerResolver
    from dreamulator.world_manager import WorldManager

    _require_canvas_dir(canvas)
    _set_data_dir(data_dir)
    meta = json.loads((canvas / "canvas.json").read_text(encoding="utf-8"))
    source = meta.get("source", {})
    try:
        world_dir = WorldManager().world_dir(source["world"])
    except (KeyError, FileNotFoundError):
        console.print("[red]canvas.json source does not name an existing world[/red]")
        raise typer.Exit(code=1) from None
    branch, planet = source.get("branch"), source.get("planet")
    map_dir = MapManager(world_dir, branch)._maps_dir(planet) if planet else None
    mesh_file = find_mesh_file(map_dir) if map_dir is not None else None
    if map_dir is None or mesh_file is None:
        console.print(f"[red]No mesh for planet '{planet}'[/red]")
        raise typer.Exit(code=1) from None
    contract_path = canvas / "orogen_contract.json"
    if not contract_path.exists():
        contract_path = map_dir / "orogen_contract.json"
    if not contract_path.exists():
        console.print("[red]No orogen_contract.json in the canvas or the map directory[/red]")
        raise typer.Exit(code=1) from None
    resolver = LayerResolver(world_dir, branch)
    inputs, derived = {}, {}
    for layer in LAYER_ORDER:
        if (directory := resolver.get_input_dir(layer)) is not None:
            inputs[layer.value] = directory
        if (directory := resolver.get_derived_dir(layer)) is not None:
            derived[layer.value] = directory
    geo, warnings = GeologicalEngine(
        world_dir, 42, layer_input_dirs=inputs, layer_derived_dirs=derived
    )._load_config({"planet_id": planet})
    if geo is None:
        console.print(f"[red]Geological configuration could not be loaded: {warnings}[/red]")
        raise typer.Exit(code=1) from None
    mesh = load_cvt_mesh_model(mesh_file)
    console.print(f"Effective incision time from {contract_path.name} ...")
    teff = effective_incision_time_myr(
        mesh,
        load_orogen_contract(contract_path),
        geo.radius_km,
        geo.gravity_m_s2,
        geo.continental_elevation_m,
    )
    lat = np.array([c.lat for c in mesh.cells])
    lon = np.array([c.lon for c in mesh.cells])
    run_canvas_surface_process(
        canvas,
        teff,
        unit_vectors(lat, lon),
        CanvasSurfaceConfig(
            block=block,
            t_max_myr=t_max_myr,
            native=native,
            native_time_myr=native_time_myr,
            params=SurfaceProcessParams(max_cells_per_step=cells_per_step),
        ),
        workers=workers,
        source={
            "world": source.get("world"),
            "branch": branch,
            "planet": planet,
            "mesh_sha256": _short_sha(mesh_file),
            "orogen_contract": str(contract_path.name),
            "orogen_contract_sha256": _short_sha(contract_path),
        },
        log=lambda m: console.print(m),
    )


def _short_sha(path: Path) -> str:
    from dreamulator.map.td_canvas_build import sha256_file

    return sha256_file(path)[:12]


def canvas_window(
    canvas: Path = typer.Argument(help="Canvas directory (canvas.json + chunks/ + climate/)"),
    lat: float = typer.Option(..., "--lat", help="Window centre latitude (degrees)"),
    lon: float = typer.Option(..., "--lon", help="Window centre longitude (degrees)"),
    span_km: float = typer.Option(550.0, "--span-km", help="Square window side (km)"),
    out_res: int = typer.Option(2048, "--out-res", help="Window raster resolution (square N×N)"),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output pack dir (default: <canvas>/windows/<canvas>-<lat>_<lon>_<span>km)",
    ),
    river_threshold: int = typer.Option(
        27000, "--river-threshold", "--threshold-cells", help=_THRESHOLD_HELP
    ),
    surface: str = typer.Option("auto", "--surface", help=_SURFACE_HELP),
) -> None:
    """S3 window: crop a region pack for `dreamulator render` (runs S2 first if unfinished)."""
    from dreamulator.media.canvas_window import CanvasSource, crop_canvas_window

    _require_canvas_dir(canvas)
    _run_hydrology(
        canvas, resume=True, force=False, threshold_cells=river_threshold, surface=surface
    )
    out_dir = output or (canvas / "windows" / f"{canvas.name}-{lat:g}_{lon:g}_{span_km:g}km")
    meta = crop_canvas_window(
        CanvasSource.load(canvas, surface=surface),
        center_lat=lat,
        center_lon=lon,
        span_km=span_km,
        out_res=out_res,
        out_dir=out_dir,
    )
    grid = cast("dict[str, int]", meta["grid"])
    elev = cast("dict[str, float]", meta["elevation_m"])
    ocean = float(cast("float", meta["ocean_fraction"]))
    console.print(
        f"Cropped {canvas.name} → {out_dir} · grid {grid['w']}×{grid['h']}"
        f" · elev {elev['min']:.0f}…{elev['max']:.0f} m · ocean {ocean * 100:.1f}%"
    )


def _mosaic_one(
    canvas: Path,
    output: Path | None,
    step: int,
    style: str,
    palette: str | None,
    sea: str | None,
    exaggeration: float | None,
    intertidal: str,
    ice: bool,
    quality: int | None,
    workers: int,
    surface: str,
) -> None:
    """Full-resolution overview image of one canvas in the shared print look."""
    from dreamulator.map.td_canvas_mosaic import (
        DEFAULT_PALETTE,
        DEFAULT_SEA,
        DEFAULT_STYLE,
        PRINT_EXAGGERATION,
        PRINT_QUALITY,
        render_mosaic,
    )

    _require_canvas_dir(canvas)
    band: tuple[float, float] | None = None
    if intertidal.strip().lower() != "off":
        try:
            lo, hi = (float(x) for x in intertidal.split(","))
        except ValueError:
            console.print("[red]--intertidal takes LO,HI in metres (e.g. -2,2) or 'off'[/red]")
            raise typer.Exit(code=2) from None
        band = (min(lo, hi), max(lo, hi))
    meta = json.loads((canvas / "canvas.json").read_text(encoding="utf-8"))
    if output is None:
        # one folder per layout root, so canvases built with different recipes stay apart
        tag = canvas.resolve().parent.name
        px_m = round(float(meta["geometry"]["px_km"]) * step * 1000)
        root = Path(os.environ.get("DREAMULATOR_EXPORT_DIR", "exports"))
        # the default look gets no suffix; any other style or palette is named in the file
        tags = [style] if style != DEFAULT_STYLE else []
        if palette not in (None, DEFAULT_PALETTE[style]):
            tags.append(palette)
        if sea not in (None, DEFAULT_SEA):
            tags.append(f"sea-{sea}")
        suffix = "".join(f"_{t}" for t in tags)
        output = root / "mosaic" / tag / f"{meta['id']}_{px_m}m{suffix}.jpg"
    t0 = time.time()
    try:
        side = render_mosaic(
            canvas,
            output,
            step=step,
            style=style,
            palette=palette,
            sea=sea or DEFAULT_SEA,
            exaggeration=PRINT_EXAGGERATION if exaggeration is None else exaggeration,
            intertidal_m=band,
            quality=PRINT_QUALITY if quality is None else quality,
            workers=workers,
            ice_overlay=ice,
            surface=surface,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None
    console.print(
        f"{meta['id']}: {side['width_px']} × {side['height_px']} px at {side['pixel_m']} m/px "
        f"→ {output} ({output.stat().st_size / 1e6:.0f} MB, {time.time() - t0:.0f} s)"
    )


_EROSION_OPTIONS_DOC = "see `dreamulator canvas erode --help`"


def canvas_erode(
    target: Path = typer.Argument(help=_TARGET_HELP),
    canvas: str = typer.Option("all", "--canvas", help=_CANVAS_SELECT_HELP),
    block: int = typer.Option(8, "--block", help="Coarse block (8: about 720 m; 16: 1.44 km)"),
    t_max_myr: float = typer.Option(50.0, "--t-max-myr", help="Incision time of platforms (Myr)"),
    native: bool = typer.Option(
        True, "--native/--no-native", help="Run the 90 m chunk pass after the coarse level"
    ),
    native_time_myr: float = typer.Option(4.0, "--native-time-myr", help="Native pass time"),
    cells_per_step: float = typer.Option(
        5.0,
        "--cells-per-step",
        help="Coarse time step as the knickpoint retreat per step in cells (5 calibrated; "
        "up to 20 converges and is 4x faster on large canvases)",
    ),
    workers: int | None = typer.Option(None, "--workers", help="Processes for the native pass"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Erosion and deposition: TD surface -> surface_process/ increments (per canvas)."""
    for path in _targets(target, canvas):
        _erode_one(
            path, block, t_max_myr, native, native_time_myr, workers, data_dir, cells_per_step
        )


def canvas_mosaic(
    target: Path = typer.Argument(help=_TARGET_HELP),
    canvas: str = typer.Option("all", "--canvas", help=_CANVAS_SELECT_HELP),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Image path (one canvas only; default: <export-dir>/mosaic/<layout root name>/"
        "<canvas>_<metres>m.jpg, export-dir = $DREAMULATOR_EXPORT_DIR or ./exports)",
    ),
    step: int = typer.Option(
        4, "--step", help="Block-average N×N pixels (1 = native 90 m; must divide 2048)"
    ),
    style: str = typer.Option(
        "relief", "--style", help="Shading: relief (shaded relief, default) | carto (export-carto)"
    ),
    palette: str | None = typer.Option(
        None,
        "--palette",
        help="Land colours (default: pastel for relief, adaptive for carto): adaptive, pastel, "
        "gmt-etopo1, gmt-globe, gmt-relief, wikipedia, cross-blended",
    ),
    sea: str | None = typer.Option(
        None,
        "--sea",
        help="Ocean: carto (depth blues, default) | palette (palette colours) "
        "| flat (constant blue) | grey",
    ),
    exaggeration: float | None = typer.Option(
        None, "--exaggeration", help="relief: vertical exaggeration (default 4 at every step)"
    ),
    intertidal: str = typer.Option(
        "-2,2",
        "--intertidal",
        help="Height band LO,HI (m) in the intertidal colour (IHO S-52 DEPIT); 'off' disables",
    ),
    ice: bool = typer.Option(
        True, "--ice/--no-ice", help="Overlay ice cover from surface/ice_chunks where present"
    ),
    quality: int | None = typer.Option(None, "--quality", help="JPEG quality (default 95)"),
    workers: int = typer.Option(16, "--workers", help="Parallel band workers"),
    surface: str = typer.Option("auto", "--surface", help=_SURFACE_HELP),
) -> None:
    """Full-resolution overview image in the shared print look (per canvas)."""
    paths = _targets(target, canvas)
    if output is not None and len(paths) > 1:
        console.print("[red]--output names one image; give a single canvas[/red]")
        raise typer.Exit(code=2) from None
    for path in paths:
        _mosaic_one(
            path, output, step, style, palette, sea, exaggeration, intertidal, ice, quality,
            workers, surface,
        )  # fmt: skip


def canvas_run(
    target: Path = typer.Argument(help=_TARGET_HELP),
    canvas: str = typer.Option("all", "--canvas", help=_CANVAS_SELECT_HELP),
    erode: bool = typer.Option(
        True, "--erode/--no-erode", help="Erosion and deposition before S2 (skipped when done)"
    ),
    block: int = typer.Option(8, "--block", help="Erosion coarse block (8: 720 m; 16: 1.44 km)"),
    t_max_myr: float = typer.Option(50.0, "--t-max-myr", help="Incision time of platforms"),
    cells_per_step: float = typer.Option(
        5.0,
        "--cells-per-step",
        help="Coarse time step as the knickpoint retreat per step in cells (5 calibrated; "
        "up to 20 converges and is 4x faster on large canvases)",
    ),
    river_threshold: int = typer.Option(27000, "--river-threshold", help=_THRESHOLD_HELP),
    workers: int | None = typer.Option(None, "--workers", help="Processes per stage"),
    force: bool = typer.Option(False, "--force", help="Redo every step, finished or not"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Post-generation chain of each canvas: erode (optional) then S2; finished steps skip."""
    from dreamulator.media.canvas_surface_process import surface_process_complete

    for path in _targets(target, canvas):
        console.print(f"[bold]{path.name}[/bold]")
        if erode and (force or not surface_process_complete(path)):
            _erode_one(path, block, t_max_myr, True, 4.0, workers, data_dir, cells_per_step)
        elif erode:
            console.print("  erosion already complete")
        _run_hydrology(
            path,
            resume=not force,
            force=force,
            threshold_cells=river_threshold,
            workers=workers,
            surface="surface-process" if erode else "td",
        )


#: Pipeline order: the help lists the commands as they run.
for _name, _command in (
    ("plan", canvas_plan),
    ("refine", canvas_refine),
    ("generate", canvas_generate),
    ("status", canvas_status_cmd),
    ("erode", canvas_erode),
    ("hydrology", canvas_hydrology),
    ("run", canvas_run),
    ("window", canvas_window),
    ("mosaic", canvas_mosaic),
):
    canvas_app.command(_name)(_command)
