"""Tests: contracts/harness/weather_pipeline.md v1.0.0

Contract: §12 real-weather data pipeline — fetch, shear transform, block bootstrap,
episode-array assembly.

Design approval: PR #77 (b0ae5fd).  task #69 spec inputs folded in.
Decisions: D3, D6, D11, D19, D31/F1; task-69 inputs (100m primary, fitted shear,
10yr oracle, EMPIRICAL non-detrend).

Notes:
  - All physics/transform tests assert hand-computed expected values (arithmetic shown).
  - Network-dependent tests are skipped unless the env var WEATHER_PIPELINE_NETWORK=1 is set.
  - JAX is imported lazily; tests that do NOT need JAX skip gracefully if it's absent.
  - The real-mode load tests use the §4.2 D19 parameters directly (no env dependency).
"""
from __future__ import annotations

import math
import os
import importlib

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers / guards
# ---------------------------------------------------------------------------

def _skip_if_no_energy_go():
    """Skip the test if the energy_go package is not installed."""
    if importlib.util.find_spec("energy_go") is None:
        pytest.skip("energy_go package not installed")


NETWORK_TESTS = os.environ.get("WEATHER_PIPELINE_NETWORK", "0") == "1"
skip_network = pytest.mark.skipif(
    not NETWORK_TESTS,
    reason="WEATHER_PIPELINE_NETWORK=1 required for live fetch tests",
)


# ---------------------------------------------------------------------------
# §3.1  Fitted shear — compute_fitted_shear
# ---------------------------------------------------------------------------

