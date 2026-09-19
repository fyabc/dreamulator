"""Result-contract metadata + endpoint consistency (CONTRACT-01).

The API / static export / frontend fields are synced across three files by hand
(``scripts/release/export_static.py``, ``frontend/src/api/staticClient.ts``,
``frontend/src/api/client.ts``).  These tests assert the two things that drift
most often:

1. the result metadata (format version + time convention) is well-formed;
2. every ``staticApi.X(...)`` delegation in ``client.ts`` has a matching ``X``
   method in ``staticClient.ts`` — so a new endpoint can't silently drop in one
   of the two readers.
"""

from __future__ import annotations

import re
from pathlib import Path

from dreamulator.result_contract import (
    FORMAT_VERSION,
    REFERENCE_MONTH_DAYS,
    REFERENCE_YEAR_DAYS,
    result_metadata,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_result_metadata_has_format_version_and_time() -> None:
    meta = result_metadata()
    assert meta["format_version"] == FORMAT_VERSION == "1"
    time = meta["time"]
    assert time["reference_year_days"] == REFERENCE_YEAR_DAYS == 365.25
    assert time["reference_month_days"] == REFERENCE_MONTH_DAYS == 365.25 / 12.0


def test_export_static_injects_metadata() -> None:
    src = (_PROJECT_ROOT / "scripts/release/export_static.py").read_text(encoding="utf-8")
    assert "from dreamulator.result_contract import result_metadata" in src
    assert "meta.update(result_metadata())" in src


def test_client_delegations_are_defined_in_static_client() -> None:
    client_ts = (_PROJECT_ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    static_ts = (_PROJECT_ROOT / "frontend/src/api/staticClient.ts").read_text(encoding="utf-8")

    # client.ts delegates via `staticApi.X(...)`.
    delegated = set(re.findall(r"staticApi\.(\w+)", client_ts))
    # staticClient.ts defines methods as `  name: (...) => ...` (or `async`).
    defined = set(
        re.findall(r"^\s{2}(\w+):\s*(?:async\s*)?\(", static_ts, flags=re.MULTILINE)
    )

    missing = delegated - defined
    assert not missing, (
        "client.ts delegates to staticApi methods that staticClient.ts does not define: "
        f"{sorted(missing)}"
    )
