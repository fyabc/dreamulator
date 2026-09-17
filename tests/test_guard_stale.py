"""Tests for dreamulator.guard.stale — stale detection (harness.md §7).

Covers P1a: ``layer_input_fingerprint`` (per-layer YAML fingerprint) and
``check_broken_refs`` (① template broken-ref detection).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from dreamulator.guard.stale import (
    NO_YAML_FINGERPRINT,
    check_broken_refs,
    check_decision_records,
    layer_input_fingerprint,
    render_claims,
    write_baseline,
)

if TYPE_CHECKING:
    from pathlib import Path

# Minimal system_catalog.yaml: one star, no bodies.
_CATALOG: dict[str, object] = {
    "stars": [{"id": "star_sol", "name": "Sol", "luminosity_sol": 1.0}],
    "bodies": [],
}


def _write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(text)


def _make_world(root: Path, *, catalog: object | None = _CATALOG) -> Path:
    """Minimal world with astronomy input (stellar.yaml) + optional catalog."""
    world = root / "test-world"
    _write_yaml(world / "layers" / "astronomy" / "input" / "stellar.yaml", {"stars": []})
    if catalog is not None:
        _write_yaml(world / "layers" / "astronomy" / "derived" / "system_catalog.yaml", catalog)
    return world


# ---------------------------------------------------------------------------
# layer_input_fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_deterministic(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    a = layer_input_fingerprint(world, None, "astronomy")
    b = layer_input_fingerprint(world, None, "astronomy")
    assert a == b
    assert a != ""  # non-empty for a configured layer


def test_fingerprint_changes_with_yaml_content(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    before = layer_input_fingerprint(world, None, "astronomy")
    _write_yaml(
        world / "layers" / "astronomy" / "input" / "stellar.yaml",
        {"stars": [{"id": "star_ignis"}]},
    )
    after = layer_input_fingerprint(world, None, "astronomy")
    assert before != after


def test_fingerprint_ignores_markdown(tmp_path: Path) -> None:
    """Narrative .md edits must not invalidate physical fingerprints."""
    world = _make_world(tmp_path)
    before = layer_input_fingerprint(world, None, "astronomy")
    _write_text(world / "layers" / "astronomy" / "input" / "note.md", "hello world")
    after = layer_input_fingerprint(world, None, "astronomy")
    assert before == after


def test_fingerprint_empty_for_unconfigured_layer(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    assert layer_input_fingerprint(world, None, "physics") == ""


def test_fingerprint_no_yaml_sentinel(tmp_path: Path) -> None:
    """A layer with input dir but no .yaml → a distinct 'no-yaml' sentinel."""
    world = _make_world(tmp_path)
    _write_text(world / "layers" / "climate" / "input" / "note.md", "hello")
    assert layer_input_fingerprint(world, None, "climate") == NO_YAML_FINGERPRINT


# ---------------------------------------------------------------------------
# check_broken_refs
# ---------------------------------------------------------------------------


def test_no_broken_refs_when_all_resolve(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _write_text(
        world / "layers" / "astronomy" / "input" / "ok.md",
        "luminosity {{ entities.star_sol.luminosity_sol }} L☉\n",
    )
    assert check_broken_refs(world) == []


def test_broken_ref_detected_for_missing_field(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _write_text(
        world / "layers" / "astronomy" / "input" / "broken.md",
        "x {{ entities.star_sol.nonexistent_field }} y\n",
    )
    findings = check_broken_refs(world)
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "broken_ref"
    assert f.path == "layers/astronomy/input/broken.md"
    assert f.layer == "astronomy"
    assert "nonexistent_field" in f.detail


def test_broken_ref_also_scans_design_notes(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _write_text(
        world / "design-notes" / "0001-test.md",
        "x {{ entities.star_sol.missing }} y\n",
    )
    findings = check_broken_refs(world)
    assert len(findings) == 1
    assert findings[0].path == "design-notes/0001-test.md"
    assert findings[0].layer is None


def test_not_run_when_context_unavailable(tmp_path: Path) -> None:
    """GUARD-01: unbuilt world → an explicit not_run finding, NEVER a silent
    empty list that reads as 'verified clean'."""
    world = _make_world(tmp_path, catalog=None)
    _write_text(
        world / "layers" / "astronomy" / "input" / "broken.md",
        "x {{ entities.star_sol.nonexistent_field }} y\n",
    )
    findings = check_broken_refs(world)
    assert [f.kind for f in findings] == ["not_run"]
    assert "unavailable" in findings[0].detail


# ---------------------------------------------------------------------------
# check_decision_records
# ---------------------------------------------------------------------------


def test_decision_record_input_changed(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    good = layer_input_fingerprint(world, None, "astronomy")

    _write_text(
        world / "design-notes" / "0001-ok.md",
        f"---\nstatus: accepted\nchecked_against:\n  astronomy: {good}\n---\nbody\n",
    )
    _write_text(
        world / "design-notes" / "0002-drift.md",
        "---\nstatus: accepted\nchecked_against:\n  astronomy: deadbeef\n---\nbody\n",
    )

    findings = check_decision_records(world)
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "input_changed"
    assert f.path == "design-notes/0002-drift.md"
    assert f.layer == "astronomy"
    assert "input changed" in f.detail


def test_decision_record_without_checked_against_skipped(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _write_text(
        world / "design-notes" / "0001-no-check.md",
        "---\nstatus: accepted\n---\nbody\n",
    )
    assert check_decision_records(world) == []


# ---------------------------------------------------------------------------
# ③ render diff + divergence
# ---------------------------------------------------------------------------


def test_render_claims_extracts_and_renders() -> None:
    context: dict[str, object] = {"entities": {"star_sol": {"luminosity_sol": 1.0}}}
    claims = render_claims("x {{ entities.star_sol.luminosity_sol }} y", context)
    assert claims == {"{{ entities.star_sol.luminosity_sol }}": "1.0"}


def _rebuild_with_luminosity(world: Path, value: float) -> None:
    """Simulate 'change input + rebuild': both stellar.yaml and catalog update."""
    _write_yaml(
        world / "layers" / "astronomy" / "input" / "stellar.yaml",
        {"stars": [{"id": "star_sol", "luminosity": value}]},
    )
    _write_yaml(
        world / "layers" / "astronomy" / "derived" / "system_catalog.yaml",
        {"stars": [{"id": "star_sol", "luminosity_sol": value}], "bodies": []},
    )


def test_fact_drifted_when_input_and_claim_change(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    fp = layer_input_fingerprint(world, None, "astronomy")
    _write_text(
        world / "design-notes" / "0001-test.md",
        f"---\nstatus: accepted\nchecked_against:\n  astronomy: {fp}\n---\n"
        "x {{ entities.star_sol.luminosity_sol }} y\n",
    )
    write_baseline(world, {"0001-test.md": {"{{ entities.star_sol.luminosity_sol }}": "1.0"}})

    _rebuild_with_luminosity(world, 2.0)

    findings = check_decision_records(world)
    kinds = {f.kind for f in findings}
    assert "input_changed" in kinds  # ② fingerprint changed
    assert "fact_drifted" in kinds  # ③ claim value drifted


def test_claims_stable_despite_input_change_no_drift(tmp_path: Path) -> None:
    """② fires but the claim renders identically → no fact_drifted (结论仍成立)."""
    world = _make_world(tmp_path)
    fp = layer_input_fingerprint(world, None, "astronomy")
    _write_text(
        world / "design-notes" / "0001-test.md",
        f"---\nstatus: accepted\nchecked_against:\n  astronomy: {fp}\n---\n"
        "x {{ entities.star_sol.luminosity_sol }} y\n",
    )
    write_baseline(world, {"0001-test.md": {"{{ entities.star_sol.luminosity_sol }}": "1.0"}})

    # Input changes, but the derived catalog (hence the rendered claim) does not
    _write_yaml(
        world / "layers" / "astronomy" / "input" / "stellar.yaml",
        {"stars": [{"id": "star_sol", "luminosity": 1.0, "note": "edited"}]},
    )

    findings = check_decision_records(world)
    assert {f.kind for f in findings} == {"input_changed"}


def test_divergence_downgrades_input_only_not_facts(tmp_path: Path) -> None:
    """GUARD-01: ``divergence: intentional`` excuses the *declared input*
    drift (②), never the drifted facts (③) — an intentional temperature
    override does not exempt unrelated dependencies."""
    world = _make_world(tmp_path)
    fp = layer_input_fingerprint(world, None, "astronomy")
    _write_text(
        world / "design-notes" / "0001-div.md",
        # NOTE: the body line is deliberately NOT an f-string — inside one,
        # ``{{`` collapses to a single brace and the template stops being a
        # template (this silently voided the ③ channel of the former test).
        f"---\nstatus: accepted\ndivergence: intentional\nchecked_against:\n"
        f"  astronomy: {fp}\n---\n"
        "x {{ entities.star_sol.luminosity_sol }} y\n",
    )
    write_baseline(world, {"0001-div.md": {"{{ entities.star_sol.luminosity_sol }}": "1.0"}})

    _rebuild_with_luminosity(world, 2.0)

    kinds = {f.kind for f in check_decision_records(world)}
    assert kinds == {"divergence", "fact_drifted"}


def test_divergence_layers_scope(tmp_path: Path) -> None:
    """With ``divergence_layers`` declared, only those layers downgrade;
    drift in any other layer still reports input_changed."""
    world = _make_world(tmp_path)
    fp = layer_input_fingerprint(world, None, "astronomy")
    _write_text(
        world / "design-notes" / "0001-div.md",
        f"---\nstatus: accepted\ndivergence: intentional\n"
        f"divergence_layers: [geological]\nchecked_against:\n"
        f"  astronomy: {fp}\n---\nbody\n",
    )
    # astronomy input changed, but only geological drift was declared intentional
    _write_yaml(
        world / "layers" / "astronomy" / "input" / "stellar.yaml",
        {"stars": [{"id": "star_sol", "luminosity": 1.0, "note": "edited"}]},
    )
    findings = check_decision_records(world)
    assert [f.kind for f in findings] == ["input_changed"]


def test_fact_drift_detected_with_same_input_fingerprint(tmp_path: Path) -> None:
    """GUARD-01 probe #1 (astra): same input fingerprint + a new engine value
    (fact 10 → 20) must report fact_drifted — ③ no longer gated on ②."""
    from unittest.mock import patch

    from dreamulator.guard import stale

    world = _make_world(tmp_path)
    fp = layer_input_fingerprint(world, None, "astronomy")
    _write_text(
        world / "design-notes" / "0001-probe.md",
        f"---\nstatus: accepted\nchecked_against:\n  astronomy: {fp}\n---\n"
        "{{ aggregates.climate.t }}\n",
    )
    write_baseline(world, {"0001-probe.md": {"{{ aggregates.climate.t }}": "10"}})

    context = {"aggregates": {"climate": {"t": 20}}}
    with (
        patch.object(stale, "build_fact_context", return_value=context),
        patch.object(stale, "layer_input_fingerprint", return_value=fp),
    ):
        findings = stale.check_decision_records(world)
    assert [f.kind for f in findings] == ["fact_drifted"]
    assert "'10' → '20'" in findings[0].detail


def test_nested_yaml_change_moves_fingerprint(tmp_path: Path) -> None:
    """GUARD-01 probe #2 (astra): authored YAML in subdirectories (conlang
    lexicons etc.) participates in the layer fingerprint."""
    world = _make_world(tmp_path)
    input_dir = world / "layers" / "civilization" / "input"
    (input_dir / "languages" / "proto").mkdir(parents=True)
    _write_text(input_dir / "top.yaml", "x: 1\n")
    nested = input_dir / "languages" / "proto" / "lexicon.yaml"
    _write_text(nested, "word: a\n")

    before = layer_input_fingerprint(world, None, "civilization")
    _write_text(nested, "word: b\n")
    after = layer_input_fingerprint(world, None, "civilization")
    assert before != after
