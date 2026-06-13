# Contract: `config_validation` — two-tier site-config validator

**Version:** 1.1.0  
**Area:** shared  
**Owner (resolver impl):** jax-env-engineer  
**Owner (econ rules):** finance-expert  
**Owner (REST endpoint):** serving-engineer  
**Owner (UI rendering):** frontend-engineer  
**Locked by:** rl-architect  
**Spec refs:** REBUILD_SPEC §3.6; LINEAGE D26 (two-tier precedent), D18 (single-validator), D32(i)  
**Composes with:** `contracts/shared/device_model_schema.md` v1.0.0 (LOCKED); extends on device_model_schema v2.0.0 + tariff_model_schema (future, see §9)  
**Task:** #66

---

## 1. Purpose

The resolver layer is the **single source of truth** for all site-config validation.
Rules live in `energy_go.env.config_validation` (Python, owned by jax-env-engineer)
and are exercised exactly once — no duplicate rule sets in TypeScript/serving.

User directive: "明显不合理的要报错" — obviously unreasonable configs MUST ERROR;
suspicious-but-legal configs MUST WARN.  The UI's stage-① gate ("can't proceed on
hard error") consumes `ValidationResult.errors`; warnings surface as explicit
acknowledgement prompts.

---

## 2. Data types

```python
from typing import NamedTuple

class ValidationIssue(NamedTuple):
    rule_id:    str   # stable, never renamed; format: "E-<CATEGORY>-<MNEMONIC>" or "W-<...>"
    field:      str   # dot-path to the offending config field, e.g. "assets.battery.fleet_power_mw"
    message:    str   # human-readable sentence (English)
    constraint: str   # numbers shown — e.g. "98.16MW/294.5MWh=0.333C ≤ 0.333C OK"

class ValidationResult(NamedTuple):
    errors:   list[ValidationIssue]   # hard errors — config REJECTED if non-empty
    warnings: list[ValidationIssue]   # soft warnings — proceed with explicit ack

class ConfigValidationError(ValueError):
    """Raised by resolve_site() when ValidationResult.errors is non-empty.

    Attributes:
        errors:   list[ValidationIssue]  (the failing hard-error rules)
        warnings: list[ValidationIssue]  (warnings that also fired; informational)
    """
    errors:   list[ValidationIssue]
    warnings: list[ValidationIssue]
```

`ConfigValidationError` is a subclass of `ValueError` and a sibling of
`DeviceModelError` (both live in `src/energy_go/env/resolver.py`).
`DeviceModelError` continues to fire for schema-level errors (missing model_id,
non-overridable constant conflict) BEFORE `ConfigValidationError` is raised for
semantic/physics errors.

---

## 3. Public API

**File:** `src/energy_go/env/config_validation.py`

```python
from __future__ import annotations
from typing import Any

def validate(
    site_config: dict[str, Any],
    device_models: dict[str, Any] | None = None,
) -> ValidationResult:
    """Validate a parsed site config dict against physics and economics rules.

    Non-raising.  Safe to call from UI pre-check and serving endpoint.

    Args:
        site_config:   Parsed YAML content of site_<name>.yaml as a Python dict.
        device_models: Parsed YAML content of device_models.yaml.  If None,
                       rules that require device physics (E-BAT-CRATE,
                       E-BAT-UNIT, W-BAT-CRATE-2C) are skipped (not errored).

    Returns:
        ValidationResult(errors, warnings).  Both lists may be empty.
    """

def validate_from_paths(
    site_config_path: str | Path,
    device_models_path: str | Path = "config/device_models.yaml",
) -> ValidationResult:
    """Convenience: load YAMLs from disk, then call validate()."""

def resolve_site(
    site_config_path: str | Path,
    device_models_path: str | Path = "config/device_models.yaml",
) -> tuple[EnvParams, int, int]:
    """Existing resolver, extended: calls validate() first, raises on errors.

    Raises:
        ConfigValidationError: if ValidationResult.errors is non-empty.
                               All hard errors are collected before raising
                               (never stops at first error).
        DeviceModelError:      if model_id not found or non-overridable constant
                               violated (fires before ConfigValidationError).
        ValueError:            (existing) tariff table wrong type, missing field.
    """
```

