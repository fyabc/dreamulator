"""Tests for habitability — 宜居海岸 / 农业核心区 classification."""

import pytest

from dreamulator.engine.habitability import (
    COAST_THRESHOLD_KM,
    P_MIN_MM,
    T_MIN_C,
    TREE_LINE_C,
    agriculture_score,
    classify_agricultural_core,
    classify_habitable_coast,
    habitability_score,
)

# ---------------------------------------------------------------------------
# 宜居海岸 (habitable coast)
# ---------------------------------------------------------------------------

HABITABLE_CASES: list[tuple[float | None, float | None, float | None, bool, bool]] = [
    # (T_annual, P_annual, dist_to_coast, is_ocean, expected)
    (15.0, 800.0, 50.0, False, True),  # warm, wet, coastal
    (15.0, 800.0, 199.0, False, True),  # just inside threshold
    (15.0, 800.0, 200.0, False, True),  # boundary: <= threshold
    (15.0, 800.0, 200.1, False, False),  # just beyond threshold
    (15.0, 800.0, 50.0, True, False),  # ocean → never habitable
    (0.0, 800.0, 50.0, False, False),  # boundary: T=0 not >0
    (-1.0, 800.0, 50.0, False, False),  # frozen
    (15.0, 500.0, 50.0, False, False),  # boundary: P=500 not >500
    (15.0, 499.0, 50.0, False, False),  # semi-arid
    (None, 800.0, 50.0, False, False),  # missing T
    (15.0, None, 50.0, False, False),  # missing P
    (15.0, 800.0, None, False, False),  # missing distance (treated interior)
]


@pytest.mark.parametrize("t, p, dist, ocean, expected", HABITABLE_CASES)
def test_classify_habitable_coast(
    t: float | None,
    p: float | None,
    dist: float | None,
    ocean: bool,
    expected: bool,
) -> None:
    assert classify_habitable_coast(t, p, dist, is_ocean=ocean) == expected


def test_habitable_coast_threshold_overrides() -> None:
    """Thresholds are overridable via keyword args."""
    # Below default T_MIN_C but above a lowered override.
    assert classify_habitable_coast(-2.0, 800.0, 50.0) is False
    assert classify_habitable_coast(-2.0, 800.0, 50.0, t_min_c=-5.0) is True
    # Below default P_MIN_MM but above a lowered override.
    assert classify_habitable_coast(15.0, 400.0, 50.0) is False
    assert classify_habitable_coast(15.0, 400.0, 50.0, p_min_mm=300.0) is True
    # Outside default coast threshold but inside a widened override.
    assert classify_habitable_coast(15.0, 800.0, 500.0) is False
    assert classify_habitable_coast(15.0, 800.0, 500.0, coast_threshold_km=600.0) is True


# ---------------------------------------------------------------------------
# 农业核心区 (agricultural core)
# ---------------------------------------------------------------------------

AGRICULTURAL_CASES: list[tuple[float | None, bool, bool]] = [
    # (t_hot, is_ocean, expected)
    (12.0, False, True),  # above tree-line
    (10.0, False, False),  # boundary: =10 not >10
    (9.9, False, False),  # below tree-line (polar ET)
    (0.0, False, False),  # frozen
    (-5.0, False, False),
    (None, False, False),  # missing t_hot
    (15.0, True, False),  # ocean → never agricultural
]


@pytest.mark.parametrize("t_hot, ocean, expected", AGRICULTURAL_CASES)
def test_classify_agricultural_core(
    t_hot: float | None,
    ocean: bool,
    expected: bool,
) -> None:
    assert classify_agricultural_core(t_hot, is_ocean=ocean) == expected


def test_agricultural_core_threshold_override() -> None:
    assert classify_agricultural_core(8.0) is False
    assert classify_agricultural_core(8.0, tree_line_c=7.0) is True


# ---------------------------------------------------------------------------
# 定居 vs 农业 两条线 (Faroese/Inuit-type cool-wet oceanic ET)
# ---------------------------------------------------------------------------


def test_cool_wet_oceanic_et_is_habitable_but_not_agricultural() -> None:
    """凉湿海洋性 ET: settleable (T>0, wet, coastal) but NOT farmable (t_hot<10)."""
    # Annual T above freezing, wet, coastal → habitable coast.
    assert classify_habitable_coast(5.0, 800.0, 30.0) is True
    # But hottest month below the 10°C tree-line → not agricultural.
    assert classify_agricultural_core(8.0) is False


