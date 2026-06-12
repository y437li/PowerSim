# Contract: `geo_site_api` — workstream A serving surface

**Version:** 1.0.0  
**Area:** serving  
**Owner:** serving-engineer  
**Spec refs:** REBUILD_SPEC §3 (env physics), §8 (composable assets), §12 (weather pipeline); design `docs/design/ux/stage_1_config.md` §4–§8  
**Decisions:** D3 (Δt=1h), D7 (spread clamp), D31/F1 (constant-real dispatch), D32(i) (config validation single-source)  
**Consumes:**  
- `contracts/shared/config_validation.md` v1.0.0 (LOCKED) — `validate()` API + `ValidationResult` schema  
- `contracts/shared/tariff_model_schema.md` v1.0.0 — `TariffRegion`, `TariffBand` derivation  
- `contracts/harness/weather_pipeline.md` v1.0.0 — `WeatherPipeline`, `fetch_weather_history`  
- `contracts/shared/device_model_schema.md` v2.0.0 (LOCKED) — device physics/economics catalogue  
**Task:** #73  

---

## 1. Purpose

This contract defines the REST surface for wizard stage ① (Site Configuration).
It bridges the frontend to the four merged backend packages without adding physics
or validation logic — those live exclusively in their respective packages.

**Single-source-of-truth rule (D18/D32(i)):** all validation rules live in
`energy_go.env.config_validation`. This layer calls `validate()` directly; it does
NOT re-implement any rule in Python/serving or TypeScript/frontend.

---

## 2. Base URL and HTTP conventions

All paths are relative to the FastAPI server root (default port 8000).

**Success:** HTTP 200 for all well-formed requests, including requests whose config
is invalid (`POST /api/site/validate` returns errors in the body, not as HTTP 4xx).

**Client error (HTTP 400):** malformed JSON body, missing required field, out-of-range
parameter, or unknown ID for a **fixed catalog** lookup (tariff region, device model).
Body: `{ "detail": "<human-readable>", "code": "<REASON_CODE>" }`.

**Resource not found (HTTP 404):** used exclusively for **created resources** — specifically,
weather job IDs that do not exist in the server's in-memory job registry. Rationale: a weather
job is a server-created resource with a lifetime; asking for a non-existent job ID has the
semantics of "this resource is gone or never existed" (404). In contrast, looking up a tariff
region or device model ID from a fixed static catalog has the semantics of "bad parameter"
(400 TARIFF_REGION_NOT_FOUND / DEVICE_MODEL_NOT_FOUND) — the catalog is configuration, not
a mutable resource.

**Frontend implication:** the wizard's weather-job poller must handle 404 as a terminal
"job gone" state (e.g., server restart) rather than treating it as a retryable error.
Tariff/device not-found errors are always 400 and indicate a client-supplied bad ID.

**Server error (HTTP 500):** unexpected exception. Body: `{ "detail": "<message>" }`.

**Content-type:** `application/json` throughout.

---

## 3. Endpoint groups

### 3.1 `POST /api/site/validate`

**Purpose:** call the LOCKED `validate()` API and return all errors and warnings.
Never re-implements rules.

**Request body:**

```json
{
  "site_config":    { … },     // required — parsed site YAML content as a dict
  "device_models":  { … }      // optional — parsed device_models.yaml dict;
                               // if absent, device-dependent rules are silently skipped
                               // (config_validation.md §3.3)
}
```

**Response (HTTP 200):**

```json
{
  "errors":   [ <ValidationIssue>, … ],
  "warnings": [ <ValidationIssue>, … ]
}
```

**`ValidationIssue` schema** (mirrors `config_validation.md` §2 exactly):

```json
{
  "rule_id":    "E-CAP-POS",
  "field":      "assets.battery.fleet_capacity_mwh",
  "message":    "fleet_capacity_mwh = -10.0 MWh — must be > 0",
  "constraint": "fleet_capacity_mwh = -10.0 MWh — must be > 0"
}
```

Field types: all strings, all required, none nullable.

**Invariants:**
- `errors` is non-empty iff the config is hard-rejected.
- Empty `errors` AND empty `warnings` → config is fully clean.
- `rule_id` values are stable (never renamed) per LOCKED contract §4/§5.
- Response is HTTP 200 regardless of validation outcome; HTTP 4xx only for malformed requests.
- The endpoint calls `energy_go.env.config_validation.validate(site_config, device_models)`.
  It does NOT call `resolve_site()` (which would raise on errors).

