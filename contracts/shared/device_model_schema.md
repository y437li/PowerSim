# Device Model Schema — shared contract

**Area:** shared  
**Contract path:** `contracts/shared/device_model_schema.md`  
**Test file:** `tests/shared/test_shared_device_model_schema.py`  
**Spec sections:** §2.1 (obs), §2.2 (action), §3.1–§3.4 (physics), §7 (JAX purity), §8 (composable assets)  
**Decisions:** D2, D3, D5, D12, D19, D22c, D23  
**Plan:** `docs/design/master_plan_geo_finance.md` §2 (Workstream B), §8 (Gansu thin slice)  
**Owner:** jax-env-engineer  
**Related locked contracts:** `contracts/shared/telemetry_schema.md` (unchanged), `contracts/shared/checkpoint_format.md` (unchanged), `assets/3d/registry.json` (unchanged — device-model IDs are the join key but this contract does NOT modify the registry)

---

## Overview

This contract defines the two-layer device-model schema that makes multi-site
support config-only:

1. **`config/device_models.yaml`** — per-device-model physics constants, keyed by
   the LOCKED `registry.json` device IDs.
2. **Composition rule** — model physics (non-overridable) + site fleet config
   (overridable fleet-level params), resolved at Python startup, never inside jit.
3. **Resolver API** — `resolve_site(site_config) → (EnvParams, obs_dim, action_dim)`;
   the returned `EnvParams` is passed directly to the jitted `step()`.
4. **`EnvParams.price_table` refactor** — per-site TOU tariff table becomes a
   `(24,)` field in `EnvParams` instead of a closed-over module-level constant,
   completing §7 purity (no site-specific globals inside jit).
5. **Gansu parity gate** — `resolve_gansu()[0] == EnvParams()` must hold
   bit-exactly for all scalar fields AND the `(24,)` `price_table` array.

**Scope (v1.0.0):** the 4 Gansu device models only
(`vestas-v150-4.2`, `trina-vertex-n-670w`, `catl-lmp-300mwh`, `pcc-substation-945mw`).
§8 composable obs/action derivation for non-Gansu sites is deferred.

---

## 1. `config/device_models.yaml` schema

### 1.1 Top-level structure

```yaml
schema_version: "1.0.0"
models:
  <model_id>:
    type: <wind_turbine | pv_panel | battery | grid_connection>
    physics:
      <field>: <value>
    economics:    # reserved; consumed only by finance workstream; resolver ignores
      {}
```

`model_id` format: `^[a-z0-9][a-z0-9.-]*$` — identical to the `registry.json` key
format (binding cross-area invariant, D23).  The 4 Gansu entries MUST use the
exact same IDs as the LOCKED `registry.json`.

### 1.2 Field catalogue by device type

All `physics` fields listed below are **required** for the given type.

#### `wind_turbine`

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `v_cutin_mps` | float | m/s | Cut-in wind speed (§3.1) |
| `v_rated_mps` | float | m/s | Rated wind speed (§3.1) |
| `v_cutout_mps` | float | m/s | Cut-out wind speed (§3.1) |
| `hub_height_m` | float | m | Default hub height; site-overridable |
| `rated_mw_per_unit` | float | MW | Nameplate output per turbine |

#### `pv_panel`

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `k_T_per_c` | float | /°C | Temperature coefficient (§3.2); negative |
| `eta_inverter` | float | — | Inverter efficiency ∈ (0, 1] |
| `degradation_yr1` | float | — | Year-1 output fraction ∈ (0, 1]; site-overridable |

#### `battery`

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `eta_ch` | float | — | Charge round-trip efficiency ∈ (0, 1]; §3.3, D4 |
| `eta_dis` | float | — | Discharge efficiency ∈ (0, 1]; §3.3 |
| `soc_min` | float | — | Minimum SOC fraction; D4 |
| `soc_max` | float | — | Maximum SOC fraction; D4 |
| `capacity_mwh_per_unit` | float | MWh | Nameplate energy capacity |
| `power_mw_per_unit` | float | MW | Nameplate charge/discharge power |

#### `grid_connection`

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `max_export_mw` | float | MW | PCC export limit; D5; site-overridable |
| `max_import_mw` | float | MW | Grid import limit; D12; site-overridable |

---

## 2. `config/site_<name>.yaml` — instance section

The resolver reads `assets`, `tariff`, `costs`, and `forecast` sections from
the site YAML.  All other site YAML sections (existing or future) are ignored
by the device-model resolver.

