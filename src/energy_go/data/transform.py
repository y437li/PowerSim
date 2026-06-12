"""energy_go.data.transform — wind-shear transform + episode-array assembly.

Contract: contracts/harness/weather_pipeline.md §3.1, §3.2, §4.2, §4.3

Key algorithms:
  - Fitted shear:    α = clip(ln(v100/v10)/ln(10), 0.0, 0.6)  with 0.14 neutral fallback
  - Hub extrapolation: v_hub = v100 * (hub_height_m/100)^α
  - Leap-year drop: Feb-29 = hours 1416-1439 (Jan 744h + Feb 1-28 672h = offset 1416)
  - Climate nonstationarity: EMPIRICAL values passed through unchanged — no detrending

Pure Python / NumPy — never called inside jit.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Union

import numpy as np

# Pre-computed constant: ln(100/10) = ln(10) ≈ 2.302585
# Used in α = ln(v100/v10) / ln(10); pre-computed to avoid per-step recalculation.
_LN10: float = math.log(10.0)

# Neutral-atmosphere Hellman exponent (standard surface-layer default)
_ALPHA_NEUTRAL: float = 0.14

# Feb-29 hour offsets in a leap year (0-indexed):
#   Jan = 31 days × 24h = 744h
#   Feb 1-28 = 28 days × 24h = 672h
#   Offset = 744 + 672 = 1416h → Feb-29 occupies hours 1416-1439 (24h)
_FEB29_START: int = 1416   # inclusive
_FEB29_END:   int = 1440   # exclusive  (= 1416 + 24)


# ---------------------------------------------------------------------------
# §3.1  Fitted wind shear
# ---------------------------------------------------------------------------

def compute_fitted_shear(
    v10_mps: np.ndarray,
    v100_mps: np.ndarray,
) -> np.ndarray:
    """Return hourly fitted-shear exponent α, shape (N,), dtype float32.

    Formula: α[t] = clip( ln(v100[t] / v10[t]) / ln(10),  lo=0.0,  hi=0.6 )

    Stability flags — α[t] = 0.14 (neutral atmosphere) when:
      - v10[t] ≤ 0  OR  v100[t] ≤ 0  (calm or negative wind)
      - v10[t] or v100[t] is NaN or ±Inf  (invalid sensor reading)

    Notes:
      - ln(10) ≈ 2.302585 is pre-computed (_LN10 constant; not recalculated per step).
      - Ratio v100==v10 is a valid no-shear reading (α=0); it does NOT trigger the
        neutral fallback (both values are positive and finite).
      - Float64 is used internally to avoid float32 precision loss in log();
        output is cast to float32.
    """
    v10  = np.asarray(v10_mps,  dtype=np.float64)
    v100 = np.asarray(v100_mps, dtype=np.float64)

    # Degenerate: v10 or v100 is non-positive or non-finite (NaN, ±Inf)
    degenerate = (v10 <= 0.0) | (v100 <= 0.0) | ~np.isfinite(v10) | ~np.isfinite(v100)

    # Safe ratio: substitute 1.0 (→ ln=0, α=0) for degenerate entries to avoid
    # log(0)/log(neg)/log(NaN) propagating into the clip.  The final np.where
    # replaces degenerate entries with 0.14 regardless.
    safe_ratio = np.where(degenerate, 1.0, v100 / v10)
    raw_alpha  = np.log(safe_ratio) / _LN10

    # Clip valid entries to [0.0, 0.6]
    clipped = np.clip(raw_alpha, 0.0, 0.6)

    # Apply neutral-atmosphere fallback for degenerate inputs
    result = np.where(degenerate, _ALPHA_NEUTRAL, clipped)

    return result.astype(np.float32)


# ---------------------------------------------------------------------------
# §3.1  Hub-height extrapolation
# ---------------------------------------------------------------------------

def extrapolate_to_hub(
    v100_mps: np.ndarray,
    alpha: np.ndarray,
    hub_height_m: float,
) -> np.ndarray:
    """Extrapolate 100m wind to hub height using the power-law profile.

    Formula: v_hub[t] = v100[t] * (hub_height_m / 100.0) ^ alpha[t]

    Special cases:
      - v100[t] ≤ 0 → v_hub[t] = 0.0 (no wind regardless of α)
      - alpha = 0   → (hub/100)^0 = 1.0, so v_hub = v100 (hub-independent)

    Args:
        v100_mps:    Shape (N,), float; wind speed at 100m (m/s).
        alpha:       Shape (N,), float; shear exponent clipped to [0.0, 0.6].
        hub_height_m: Turbine hub height in metres (e.g. 90.0 for Gansu v150-4.2).

    Returns:
        Shape (N,), float32; hub-height wind speed (m/s).
    """
    v100  = np.asarray(v100_mps, dtype=np.float64)
    alpha = np.asarray(alpha,    dtype=np.float64)
    factor = hub_height_m / 100.0   # (hub/100) — scalar

    v_hub = v100 * np.power(factor, alpha)  # factor^0 = 1.0 when alpha=0 ✓

    # Zero out calm entries
    v_hub = np.where(v100 <= 0.0, 0.0, v_hub)

    return v_hub.astype(np.float32)


# ---------------------------------------------------------------------------
# §3.2  Leap-year normalisation
# ---------------------------------------------------------------------------

def _drop_feb29_if_present(arr: np.ndarray, year: int) -> np.ndarray:
    """Drop Feb-29 from a (N, D) array if `year` is a leap year.

    Feb-29 = hours 1416-1439 (0-indexed):
        Jan (31d × 24h = 744h) + Feb 1-28 (28d × 24h = 672h) = offset 1416h
        Feb-29 occupies indices 1416 to 1439 inclusive (24 hours).

    For non-leap years: returns arr unchanged.
    For leap years: returns np.concatenate([arr[:1416], arr[1440:]], axis=0)
    resulting in exactly N-24 rows.

    Handles any number of columns (works for (N,3), (N,4), etc.).
    """
    if not _is_leap_year(year):
        return arr
    return np.concatenate([arr[:_FEB29_START], arr[_FEB29_END:]], axis=0)


def _is_leap_year(year: int) -> bool:
    """Return True iff year is a proleptic Gregorian leap year."""
    return (year % 4 == 0) and (year % 100 != 0 or year % 400 == 0)


# ---------------------------------------------------------------------------
# §4.2  Multi-year array builder (from cache or raw arrays)
# ---------------------------------------------------------------------------

def build_multi_year_array(
    cache_path: Union[str, Path],
    hub_height_m: float,
) -> np.ndarray:
    """Load cached Parquet, apply shear + hub-height transform, drop Feb-29.

    Returns shape (N_hours, 3), float32: [v_hub_mps, irr_wm2, temp_c].
    N_hours = oracle_years × 8760 (exact; leap years normalised).

    Climate nonstationarity: EMPIRICAL values are returned unchanged.
    No detrending, no bias correction, no weighting. (contract §3.5)
    """
    try:
        import pandas as pd
    except ImportError as e:
        raise ImportError(
            "build_multi_year_array requires 'pandas'. "
            "Install with: pip install pandas pyarrow"
        ) from e

    df = pd.read_parquet(cache_path)
    times = pd.to_datetime(df["time"])
    years_in_cache = sorted(times.dt.year.unique())

    v10_all  = df["wind_speed_10m"].to_numpy(dtype=np.float32)
    v100_all = df["wind_speed_100m"].to_numpy(dtype=np.float32)
    ghi_all  = df["shortwave_radiation"].to_numpy(dtype=np.float32)
    temp_all = df["temperature_2m"].to_numpy(dtype=np.float32)
    year_arr = times.dt.year.to_numpy()

    chunks = []
    for yr in years_in_cache:
        mask = year_arr == yr
        v10_yr  = v10_all[mask]
        v100_yr = v100_all[mask]
        ghi_yr  = ghi_all[mask]
        temp_yr = temp_all[mask]

        # Stack as (N, 4): [v10, v100, ghi, temp]
        chunk = np.stack([v10_yr, v100_yr, ghi_yr, temp_yr], axis=1)  # (N,4)
        chunk = _drop_feb29_if_present(chunk, yr)
        chunks.append(chunk)

    raw = np.concatenate(chunks, axis=0)  # (N_years×8760, 4)

    # Fitted shear + hub extrapolation
    alpha = compute_fitted_shear(raw[:, 0], raw[:, 1])
    v_hub = extrapolate_to_hub(raw[:, 1], alpha, hub_height_m)

    # Output: [v_hub_mps, irr_wm2, temp_c]
    return np.stack([v_hub, raw[:, 2], raw[:, 3]], axis=1).astype(np.float32)


def build_multi_year_array_from_arrays(
    v10_mps: np.ndarray,
    v100_mps: np.ndarray,
    ghi_wm2: np.ndarray,
    temp_c: np.ndarray,
    hub_height_m: float,
) -> np.ndarray:
    """Transform raw component arrays directly to (N, 3) float32 [v_hub, ghi, temp].

    Used for unit testing (no Parquet cache needed) and for the
    TestNoDetrending test — verifies that temperature values pass through
    unchanged (EMPIRICAL, no detrending applied).

    Args:
        v10_mps:     Shape (N,) — 10m wind speed (m/s).
        v100_mps:    Shape (N,) — 100m wind speed (m/s).
        ghi_wm2:     Shape (N,) — global horizontal irradiance (W/m²).
        temp_c:      Shape (N,) — temperature at 2m (°C).
        hub_height_m: Turbine hub height (m).

    Returns:
        Shape (N, 3) float32: [v_hub_mps, irr_wm2, temp_c].
        temp_c column is passed through WITHOUT detrending/modification.
    """
    v10  = np.asarray(v10_mps,  dtype=np.float32)
    v100 = np.asarray(v100_mps, dtype=np.float32)
    ghi  = np.asarray(ghi_wm2,  dtype=np.float32)
    temp = np.asarray(temp_c,   dtype=np.float32)

    alpha = compute_fitted_shear(v10, v100)
    v_hub = extrapolate_to_hub(v100, alpha, hub_height_m)

    # Climate nonstationarity: temp is passed through UNCHANGED — no detrending.
    return np.stack([v_hub, ghi, temp], axis=1).astype(np.float32)
