"""Sky-culture tests: structural validation, cross-file reference checks,
and edge normalization.

The contract under test: cultures reference background objects by id only
(the Stellarium sky-culture model), structural mistakes are rejected by the
Pydantic validators, unresolvable references are reported by the engine-side
validator, and the derived output deduplicates edges.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from pydantic import ValidationError

from dreamulator.engine.civilization import CivilizationEngine
from dreamulator.engine.sky_culture import (
    collect_reference_ids,
    derive_sky_culture,
    normalize_edges,
    validate_cultures,
)
from dreamulator.models.sky_background import (
    BackgroundStarDerived,
    DeepSkyObjectDerived,
    SkyBackgroundDerived,
)
from dreamulator.models.sky_culture import Asterism, SkyCulture, SkyCultureInput

if TYPE_CHECKING:
    from pathlib import Path


def _catalogue() -> SkyBackgroundDerived:
    return SkyBackgroundDerived(
        stars=[
            BackgroundStarDerived(
                id="star_a",
                magnitude=1.0,
                temperature_k=6000.0,
                unit=(1.0, 0.0, 0.0),
                source="authored",
            ),
            BackgroundStarDerived(
                id="star_b",
                magnitude=2.0,
                temperature_k=5000.0,
                unit=(0.0, 1.0, 0.0),
                source="authored",
            ),
            BackgroundStarDerived(
                id="bg_star_00001",
                magnitude=5.0,
                temperature_k=4000.0,
                unit=(0.0, 0.0, 1.0),
                source="starfield",
            ),
        ],
        deep_sky=[
            DeepSkyObjectDerived(
                id="dso_x",
                type="cluster",
                magnitude=3.0,
                angular_size_deg=2.0,
                unit=(1.0, 0.0, 0.0),
            )
        ],
    )


def test_collect_reference_ids_excludes_procedural_starfield() -> None:
    ids = collect_reference_ids(_catalogue())
    assert ids == {"star_a", "star_b", "dso_x"}


def test_validate_cultures_reports_unresolved_references() -> None:
    cultures = [
        SkyCulture(
            id="c1",
            name="Culture One",
            star_names={"star_a": "the Nail", "bg_star_00001": "ghost"},
            asterisms=[
                Asterism(id="ast1", name="Figure", lines=[("star_a", "star_b"), ("star_a", "nope")])
            ],
        )
    ]
    errors = validate_cultures(cultures, collect_reference_ids(_catalogue()))
    assert len(errors) == 2
    assert any("nope" in e and "ast1" in e for e in errors)
    # procedural starfield ids are not referenceable even though they exist
    assert any("bg_star_00001" in e and "star_names" in e for e in errors)


def test_validate_cultures_accepts_valid_references() -> None:
    cultures = [
        SkyCulture(
            id="c1",
            name="Culture One",
            star_names={"star_a": "the Nail"},
            asterisms=[Asterism(id="ast1", name="Figure", lines=[("star_a", "dso_x")])],
        )
    ]
    assert validate_cultures(cultures, collect_reference_ids(_catalogue())) == []


def test_derive_deduplicates_edges_keeping_first_occurrence() -> None:
    source = SkyCultureInput(
        cultures=[
            SkyCulture(
                id="c1",
                name="Culture One",
                asterisms=[
                    Asterism(
                        id="ast1",
                        name="Figure",
                        lines=[("star_a", "star_b"), ("star_b", "star_a"), ("star_b", "dso_x")],
                    )
                ],
            )
        ]
    )
    derived = derive_sky_culture(source)
    (asterism,) = derived.cultures[0].asterisms
    assert asterism.lines == [("star_a", "star_b"), ("star_b", "dso_x")]
    assert normalize_edges([]) == []


def test_empty_input_derives_to_empty() -> None:
    assert derive_sky_culture(SkyCultureInput()).cultures == []


def test_structural_problems_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Asterism(id="a", name="A", lines=[])  # an empty figure draws nothing
    with pytest.raises(ValidationError):
        Asterism(id="a", name="A", lines=[("star_a", "star_a")])  # self-edge
    with pytest.raises(ValidationError):
        SkyCultureInput(
            cultures=[
                SkyCulture(id="c1", name="One"),
                SkyCulture(id="c1", name="One again"),  # duplicate culture id
            ]
        )
    with pytest.raises(ValidationError):
        SkyCultureInput(
            cultures=[
                SkyCulture(
                    id="c1",
                    name="One",
                    asterisms=[Asterism(id="ast1", name="F", lines=[("a", "b")])],
                ),
                SkyCulture(
                    id="c2",
                    name="Two",
                    asterisms=[Asterism(id="ast1", name="F", lines=[("c", "d")])],
                ),
            ]
        )  # asterism ids are globally unique (the selection namespace is flat)


def test_round_trip_preserves_names_and_meaning() -> None:
    source = SkyCultureInput(
        cultures=[
            SkyCulture(
                id="culture_xiangxing",
                name="向星诸族（暂定）",
                description="test",
                star_names={"star_arrow_alpha": "出鞘"},
                asterisms=[
                    Asterism(
                        id="asterism_arrow",
                        name="箭",
                        meaning="沿箭四倍见极",
                        lines=[("star_arrow_delta", "star_arrow_gamma")],
                    )
                ],
            )
        ]
    )
    dumped = source.model_dump(mode="json")
    restored = SkyCultureInput.model_validate(dumped)
    assert restored == source
    derived = derive_sky_culture(restored)
    assert derived.cultures[0].star_names == {"star_arrow_alpha": "出鞘"}
    assert derived.cultures[0].asterisms[0].meaning == "沿箭四倍见极"


# ---- engine-level integration (CivilizationEngine wiring) ----

#: Minimal derived-shape sky catalogue (what the astronomy engine writes).
CATALOGUE_YAML = {
    "frame": "ecliptic",
    "starfield": {"seed": 1, "count": 0, "magnitude_limit": 6.5},
    "stars": [
        {
            "id": "star_a",
            "name": None,
            "magnitude": 1.0,
            "temperature_k": 6000.0,
            "unit": [1.0, 0.0, 0.0],
            "source": "authored",
            "variability": None,
        },
        {
            "id": "bg_star_00000",
            "name": None,
            "magnitude": 4.0,
            "temperature_k": 5000.0,
            "unit": [0.0, 1.0, 0.0],
            "source": "starfield",
            "variability": None,
        },
    ],
    "deep_sky": [],
    "galactic_band": None,
    "transient_events": [],
    "wandering_objects": [],
}


def _culture_yaml(second_ref: str, *, duplicate_edge: bool = False) -> str:
    """A one-culture/one-asterism document referencing star_a + `second_ref`."""
    extra = f"\n          - [{second_ref}, star_a]" if duplicate_edge else ""
    return f"""
