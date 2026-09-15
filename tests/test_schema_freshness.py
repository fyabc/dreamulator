"""Freshness gate for the committed JSON Schemas in ``schemas/``.

The ``schemas/`` directory is a build artifact of ``dreamulator schema``
(Pydantic → JSON Schema, ``io/schema_gen.py``) kept in git as a reference for
LLM/external YAML authors.  Nothing else in the repo consumes it, so without
this test it silently drifts every time one of the registered models changes
(2026-09: ``j2`` / ``k2_over_q`` / ``c_over_mr2`` went stale within 3 weeks).

Regenerate with::

    uv run dreamulator schema
"""

from pathlib import Path

from dreamulator.io.schema_gen import SCHEMA_MODELS, generate_schemas

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def test_schemas_are_fresh(tmp_path: Path) -> None:
    generated = generate_schemas(tmp_path)
    generated_names = {p.name for p in generated}
    committed_names = {p.name for p in SCHEMAS_DIR.glob("*.schema.json")}

    assert generated_names == committed_names, (
        f"schema set mismatch — SCHEMA_MODELS registry vs schemas/: "
        f"only generated {sorted(generated_names - committed_names)}, "
        f"only committed {sorted(committed_names - generated_names)}"
    )
    assert len(generated_names) == len(SCHEMA_MODELS)

    stale = [p.name for p in generated if p.read_bytes() != (SCHEMAS_DIR / p.name).read_bytes()]
    assert not stale, f"stale schema(s): {stale} — regenerate with `uv run dreamulator schema`"
