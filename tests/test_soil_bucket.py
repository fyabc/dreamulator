"""Soil-water bucket (CLIM-02, astra §2.3): cross-month land water memory.

The pure-function contract: exact per-cell monthly balance P = E + R + ΔS,
periodic steady state (ΣΔS over the reported year = 0), dry-season drawdown,
capacity overflow, and the degenerate no-memory limit.
"""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.engine.climate_physics import soil_bucket_monthly


def _seasonal_forcing(n: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Wet-season / dry-season forcing: P in months 0-5, E_pot all year."""
    p = np.zeros((n, 12))
    p[:, 0:6] = 100.0  # wet season: 100 mm/month
    e_pot = np.full((n, 12), 50.0)  # 50 mm/month potential, year-round
    return p, e_pot


class TestSoilBucketContract:
    def test_monthly_water_balance_exact(self):
        """P = E + R + ΔS every month; at periodic steady state the reported
        year closes: ΣP = ΣE + ΣR."""
        p, e_pot = _seasonal_forcing()
        e, r, cycles, ds = soil_bucket_monthly(p, e_pot, capacity_mm=150.0)
        assert ds < 0.05
        # Per-cell annual closure (ΔS over the converged cycle ≈ 0).
        np.testing.assert_allclose(
            p.sum(axis=1), e.sum(axis=1) + r.sum(axis=1), atol=cycles * ds + 1e-9
        )

    def test_dry_season_draws_on_store(self):
        """A dry month following the wet season still evaporates — from the
        store, not from rain (the memory the memoryless Budyko lacked)."""
        p, e_pot = _seasonal_forcing()
        e, r, _, _ = soil_bucket_monthly(p, e_pot, capacity_mm=150.0)
        # Dry-season months (6-11) have P = 0 but E > 0 while the store lasts.
        assert e[0, 6] > 0.0
        # And the store eventually depletes: late dry season < potential
        # only after exhaustion — with 150 mm store and 50 mm/month demand
        # it runs dry in month 9, so E must fall below E_pot there.
        assert e[0, 11] < 50.0

    def test_humid_no_memory_case_matches_pot(self):
        """Perpetually wet (P ≥ E_pot every month): E = E_pot exactly, the
        store never limits — the bucket adds no artificial stress."""
        p = np.full((2, 12), 200.0)
        e_pot = np.full((2, 12), 50.0)
        e, r, _, ds = soil_bucket_monthly(p, e_pot, capacity_mm=150.0)
        np.testing.assert_allclose(e, 50.0)
        # Overflow: 200 − 50 = 150 inflow/month, store pinned at C → R = 150.
        np.testing.assert_allclose(r, 150.0, atol=1e-9)
        assert ds < 0.05

    def test_overflow_caps_store(self):
        """Extreme rain: store saturates at C, everything above is runoff."""
        p = np.full((1, 12), 1000.0)
        e_pot = np.full((1, 12), 10.0)
        e, r, _, _ = soil_bucket_monthly(p, e_pot, capacity_mm=100.0)
        np.testing.assert_allclose(e, 10.0)
        np.testing.assert_allclose(r, 990.0, atol=1e-9)

    def test_tiny_capacity_is_memoryless(self):
        """C → 0 degenerates to E = min(E_pot, P) per month (no carry-over)."""
        p, e_pot = _seasonal_forcing()
        e, _, _, _ = soil_bucket_monthly(p, e_pot, capacity_mm=1e-9)
        expected = np.minimum(e_pot, p)
        np.testing.assert_allclose(e, expected, atol=1e-6)

    def test_periodic_steady_state_converges(self):
        """Even with strong seasonality the cycle iteration closes on itself."""
        p = np.zeros((2, 12))
        p[:, 4:8] = 300.0  # extreme 4-month monsoon
        e_pot = np.full((2, 12), 80.0)
        _, _, cycles, ds = soil_bucket_monthly(p, e_pot, capacity_mm=200.0)
        assert ds < 0.05
        assert cycles < 24

    def test_invalid_inputs_raise(self):
        p, e_pot = _seasonal_forcing()
        with pytest.raises(ValueError, match="shape mismatch"):
            soil_bucket_monthly(p, e_pot[:, :6], capacity_mm=150.0)
        with pytest.raises(ValueError, match="capacity_mm"):
            soil_bucket_monthly(p, e_pot, capacity_mm=0.0)


class TestSoilBucketIntegration:
    def test_bucket_changes_land_et_and_conserves(self):
        """In the full simulator the bucket pass must (a) actually change the
        land water cycle vs the memoryless Budyko pass and (b) keep the final
        field on the conserved budget (ΣA·P core identity per solve)."""
        from dreamulator.map.climate_simulator import simulate_climate
        from dreamulator.map.pipeline_types import TerrainPipelineConfig
        from tests.test_climate_simulator import _build_test_mesh

        results = {}
        for enabled in (False, True):
            mesh = _build_test_mesh(num_bands=10, cells_per_band=10)
            config = TerrainPipelineConfig(
                seed=42,
                num_nodes=100,
                soil_bucket_enabled=enabled,
            )
            debug: dict[str, np.ndarray] = {}
            simulate_climate(mesh, config, debug=debug)
            p = np.array([c.precipitation_mm for c in mesh.cells])
            results[enabled] = p

        p_off, p_on = results[False], results[True]
        # (a) the bucket is not a no-op on a world with land + seasonality
        assert not np.allclose(p_off, p_on), "soil bucket had no effect — wiring broken"
        # (b) global totals stay close (the bucket redistributes ET in time;
        #     the atmospheric budget re-solves to conserve around it)
        assert abs(p_on.sum() - p_off.sum()) / p_off.sum() < 0.10
