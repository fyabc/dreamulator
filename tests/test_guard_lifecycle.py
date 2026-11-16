"""End-to-end guard evidence, decision lifecycle, and branch isolation probes."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
import yaml
from typer.testing import CliRunner

from dreamulator.cli import app
from dreamulator.guard.adr import accept, archive, count_accepted, deprecate, supersede
from dreamulator.guard.stale import (
    check_broken_refs,
    check_decision_records,
    layer_input_fingerprint,
    read_baseline,
)

if TYPE_CHECKING:
    from pathlib import Path

CLAIM = "Luminosity is {{ entities.star_sol.luminosity_sol }} solar units.\n"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def catalog(scope: Path, luminosity: float) -> None:
    write(
        scope / "layers/astronomy/derived/system_catalog.yaml",
        yaml.safe_dump({"stars": [{"id": "star_sol", "luminosity_sol": luminosity}]}),
    )


def decision(scope: Path, name: str = "0001-star.md", body: str = CLAIM) -> Path:
    path = scope / "design-notes" / name
    write(path, "---\nstatus: proposed\n---\n" + body)
    return path


@pytest.fixture
def world(tmp_path: Path) -> Path:
    root = tmp_path / "probe"
    write(root / "world.yaml", "name: probe\n")
    write(root / "layers/astronomy/input/stellar.yaml", "stars: []\n")
    catalog(root, 1.0)
    decision(root)
    return root


def branch(world: Path, name: str = "variant", *, parent: str | None = None) -> Path:
    scope = world / "branches" / name
    write(
        scope / "branch.yaml",
        yaml.safe_dump({"name": name, "fork_layer": "astronomy", "parent": parent}),
    )
    write(scope / "layers/astronomy/input/stellar.yaml", "stars: []\n")
    catalog(scope, 2.0)
    return scope


def snapshot(world: Path) -> dict[str, bytes]:
    return {
        p.relative_to(world).as_posix(): p.read_bytes() for p in world.rglob("*") if p.is_file()
    }


def test_accept_then_check_is_clean_with_unconfigured_layers(world: Path) -> None:
    accept(world, None, "0001")
    assert check_broken_refs(world) == []
    assert check_decision_records(world) == []
    fm = yaml.safe_load(
        (world / "design-notes/0001-star.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert fm["checked_against"]["physics"] == ""


@pytest.mark.parametrize("damage", ["missing", "syntax", "shape", "entry", "value"])
def test_baseline_damage_is_incomplete(world: Path, damage: str) -> None:
    accept(world, None, "0001")
    path = world / "design-notes/.guard-baseline.json"
    if damage == "missing":
        path.unlink()
    else:
        write(
            path,
            {
                "syntax": "{",
                "shape": "[]",
                "entry": '{"0001-star.md": []}',
                "value": '{"0001-star.md": {"x": 1}}',
            }[damage],
        )
    assert "not_run" in {f.kind for f in check_decision_records(world)}


@pytest.mark.parametrize(
    "body",
    [
        "{{ entities.star_sol.absent }}",
        "{{ entities.star_sol.luminosity_sol",
        "{{ entities.star_sol.luminosity_sol | not_a_filter }}",
        "{{ 1 / 0 }}",
        "{{ entities.star_sol.luminosity_sol | round1 }}\n{% if missing %}yes{% endif %}",
    ],
)
def test_failed_accept_leaves_every_file_unchanged(world: Path, body: str) -> None:
    decision(world, body=body)
    before = snapshot(world)
    with pytest.raises(ValueError, match="cannot be verified"):
        accept(world, None, "0001")
    assert snapshot(world) == before
    assert check_broken_refs(world)


def test_accept_without_catalog_leaves_record_proposed(world: Path) -> None:
    (world / "layers/astronomy/derived/system_catalog.yaml").unlink()
    before = snapshot(world)
    with pytest.raises(ValueError, match="Fact context unavailable"):
        accept(world, None, "0001")
    assert snapshot(world) == before


def test_same_input_new_facts_cannot_be_reaccepted(world: Path) -> None:
    accept(world, None, "0001")
    fp = layer_input_fingerprint(world, None, "astronomy")
    catalog(world, 3.0)
    assert layer_input_fingerprint(world, None, "astronomy") == fp
    assert [f.kind for f in check_decision_records(world)] == ["fact_drifted"]
    before = snapshot(world)
    with pytest.raises(ValueError, match="needs review"):
        accept(world, None, "0001")
    assert snapshot(world) == before


def test_unchanged_reaccept_is_noop(world: Path) -> None:
    accept(world, None, "0001", limit=1)
    before = snapshot(world)
    accept(world, None, "0001", limit=1)
    assert snapshot(world) == before


@pytest.mark.parametrize(
    "body",
    [
        "{% for star in entities.values() %}{{ star.luminosity_sol }}{% endfor %}",
        "{% if entities.star_sol.luminosity_sol > 1.5 %}bright{% else %}dim{% endif %}",
    ],
)
def test_control_blocks_use_full_rendered_baseline(world: Path, body: str) -> None:
    decision(world, body=body)
    accept(world, None, "0001")
    assert check_decision_records(world) == []
    catalog(world, 2.0)
    assert [f.kind for f in check_decision_records(world)] == ["fact_drifted"]


def test_literal_template_examples_are_valid(world: Path) -> None:
    decision(world, body="{% raw %}Example: {{ absent.field }}{% endraw %}")
    accept(world, None, "0001")
    assert check_broken_refs(world) == []
    assert check_decision_records(world) == []


def test_removed_claim_is_drift(world: Path) -> None:
    path = accept(world, None, "0001")
    write(path, path.read_text(encoding="utf-8").replace(CLAIM, "Conclusion has no value now.\n"))
    assert [f.kind for f in check_decision_records(world)] == ["fact_drifted"]


def test_archived_accepted_records_still_detect_drift(world: Path) -> None:
    accept(world, None, "0001")
    archive(world, limit=0)
    assert count_accepted(world) == 0
    catalog(world, 2.0)
    assert [f.kind for f in check_decision_records(world)] == ["fact_drifted"]


def test_retired_record_does_not_block_active_ledger(world: Path) -> None:
    accept(world, None, "0001")
    deprecate(world, "0001")
    catalog(world, 2.0)
    assert check_decision_records(world) == []
    assert check_broken_refs(world) == []
    with pytest.raises(ValueError, match="retired record"):
        accept(world, None, "0001")


def test_supersede_requires_existing_accepted_successor(world: Path) -> None:
    accept(world, None, "0001")
    before = snapshot(world)
    with pytest.raises(FileNotFoundError):
        supersede(world, "0001", "0002")
    with pytest.raises(ValueError, match="itself"):
        supersede(world, "0001", "0001")
    assert snapshot(world) == before
    decision(world, "0002-new.md")
    with pytest.raises(ValueError, match="accepted first"):
        supersede(world, "0001", "0002")
    accept(world, None, "0002")
    supersede(world, "0001", "0002")
    assert check_decision_records(world) == []


def test_branch_accept_requires_local_ledger(world: Path) -> None:
    accept(world, None, "0001")
    branch(world)
    before = snapshot(world)
    with pytest.raises(ValueError, match="copy the records"):
        accept(world, "variant", "0001")
    assert snapshot(world) == before
    assert "fact_drifted" in {f.kind for f in check_decision_records(world, "variant")}


def test_branch_ledger_and_baseline_do_not_change_root(world: Path) -> None:
    accept(world, None, "0001")
    root_record = (world / "design-notes/0001-star.md").read_bytes()
    root_baseline = (world / "design-notes/.guard-baseline.json").read_bytes()
    scope = branch(world)
    decision(scope)
    accept(world, "variant", "0001")
    assert check_decision_records(world, "variant") == []
    assert check_decision_records(world) == []
    catalog(scope, 3.0)
    assert [f.kind for f in check_decision_records(world, "variant")] == ["fact_drifted"]
    assert check_decision_records(world) == []
    deprecate(world, "0001", "variant")
    assert (world / "design-notes/0001-star.md").read_bytes() == root_record
    assert (world / "design-notes/.guard-baseline.json").read_bytes() == root_baseline


def test_branch_copied_accepted_record_cannot_overwrite_baseline(world: Path) -> None:
    accept(world, None, "0001")
    scope = branch(world)
    shutil.copytree(world / "design-notes", scope / "design-notes")
    before = snapshot(world)
    with pytest.raises(ValueError, match="needs review"):
        accept(world, "variant", "0001")
    assert snapshot(world) == before


def test_parent_inputs_are_tracked_despite_branch_override(world: Path) -> None:
    branch(world)
    inherited = world / "layers/astronomy/input/nested/satellite.yml"
    write(inherited, "period_days: 2\n")
    before = layer_input_fingerprint(world, "variant", "astronomy")
    write(inherited, "period_days: 3\n")
    assert layer_input_fingerprint(world, "variant", "astronomy") != before


def test_inherit_merge_tracks_parent_but_full_override_does_not(world: Path) -> None:
    scope = branch(world)
    parent = world / "layers/astronomy/input/stellar.yaml"
    child = scope / "layers/astronomy/input/stellar.yaml"
    write(child, "_inherit: true\nstars: []\n")
    before = layer_input_fingerprint(world, "variant", "astronomy")
    write(parent, "stars: []\nother: 1\n")
    assert layer_input_fingerprint(world, "variant", "astronomy") != before
    write(child, "stars: []\n")
    before = layer_input_fingerprint(world, "variant", "astronomy")
    write(parent, "stars: []\nother: 2\n")
    assert layer_input_fingerprint(world, "variant", "astronomy") == before


def test_nested_inherited_markdown_is_checked(world: Path) -> None:
    branch(world)
    write(world / "layers/astronomy/input/notes/facts.md", "{{ entities.star_sol.missing }}")
    findings = check_broken_refs(world, "variant")
    assert [f.kind for f in findings] == ["broken_ref"]
    assert findings[0].path == "layers/astronomy/input/notes/facts.md"


@pytest.mark.parametrize(
    "metadata", ["status: [", "- accepted", 'status: accepted\narchived: "false"']
)
def test_invalid_frontmatter_is_incomplete(world: Path, metadata: str) -> None:
    write(world / "design-notes/0001-star.md", "---\n" + metadata + "\n---\n" + CLAIM)
    assert "not_run" in {f.kind for f in check_decision_records(world)}
    before = snapshot(world)
    with pytest.raises(ValueError):
        accept(world, None, "0001")
    assert snapshot(world) == before


def test_malformed_divergence_scope_does_not_exempt_other_inputs(world: Path) -> None:
    path = accept(world, None, "0001")
    write(
        path,
        path.read_text(encoding="utf-8").replace(
            "status: accepted",
            "status: accepted\ndivergence: intentional\ndivergence_layers: astronomy",
        ),
    )
    write(world / "layers/astronomy/input/stellar.yaml", "stars: []\nother: 1\n")
    assert "input_changed" in {f.kind for f in check_decision_records(world)}


def run_check(world: Path, *extra: str) -> tuple[int, str]:
    result = CliRunner().invoke(
        app,
        ["guard", "check", "probe", "--data-dir", str(world.parent), *extra],
        terminal_width=160,
    )
    return result.exit_code, result.output


def test_cli_exit_status_matches_complete_stale_and_incomplete(world: Path) -> None:
    accept(world, None, "0001")
    code, output = run_check(world)
    assert code == 0 and "checks passed" in output
    catalog(world, 2.0)
    code, output = run_check(world)
    assert code == 1 and "fact_drifted" in output
    (world / "design-notes/.guard-baseline.json").unlink()
    code, output = run_check(world)
    assert code == 2 and "not_run" in output and "checks passed" not in output
    code, output = run_check(world, "--branch", "missing")
    assert code == 2 and "could not run" in output


def test_cli_declared_input_change_is_info_but_fact_change_is_stale(world: Path) -> None:
    path = accept(world, None, "0001")
    write(
        path,
        path.read_text(encoding="utf-8").replace(
            "status: accepted",
            "status: accepted\ndivergence: intentional\ndivergence_layers: [astronomy]",
        ),
    )
    write(world / "layers/astronomy/input/stellar.yaml", "stars: []\nother: 1\n")
    assert run_check(world)[0] == 0
    catalog(world, 2.0)
    assert run_check(world)[0] == 1


def test_baseline_replace_failure_preserves_prior_file(
    world: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dreamulator.guard import storage
    from dreamulator.guard.stale import write_baseline

    accept(world, None, "0001")
    before = snapshot(world)

    def fail_replace(src: object, dst: object) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failure"):
        write_baseline(world, {"other.md": {"x": "y"}})
    assert snapshot(world) == before
    assert read_baseline(world)


def test_missing_baseline_for_plain_record_is_incomplete(world: Path) -> None:
    decision(world, body="This decision has no formula.\n")
    accept(world, None, "0001")
    (world / "design-notes/.guard-baseline.json").unlink()
    assert [f.kind for f in check_decision_records(world)] == ["not_run"]


def test_invalid_status_type_is_incomplete_and_cannot_be_accepted(world: Path) -> None:
    decision(world)
    path = world / "design-notes/0001-star.md"
    write(path, "---\nstatus: [accepted]\n---\n" + CLAIM)
    assert [f.kind for f in check_decision_records(world)] == ["not_run"]
    with pytest.raises(ValueError, match="status field"):
        accept(world, None, "0001")


def test_legacy_null_empty_fingerprint_is_compatible(world: Path) -> None:
    path = accept(world, None, "0001")
    text = path.read_text(encoding="utf-8").replace("physics: ''", "physics:")
    write(path, text)
    assert check_decision_records(world) == []