### 3.1 Contract: validation is exhaustive

`validate()` MUST collect ALL failing rules before returning — it never short-circuits
at the first error.  This ensures the UI can display all problems at once.

### 3.2 Contract: non-raising

`validate()` and `validate_from_paths()` MUST NOT raise even on malformed configs.
If a required field is absent (e.g., `assets.battery` missing entirely), the relevant
rules are skipped and the missing-field itself is an E-SCHEMA error (see §4 E-SCHEMA-*).

**Division guard:** rules that compute a ratio (`fleet_power / fleet_capacity` for C-rate;
`fleet_capacity / fleet_power` for duration) MUST skip rather than divide when the
denominator is ≤ 0 or NaN.  Non-positive capacities/powers are already covered by
`E-CAP-POS` — C-rate and duration rules therefore skip and defer.  Implementation MUST
NOT let a ZeroDivisionError escape from `validate()`.

### 3.3 Contract: device_models optional

When `device_models=None`, rules that require device-model physics are silently skipped
(not reported as errors).  This allows partial validation in UI flows where the device
model catalogue has not yet been loaded.

---

## 4. Hard-error rules (ERRORS — config rejected)

All `rule_id` values are **stable** — they are referenced in test assertions and the
serving API; renaming requires a major version bump of this contract.

### E-CAP-POS — Non-positive physical capacity

| field | check | error condition |
|-------|-------|-----------------|
| `assets.wind.fleet_rated_mw` | > 0 | ≤ 0 |
| `assets.solar.fleet_capacity_mw` | > 0 | ≤ 0 |
| `assets.battery.fleet_capacity_mwh` | > 0 | ≤ 0 |
| `assets.battery.fleet_power_mw` | > 0 | ≤ 0 |
| `assets.grid.max_export_mw` (resolved) | > 0 | ≤ 0 |
| `assets.grid.max_import_mw` (resolved) | > 0 | ≤ 0 |

Each failing field produces a separate `ValidationIssue` with `rule_id="E-CAP-POS"`.

**Constraint format example:**  
`"fleet_capacity_mwh = -10.0 MWh — must be > 0"`

**NaN / missing guard:** implementation MUST check `not (x > 0)` (which is True for both
≤ 0 and NaN) rather than `x <= 0` (which would silently pass NaN because `NaN <= 0`
is False in Python/IEEE 754).  Any field where `not (x > 0)` produces an E-CAP-POS
issue with an informative constraint message.

**Gansu:** all capacities positive → no error.

### E-BAT-CRATE — Battery C-rate exceeds device per-unit rating

Requires `device_models` to be provided.

The device per-unit C-rate is the physical maximum the hardware can sustain.
The fleet C-rate MUST NOT exceed the device per-unit C-rate.

```
fleet_crate    = fleet_power_mw / fleet_capacity_mwh
device_crate   = device.physics.power_mw_per_unit / device.physics.capacity_mwh_per_unit
HARD ERROR iff  fleet_crate > device_crate  (no tolerance)
```

**Skip guard:** if `fleet_capacity_mwh ≤ 0` or `not (fleet_capacity_mwh > 0)`, this rule
is **skipped** (E-CAP-POS already covers the non-positive capacity case; dividing would
raise ZeroDivisionError, violating §3.2).

**Constraint format example:**  
`"200.0MW/294.5MWh=0.679C > device limit 100.0MW/300.0MWh=0.333C"`

**Gansu:** 98.16/294.5 = 0.3333C ≤ 100.0/300.0 = 0.3333C → no error.
*(arithmetic: 98.16/294.5 = 0.333311…; 100.0/300.0 = 0.333333…; within floating-point)*

### E-BAT-UNIT — Explicit unit_count inconsistent with fleet sizing

Fires only when `assets.battery.unit_count` is **explicitly** provided in the site YAML.
If absent (the common case), it is derived by `round(fleet_capacity_mwh / capacity_mwh_per_unit)` and this rule does not apply.

Two sub-checks (both fire if failing):