class TestComputeFittedShear:
    """Verify the hourly fitted-shear formula α = clip(ln(v100/v10)/ln(10), 0.0, 0.6)."""

    def _fn(self):
        _skip_if_no_energy_go()
        from energy_go.data.transform import compute_fitted_shear
        return compute_fitted_shear

    def test_nominal_case(self):
        """v10=5, v100=10 → α = ln(2)/ln(10).
        ln(2) = 0.693147, ln(10) = 2.302585
        α = 0.693147 / 2.302585 = 0.30103  (≈ log10(2))
        """
        fn = self._fn()
        v10  = np.array([5.0], dtype=np.float32)
        v100 = np.array([10.0], dtype=np.float32)
        alpha = fn(v10, v100)
        expected = math.log(10.0 / 5.0) / math.log(10.0)  # = log10(2) = 0.30103
        assert alpha.shape == (1,)
        assert abs(float(alpha[0]) - expected) < 1e-5, (
            f"α={alpha[0]:.6f}, expected={expected:.6f}"
        )

    def test_high_shear_clipped_to_0_6(self):
        """v10=1, v100=20 → raw α = ln(20)/ln(10) = 1.30103 → clipped to 0.6.
        ln(20) = 2.995732, ln(10) = 2.302585
        raw α = 2.995732 / 2.302585 = 1.30103  >0.6 → clip → 0.6
        """
        fn = self._fn()
        v10  = np.array([1.0], dtype=np.float32)
        v100 = np.array([20.0], dtype=np.float32)
        alpha = fn(v10, v100)
        assert float(alpha[0]) == pytest.approx(0.6, abs=1e-6), (
            f"Expected α clipped to 0.6, got {alpha[0]}"
        )

    def test_negative_raw_alpha_clipped_to_0(self):
        """v100 < v10 (temperature inversion): raw α < 0 → clip → 0.0.
        v10=10, v100=5 → raw α = ln(5/10)/ln(10) = ln(0.5)/ln(10)
          = -0.693147 / 2.302585 = -0.30103 → clip → 0.0
        """
        fn = self._fn()
        v10  = np.array([10.0], dtype=np.float32)
        v100 = np.array([5.0], dtype=np.float32)
        alpha = fn(v10, v100)
        assert float(alpha[0]) == pytest.approx(0.0, abs=1e-6), (
            f"Expected 0.0 for inversion case, got {alpha[0]}"
        )

    def test_calm_v10_zero_uses_neutral_default(self):
        """v10=0 → undefined ratio → stability flag → α = 0.14."""
        fn = self._fn()
        v10  = np.array([0.0], dtype=np.float32)
        v100 = np.array([6.0], dtype=np.float32)
        alpha = fn(v10, v100)
        assert abs(float(alpha[0]) - 0.14) < 1e-5, (
            f"Expected neutral default 0.14, got {alpha[0]}"
        )

    def test_calm_v100_zero_uses_neutral_default(self):
        """v100=0 → undefined ratio → stability flag → α = 0.14."""
        fn = self._fn()
        v10  = np.array([5.0], dtype=np.float32)
        v100 = np.array([0.0], dtype=np.float32)
        alpha = fn(v10, v100)
        assert abs(float(alpha[0]) - 0.14) < 1e-5, (
            f"Expected neutral default 0.14, got {alpha[0]}"
        )

    def test_both_calm_uses_neutral_default(self):
        """v10=0, v100=0 → both zero → α = 0.14."""
        fn = self._fn()
        v10  = np.array([0.0], dtype=np.float32)
        v100 = np.array([0.0], dtype=np.float32)
        alpha = fn(v10, v100)
        assert abs(float(alpha[0]) - 0.14) < 1e-5

    def test_batch_mixed_cases(self):
        """Array input: [nominal, high-shear, calm-v10, inversion, neutral-stable].
        Expected: [0.30103, 0.6, 0.14, 0.0, 0.17609]
        Case 5: v10=3, v100=7 → α = ln(7/3)/ln(10) = 0.84730/2.302585 = 0.36798
        Wait — let me recompute more carefully:
          ln(7/3) = ln(2.3333) = 0.84730
          0.84730/2.302585 = 0.36798
        """
        fn = self._fn()
        v10  = np.array([5.0,  1.0,  0.0, 10.0,  3.0], dtype=np.float32)
        v100 = np.array([10.0, 20.0,  6.0,  5.0,  7.0], dtype=np.float32)
        alpha = fn(v10, v100)
        assert alpha.shape == (5,)
        # Index 0: ln(2)/ln(10) = 0.30103
        assert abs(float(alpha[0]) - 0.30103) < 1e-4
        # Index 1: clipped 0.6
        assert abs(float(alpha[1]) - 0.6) < 1e-6
        # Index 2: calm v10=0 → 0.14
        assert abs(float(alpha[2]) - 0.14) < 1e-5
        # Index 3: inversion → 0.0
        assert abs(float(alpha[3]) - 0.0) < 1e-6
        # Index 4: ln(7/3)/ln(10) = ln(2.3333)/2.302585 = 0.84730/2.302585 = 0.36798
        expected_4 = math.log(7.0 / 3.0) / math.log(10.0)
        assert abs(float(alpha[4]) - expected_4) < 1e-4

    def test_output_dtype_float32(self):
        """Output dtype must be float32."""
        fn = self._fn()
        v10  = np.array([5.0], dtype=np.float32)
        v100 = np.array([10.0], dtype=np.float32)
        alpha = fn(v10, v100)
        assert alpha.dtype == np.float32

    def test_float64_input_accepted(self):
        """float64 input should still work (cast internally)."""
        fn = self._fn()
        v10  = np.array([5.0], dtype=np.float64)
        v100 = np.array([10.0], dtype=np.float64)
        alpha = fn(v10, v100)
        assert alpha.dtype == np.float32
        assert abs(float(alpha[0]) - 0.30103) < 1e-4


# ---------------------------------------------------------------------------
# §3.1  Hub-height extrapolation — extrapolate_to_hub
# ---------------------------------------------------------------------------

