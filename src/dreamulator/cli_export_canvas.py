"""``export canvas`` command group — the global terrain-diffusion canvas chain.

One subcommand per stage, in chain order:

* ``plan``      S1 layout, ownership tables and per-canvas inputs (``canvas_layout.yaml``)
* ``refine``    S1 native mountain-source selection, integration and accepted reference statistics
* ``generate``  S1 chunk generation with terrain-diffusion, one worker per GPU, resumable
* ``status``    per-canvas progress and checksums
* ``hydrology`` S2 out-of-core fill, accumulation and river segments
* ``window``    S3 region window pack for ``export render`` (runs hydrology first if needed)
* ``mosaic``    full-resolution overview image of one canvas

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
    help="Global canvas chain: plan → generate → hydrology → window, plus status and mosaic.",
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


@canvas_app.command("plan")
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
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """S1: canvas layout, ownership tables and per-canvas TD inputs."""
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


@canvas_app.command("refine")
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
    """S1: prepare native continuous mountain sources with their accepted reference statistics."""
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


@canvas_app.command("generate")
def canvas_generate(
    root: Path = typer.Argument(help="Layout root written by `export canvas plan`"),
    td: Path = typer.Option(..., "--td", help="terrain-diffusion clone (with its .venv)"),
    canvas: str = typer.Option("all", "--canvas", help="all, or comma-separated canvas ids"),
    gpus: str = typer.Option("0", "--gpus", help="GPU ids, e.g. 0-7 or 0,2,3 (one worker each)"),
    check: bool = typer.Option(
        False, "--check", help="Also regenerate one chunk per worker boundary into chunks/check/"
    ),
) -> None:
    """S1: generate the canvases' chunks with terrain-diffusion (resumable)."""
    from dreamulator.map import td_canvas_build as tb
    from dreamulator.map import td_canvas_worker
    from dreamulator.media.terrain_refine import _td_python

    if not (root / "layout.json").is_file():
        console.print(f"[red]No layout.json in {root} — run `export canvas plan` first[/red]")
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


@canvas_app.command("status")
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


def _run_hydrology(canvas: Path, *, resume: bool, force: bool, threshold_cells: int) -> None:
    from dreamulator.media.canvas_pipeline import CanvasStore, run_canvas_fill, run_canvas_rivers

    store = CanvasStore.load(canvas)
    finals = list((store.work / "final").glob("r*_c*.npy"))
    if force or len(finals) < len(store.chunks):
        console.print(f"Running hydrology on {canvas.name} ({len(store.chunks)} chunks)")
        stats = run_canvas_fill(store, resume=resume)
        console.print(f"  {int(stats['watersheds'])} watersheds · {stats['stages_seconds']:.1f} s")
    else:
        console.print(f"Hydrology already complete under {store.work}")
    if force or not (canvas / "hydro" / "rivers.line.npy").exists():
        run_canvas_rivers(store, threshold_cells=threshold_cells)


_THRESHOLD_HELP = (
    "Channel onset in runoff-weighted cells (27000 ≈ 2.1 m³/s mean discharge at 90 m — the "
    "region chain's calibrated onset; lower values give a denser network)"
)


@canvas_app.command("hydrology")
def canvas_hydrology(
    canvas: Path = typer.Argument(help="Canvas directory (canvas.json + chunks/ + climate/)"),
    resume: bool = typer.Option(
        True, "--resume/--no-resume", help="Resume from checksummed work files"
    ),
    force: bool = typer.Option(False, "--force", help="Re-run even when work files are complete"),
    threshold_cells: int = typer.Option(27000, "--threshold-cells", help=_THRESHOLD_HELP),
) -> None:
    """S2: out-of-core fill, flow accumulation and river segments of one canvas."""
    _require_canvas_dir(canvas)
    _run_hydrology(canvas, resume=resume, force=force, threshold_cells=threshold_cells)


@canvas_app.command("window")
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
    threshold_cells: int = typer.Option(27000, "--threshold-cells", help=_THRESHOLD_HELP),
) -> None:
    """S3: crop a region window pack for `export render` (runs S2 first when unfinished)."""
    from dreamulator.media.canvas_window import CanvasSource, crop_canvas_window

    _require_canvas_dir(canvas)
    _run_hydrology(canvas, resume=True, force=False, threshold_cells=threshold_cells)
    out_dir = output or (canvas / "windows" / f"{canvas.name}-{lat:g}_{lon:g}_{span_km:g}km")
    meta = crop_canvas_window(
        CanvasSource.load(canvas),
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


@canvas_app.command("mosaic")
def canvas_mosaic(
    canvas: Path = typer.Argument(help="Canvas directory with generated chunks"),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Image (.jpg/.png/.tif; default: <export-dir>/mosaic/<layout root name>/"
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
    sea: str = typer.Option(
        "carto", "--sea", help="Ocean: carto (depth blues) | palette (the palette's own) | grey"
    ),
    exaggeration: float | None = typer.Option(
        None, "--exaggeration", help="relief: vertical exaggeration (default pixel size / 90 m)"
    ),
    intertidal: str = typer.Option(
        "-2,2",
        "--intertidal",
        help="Height band LO,HI (m) in the intertidal colour (IHO S-52 DEPIT); 'off' disables",
    ),
    quality: int = typer.Option(90, "--quality", help="JPEG quality"),
    workers: int = typer.Option(16, "--workers", help="Parallel band workers"),
) -> None:
    """Full-resolution overview image of one canvas in the export-carto palette."""
    from dreamulator.map.td_canvas_mosaic import render_mosaic

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
        from dreamulator.map.td_canvas_mosaic import DEFAULT_PALETTE, DEFAULT_STYLE

        # the default look gets no suffix; any other style or palette is named in the file
        tags = [style] if style != DEFAULT_STYLE else []
        if palette not in (None, DEFAULT_PALETTE[style]):
            tags.append(palette)
        if sea != "carto":
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
            sea=sea,
            exaggeration=exaggeration,
            intertidal_m=band,
            quality=quality,
            workers=workers,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None
    console.print(
        f"{meta['id']}: {side['width_px']} × {side['height_px']} px at {side['pixel_m']} m/px "
        f"→ {output} ({output.stat().st_size / 1e6:.0f} MB, {time.time() - t0:.0f} s)"
    )
