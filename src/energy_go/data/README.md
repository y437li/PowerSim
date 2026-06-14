# `src/energy_go/data`

<!-- curated -->
## Purpose

This package implements the real-weather data pipeline described in REBUILD_SPEC §12 (see also `contracts/harness/weather_pipeline.md`). It is a pure Python/NumPy stack (pandas ≥ 2.0, pyarrow ≥ 14.0, requests ≥ 2.31) and is never called inside a JIT-compiled function. It is an optional install group (`weather` in `pyproject.toml`).

The pipeline runs in four stages:

1. **Fetch** (`fetch.py`): retrieves multi-year hourly weather data from the Open-Meteo API (CC BY 4.0 licence) and writes it to a deterministic Parquet cache keyed on `(source, lat, lon, years)`. Subsequent calls with the same key read from cache without a network request.
2. **Transform** (`transform.py`): applies the power-law wind-shear profile — fitting the shear exponent α = clip(ln(v100/v10) / ln(10), 0.0, 0.6) from 10 m and 100 m wind speeds, then extrapolating to hub height — drops leap-year Feb-29 rows, and assembles a multi-year `(N, 3)` array of `[v_hub, ghi, temp_c]`.
3. **Bootstrap** (`bootstrap.py`): constructs one 8760-hour synthetic year via a seasonally-stratified day-aligned block bootstrap (B = 24-hour blocks; 90/92/92/91-day season strata) so that sampled years preserve seasonal structure.
4. **Pipeline and mode switch** (`pipeline.py`): `WeatherPipeline` orchestrates stages 1–3; `get_episode_array` is the top-level entry point that accepts `mode="real"` or `mode="synthetic"`, calling this package for real data and delegating to `generators.synthetic.generate_year` for the synthetic path.

What does NOT live here: the JAX synthetic generator (that is the `generators` package, REBUILD_SPEC §4), JAX env physics (that is the `env` package), and any training or serving logic.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `__init__.py`

> energy_go.data — §12 real-weather data pipeline.

_No public symbols exported._

### `bootstrap.py`

> energy_go.data.bootstrap — seasonally-stratified block bootstrap.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `build_block_pool` | `function` | Partition a multi-year weather array into blocks; assign season labels. |
| `sample_bootstrap_year` | `function` | Sample one 8760h year via seasonally-stratified block bootstrap. |

### `fetch.py`

> energy_go.data.fetch — Open-Meteo fetch + deterministic local cache.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `make_cache_path` | `function` | Return the deterministic Parquet cache path for a (source, lat, lon, years) key. |
| `fetch_weather_history` | `function` | Fetch multi-year hourly weather from Open-Meteo; cache to Parquet. |

### `pipeline.py`

> energy_go.data.pipeline — top-level real-weather pipeline + mode switch.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `WeatherPipeline` | `class` | Top-level real-weather pipeline: fetch → cache → transform → bootstrap → sample. |
| `get_episode_array` | `function` | Return a (8760, 4) float32 episode array via the mode switch. |

### `transform.py`

> energy_go.data.transform — wind-shear transform + episode-array assembly.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `compute_fitted_shear` | `function` | Return hourly fitted-shear exponent α, shape (N,), dtype float32. |
| `extrapolate_to_hub` | `function` | Extrapolate 100m wind to hub height using the power-law profile. |
| `build_multi_year_array` | `function` | Load cached Parquet, apply shear + hub-height transform, drop Feb-29. |
| `build_multi_year_array_from_arrays` | `function` | Transform raw component arrays directly to (N, 3) float32 [v_hub, ghi, temp]. |

<!-- generated:end -->