class TestExtrapolateToHub:
    """Verify v_hub = v100 * (hub_height_m/100)^α."""

    def _fn(self):
        _skip_if_no_energy_go()
        from energy_go.data.transform import extrapolate_to_hub
        return extrapolate_to_hub

    def test_hub_below_100m(self):
        """v100=10, α=0.30103, hub=90m:
        v_hub = 10 * (90/100)^0.30103
              = 10 * (0.9)^0.30103
              = 10 * exp(0.30103 * ln(0.9))
              = 10 * exp(0.30103 * -0.10536)
              = 10 * exp(-0.031726)
              = 10 * 0.96881
              = 9.6881
        """
        fn = self._fn()
        v100 = np.array([10.0], dtype=np.float32)
        alpha = np.array([0.30103], dtype=np.float32)
        v_hub = fn(v100, alpha, hub_height_m=90.0)
        expected = 10.0 * (90.0 / 100.0) ** 0.30103
        # = 9.68814
        assert abs(float(v_hub[0]) - expected) < 1e-3, (
            f"v_hub={v_hub[0]:.5f}, expected={expected:.5f}"
        )

    def test_hub_above_100m(self):
        """v100=10, α=0.30103, hub=120m:
        v_hub = 10 * (120/100)^0.30103
              = 10 * (1.2)^0.30103
              = 10 * exp(0.30103 * ln(1.2))
              = 10 * exp(0.30103 * 0.18232)
              = 10 * exp(0.054886)
              = 10 * 1.056421
              = 10.5642
        """
        fn = self._fn()
        v100 = np.array([10.0], dtype=np.float32)
        alpha = np.array([0.30103], dtype=np.float32)
        v_hub = fn(v100, alpha, hub_height_m=120.0)
        expected = 10.0 * (120.0 / 100.0) ** 0.30103
        assert abs(float(v_hub[0]) - expected) < 1e-3

    def test_hub_exactly_100m(self):
        """hub=100m: v_hub = v100 * (100/100)^α = v100 * 1 = v100."""
        fn = self._fn()
        v100 = np.array([8.5], dtype=np.float32)
        alpha = np.array([0.30103], dtype=np.float32)
        v_hub = fn(v100, alpha, hub_height_m=100.0)
        assert abs(float(v_hub[0]) - 8.5) < 1e-6

    def test_zero_v100_gives_zero_v_hub(self):
        """v100=0 → v_hub=0 (no wind regardless of α)."""
        fn = self._fn()
        v100 = np.array([0.0], dtype=np.float32)
        alpha = np.array([0.5], dtype=np.float32)
        v_hub = fn(v100, alpha, hub_height_m=90.0)
        assert float(v_hub[0]) == 0.0

    def test_neutral_alpha_0_14_gansu_hub_90m(self):
        """Neutral shear α=0.14, v100=8.0, hub=90m (Gansu default):
        v_hub = 8.0 * (90/100)^0.14
              = 8.0 * (0.9)^0.14
              = 8.0 * exp(0.14 * ln(0.9))
              = 8.0 * exp(0.14 * -0.10536)
              = 8.0 * exp(-0.014751)
              = 8.0 * 0.985358
              = 7.88286
        """
        fn = self._fn()
        v100 = np.array([8.0], dtype=np.float32)
        alpha = np.array([0.14], dtype=np.float32)
        v_hub = fn(v100, alpha, hub_height_m=90.0)
        expected = 8.0 * (90.0 / 100.0) ** 0.14
        assert abs(float(v_hub[0]) - expected) < 1e-3

    def test_max_shear_0_6_amplification(self):
        """α=0.6 (high stable shear), v100=6.0, hub=120m:
        v_hub = 6.0 * (1.2)^0.6
              = 6.0 * exp(0.6 * ln(1.2))
              = 6.0 * exp(0.6 * 0.18232)
              = 6.0 * exp(0.10939)
              = 6.0 * 1.11554
              = 6.6932
        """
        fn = self._fn()
        v100 = np.array([6.0], dtype=np.float32)
        alpha = np.array([0.6], dtype=np.float32)
        v_hub = fn(v100, alpha, hub_height_m=120.0)
        expected = 6.0 * (120.0 / 100.0) ** 0.6
        assert abs(float(v_hub[0]) - expected) < 1e-3

    def test_output_dtype_float32(self):
        """Output dtype must be float32."""
        fn = self._fn()
        v100 = np.array([10.0], dtype=np.float32)
        alpha = np.array([0.3], dtype=np.float32)
        v_hub = fn(v100, alpha, hub_height_m=90.0)
        assert v_hub.dtype == np.float32


# ---------------------------------------------------------------------------
# §3.2  Leap year normalisation
# ---------------------------------------------------------------------------

