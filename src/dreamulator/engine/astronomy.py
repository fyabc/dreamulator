"""Astronomy engine — computes derived stellar parameters from input stellar data.

Reads layers/astronomy/input/stellar.yaml, computes mass-luminosity-radius-temperature
relations, habitable zones, and condensation lines. Outputs derived data to
layers/astronomy/derived/.
"""

from __future__ import annotations

import logging

import yaml

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.engine.physical_inputs import build_system_catalog
from dreamulator.engine.stellar_physics import (
    compute_stellar_parameters,
    condensation_lines,
    habitable_zone_boundaries,
    habitable_zone_center,
)
from dreamulator.io.loader import load_yaml_model
from dreamulator.models.layers import Layer
from dreamulator.models.stellar import StellarSystem

logger = logging.getLogger(__name__)

# Threshold for mass/luminosity consistency warning (fractional deviation)
_CONSISTENCY_THRESHOLD: float = 0.20


class AstronomyEngine(BaseEngine):
    """Computes derived stellar parameters, habitable zones, and condensation lines."""

    name = "astronomy"
    layer = Layer.ASTRONOMY
    requires: list[str] = []
    input_files = ["stellar.yaml"]
    output_files = [
        "stellar_derived.yaml",
        "habitable_zones.yaml",
        "system_catalog.yaml",
    ]

    def run(
        self, parameters: dict[str, object] | None = None, *, force: bool = False
    ) -> EngineResult:
        """Execute the astronomy engine.

        Reads stellar.yaml, computes derived parameters for each star using
        hybrid input mode (mass or luminosity), and writes two derived files.

        Args:
            parameters: Optional engine parameters (unused).

        Returns:
            EngineResult describing the computation outcome.
        """
        warnings: list[str] = []

        # Load input
        input_path = self.find_input("stellar.yaml")
        if input_path is None:
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=["stellar.yaml not found in any layer input directory"],
            )

        system = load_yaml_model(input_path, StellarSystem)

        # Compute derived parameters for each star
        stars_derived: list[dict[str, object]] = []
        hz_data: list[dict[str, object]] = []
        computed_stars: dict[str, dict[str, float]] = {}

        for star in system.stars:
            # Determine input mode and check consistency
            star_warnings = _compute_star_derived(
                star_id=star.id,
                mass=star.mass,
                luminosity=star.luminosity,
                age_gyr=star.age_gyr,
                metallicity_dex=star.metallicity,
            )
            for w in star_warnings:
                warnings.append(w)
                logger.warning("%s", w)

            params = compute_stellar_parameters(
                mass=star.mass,
                luminosity=star.luminosity,
                age_gyr=star.age_gyr,
                metallicity_dex=star.metallicity,
            )

            computed_stars[star.id] = {
                "luminosity": float(params["luminosity"]),
                "mass": float(params["mass"]),
                "radius": float(params["radius"]),
                "temperature": float(params["temperature"]),
                "ms_lifetime_gyr": float(params["ms_lifetime_gyr"]),
                "evolution_progress": float(params["evolution_progress"]),
                "age_gyr": star.age_gyr,
            }

            # Build derived star record
            stars_derived.append(
                {
                    "id": star.id,
                    "name": star.name,
                    "spectral_class": star.spectral_class,
                    "input_mode": params["input_mode"],
                    "computed_mass": params["mass"],
                    "computed_luminosity": params["luminosity"],
                    "computed_radius": params["radius"],
                    "computed_temperature": params["temperature"],
                    "ms_lifetime_gyr": params["ms_lifetime_gyr"],
                    "evolution_progress": params["evolution_progress"],
                    "metallicity_z": params["metallicity_z"],
                }
            )

            # Habitable zone and condensation lines
            lum = float(params["luminosity"])
            t_eff = float(params["temperature"])
            hz = habitable_zone_boundaries(lum, t_eff)
            hz_center = habitable_zone_center(lum, t_eff)
            cl = condensation_lines(lum)
            hz_data.append(
                {
                    "id": star.id,
                    "name": star.name,
                    "habitable_zone": hz,
                    "habitable_zone_center_au": hz_center,
                    "condensation_lines": cl,
                }
            )

        # Merge stellar.yaml + planets.yaml into a single per-body catalog
        # (frontend 3D viewer, body-encyclopedia, and the fact context in
        # guard/facts.py consume this one file — the single source of truth).
        catalog, catalog_warnings = build_system_catalog(self, computed_stars=computed_stars)
        warnings.extend(catalog_warnings)
        for w in catalog_warnings:
            logger.warning("%s", w)

        # Write output files
        self._write_yaml("stellar_derived.yaml", {"stars": stars_derived})
        self._write_yaml("habitable_zones.yaml", {"stars": hz_data})
        self._write_system_catalog(catalog)

        logger.info(
            "Computed derived parameters for %d star(s) in '%s'",
            len(system.stars),
            system.name,
        )

        return EngineResult(
            engine_name=self.name,
            success=True,
            output_files=self.output_files,
            warnings=warnings,
            metadata={
                "system_name": system.name,
                "num_stars": len(system.stars),
            },
        )

    def _write_yaml(self, filename: str, data: dict[str, object]) -> None:
        """Write data as YAML to the output directory."""
        path = self.output_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _write_system_catalog(self, data: dict[str, object]) -> None:
        """Write system_catalog.yaml with a machine-generated header."""
        path = self.output_path("system_catalog.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            f.write(
                "# system_catalog.yaml — 恒星系天体统一目录（自动生成，勿手编辑）\n"
                "# 由 dreamulator build 的天文引擎合并 stellar.yaml（天文层：恒星/轨道/\n"
                "# 叙事描述）与 planets.yaml（地质层：权威物理参数 + 大气/水圈/岩石圈）\n"
                "# 而成。共享物理字段以 planets.yaml 为权威，漂移会以 warning 报出。\n"
                "# 前端 3D 视图与天体百科应消费本文件，不再自行合并两个输入。\n"
            )
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _compute_star_derived(
    star_id: str,
    mass: float | None,
    luminosity: float | None,
    age_gyr: float,
    metallicity_dex: float,
) -> list[str]:
    """Check consistency when both mass and luminosity are provided.

    Returns:
        List of warning messages (empty if consistent or single-input mode).
    """
    if mass is None or luminosity is None:
        return []

    # Compute what luminosity the mass would predict
    from dreamulator.engine.stellar_physics import mass_luminosity_zams

    l_predicted = mass_luminosity_zams(mass)
    # Apply same age/metallicity corrections for fair comparison
    from dreamulator.engine.stellar_physics import (
        apply_age_metallicity,
        evolution_progress,
        mass_radius_zams,
    )

    tau = evolution_progress(age_gyr, mass)
    z = 10.0**metallicity_dex
    l_predicted_corrected, _ = apply_age_metallicity(l_predicted, mass_radius_zams(mass), tau, z)

    deviation = abs(luminosity - l_predicted_corrected) / l_predicted_corrected

    if deviation > _CONSISTENCY_THRESHOLD:
        return [
            f"Star '{star_id}': mass={mass} M☉ predicts L={l_predicted_corrected:.4f} L☉ "
            f"but user provided L={luminosity} L☉ (deviation {deviation:.1%}). "
            f"Using user-provided luminosity as override."
        ]
    return []