```
energy_check: abs(unit_count * capacity_mwh_per_unit - fleet_capacity_mwh)
              / fleet_capacity_mwh  > 0.01   (1% relative tolerance)

power_check:  abs(unit_count * power_mw_per_unit  - fleet_power_mw)
              / fleet_power_mw      > 0.01   (1% relative tolerance)
```

**Constraint format example:**  
`"unit_count=5, 5×300.0=1500.0MWh ≠ fleet=294.5MWh (>1% tolerance)"`

**Gansu:** no explicit unit_count → rule skipped.

### E-LOAD-SVC — Load unservable at maximum supply

*Gated on `load_peak_mw` field being present in site config* (new optional field
under `load:`; not in site_gansu.yaml v1 — rule is skipped when absent).

```
max_supply = grid.max_import_mw
           + assets.wind.fleet_rated_mw
           + assets.solar.fleet_capacity_mw
           + assets.battery.fleet_power_mw
HARD ERROR iff load_peak_mw > max_supply
```

**Constraint format example:**  
`"peak_load=2000.0MW > max_supply=400+615+330+98.16=1443.16MW"`

**Gansu (without load_peak_mw):** rule skipped.

### E-TAR-SHAPE — Tariff table wrong shape

For `device_model_schema` **v1.x** (flat `(24,)` price table):
```
HARD ERROR iff len(price_table_yuan_per_mwh) != 24
```

