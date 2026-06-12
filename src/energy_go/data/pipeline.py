"""energy_go.data.pipeline — top-level real-weather pipeline + mode switch.

Contract: contracts/harness/weather_pipeline.md §3.4–§3.7, §4.4

Exposes:
  WeatherPipeline — fetch → cache → transform → block-pool → sample
  get_episode_array — mode switch: "synthetic" (generate_year) | "real" (pipeline.sample)

§4.2 load (D19): §4.2 AR(1)-on-temperature formula conditioned on real temp_c.
  Parameters: base=75 000 kW, α=4 500 kW/°C, β=3 750 kW/°C, σ_AR1=5 000 kW, ρ=0.8.
  Day-of-week factor from synthetic generator: [1.0, 1.0, 1.0, 1.0, 1.0, 0.7, 0.6].

D11 (Gansu parity): mode="synthetic" calls generate_year(key) unmodified —
  bit-identical to the current path; this package is not imported.

Pure Python — never called inside jit.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import numpy as np

# §4.2 D19 load parameters (×100 scale, see LINEAGE D19)
_LOAD_BASE_KW:    float = 75_000.0   # kW  (75 MW baseline)
_LOAD_ALPHA_KW:   float = 4_500.0    # kW/°C  (CDD sensitivity)
_LOAD_BETA_KW:    float = 3_750.0    # kW/°C  (HDD sensitivity)
_LOAD_SIGMA_KW:   float = 5_000.0    # kW  (AR1 noise scale)
_LOAD_RHO:        float = 0.8        # AR1 autocorrelation
_LOAD_T_COOL:     float = 26.0       # °C  cooling-degree-day threshold
_LOAD_T_HEAT:     float = 18.0       # °C  heating-degree-day threshold

# Day-of-week factor (day 0 = Monday; same table as generators/synthetic.py)
_DOW_TABLE = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 0.7, 0.6], dtype=np.float32)


def _generate_load(temp_c: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Synthesise load (MW) conditioned on real temperature using the §4.2 D19 formula.

    Formula:
        CDD[t] = max(0, temp_c[t] − T_cool)  (cooling-degree contribution)
        HDD[t] = max(0, T_heat − temp_c[t])  (heating-degree contribution)
        base_kw[t] = 75000 + 4500·CDD + 3750·HDD + φ[t]·5000
        load_mw[t] = (base_kw[t] / 1000) × dow_factor[t % 7]

    where φ is the §4.2 AR(1) process: φ[t] = 0.8·φ[t-1] + sqrt(1−0.8²)·z[t].

    Day-of-week factor: same DOW_TABLE as the synthetic generator (day 0 = Monday
    by convention; does NOT re-align to the historical calendar).

    Args:
        temp_c: Shape (N,), float32 — temperature column from block-bootstrap.
        rng:    NumPy Generator — used for AR(1) noise; same rng that drove bootstrap.

    Returns:
        Shape (N,), float32 — load in MW.
    """
    N = len(temp_c)
    temp = np.asarray(temp_c, dtype=np.float64)

    # CDD / HDD
    cdd = np.maximum(0.0, temp - _LOAD_T_COOL)
    hdd = np.maximum(0.0, _LOAD_T_HEAT - temp)

    # AR(1) noise
    _sig = np.sqrt(1.0 - _LOAD_RHO ** 2)
    z = rng.standard_normal(N)
    phi = np.empty(N, dtype=np.float64)
    phi[0] = z[0]
    for t in range(1, N):
        phi[t] = _LOAD_RHO * phi[t - 1] + _sig * z[t]

    # Base load (kW)
    base_kw = _LOAD_BASE_KW + _LOAD_ALPHA_KW * cdd + _LOAD_BETA_KW * hdd + _LOAD_SIGMA_KW * phi

    # Day-of-week factor
    t_arr = np.arange(N, dtype=np.int32)
    dow = (t_arr // 24) % 7
    dow_factor = _DOW_TABLE[dow].astype(np.float64)

    load_mw = (base_kw / 1000.0) * dow_factor
    return load_mw.astype(np.float32)


# ---------------------------------------------------------------------------
# WeatherPipeline
# ---------------------------------------------------------------------------

class WeatherPipeline:
    """Top-level real-weather pipeline: fetch → cache → transform → bootstrap → sample.

    EMPIRICAL-decade note: the oracle window samples the decade as observed,
    without detrending or bias correction.  Climate nonstationarity (warming,
    solar brightening over the oracle window) is a documented, intended feature.
    (contract §3.5, task #69 input #4)

    Typical use:
        pipeline = WeatherPipeline.from_site_config(site_config, cache_dir=...)
        pipeline.build()                   # fetch + cache + transform (idempotent)
        year_array = pipeline.sample(rng)  # (8760, 4) float32
    """

    def __init__(
        self,
        lat: float,
        lon: float,
        hub_height_m: float,
        oracle_years: int,
        end_year: int,
        source: str = "open_meteo",
        cache_dir: Union[str, Path] = "data/weather_cache",
        block_size_h: int = 24,
    ) -> None:
        self._lat         = float(lat)
        self._lon         = float(lon)
        self._hub_height_m = float(hub_height_m)
        self._oracle_years = int(oracle_years)
        self._end_year    = int(end_year)
        self._source      = source
        self._cache_dir   = Path(cache_dir)
        self._block_size_h = int(block_size_h)

        self._years: list = list(range(end_year - oracle_years + 1, end_year + 1))
        self._blocks       = None   # populated by build()
        self._season_labels = None

    # ------------------------------------------------------------------
    # Class-method constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_site_config(
        cls,
        site_config: dict,
        cache_dir: Union[str, Path, None] = None,
    ) -> "WeatherPipeline":
        """Construct from a parsed site YAML dict.

        Raises:
            ValueError: if location.latitude / location.longitude are missing.
        """
        loc = site_config.get("location", {})
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        if lat is None or lon is None:
            raise ValueError(
                "site_config is missing required location.latitude / location.longitude. "
                "Add a 'location:' block to the site YAML (contract §2.2)."
            )

        weather = site_config.get("weather", {})
        source      = weather.get("source", "open_meteo")
        oracle_years = int(weather.get("oracle_years", 10))
        end_year    = int(weather.get("end_year", 2023))
        block_size_h = int(weather.get("block_size_h", 24))
        _cache_dir  = cache_dir if cache_dir is not None else weather.get("cache_dir", "data/weather_cache")

        # Resolve hub_height_m from the site's wind asset model
        # For the unit tests, a simple fallback of 90m (Gansu vestas hub) is used.
        hub_height_m = cls._resolve_hub_height(site_config)

        return cls(
            lat=lat,
            lon=lon,
            hub_height_m=hub_height_m,
            oracle_years=oracle_years,
            end_year=end_year,
            source=source,
            cache_dir=_cache_dir,
            block_size_h=block_size_h,
        )

    @classmethod
    def _from_test_array(
        cls,
        weather_array: np.ndarray,
        hub_height_m: float = 90.0,
        block_size_h: int = 24,
    ) -> "WeatherPipeline":
        """Test helper: construct directly from a pre-built (N, 3) weather array.

        Skips the fetch/cache/transform pipeline entirely — for unit tests that
        need a WeatherPipeline without network access or Parquet files.
        The array must already be in [v_hub_mps, irr_wm2, temp_c] format.
        """
        from energy_go.data.bootstrap import build_block_pool

        instance = cls.__new__(cls)
        instance._lat          = 0.0
        instance._lon          = 0.0
        instance._hub_height_m = float(hub_height_m)
        instance._oracle_years = weather_array.shape[0] // 8760
        instance._end_year     = 2023
        instance._source       = "test"
        instance._cache_dir    = Path(".")
        instance._block_size_h = block_size_h
        instance._years        = []

        blocks, labels = build_block_pool(weather_array, block_size_h=block_size_h)
        instance._blocks = blocks
        instance._season_labels = labels
        return instance

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Fetch + cache + transform (idempotent — re-runs read the local cache).

        Populates self._blocks and self._season_labels for subsequent sample() calls.
        """
        from energy_go.data.fetch import fetch_weather_history
        from energy_go.data.transform import build_multi_year_array
        from energy_go.data.bootstrap import build_block_pool

        cache_path = fetch_weather_history(
            lat=self._lat,
            lon=self._lon,
            years=self._years,
            cache_dir=self._cache_dir,
            source=self._source,
        )

        weather_array = build_multi_year_array(cache_path, self._hub_height_m)
        self._blocks, self._season_labels = build_block_pool(
            weather_array, block_size_h=self._block_size_h
        )

    def sample(
        self,
        rng: np.random.Generator,
        episode_len_h: int = 8760,
        load_key=None,
    ) -> np.ndarray:
        """Sample one episode year as (8760, 4) float32 array.

        Columns: [v_hub_mps, irr_wm2, temp_c, load_mw]  (same as §4 SyntheticYear).

        Fixed rng seed → identical output (determinism must hold for same pool).

        Args:
            rng:          NumPy Generator (e.g. np.random.default_rng(42)).
            episode_len_h: Must be 8760 in v1.
            load_key:     Reserved for future JAX-key interface; ignored in v1.

        Returns:
            Shape (8760, 4), float32.

        Raises:
            RuntimeError: if build() has not been called (no block pool available).
        """
        if self._blocks is None:
            raise RuntimeError(
                "WeatherPipeline.sample() called before build(). "
                "Call pipeline.build() first to fetch + cache + transform."
            )

        from energy_go.data.bootstrap import sample_bootstrap_year

        # Sample (8760, 3): [v_hub_mps, irr_wm2, temp_c]
        weather = sample_bootstrap_year(
            self._blocks, self._season_labels, rng, block_size_h=self._block_size_h
        )

        # Append §4.2 load column conditioned on real temp_c
        temp_c = weather[:, 2]
        load_mw = _generate_load(temp_c, rng)

        # Assemble (8760, 4): [v_hub, irr, temp, load]
        result = np.stack([weather[:, 0], weather[:, 1], weather[:, 2], load_mw], axis=1)
        return result.astype(np.float32)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_hub_height(site_config: dict) -> float:
        """Return hub_height_m from site_config.assets.wind, or 90.0 as default.

        Full resolution (v1 scope): looks for a `hub_height_m` override on the site
        wind asset; falls back to 90.0 (Gansu vestas-v150-4.2 default).
        Full device_model join is deferred to the resolver integration (post-QA).
        """
        try:
            wind_cfg = site_config["assets"]["wind"]
            return float(wind_cfg.get("hub_height_m", 90.0))
        except (KeyError, TypeError):
            return 90.0


# ---------------------------------------------------------------------------
# Mode switch
# ---------------------------------------------------------------------------

def get_episode_array(
    mode: str,
    key=None,
    pipeline: "WeatherPipeline | None" = None,
    rng: "np.random.Generator | None" = None,
) -> np.ndarray:
    """Return a (8760, 4) float32 episode array via the mode switch.

    mode="synthetic" (D11):
        Calls ``energy_go.generators.synthetic.generate_year(key)`` unmodified.
        Bit-identical to the current path.  The data package is NOT imported.
        ``key`` must be a valid JAX PRNGKey.

    mode="real":
        Calls ``pipeline.sample(rng)`` — returns block-bootstrap weather.
        ``pipeline`` must be a built WeatherPipeline instance.

    Raises:
        ValueError: if mode is not "synthetic" or "real".
    """
    if mode == "synthetic":
        from energy_go.generators.synthetic import generate_year
        return np.array(generate_year(key))
    elif mode == "real":
        if pipeline is None:
            raise ValueError("mode='real' requires a WeatherPipeline instance (pipeline=...).")
        if rng is None:
            raise ValueError("mode='real' requires a NumPy Generator (rng=...).")
        return pipeline.sample(rng)
    else:
        raise ValueError(
            f"Unknown weather mode '{mode}'; expected 'synthetic' or 'real' (contract §3.6)."
        )