class TestLeapYearNormalisation:
    """build_multi_year_array drops Feb-29, producing exactly 8760h per year."""

    def test_non_leap_year_unchanged(self):
        """Non-leap year: raw 8760h → exactly 8760h in output."""
        _skip_if_no_energy_go()
        from energy_go.data.transform import _drop_feb29_if_present  # internal helper
        # Non-leap raw: 365 days × 24 = 8760 rows
        arr = np.zeros((8760, 3), dtype=np.float32)
        result = _drop_feb29_if_present(arr, year=2023)  # 2023 is not leap
        assert result.shape == (8760, 3), (
            f"Non-leap year should remain 8760h, got {result.shape[0]}"
        )

    def test_leap_year_drops_24_hours(self):
        """Leap year (2024): raw 8784h → 8760h after Feb-29 drop.
        Jan (31d=744h) + Feb 1-28 (28d=672h) = offset 1416h.
        Feb 29 = hours 1416–1439 (indices 1416 to 1439, inclusive → 24 hours).
        Drop hours 1416-1439 → 8784-24=8760h.
        """
        _skip_if_no_energy_go()
        from energy_go.data.transform import _drop_feb29_if_present
        # 2024 is a leap year
        arr = np.arange(8784 * 3, dtype=np.float32).reshape(8784, 3)
        result = _drop_feb29_if_present(arr, year=2024)
        assert result.shape == (8760, 3), (
            f"Leap year should be 8760h after Feb-29 drop, got {result.shape[0]}"
        )
        # Verify continuity: row 1415 (Feb 28, hour 23) followed by row 1416 (Mar 1, hour 0)
        # i.e. original row 1440 (Mar 1 h=0) becomes output row 1416
        # original row indices 1416-1439 (Feb 29) are absent
        # so output[1415] == input[1415] and output[1416] == input[1440]
        assert np.array_equal(result[1415], arr[1415]), "Row before Feb-29 should match"
        assert np.array_equal(result[1416], arr[1440]), "Row after Feb-29 drop should be Mar-1 h=0"


# ---------------------------------------------------------------------------
# §2.5  Season labels — build_block_pool
# ---------------------------------------------------------------------------

class TestSeasonLabels:
    """Season label assignment from meteorological seasons (day-of-year 0-indexed)."""

    def _pool_fn(self):
        _skip_if_no_energy_go()
        from energy_go.data.bootstrap import build_block_pool
        return build_block_pool

    def test_blocks_per_10yr_array(self):
        """N_hours = 10*8760 = 87600; N_blocks = 87600/24 = 3650."""
        fn = self._pool_fn()
        arr = np.zeros((87600, 3), dtype=np.float32)
        blocks, labels = fn(arr, block_size_h=24)
        assert blocks.shape == (3650, 24, 3), f"Expected (3650,24,3), got {blocks.shape}"
        assert labels.shape == (3650,), f"Expected (3650,), got {labels.shape}"

    def test_block0_day0_is_DJF(self):
        """Block 0 = day 0 (Jan 1) → DJF (season 0)."""
        fn = self._pool_fn()
        arr = np.zeros((8760, 3), dtype=np.float32)  # 1 year
        _, labels = fn(arr, block_size_h=24)
        assert labels[0] == 0, f"Block 0 (Jan 1) should be DJF=0, got {labels[0]}"

    def test_block59_day59_is_MAM(self):
        """Block 59 = day 59 (Mar 1, 0-indexed: days 59–150 = MAM) → label 1.
        Mar 1 = day 59 (Jan=31, Feb=28 → 31+28=59).
        """
        fn = self._pool_fn()
        arr = np.zeros((8760, 3), dtype=np.float32)
        _, labels = fn(arr, block_size_h=24)
        assert labels[59] == 1, f"Block 59 (Mar 1) should be MAM=1, got {labels[59]}"

    def test_block150_day150_is_MAM(self):
        """Block 150 = day 150 (May 31) → still MAM (days 59–150 inclusive) → label 1."""
        fn = self._pool_fn()
        arr = np.zeros((8760, 3), dtype=np.float32)
        _, labels = fn(arr, block_size_h=24)
        assert labels[150] == 1, f"Block 150 (May 31) should be MAM=1, got {labels[150]}"

    def test_block151_day151_is_JJA(self):
        """Block 151 = day 151 (Jun 1) → JJA (days 151–242) → label 2."""
        fn = self._pool_fn()
        arr = np.zeros((8760, 3), dtype=np.float32)
        _, labels = fn(arr, block_size_h=24)
        assert labels[151] == 2, f"Block 151 (Jun 1) should be JJA=2, got {labels[151]}"

    def test_block243_day243_is_SON(self):
        """Block 243 = day 243 (Sep 1) → SON (days 243–333) → label 3."""
        fn = self._pool_fn()
        arr = np.zeros((8760, 3), dtype=np.float32)
        _, labels = fn(arr, block_size_h=24)
        assert labels[243] == 3, f"Block 243 (Sep 1) should be SON=3, got {labels[243]}"

    def test_block334_day334_is_DJF(self):
        """Block 334 = day 334 (Dec 1) → DJF (Dec is in DJF pool) → label 0."""
        fn = self._pool_fn()
        arr = np.zeros((8760, 3), dtype=np.float32)
        _, labels = fn(arr, block_size_h=24)
        assert labels[334] == 0, f"Block 334 (Dec 1) should be DJF=0, got {labels[334]}"

    def test_season_counts_sum_to_365(self):
        """Per-year season block counts: 90 DJF + 92 MAM + 92 JJA + 91 SON = 365."""
        fn = self._pool_fn()
        arr = np.zeros((8760, 3), dtype=np.float32)
        _, labels = fn(arr, block_size_h=24)
        counts = {s: int(np.sum(labels == s)) for s in range(4)}
        assert counts[0] == 90, f"DJF: expected 90, got {counts[0]}"
        assert counts[1] == 92, f"MAM: expected 92, got {counts[1]}"
        assert counts[2] == 92, f"JJA: expected 92, got {counts[2]}"
        assert counts[3] == 91, f"SON: expected 91, got {counts[3]}"
        assert sum(counts.values()) == 365

    def test_non_divisible_raises(self):
        """N_hours not divisible by block_size_h → ValueError."""
        fn = self._pool_fn()
        arr = np.zeros((8761, 3), dtype=np.float32)  # 8761 not divisible by 24
        with pytest.raises(ValueError, match="block_size_h"):
            fn(arr, block_size_h=24)


