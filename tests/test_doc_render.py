"""Tests for dreamulator.doc_render — Jinja2 template rendering for world docs.

Covers the render_body semantics table (passthrough / degradation / source
echo), the filter set, and parse_frontmatter. The render context is now the
entity-addressed fact context (``guard/facts.py``); its loading and branch
inheritance are tested in ``test_guard_facts.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dreamulator.doc_render import (
    load_render_context,
    parse_frontmatter,
    render_body,
)

# Synthetic context for render_body semantics tests. render_body is agnostic to
# the key structure, so arbitrary role-like keys are fine here — the real
# entity-addressed fact context is exercised via test_guard_facts.py and the
# nacrea anchor tests below.
CONTEXT: dict[str, object] = {
    "body": {
        "name": "Nacrea",
        "mass_earth": 1.2,
        "gravity_m_s2": 10.282,
        "axial_tilt_deg": 9.0,
    },
    "star": {"luminosity_sol": 0.0414, "ms_lifetime_gyr": 67.2803, "evolution_progress": 0.0877},
    "orbit": {"semi_major_axis_au": 0.2504, "period_days": 67.007},
    "derived": {"solar_day_days": 3.4157, "days_per_year": 19.62, "instellation_w_m2": 898.73},
    "satellite": {"orbital_period_days": 3.2451, "tidally_locked": True},
}


# ---------------------------------------------------------------------------
# render_body — semantics table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("context", [None, CONTEXT])
def test_passthrough_without_markers(context: object) -> None:
    body = "# Title\n\nPlain markdown: 3.42 天, 67 d — no template markers at all.\n"
    text, rendered = render_body(body, context)
    assert text == body
    assert rendered is True


def test_normal_substitution() -> None:
    text, rendered = render_body("太阳日 {{ derived.solar_day_days | round2 }} 天", CONTEXT)
    assert text == "太阳日 3.42 天"
    assert rendered is True


def test_multi_section_substitution() -> None:
    template = (
        "{{ body.gravity_m_s2 | round2 }} / {{ orbit.period_days | round0 }} / "
        '{{ "%.2f" | format(body.mass_earth) }} / '
        "{{ satellite.orbital_period_days | hours | round0 }}h"
    )
    text, rendered = render_body(template, CONTEXT)
    assert text == "10.28 / 67 / 1.20 / 78h"
    assert rendered is True


def test_missing_section_echoes_full_chain() -> None:
    # Whole-section miss: the full attribute chain is echoed.
    context: dict[str, object] = {"body": {"name": "Earth"}}
    text, rendered = render_body("{{ satellite.orbital_period_days }}", context)
    assert text == "{{ satellite.orbital_period_days }}"
    assert rendered is True


def test_missing_deep_chain_does_not_crash() -> None:
    text, rendered = render_body("{{ satellite.moon.name }}", {})
    assert text == "{{ satellite.moon.name }}"
    assert rendered is True


def test_missing_key_on_existing_section_echoes_name() -> None:
    # When the parent mapping exists but the key is omitted, jinja reports
    # only the key name (the parent expression is not recoverable).
    text, rendered = render_body("{{ body.greenhouse_warming_k }}", CONTEXT)
    assert text == "{{ greenhouse_warming_k }}"
    assert rendered is True
    text, rendered = render_body("X {{ derived.nope }} Y", CONTEXT)
    assert text == "X {{ nope }} Y"
    assert rendered is True


def test_none_context_with_markers_degrades() -> None:
    body = "太阳日 {{ derived.solar_day_days }} 天"
    text, rendered = render_body(body, None)
    assert text == body
    assert rendered is False


def test_syntax_error_degrades() -> None:
    text, rendered = render_body("{{ unclosed", CONTEXT)
    assert text == "{{ unclosed"
    assert rendered is False


def test_sandbox_violation_degrades() -> None:
    text, rendered = render_body("{{ ''.__class__ }}", CONTEXT)
    assert text == "{{ ''.__class__ }}"
    assert rendered is False


def test_arithmetic_on_undefined_degrades() -> None:
    text, rendered = render_body("{{ nope + 1 }}", CONTEXT)
    assert text == "{{ nope + 1 }}"
    assert rendered is False


def test_trailing_newline_preserved() -> None:
    text, _ = render_body("x {{ body.mass_earth }}\n", CONTEXT)
    assert text == "x 1.2\n"


def test_comment_marker_counts_as_template() -> None:
    # {# ... #} marks a template: with context it is stripped by jinja.
    text, rendered = render_body("a{# comment #}b", CONTEXT)
    assert text == "ab"
    assert rendered is True


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_filter_round_values() -> None:
    assert render_body("{{ v | round0 }}", {"v": 67.007}) == ("67", True)
    assert render_body("{{ v | round1 }}", {"v": 19.62}) == ("19.6", True)
    assert render_body("{{ v | round2 }}", {"v": 3.4157}) == ("3.42", True)
    assert render_body("{{ v | round2 }}", {"v": 10.282}) == ("10.28", True)


def test_filter_hours() -> None:
    text, _ = render_body("{{ v | hours | round0 }}", {"v": 3.2451})
    assert text == "78"


def test_filter_pct() -> None:
    text, _ = render_body("{{ v | pct }}", {"v": 0.0877})
    assert text == "8.8%"


def test_builtin_format_fixed_decimals() -> None:
    text, _ = render_body('{{ "%.2f" | format(v) }}', {"v": 1.2})
    assert text == "1.20"


def test_builtin_round_precision() -> None:
    text, _ = render_body("{{ v | round(4) }}", {"v": 0.466493})
    assert text == "0.4665"


def test_filters_pass_through_undefined() -> None:
    text, rendered = render_body("{{ satellite.orbital_period_days | hours | round0 }}", {})
    assert text == "{{ satellite.orbital_period_days }}"
    assert rendered is True


def test_format_with_undefined_arg_echoes() -> None:
    text, rendered = render_body('{{ "%.2f" | format(body.mass_earth) }}', {})
    assert text == "{{ body.mass_earth }}"
    assert rendered is True


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


def test_parse_frontmatter_normal() -> None:
    text = '---\ntitle: "Doc"\ntags: [a, b]\n---\n\n# Body\n'
    fm, body = parse_frontmatter(text)
    assert fm == {"title": "Doc", "tags": ["a", "b"]}
    # The delimiter's ``\\s*`` consumes the blank line after ``---``
    # (identical regex to the previous worlds.py / export_static.py copies).
    assert body == "# Body\n"


def test_parse_frontmatter_absent() -> None:
    text = "# Just a body"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_malformed_yaml() -> None:
    text = "---\ntitle: [unclosed\n---\nbody"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == "body"


def test_frontmatter_placeholders_not_rendered() -> None:
    text = '---\ntitle: "{{ derived.solar_day_days }}"\n---\nbody {{ derived.solar_day_days }}'
    fm, body = parse_frontmatter(text)
    assert fm["title"] == "{{ derived.solar_day_days }}"  # literal, never rendered
    rendered_body, ok = render_body(body, CONTEXT)
    assert rendered_body == "body 3.4157"
    assert ok is True


# ---------------------------------------------------------------------------
# Real-world anchor tests (nacrea)
#
# These render the actual templated world documents against the committed
# ``system_catalog.yaml`` (+ summaries) via the fact context, and pin the
# rendered physical values. They mirror the authored-value anchors in
# ``test_physical_inputs.py`` and catch drift between the template
# placeholders, the filter set, and the derived data.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GAIA_WORLD = _REPO_ROOT / "data" / "worlds" / "nacrea"

_DOC_ANCHORS: dict[str, list[str]] = {
    "layers/astronomy/input/orbital_dynamics.md": [
        "| 卫星轨道倾角 i | 9.0° |",
        "南北纬 81°",
        "**33.5 天**",
        "**67 天**",
        "**3.42 天（82.0 小时）**",
        "**19.6 个**",
        "每 78h 穿过本影一次",
    ],
    "layers/geological/input/physical_params.md": [
        "1.20 M⊕",
        "1.07 R⊕（6817 km）",
        "10.28 m/s²（≈1.05g）",
        "**3.42 地球日（82.0 小时）**",
        "**67 地球日**",
        "9° / ±81°",
        "78 小时",
    ],
    "layers/astronomy/input/giant_brightness.md": [
        "**899 W/m²**",  # round0 of 898.73 (previously truncated to 898)
        "**1.91 W/m²**",
        "**约 560 倍**",  # 1.91/0.0034 ≈ 562（旧锚 1592 已过时）
    ],
    "design-notes/0001-stellar-parameters.md": [
        "0.0414 L☉",
        "0.4665 M☉",
        "3931 K",
        "67.3 Gyr",
        "0.0877",
    ],
    "layers/climate/input/long_term_cycles.md": [
        "**0.66 S⊕**",
        "日照 899 W/m²",  # drift fix: stale pre-方案2 value was 656
        "evolution_progress=0.09",  # round0/round2 of 0.0877 (was truncated 0.08)
        "67.3 Gyr 的 8.8%",
    ],
}


@pytest.mark.skipif(not _GAIA_WORLD.exists(), reason="nacrea world not present")
@pytest.mark.parametrize("rel_path", sorted(_DOC_ANCHORS))
def test_nacrea_document_renders_anchored_values(rel_path: str) -> None:
    context = load_render_context(_GAIA_WORLD)
    assert context is not None, "nacrea must have a built system_catalog.yaml"

    raw = (_GAIA_WORLD / rel_path).read_text(encoding="utf-8")
    _fm, body = parse_frontmatter(raw)
    text, rendered = render_body(body, context)

    assert rendered is True
    assert "{{" not in text, f"unresolved placeholder left in {rel_path}"
    for anchor in _DOC_ANCHORS[rel_path]:
        assert anchor in text, f"missing {anchor!r} in rendered {rel_path}"
