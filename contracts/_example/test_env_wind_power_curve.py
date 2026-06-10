"""WORKED EXAMPLE — test cases for contracts/_example/wind_power_curve.md.

Demonstrates the project's test standard:
- every case asserts a hand-computed number, arithmetic shown in the comment
- edge cases pinned exactly at the contract's stated boundaries
- reviewer-added cases marked with `# reviewer:`

A real feature's tests live in tests/env/test_env_<feature>.py, not here.
"""

import jax.numpy as jnp
import pytest

# from energy_go.env.wind import wind_power, WindParams  # real import in actual tests
from conftest import wind_power, WindParams  # example placeholder

V150 = WindParams(p_rated_mw=4.2, v_cutin=3.0, v_rated=12.0, v_cutout=25.0,
                  hub_height_m=105.0)

# Shear factor used throughout: (105/10)^0.14 = 10.5^0.14
#   ln 10.5 = 2.351375, × 0.14 = 0.329193, e^0.329193 = 1.389858
SHEAR = 1.389858


def test_below_cutin_is_zero():
    # v_10m = 1.5 → v_hub = 1.5 × 1.389858 = 2.0848 < 3.0 → P = 0
    assert wind_power(jnp.array(1.5), V150) == 0.0


def test_cubic_region_midpoint():
    # Choose v_10m so v_hub = 7.5 exactly: v_10m = 7.5 / 1.389858 = 5.395518
    # P = 4.2 × ((7.5 − 3)/(12 − 3))³ = 4.2 × 0.5³ = 4.2 × 0.125 = 0.525 MW
    p = wind_power(jnp.array(5.395518), V150)
    assert p == pytest.approx(0.525, rel=1e-4)


def test_shear_applied_to_10m_speed():
    # v_10m = 5.0 → v_hub = 5.0 × 1.389858 = 6.949290
    # P = 4.2 × ((6.949290 − 3)/9)³ = 4.2 × 0.438810³
    #   0.438810² = 0.192554, × 0.438810 = 0.084495 → × 4.2 = 0.354878 MW
    p = wind_power(jnp.array(5.0), V150)
    assert p == pytest.approx(0.354878, rel=1e-4)


def test_rated_region_is_flat():
    # v_10m = 13.0 → v_hub = 18.068 ∈ [12, 25) → P = p_rated = 4.2 MW exactly
    assert wind_power(jnp.array(13.0), V150) == pytest.approx(4.2, rel=1e-6)


def test_above_cutout_is_zero():
    # v_10m = 20.0 → v_hub = 27.797 ≥ 25 → P = 0
    assert wind_power(jnp.array(20.0), V150) == 0.0


# reviewer: contract says cut-in boundary gives 0 via the cubic term — pin it exactly.
def test_exactly_at_cutin_is_zero():
    # v_10m = 3.0 / 1.389858 = 2.158494 → v_hub = 3.0 exactly
    # P = 4.2 × ((3 − 3)/9)³ = 0 — must be 0 by formula, not by the < cut-in branch
    assert wind_power(jnp.array(2.158494), V150) == pytest.approx(0.0, abs=1e-9)


# reviewer: cut-out is inclusive (v ≥ 25 → 0); the step from 4.2 MW to 0 must land AT 25.0.
def test_exactly_at_cutout_is_zero_and_just_below_is_rated():
    v10_at_cutout = 25.0 / SHEAR          # v_hub = 25.000000 → 0 MW
    v10_just_below = 24.999 / SHEAR       # v_hub = 24.999 → rated 4.2 MW
    assert wind_power(jnp.array(v10_at_cutout), V150) == 0.0
    assert wind_power(jnp.array(v10_just_below), V150) == pytest.approx(4.2, rel=1e-6)


# reviewer: exactly at rated speed the cubic and flat branches must agree (no seam).
def test_exactly_at_rated_is_p_rated():
    # v_hub = 12.0: cubic gives 4.2 × ((12−3)/9)³ = 4.2 × 1 = 4.2; flat gives 4.2
    v10 = 12.0 / SHEAR
    assert wind_power(jnp.array(v10), V150) == pytest.approx(4.2, rel=1e-6)


# reviewer: function must be vmappable — batched input crossing every regime in one call.
def test_vectorized_all_regimes():
    v10 = jnp.array([1.5, 5.395518, 13.0, 20.0])
    expected = jnp.array([0.0, 0.525, 4.2, 0.0])
    assert wind_power(v10, V150) == pytest.approx(expected, rel=1e-4)