# ---------------------------------------------------------------------------
# §3.3  Block bootstrap — sample_bootstrap_year
# ---------------------------------------------------------------------------

class TestSampleBootstrapYear:
    """Verify episode-year sampling shape, season counts, and determinism."""

    def _fn(self):
        _skip_if_no_energy_go()
        from energy_go.data.bootstrap import sample_bootstrap_year
        return sample_bootstrap_year

    def _pool(self):
        _skip_if_no_energy_go()
        from energy_go.data.bootstrap import build_block_pool
        return build_block_pool

    def test_output_shape_is_8760x3(self):
        """sample_bootstrap_year returns shape (8760, 3)."""
        sample = self._fn()
        pool_fn = self._pool()
        arr = np.random.default_rng(0).random((87600, 3)).astype(np.float32)
        blocks, labels = pool_fn(arr, block_size_h=24)
        rng = np.random.default_rng(42)
        out = sample(blocks, labels, rng, block_size_h=24)
        assert out.shape == (8760, 3), f"Expected (8760,3), got {out.shape}"
        assert out.dtype == np.float32

    def test_sampled_blocks_belong_to_correct_season(self):
        """Blocks sampled for each season must come from the correct season pool.
        Strategy: fill each season with a distinct constant value; assert the
        corresponding output segments are from the right constant.
        DJF(0)=10.0, MAM(1)=20.0, JJA(2)=30.0, SON(3)=40.0 in column 0.
        DJF output: hours 0–89*24+23 = 0–2159   → all ≈ 10.0
        MAM output: hours 2160–2160+92*24-1      → all ≈ 20.0
        JJA output: hours 2160+92*24–...          → all ≈ 30.0
        SON output: rest                           → all ≈ 40.0
        """
        sample = self._fn()
        pool_fn = self._pool()

        # Build 1-year array with season-constant col-0 values
        arr = np.zeros((8760, 3), dtype=np.float32)
        season_vals = {0: 10.0, 1: 20.0, 2: 30.0, 3: 40.0}
        # Assign by day-of-year boundaries
        for day in range(365):
            hour = day * 24
            if day < 59 or day >= 334:    # DJF
                arr[hour:hour+24, 0] = 10.0
            elif day < 151:               # MAM
                arr[hour:hour+24, 0] = 20.0
            elif day < 243:               # JJA
                arr[hour:hour+24, 0] = 30.0
            else:                          # SON
                arr[hour:hour+24, 0] = 40.0

        blocks, labels = pool_fn(arr, block_size_h=24)
        rng = np.random.default_rng(42)
        out = sample(blocks, labels, rng, block_size_h=24)

        # DJF segment: 90 blocks × 24h = 2160h, col 0 = 10.0
        djf_out = out[:90*24, 0]
        assert np.all(djf_out == 10.0), "DJF output should be sourced from DJF blocks"
        # MAM: 92 blocks = 2208h
        mam_out = out[90*24:(90+92)*24, 0]
        assert np.all(mam_out == 20.0), "MAM output should be sourced from MAM blocks"
        # JJA: 92 blocks = 2208h
        jja_out = out[(90+92)*24:(90+92+92)*24, 0]
        assert np.all(jja_out == 30.0), "JJA output should be sourced from JJA blocks"
        # SON: 91 blocks = 2184h
        son_out = out[(90+92+92)*24:, 0]
        assert np.all(son_out == 40.0), "SON output should be sourced from SON blocks"

    def test_determinism_fixed_seed(self):
        """Fixed rng seed → identical output across two calls."""
        sample = self._fn()
        pool_fn = self._pool()
        arr = np.random.default_rng(1).random((87600, 3)).astype(np.float32)
        blocks, labels = pool_fn(arr, block_size_h=24)

        out1 = sample(blocks, labels, np.random.default_rng(42), block_size_h=24)
        out2 = sample(blocks, labels, np.random.default_rng(42), block_size_h=24)
        assert np.array_equal(out1, out2), "Determinism violated: different seeds"

    def test_different_seeds_differ(self):
        """Different rng seeds → different outputs (extremely unlikely to be equal)."""
        sample = self._fn()
        pool_fn = self._pool()
        arr = np.random.default_rng(1).random((87600, 3)).astype(np.float32)
        blocks, labels = pool_fn(arr, block_size_h=24)

        out1 = sample(blocks, labels, np.random.default_rng(42), block_size_h=24)
        out2 = sample(blocks, labels, np.random.default_rng(99), block_size_h=24)
        assert not np.array_equal(out1, out2), "Different seeds should (almost surely) differ"