**HTTP 400 triggers:** `site_config` key absent from body; `site_config` is not a dict.

---

### 3.2 `GET /api/tariff/regions`

**Purpose:** list all available tariff region IDs with a one-line summary each.

**Query parameters:** none.

**Response (HTTP 200):**

```json
{
  "schema_version": "1.0.0",
  "regions": [
    {
      "region_id":   "cn-gansu",
      "currency":    "CNY",
      "price_min_yuan_per_mwh":  250.0,
      "price_max_yuan_per_mwh":  780.0,
      "demand_rate_yuan_per_mw_month": 32000.0,
      "provenance":  "public"
    }
  ]
}
```

**Field types and units:**

| Field | Type | Unit | Notes |
|---|---|---|---|
| `region_id` | string | — | stable key (join key with site YAML `tariff_region`) |
| `currency` | string | ISO-4217 | display only; env is ¥-pure |
| `price_min_yuan_per_mwh` | float | ¥/MWh | min value across the full (12,24) table |
| `price_max_yuan_per_mwh` | float | ¥/MWh | max value across the full (12,24) table |
| `demand_rate_yuan_per_mw_month` | float | ¥/MW·month | fixed demand charge rate |
| `provenance` | string | — | `"public"` or `"private"` (runtime-injected by resolver) |

**Invariant:** `price_min ≤ price_max`.

---

### 3.3 `GET /api/tariff/regions/{region_id}`

**Purpose:** full region detail — the complete (12, 24) price table, sell-clamp params,
and TariffBand list for every month.

**Path parameter:** `region_id` — must be a key in the loaded tariff schema.

**Query parameters:** none.

**Response (HTTP 200):**

```json
{
  "region_id":  "cn-gansu",
  "currency":   "CNY",
  "provenance": "public",
  "price_table_yuan_per_mwh": [
    [ 250.0, 250.0, … ],  // month 0 (Jan) — 24 floats
    …                      // months 1–11
  ],
  "demand_rate_yuan_per_mw_month": 32000.0,
  "sell_clamp": {
    "spread_yuan_per_mwh":           30.0,
    "spread_noise_std_yuan_per_mwh": 10.0
  },
  "monthly_bands": [
    {
      "month": 0,
      "bands": [
        {
          "name":               "valley",
          "start_hour":         0,
          "end_hour":           7,
          "price_yuan_per_mwh": 250.0
        },
        …
      ]
    },
    …  // months 0–11 (12 entries total)
  ]
}
```

**`price_table_yuan_per_mwh`:** 12 rows × 24 columns; row index = month (0=Jan … 11=Dec);
column index = hour (0–23, at Δt=1h on :00). Units: ¥/MWh, float.

**`TariffBand` schema:**

| Field | Type | Unit | Notes |
|---|---|---|---|
| `name` | string | — | e.g. `"valley"`, `"mid"`, `"peak"`, `"critical_peak"` |
| `start_hour` | int | hours | inclusive; 0–23 |
| `end_hour` | int | hours | exclusive; 1–24 |
| `price_yuan_per_mwh` | float | ¥/MWh | uniform within band |

**Band derivation (server-side only, per tariff_model_schema §7.1):**
Run-length encoding of `price_table[month]` — each contiguous run of equal prices
becomes one TariffBand. Band names come from a server-side price→name lookup
(Gansu initial: 250 → `"valley"`, 450 → `"mid"`, 620 → `"peak"`, 780 → `"critical_peak"`).
Clients MUST NOT reconstruct band boundaries from the price table; they use `monthly_bands`.

**HTTP 400:** `region_id` not found in the loaded tariff schema. Body:
`{ "detail": "region 'x' not found", "code": "TARIFF_REGION_NOT_FOUND" }`.

**Invariant:** `monthly_bands` always has exactly 12 entries (months 0–11); each band
list covers [0, 24) without gaps or overlaps.

---

### 3.4 `GET /api/tariff/bands/{region_id}`

**Purpose:** TariffBand list for a single month. Lightweight alternative to the full
region detail endpoint, used by the live TOU timeline chart.

