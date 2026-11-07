"""``sky`` command — the observer's-sky ephemeris on the CLI.

``sky`` runs the registered ``sky_ephemeris`` engine query (reference
``docs/design/pipelines/sky-ephemeris.md``) against a world's catalog and
prints the sky table (or its JSON — the exact payload consumers such as the
video shot planner and FUI data cards read); the single-command group collapses
so users type ``dreamulator sky <world> ...``.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def _set_data_dir(data_dir: Path | None) -> None:
    import os

    if data_dir is not None:
        os.environ["DREAMULATOR_DATA_DIR"] = str(data_dir.resolve())


#: Every non-ASCII glyph the table and legend use.  GBK-family consoles encode
#: all of these; Western single-byte code pages do not — and the error message
#: below is ASCII-only so it still prints on the very consoles it rejects.
_OUTPUT_PROBE = (
    "天体高度方位视径相位照亮星等距离升落永不落下升起肉眼可见暗淡窗口极圈万千时用大于°↑↓—·（）′″"
)


def _encoding_ok(encoding: str | None) -> bool:
    if not encoding:
        return True
    try:
        _OUTPUT_PROBE.encode(encoding, errors="strict")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _angular_size_text(deg: float) -> str:
    """Angular diameter in the star-chart's stepped units: °, arcmin, arcsec.

    Degree decimals lose everything below ~0.005° to rounding (the dwarf
    planets showed as 0.000); planetaria quote sub-degree sizes in arcminutes
    and arcseconds, so the table follows: >=0.1° as degrees (the Sun-Moon
    scale reads naturally in degrees), >=1' as arcminutes, smaller as
    arcseconds with one decimal below 10".
    """
    if deg >= 0.1:
        return f"{deg:.2f}°"
    arcmin = deg * 60.0
    if arcmin >= 1.0:
        return f"{arcmin:.1f}′"
    arcsec = deg * 3600.0
    return f"{arcsec:.1f}″" if arcsec < 10.0 else f"{arcsec:.0f}″"


def _require_unicode_console() -> None:
    encoding = getattr(console.file, "encoding", None)
    if _encoding_ok(encoding):
        return
    # ASCII-only on purpose: a console that cannot show the probe cannot show
    # a Chinese error message either.
    console.print(
        f"[red]Console encoding '{encoding}' cannot display this command's output "
        "(Chinese text and degree signs). Use a UTF-8 console (Windows: 'chcp 65001' "
        "or Windows Terminal) or set PYTHONIOENCODING=utf-8.[/red]"
    )
    raise typer.Exit(code=1)


def sky(
    world: str = typer.Argument(help="World name"),
    from_body: str | None = typer.Option(
        None, "--from", help="Observing body id (default: the catalog's target body)"
    ),
    lat: float = typer.Option(0.0, "--lat", help="Observer latitude (degrees, north-positive)"),
    lon: float = typer.Option(0.0, "--lon", help="Observer longitude (degrees, east-positive)"),
    at: float = typer.Option(0.0, "--at", help="Days since the catalog epoch"),
    targets: str = typer.Option(
        "all", "--targets", help="Comma-separated body ids, or 'all' (every body but the observer)"
    ),
    branch: str | None = typer.Option(None, "--branch", "-b", help="World branch"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit the query result as JSON"),
) -> None:
    """Show every target's position, phase and rise/set above one surface point.

    Registered as a bare top-level command (the explore-seeds precedent), so
    users type ``dreamulator sky <world> ...`` with no subcommand; a second
    command later (M4 event search) would grow a group around it.
    """
    _require_unicode_console()
    from dreamulator.engine.ephemeris import sky_ephemeris
    from dreamulator.guard.facts import build_fact_context
    from dreamulator.world_manager import WorldManager

    _set_data_dir(data_dir)
    try:
        world_dir = WorldManager().world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found.[/red]")
        raise typer.Exit(code=1) from None
    context = build_fact_context(world_dir, branch)
    if context is None:
        console.print(
            f"[red]No system catalog for '{world}'"
            + (f" (branch {branch})" if branch else "")
            + " — run `dreamulator build "
            + world
            + "` first.[/red]"
        )
        raise typer.Exit(code=1)
    entities = context["entities"]

    if from_body is None:
        catalog_target = _catalog_target_body(world_dir, branch)
        if catalog_target is None or catalog_target not in entities:
            console.print("[red]The catalog has no usable target body; pass one with --from.[/red]")
            raise typer.Exit(code=1)
        from_body = catalog_target
    if from_body not in entities:
        known = ", ".join(sorted(entities))
        console.print(f"[red]Unknown body '{from_body}'. Known: {known}[/red]")
        raise typer.Exit(code=1)

    target_ids = None if targets == "all" else [t.strip() for t in targets.split(",")]
    if target_ids is not None:
        unknown = [t for t in target_ids if t not in entities]
        if unknown:
            console.print(f"[red]Unknown target body ids: {', '.join(unknown)}[/red]")
            raise typer.Exit(code=1)

    try:
        result = sky_ephemeris(entities, from_body, lat, lon, at, targets=target_ids)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    if json_output:
        console.print_json(json.dumps(result.model_dump(), ensure_ascii=False))
        return

    observer_name = entities[from_body].get("name") or from_body
    table = Table(
        title=(
            f"{observer_name}（{from_body}）上空 ({lat:+g}°, {lon:+g}°) · t = {at:g} d"
            + (
                f" · 太阳日 {result.solar_day_days:.2f} d"
                if result.solar_day_days is not None
                else ""
            )
            + f" · 自转轴来源: {result.spin_source}"
        )
    )
    columns = ("天体", "高度°", "方位°", "视径°", "相位°", "照亮", "星等", "距离", "升落")
    for column in columns:
        table.add_column(column, justify="right" if column != "天体" else "left")
    for row in result.targets:
        phase = "—" if row.phase_angle_deg is None else f"{row.phase_angle_deg:.1f}"
        illum = (
            "—" if row.illuminated_fraction is None else f"{100 * row.illuminated_fraction:.0f}%"
        )
        if row.rise_state == "rises_sets":
            # Inside the polar circles a body can cross the horizon once per
            # season: the other crossing lies beyond the rise/set window (an
            # M4 event search), shown as "—" rather than crashing.
            rise = "—" if row.next_rise_days is None else f"{row.next_rise_days:.2f}d"
            setting = "—" if row.next_set_days is None else f"{row.next_set_days:.2f}d"
            events = f"↑{rise} ↓{setting}"
        elif row.rise_state == "never_sets":
            events = "永不落下"
        else:
            events = "永不升起"
        altitude = f"{row.altitude_deg:+.2f}"
        if row.altitude_deg > 0.0:
            altitude = f"[green]{altitude}[/green]"
        elif row.altitude_deg < 0.0:
            altitude = f"[red]{altitude}[/red]"
        magnitude = f"{row.apparent_magnitude:+.2f}"
        if row.apparent_magnitude < 0.0:
            magnitude = f"[bold yellow]{magnitude}[/bold yellow]"
        elif row.apparent_magnitude >= 6.0:
            magnitude = f"[dim]{magnitude}[/dim]"
        distance = (
            f"{row.distance_km / 149_597_870.7:.3f} AU"
            if row.distance_km >= 1e7
            else f"{row.distance_km:,.0f}"
        )
        table.add_row(
            row.name or row.body_id,
            altitude,
            f"{row.azimuth_deg:.1f}",
            _angular_size_text(row.angular_diameter_deg),
            phase,
            illum,
            magnitude,
            distance,
            events,
        )
    console.print(table)
    console.print(
        "[dim]高度(alt)=地平仰角，正数在地平线上；方位(az)=0°正北顺时针；"
        "视径=角直径（不小于0.1度用度，不小于1角分用分，更小用角秒）；相位=恒星-天体-观测者夹角（0°满相）；照亮=可见盘面照亮比例；"
        "升落=下一次升起/落下距当前时刻的天数（“—”=在窗口之外，极圈内常见）；"
        "星等：黄色=亮于0等，暗淡=肉眼不可见（6等及更暗）；距离：大于一千万 km 时用 AU[/dim]"
    )


def _catalog_target_body(world_dir: Path, branch: str | None) -> str | None:
    """The catalog's ``target_body_id``, or None when unreadable."""
    from dreamulator.models.layers import Layer
    from dreamulator.resolver import LayerResolver

    try:
        derived = LayerResolver(world_dir, branch).get_derived_dir(Layer.ASTRONOMY)
    except FileNotFoundError:
        return None
    if derived is None:
        return None
    path = derived / "system_catalog.yaml"
    if not path.exists():
        return None
    import yaml

    with path.open("r", encoding="utf-8") as fh:
        catalog = yaml.safe_load(fh)
    if not isinstance(catalog, dict):
        return None
    target = catalog.get("target_body_id")
    return str(target) if target else None