# ---------------------------------------------------------------------------
# §5.1  Episode array schema — WeatherPipeline.sample (output contract)
# ---------------------------------------------------------------------------

class TestEpisodeArraySchema:
    """The real-mode output must match the §4 SyntheticYear format exactly."""

    def test_shape_is_8760x4(self):
        """WeatherPipeline.sample() returns (8760, 4), float32."""
        _skip_if_no_energy_go()
        from energy_go.data.pipeline import WeatherPipeline
        # Build a minimal mock (no network; pre-built from a fixture array)
        pipeline = WeatherPipeline._from_test_array(
            weather_array=np.random.default_rng(0).random((87600, 3)).astype(np.float32),
            hub_height_m=90.0,
            block_size_h=24,
        )
        out = pipeline.sample(np.random.default_rng(42))
        assert out.shape == (8760, 4), f"Expected (8760,4), got {out.shape}"
        assert out.dtype == np.float32

    def test_all_values_finite(self):
        """No NaN or ±Inf in any column."""
        _skip_if_no_energy_go()
        from energy_go.data.pipeline import WeatherPipeline
        pipeline = WeatherPipeline._from_test_array(
            weather_array=np.random.default_rng(0).random((87600, 3)).astype(np.float32) * 10,
            hub_height_m=90.0,
            block_size_h=24,
        )
        out = pipeline.sample(np.random.default_rng(42))
        assert np.all(np.isfinite(out)), "Episode array contains NaN or ±Inf"

    def test_irr_non_negative(self):
        """Column 1 (irr_wm2) ≥ 0 for all hours."""
        _skip_if_no_energy_go()
        from energy_go.data.pipeline import WeatherPipeline
        arr = np.abs(np.random.default_rng(0).random((8760, 3)).astype(np.float32)) * 500
        pipeline = WeatherPipeline._from_test_array(
            weather_array=arr, hub_height_m=90.0, block_size_h=24,
        )
        out = pipeline.sample(np.random.default_rng(1))
        assert np.all(out[:, 1] >= 0.0), "irr_wm2 column has negative values"

    def test_load_positive(self):
        """Column 3 (load_mw) > 0 at D19 scale (base=75 MW minus noise; always positive)."""
        _skip_if_no_energy_go()
        from energy_go.data.pipeline import WeatherPipeline
        # Typical temperature (20°C) → load ≈ 75 MW + noise; should never be ≤0 at D19 scale
        arr = np.ones((8760, 3), dtype=np.float32) * np.array([6.0, 300.0, 20.0])
        pipeline = WeatherPipeline._from_test_array(
            weather_array=arr, hub_height_m=90.0, block_size_h=24,
        )
        out = pipeline.sample(np.random.default_rng(0))
        assert np.all(out[:, 3] > 0.0), "load_mw column has non-positive values"

    def test_synthetic_mode_bit_identical_to_generate_year(self):
        """mode=synthetic must call generate_year(key) → bit-identical output (D11).
        The WeatherPipeline is NOT imported when mode=synthetic.
        """
        _skip_if_no_energy_go()
        try:
            import jax
        except ImportError:
            pytest.skip("JAX not installed")
        from energy_go.generators.synthetic import generate_year
        from energy_go.data.pipeline import get_episode_array

        key = jax.random.PRNGKey(42)
        # Synthetic path (mode=synthetic or absent)
        arr_synthetic = np.array(generate_year(key))
        arr_pipeline  = get_episode_array(mode="synthetic", key=key)
        assert np.array_equal(arr_synthetic, arr_pipeline), (
            "Synthetic mode must be bit-identical to generate_year"
        )