**Path parameter:** `region_id`.
**Query parameter:** `month` (int, 0–11, required).

**Response (HTTP 200):**

```json
{
  "region_id": "cn-gansu",
  "month":     0,
  "bands": [
    { "name": "valley", "start_hour": 0,  "end_hour": 7,  "price_yuan_per_mwh": 250.0 },
    { "name": "mid",    "start_hour": 7,  "end_hour": 8,  "price_yuan_per_mwh": 450.0 },
    { "name": "peak",   "start_hour": 8,  "end_hour": 11, "price_yuan_per_mwh": 620.0 },
    { "name": "critical_peak", "start_hour": 11, "end_hour": 12, "price_yuan_per_mwh": 780.0 },
    { "name": "mid",    "start_hour": 12, "end_hour": 18, "price_yuan_per_mwh": 450.0 },
    { "name": "peak",   "start_hour": 18, "end_hour": 19, "price_yuan_per_mwh": 620.0 },
    { "name": "critical_peak", "start_hour": 19, "end_hour": 21, "price_yuan_per_mwh": 780.0 },
    { "name": "peak",   "start_hour": 21, "end_hour": 23, "price_yuan_per_mwh": 620.0 },
    { "name": "valley", "start_hour": 23, "end_hour": 24, "price_yuan_per_mwh": 250.0 }
  ]
}
```

**HTTP 400:** `region_id` not found OR `month` outside [0, 11]. Codes:
`TARIFF_REGION_NOT_FOUND`, `TARIFF_MONTH_OUT_OF_RANGE`.

**Derivation:** same run-length algorithm as §3.3 `monthly_bands`. Single call to
the same `tariff_bands.py` helper.

**Deviation note:** tariff_model_schema §7.1 shows path `GET /api/config/tariff/{region_id}?month=…`.
This contract uses `GET /api/tariff/bands/{region_id}?month=…` for REST consistency
with the `/api/tariff/` namespace. The same server-side TariffBand derivation algorithm
applies; no change to the band format.

---

### 3.5 `POST /api/site/weather/fetch`

**Purpose:** trigger a weather fetch + cache job via `WeatherPipeline`. Long-running;
returns a `job_id` immediately. Poll `GET /api/site/weather/jobs/{job_id}` for status.
Off-wire — not over the telemetry WebSocket.

**Request body:**

```json
{
  "lat":   38.5,
  "lon":   99.9,
  "years": [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023]
}
```

| Field | Type | Unit | Required | Constraint |
|---|---|---|---|---|
| `lat` | float | decimal degrees N/S (+/−) | yes | [−90.0, 90.0] |
| `lon` | float | decimal degrees E/W (+/−) | yes | [−180.0, 180.0] |
| `years` | list[int] | calendar year | yes | 1 ≤ len ≤ 20; all years in [1940, 2024] |

**Response (HTTP 200, job accepted):**

```json
{
  "job_id": "wf_abc123",
  "status": "queued",
  "lat":    38.5,
  "lon":    99.9,
  "years":  [2014, 2015, …, 2023]
}
```

`job_id` is a server-assigned string; opaque to the client.

**HTTP 400:** lat/lon out of range, years list empty or too long, year out of [1940, 2024].
Code: `WEATHER_PARAM_INVALID`.

**Background job:** calls `fetch_weather_history(lat, lon, years, cache_dir)` in a
FastAPI background task (not blocking the event loop). The endpoint returns before the
network fetch completes. On cache hit (all years already cached), the job transitions
`queued → done` without a network call.

---

### 3.6 `GET /api/site/weather/jobs/{job_id}`

**Purpose:** poll the status of a weather fetch job started by §3.5.

**Path parameter:** `job_id` — as returned by `POST /api/site/weather/fetch`.

**Response (HTTP 200):**

Status `"queued"`:
```json
{ "job_id": "wf_abc123", "status": "queued",   "progress_pct": 0 }
```

Status `"running"`:
```json
{ "job_id": "wf_abc123", "status": "running",  "progress_pct": 40 }
```