def test_cradle_is_both_habitable_and_agricultural() -> None:
    """Coastal warm-wet cell is the civilisation 'cradle' — both layers true."""
    assert classify_habitable_coast(18.0, 1200.0, 40.0) is True
    assert classify_agricultural_core(22.0) is True


def test_dry_inland_et_is_neither() -> None:
    """温和但干 inland ET: too dry to settle, too cold to farm."""
    # Dry (P < 500) and interior (dist > threshold) → not habitable coast.
    assert classify_habitable_coast(5.0, 200.0, 1500.0) is False
    assert classify_agricultural_core(8.0) is False


def test_inland_warm_farm_is_agricultural_but_not_habitable_coast() -> None:
    """Inland warm land: farmable, but outside the coastal threshold."""
    assert classify_habitable_coast(18.0, 900.0, 1500.0) is False
    assert classify_agricultural_core(22.0) is True


# ---------------------------------------------------------------------------
# Constants are the documented roadmap-spec values
# ---------------------------------------------------------------------------


def test_threshold_constants_match_roadmap_spec() -> None:
    assert T_MIN_C == 0.0
    assert P_MIN_MM == 500.0
    assert COAST_THRESHOLD_KM == 200.0
    assert TREE_LINE_C == 10.0


# ---------------------------------------------------------------------------
# 宜居等级 (habitability_score)
# ---------------------------------------------------------------------------


def test_habitability_score_niche_peak_is_high() -> None:
    # MAT ~13 °C + wet → the human climate niche centre → high.
    assert habitability_score(13.0, 1000.0) > 80.0


def test_habitability_score_ocean_and_missing_are_zero() -> None:
    assert habitability_score(13.0, 1000.0, is_ocean=True) == 0.0
    assert habitability_score(None, 1000.0) == 0.0
    assert habitability_score(13.0, None) == 0.0


def test_habitability_score_cold_side_declines_steeply() -> None:
    # T = −5 °C is ~3σ below the niche centre → near zero.
    assert habitability_score(-5.0, 1000.0) < 5.0
    # T = 7 °C is ~1σ below → mid-range.
    assert 30.0 < habitability_score(7.0, 1000.0) < 80.0


def test_habitability_score_hot_side_declines_gently() -> None:
    # Hot side is wide (secondary tropical cluster): T = 30 °C still scores ~64.
    assert habitability_score(30.0, 1000.0) > 40.0


def test_habitability_score_dry_is_low() -> None:
    # Arid: f_P = 100/500 = 0.2 → score = 20.
    assert habitability_score(13.0, 100.0) < 25.0


def test_habitability_score_asymmetric_band() -> None:
    # Same distance from the centre: cold side scores lower than hot side.
    cold = habitability_score(3.0, 1000.0)  # 10 °C below centre
    hot = habitability_score(23.0, 1000.0)  # 10 °C above centre
    assert cold < hot


# ---------------------------------------------------------------------------
# 农业等级 (agriculture_score)
# ---------------------------------------------------------------------------


def test_agriculture_score_hard_zero_below_tree_line() -> None:
    assert agriculture_score(8.0, 1000.0, "high") == 0.0
    assert agriculture_score(10.0, 1000.0, "high") == 0.0  # boundary: =10 not >10


def test_agriculture_score_full_at_warm_wet_fertile() -> None:
    assert agriculture_score(25.0, 1000.0, "high") == 100.0


def test_agriculture_score_factors() -> None:
    # Dry halves the water factor: 100 × 1 × 0.5 × 1 = 50.
    assert agriculture_score(25.0, 500.0, "high") == 50.0
    # Low fertility quarters it: 100 × 1 × 1 × 0.25 = 25.
    assert agriculture_score(25.0, 1000.0, "low") == 25.0
    # Missing fertility defaults to neutral 0.5.
    assert agriculture_score(25.0, 1000.0, None) == 50.0


def test_agriculture_score_ocean_and_missing_are_zero() -> None:
    assert agriculture_score(25.0, 1000.0, "high", is_ocean=True) == 0.0
    assert agriculture_score(None, 1000.0, "high") == 0.0
