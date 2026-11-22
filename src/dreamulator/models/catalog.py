"""Runtime-independent access to entities in a derived system catalog."""

from typing import Any

_BODY_IDENTITY_KEYS = (
    "id",
    "name",
    "body_type",
    "parent_id",
    "in_planets_yaml",
    "magnetic_field_strength_ut",
    "description",
)
_FLAT_SECTIONS = ("physical", "orbit", "derived")
_NESTED_SECTIONS = ("atmosphere", "hydrosphere", "lithosphere")


def _flatten_body(body: dict[str, Any]) -> dict[str, Any]:
    """Promote scalar sections, but keep atmosphere, water and rock composition nested."""
    entity: dict[str, Any] = {key: body[key] for key in _BODY_IDENTITY_KEYS if key in body}
    for section in _FLAT_SECTIONS:
        values = body.get(section)
        if isinstance(values, dict):
            entity.update(values)
    for section in _NESTED_SECTIONS:
        values = body.get(section)
        if isinstance(values, dict):
            entity[section] = values
    entity["is_satellite"] = entity.get("body_type") == "natural_satellite"
    return entity


def load_entities(catalog: dict[str, Any]) -> dict[str, Any]:
    """Key stars and flattened bodies by ID, preferring full-precision orbit entries."""
    orbits = {
        str(entry["body_id"]): entry
        for entry in catalog.get("orbits") or []
        if isinstance(entry, dict) and entry.get("body_id") is not None
    }
    entities: dict[str, Any] = {}
    for star in catalog.get("stars") or []:
        if isinstance(star, dict) and star.get("id") is not None:
            entities[str(star["id"])] = star
    for body in catalog.get("bodies") or []:
        if isinstance(body, dict) and body.get("id") is not None:
            entity = _flatten_body(body)
            elements = orbits.get(str(body["id"]))
            if elements is not None:
                entity.update({key: value for key, value in elements.items() if key != "body_id"})
            entities[str(body["id"])] = entity
    return entities
