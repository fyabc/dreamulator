"""过期检测（stale detection）——守护轴的设定溯源内核（harness.md §7）。

三级检测，从粗到精：

- **① 模板断链**：字段被删/改名 → 渲染残留 ``{{ ... }}``。``SourceUndefined`` 遇到
  缺失变量原样回显，本模块扫描渲染产物里的残留占位符。
- **② 输入指纹**：对每层 authored ``input/*.yaml`` 做稳定哈希；ADR 记录
  ``checked_against``，输入改动 → 指纹不匹配。
- **③ 渲染 diff**：ADR 的定量声明是模板，重渲染对比基线，区分「结论仍成立」vs
  「事实漂移」。

P1a 交付 ① 与 ② 的指纹函数；② 的台账比对与 ③ 在 P1b/P1c。全部纯函数、无 RNG、可单测。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from dreamulator.doc_render import parse_frontmatter, render_body
from dreamulator.guard.facts import build_fact_context
from dreamulator.models.layers import LAYER_ORDER, Layer
from dreamulator.resolver import LayerResolver

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

# Residual ``{{ ... }}`` placeholder in *rendered* output = a template reference
# whose field no longer exists (or is misspelled).  Nested braces are excluded so
# a raw ``{{ unclosed`` syntax error (no closing ``}}``) is not misreported.
# Reused for ③ claim extraction (same ``{{ ... }}`` shape).
_BROKEN_REF_RE = re.compile(r"\{\{[^{}]*\}\}")

# Sentinel fingerprint: the layer has an input dir but no authored ``.yaml``
# files (e.g. climate/ecology — their inputs are ``.md`` narratives +
# upstream-derived).  Distinct from ``""`` (unconfigured layer) so the two
# "nothing to hash" cases are not conflated.
NO_YAML_FINGERPRINT = "<no-yaml>"


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
    sorted) — GUARD-01: the former single-level glob missed authored data in
    subdirectories (e.g. a conlang ``languages/proto/lexicon.yaml``), so an
    ADR depending on it kept a stale "unchanged" fingerprint.  ``.md``
    narrative docs remain deliberately excluded — narrative edits must not
    invalidate physical conclusions (decided 2026-08-18).

    Returns:
        Hex digest; ``NO_YAML_FINGERPRINT`` when the layer has an input dir but
        no ``.yaml``/``.yml`` files anywhere under it; ``""`` when the layer has
        no effective input dir (unconfigured layer / missing input).
    """
    resolver = LayerResolver(world_dir, branch)
    input_dir = resolver.get_input_dir(layer)
    if input_dir is None or not input_dir.exists():
        return ""

    yaml_files = sorted(
        [*input_dir.glob("**/*.yaml"), *input_dir.glob("**/*.yml")],
        key=lambda p: p.relative_to(input_dir).as_posix(),
    )
    if not yaml_files:
        return NO_YAML_FINGERPRINT

    hasher = hashlib.sha256()
    for path in yaml_files:
        # Relative path (not bare name): distinguishes same-named files in
        # different subdirectories and detects moves between them.
        hasher.update(path.relative_to(input_dir).as_posix().encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(path.read_bytes())
        hasher.update(b"\x00")
    return hasher.hexdigest()


def render_claims(body: str, context: dict[str, Any]) -> dict[str, str]:
    """③ render each ``{{ ... }}`` template in a body to its current value.

    Returns ``{template: rendered_value}`` — the quantitative claims an ADR's
    conclusion depends on.  Used to diff against the baseline (see
    ``check_decision_records``).
    """
    claims: dict[str, str] = {}
    for template in _BROKEN_REF_RE.findall(body):
        text, _rendered = render_body(template, context)
        claims[template] = text
    return claims


def _baseline_path(world_dir: Path) -> Path:
    return world_dir / "design-notes" / ".guard-baseline.json"


def read_baseline(world_dir: Path) -> dict[str, dict[str, str]]:
    """Read the rendered-claims baseline (③), or ``{}`` when absent/corrupt."""
    path = _baseline_path(world_dir)
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_baseline(world_dir: Path, baseline: dict[str, dict[str, str]]) -> None:
    """Persist the rendered-claims baseline (③) — called by ``guard accept``."""
    path = _baseline_path(world_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)


def _broken_refs_in_line(line: str) -> list[str]:
    """Extract residual ``{{ ... }}`` placeholders from one rendered line."""
    return _BROKEN_REF_RE.findall(line)


def check_broken_refs(world_dir: Path, branch: str | None = None) -> list[Finding]:
    """① broken-ref detection: render every doc + ADR, report residual placeholders.

    Renders each ``layers/*/input/*.md`` and ``design-notes/*.md`` against the
    fact context; a residual ``{{ ... }}`` means a referenced field was deleted
    or renamed.  When the fact context is unavailable (unbuilt world), returns
    a single ``not_run`` finding — the check did NOT pass, it could not run
    (GUARD-01: an empty list must not read as "verified clean").
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

    resolver = LayerResolver(world_dir, branch)
    findings: list[Finding] = []

    for layer in LAYER_ORDER:
        input_dir = resolver.get_input_dir(layer)
        if input_dir is None or not input_dir.exists():
            continue
        for doc in sorted(input_dir.glob("*.md")):
            _scan_document(world_dir, doc, layer.value, context, findings)

    design_dir = world_dir / "design-notes"
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
    design_dir = world_dir / "design-notes"
    if not design_dir.exists():
        return []

    context = build_fact_context(world_dir, branch)
    baseline = read_baseline(world_dir)
    findings: list[Finding] = []
    context_missing_reported = False

    for doc in sorted(design_dir.glob("*.md")):
        raw = doc.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(raw)
        rel = f"design-notes/{doc.name}"
        divergence = fm.get("divergence") == "intentional"
        div_layers = fm.get("divergence_layers")
        div_scope: list[str] | None = (
            [str(x) for x in div_layers] if isinstance(div_layers, list) else None
        )

        # ② input fingerprint
        checked = fm.get("checked_against")
        if not isinstance(checked, dict):
            continue
        for layer, recorded in checked.items():
            current = layer_input_fingerprint(world_dir, branch, layer)
            if current != str(recorded):
                scoped = divergence and (div_scope is None or str(layer) in div_scope)
                findings.append(
                    Finding(
                        kind="divergence" if scoped else "input_changed",
                        path=rel,
                        layer=str(layer),
                        detail=f"input changed: {str(recorded)[:8]}… → {current[:8]}…",
                    )
                )

        # ③ render diff — independent of ②: same input + new engine can still
        # move the derived facts the conclusion rests on.
        if context is None:
            if not context_missing_reported:
                findings.append(
                    Finding(
                        kind="not_run",
                        path="-",
                        layer=None,
                        detail=(
                            "render-diff check skipped: fact context unavailable "
                            "(unbuilt world or missing/corrupt system_catalog.yaml)"
                        ),
                    )
                )
                context_missing_reported = True
            continue
        if doc.name not in baseline:
            continue
        recorded_claims = baseline[doc.name]
        for template, value in render_claims(body, context).items():
            recorded = recorded_claims.get(template)
            if recorded is not None and recorded != value:
                findings.append(
                    Finding(
                        kind="fact_drifted",
                        path=rel,
                        layer=None,
                        detail=f"{template}: {recorded!r} → {value!r}",
                    )
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
    raw = doc.read_text(encoding="utf-8")
    _fm, body = parse_frontmatter(raw)
    text, rendered = render_body(body, context)
    if not rendered:
        # Context was present (checked by caller) but the template failed to
        # render (syntax error / sandbox violation) — a different kind of issue,
        # not a broken field reference.
        return

    # as_posix(): stable forward-slash paths regardless of host OS separator.
    rel = doc.relative_to(world_dir).as_posix()
    for line_no, line in enumerate(text.splitlines(), 1):
        for marker in _broken_refs_in_line(line):
            findings.append(
                Finding(
                    kind="broken_ref",
                    path=rel,
                    layer=layer,
                    detail=f"line {line_no}: unresolved {marker}",
                )
            )
