# Contract: `site_assemble` — wizard-form → resolved site_config

**Version:** 1.0.0
**Area:** serving
**Owner:** serving-engineer
**Spec refs:** REBUILD_SPEC §3 (env physics), §8 (composable assets)
**Decisions:** D18 (single-validator), D26 (two-tier validation), D32(b) (single-config source),
D37 (assembly lives in one Python implementation — this contract)
**Consumes:**
- `contracts/shared/config_validation.md` v1.0.0 (LOCKED) — `validate()` API + `ValidationResult` schema
- `contracts/shared/tariff_model_schema.md` v1.0.0 (LOCKED) — tariff region keyed lookup
- `contracts/shared/device_model_schema.md` v2.0.0 (LOCKED) — per-unit physics catalogue
- `contracts/serving/geo_site_api.md` v1.0.0 — `POST /api/site/validate` (unchanged; both
  endpoints call the same single-source validator)
**Task:** #6
**Frontend advisory:** frontend-engineer (wizard #102 is the consumer)

---

## 1. Purpose

This contract defines `POST /api/site/assemble` — the missing piece between the
wizard stage ① UI (task #2) and the env harness / training pipeline.

**Problem it solves (D37):** The wizard collects a user-friendly form
(`{fleet: [{model_id, count}], tariff_region, site_meta}`). The resolver needs a
canonical category-keyed site_config dict. Computing the assembly — fleet count ×
per-unit MW/MWh from the device model catalogue — MUST live in ONE Python
implementation, not be duplicated in frontend TypeScript.

**Design choice: assemble + validate in one round-trip.**
The endpoint assembles the canonical site_config, immediately calls
`config_validation.validate()` on it, and returns both the assembled config and
the validation result. Rationale: the wizard debounces every 300 ms and needs both
pieces in a single call; no extra round-trips vs the wizard's existing flow.

**`POST /api/site/validate` is unchanged.** It still accepts a resolved dict and
is the entry point for other consumers (harness, CLI). Both endpoints call the
same `config_validation.validate()` — the single source of truth per D18/D32(i).

**Single-source rule (D18/D26/D32(b)/D37):** all fleet-aggregate and tariff
assembly logic lives in `src/energy_go/serving/site_assembly.py`. No physics
computation in the endpoint handler, no duplication in TypeScript.

---

## 2. Endpoint

### 2.1 `POST /api/site/assemble`

**Purpose:** Convert wizard form data into the canonical resolved `site_config` dict
and immediately validate it, returning the result in one response.

**HTTP conventions** (same as `geo_site_api.md §2`):
- HTTP 200: request was syntactically valid; body contains assembled config + validation result.
  Even when `errors` is non-empty, the response is HTTP 200 (validation outcome is domain data).
- HTTP 400: malformed request — missing required field, unknown catalog ID, invalid count.
  Body: `{ "detail": "<human-readable>", "code": "<REASON_CODE>" }`.
- HTTP 500: unexpected exception.

---

## 3. Request body

```json
{
  "fleet": [
    { "model_id": "vestas-v150-4.2",     "count": 146 },
    { "model_id": "trina-vertex-n-670w",  "fleet_capacity_mw": 330.0 },
    { "model_id": "catl-lmp-300mwh",      "count": 1  },
    { "model_id": "pcc-substation-945mw" }
  ],
  "tariff_region": "cn-gansu",
  "site_meta": {
    "name":         "Gansu Demo Site",
    "lat":          38.5,
    "lon":          99.9,
    "province":     "Gansu",
    "weather_mode": "synthetic"
  },
  "costs": {
    "c_deg_yuan_per_mwh":        10.0,
    "voll_yuan_per_mwh":      20000.0,
    "curtail_yuan_per_mwh":     800.0,
    "soc_penalty_yuan_per_mwh": 20000.0,
    "reward_scale":             1.0e-5
  },
  "forecast": { "sigma_max": 0.10 }
}
```

### 3.1 `fleet` (required)

A non-empty list of fleet entries. Each entry:

| Field | Type | Required | Constraint |
|---|---|---|---|
| `model_id` | string | yes | must exist in device_models.yaml |
| `count` | int | **required for `wind_turbine` and `battery`** | ≥ 1; absent for `pv_panel` and `grid_connection` |
| `fleet_capacity_mw` | float | **required for `pv_panel`** | > 0; MW; see §3.1.1 |

**`count` by device type:**
- `wind_turbine`: required (server computes `fleet_rated_mw = count × rated_mw_per_unit`)
- `battery`: required (server computes `fleet_capacity_mwh = count × capacity_mwh_per_unit`,
  `fleet_power_mw = count × power_mw_per_unit`)
- `pv_panel`: absent or ignored — fleet is specified by `fleet_capacity_mw` directly
- `grid_connection`: absent or ignored — model implies max_export/import; always one per site

**Merge rule:** multiple entries with the SAME `model_id` are merged before assembly
(`count` values summed for wind/battery; `fleet_capacity_mw` values summed for PV).
Merged before type-conflict checking.

**Type-conflict rule (`FLEET_MIXED_MODEL`):** after merging by `model_id`, each
resolved device type may have at most ONE model_id. If two distinct `model_id`
values resolve to the same device type (e.g., two different wind turbine models),
the request is rejected with HTTP 400 `FLEET_MIXED_MODEL`. Rationale: the resolver
is category-keyed (one model per asset category) per device_model_schema §3.3.

#### 3.1.1 `fleet_capacity_mw` for `pv_panel`

The `pv_panel` device model schema has NO `panel_mw_per_unit` physics field —
device_model_schema.md §1.2 lists only `k_T_per_c`, `eta_inverter`,
`degradation_yr1`. Utility-scale PV fleets are specified as a total MW capacity,
not as individual panel counts (spec-intentional; see device_model_schema §3.2:
"Required at site — fleet_capacity_mw"). Therefore:
- For `pv_panel` fleet entries: `fleet_capacity_mw` (MW, float > 0) is **required**.
- `count` is **absent** — there is no meaningful unit count for PV (unlike wind
  turbines or battery BESS units). The wizard UI shows "Fleet capacity (MWp)"
  instead of "Count" for PV rows.
- If a future `pv_panel` model adds `panel_mw_per_unit`, the server uses
  `fleet_capacity_mw` when provided; may fall back to `count × panel_mw_per_unit`
  only if `fleet_capacity_mw` is absent. That extension is out of scope here.
- If `fleet_capacity_mw` is absent for a `pv_panel` entry → HTTP 400
  `PV_FLEET_CAPACITY_REQUIRED`.
- `fleet_capacity_mw = 0` or negative → HTTP 400 `FLEET_COUNT_INVALID` (capacity
  must be > 0 MW).

### 3.2 `tariff_region` (required)

String. Must match a key in `config/tariff_model_schema.yaml`.

- Absent or empty string → HTTP 400 `TARIFF_REGION_REQUIRED`.
- Present but not found in the schema → HTTP 400 `TARIFF_REGION_NOT_FOUND`.

**Rationale for required:** An assembled `site_config` always uses `tariff_region`
(never an inline `price_table`). At training time, `resolve_site()` goes through
the region-keyed path which calls `load_tariff_schema()` and sources the
`price_table` from the region definition. Without a valid `tariff_region`, that
path fails at the resolver — the assembled config is not usable for training.
Requiring `tariff_region` at the API boundary catches this early with a clear 400.

**Note on `_check_e_tar_shape` (E-TAR-SHAPE):** since assembled configs never
include an inline `tariff.price_table_yuan_per_mwh`, the validator's E-TAR-SHAPE
rule silently skips for ALL assembled configs regardless of whether `tariff_region`
is valid. E-TAR-SHAPE is **not** the safety net here; it is N/A for region-keyed
configs. The actual enforcement is: `TARIFF_REGION_NOT_FOUND` at the 400 boundary
plus the resolver's region-path requirement at training time.

**Frontend gate:** the wizard MUST NOT call `POST /api/site/assemble` until
`tariffRegion !== ""`. Before tariff selection, the wizard shows an inline hint
("Select a tariff region to validate your configuration"). Early fleet-only
validation (without tariff) may use `POST /api/site/validate` with just the
assets dict — that endpoint accepts partial configs and E-TAR-SHAPE skips when
the tariff section is absent, returning only fleet-related rule results.

### 3.3 `site_meta` (optional)

Optional object. All sub-fields are optional.

| Field | Type | Unit | Notes |
|---|---|---|---|
| `name` | string | — | site display name; max 128 chars; echoed back in site_config |
| `lat` | float | decimal degrees N | [-90, 90]; echoed back |
| `lon` | float | decimal degrees E | [-180, 180]; echoed back |
| `province` | string | — | display only; not used by resolver/validator |
| `weather_mode` | string | — | `"synthetic"` \| `"historical"` \| `"bootstrap"`; echoed back |

No config_validation rule uses `lat`, `lon`, or `province`. The assemble call can
fire before coordinates are entered (F1 decision: lat/lon optional).

### 3.4 `costs` (optional, with server defaults)

Optional object. Absent or missing sub-fields use canonical defaults.

| Field | Type | Unit | Default | Notes |
|---|---|---|---|---|
| `c_deg_yuan_per_mwh` | float | ¥/MWh | 10.0 | battery degradation proxy (§3.4) |
| `voll_yuan_per_mwh` | float | ¥/MWh | 20000.0 | value of lost load (§3.4) |
| `curtail_yuan_per_mwh` | float | ¥/MWh | 800.0 | curtailment penalty (§3.4) |
| `soc_penalty_yuan_per_mwh` | float | ¥/MWh | 20000.0 | SOC violation penalty |
| `reward_scale` | float | — | 1.0e-5 | reward normalisation (§3.5) |

Defaults match the canonical Gansu site values (site_gansu.yaml). The tariff-
sourced costs (`demand_rate_yuan_per_mw_month`, `price_spread_yuan_per_mwh`,
`price_spread_sigma`) are always sourced from the tariff region schema — they
are NOT user-configurable at this endpoint.

### 3.5 `forecast` (optional, with server default)

Optional object.

| Field | Type | Unit | Default | Notes |
|---|---|---|---|---|
| `sigma_max` | float | — | 0.10 | max relative noise at horizon H_max=24 (D6) |

---

## 4. Response body (HTTP 200)

```json
{
  "site_config": {
    "assets": {
      "wind":    { "model": "vestas-v150-4.2",     "fleet_rated_mw": 613.2 },
      "solar":   { "model": "trina-vertex-n-670w",  "fleet_capacity_mw": 330.0 },
      "battery": { "model": "catl-lmp-300mwh",      "fleet_capacity_mwh": 300.0,
                   "fleet_power_mw": 100.0 },
      "grid":    { "model": "pcc-substation-945mw" }
    },
    "tariff_region": "cn-gansu",
    "costs": {
      "c_deg_yuan_per_mwh":             10.0,
      "voll_yuan_per_mwh":           20000.0,
      "curtail_yuan_per_mwh":          800.0,
      "demand_rate_yuan_per_mw_month": 32000.0,
      "soc_penalty_yuan_per_mwh":    20000.0,
      "reward_scale":                1.0e-5,
      "price_spread_yuan_per_mwh":     30.0,
      "price_spread_sigma":            10.0
    },
    "forecast": { "sigma_max": 0.10 },
    "site_meta": {
      "name":         "Gansu Demo Site",
      "lat":          38.5,
      "lon":          99.9,
      "province":     "Gansu",
      "weather_mode": "synthetic"
    }
  },
  "errors":   [],
  "warnings": []
}
```

### 4.1 `site_config` (always present)

`site_config` is ALWAYS present in the 200 response, even when `errors` is
non-empty. Assembly always completes before validation; the assembled dict is
always returned. Clients may read `site_config.assets.*` for fleet totals
(site totals strip display) from any 200 response, regardless of errors.

`site_config` is the canonical dict that can be:
- Passed directly to `POST /api/site/validate` for re-validation
- Saved via future `POST /api/site/config` (site_config_persistence.md)
- Handed to the env harness for training

**`site_meta` key:** present at root level of `site_config` when the request
included `site_meta` (any sub-field set). Absent from `site_config` if the
request omitted `site_meta` entirely.

### 4.2 Assembly rules (single-source in `site_assembly.py`)

| Device type | `assets` key | Input | Assembled fields |
|---|---|---|---|
| `wind_turbine` | `wind` | `count` (required) | `model`: first model_id; `fleet_rated_mw` = Σ(`count` × `physics.rated_mw_per_unit`) MW |
| `pv_panel` | `solar` | `fleet_capacity_mw` (required; no count) | `model`: first model_id; `fleet_capacity_mw` = Σ `fleet_capacity_mw` across merged entries; MW |
| `battery` | `battery` | `count` (required) | `model`: first model_id; `fleet_capacity_mwh` = Σ(`count` × `physics.capacity_mwh_per_unit`) MWh; `fleet_power_mw` = Σ(`count` × `physics.power_mw_per_unit`) MW |
| `grid_connection` | `grid` | `model_id` only (no count) | `model`: model_id only; NO `max_export_mw`/`max_import_mw` in assembled dict (resolver reads from model physics directly) |

**Device type absent from fleet:** that asset category key is omitted from
`site_config.assets`. Example: no battery in fleet → `assets.battery` absent.
The validator will catch missing required assets as validation errors (not 400).
**Note:** missing-category validation is deferred to the E-SCHEMA rule in
`config_validation.md §4`; E-SCHEMA is not implemented in v1.0.0 ("not in v1
scope") — absent sections are silently skipped by `validate()`. Tracked in
task #8. Two xfail tests assert the contracted behavior for when E-SCHEMA lands.

**Costs assembly:**
```python
assembled_costs = {
    # From request.costs (with defaults)
    "c_deg_yuan_per_mwh":          request.costs.c_deg_yuan_per_mwh or DEFAULT_C_DEG,
    "voll_yuan_per_mwh":           request.costs.voll_yuan_per_mwh or DEFAULT_VOLL,
    "curtail_yuan_per_mwh":        request.costs.curtail_yuan_per_mwh or DEFAULT_CURTAIL,
    "soc_penalty_yuan_per_mwh":    request.costs.soc_penalty_yuan_per_mwh or DEFAULT_SOC_PEN,
    "reward_scale":                request.costs.reward_scale or DEFAULT_REWARD_SCALE,
    # From tariff region schema (always overrides any request value)
    "demand_rate_yuan_per_mw_month": region.demand_rate_yuan_per_mw_month,
    "price_spread_yuan_per_mwh":     region.sell_clamp.spread_yuan_per_mwh,
    "price_spread_sigma":            region.sell_clamp.spread_noise_std_yuan_per_mwh,
}
```

### 4.3 `errors` and `warnings` (ValidationIssue list)

Same schema as `POST /api/site/validate` response (geo_site_api §4.1):

```json
{
  "rule_id":    "E-CAP-POS",
  "field":      "assets.battery.fleet_capacity_mwh",
  "message":    "fleet_capacity_mwh must be > 0",
  "constraint": "fleet_capacity_mwh = -10.0 — must be > 0"
}
```

All four fields are strings, non-nullable. `errors` non-empty → config is
hard-rejected for training; `warnings` require explicit acknowledgement in the
wizard UI.

**Validation call:** `config_validation.validate(site_config, device_models)` with
the server's loaded `device_models` dict. Device-dependent rules (E-BAT-CRATE,
E-BAT-UNIT, W-BAT-CRATE-2C) are always evaluated (unlike `POST /api/site/validate`
which makes `device_models` optional).

---

## 5. HTTP 400 codes

| Code | Trigger |
|---|---|
| `FLEET_EMPTY` | `fleet` list is absent or empty |
| `TARIFF_REGION_REQUIRED` | `tariff_region` field absent or empty string |
| `TARIFF_REGION_NOT_FOUND` | `tariff_region` not found in loaded tariff schema; body includes `available_regions: [...]` |
| `DEVICE_MODEL_NOT_FOUND` | one or more `model_id` values not found in device_models.yaml; body includes `missing_ids: [...]` |
| `FLEET_COUNT_INVALID` | any fleet entry has `count < 1` or `count` is not an integer |
| `FLEET_MIXED_MODEL` | two distinct `model_id` values resolve to the same device type; body identifies the conflicting type |
| `PV_FLEET_CAPACITY_REQUIRED` | a `pv_panel` fleet entry has no `fleet_capacity_mw` and the device model has no `panel_mw_per_unit` |

All 400 responses: `{ "detail": "<human-readable>", "code": "<CODE>", [extra fields] }`.

---

## 6. Units — explicit registry

All units inherit from `geo_site_api.md §5`. Additions for this endpoint:

| Quantity | Unit | Notes |
|---|---|---|
| Generator/battery fleet MW | MW | Never kW; assembled from count × per-unit physics |
| Battery fleet energy | MWh | Never kWh; assembled from count × capacity_mwh_per_unit |
| PV fleet capacity | MW | fleet_capacity_mw; direct user input (no per-panel multiplication) |
| Demand charge rate | ¥/MW·month | sourced from tariff region schema |
| Sell spread | ¥/MWh | sourced from tariff region schema |

---

## 7. Implementation notes

### 7.1 Module placement

Assembly logic: `src/energy_go/serving/site_assembly.py` (new file).
Endpoint registration: added to `src/energy_go/serving/geo_site_api.py` on the
existing `geo_site_router` (or a new `site_assemble_router` if preferred).

### 7.2 `assemble_site_config` function

```python
# src/energy_go/serving/site_assembly.py

from energy_go.env.tariff_model_schema import load_tariff_schema

# Server defaults — match site_gansu.yaml
ASSEMBLE_DEFAULTS = {
    "c_deg_yuan_per_mwh":       10.0,
    "voll_yuan_per_mwh":     20000.0,
    "curtail_yuan_per_mwh":    800.0,
    "soc_penalty_yuan_per_mwh": 20000.0,
    "reward_scale":            1.0e-5,
    "forecast_sigma_max":       0.10,
}

def assemble_site_config(
    fleet: list[dict],               # validated fleet entries (model resolved)
    tariff_region_id: str,
    tariff_schema: dict,             # loaded from tariff_model_schema.yaml
    device_models: dict,             # loaded from device_models.yaml
    costs_overrides: dict | None,
    forecast_overrides: dict | None,
    site_meta: dict | None,
) -> dict:
    """Assemble a canonical site_config dict from wizard form inputs.

    Pure function — no I/O.  Called by the endpoint after all catalog lookups
    and input validation succeed.

    Returns:
        site_config dict ready for config_validation.validate() and persistence.

    Raises:
        AssemblyError (subclass of ValueError) on type-conflict or PV capacity gap.
    """
```

### 7.3 Validation call

```python
from energy_go.env.config_validation import validate

@router.post("/api/site/assemble")
async def site_assemble(body: SiteAssembleRequest) -> SiteAssembleResponse:
    # 1. Input validation (400 checks)
    # 2. Catalog lookups (device_models + tariff schema)
    # 3. assemble_site_config(...)
    site_config = assemble_site_config(...)
    # 4. Validate (always with device_models — non-optional here)
    result = validate(site_config, device_models)
    return SiteAssembleResponse(
        site_config=site_config,
        errors=[_to_issue_dto(e) for e in result.errors],
        warnings=[_to_issue_dto(w) for w in result.warnings],
    )
```

### 7.4 Data loading

Device models and tariff schema are loaded once at router initialization (same
pattern as `geo_site_api.py §6.5`). Both are passed into `assemble_site_config`
— no file I/O inside the pure assembly function.

### 7.5 `POST /api/site/validate` — unchanged

`POST /api/site/validate` (geo_site_api §3.1) is NOT modified by this contract.
It continues to accept a pre-assembled site_config dict with optional
`device_models`. Both endpoints call `config_validation.validate()` — the single
source of truth. Do NOT re-open the geo_site_api validate contract.

---

## 8. Deliberate deviations

| Item | Expected | Deviation | Reason |
|---|---|---|---|
| `fleet` flat list → category-keyed assembly | client computes fleet MW/MWh | server computes from count × per-unit physics | D37: assembly is one Python implementation |
| `tariff_region` required (400 if absent) | could be optional with E-TAR-SHAPE fallback | required | assembled configs always use region-keyed tariff (no inline price_table); `resolve_site()` region path fails without valid tariff_region; E-TAR-SHAPE always skips for assembled configs (never an inline price_table to check — N/A) |
| `pv_panel` requires `fleet_capacity_mw` | derived from count × panel_mw_per_unit | direct field required | pv_panel has no panel_mw_per_unit in device_model_schema v2.0.0 |
| Grid overrides not in wizard input | max_export/import could be user-specified | not supported in v1 wizard form | Grid model physics defaults cover all known sites; wizard v1 doesn't expose grid configuration |
| `costs` always includes tariff-sourced fields | demand_rate/spread are tariff config | included in costs response | transparency for the wizard totals strip |

---

## 9. Out of scope

- Inline `price_table` in the request (only `tariff_region` is supported)
- Grid `max_export_mw` / `max_import_mw` overrides in the wizard fleet entry
- Multiple models per device type (v2 composable assets, §8)
- Custom cost/tariff knobs in stage ① UI (v1 uses server defaults)
- Scenario configuration (future contract; stage ② and beyond)
- Persistence (`POST /api/site/config`) — future `site_config_persistence.md`
- Site totals strip aggregated display endpoint (`GET /api/site/resolve`) — future

---

## 10. Test file

`tests/serving/test_serving_site_assemble.py`

Key invariants tested:
1. Gansu fleet → assembled site_config has count×per-unit values (wind: 146×4.2 = 613.2 MW;
   battery: 1×300 = 300.0 MWh, 1×100 = 100.0 MW; solar: 330.0 MW direct). These differ from
   site_gansu.yaml's sub-nominal overrides (615.0 MW, 294.5 MWh, 98.16 MW) which wizard assembly
   cannot reproduce — parity-critical sites require direct YAML config, not wizard assembly.
2. Gansu assembled config → 0 errors, 0 warnings (validation clean)
10b. Resolver round-trip: assembled Gansu config resolves without error via tariff_region path
   (guards: importorskip; skips if JAX/resolver unavailable)
3. `site_config` present in response even when `errors` non-empty
4. All HTTP 400 codes fire on their respective trigger conditions
5. Fleet merge: two same-model_id entries sum counts correctly
6. Missing battery in fleet → validation error (not 400) in response body
7. `costs` defaults: omitting `costs` → assembled site_config uses ASSEMBLE_DEFAULTS values
8. Tariff sourcing: `demand_rate`, `price_spread`, `price_spread_sigma` come from tariff schema, not from request
9. `site_meta` echoed back when provided; absent when omitted
10. PV fleet_capacity_mw: direct value used as `assets.solar.fleet_capacity_mw`