Status `"done"`:
```json
{
  "job_id":  "wf_abc123",
  "status":  "done",
  "progress_pct": 100,
  "result": {
    "cache_path":        "data/weather_cache/open_meteo_38.50000_99.90000_2014_2023.parquet",
    "years_cached":      [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023],
    "row_count":         87600,
    "wind_mps_mean":     6.34,
    "irr_wm2_mean":      182.5,
    "temp_c_mean":        8.1
  }
}
```

Status `"error"`:
```json
{
  "job_id":        "wf_abc123",
  "status":        "error",
  "progress_pct":  20,
  "error_message": "HTTP 502 from Open-Meteo API for year 2016"
}
```

**`result` field types and units:**

| Field | Type | Unit | Notes |
|---|---|---|---|
| `cache_path` | string | — | relative path from repo root |
| `years_cached` | list[int] | calendar year | years successfully fetched and cached |
| `row_count` | int | rows | total hourly rows in Parquet (N_years × 8760, leap-years included in raw cache) |
| `wind_mps_mean` | float | m/s | mean of `wind_speed_100m` column (raw; no shear transform) |
| `irr_wm2_mean` | float | W/m² | mean of `shortwave_radiation` column |
| `temp_c_mean` | float | °C | mean of `temperature_2m` column |

**HTTP 404:** `job_id` unknown. Code: `JOB_NOT_FOUND`.

**State machine:** `queued → running → done | error`. `done` and `error` are terminal.
Completed jobs are retained in memory for the server lifetime.

---

### 3.7 `GET /api/site/weather-coverage`

**Purpose:** lightweight check whether Open-Meteo ERA5 data is available for given
coordinates. Used by the weather-mode selector availability indicator (stage_1_config §4.1).
Does NOT trigger a fetch — no network call, no cache write.

**Query parameters:**

| Parameter | Type | Unit | Required | Constraint |
|---|---|---|---|---|
| `lat` | float | decimal degrees | yes | [−90.0, 90.0] |
| `lon` | float | decimal degrees | yes | [−180.0, 180.0] |

**Response (HTTP 200):**

```json
{
  "lat":                   38.5,
  "lon":                   99.9,
  "historical_available":  true,
  "available_year_count":  10,
  "year_range":            [2014, 2023],
  "bootstrap_available":   true,
  "source":                "open_meteo"
}
```

If `historical_available` is `false`:
```json
{
  "lat":                   0.0,
  "lon":                   -200.0,
  "historical_available":  false,
  "available_year_count":  0,
  "year_range":            null,
  "bootstrap_available":   false,
  "source":                "open_meteo"
}
```

**Field types and units:**

| Field | Type | Unit | Notes |
|---|---|---|---|
| `lat` | float | decimal degrees N | echoed from request |
| `lon` | float | decimal degrees E | echoed from request |
| `historical_available` | bool | — | true iff Open-Meteo ERA5 covers these coords |
| `available_year_count` | int | calendar years | 0 if not available |
| `year_range` | [int, int] or null | calendar years | [start_year, end_year] inclusive; null if not available |
| `bootstrap_available` | bool | — | true iff historical_available (bootstrap derives from historical) |
| `source` | string | — | `"open_meteo"` (only source in v1) |

**Coverage determination (v1):** Open-Meteo ERA5 covers all land and ocean globally.
For v1, `historical_available` is `true` for all valid lat/lon and `false` only when
the coordinates are outside the valid range. `year_range` defaults to `[2014, 2023]`
(the default 10-year oracle window per weather_pipeline §2.2).

**HTTP 400:** lat/lon out of range. Code: `COVERAGE_PARAM_INVALID`.

---

### 3.8 `GET /api/devices/models`

**Purpose:** list all device models — physics summary + economics summary for the
brand picker (stage_1_config §5.1). No resolver call; reads `device_models.yaml` directly.

**Query parameters:** none.

**Response (HTTP 200):**

```json
{
  "schema_version": "2.0.0",
  "models": {
    "vestas-v150-4.2": {
      "model_id":   "vestas-v150-4.2",
      "type":       "wind_turbine",
      "physics":    { … },
      "economics":  { … }
    },
    …
  }
}
```

Each model entry shape:

