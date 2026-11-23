"""Audit authored parameters duplicated across layer input files.

The first audited case is the physical fields shared between
``astronomy/input/stellar.yaml`` bodies and ``geological/input/planets.yaml``.
``planets.yaml`` is authoritative for engine runs; a duplicate in
``stellar.yaml`` is a drift risk even when the two values currently agree,
because a later edit can change one and silently leave the other behind.

The audit is intentionally conservative and report-only at this stage: it
lists every duplicated field, distinguishing equal copies from divergent ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from dreamulator.resolver import LayerResolver

if TYPE_CHECKING:
    from pathlib import Path

_RADIUS_EARTH_KM = 6371.0


def _read_items(path: Path, key: str) -> list[dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get(key)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get("id") is not None]


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _equal(body_value: Any, planet_value: Any, *, radius: bool = False) -> bool:
    body_number = _as_float(body_value)
    planet_number = _as_float(planet_value)
    if body_number is None or planet_number is None:
        return bool(body_value == planet_value)
    if radius:
        planet_number *= _RADIUS_EARTH_KM
    return abs(body_number - planet_number) <= 1e-3 * max(
        abs(body_number), abs(planet_number), 1e-12
    )


def audit_body_field_duplicates(world_dir: Path, branch: str | None = None) -> list[str]:
    """List physical fields authored in both stellar.yaml and planets.yaml.

    Args:
        world_dir: Root world directory.
        branch: Optional branch to resolve through.

    Returns:
        One message per duplicated field. Equal and divergent copies are
        distinguished so the migration can remove the safe ones first.
    """
    resolver = LayerResolver(world_dir, branch)
    stellar = resolver.find_input_file("astronomy", "stellar.yaml")
    planets = resolver.find_input_file("geological", "planets.yaml")
    if stellar is None or planets is None:
        return []

    bodies = {str(item["id"]): item for item in _read_items(stellar, "bodies")}
    planets_by_id = {str(item["id"]): item for item in _read_items(planets, "planets")}
    if not bodies:
        return []

    messages: list[str] = []
    stellar_name = stellar.relative_to(world_dir).as_posix()
    for body_id, body in sorted(bodies.items()):
        if body_id not in planets_by_id and (
            body.get("mass_earth") is None or body.get("radius_km") is None
        ):
            messages.append(
                f"{stellar_name}: body '{body_id}' has no mass_earth/radius_km and is "
                "not defined in planets.yaml"
            )
    for body_id in sorted(set(bodies) & set(planets_by_id)):
        body = bodies[body_id]
        planet = planets_by_id[body_id]
        pairs = (
            ("mass_earth", "mass", body.get("mass_earth"), planet.get("mass"), False),
            ("radius_km", "radius", body.get("radius_km"), planet.get("radius"), True),
            (
                "rotation_period_days",
                "rotation_period_days",
                body.get("rotation_period_days"),
                planet.get("rotation_period_days"),
                False,
            ),
            (
                "axial_tilt_deg",
                "axial_tilt_deg",
                body.get("axial_tilt_deg"),
                planet.get("axial_tilt_deg"),
                False,
            ),
            ("albedo", "albedo", body.get("albedo"), planet.get("albedo"), False),
        )
        for body_field, planet_field, body_value, planet_value, is_radius in pairs:
            if body_value is None or planet_value is None:
                continue
            if _equal(body_value, planet_value, radius=is_radius):
                detail = f"equal values ({body_value})"
            else:
                detail = f"different values (stellar {body_value}, planets {planet_value})"
            messages.append(
                f"{stellar_name}: body '{body_id}' duplicates planets.yaml "
                f"field {planet_field} as {body_field}, {detail}"
            )
    return messages
