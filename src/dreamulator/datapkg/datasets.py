"""Dataset registry for imported-terrain data sources.

Maps the stable ``dataset`` id used in a ``terrain_import`` recipe to the raw
data's URL / expected size / provenance.  The URL and size here must stay in
sync with the importer that actually downloads the data (audit
branch-build-bootstrap-plan §4: "源数据 URL、版本与经核实的校验摘要可放入代码内
数据集注册表，配置引用稳定数据集 ID").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSpec:
    url: str
    expected_size_mb: int
    provenance: str


# Keyed by the stable ``dataset`` id in the terrain_import recipe.  URLs mirror
# the importer constants (import_earth_elevation._ETOPO1_URL etc.).
DATASETS: dict[str, DatasetSpec] = {
    "etopo1_ice_surface_grid_registered": DatasetSpec(
        url=(
            "https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO1/data/"
            "ice_surface/grid_registered/netcdf/ETOPO1_Ice_g_gmt4.grd.gz"
        ),
        expected_size_mb=420,
        provenance="ETOPO1 Ice Surface (grid-registered), NOAA NGDC",
    ),
}


def get_dataset(dataset_id: str) -> DatasetSpec | None:
    return DATASETS.get(dataset_id)
