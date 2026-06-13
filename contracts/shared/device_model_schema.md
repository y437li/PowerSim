# Device Model Schema — shared contract

**Area:** shared  
**Contract path:** `contracts/shared/device_model_schema.md`  
**Test file:** `tests/shared/test_shared_device_model_schema.py`  
**Spec sections:** §2.1 (obs), §2.2 (action), §3.1–§3.4 (physics), §7 (JAX purity), §8 (composable assets)  
**Decisions:** D2, D3, D5, D12, D19, D22c, D23  
**Plan:** `docs/design/master_plan_geo_finance.md` §2 (Workstream B), §5.6 (CAPEX/OPEX/lifetime), §8 (Gansu thin slice)  
**Owner:** jax-env-engineer  
**Related locked contracts:** `contracts/shared/telemetry_schema.md` (unchanged), `contracts/shared/checkpoint_format.md` (unchanged), `assets/3d/registry.json` (unchanged — device-model IDs are the join key but this contract does NOT modify the registry)

**v1.1.0 amendment (task #57):** adds `economics:` field catalogue (CAPEX/OPEX/lifetime/replacement/residual)
for Workstreams C (multi-year degradation) and D (project finance).  The resolver continues to
**ignore all `economics:` fields** — no resolver API change, no `EnvParams` change.  Minor version
bump from v1.0.0 baseline (additive optional fields → no re-LOCK required).

**v2.0.0 amendment (task #58 / Step A):** reshapes `EnvParams.price_table` from `(24,)` to
`(12, 24)` (months × hours).  Gansu: old `(24,)` row **replicated ×12** — bit-identical parity
for all `EnvParams()` callers.  Lookup in `jax_env.py`: `params.price_table[month, hour]` where
`month = MONTH_OF_STEP[t]` (already precomputed module-level).  Resolver builds `(12,24)` from a
flat `(24,)` site YAML input.  Real seasonal data arrives later via `tariff_model_schema` (task
#58 Step B); until then Gansu stays replicated-×12.
**Breaking shape change → major version bump; re-LOCK required** (both reviewers advisory +
rl-architect re-LOCK).  Combined contract+impl PR per rl-architect sequencing ruling.

**v2.1.0 amendment (task #63):** adds the optional `provenance:` top-level field on every model
entry, and 9 new China 2024 benchmark model entries (wind/PV/BESS/grid + SST stub — see
`contracts/shared/benchmark_device_library.md` v1.0.0).  The `provenance:` field is **resolver-ignored**
(no `EnvParams` or resolver change — identical pattern to `economics:`); it is required for
public-repo compliance (D32): committed public entries cite their data sources; proprietary values
live only in the gitignored private overlay with a `"USER-provided, pending"` stub.  See §1.4
for the field definition.
**Minor version bump (additive optional field + additive model entries → no re-LOCK; §11 rules).**

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
    provenance: "<access_keyword>; <source>; …"  # optional; resolver ignores; D32 — see §1.4
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

### 1.3 `economics:` field catalogue (v1.1.0 — task #57)

**Resolver ignores all `economics:` fields** — these are consumed exclusively by
Workstreams C (multi-year degradation/replacement) and D (project finance: LCOE/LCOS/OPEX/NPV/IRR).

All `economics:` fields are **optional** (the resolver succeeds whether or not they are
present; missing = the field is unavailable to C/D, not an error).  Finance workstream
SHOULD assert that required fields for its specific calculation are present at finance-layer
entry time, not at resolver time.

Field values below are **initial estimates sourced from publicly available Chinese
utility-scale market benchmarks (2024/25)**.  They will be refined by the benchmark
library (task #63).  All values are ≥ 0; fractions are ∈ (0, 1] unless noted.

#### `wind_turbine` — economics

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `capex_per_kw_yuan` | float | ¥/kW | Overnight CAPEX per kW of rated power; master plan §5.6 |
| `opex_fixed_per_kw_year_yuan` | float | ¥/kW·yr | Fixed O&M per rated kW per year |
| `opex_var_per_mwh_yuan` | float | ¥/MWh | Variable O&M per MWh generated (≠ D13 `c_degradation`) |
| `lifetime_years` | float | yr | Design lifetime; C replacement trigger |
| `replacement_cost_fraction` | float | — | Replacement cost / original CAPEX; ∈ (0, 1] |
| `residual_value_fraction` | float | — | Salvage value / original CAPEX at end-of-life; ∈ [0, 1) |
| `construction_months` | float | months | Construction duration (for IDC if debt-financed) |
| `decommissioning_cost_per_kw_yuan` | float | ¥/kW | Decommissioning cost per rated kW at end-of-life |

#### `pv_panel` — economics

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `capex_per_kw_yuan` | float | ¥/kW | Overnight CAPEX per kW of DC peak capacity |
| `opex_fixed_per_kw_year_yuan` | float | ¥/kW·yr | Fixed O&M per rated kW per year |
| `opex_var_per_mwh_yuan` | float | ¥/MWh | Variable O&M per MWh generated |
| `lifetime_years` | float | yr | Module design lifetime |
| `replacement_cost_fraction` | float | — | ∈ (0, 1] |
| `residual_value_fraction` | float | — | ∈ [0, 1) |
| `construction_months` | float | months | |
| `decommissioning_cost_per_kw_yuan` | float | ¥/kW | |

#### `battery` — economics

The battery CAPEX formula is two-part:
`CAPEX = fleet_capacity_mwh * 1000 * capex_energy_per_kwh_yuan + fleet_power_mw * 1000 * capex_power_per_kw_yuan`
(master plan §5.6).

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `capex_energy_per_kwh_yuan` | float | ¥/kWh | Energy-capacity component of CAPEX |
| `capex_power_per_kw_yuan` | float | ¥/kW | Power-capacity component of CAPEX (0.0 if bundled into energy) |
| `opex_fixed_per_kwh_year_yuan` | float | ¥/kWh·yr | Fixed O&M per installed kWh per year |
| `opex_var_per_mwh_yuan` | float | ¥/MWh | Variable O&M per MWh cycled (≠ D13 `c_degradation`) |
| `lifetime_years` | float | yr | Calendar lifetime; C secondary replacement trigger |
| `cycle_life_full_equiv` | float | cycles | Full-depth equivalent cycle life; C primary replacement trigger |
| `eol_soh_threshold` | float | — | State-of-health fraction below which replacement is triggered; ∈ (0, 1) |
| `replacement_cost_fraction` | float | — | ∈ (0, 1] |
| `residual_value_fraction` | float | — | ∈ [0, 1) |
| `construction_months` | float | months | |
| `decommissioning_cost_per_kwh_yuan` | float | ¥/kWh | |

#### `grid_connection` — economics

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `capex_lump_sum_yuan` | float | ¥ | Grid-connection infrastructure CAPEX (highly site-specific; may be 0.0 if absorbed into site capex) |
| `opex_fixed_per_mw_year_yuan` | float | ¥/MW·yr | Fixed O&M per connected MW per year |
| `lifetime_years` | float | yr | Infrastructure lifetime |
| `residual_value_fraction` | float | — | ∈ [0, 1) |
| `decommissioning_cost_yuan` | float | ¥ | Decommissioning lump sum |

### 1.4 `provenance:` field (v2.1.0 — task #63)

**Resolver ignores** the `provenance:` field — identical pattern to `economics:`.  It is
**required for public-repo compliance (D32)** on all committed model entries, and SHOULD be
present on every entry added at or after v2.1.0.

```yaml
provenance: "<access_keyword>; <source1>; [<source2>; …]"
```

| Access keyword | Meaning |
|---|---|
| `public` | Publicly available data — manufacturer datasheets, IRENA, IEA, NEA, CNREC, CNESA, peer-reviewed literature, etc. |
| `USER-provided, pending` | Data awaiting USER input; all values are placeholder stubs |

**Format and compliance rules:**
- **Public entries** start `"public; …"` followed by at least one source citation.
- **Proprietary or partner-confidential data MUST NOT be committed** (CLAUDE.md D32).
  Such data lives only in the gitignored private overlay (`ENERGY_GO_PRIVATE_CONFIG` env var).
  The stub in public config MUST carry `provenance: "USER-provided, pending"` and placeholder
  physics values (e.g. `pcc-sst-stub` — SST data PAUSED by USER).
- The field is **optional in the resolver** (absent = unavailable to finance layer, not an error).
- For entries added after v2.1.0, omitting `provenance:` is a style warning, not a schema error —
  but the finance layer SHOULD reject un-provenanced entries when computing LCOE/LCOS.

`contracts/shared/benchmark_device_library.md` §1 also describes the provenance convention for
the benchmark library context; this §1.4 is the canonical schema-level definition (D18 single source).

### 1.5 Gansu v1.1.0 default economics values

Initial estimates (2024/25 Chinese utility-scale market; source: IRENA/NEA public data; to be
refined by task #63 benchmark library).  All values are **non-zero documented estimates**,
not placeholder zeros, so the finance engine produces plausible order-of-magnitude results
from day one.

#### vestas-v150-4.2 (wind_turbine)

| Field | Value | Notes |
|-------|-------|-------|
| `capex_per_kw_yuan` | 5800.0 | ≈800 USD/kW; onshore wind China 2024 |
| `opex_fixed_per_kw_year_yuan` | 180.0 | ≈25 USD/kW·yr |
| `opex_var_per_mwh_yuan` | 0.0 | negligible at this scale; captured in fixed |
| `lifetime_years` | 25.0 | IEC Class III design life |
| `replacement_cost_fraction` | 0.15 | major overhaul (not full replacement) at EOL |
| `residual_value_fraction` | 0.05 | scrap value |
| `construction_months` | 18.0 | |
| `decommissioning_cost_per_kw_yuan` | 100.0 | |

#### trina-vertex-n-670w (pv_panel)

| Field | Value | Notes |
|-------|-------|-------|
| `capex_per_kw_yuan` | 3200.0 | ≈450 USD/kW; utility PV China 2024 |
| `opex_fixed_per_kw_year_yuan` | 80.0 | ≈11 USD/kW·yr |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `lifetime_years` | 25.0 | |
| `replacement_cost_fraction` | 0.20 | inverter replacement |
| `residual_value_fraction` | 0.02 | |
| `construction_months` | 12.0 | |
| `decommissioning_cost_per_kw_yuan` | 60.0 | |

#### catl-lmp-300mwh (battery)

| Field | Value | Notes |
|-------|-------|-------|
| `capex_energy_per_kwh_yuan` | 1000.0 | ≈140 USD/kWh; LFP grid-scale China 2024 |
| `capex_power_per_kw_yuan` | 0.0 | bundled into energy CAPEX for LFP |
| `opex_fixed_per_kwh_year_yuan` | 20.0 | ≈2.8 USD/kWh·yr |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `lifetime_years` | 12.0 | LFP calendar life at ≥80% SOH |
| `cycle_life_full_equiv` | 6000.0 | LFP at 0.8 EOL; 1 cycle/day × 12yr ≈ 4380; 6k gives head-room |
| `eol_soh_threshold` | 0.80 | 80% remaining capacity triggers replacement |

> **Note (§1.3 vs §1.4):** The *schema* bound for `eol_soh_threshold` is `(0, 1)` — a config author may set any value in that range. The Gansu default (0.80) falls in the plausible LFP range (≈ 0.7–0.9); this is a defaults-plausibility constraint, **not** a schema constraint. Do not cite 0.80 or the 0.7–0.9 band as the schema bound.

| `replacement_cost_fraction` | 0.70 | cell+BMS replacement; learning-curve reduction vs original |
| `residual_value_fraction` | 0.05 | |
| `construction_months` | 6.0 | |
| `decommissioning_cost_per_kwh_yuan` | 30.0 | |

#### pcc-substation-945mw (grid_connection)

| Field | Value | Notes |
|-------|-------|-------|
| `capex_lump_sum_yuan` | 0.0 | site-specific; treated as sunk cost at Gansu; operators override per-site |
| `opex_fixed_per_mw_year_yuan` | 5000.0 | ≈700 USD/MW·yr; transmission service fee |
| `lifetime_years` | 40.0 | |
| `residual_value_fraction` | 0.10 | |
| `decommissioning_cost_yuan` | 0.0 | |

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
    unit_count: <int>             # optional; if absent, derived as round(fleet_rated_mw / rated_mw_per_unit)
  solar:
    model: <model_id>
    fleet_capacity_mw: <float>    # MW — total fleet DC/AC capacity (required)
    degradation_yr1: <float>      # optional override; model default if absent
  battery:
    model: <model_id>
    fleet_capacity_mwh: <float>   # MWh — total fleet energy capacity (required)
    fleet_power_mw: <float>       # MW  — total fleet charge/discharge power (required)
    unit_count: <int>             # optional; if absent, derived as round(fleet_capacity_mwh / capacity_mwh_per_unit)
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

def get_unit_counts(
    site_config_path: str | Path,
    device_models_path: str | Path = "config/device_models.yaml",
) -> dict[str, int]:
    """Return resolved unit counts for discretely-instanced assets.

    Applies the canonical rounding rule (§4.1) or the explicit `unit_count`
    override from the site YAML (explicit takes precedence).

    Returns a dict with keys "wind" and "battery".
    PV and grid are fleet-only — no per-unit count exposed.

    For Gansu:
        {"wind": 146, "battery": 1}
        (146 = round(615.0 / 4.2), 1 = round(294.5 / 300.0))

    Used by the serving REST endpoint so A/E consumers (3D instanced fleet,
    composition panel) never re-implement the rounding in TS.
    """
```

**`resolve_gansu()` must return `(EnvParams(...), 107, 6)`** — obs_dim=107 (§2.1
LOCKED: 11 base + 24×4 forecast), action_dim=6 (§2.2 LOCKED: a_bat + 5 fractions).

### 4.1 Unit-count derivation (single source of truth)

The resolver computes a `unit_counts: dict[str, int]` for discretely-instanced
assets (wind turbines, battery units).  This is **not** returned from `resolve_site`
directly (EnvParams-only path), but is exposed by the serving REST endpoint so the
frontend and 3D scene can use it for instancing without re-implementing the rounding:

```
unit_counts["wind"]    = site.assets.wind.unit_count            # if explicit
                       OR round(fleet_rated_mw / rated_mw_per_unit)   # derived
unit_counts["battery"] = site.assets.battery.unit_count         # if explicit
                       OR round(fleet_capacity_mwh / capacity_mwh_per_unit)  # derived
```

This is the **canonical rounding rule**; TS clients MUST use the serving endpoint
rather than re-deriving it.  For Gansu: `round(615.0 / 4.2) = 146` (wind),
`round(294.5 / 300.0) = 1` (battery).  The `unit_count` optional field in
`site_<name>.yaml` (§2) takes precedence when set, allowing exact deployment counts
that differ from nameplate math.

---

## 5. `EnvParams.price_table` refactor

### 5.1 Field shape (v1.0.0 → v2.0.0)

`EnvParams.price_table` is reshaped from `(24,)` to `(12, 24)` (months × hours):

```python
# v1.0.0 (SUPERSEDED by v2.0.0):
# price_table: jax.Array = PRICE_TABLE_YPW  # shape (24,), float32, ¥/MWh

# v2.0.0 (this amendment):
PRICE_TABLE_SEASONAL_YPW: jax.Array = jnp.stack(
    [PRICE_TABLE_YPW] * 12, axis=0
)  # shape (12, 24), month m=0..11 (Jan..Dec)

class EnvParams(NamedTuple):
    # ... existing fields unchanged ...
    # Tariff — (12, 24) seasonal table (NEW shape; v2.0.0)
    price_table: jax.Array = PRICE_TABLE_SEASONAL_YPW  # shape (12,24), float32, ¥/MWh
```

`PRICE_TABLE_YPW` (the `(24,)` constant) is **retained** as a module-level constant
for use in parity assertions; it is no longer the default for `EnvParams.price_table`.
`PRICE_TABLE_SEASONAL_YPW` is the new `(12,24)` default (all 12 rows identical to
`PRICE_TABLE_YPW` — bit-identical parity for Gansu).

### 5.2 Step / obs refactor (v2.0.0)

All `params.price_table[h]` reads in `jax_env.py` are updated to
`params.price_table[month, h]` where `month = MONTH_OF_STEP[t]`:

| Location | Before (v1.0.0) | After (v2.0.0) |
|---|---|---|
| `get_obs()` — live price obs | `params.price_table[hour]` | `params.price_table[month, hour]` |
| `get_obs()` — forecast price | `params.price_table[t_fc % 24]` | `params.price_table[MONTH_OF_STEP[t_fc], t_fc % 24]` |
| `step()` — buy price for cost | `params.price_table[hour]` | `params.price_table[month, hour]` |

`MONTH_OF_STEP` is the existing precomputed `(8761,) int32` module-level array
(`MONTH_OF_STEP[t]` = calendar month 0=Jan … 11=Dec for step `t`).  No new
data-dependent Python branching is introduced.

Since `params` is shared across vmapped envs (not in the vmap batch axis), the
`(12, 24)` array field adds negligible per-env memory and does not affect vmap semantics.

### 5.3 Backward compatibility / parity gate

`EnvParams()` (no args) produces `price_table = PRICE_TABLE_SEASONAL_YPW` where
every row equals `PRICE_TABLE_YPW`.  The **bit-identity parity test** is:

```python
# For ALL months m ∈ [0,11] and hours h ∈ [0,23]:
assert EnvParams().price_table[m, h] == PRICE_TABLE_YPW[h]
# Equivalently:
assert jnp.allclose(EnvParams().price_table, PRICE_TABLE_SEASONAL_YPW)
```

Existing tests that call `step(state, action, EnvParams(), data)` continue to produce
identical outputs because `price_table[MONTH_OF_STEP[t], hour] == PRICE_TABLE_YPW[hour]`
for every month.  The resolver parity test extends to check
`resolve_gansu()[0].price_table[m, h] == PRICE_TABLE_YPW[h]` for all `m, h`.

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
| `tariff.price_table_yuan_per_mwh` | `price_table` | **(12,24)** ¥/MWh — flat 24-entry YAML replicated ×12 by resolver (v2.0.0); real seasonal data via tariff_model_schema |

---

## 9. Deliberate deviations

**v1.0.0 (no deviations):** This contract added new functionality; no behavior changed.

**v2.0.0 deviations (breaking shape change — gated by re-LOCK):**

| Old behavior | New behavior | Reason |
|---|---|---|
| `EnvParams.price_table.shape == (24,)` | `shape == (12, 24)` | Enable seasonal tariffs |
| Default `PRICE_TABLE_YPW` | Default `PRICE_TABLE_SEASONAL_YPW` (= stack of 12 × `PRICE_TABLE_YPW`) | Same values, new shape |
| `params.price_table[hour]` | `params.price_table[month, hour]` | Month-indexed lookup |
| Resolver builds flat `(24,)` | Resolver builds `(12,24)` via `stack([row]*12)` | Match new shape |

All v2.0.0 changes produce **bit-identical outputs** for any scenario that was valid
under v1.0.0, because `PRICE_TABLE_SEASONAL_YPW[m, h] == PRICE_TABLE_YPW[h]` for
all `m ∈ [0,11]` and `h ∈ [0,23]`.  The parity bit-identity test is the acceptance gate.

- `PRICE_TABLE_YPW` is **retained** as a module-level constant (parity assertion target).
- `PRICE_TABLE_SEASONAL_YPW` is the new module-level default for `EnvParams.price_table`.
- `EnvParams()` (no-arg construction) continues to produce Gansu-correct params.
- All physics values are unchanged — this is a shape-only refactor.

---

## 10. Out of scope

- **Sub-hour TOU structure:** `price_table` is an hourly `(12, 24)` array (v2.0.0)
  and cannot express sub-hour TOU boundaries (e.g., D8's 10:30/11:30 transitions).
  Gansu v1 is correct — Δt=1 h steps land on :00 and the minute-aware lookup lives in
  the reference impl (not the table). Sub-hour TOU would require a further breaking
  schema change (superseding DECISION + re-LOCK).
- **Intra-year seasonal variation (Gansu):** v2.0.0 ships Gansu as replicated-×12
  (all 12 months identical); real monthly Gansu TOU data arrives in `tariff_model_schema`
  (task #58 Step B), delivered as explicit `(12,24)` values, each row independently
  testable via hand-computed cost assertions.
- **Frontend physics access:** the browser cannot read `config/device_models.yaml`
  off disk; device physics (including `unit_counts` from §4.1) must be served via a
  REST endpoint wrapping the resolver. The serving contract owns that endpoint shape.
- **Year-indexed price escalation (F1 ruling, PR #78 gate):** dispatch operates on
  constant-real prices — a flat `price_table` per site, exactly as specified here.
  Nominal price escalation (~49% by year 20) is applied in the finance layer only,
  because escalating dispatch-time prices would shift the policy's training
  distribution. Year-indexed escalation is therefore finance-layer only and does
  NOT affect the resolver or `EnvParams`. The `economics: {}` section is the hook
  point for finance-side parameters (CAPEX, O&M, degradation curve refs, PPA rates)
  and does not affect the resolver.
- Non-Gansu site configs — deferred; this v1.0.0 ships only the 4 Gansu entries.
- §8 composable obs/action derivation — deferred; for non-Gansu sites `obs_dim` and
  `action_dim` would change, requiring a §8 env-logic contract. Out of scope here.
- E2/E5 Tier-1 enhancements (D17) — unaffected by this contract.
- LOCKED `registry.json`, `telemetry_schema.md`, `checkpoint_format.md` — unchanged.

---

## 11. Versioning

`config/device_models.yaml` carries `schema_version`.

| Version | Change | Re-LOCK? |
|---|---|---|
| `"1.0.0"` | Initial release — 4 Gansu device models, `physics:` catalogue (PR #79) | First LOCK |
| `"1.1.0"` | Adds `economics:` field catalogue, Gansu initial estimates (task #57) | No — additive optional fields |
| `"2.0.0"` | `price_table` reshaped `(24,)→(12,24)` seasonal; Gansu replicated ×12 (bit-identical) | Yes — shape change |
| `"2.1.0"` | Adds optional `provenance:` field (§1.4) + 9 China 2024 benchmark entries (wind/PV/BESS/grid + SST stub) — task #63 | No — additive optional field + new entries |

**Rules:**
- Additive new model entries or `economics:` fields = minor bump — no re-LOCK required.
- **`economics:` values** are initial estimates (2024/25 Chinese market) and will be
  refined by the benchmark library (task #63).  Updating economics values = minor bump
  (no re-LOCK); updating economics field names or adding required-field enforcement in
  the resolver = major bump.
- **Adding non-Gansu models** that produce different `(obs_dim, action_dim)` is also a
  minor schema bump — it does NOT reopen the LOCKED Gansu checkpoint.  The Gansu
  checkpoint remains authoritative at `obs_dim=107, action_dim=6`; non-Gansu site
  compositions receive their own site-specific checkpoints (per §8 design and the
  checkpoint-format contract §6 note on non-Gansu sites).
- Field removal, rename, type change, or shape change = major bump → superseding
  DECISION + re-LOCK + both-reviewer re-review.
