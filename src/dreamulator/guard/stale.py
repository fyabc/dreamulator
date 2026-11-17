"""Read-only checks of document references, authored inputs, and accepted claims.

Inputs are fingerprinted per layer. Rendered facts are compared independently
against the accepted baseline. Missing evidence and failed evaluation are
reported explicitly, while decision lifecycle writes belong to adr.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import yaml
from jinja2 import StrictUndefined
from jinja2.exceptions import TemplateError, UndefinedError

from dreamulator.doc_render import build_environment
from dreamulator.guard.facts import build_fact_context
from dreamulator.guard.storage import design_notes_dir, input_files, read_document
from dreamulator.models.layers import LAYER_ORDER, Layer

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "Finding",
    "NO_YAML_FINGERPRINT",
    "check_broken_refs",
    "check_decision_records",
    "layer_input_fingerprint",
    "read_baseline",
    "render_claims",
    "write_baseline",
]

# Extract independent expression claims for compatibility with simple baselines.
# Control-block templates use the complete rendered body instead.
_BROKEN_REF_RE = re.compile(r"\{\{[^{}]*\}\}")

# Sentinel fingerprint: the layer has an input dir but no authored ``.yaml``
# files (e.g. climate/ecology — their inputs are ``.md`` narratives +
# upstream-derived).  Distinct from ``""`` (unconfigured layer) so the two
# "nothing to hash" cases are not conflated.
NO_YAML_FINGERPRINT = "<no-yaml>"
RENDERED_BODY_KEY = "__rendered_body__"
_GUARD_ENV = build_environment()
_GUARD_ENV.undefined = StrictUndefined


def render_checked_body(body: str, context: dict[str, Any]) -> str:
    """Render strictly for validation, including references inside control blocks.

    Display rendering remains permissive. Guard checks must surface missing
    facts and syntax/filter failures instead of recording fallback text.
    """
    return _GUARD_ENV.from_string(body).render(context)


@dataclass(frozen=True)
class Finding:
    """One stale-detection finding (harness.md §7).

    ``kind`` discriminates the three levels + the intentional-divergence case.
    ``not_run`` marks a check that could NOT be performed (missing fact
    context / unbuilt world) — an empty finding list must never be displayed
    as "verified clean" when the check did not actually run (GUARD-01, astra
    proposals-review §3.3).  ``path`` is the doc/ADR path relative to the
    world root; ``layer`` is the owning layer (``None`` for design-notes /
    world-level).
    """

    kind: Literal["broken_ref", "input_changed", "fact_drifted", "divergence", "not_run"]
    path: str
    layer: str | None
    detail: str


def layer_input_fingerprint(world_dir: Path, branch: str | None, layer: Layer | str) -> str:
    """Stable fingerprint of a layer's authored YAML inputs (harness.md §7 ②).

    Hashes relative path + content of every ``input/**/*.yaml`` (recursive,
    sorted), including inherited files and parent files used by YAML merges.
    Narrative Markdown does not participate in physical input fingerprints.

    Returns:
        Hex digest; ``NO_YAML_FINGERPRINT`` when the layer has an input dir but
        no ``.yaml``/``.yml`` files anywhere under it; ``""`` when the layer has
        no effective input dir (unconfigured layer / missing input).
    """
    layer_name = layer.value if isinstance(layer, Layer) else layer
    files = input_files(world_dir, branch, layer_name)
    yaml_files = {name: paths for name, paths in files.items() if name.endswith((".yaml", ".yml"))}
    if not yaml_files:
        from dreamulator.guard.storage import scope_dirs

        configured = any(
            (scope / "layers" / layer_name / "input").exists()
            for scope in scope_dirs(world_dir, branch)
        )
        return NO_YAML_FINGERPRINT if configured else ""

    hasher = hashlib.sha256()
    for name, paths in sorted(yaml_files.items()):
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\x00")
        for index, path in enumerate(paths):
            content = path.read_bytes()
            if index:
                hasher.update(b"<inherited>\x00")
            hasher.update(content)
            hasher.update(b"\x00")
            data = yaml.safe_load(content)
            # An empty YAML override also inherits, matching load_layer_yaml.
            if data is not None and not (isinstance(data, dict) and data.get("_inherit")):
                break
    return hasher.hexdigest()


def render_claims(body: str, context: dict[str, Any]) -> dict[str, str]:
    """③ render each ``{{ ... }}`` template in a body to its current value.

    Returns ``{template: rendered_value}`` — the quantitative claims an ADR's
    conclusion depends on.  Used to diff against the baseline (see
    ``check_decision_records``).
    """
    rendered = render_checked_body(body, context)
    if "{%" in body or "{#" in body:
        # Local loop/set variables cannot be evaluated outside their template.
        return {RENDERED_BODY_KEY: rendered}
    return {
        template: render_checked_body(template, context)
        for template in _BROKEN_REF_RE.findall(body)
    }


def _baseline_path(world_dir: Path, branch: str | None = None) -> Path:
    return design_notes_dir(world_dir, branch) / ".guard-baseline.json"


def read_baseline(world_dir: Path, branch: str | None = None) -> dict[str, dict[str, str]]:
    """Read a claims baseline; reject malformed data rather than hiding it."""
    path = _baseline_path(world_dir, branch)
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read guard baseline: {exc}") from exc
    if not isinstance(data, dict) or any(
        not isinstance(name, str)
        or not isinstance(claims, dict)
        or any(not isinstance(k, str) or not isinstance(v, str) for k, v in claims.items())
        for name, claims in data.items()
    ):
        raise ValueError("Guard baseline must map record filenames to string claims")
    return data


def write_baseline(
    world_dir: Path, baseline: dict[str, dict[str, str]], branch: str | None = None
) -> None:
    """Persist claims with atomic replacement, preserving a valid file on failure."""
    from dreamulator.guard.storage import atomic_write_text, writable_design_notes_dir

    path = writable_design_notes_dir(world_dir, branch) / ".guard-baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(baseline, indent=2, ensure_ascii=False) + "\n")


def check_broken_refs(world_dir: Path, branch: str | None = None) -> list[Finding]:
    """Check effective Markdown and decision references with strict evaluation.

    Missing facts produce broken_ref. Missing context or failed evaluation
    produces not_run, so a skipped check never appears clean.
    """
    context = build_fact_context(world_dir, branch)
    if context is None:
        return [
            Finding(
                kind="not_run",
                path="-",
                layer=None,
                detail=(
                    "broken-ref scan skipped: fact context unavailable "
                    "(unbuilt world or missing/corrupt system_catalog.yaml) — "
                    "run `dreamulator build` first"
                ),
            )
        ]

    findings: list[Finding] = []

    for layer in LAYER_ORDER:
        for name, paths in sorted(input_files(world_dir, branch, layer.value).items()):
            if name.endswith(".md"):
                _scan_document(world_dir, paths[0], layer.value, context, findings)

    design_dir = design_notes_dir(world_dir, branch)
    if design_dir.exists():
        for doc in sorted(design_dir.glob("*.md")):
            _scan_document(world_dir, doc, None, context, findings)

    return findings


def check_decision_records(world_dir: Path, branch: str | None = None) -> list[Finding]:
    """② input-fingerprint drift + ③ render diff, for each ADR.

    - ② compares frontmatter ``checked_against`` (``{layer: fingerprint}``)
      against the recomputed layer fingerprint → ``input_changed``.
    - ③ re-renders the ADR's ``{{ ... }}`` claims and diffs against the
      baseline → ``fact_drifted``.  Runs **independently of ②** (GUARD-01):
      a fact can drift with the input fingerprint unchanged — e.g. a new
      engine version derives a different value from the same YAML, the exact
      case the former ``if not changed: skip`` gate missed.
    - ``divergence: intentional`` downgrades **② only** (declared creative
      divergence of the authored input), optionally scoped to the layers
      listed in ``divergence_layers``.  ③ ``fact_drifted`` is NEVER exempted:
      an intentional temperature override does not excuse drift in unrelated
      dependencies (astra proposals-review §3.3).
    - Missing fact context while checkable ADRs exist → one ``not_run``
      finding (the ③ channel could not be evaluated).
    """
    design_dir = design_notes_dir(world_dir, branch)
    if not design_dir.exists():
        return []

    context = build_fact_context(world_dir, branch)
    findings: list[Finding] = []
    try:
        baseline = read_baseline(world_dir, branch)
    except ValueError as exc:
        baseline = {}
        findings.append(Finding("not_run", "design-notes/.guard-baseline.json", None, str(exc)))

    for doc in sorted(design_dir.glob("*.md")):
        rel = doc.relative_to(world_dir).as_posix()
        try:
            fm, body = read_document(doc)
        except (ValueError, OSError) as exc:
            findings.append(Finding("not_run", rel, None, str(exc)))
            continue
        if fm.get("status") != "accepted":
            continue
        checked = fm.get("checked_against")
        if not isinstance(checked, dict) or not checked:
            findings.append(
                Finding("not_run", rel, None, "Accepted record has no input fingerprints")
            )
        else:
            divergence = fm.get("divergence") == "intentional"
            div_scope = fm.get("divergence_layers")
            for layer, recorded in checked.items():
                try:
                    current = layer_input_fingerprint(world_dir, branch, str(layer))
                except (ValueError, OSError, yaml.YAMLError) as exc:
                    findings.append(Finding("not_run", rel, str(layer), str(exc)))
                    continue
                # Older stamps serialized an empty fingerprint as YAML null.
                previous = "" if recorded is None else str(recorded)
                if current != previous:
                    scoped = divergence and (
                        div_scope is None or isinstance(div_scope, list) and str(layer) in div_scope
                    )
                    findings.append(
                        Finding(
                            "divergence" if scoped else "input_changed",
                            rel,
                            str(layer),
                            f"input changed: {previous[:8]}… → {current[:8]}…",
                        )
                    )

        if context is None:
            findings.append(
                Finding(
                    "not_run", rel, None, "Fact context unavailable; render comparison did not run"
                )
            )
            continue
        try:
            current_claims = render_claims(body, context)
        except (TemplateError, TypeError, ValueError, ArithmeticError) as exc:
            findings.append(Finding("not_run", rel, None, f"Cannot render decision claims: {exc}"))
            continue
        recorded_claims = baseline.get(doc.name)
        if recorded_claims is None:
            findings.append(Finding("not_run", rel, None, "Rendered claims baseline is missing"))
            continue
        if RENDERED_BODY_KEY in recorded_claims:
            if recorded_claims[RENDERED_BODY_KEY] != render_checked_body(body, context):
                findings.append(
                    Finding(
                        "fact_drifted",
                        rel,
                        None,
                        "Rendered decision text differs from its accepted baseline",
                    )
                )
        elif RENDERED_BODY_KEY in current_claims:
            findings.append(
                Finding(
                    "not_run", rel, None, "Control-block template needs a full rendered baseline"
                )
            )
        elif current_claims.keys() != recorded_claims.keys():
            findings.append(
                Finding(
                    "fact_drifted",
                    rel,
                    None,
                    "Decision claim set differs from its accepted baseline",
                )
            )
        else:
            for template, value in current_claims.items():
                recorded = recorded_claims[template]
                if recorded != value:
                    findings.append(
                        Finding("fact_drifted", rel, None, f"{template}: {recorded!r} → {value!r}")
                    )
    return findings


def _scan_document(
    world_dir: Path,
    doc: Path,
    layer: str | None,
    context: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Render one document and append any broken-ref findings."""
    rel = doc.relative_to(world_dir).as_posix()
    try:
        fm, body = read_document(doc)
    except (ValueError, OSError) as exc:
        findings.append(Finding("not_run", rel, layer, str(exc)))
        return
    if fm.get("status") == "deprecated" or str(fm.get("status", "")).startswith("superseded by "):
        return
    rel = doc.relative_to(world_dir).as_posix()
    try:
        render_checked_body(body, context)
    except UndefinedError as exc:
        findings.append(Finding("broken_ref", rel, layer, f"Unresolved template reference: {exc}"))
    except (TemplateError, TypeError, ValueError, ArithmeticError) as exc:
        findings.append(
            Finding("not_run", rel, layer, f"Document template could not render: {exc}")
        )