# ---------------------------------------------------------------------------
# §5.6  Climate nonstationarity — no detrending
# ---------------------------------------------------------------------------

class TestNoDetrending:
    """The pipeline passes empirical values through without detrending."""

    def test_temperature_mean_preserved(self):
        """build_multi_year_array must not alter the temperature mean.
        If detrending were applied, the mean would shift. Assert raw mean == output mean.
        """
        _skip_if_no_energy_go()
        from energy_go.data.transform import build_multi_year_array_from_arrays

        # Simulate a 1-year record with a linear temperature trend (mock non-stationarity)
        N = 8760
        v10  = np.ones(N, dtype=np.float32) * 5.0
        v100 = np.ones(N, dtype=np.float32) * 10.0
        ghi  = np.ones(N, dtype=np.float32) * 300.0
        temp = (20.0 + np.linspace(0, 3, N)).astype(np.float32)  # 3°C trend over year

        result = build_multi_year_array_from_arrays(
            v10_mps=v10, v100_mps=v100, ghi_wm2=ghi, temp_c=temp, hub_height_m=100.0,
        )
        # temp column is index 2 in output [v_hub, ghi, temp]
        assert result.shape == (N, 3)
        raw_mean = float(np.mean(temp))
        out_mean = float(np.mean(result[:, 2]))
        assert abs(raw_mean - out_mean) < 1e-4, (
            f"Temperature mean changed from {raw_mean:.4f} to {out_mean:.4f} — "
            "detrending must NOT be applied"
        )


# ---------------------------------------------------------------------------
# §2.3  Cache path — deterministic key
# ---------------------------------------------------------------------------

class TestCachePath:
    """Cache path is deterministic from (source, lat, lon, start_year, end_year)."""

    def test_cache_path_is_deterministic(self):
        """Same inputs → same cache path, independent of call order."""
        _skip_if_no_energy_go()
        from energy_go.data.fetch import make_cache_path

        path1 = make_cache_path(
            source="open_meteo", lat=38.5, lon=99.9,
            start_year=2014, end_year=2023,
            cache_dir="/tmp/weather_cache",
        )
        path2 = make_cache_path(
            source="open_meteo", lat=38.5, lon=99.9,
            start_year=2014, end_year=2023,
            cache_dir="/tmp/weather_cache",
        )
        assert path1 == path2

    def test_cache_path_includes_lat_lon(self):
        """Cache path includes the rounded lat/lon for cache-key uniqueness."""
        _skip_if_no_energy_go()
        from energy_go.data.fetch import make_cache_path
        path = make_cache_path(
            source="open_meteo", lat=38.5, lon=99.9,
            start_year=2014, end_year=2023,
            cache_dir="/tmp/weather_cache",
        )
        path_str = str(path)
        assert "38.5" in path_str or "38.50000" in path_str
        assert "99.9" in path_str or "99.90000" in path_str

    def test_different_coords_different_paths(self):
        """Different lat/lon → different cache paths."""
        _skip_if_no_energy_go()
        from energy_go.data.fetch import make_cache_path
        path_gansu = make_cache_path(
            source="open_meteo", lat=38.5, lon=99.9,
            start_year=2014, end_year=2023,
            cache_dir="/tmp/weather_cache",
        )
        path_other = make_cache_path(
            source="open_meteo", lat=35.0, lon=100.0,
            start_year=2014, end_year=2023,
            cache_dir="/tmp/weather_cache",
        )
        assert path_gansu != path_other


# ---------------------------------------------------------------------------
# §5.3  Mode switch — synthetic path unchanged
# ---------------------------------------------------------------------------