```yaml
assets:
  wind:
    model: <model_id>
    fleet_rated_mw: <float>       # MW — total fleet rated power (required)
    hub_height_m: <float>         # m  — optional override; model default if absent
  solar:
    model: <model_id>
    fleet_capacity_mw: <float>    # MW — total fleet DC/AC capacity (required)
    degradation_yr1: <float>      # optional override; model default if absent
  battery:
    model: <model_id>
    fleet_capacity_mwh: <float>   # MWh — total fleet energy capacity (required)
    fleet_power_mw: <float>       # MW  — total fleet charge/discharge power (required)
  grid:
    model: <model_id>
    max_export_mw: <float>        # MW  — optional override; model physics default if absent
    max_import_mw: <float>        # MW  — optional override; model physics default if absent
tariff:
  price_table_yuan_per_mwh:      # list of exactly 24 floats ¥/MWh, index = hour 0–23
    [<float> × 24]
costs:
  c_deg_yuan_per_mwh: <float>
  voll_yuan_per_mwh: <float>
  curtail_yuan_per_mwh: <float>   # note: key matches EnvParams field name
  demand_rate_yuan_per_mw_month: <float>
  soc_penalty_yuan_per_mwh: <float>
  reward_scale: <float>
  price_spread_yuan_per_mwh: <float>
  price_spread_sigma: <float>
forecast:
  sigma_max: <float>              # max relative noise at horizon H_max=24; D6
```

---

## 3. Composition rule

### 3.1 Non-overridable physics constants

These fields are intrinsic to the device model.  If a site YAML `assets` entry
contains any of these keys, the resolver raises `DeviceModelError`.

| Device type | Non-overridable fields |
|-------------|----------------------|
| wind_turbine | `v_cutin_mps`, `v_rated_mps`, `v_cutout_mps` |
| pv_panel | `k_T_per_c`, `eta_inverter` |
| battery | `eta_ch`, `eta_dis`, `soc_min`, `soc_max` |

### 3.2 Site-overridable fields

These fields have model-provided defaults; the site YAML may override them.

| Device type | Site-overridable | Required at site |
|-------------|-----------------|-----------------|
| wind_turbine | `hub_height_m` | `fleet_rated_mw` |
| pv_panel | `degradation_yr1` | `fleet_capacity_mw` |
| battery | — | `fleet_capacity_mwh`, `fleet_power_mw` |
| grid_connection | `max_export_mw`, `max_import_mw` | — |

### 3.3 Resolution algorithm

```
for each asset type in [wind, solar, battery, grid]:
  1. look up model_id in device_models.yaml → physics dict (error if missing)
  2. take all non-overridable physics constants from the model (authoritative)
  3. apply site-level fleet params (required) and optional overrides
  4. raise DeviceModelError if any site key conflicts with a non-overridable constant
```

Cost, tariff, and forecast params come entirely from the site YAML (no model
involvement).  `soc_init = 0.5` and `episode_len = 168` use `EnvParams` defaults
(not exposed in site YAML; these are training/episode params, not site physics).

---

## 4. Resolver API

**Module:** `energy_go.env.resolver`  
**File:** `src/energy_go/env/resolver.py`

```python
from pathlib import Path
from energy_go.env.jax_env import EnvParams

class DeviceModelError(ValueError):
    """Raised when model_id missing or site attempts to override a physics constant."""

def resolve_site(
    site_config_path: str | Path,
    device_models_path: str | Path = "config/device_models.yaml",
) -> tuple[EnvParams, int, int]:
    """Resolve a site YAML + device model schema to (EnvParams, obs_dim, action_dim).

    Pure Python (never called inside jit).  The returned EnvParams is passed
    directly to jax.jit(step) as the `params` argument.

    Args:
        site_config_path: path to site_<name>.yaml
        device_models_path: path to device_models.yaml (default relative to repo root)

    Returns:
        params:     Fully populated EnvParams NamedTuple including price_table
        obs_dim:    Observation dimension (107 for Gansu; site-dependent for §8 non-Gansu)
        action_dim: Action dimension (6 for Gansu; site-dependent for §8 non-Gansu)

    Raises:
        DeviceModelError: model_id not found, or site overrides a non-overridable constant
        ValueError: tariff table not exactly 24 entries, required fleet param missing
    """

def resolve_gansu(
    device_models_path: str | Path = "config/device_models.yaml",
) -> tuple[EnvParams, int, int]:
    """Convenience: resolve the Gansu site (config/site_gansu.yaml).

    Acceptance gate: resolve_gansu()[0] == EnvParams() must hold bit-exactly.
    """
```

