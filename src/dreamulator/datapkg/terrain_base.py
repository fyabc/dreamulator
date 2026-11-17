"""Identify climate fields that a base-terrain package must not carry."""

from __future__ import annotations

from typing import Any

CLIMATE_FIELDS = (
    "temperature_C",
    "precipitation_mm",
    "koppen_class",
    "temperature_hottest_month_C",
    "temperature_coldest_month_C",
    "ocean_current_east_m_s",
    "ocean_current_north_m_s",
    "sst_anomaly_c",
    "wind_east_m_s",
    "wind_north_m_s",
    "cloud_total_frac",
    "cloud_low_frac",
    "cloud_mid_frac",
    "cloud_high_frac",
    "slp_annual_hpa",
    "pressure_anomaly_annual_hpa",
)


def populated_climate_fields(mesh: dict[str, Any]) -> set[str]:
    """Return populated climate fields, including the observation reliability mask."""
    present: set[str] = set()
    for cell in mesh.get("cells", []):
        present.update(name for name in CLIMATE_FIELDS if cell.get(name) is not None)
        if cell.get("slp_reduction_unreliable", False):
            present.add("slp_reduction_unreliable")
    return present
