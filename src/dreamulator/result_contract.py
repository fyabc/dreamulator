"""Result-contract metadata for exported world data (CONTRACT-01).

The audit (``project-structure-outline`` §CONTRACT-01) found the API / static
export / frontend fields are synced across three files by hand, and the time /
geometry identifiers are used across layers without a shared definition.  This
module is the single source of truth for the *metadata* of exported results —
a format version plus the time convention — so drift is caught by the
consistency fixture (``tests/test_result_contract.py``) rather than by manual
review.
"""

from __future__ import annotations

# Format version of the exported result shape.  Bump when a field/endpoint is
# added, removed, or re-typed; the consistency fixture asserts the exporter and
# the frontend readers agree with it.
FORMAT_VERSION = "1"

# Time convention (climate-pipeline.md §1): annual rates are per a 365.25-day
# reference year; monthly fields are that reference year / 12.
REFERENCE_YEAR_DAYS = 365.25
REFERENCE_MONTH_DAYS = REFERENCE_YEAR_DAYS / 12.0  # ≈ 30.44


def result_metadata() -> dict[str, object]:
    """The shared result-contract metadata (format version + time convention)."""
    return {
        "format_version": FORMAT_VERSION,
        "time": {
            "reference_year_days": REFERENCE_YEAR_DAYS,
            "reference_month_days": REFERENCE_MONTH_DAYS,
        },
    }