**`resolve_gansu()` must return `(EnvParams(...), 107, 6)`** — obs_dim=107 (§2.1
LOCKED: 11 base + 24×4 forecast), action_dim=6 (§2.2 LOCKED: a_bat + 5 fractions).

---

## 5. `EnvParams.price_table` refactor

### 5.1 New field

`EnvParams` gains one field appended after the existing fields:

```python
class EnvParams(NamedTuple):
    # ... existing fields unchanged ...
    # Tariff (NEW — was module-level PRICE_TABLE_YPW)
    price_table: jax.Array = PRICE_TABLE_YPW  # shape (24,), float32, ¥/MWh
```

The default value is `PRICE_TABLE_YPW` (the existing module-level Gansu constant),
preserving backward-compatibility: `EnvParams()` still produces the Gansu-correct params.

### 5.2 Step / obs refactor

All uses of the module-global `PRICE_TABLE_YPW` inside `step()` and `get_obs()` are
replaced with `params.price_table`.  `PRICE_TABLE_YPW` remains as a module-level
constant for use as the `EnvParams.price_table` default and in parity tests.

- **Before:** `PRICE_TABLE_YPW[h]` (closes over module global — §7 impurity)
- **After:** `params.price_table[h]` (reads from the shared `params` pytree — §7 pure)

Since `params` is shared across vmapped envs (not in the vmap batch axis), the
`(24,)` array field adds no per-env memory and does not affect vmap semantics.

### 5.3 Backward compatibility

`EnvParams()` (no args) continues to produce the correct Gansu params.
Existing tests that call `step(state, action, EnvParams(), data)` remain valid.
The Gansu parity gate asserts this explicitly.

---

## 6. Gansu device model entries

The 4 entries in `config/device_models.yaml` for Gansu parity:

```yaml
schema_version: "1.0.0"
models:
  vestas-v150-4.2:
    type: wind_turbine
    physics:
      v_cutin_mps: 3.0
      v_rated_mps: 12.0
      v_cutout_mps: 25.0
      hub_height_m: 105.0
      rated_mw_per_unit: 4.2
    economics: {}

  trina-vertex-n-670w:
    type: pv_panel
    physics:
      k_T_per_c: -0.003
      eta_inverter: 0.97
      degradation_yr1: 0.98
    economics: {}

  catl-lmp-300mwh:
    type: battery
    physics:
      eta_ch: 0.97
      eta_dis: 0.97
      soc_min: 0.2
      soc_max: 0.9
      capacity_mwh_per_unit: 300.0
      power_mw_per_unit: 100.0
    economics: {}

  pcc-substation-945mw:
    type: grid_connection
    physics:
      max_export_mw: 945.0
      max_import_mw: 400.0
    economics: {}
```

---

## 7. `config/site_gansu.yaml` additions

