"""energy_go.data.bootstrap — seasonally-stratified block bootstrap.

Contract: contracts/harness/weather_pipeline.md §2.5, §3.3, §4.3

v1 generator: day-aligned B=24 block bootstrap (design study approach (b)).
  - Preserves real joint wind/solar/temperature co-structure (cross-variable correlation
    for free; the hardest realism dimension per the design study).
  - §7-device-native and combinatorially unlimited: the multi-year array is ~4 MB
    on-device; each env samples random block indices via vmapped lax.dynamic_slice.
  - Seasonally stratified: 90 DJF + 92 MAM + 92 JJA + 91 SON = 365 blocks per year.

Pure Python / NumPy — never called inside jit.  The output (8760, 3) array is
materialised offline; the env indexes it with lax.dynamic_slice in the hot path.
"""
from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Season boundaries (meteorological, day-of-year 0-indexed, non-leap):
#
#   DJF (0): days   0– 58  (Jan + Feb)      = 59 days
#            days 334–364  (Dec)             = 31 days  → 90 total
#   MAM (1): days  59–150  (Mar+Apr+May)     = 92 days
#   JJA (2): days 151–242  (Jun+Jul+Aug)     = 92 days
#   SON (3): days 243–333  (Sep+Oct+Nov)     = 91 days
#   Total: 90+92+92+91 = 365 ✓
# ---------------------------------------------------------------------------
_SEASON_DJF = 0
_SEASON_MAM = 1
_SEASON_JJA = 2
_SEASON_SON = 3

# Target block counts per season for one 8760h (365-day) episode year
_SEASON_COUNTS = {_SEASON_DJF: 90, _SEASON_MAM: 92, _SEASON_JJA: 92, _SEASON_SON: 91}

# Days per year (non-leap) for modular day-of-year computation across multi-year pools
_DAYS_PER_YEAR = 365


def _day_to_season(day: int) -> int:
    """Map 0-indexed day-of-year (0=Jan1, 364=Dec31) to meteorological season.

    Season boundaries:
        DJF (0): day < 59  (Jan–Feb)  or  day ≥ 334  (Dec)
        MAM (1): 59 ≤ day < 151       (Mar–May)
        JJA (2): 151 ≤ day < 243      (Jun–Aug)
        SON (3): 243 ≤ day < 334      (Sep–Nov)
    """
    if day < 59:
        return _SEASON_DJF     # Jan (0-30) + Feb (31-58)
    elif day < 151:
        return _SEASON_MAM     # Mar (59-89) + Apr (90-119) + May (120-150)
    elif day < 243:
        return _SEASON_JJA     # Jun (151-180) + Jul (181-211) + Aug (212-242)
    elif day < 334:
        return _SEASON_SON     # Sep (243-272) + Oct (273-302) + Nov (303-333)
    else:
        return _SEASON_DJF     # Dec (334-364)


def build_block_pool(
    weather_array: np.ndarray,
    block_size_h: int = 24,
) -> tuple:
    """Partition a multi-year weather array into blocks; assign season labels.

    Args:
        weather_array: Shape (N_hours, D), float32 — multi-year [v_hub, ghi, temp].
        block_size_h:  Block length in hours.  24 = day-aligned (default);
                       168 = week-aligned (config option).

    Returns:
        blocks        — shape (N_blocks, block_size_h, D), float32
        season_labels — shape (N_blocks,), int8 in {0,1,2,3}

    Raises:
        ValueError: if N_hours % block_size_h != 0.

    Season of block k = season of day (k * block_size_h // 24) mod 365.
    For day-aligned B=24: each block is exactly one calendar day.
    """
    N_hours, D = weather_array.shape
    if N_hours % block_size_h != 0:
        raise ValueError(
            f"N_hours ({N_hours}) is not divisible by block_size_h ({block_size_h}). "
            f"The multi-year array must have exactly oracle_years × 8760 hours."
        )

    N_blocks = N_hours // block_size_h
    blocks = weather_array.reshape(N_blocks, block_size_h, D).copy()

    # Assign season to each block based on its first day-of-year
    season_labels = np.empty(N_blocks, dtype=np.int8)
    for k in range(N_blocks):
        block_start_hour = k * block_size_h
        # Day-of-year modulo 365 (wraps across year boundaries in multi-year arrays)
        day_of_year = (block_start_hour // 24) % _DAYS_PER_YEAR
        season_labels[k] = _day_to_season(day_of_year)

    return blocks, season_labels


def sample_bootstrap_year(
    blocks: np.ndarray,
    season_labels: np.ndarray,
    rng: np.random.Generator,
    block_size_h: int = 24,
) -> np.ndarray:
    """Sample one 8760h year via seasonally-stratified block bootstrap.

    Day-aligned (B=24, default):
        Draws with replacement:
            90 DJF blocks  (days 0-58 + Dec)
            92 MAM blocks  (Mar-May)
            92 JJA blocks  (Jun-Aug)
            91 SON blocks  (Sep-Nov)
        Concatenates in DJF→MAM→JJA→SON calendar order (= Jan–Dec order).
        Total: 365 blocks × 24h = 8760h ✓

    Week-aligned (B=168): raises NotImplementedError (config option, not v1 impl).

    Args:
        blocks:        Shape (N_blocks, B, D), float32.
        season_labels: Shape (N_blocks,), int8; season index per block.
        rng:           NumPy Generator (e.g. np.random.default_rng(42)).
        block_size_h:  Must match blocks.shape[1].

    Returns:
        Shape (8760, D), float32: one episode year.

    Raises:
        ValueError:         if any season pool is empty.
        NotImplementedError: if block_size_h=168 (week-aligned; v2 deferred).
    """
    if block_size_h == 168:
        raise NotImplementedError(
            "Week-aligned blocks (B=168) are specified as a config option but are "
            "deferred to v2.  Use block_size_h=24 (day-aligned default)."
        )
    if block_size_h != 24:
        raise ValueError(
            f"block_size_h must be 24 (day-aligned) in v1; got {block_size_h}."
        )

    D = blocks.shape[2]

    # Pre-index each season pool
    pools = {s: np.where(season_labels == s)[0] for s in range(4)}
    for s, pool in pools.items():
        if len(pool) == 0:
            season_name = ["DJF", "MAM", "JJA", "SON"][s]
            raise ValueError(
                f"No blocks available for season {season_name} (index {s}). "
                f"The multi-year pool is too small or misconfigured."
            )

    # Draw blocks per season (with replacement), in DJF→MAM→JJA→SON calendar order
    segments = []
    for season_idx in [_SEASON_DJF, _SEASON_MAM, _SEASON_JJA, _SEASON_SON]:
        n = _SEASON_COUNTS[season_idx]
        pool = pools[season_idx]
        chosen_idx = rng.choice(pool, size=n, replace=True)
        segment = blocks[chosen_idx]                    # (n, 24, D)
        segments.append(segment.reshape(n * 24, D))    # (n*24, D)

    result = np.concatenate(segments, axis=0)           # (8760, D)
    return result.astype(np.float32)