```json
{
  "model_id":  "vestas-v150-4.2",
  "type":      "wind_turbine",
  "physics": {
    "v_cutin_mps":         3.0,
    "v_rated_mps":        12.0,
    "v_cutout_mps":       25.0,
    "hub_height_m":      105.0,
    "rated_mw_per_unit":   4.2
  },
  "economics": {
    "capex_per_kw_yuan":           5800.0,
    "opex_fixed_per_kw_year_yuan":  180.0,
    "opex_var_per_mwh_yuan":          0.0,
    "lifetime_years":                25.0
  }
}
```

**All physics and economics fields from `device_model_schema.md` are passthrough.**
The `economics` dict may be empty (`{}`) if no economics block is present in the YAML
(per device_model_schema §1.3: all economics fields optional).

**Units mirror `device_model_schema.md` §1.2/§1.3 exactly:**

| Device type | Field | Unit |
|---|---|---|
| wind_turbine physics | `v_cutin_mps`, `v_rated_mps`, `v_cutout_mps` | m/s |
| wind_turbine physics | `hub_height_m` | m |
| wind_turbine physics | `rated_mw_per_unit` | MW |
| wind_turbine economics | `capex_per_kw_yuan` | ¥/kW |
| wind_turbine economics | `opex_fixed_per_kw_year_yuan` | ¥/kW·yr |
| wind_turbine economics | `opex_var_per_mwh_yuan` | ¥/MWh |
| wind_turbine economics | `lifetime_years` | yr |
| pv_panel physics | `k_T_per_c` | /°C |
| pv_panel physics | `eta_inverter` | — (dimensionless, ∈ (0,1]) |
| pv_panel physics | `degradation_yr1` | — (dimensionless, ∈ (0,1]) |
| pv_panel economics | `capex_per_kw_yuan` | ¥/kW |
| battery physics | `eta_ch`, `eta_dis` | — (dimensionless) |
| battery physics | `soc_min`, `soc_max` | — (dimensionless) |
| battery physics | `capacity_mwh_per_unit` | MWh |
| battery physics | `power_mw_per_unit` | MW |
| battery economics | `capex_energy_per_kwh_yuan` | ¥/kWh |
| battery economics | `capex_power_per_kw_yuan` | ¥/kW |
| grid_connection physics | `max_export_mw`, `max_import_mw` | MW |
| grid_connection economics | `capex_lump_sum_yuan` | ¥ |

**Invariant:** `model_id` in each entry matches its map key verbatim. No model is
omitted (full catalogue is returned).

---

### 3.9 `GET /api/devices/models/{model_id}`

**Purpose:** single-model detail. Same schema as one entry from §3.8 `models`.

**Path parameter:** `model_id` — must match a key in `device_models.yaml`.

**Response (HTTP 200):** same as the per-entry shape in §3.8.

**HTTP 400:** `model_id` not found. Code: `DEVICE_MODEL_NOT_FOUND`.

---

### 3.10 `GET /api/devices/search`

**Purpose:** autocomplete search for the Device ID field in the fleet table
(stage_1_config §5.1 autocomplete dropdown).

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `q` | string | yes | prefix or substring search against model_id |
| `limit` | int | no | max results; default 10, max 50 |

**Response (HTTP 200):**

```json
{
  "results": [
    {
      "model_id":     "vestas-v150-4.2",
      "type":         "wind_turbine",
      "label":        "Wind turbine · 4.2 MW · 105m hub",
      "rated_output": { "value": 4.2, "unit": "MW" }
    },
    {
      "model_id":     "catl-lmp-300mwh",
      "type":         "battery",
      "label":        "Battery · 300 MWh / 100 MW",
      "rated_output": { "value": 300.0, "unit": "MWh" }
    }
  ]
}
```

**`label` construction rules:**

| `type` | label format |
|---|---|
| `wind_turbine` | `"Wind turbine · {rated_mw_per_unit} MW · {hub_height_m}m hub"` |
| `pv_panel` | `"PV panel · {degradation_yr1 * 100:.0f}% yr-1 · {eta_inverter * 100:.0f}% inverter"` |
| `battery` | `"Battery · {capacity_mwh_per_unit} MWh / {power_mw_per_unit} MW"` |
| `grid_connection` | `"Grid · {max_export_mw} MW export / {max_import_mw} MW import"` |

