## 12. Real-weather data pipeline (proposal — user approval)
> **Owner:** env-harness-engineer (rl-architect interim until staffed)

**Status: PROPOSAL for user approval.** Feeds the simulation with **real hour-level weather** allocated by **site latitude/longitude**, as an alternative to the §4 synthetic generators. The pure-JAX env is unchanged: the pipeline is an **offline build step** that produces the **same device-array episode format §4 emits** — no network or I/O ever enters the jitted `step`.

### 12.1 Data source

**Primary: Open-Meteo** (historical + forecast archive). Rationale: free, **no API key** (fits a research rebuild), **native hourly** (matches Δt = 1 h, D3), global coverage by lat/lon, single API for both historical reanalysis (ERA5-backed) and forecast. Variables fetched:

| Need | Open-Meteo variable | Used by |
|---|---|---|
| Wind speed | `wind_speed_10m` (m/s) | §3.1 wind power curve, via the §3.1 power-law shear to hub height — keeps the §3.1 model intact and comparable to synthetic. (`wind_speed_100m` fetched as a cross-check only.) |
| Solar irradiance | `shortwave_radiation` (GHI, W/m²) | §3.1 PV `G` |
| Temperature | `temperature_2m` (°C) | §3.1 PV derate `k_T` + §4.2 load CDD/HDD |

- **Fallbacks (noted, not v1 primary):** **NASA POWER** for solar-irradiance validation/cross-check; **ERA5** (CDS API) is research-grade reanalysis but needs auth + heavier access/latency — out of scope for v1, revisitable.
- All incoming units pass through the **one named conversion utility** (§ engineering rules) before becoming canonical MW/°C/W·m⁻² arrays.

### 12.2 Config schema change

Site YAML gains a `location` block:
```yaml
location:
  latitude: 38.5        # decimal degrees
  longitude: 99.9
  elevation_m: 1500     # optional; refines pressure/air-density if modeled
weather:
  mode: synthetic       # "synthetic" (§4) | "real"
  source: open_meteo    # when mode=real
  year: 2023            # historical year to pull
```
This is a **config schema change** (the asset-config/site contract must add `location` + `weather`).

### 12.3 Pipeline shape

`fetch → cache → transform → device array`, all offline:
1. **Fetch** hourly variables for `(latitude, longitude, year)` from the source.
2. **Cache** locally under `data/weather_cache/<source>_<lat>_<lon>_<year>.parquet` (or `.npz`) — deterministic, network hit once; re-runs read cache. Cache key includes source + rounded lat/lon + year.
3. **Transform** to the exact 8760×features device-array episode format that §4 emits (same column order, same units, same dtype) — so the env and the §4 synthetic path are byte-compatible consumers.
4. The env indexes this array with `lax.dynamic_slice` exactly as for synthetic data (§7). **No network in `step`.**

### 12.4 Mode switch, parity, and forecast noise

- **Mode switch:** `weather.mode: synthetic | real`, default **synthetic**. The **Gansu parity case (D11) stays synthetic-only** — real-weather is a toggle that never disturbs the synthetic parity year (same discipline as the §10 enhancements; the parity test asserts `mode == synthetic`).
- **Forecast noise (D6):** mode-agnostic. D6's horizon-scaled multiplicative noise (`x̂_h = x_true_h·(1+ε_h)`) is applied in `_get_obs` to whatever the episode array holds — synthetic or real. So in real mode the agent still faces the D6 forecast-error structure over realized weather (train/eval consistency). Using Open-Meteo's *actual forecast product* as the forecast (instead of D6 noise over realized data) is a **future option**, flagged — kept out of v1 so forecast-error structure is identical across modes.

### 12.5 Location & contract area

- **Code:** new package **`energy_go/data/`** (data acquisition + caching + transform) — kept separate from `energy_go/generators/` (the pure synthetic models) precisely because it does network I/O. It emits the §4-format array the env consumes; the env stays pure and mode-agnostic.
- **Contract area:** **harness** — `contracts/harness/weather_pipeline.md` (offline data-prep/orchestration feeding the env, not the jitted step). It depends on the §4 episode-array format (env area) as its output contract.

### 12.6 Acceptance criteria (for the implementation task)
- Fetching Gansu `(lat, lon, year)` produces a cached file and an 8760×features array matching §4's shape, column order, and units exactly (asserted).
- `mode: synthetic` reproduces the §4 path bit-for-bit (no behavior change when real-weather is off); `mode: real` swaps the array with no change to the env step.
- The Gansu parity config (D11) asserts `weather.mode == synthetic`.
- D6 forecast noise applies identically in both modes (a fixed seed gives the documented noised obs over the chosen base array).
- No network call occurs inside the jitted `step` (the device array is fully materialized at episode setup).

### 12.7 Open questions for the user
1. Open-Meteo as primary (free/no-key/hourly) — agree, or prefer NASA POWER (solar focus) or ERA5 (research-grade, heavier) as primary?
2. Fetch `wind_speed_10m` + apply §3.1 shear (keeps the synthetic-comparable model), or fetch `wind_speed_100m` directly when available?
3. Keep D6 synthetic forecast noise over realized data (train/eval consistency), or use Open-Meteo's real forecast product in real mode?
