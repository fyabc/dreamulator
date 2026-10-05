"""``ucc`` command group — UCC v2 short-code inspection.

``ucc decode`` parses a zone-grammar code (specification §5.4) and prints
the full classification behind it, validating structure along the way —
the panel-tooltip equivalent for terminals, docs review and scripting.
"""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from dreamulator.map.ucc import UCCGrammarError, parse_ucc_code

ucc_app = typer.Typer(
    help="UCC short codes: decode and validate (v2 zone grammar).",
    no_args_is_help=True,
)
console = Console()

_THERMAL_NAMES = {
    "tropical": "热带 (tropical)",
    "temperate": "温和 (temperate)",
    "cold": "寒冷 (cold)",
    "polar": "极地 (polar)",
}
_SUPPLY_NAMES = {
    "arid": "干旱 (arid)",
    "semi_arid": "半干旱 (semi-arid)",
    "transitional": "过渡 (transitional)",
    "humid": "湿润 (humid)",
}
_SLOT_NAMES = {
    "o": "海洋槽位 (ocean — supply axis not applicable)",
    "n": "陆地·供需不适用 (land, supply axis n/a — reason in the status field)",
}
_SHAPE_NAMES = {"unimodal": "单雨季 (unimodal wet season)", "bimodal": "双雨季 (two wet seasons)"}
_PHASE_NAMES = {
    "in_phase": "雨热同季 (rain peaks with demand)",
    "anti_phase": "雨热反季 (rain peaks half a cycle away — Mediterranean-type)",
}


def _parts_to_dict(code: str, parts: Any) -> dict[str, Any]:
    return {
        "code": code,
        "render": parts.render(),
        "thermal": parts.thermal,
        "supply": parts.supply,
        "slot": parts.slot,
        "modifiers": {
            "continental": parts.continental,
            "water_stress": parts.water_stress,
            "highland": parts.highland,
        },
        "shape": parts.shape,
        "phase": parts.phase,
    }


@ucc_app.command("decode")
def decode(
    codes: list[str] = typer.Argument(..., help="One or more UCC v2 codes, e.g. 'Dp-Slgmo-H'"),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON (one object per code)"
    ),
) -> None:
    """Decode UCC v2 short codes into their full classification.

    Exit code 1 with a grammar error line for every invalid code; valid codes
    still print before the failure summary.
    """
    results: list[tuple[str, Any]] = []
    errors: list[tuple[str, str]] = []
    for code in codes:
        try:
            results.append((code, parse_ucc_code(code)))
        except UCCGrammarError as exc:
            errors.append((code, str(exc)))

    if json_output:
        payload = [{"ok": True, **_parts_to_dict(code, parts)} for code, parts in results] + [
            {"ok": False, "code": code, "error": err} for code, err in errors
        ]
        console.print_json(json.dumps(payload, ensure_ascii=False))
    else:
        table = Table(title="UCC decode", show_lines=False)
        table.add_column("code", style="bold")
        table.add_column("classification")
        for code, parts in results:
            bits = [_THERMAL_NAMES[parts.thermal]]
            if parts.supply is not None:
                bits.append(_SUPPLY_NAMES[parts.supply])
            elif parts.slot is not None:
                bits.append(_SLOT_NAMES[parts.slot])
            if parts.continental:
                bits.append("强季节 l")
            if parts.water_stress:
                bits.append("干季 g")
            if parts.highland:
                bits.append("高地 H")
            if parts.shape is not None:
                bits.append(_SHAPE_NAMES[parts.shape])
            if parts.phase is not None:
                bits.append(_PHASE_NAMES[parts.phase])
            table.add_row(code, " · ".join(bits))
        if results:
            console.print(table)
        for code, err in errors:
            console.print(f"[red]✗ {code}[/red] — {err}")

    if errors:
        raise typer.Exit(code=1)