**`rated_output`:** primary capacity in the most natural unit per device type:
- `wind_turbine` → `{ value: rated_mw_per_unit, unit: "MW" }`
- `pv_panel` → `{ value: <fleet_capacity_mw_per_unit inferred from schema or 0>, unit: "MWp" }`
  — for v1 where no fleet figure per-panel exists, omit `rated_output` or set `null`
- `battery` → `{ value: capacity_mwh_per_unit, unit: "MWh" }`
- `grid_connection` → `{ value: max_export_mw, unit: "MW" }`

**Matching rule:** case-insensitive substring match of `q` against `model_id`.
Empty `q` returns all models (up to `limit`). Results ordered by exact-prefix match
before substring match, then alphabetically within each group.

**HTTP 400:** `limit` > 50 or `limit` < 1. `q` absent.

---

## 4. Common response types

### 4.1 `ValidationIssue` (used by §3.1)

```json
{
  "rule_id":    "E-CAP-POS",
  "field":      "assets.battery.fleet_capacity_mwh",
  "message":    "fleet_capacity_mwh = -10.0 MWh — must be > 0",
  "constraint": "fleet_capacity_mwh = -10.0 MWh — must be > 0"
}
```

All four fields are strings, non-nullable. Shape mirrors `config_validation.md §2`
exactly — no `severity` field (severity is implicit: errors list = hard, warnings
list = soft, per LOCKED contract).

### 4.2 `TariffBand` (used by §3.3, §3.4)

```json
{
  "name":               "valley",
  "start_hour":         0,
  "end_hour":           7,
  "price_yuan_per_mwh": 250.0
}
```

`start_hour` ∈ [0, 23]; `end_hour` ∈ [1, 24]; `end_hour > start_hour`.

---

## 5. Units — explicit registry

The following units are used in this API. Mixing units between endpoints is a
contract violation.

| Quantity | Unit used here | Notes |
|---|---|---|
| Electricity price | ¥/MWh | Never ¥/kWh or cents/kWh |
| Demand charge rate | ¥/MW·month | Never ¥/kW·month |
| Generator power | MW | Never kW |
| Battery energy | MWh | Never kWh in physics fields |
| Battery power | MW | Never kW |
| CAPEX (wind, solar) | ¥/kW | Per device_model_schema economics; kW base |
| CAPEX (battery energy) | ¥/kWh | Per device_model_schema economics |
| CAPEX (grid) | ¥ (lump sum) | Site-specific total |
| O&M (wind, solar) | ¥/kW·yr | Per device_model_schema economics |
| O&M (battery) | ¥/kWh·yr | Per device_model_schema economics |
| Variable O&M | ¥/MWh | All device types |
| Wind speed | m/s | All wind-speed fields |
| Hub height | m | |
| Temperature | °C | |
| Solar irradiance | W/m² | |
| Latitude | decimal degrees N | positive = north |
| Longitude | decimal degrees E | positive = east |
| Tariff month | int | 0=Jan … 11=Dec |
| Tariff hour | int | 0–23, Δt=1h, on :00 (D3) |

---

## 6. Implementation notes

### 6.1 Module placement

All geo/site endpoints live in `src/energy_go/serving/geo_site_api.py` and are
registered on the existing FastAPI `app` via `app.include_router(geo_site_router)`.
No physics, no validation rules here.

### 6.2 Validation endpoint implementation

```python
from energy_go.env.config_validation import validate, ValidationResult

@router.post("/api/site/validate")
async def site_validate(body: SiteValidateRequest) -> SiteValidateResponse:
    result: ValidationResult = validate(
        body.site_config,
        body.device_models,     # may be None
    )
    return SiteValidateResponse(
        errors=[_to_issue_dto(e) for e in result.errors],
        warnings=[_to_issue_dto(w) for w in result.warnings],
    )
```

### 6.3 Tariff band derivation

Lives in `src/energy_go/serving/tariff_bands.py`:

```python
def derive_bands(price_row: list[float]) -> list[TariffBandDTO]:
    """Run-length encode a 24-element hourly price row into TariffBand list."""
```

Band name lookup for Gansu initial data (price → name):
```python
BAND_NAME = {250.0: "valley", 450.0: "mid", 620.0: "peak", 780.0: "critical_peak"}
```
Unknown price values (not in BAND_NAME) → name `"tier_{price:.0f}"`.

### 6.4 Weather job management