The following sections are ADDED to the existing `config/site_gansu.yaml`
(which currently holds TOU hours for reference only; this contract makes it
the resolver's source of truth):

```yaml
assets:
  wind:
    model: vestas-v150-4.2
    fleet_rated_mw: 615.0   # 146 turbines; override (146×4.2=613.2 MW; spec rounds to 615)
  solar:
    model: trina-vertex-n-670w
    fleet_capacity_mw: 330.0
  battery:
    model: catl-lmp-300mwh
    fleet_capacity_mwh: 294.5   # actual deployed < nominal 300 MWh per unit
    fleet_power_mw: 98.16
  grid:
    model: pcc-substation-945mw
    # max_export/max_import use model physics defaults (945 / 400 MW)

tariff:
  price_table_yuan_per_mwh:
    [250, 250, 250, 250, 250, 250, 250,   # h=0–6   Valley 23:00–07:00
     450,                                  # h=7     Mid
     620, 620, 620,                        # h=8–10  Peak
     780,                                  # h=11    Critical peak (10:30–11:30)
     450, 450, 450, 450, 450, 450,         # h=12–17 Mid
     620,                                  # h=18    Peak
     780, 780,                             # h=19–20 Critical peak
     620, 620,                             # h=21–22 Peak
     250]                                  # h=23    Valley

costs:
  c_deg_yuan_per_mwh: 10.0
  voll_yuan_per_mwh: 20000.0
  curtail_yuan_per_mwh: 800.0
  demand_rate_yuan_per_mw_month: 32000.0
  soc_penalty_yuan_per_mwh: 20000.0
  reward_scale: 1.0e-5
  price_spread_yuan_per_mwh: 30.0
  price_spread_sigma: 10.0

forecast:
  sigma_max: 0.10
```

---

## 8. Mapping: site YAML fields → `EnvParams` fields

| Site YAML path | `EnvParams` field | Value (Gansu) |
|----------------|------------------|---------------|
| `assets.wind.fleet_rated_mw` | `wind_rated_mw` | 615.0 MW |
| `assets.wind.model` → `v_cutin_mps` | `wind_v_cutin` | 3.0 m/s |
| `assets.wind.model` → `v_rated_mps` | `wind_v_rated` | 12.0 m/s |
| `assets.wind.model` → `v_cutout_mps` | `wind_v_cutout` | 25.0 m/s |
| `assets.wind.hub_height_m` (or model default) | `wind_hub_height_m` | 105.0 m |
| `assets.solar.fleet_capacity_mw` | `pv_capacity_mw` | 330.0 MW |
| `assets.solar.model` → `k_T_per_c` | `pv_k_T` | −0.003 /°C |
| `assets.solar.model` → `eta_inverter` | `pv_eta_inv` | 0.97 |
| `assets.solar.degradation_yr1` (or model default) | `pv_degradation` | 0.98 |
| `assets.battery.fleet_capacity_mwh` | `bat_capacity_mwh` | 294.5 MWh |
| `assets.battery.fleet_power_mw` | `bat_power_mw` | 98.16 MW |
| `assets.battery.model` → `eta_ch` | `bat_eta_ch` | 0.97 |
| `assets.battery.model` → `eta_dis` | `bat_eta_dis` | 0.97 |
| `assets.battery.model` → `soc_min` | `soc_min` | 0.2 |
| `assets.battery.model` → `soc_max` | `soc_max` | 0.9 |
| *(EnvParams default)* | `soc_init` | 0.5 |
| `assets.grid.max_export_mw` (or model default) | `grid_max_export_mw` | 945.0 MW |
| `assets.grid.max_import_mw` (or model default) | `grid_max_import_mw` | 400.0 MW |
| `costs.c_deg_yuan_per_mwh` | `c_deg_yuan_per_mwh` | 10.0 ¥/MWh |
| `costs.voll_yuan_per_mwh` | `voll_yuan_per_mwh` | 20 000 ¥/MWh |
| `costs.curtail_yuan_per_mwh` | `curtail_yuan_per_mwh` | 800 ¥/MWh |
| `costs.demand_rate_yuan_per_mw_month` | `demand_rate_yuan_per_mw_month` | 32 000 ¥/MW·month |
| `costs.soc_penalty_yuan_per_mwh` | `soc_penalty_yuan_per_mwh` | 20 000 ¥/MWh |
| `costs.reward_scale` | `reward_scale` | 1 × 10⁻⁵ |
| `costs.price_spread_yuan_per_mwh` | `price_spread_yuan_per_mwh` | 30 ¥/MWh |
| `costs.price_spread_sigma` | `price_spread_sigma` | 10 ¥/MWh |
| `forecast.sigma_max` | `forecast_sigma_max` | 0.10 |
| *(EnvParams default)* | `episode_len` | 168 steps |
| `tariff.price_table_yuan_per_mwh` | `price_table` | (24,) ¥/MWh (NEW field) |

---

## 9. Deliberate deviations

None — this contract adds new functionality.

- `PRICE_TABLE_YPW` is retained as a module-level constant (default for
  `EnvParams.price_table`; used in tests); only removed from the jitted read path.
- `EnvParams()` (no-arg construction) preserves Gansu defaults — backward-compatible.
- All physics values are the same as the current `EnvParams` hardcoded defaults;
  the schema resolver is a new indirection, not a value change.

---

## 10. Out of scope

- Economics fields (`capex_yuan_per_mw`, WACC, PPA rate, etc.) — `economics: {}`
  placeholder reserved in the schema; consumed only by workstream D (finance); the
  resolver ignores it.
- Non-Gansu site configs — deferred; this v1.0.0 ships only the 4 Gansu entries.
- §8 composable obs/action derivation — deferred; for non-Gansu sites `obs_dim` and
  `action_dim` would change, requiring a §8 env-logic contract. Out of scope here.
- E2/E5 Tier-1 enhancements (D17) — unaffected by this contract.
- LOCKED `registry.json`, `telemetry_schema.md`, `checkpoint_format.md` — unchanged.

---

## 11. Versioning

`config/device_models.yaml` carries `schema_version: "1.0.0"`.  
Additive new model entries = minor bump (`"1.1.0"`) — no re-LOCK required.  
Field removal, rename, type change, or semantics change = major bump → superseding
DECISION + re-LOCK + re-review.
