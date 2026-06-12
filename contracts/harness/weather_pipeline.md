# Contract: weather_pipeline — §12 Real-Weather Data Pipeline

- **Area:** harness
- **Branch:** `feat/harness-weather-pipeline`
- **Version:** 1.0.0
- **Spec sections:** §12 (weather pipeline), §4.1 (synthetic weather — episode array format),
  §4.2 (load generator), §3.1 (wind power curve, hub-height extrapolation), §7 (JAX device array)
- **Design study:** `docs/design/section12_historical_weather_design.md` (team-lead APPROVED,
  PR #77 @ `b0ae5fd`; Fable gate closed 2026-06-11)
- **Decisions:** D3 (Δt=1h, episode=8760h), D6 (horizon-scaled forecast noise, mode-agnostic),
  D11 (Gansu parity stays synthetic), D19 (load scale ×100), D31/F1 (constant-real-price),
  task #69 inputs (100m primary wind, fitted shear, 10yr oracle, EMPIRICAL non-detrend)
- **Status:** DRAFT — awaiting backend-reviewer APPROVE before implementation
- **Review record:** `contracts/reviews/weather_pipeline.md` (to be created by reviewer)
- **Depends on:**
  - `energy_go.generators.synthetic.generate_year` (LOCKED PR #33) — §4 episode array format
    `SyntheticYear = jax.Array`, shape `(8760, 4)` float32, columns `[wind_mps, irr_wm2, temp_c, load_mw]`
  - `contracts/shared/device_model_schema.md` v1.0.0 (LOCKED PR #79) — `hub_height_m` per turbine model
  - Site YAML `location` block (§12.2 config schema change — **new fields added by this contract**):
    see §2.2 below
- **Open-Meteo attribution:** license check is a hard gate for implementation (§4.1 licensing note).
  Caching for local research use is clearly permitted; bundling a derived array in the repo
  needs Copernicus/Open-Meteo attribution confirmation. Implementation-stage blocker.

---

## 1. Scope

The weather pipeline is an **offline build step** that fetches real historical weather from
Open-Meteo (ERA5-backed), caches it, applies the hub-height shear transform, and produces
the **same (8760, 4) float32 device-array episode format** that `generate_year` emits — so
the JAX env and the §4 synthetic path are byte-compatible consumers. **No network I/O ever
enters the jitted `step`.**

New package: `energy_go/data/` (separate from `energy_go/generators/` because it does
network I/O; the pure synthetic generator remains unchanged).

**v1 primary generator:** seasonally-stratified **block bootstrap** (approach (b) from the
design study — real joint wind/solar/temperature structure, §7-device-native, unlimited,
easiest to validate). Unlimited years come from randomly stitching day-aligned blocks
from the multi-year historical pool.

**In scope for v1:**
- Multi-year Open-Meteo fetch + deterministic local cache
- Fitted wind-shear transform (100m primary; extrapolate to hub_height_m)
- Day-aligned block bootstrap (B=24, season-stratified)
- Episode-array assembly (real weather + synthetic load conditioned on real temp)
- Mode switch: `weather.mode: synthetic | real`, default `synthetic`
- Gansu parity unchanged: D11's `mode: synthetic` path is bit-identical to `generate_year`

**Out of scope for v1 (explicitly deferred):**
- Regime-switching generator (design study §5, v2)
- VAR parametric device fallback (design study §5, v2)
- Copula / VAE-GAN (parked)
- Week-aligned blocks (B=168) — spec'd below but NOT a v1 acceptance criterion
- Online Open-Meteo forecast product as the D6 noise source (flagged in §12.4)
- ERA5 direct access (CDS API, auth required)
- NASA POWER primary source
- Bundling pre-cached arrays in the repo (licensing confirmation required first)

---

## 2. Data schemas

### 2.1 Episode array (output — matches §4 exactly)

```
SyntheticYear = np.ndarray  # shape (8760, 4), dtype float32
```

Column layout **exactly matches** `energy_go.generators.synthetic.SyntheticYear`:

| Index | Name | Unit | Source (real mode) |
|-------|------|------|--------------------|
| 0 | `wind_mps` | m/s | v_hub from fitted-shear extrapolation (§3 below) |
| 1 | `irr_wm2` | W/m² | `shortwave_radiation` from Open-Meteo |
| 2 | `temp_c` | °C | `temperature_2m` from Open-Meteo |
| 3 | `load_mw` | MW | §4.2 synthetic load conditioned on real `temp_c` (see §3.4) |

`wind_mps` in column 0 is the **hub-height** wind speed fed directly to the §3.1 power
curve. In real mode it is v_hub (not the raw 10m or 100m fetch value).

### 2.2 Site YAML — new `location` and `weather` blocks (§12.2)

```yaml
location:
  latitude: 38.5          # decimal degrees N (+) / S (−)
  longitude: 99.9         # decimal degrees E (+) / W (−)
  elevation_m: 1500       # optional; reserved for future air-density refinement

weather:
  mode: synthetic          # "synthetic" (§4, default) | "real"
  source: open_meteo       # when mode=real; only "open_meteo" in v1
  oracle_years: 10         # number of historical years to fetch (default 10, configurable)
  end_year: 2023           # inclusive; pipeline fetches [end_year-oracle_years+1, end_year]
  block_size_h: 24         # 24 = day-aligned (default); 168 = week-aligned (config option)
  cache_dir: "data/weather_cache"  # local cache root (relative to repo root, or absolute)
```

**Backward compatibility:** `location` and `weather` blocks are optional. Sites with
`weather.mode: synthetic` (or no `weather` block) are fully backward-compatible — the
resolver returns the §4 synthetic path unchanged. No existing site YAML breaks.

### 2.3 Cache format

One Parquet file per (source, lat_rounded, lon_rounded, year):
```
data/weather_cache/<source>_<lat5>_<lon5>_<year>.parquet
```
- `lat5` = latitude rounded to 5 decimal places (e.g. `38.50000`)
- `lon5` = longitude rounded to 5 decimal places (e.g. `99.90000`)
- Float rounding is for cache-key stability; Open-Meteo actually snaps to its grid.

Cache columns (raw fetch, before unit conversions):

| Column | Open-Meteo variable | dtype |
|--------|---------------------|-------|
| `wind_speed_10m` | `wind_speed_10m` | float32 |
| `wind_speed_100m` | `wind_speed_100m` | float32 |
| `shortwave_radiation` | `shortwave_radiation` | float32 |
| `temperature_2m` | `temperature_2m` | float32 |
| `time` | `time` (ISO-8601) | str / datetime |

All values are hourly, calendar-aligned. N rows = 8760 × oracle_years (leap years normalised
to 8760h by dropping Feb 29 entirely — see §3.2).

### 2.4 Multi-year array (intermediate, in-memory)

After transform, before bootstrap:
```
WeatherArray = np.ndarray  # shape (N_hours, 3), dtype float32
```
Columns: `[v_hub_mps, irr_wm2, temp_c]` (load not included here — synthesized at episode-assembly time).

N_hours = oracle_years × 8760 (exact, after Feb-29 drop).

### 2.5 Block pool

```
BlockPool = np.ndarray      # shape (N_blocks, block_size_h, 3), dtype float32
SeasonLabels = np.ndarray   # shape (N_blocks,), dtype int8 — {0=DJF, 1=MAM, 2=JJA, 3=SON}
```

Season boundaries (calendar day-of-year, 0-indexed, non-leap):
- DJF (0): days 0–58 (Jan+Feb) ∪ days 334–364 (Dec)  → 90 days per year
- MAM (1): days 59–150 (Mar+Apr+May)                  → 92 days per year
- JJA (2): days 151–242 (Jun+Jul+Aug)                 → 92 days per year
- SON (3): days 243–333 (Sep+Oct+Nov)                 → 91 days per year
Total: 90+92+92+91 = 365 days ✓

A block's season label = season of its **first day**. With default B=24, each block is
exactly one calendar day; the season label is exact.

---

## 3. Behaviour specification

### 3.1 Wind reference height and fitted shear (task #69 inputs #1, #2)

**Primary wind source: `wind_speed_100m`** (not 10m). Rationale: modern Gansu turbine
hubs are 90–140m; ERA5 100m data is far more accurate than a 10m→hub extrapolation through
the full surface-layer profile. (`wind_speed_10m` is fetched as a secondary variable purely
for computing the fitted shear exponent α.)

**Fitted shear computation** (hourly per-step):

```
α[t] = clip( ln(v100[t] / v10[t]) / ln(100 / 10),  lo=0.0,  hi=0.6 )
```

- `ln(100/10) = ln(10) ≈ 2.302585` (pre-computed constant, never recalculated per step)
- Stability flags:
  - If `v10[t] ≤ 0.0` OR `v100[t] ≤ 0.0`: α[t] = 0.14 (neutral atmosphere default)
  - If `v100[t] / v10[t] ≤ 0` or `ln(...)` is NaN/±Inf: α[t] = 0.14
  - Clip [0.0, 0.6] applied after the above (so negative raw α → 0.0, >0.6 → 0.6)
- `0.14` is the standard neutral-atmosphere Hellman exponent; used only as a fallback
  when the two-height ratio produces an invalid or degenerate value.

**Hub-height extrapolation** (using the 100m value as the anchor):

```
v_hub[t] = v100[t] * (hub_height_m / 100.0) ^ α[t]
```

- `hub_height_m` sourced from the resolved device model (e.g. Gansu v150-4.2: 90m).
- If `v100[t] ≤ 0.0`: v_hub[t] = 0.0 (no wind, regardless of α).

### 3.2 Leap year normalisation

Calendar years from Open-Meteo may contain 8784h (leap year). **Drop February 29 entirely**
(hours 1416–1439: Jan 744h + Feb 1–28 672h = offset 1416; 24 hours dropped) to produce
exactly 8760h per year. This is
consistent with the §4 synthetic generator which always emits 8760h. The discarded hours
are not blended — they are simply absent from the pool (Feb-29 weather is effectively
replaced by nearby Mar-1 blocks when blocks are sampled).

### 3.3 Block bootstrap (day-aligned default)

Episode year generation with `block_size_h=24` (default):

1. **Partition** the multi-year array into N_blocks = N_hours / 24 non-overlapping
   day-length blocks. Block k covers hours [k×24, (k+1)×24).
2. **Label** each block with its season (§2.5 season boundaries).
3. **Stratified sample:** to assemble one 8760h episode year, sample **with replacement**:
   - 90 DJF blocks from the DJF pool
   - 92 MAM blocks from the MAM pool
   - 92 JJA blocks from the JJA pool
   - 91 SON blocks from the SON pool
   Total: 365 blocks × 24h = 8760h ✓
4. **Concatenate** sampled blocks in DJF→MAM→JJA→SON order (i.e. Jan-Feb first,
   then Mar–May, …, Dec last — matching the calendar order of the synthetic year).
5. **Overlap blend (v1: OFF by default):** no smoothing applied at block boundaries.
   The `boundary_acf_dip` statistic should be measured during validation (see §5.2).
   A future config option `overlap_blend_h: 0` (default) | `1` | `2` can be added
   without a contract amendment — it does not change the output schema.

**Week-aligned blocks (B=168, config option):** use 52 week-blocks (52×168=8736h) +
1 additional day-block (24h), both drawn from the stratified pool matching the
52nd week's season. Total: 52×168 + 24 = 8760h. This schema is **specified but not
a v1 acceptance criterion** — it requires explicit `block_size_h: 168` in the site YAML.

### 3.4 Load: §4 synthetic conditioned on real temperature

**Decision (contract-stage flag #1, PR #77 approval):** load column uses the
**§4.2 formula conditioned on the real temperature** from the block data. It does NOT
replay historical metered load. Rationale: Gansu industrial load is temperature-driven
(CDD/HDD); the §4 load model (with D19 scaling) is calibrated to the right magnitude;
using real temperature preserves the wind/solar/temperature/load cross-correlation via
the dominant thermal driver, without requiring historical metered load (unavailable in
public data) and without the weekday/weekend alignment complexity.

Concretely, `load_mw[t]` is computed from the §4.2 AR(1)-on-temperature formula:

```
load_mw[t] = base + α_load·CDD[t] + β_load·HDD[t] + φ[t]·σ_load
```
where `CDD[t] = max(0, temp_c[t] - T_cool)`, `HDD[t] = max(0, T_heat - temp_c[t])`,
`φ[t]` is the §4.2 AR(1) noise process (with a fresh JAX key per episode), and the
D19 ×100 scaling is applied. The synthetic week-day-of-week factor is preserved (day 0 =
Monday by convention, matching the §4 generator; day-of-week does not re-align to
historical calendar).

Parameters (D19): `base=75_000 kW`, `α=4_500 kW/°C`, `β=3_750 kW/°C`, `σ_AR1=5_000 kW`,
`ρ=0.8`, `T_cool=26°C`, `T_heat=18°C` (same as §4.2 reference implementation).

### 3.5 Climate nonstationarity — EMPIRICAL, NOT detrended (task #69 input #4)

The 10-year oracle window (default 2014–2023) straddles the ongoing warming and
solar-brightening trend. **The generator samples the EMPIRICAL decade — no detrending,
no bias correction, no recent-year weighting.** This is a deliberate choice recorded
in the contract per rl-architect's task #69 binding input:

- **Documented, intended:** the empirical-decade distribution IS the target; it reflects
  what this site actually experienced.
- **Not a silent omission:** operators who want a detrended or climate-scenario-shifted
  version can adjust `end_year` and `oracle_years`, or implement a per-variable shift
  as a pre-processing step outside this contract's scope.
- Climate nonstationarity must be called out in the docstring of `WeatherPipeline` and
  in the `fetch_weather_history` docstring.

### 3.6 Mode switch

The `weather.mode` field in site YAML controls the episode source:

- `synthetic` (default): `generate_year(key)` is called unchanged. The weather pipeline
  package is not imported. Bit-for-bit identical to today's behavior (D11 parity preserved).
- `real`: `WeatherPipeline(site_config).sample(rng_key, episode_len_h=8760)` is called
  instead. Returns the same (8760, 4) float32 array.

The env's `reset()` / episode-setup code makes this switch; the jitted `step` is
**completely unaffected** — it always indexes a pre-materialized device array.

### 3.7 D6 forecast noise — mode-agnostic (unchanged)

The D6 horizon-scaled multiplicative forecast noise (`x̂_h = x_true_h·(1+ε_h)`) is applied
in `get_obs` to whatever the episode array holds — synthetic or real. The weather pipeline
produces raw realised values; the obs-layer applies noise on top. This is unchanged from
the current synthetic path and requires no contract amendment.

---

## 4. Public API

### 4.1 `energy_go.data.fetch`

```python
def fetch_weather_history(
    lat: float,
    lon: float,
    years: list[int],                           # e.g. list(range(2014, 2024))
    cache_dir: str | Path = "data/weather_cache",
    source: str = "open_meteo",                 # only "open_meteo" in v1
    variables: tuple[str, ...] = (
        "wind_speed_10m",
        "wind_speed_100m",
        "shortwave_radiation",
        "temperature_2m",
    ),
) -> Path:
    """Fetch multi-year hourly weather from Open-Meteo; cache to Parquet.

    Returns the path to the (merged, multi-year) cache file:
        <cache_dir>/<source>_<lat5>_<lon5>_<start_year>_<end_year>.parquet

    On cache hit (file exists), returns the path immediately — no network call.
    On cache miss, fetches year-by-year (one HTTP request per year), merges,
    and writes the Parquet file.

    Leap years are retained in the cache (raw); Feb-29 dropping happens in
    `build_multi_year_array`, NOT here.

    Climate nonstationarity: the fetched record is EMPIRICAL. No detrending,
    no bias correction, no weighting — the decade as observed.
    """
```

Raises:
- `RuntimeError` if the HTTP request fails and no cache exists.
- `ValueError` if `source` is not `"open_meteo"`.

### 4.2 `energy_go.data.transform`

```python
def compute_fitted_shear(
    v10_mps: np.ndarray,    # shape (N,), float, m/s; raw 10m fetch
    v100_mps: np.ndarray,   # shape (N,), float, m/s; raw 100m fetch
) -> np.ndarray:
    """Return α array, shape (N,), float32.

    Per-step:  α[t] = clip( ln(v100[t]/v10[t]) / ln(10),  lo=0.0, hi=0.6 )
    Stability flag: α[t] = 0.14 when v10[t]<=0 OR v100[t]<=0 OR ratio invalid.
    ln(10) ≈ 2.302585 is pre-computed; never recalculated per step.
    """

def extrapolate_to_hub(
    v100_mps: np.ndarray,   # shape (N,), float32, m/s
    alpha: np.ndarray,      # shape (N,), float32, clipped [0.0, 0.6]
    hub_height_m: float,    # e.g. 90.0
) -> np.ndarray:
    """Return v_hub array, shape (N,), float32, m/s.

    v_hub[t] = v100[t] * (hub_height_m / 100.0) ** alpha[t]
    When v100[t] <= 0: v_hub[t] = 0.0.
    """

def build_multi_year_array(
    cache_path: str | Path,
    hub_height_m: float,
) -> np.ndarray:
    """Load cached Parquet, apply shear+hub-height transform, drop Feb-29.

    Returns shape (N_hours, 3), float32: [v_hub_mps, irr_wm2, temp_c].
    N_hours = oracle_years * 8760.
    irr_wm2: raw shortwave_radiation (W/m²) — no unit conversion needed.
    temp_c: raw temperature_2m (°C) — no unit conversion needed.
    """
```

### 4.3 `energy_go.data.bootstrap`

```python
def build_block_pool(
    weather_array: np.ndarray,  # shape (N_hours, 3), float32
    block_size_h: int = 24,     # 24 (day-aligned) or 168 (week-aligned)
) -> tuple[np.ndarray, np.ndarray]:
    """Partition multi-year array into blocks; assign season labels.

    Returns:
        blocks        — shape (N_blocks, block_size_h, 3), float32
        season_labels — shape (N_blocks,), int8 in {0,1,2,3}
    N_blocks = N_hours // block_size_h  (must divide exactly; raises ValueError if not).
    Season of block k: season of day k*block_size_h//24 (0-indexed day-of-year mod 365).
    """

def sample_bootstrap_year(
    blocks: np.ndarray,          # shape (N_blocks, B, 3), float32
    season_labels: np.ndarray,   # shape (N_blocks,), int8
    rng: np.random.Generator,    # e.g. np.random.default_rng(seed)
    block_size_h: int = 24,      # must match blocks.shape[1]
) -> np.ndarray:
    """Sample one 8760h year via seasonally-stratified block bootstrap.

    Day-aligned (B=24): draws 90 DJF + 92 MAM + 92 JJA + 91 SON blocks (365 total).
    Concatenates in DJF→MAM→JJA→SON calendar order.
    Returns shape (8760, 3), float32: [v_hub_mps, irr_wm2, temp_c].

    Week-aligned (B=168): draws 52 week-blocks (season = first day) + 1 extra day-block
    from the 52nd week's season pool. Total: 52*168 + 24 = 8760h.
    """
```

### 4.4 `energy_go.data.pipeline`

```python
class WeatherPipeline:
    """Top-level real-weather pipeline.

    EMPIRICAL-decade note: the oracle window samples the decade as observed,
    without detrending or bias correction. Climate nonstationarity (warming,
    solar brightening) is a documented, intended feature of this pipeline.

    Typical use:
        pipeline = WeatherPipeline.from_site_config(site_config, cache_dir=...)
        pipeline.build()                  # fetch + cache + transform (idempotent)
        year_array = pipeline.sample(rng) # (8760, 4) float32
    """

    @classmethod
    def from_site_config(
        cls,
        site_config: dict,              # parsed site YAML dict
        cache_dir: str | Path | None = None,
    ) -> "WeatherPipeline":
        """Construct from a site_config dict (requires location + weather blocks)."""

    def build(self) -> None:
        """Fetch + cache + transform (idempotent — re-runs read cache).

        Raises ConfigValidationError with rule_id="E-WEATHER-REGION" if
        `location.latitude` / `location.longitude` are missing from the site config.
        """

    def sample(
        self,
        rng: np.random.Generator,
        episode_len_h: int = 8760,
        load_key: "jax.Array | None" = None,  # JAX RNG key for §4.2 load AR(1); None → use rng
    ) -> np.ndarray:
        """Sample one episode year as (8760, 4) float32 array.

        Columns: [v_hub_mps, irr_wm2, temp_c, load_mw].
        Calls sample_bootstrap_year → appends §4.2 load conditioned on real temp_c.
        Fixed rng seed → identical output (determinism must hold).
        """
```

---

## 5. Acceptance criteria

### 5.1 Schema & shape invariants (must-pass before implementation)
- `sample()` returns shape `(8760, 4)`, dtype `float32` — identical to `SyntheticYear`.
- All values finite (no NaN, no ±Inf) — both real and synthetic paths.
- `wind_mps` (column 0) ∈ [0.0, 25.0] after hub extrapolation (not enforced by clip, but a
  violated upper bound triggers a test failure — it means extreme events are physically
  implausible and signals a transform bug).
- `irr_wm2` ≥ 0.0 (no negative solar irradiance).
- `load_mw` > 0.0 for all hours (load baseline 75 MW minus AR1 fluctuations; this always holds
  at D19 scale).

### 5.2 Physics correctness
- Fitted shear: hand-computed values verified (see test file §6).
- Hub extrapolation: hand-computed values verified.
- Block count: `N_hours % block_size_h == 0` always holds (ValueError if not).
- Season boundaries: blocks 0–58 → DJF (label 0); block 59 → MAM (label 1); block 150 → MAM;
  block 151 → JJA (label 2); block 334 → DJF (Dec, label 0).

### 5.3 Mode parity (D11)
- `mode: synthetic` path calls `generate_year(key)` unmodified; the WeatherPipeline package
  is not imported; the result is bit-identical to the current path.

### 5.4 Determinism
- Fixed `rng = np.random.default_rng(42)` → identical episode array across two calls.

### 5.5 Cache idempotency
- Two consecutive `build()` calls produce the same Parquet file (no second HTTP request if
  file exists).
- Cache path is deterministic from `(source, lat, lon, start_year, end_year)`.

### 5.6 Climate nonstationarity: no detrending applied
- The multi-year array from `build_multi_year_array` contains the EMPIRICAL values, not
  a detrended version — mean and trend preserved, asserted by comparing raw vs processed
  means (they must be equal to float32 precision for the temperature column).

---

## 6. Deliberate deviations from §12 spec

| §12 spec text | Deviation | Reason |
|---|---|---|
| §12.1: "Fetch `wind_speed_10m`; use §3.1 power-law shear to hub height" | **v_100m PRIMARY; fitted α** (task #69 #1, #2) | 100m ERA5 data is ~50m closer to hub than 10m; fitted α from v100/v10 ratio is more accurate than fixed α=0.14 in Gansu's stable nocturnal boundary layer |
| §12.1: Single historical year | **Multi-year oracle (10yr default)** (task #69 #3, design study) | Combinatorial unlimited bootstrap requires multi-year pool; block-bootstrap only as realistic as the pool is diverse |
| §12.3: "fetch → cache → transform → device array" (one year) | **Offline build + block-bootstrap; `sample()` returns a new year each call** | Design study approved approach (b); provides unlimited realistic years |
| §12.4: "real weather mode swaps the array" | **Real mode also uses §4.2 synthetic load on real temp** (contract flag #1) | Historical metered load is unavailable in public data; thermal co-movement preserved via temp; day-of-week alignment complexity avoided |
| §12.7 Q2: "fetch v_10m + shear" open question | **RESOLVED: v_100m primary** (task #69 #1) | Closed by rl-architect / USER inputs |
| §12.7 Q4: climate nonstationarity open question | **RESOLVED: EMPIRICAL decade, NOT detrended** (task #69 #4) | rl-architect: "state explicitly, document, intentional" |

---

## 7. Out of scope

- Regime-switching generator (v2, deferred)
- VAR parametric fallback (v2, deferred)
- Copula / neural-generative models (parked — design study §5)
- Online Open-Meteo forecast product as D6 noise source (flagged, future option)
- ERA5 direct CDS API access
- Bundling pre-fetched data in the public repo (licensing gate)
- Per-unit wind shear (single-turbine-model fleet assumed in v1)
- Non-Gansu sites (§8 devices not in scope for this contract)
- SOC / efficiency / §10 enhancement interactions (E2/E5 are separate tasks)