Jobs are stored in an in-process dict `Dict[str, WeatherJob]`. `job_id` format:
`"wf_" + uuid4().hex[:8]` (opaque; no guaranteed format). Background tasks use
FastAPI's `BackgroundTasks`. No persistence across server restarts.

Progress reporting: `progress_pct` increments per year fetched:
`100 * years_fetched / total_years`. On cache hit (year file exists), the year counts
as fetched without network I/O.

### 6.5 Device model loading

Loaded once at router initialization from `config/device_models.yaml` (same path as the
resolver default). Reload on `SIGHUP` is out of scope for v1.

### 6.6 D32(i) compliance

`POST /api/site/validate` is the sole entry point for validation in the serving layer.
No other endpoint calls `resolve_site()` as a validation side-effect.

---

## 7. Deliberate deviations

| Item | Source / expected | Deviation | Reason |
|---|---|---|---|
| Tariff band endpoint path | `tariff_model_schema §7.1`: `GET /api/config/tariff/{id}?month=…` | `GET /api/tariff/bands/{id}?month=…` | REST consistency with `/api/tariff/` namespace; same derivation algorithm |
| `POST /api/site/validate` HTTP status on invalid config | Some REST patterns return 422 | Returns HTTP 200 with non-empty `errors` list | Validation outcome is domain data, not a protocol error; the config may be partially valid with warnings |
| Weather coverage v1 | stage_1_config §4.1 implies a real availability API | v1 returns `true` for all valid lat/lon (Open-Meteo has global coverage) | Simplification for v1; real per-coordinate availability check deferred |

---

## 8. Out of scope

- `POST /api/site/config` / `PUT /api/site/config/{hash}` — site config persistence and
  `config_hash` generation (separate contract `site_config_persistence.md`, future task)
- `GET /api/site/resolve` — derived diagnostics (C-rate, storage duration, PCC coverage ratio,
  unit counts, site totals strip) for the green-badge UI (config_validation §11.1 note;
  separate contract `site_resolve.md`, future task)
- Custom tariff upload (v2 per stage_1_config §6)
- Non-default weather source (only `"open_meteo"` in v1)
- Private-overlay tariff/device entries in API responses — provenance field present;
  the overlay mechanism itself is not re-spec'd here (PR #68 authority)
- WebSocket-based weather progress streaming (off-wire per task description; use polling)
- Batch weather fetch for multiple coordinates in one request
- Scenario composition endpoints (v2, §8 composable assets)

---

## 9. Test file

`tests/serving/test_serving_geo_site_api.py`

See the test file for complete case coverage. Key invariants verified by tests:

1. `POST /api/site/validate` — passes Gansu config clean (0 errors, 0 warnings);
   returns errors for hard violations; returns warnings for soft violations; works
   without `device_models` (silently skips device-dependent rules).
2. `GET /api/tariff/regions` — returns all regions; each entry has required fields;
   `price_min ≤ price_max`; units are ¥/MWh.
3. `GET /api/tariff/regions/{region_id}` — Gansu: (12, 24) table; 12 monthly_bands entries;
   each month's bands cover [0, 24) without gaps; `price_yuan_per_mwh` values match LOCKED
   Gansu vector.
4. `GET /api/tariff/bands/{region_id}?month=0` — Gansu month-0 bands match expected RLE;
   unknown region → 400 TARIFF_REGION_NOT_FOUND; month=12 → 400 TARIFF_MONTH_OUT_OF_RANGE.
5. `POST /api/site/weather/fetch` — returns job_id + status=queued; validates lat/lon/years;
   out-of-range params → 400.
6. `GET /api/site/weather/jobs/{job_id}` — unknown job → 404; queued/running/done/error states
   all deserialize correctly.
7. `GET /api/site/weather-coverage` — valid coords → historical_available=true; out-of-range
   lat/lon → 400.
8. `GET /api/devices/models` — returns all 4 Gansu models; `vestas-v150-4.2` physics fields
   match LOCKED device_model_schema values (MW units); economics fields present.
9. `GET /api/devices/models/{model_id}` — unknown → 400; known → correct physics+economics.
10. `GET /api/devices/search?q=vestas` — returns vestas model; `q=catl` returns battery model;
    empty q returns all; limit=1 returns exactly 1.