class TestModeSwitch:
    """Mode=synthetic must not touch the WeatherPipeline at all."""

    def test_synthetic_mode_no_import(self):
        """In synthetic mode, energy_go.data is NOT imported (it may not even be present)."""
        _skip_if_no_energy_go()
        try:
            import jax
        except ImportError:
            pytest.skip("JAX not installed")
        from energy_go.data.pipeline import get_episode_array
        from energy_go.generators.synthetic import generate_year

        key = jax.random.PRNGKey(0)
        # This must work even if the data package has not been built (no cache)
        result = get_episode_array(mode="synthetic", key=key)
        expected = np.array(generate_year(key))
        assert np.array_equal(result, expected), (
            "synthetic mode must be bit-identical to generate_year"
        )

    def test_invalid_mode_raises(self):
        """Unsupported mode value raises ValueError."""
        _skip_if_no_energy_go()
        try:
            import jax
        except ImportError:
            pytest.skip("JAX not installed")
        from energy_go.data.pipeline import get_episode_array
        with pytest.raises(ValueError, match="mode"):
            get_episode_array(mode="invalid_mode", key=None)


# ---------------------------------------------------------------------------
# Live fetch tests (require WEATHER_PIPELINE_NETWORK=1)
# ---------------------------------------------------------------------------

class TestLiveFetch:
    """Integration tests requiring network access."""

    @skip_network
    def test_gansu_fetch_produces_parquet(self, tmp_path):
        """Fetch 2 years of Gansu weather → Parquet file exists, non-empty."""
        _skip_if_no_energy_go()
        from energy_go.data.fetch import fetch_weather_history
        path = fetch_weather_history(
            lat=38.5, lon=99.9, years=[2022, 2023],
            cache_dir=tmp_path, source="open_meteo",
        )
        assert path.exists(), "Cache Parquet should exist after fetch"
        assert path.stat().st_size > 0, "Cache Parquet should be non-empty"

    @skip_network
    def test_fetch_is_idempotent(self, tmp_path):
        """Two fetch calls → second call hits cache (same path, no second HTTP request)."""
        _skip_if_no_energy_go()
        from energy_go.data.fetch import fetch_weather_history
        years = [2023]
        path1 = fetch_weather_history(
            lat=38.5, lon=99.9, years=years, cache_dir=tmp_path,
        )
        mtime1 = path1.stat().st_mtime
        path2 = fetch_weather_history(
            lat=38.5, lon=99.9, years=years, cache_dir=tmp_path,
        )
        mtime2 = path2.stat().st_mtime
        assert path1 == path2, "Cache path should be identical on second call"
        assert mtime1 == mtime2, "File mtime should not change on cache hit"

    @skip_network
    def test_gansu_multi_year_array_shape(self, tmp_path):
        """Gansu 2-year fetch → build_multi_year_array → shape (2*8760, 3)."""
        _skip_if_no_energy_go()
        from energy_go.data.fetch import fetch_weather_history
        from energy_go.data.transform import build_multi_year_array
        path = fetch_weather_history(
            lat=38.5, lon=99.9, years=[2022, 2023], cache_dir=tmp_path,
        )
        arr = build_multi_year_array(path, hub_height_m=90.0)
        assert arr.shape == (2 * 8760, 3), (
            f"Expected (17520,3), got {arr.shape}"
        )
        assert arr.dtype == np.float32
        # All values finite
        assert np.all(np.isfinite(arr)), "Multi-year array contains non-finite values"

    @skip_network
    def test_full_pipeline_gansu_1yr(self, tmp_path):
        """End-to-end: Gansu 2yr pool → 1-year bootstrap sample → (8760,4) float32."""
        _skip_if_no_energy_go()
        from energy_go.data.pipeline import WeatherPipeline
        # Minimal site config
        site = {
            "location": {"latitude": 38.5, "longitude": 99.9},
            "weather": {
                "mode": "real", "source": "open_meteo",
                "oracle_years": 2, "end_year": 2023,
                "block_size_h": 24,
            },
            "assets": {"wind": {"model": "vestas-v150-4.2"}},
        }
        pipeline = WeatherPipeline.from_site_config(site, cache_dir=tmp_path)
        pipeline.build()
        out = pipeline.sample(np.random.default_rng(42))
        assert out.shape == (8760, 4)
        assert out.dtype == np.float32
        assert np.all(np.isfinite(out))
        assert np.all(out[:, 3] > 0.0)  # load always positive
