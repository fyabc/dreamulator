"""Jinja2 template rendering for world markdown documents (roadmap #22 ②).

World documents (``layers/*/input/*.md`` and ``design-notes/*.md``) may embed
``{{ ... }}`` placeholders referencing the single source of truth for world
facts: the entity-addressed fact context built by
``guard/facts.py::build_fact_context`` (``system_catalog.yaml`` + per-layer
``*_summary.yaml``, see ``docs/design/harness.md`` §5). Entities are keyed by
stable ID (``{{ entities.satellite_gaiam.axial_tilt_deg }}``); per-layer
aggregates live under ``aggregates.climate`` / ``.ecology`` / ``.civilization``.

Design decisions:

- Templates are the only git-tracked source. Rendering happens **at read
  time** (API endpoints) and **at static-export time** — rendered output is
  never persisted, so it can never drift from the derived data.
- Branch inheritance works automatically: a branch inherits its parent's
  templates but renders against its own derived data when built.
- Missing context (fresh clone, branch never built) degrades to returning the
  raw template with ``rendered=False``; missing individual variables echo
  their source form (``{{ path }}``) instead of crashing.

See ``docs/worldbuilding/design_patterns.md`` (pattern: 文档模板渲染).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Literal

import yaml
from jinja2 import ChainableUndefined, Undefined
from jinja2.exceptions import SecurityError, TemplateError
from jinja2.filters import do_format, do_round
from jinja2.sandbox import SandboxedEnvironment
from jinja2.utils import missing

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "SourceUndefined",
    "build_environment",
    "load_render_context",
    "parse_frontmatter",
    "render_body",
]

# Any of these markers marks a body as a template. ``{#`` is included so a
# jinja comment cannot be silently stripped from an "untemplated" document.
_TEMPLATE_MARKERS = ("{{", "{%", "{#")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown string.

    Returns ``(frontmatter_dict, body_without_frontmatter)``.
    If no frontmatter found (or it is malformed), returns ``({}, original_text)``
    or ``({}, body)`` respectively. The frontmatter itself is never rendered;
    placeholders are only meaningful in the body.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    try:
        fm = yaml.safe_load(match.group(1))
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        fm = {}
    return fm, match.group(2)


class SourceUndefined(ChainableUndefined):
    """Undefined that echoes its source form ``{{ path }}`` in the output.

    Unlike ``ChainableUndefined`` (which returns ``self`` on attribute access
    and thus loses the path), this class tracks the access chain, so a
    reference into a missing section — e.g. ``{{ satellite.orbital_period_days }}``
    on a world without a satellite — echoes the full literal source path
    instead of raising. Sandbox violations (created with ``exc=SecurityError``)
    raise on stringification so ``render_body`` degrades to the raw template
    rather than echoing the security message into the document.
    """

    __slots__ = ()

    def _source_path(self) -> str:
        return str(self._undefined_hint or self._undefined_name or "")

    def __getattr__(self, name: str) -> SourceUndefined:
        # Dunder probing (copy/pickle protocols etc.) must raise AttributeError.
        if name[:2] == "__" and name[-2:] == "__":
            raise AttributeError(name)
        return self.__class__(
            hint=f"{self._source_path()}.{name}",
            obj=missing,
            name=name,
            exc=self._undefined_exception,
        )

    # jinja2 declares ``Undefined.__getitem__`` as the never-returning failure
    # stub; our override returns a chained undefined instead.
    def __getitem__(self, key: Any) -> SourceUndefined:  # type: ignore[override]
        return self.__class__(
            hint=f"{self._source_path()}[{key!r}]",
            obj=missing,
            name=str(key),
            exc=self._undefined_exception,
        )

    def __str__(self) -> str:
        if self._undefined_exception is SecurityError:
            raise SecurityError(self._undefined_hint or "unsafe attribute access")
        return "{{ " + self._source_path() + " }}"


def _round0(value: Any) -> Any:
    """Round to integer (67.007 → 67)."""
    if isinstance(value, Undefined):
        return value
    return round(float(value))


def _round1(value: Any) -> Any:
    """Round to 1 decimal (19.62 → 19.6)."""
    if isinstance(value, Undefined):
        return value
    return round(float(value), 1)


def _round2(value: Any) -> Any:
    """Round to 2 decimals (3.4157 → 3.42)."""
    if isinstance(value, Undefined):
        return value
    return round(float(value), 2)


def _hours(value: Any) -> Any:
    """Convert days to hours (combine with round filters: ``| hours | round0``)."""
    if isinstance(value, Undefined):
        return value
    return float(value) * 24.0


def _pct(value: Any) -> Any:
    """Render a fraction as a percent string (0.0877 → "8.8%")."""
    if isinstance(value, Undefined):
        return value
    return f"{round(float(value) * 100.0, 1)}%"


def _format_filter(value: Any, *args: Any, **kwargs: Any) -> Any:
    """Builtin ``format`` with Undefined passthrough (``"%.2f"|format(...)``).

    If the format string or any argument is undefined, the first undefined
    value is returned so it echoes as its source path instead of crashing
    inside the ``%`` operation.
    """
    if isinstance(value, Undefined):
        return value
    for arg in args:
        if isinstance(arg, Undefined):
            return arg
    for arg in kwargs.values():
        if isinstance(arg, Undefined):
            return arg
    return do_format(value, *args, **kwargs)


def _round_filter(
    value: Any, precision: int = 0, method: Literal["common", "ceil", "floor"] = "common"
) -> Any:
    """Builtin ``round`` with Undefined passthrough."""
    if isinstance(value, Undefined):
        return value
    return do_round(value, precision, method)


def build_environment() -> SandboxedEnvironment:
    """Build the sandboxed Jinja2 environment used for document rendering.

    No loader is configured: templates are always rendered from strings via
    ``from_string``. Autoescape is off because the output is markdown, not HTML.
    """
    env = SandboxedEnvironment(
        undefined=SourceUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        auto_reload=False,
    )
    env.filters.update(
        {
            "round0": _round0,
            "round1": _round1,
            "round2": _round2,
            "hours": _hours,
            "pct": _pct,
            # Builtin overrides: Undefined passthrough instead of crashing.
            "format": _format_filter,
            "round": _round_filter,
        }
    )
    return env


# Module-level singleton: the environment is immutable after filter
# registration and safe to share across threads (API workers, export script).
_ENV = build_environment()


def load_render_context(world_dir: Path, branch: str | None = None) -> dict[str, Any] | None:
    """Load the render context for a world/branch.

    Delegates to :func:`~dreamulator.guard.facts.build_fact_context` — the fact
    context is now the entity-addressed materialized view over
    ``system_catalog.yaml`` + per-layer ``*_summary.yaml`` (harness.md §5),
    replacing the role-keyed ``world_parameters.yaml``. A branch that overrides
    astronomy input but has no built derived directory gets ``None`` — it must
    NOT silently fall back to the root world's data, which may describe a
    different star system.

    Returns:
        The ``{"entities", "aggregates", "spatial"}`` fact context, or ``None``
        when unavailable (fresh clone, branch never built, missing/corrupt file).
    """
    from dreamulator.guard import build_fact_context

    return build_fact_context(world_dir, branch)


def render_body(body: str, context: Mapping[str, Any] | None) -> tuple[str, bool]:
    """Render a markdown body template against the world parameter context.

    Returns ``(text, rendered)`` where ``rendered`` indicates whether ``text``
    is the final rendered output (``True``) or the raw template returned as a
    degradation (``False``).

    Semantics:

    - No template markers → passthrough, ``rendered=True`` (even if context
      is ``None``).
    - Markers present but context is ``None`` → raw template, ``rendered=False``.
    - Missing individual variables → the source form ``{{ path }}`` is echoed;
      ``rendered`` is still ``True`` (rendering succeeded, data is incomplete).
    - Template syntax errors / sandbox violations / filter type errors →
      raw template + warning log, ``rendered=False``.
    """
    if not any(marker in body for marker in _TEMPLATE_MARKERS):
        return body, True
    if context is None:
        return body, False

    try:
        template = _ENV.from_string(body)
        # Positional mapping argument on purpose: the context contains a
        # top-level "body" key that would collide with a keyword argument.
        rendered = template.render(context)
    except (TemplateError, TypeError, ValueError) as exc:
        logger.warning("Document template rendering failed, returning raw body: %s", exc)
        return body, False
    return rendered, True