cultures:
  - id: culture_test
    name: "Test Culture"
    star_names:
      star_a: "the Nail"
    asterisms:
      - id: asterism_test
        name: "Figure"
        meaning: "lore"
        lines:
          - [star_a, {second_ref}]{extra}
"""


def _engine(tmp_path, culture_yaml: str | None, catalogue: dict | None) -> CivilizationEngine:
    civ_in: Path = tmp_path / "layers" / "civilization" / "input"
    civ_in.mkdir(parents=True)
    astro_derived: Path = tmp_path / "layers" / "astronomy" / "derived"
    astro_derived.mkdir(parents=True)
    if culture_yaml is not None:
        (civ_in / "sky_culture.yaml").write_text(culture_yaml, encoding="utf-8")
    if catalogue is not None:
        with (astro_derived / "sky_background.yaml").open("w", encoding="utf-8") as fh:
            yaml.safe_dump(catalogue, fh, allow_unicode=True)
    return CivilizationEngine(
        tmp_path,
        seed=1,
        layer_input_dirs={"civilization": civ_in},
        layer_derived_dirs={"astronomy": astro_derived},
    )


def test_prepare_rejects_procedural_starfield_reference(tmp_path) -> None:
    engine = _engine(tmp_path, _culture_yaml("bg_star_00000"), CATALOGUE_YAML)
    _, warnings, errors = engine._prepare_sky_culture()
    # procedural starfield ids are not referenceable, even though they exist
    assert len(errors) == 1
    assert "bg_star_00000" in errors[0]
    assert warnings == []


def test_prepare_accepts_authored_and_dso_references(tmp_path) -> None:
    catalogue = {
        **CATALOGUE_YAML,
        "deep_sky": [
            {
                "id": "dso_x",
                "name": None,
                "type": "cluster",
                "magnitude": 3.0,
                "angular_size_deg": 1.0,
                "unit": [0.0, 0.0, 1.0],
            }
        ],
    }
    # the reversed duplicate edge exercises normalization through the engine path
    engine = _engine(tmp_path, _culture_yaml("dso_x", duplicate_edge=True), catalogue)
    derived, warnings, errors = engine._prepare_sky_culture()
    assert errors == []
    assert warnings == []
    assert derived.cultures[0].star_names == {"star_a": "the Nail"}
    assert derived.cultures[0].asterisms[0].lines == [("star_a", "dso_x")]


def test_prepare_warns_without_catalogue(tmp_path) -> None:
    engine = _engine(tmp_path, _culture_yaml("star_z"), None)
    derived, warnings, errors = engine._prepare_sky_culture()
    assert errors == []  # nothing to validate against — not the author's fault
    assert any("NOT validated" in w for w in warnings)
    assert derived.cultures  # still derived (references pass through unchecked)


def test_run_fails_build_on_unknown_reference_and_publishes_nothing(tmp_path) -> None:
    engine = _engine(tmp_path, _culture_yaml("nope"), CATALOGUE_YAML)
    result = engine.run()
    assert not result.success
    assert any("nope" in w for w in result.warnings)
    # a failed build never publishes derived data
    assert not (tmp_path / "layers" / "civilization" / "derived" / "sky_culture.yaml").exists()