For `device_model_schema` **v2.0+** (seasonal or flat — post-PR #87, D33 fix):
```
ACCEPT  flat list of exactly 24 scalars  → resolver.py replicates ×12 internally
ACCEPT  nested list of shape (12, 24)    → seasonal table, passed as-is
HARD ERROR iff neither form is matched
```

The v1/v2 branch is resolved at call-time from `device_model_schema` version
(`"2.0.0"` or higher activates the v2 check).

**Rationale (D33):** `resolver.py` is the single source of truth (D18/D26): the
inline-tariff path accepts a flat `(24,)` list and replicates it ×12 before building
`EnvParams`; it also accepts a seasonal `(12,24)` as a passthrough.  The validator
MUST NOT reject what the resolver accepts; both accept exactly `{flat (24,), (12,24)}`.

**Preferred path for seasonal tariffs:** `tariff_region` (§7, `resolver.py` L192) is
the PREFERRED route for seasonal pricing — it carries demand_rate, sell_clamp, and
currency metadata that inline tables cannot express.  Inline `(12,24)` is a valid
escape hatch (e.g. API callers that have already materialized the matrix) but carries
no metadata side-channel.  If `tariff_region` and an inline `price_table` coexist on
the same site, `tariff_region` wins and the inline table is validated but unused
(pre-existing resolver precedence at L192; noted here so future readers are not confused).

**Parity invariant (binding):** the set of `price_table` shapes accepted by this rule
MUST equal the set that `resolve_site()`'s inline-tariff path accepts without raising.
Any future change to either side MUST update the other in the same PR.
Covered by `test_real_gansu_config_validates_no_tar_shape`.

**Constraint format examples:**  
v1: `"len(price_table)=12 ≠ 24 (expected flat hourly list)"`  
v2: `"shape(price_table)=(11,) — expected flat (24,) or seasonal (12,24)"`

**Gansu:** 24-entry flat list → no error (v1 and v2).

### E-ECON-WACC — WACC outside valid range

*Gated on `finance.wacc_pct` field being present in site config* (post-finance config;
not in site_gansu.yaml v1 — rule is skipped when absent).

```
HARD ERROR iff  not (0.0 < wacc_pct < 30.0)
```

Range `(0, 30)` exclusive: 0% is nonsensical (no time value), 30%+ is extreme
and likely a data-entry error (percentage vs decimal confusion — 25% vs 0.25).

**Constraint format example:**  
`"wacc_pct=35.0 not in (0, 30) — likely entry error (% vs decimal?)"`

### E-ECON-NEG — Negative economics parameter

*Gated on `economics` blocks being present in site or device config.*  
Applies to device-level economics fields that MUST be non-negative:
`capex_per_kw_yuan`, `opex_fixed_per_kw_year_yuan`, `opex_var_per_mwh_yuan`,
`lifetime_years`, `capex_energy_per_kwh_yuan`, `capex_power_per_kw_yuan`,
`opex_fixed_per_kwh_year_yuan`.

```
HARD ERROR iff  any econ field in the above list < 0.0
```

(Note: `residual_value_fraction` may be 0; `decommissioning_cost_*` may be 0.
Negative is the error — zero is legal for fields that represent "none".)

**Constraint format example:**  
`"capex_per_kw_yuan = -100.0 for model 'vestas-v150-4.2' — must be ≥ 0"`

### E-SCHEMA — Required asset section absent (v1.1.0, task #8)

Fires when a required asset category is absent or not a dict under `site.assets`.

**v1 power-composite required set** (rl-architect ruling, task #8; grid added per F1 correction):

| Required | check |
|----------|-------|
| `assets.battery` | present AND is a dict |
| at least one of `assets.wind`, `assets.solar` | ≥ 1 present AND is a dict |
| `assets.grid` | present AND is a dict |

**Battery** is structurally required in v1: the Gansu env's 6-dim action space assumes a
battery (D32(d) scenario composition; a battery-less site is a different composition
with a different action_dim and its own checkpoint namespace).

**Generation** requirement is **at least one of {wind, solar}**, not both — wind-only and
solar-only renewable sites are physically valid.  E-SCHEMA fires when **neither** wind
nor solar is present (no generation source at all).

**Grid** is a direct section check (F1 correction — rl-architect ruling, task #8):
`_resolve_grid_limits()` returns `(None, None)` when `assets.grid` is absent, and
`E-CAP-POS` guards with `if max_export is not None` → **skips** on a missing grid.
A grid-less config therefore passes both E-SCHEMA and E-CAP-POS under the original
ruling — validating clean but breaking at `resolve_site()`.  v1 is a grid-connected
merchant exporter (PCC export/import is the revenue core), so a missing grid section
is as invalid as a missing battery.  The previous "covered by E-CAP-POS" rationale
was factually incorrect and is withdrawn.

**Forward-compat note (D32(d)):** this required-set is the **v1 power-composite**
requirement, not a permanent universal rule.  Future scenario activations (H₂,
aluminium, datacenter) derive their required-sections from the enabled-set; a future
contract amendment will update this rule as scenario support expands.  Jax-env-engineer
should validate the obs/action physics assumptions when that happens.

**HARD ERROR iff:**
```
assets.battery absent or not a dict               → E-SCHEMA on "assets.battery"
(assets.wind absent or not dict)
  AND (assets.solar absent or not dict)            → E-SCHEMA on "assets"
assets.grid absent or not a dict                  → E-SCHEMA on "assets.grid"
```

Each failing check produces a separate `ValidationIssue` with `rule_id="E-SCHEMA"`.

**field values:**
- Missing battery: `"assets.battery"`
- No generation source: `"assets"` (covers the absence of both wind and solar)
- Missing grid: `"assets.grid"`

**Constraint format examples:**
- `"assets.battery absent — battery required for v1 power-composite dispatch"`
- `"assets.wind and assets.solar both absent — at least one generation source required"`
- `"assets.grid absent — grid connection required for v1 power-composite dispatch"`

**Gansu:** battery, wind, solar, and grid all present → no error.

---

## 5. Warning rules (WARNINGS — proceed with explicit ack)

### W-BAT-CRATE-2C — Battery C-rate >2C (LFP chemistry)

LFP batteries degrade rapidly and may have BMS shutdowns above 2C, regardless
of nameplate rating.  The check fires even if E-BAT-CRATE passes.

```
fleet_crate = fleet_power_mw / fleet_capacity_mwh
WARNING iff fleet_crate > 2.0
```

**Skip guard:** if `not (fleet_capacity_mwh > 0)`, this rule is **skipped**
(E-CAP-POS covers the case; dividing would violate §3.2).

**Independence from E-BAT-CRATE:** this warning fires based solely on the 2.0C
absolute threshold — it fires even when E-BAT-CRATE does not fire (i.e., when
fleet C-rate ≤ device C-rate but still > 2.0C, which happens when the device itself
is rated above 2C).

**Constraint format example:**  
`"fleet_power=591.0MW/fleet_capacity=294.5MWh=2.007C > 2.0C LFP advisory"`

**Gansu:** 98.16/294.5 = 0.333C → no warning.

### W-BAT-DUR-10H — Battery storage duration >10 hours

Storage >10 hours (ultra-long duration) is unusual and likely a configuration error
(e.g., MWh vs kWh unit confusion).

```
duration_h = fleet_capacity_mwh / fleet_power_mw
WARNING iff duration_h > 10.0
```

**Skip guard:** if `not (fleet_power_mw > 0)`, this rule is **skipped**
(E-CAP-POS covers the case; dividing would violate §3.2).

**Constraint format example:**  
`"294.5MWh/9.816MW=30.0h > 10h — check units (MWh vs kWh?)"`

**Gansu:** 294.5/98.16 = 3.00h → no warning.

### W-H2-GT-GEN — Electrolyzer fleet exceeds total generation

*Gated on `assets.electrolyzer` being present in site config* (post-§8 electrolyzer;
not in site_gansu.yaml v1 — rule is skipped when absent).

```
total_gen_mw = wind.fleet_rated_mw + solar.fleet_capacity_mw
WARNING iff electrolyzer.fleet_rated_mw > total_gen_mw
```

**Constraint format example:**  
`"electrolyzer=1200MW > wind=615MW+solar=330MW=945MW — persistent grid import likely"`

### W-PCC-CURTAIL — PCC export capacity ≪ installed generation

Severe structural curtailment occurs when the PCC export limit is much less than
total installed generation.

```
total_gen_mw = wind.fleet_rated_mw + solar.fleet_capacity_mw
WARNING iff grid.max_export_mw < 0.20 * total_gen_mw
```

(Threshold 20% of installed gen — below this, the site would curtail >80% at rated
output, making the investment economically incoherent.)

**Constraint format example:**  
`"max_export=100.0MW < 0.20×(615+330)=189.0MW — >80% curtailment at rated output"`

**Gansu:** 945.0 ≥ 0.20 × (615+330) = 189.0 → no warning.

### W-SIZE-TRIVIAL — Site so small training is meaningless

All three generation/storage assets below 1 MW/MWh simultaneously — a configuration
so small that SAC training produces no useful policy.

```
WARNING iff (wind.fleet_rated_mw < 1.0
             AND solar.fleet_capacity_mw < 1.0
             AND battery.fleet_capacity_mwh < 1.0)
```

**Constraint format example:**  
`"wind=0.1MW, solar=0.1MW, bat=0.1MWh — all below 1MW/MWh; training will not converge"`

**Gansu:** wind=615MW → no warning.

---

## 6. Rule table (summary)

| rule_id | tier | gated on | Gansu result |
|---------|------|----------|--------------|
| `E-SCHEMA` | ERROR | — (v1 power-composite required set) | OK |
| `E-CAP-POS` | ERROR | — | OK |
| `E-BAT-CRATE` | ERROR | device_models | OK (0.333C ≤ 0.333C) |
| `E-BAT-UNIT` | ERROR | explicit unit_count | SKIP (not set) |
| `E-LOAD-SVC` | ERROR | load_peak_mw field | SKIP (not set) |
| `E-TAR-SHAPE` | ERROR | — | OK (flat (24,) accepted v1 and v2) |
| `E-ECON-WACC` | ERROR | finance.wacc_pct field | SKIP (not set) |
| `E-ECON-NEG` | ERROR | economics blocks present | OK |
| `W-BAT-CRATE-2C` | WARNING | device_models | OK (0.333C) |
| `W-BAT-DUR-10H` | WARNING | — | OK (3.00h) |
| `W-H2-GT-GEN` | WARNING | assets.electrolyzer | SKIP (not set) |
| `W-PCC-CURTAIL` | WARNING | — | OK (945≥189) |
| `W-SIZE-TRIVIAL` | WARNING | — | OK (615MW) |

---

## 7. Integration with `resolve_site()`

```python
# Pseudocode — actual implementation in src/energy_go/env/resolver.py
def resolve_site(site_config_path, device_models_path="config/device_models.yaml"):
    site   = yaml.safe_load(open(site_config_path))
    models = yaml.safe_load(open(device_models_path))

    # Existing DeviceModelError checks (model_id lookup, non-overridable constants)
    # fire FIRST — config_validation assumes schema is structurally valid.
    _check_device_schema(site, models)   # raises DeviceModelError

    # Config validation — exhaustive (collects all issues)
    result = validate(site, models)
    if result.errors:
        raise ConfigValidationError(errors=result.errors, warnings=result.warnings)

    # Existing resolver logic continues...
    return _build_env_params(site, models)
```

`resolve_site()` continues to return `(EnvParams, obs_dim, action_dim)` unchanged.
The `ConfigValidationError` is a NEW exception type; callers that currently catch
`DeviceModelError` or `ValueError` will NOT automatically catch it (intentional —
callers must explicitly handle the new tier).

---

## 8. REST / serving endpoint

**Owner:** serving-engineer  
**Contract:** `contracts/serving/config_validate.md` (future, task scope serving)

The serving layer exposes:
```
POST /api/site/validate
Body:  { site_config: <dict>, device_models?: <dict> }
Response: { errors: [ValidationIssue], warnings: [ValidationIssue] }
```

**Key guarantee:** the endpoint calls `energy_go.env.config_validation.validate()`
directly — it does NOT re-implement any rules in Python/serving or TypeScript/frontend.
This is the single-source-of-truth requirement from D18.

---

## 9. Sequencing and future extensions

### v1.0.0 (task #66)
Rules implemented: `E-CAP-POS`, `E-BAT-CRATE`, `E-BAT-UNIT`, `E-TAR-SHAPE` (v1),
`E-ECON-NEG` (if economics blocks present), `W-BAT-CRATE-2C`, `W-BAT-DUR-10H`,
`W-PCC-CURTAIL`, `W-SIZE-TRIVIAL`.

Gated/skipped v1.0: `E-SCHEMA` (deferred — "not in v1 scope"),
`E-LOAD-SVC` (needs `load_peak_mw`), `E-TAR-SHAPE` v2 (needs PR #87),
`E-ECON-WACC` (needs `finance.wacc_pct`), `W-H2-GT-GEN` (needs §8 electrolyzer).

### v1.1.0 (task #8) — MINOR, no re-LOCK (activates contracted-but-deferred rule)
Activates `E-SCHEMA`: missing battery or no generation source now emits a hard error.
Observable behavior change from v1.0.0: configs lacking `assets.battery` or lacking
both `assets.wind` and `assets.solar` were previously accepted (silently skipped);
under v1.1.0 they produce `E-SCHEMA` errors.  Version bumped to signal this shift to
consumers (rl-architect ruling, task #8).  No re-LOCK — activating a gated rule is
minor per the config_validation LOCK policy.

### Post-PR #87 (device_model_schema v2.0.0) + D33 fix
`E-TAR-SHAPE` under v2.0+ accepts **flat `(24,)` OR seasonal `(12,24)`**.
A flat `(24,)` list is the on-disk backward-compatible form; `resolver.py` replicates
it ×12 to `(12,24)` before building `EnvParams` (D18/D26 single-validator rule).
Implementation is version-gated:
```python
if device_model_schema_version >= (2, 0, 0):
    # Accept flat (24,) OR nested (12,24) — resolver broadcasts the flat form ×12.
    flat_ok     = isinstance(price_table, list) and len(price_table) == 24
                  and not any(isinstance(row, list) for row in price_table)
    seasonal_ok = (isinstance(price_table, list) and len(price_table) == 12
                   and all(isinstance(row, list) and len(row) == 24 for row in price_table))
    if not (flat_ok or seasonal_ok):
        # ERROR
else:
    if len(price_table) != 24:
        # ERROR
```

### Post-tariff_model_schema (task #58 Step B)
Tariff validation composes with the typed `TariffConfig`; `E-TAR-SHAPE` can delegate
to the tariff schema validator.

### Post-§8 electrolyzer
`W-H2-GT-GEN` activates when `assets.electrolyzer` key is present.

### Post-finance config
`E-ECON-WACC` activates when `finance.wacc_pct` key is present.

---

## 10. Deliberate deviations from current code

1. `resolve_site()` currently raises `DeviceModelError` or bare `ValueError` for
   all config problems.  This contract introduces `ConfigValidationError` as a
   NEW exception type, distinct from `DeviceModelError`.  Callers must be updated.

2. Current `resolver.py` raises on the FIRST error (e.g., first bad tariff entry).
   This contract mandates **exhaustive collection** — all errors reported before raise.

3. No TypeScript/serving rule duplication: the frontend currently has no validation
   logic, so this is not a breaking change.  Serving's `POST /api/site/validate` endpoint
   is a NEW endpoint (additive).

---

## 11. Out of scope

- Runtime physics validation (NaN detection, SOC clamps) — that is `D26` territory.
- Reward-shaping parameter validation (VOLL, c_deg, etc.) — design choices, not errors.
- Cross-site consistency (e.g., two sites with conflicting grid IDs) — future.
- YAML syntax errors — callers handle YAML parse failures before calling `validate()`.

### 11.1 Coordination note: passing-state confirmations (frontend-reviewer advisory)

`validate()` emits only errors and warnings — **a passing rule emits nothing**.
The wizard's per-field OK badges ("0.33 C — OK (limit 0.33 C)") therefore require a
second data source: `POST /api/site/resolve` returning derived diagnostics (fleet
C-rate, storage duration, PCC coverage ratio, unit counts, etc.) alongside `EnvParams`.
This contract does NOT provide those positives; the serving `resolve` endpoint owns them.

**Contract boundary:** `validate()` is the rejection oracle; `resolve()` is the
positive-state oracle.  The UI calls both — `validate` for red/amber, `resolve` for
green badges.  The serving contract for `POST /api/site/resolve` MUST include these
derived diagnostics (see `contracts/serving/site_resolve.md`, to be authored by
serving-engineer after this contract locks).

### 11.2 (rule_id, field) uniqueness within a ValidationResult

Within a single `ValidationResult`, the pair `(rule_id, field)` is **not** guaranteed
unique — the same rule may fire on multiple fields (e.g., `E-CAP-POS` firing on both
`assets.battery.fleet_capacity_mwh` and `assets.wind.fleet_rated_mw`).  The UI keys
per-warning acknowledgement on `rule_id` alone (one ack dismisses all issues with that
`rule_id`).  For field-level highlighting, the UI iterates `errors`/`warnings` and
highlights every dot-path in `field`.

**For v1** (one device model per type): `(rule_id, field)` is unique within a rule's
firing for a given field path.  When the site schema gains device lists (§8 composition
panel), `field` must encode the device index or ID (e.g.,
`"assets.batteries[0].fleet_power_mw"`) — noted as a forward-compat constraint.

---

## 12. Implementation checklist (for QA)

- [ ] `E-SCHEMA` fires when `assets.battery` absent/non-dict (one issue)
- [ ] `E-SCHEMA` fires when both `assets.wind` and `assets.solar` absent/non-dict (one issue)
- [ ] `E-SCHEMA` fires when `assets.grid` absent/non-dict (one issue)
- [ ] `E-SCHEMA` does NOT fire when battery + grid present + at least one of wind/solar present
- [ ] `ValidationIssue`, `ValidationResult`, `ConfigValidationError` defined as specified
- [ ] `validate()` non-raising on all test inputs including malformed dicts
- [ ] All rules exhaustive (no early exit)
- [ ] `resolve_site()` calls `validate()` and raises `ConfigValidationError` on errors
- [ ] `validate(gansu_config, gansu_device_models)` → `errors=[], warnings=[]`
- [ ] Each rule tested with a hand-crafted invalid/borderline config (see test file)
- [ ] `device_models=None` → device-dependent rules silently skipped, not errored
- [ ] Stable `rule_id` strings present in all `ValidationIssue` instances
- [ ] E-CAP-POS uses `not (x > 0)` — catches both ≤ 0 and NaN (IEEE 754 safe)
- [ ] E-BAT-CRATE skips (not errors) when fleet_capacity_mwh ≤ 0 or NaN
- [ ] W-BAT-CRATE-2C skips when fleet_capacity_mwh ≤ 0 or NaN
- [ ] W-BAT-DUR-10H skips when fleet_power_mw ≤ 0 or NaN
- [ ] No ZeroDivisionError escapes from `validate()` under any input
