# Tariff Model Schema — shared contract

**Area:** shared  
**Contract path:** `contracts/shared/tariff_model_schema.md`  
**Schema file:** `config/tariff_model_schema.yaml`  
**Test file:** `tests/shared/test_shared_tariff_model_schema.py`  
**Spec sections:** §3.4 (costs), §3.7 (Gansu 4-tier TOU), §3 constraint table row 10 (no negative sell price)  
**Decisions:** D3 (Δt=1h, minute=0 convention), D7 (spread clamp ≥ 0), D8 (minute-accurate tariff lookup), D31/F1 (constant-real-price dispatch default)  
**Plan:** `docs/design/master_plan_geo_finance.md` §5.7 (Workstream A step B, tariff library)  
**Owner:** jax-env-engineer  
**Version:** v1.0.0  
**Related locked contracts:**  
- `contracts/shared/device_model_schema.md` v2.0.0 (PR #87 — `price_table` reshaped (24,)→(12,24); this schema is Step B of that same task-#58 workstream)  
- `contracts/shared/config_validation.md` v1.0.0 (LOCKED — `E-TAR-SHAPE` v2 upgrades when this contract lands; see §8)  
- Private-overlay mechanism: same as device models (PR #68 ruling) — tariff entries are overlayable via `ENERGY_GO_PRIVATE_CONFIG`; public config carries only public data + provisional stubs. Reference the PR #68 ruling; do not re-spec here.

---

## Overview

This contract defines the **tariff library** — a `config/tariff_model_schema.yaml` file keyed by
region ID (`cn-gansu`, `cn-guangdong`, …). Each region entry carries:

- A **(12, 24) month × hour** buy-price table (¥/MWh, float32), replacing the flat `(24,)` table
  that `device_model_schema.md` v2.0.0 established.
- Demand rate (¥/MW·month), matching the existing `EnvParams.demand_rate_yuan_per_mw_month`.
- D7 sell-clamp parameters (spread, spread noise σ), matching
  `EnvParams.price_spread_yuan_per_mwh` / `price_spread_sigma`.
- Currency code (display-layer only; the env stays ¥-pure internally).

The **region ID is the A↔B join key**: the site YAML gains an optional `tariff_region` field;
the resolver sources tariff parameters from the matching region entry. When `tariff_region` is
absent, the resolver falls back to the inline `tariff.price_table_yuan_per_mwh` block in the site
YAML (backward-compatible with all existing callers).

**cn-gansu initial entry**: the current Gansu 24-vector **replicated ×12** (all months identical).
This is bit-parity with the merged `device_model_schema` v2.0.0 baseline. Real seasonal provincial
data lands later as data-only changes (no contract amendment needed, only hand-computed cost tests
per the project rule).

---

## 1. Schema file location

`config/tariff_model_schema.yaml`

Loaded at Python startup by the resolver (`src/energy_go/env/resolver.py`). Never inside jit.
Changes to the YAML content are data changes; changes to the key-set or field structure are
schema-version bumps requiring a new contract.

---

## 2. YAML schema structure

```yaml
schema_version: "1.0.0"
regions:
  <region_id>:                            # e.g. "cn-gansu", "cn-guangdong"
    currency: <ISO-4217 string>           # e.g. "CNY" — display only, env stays ¥-pure
    price_table_yuan_per_mwh:             # shape (12, 24) — row = month (0=Jan … 11=Dec),
      - [<h0>, <h1>, …, <h23>]           #  column = hour of day (0–23, at Δt=1h steps on :00)
      - …                                 # 12 rows total
    demand_rate_yuan_per_mw_month: <f>    # ¥/MW·month (= ¥/kW·month × 1000)
    sell_clamp:                           # D7 parameters
      spread_yuan_per_mwh:     <f>        # mean buy-sell spread (¥/MWh), ≥ 0 by convention
      spread_noise_std_yuan_per_mwh: <f>  # σ for spread noise draw (¥/MWh), ≥ 0
```

### 2.1 Field types and units

| Field | Type | Unit | Valid range | Notes |
|---|---|---|---|---|
| `schema_version` | string | — | `"1.0.0"` | Presence-only check in tests; equality check in validators |
| `currency` | string | ISO-4217 | non-empty | Display only; env arithmetic is always ¥-internal |
| `price_table_yuan_per_mwh` | list[list[float]] | ¥/MWh | shape (12, 24); values ≥ 0 by convention | **Hard error E-TARIFF-SHAPE if shape ≠ (12, 24)** |
| `demand_rate_yuan_per_mw_month` | float | ¥/MW·month | ≥ 0 (**E-TARIFF-DEMAND hard error if < 0**) | Maps directly to `EnvParams.demand_rate_yuan_per_mw_month`; 0.0 valid for no-demand-charge sites |
| `spread_yuan_per_mwh` | float | ¥/MWh | ≥ 0 | D7: `eff_spread = max(0, spread + N(0, σ))` |
| `spread_noise_std_yuan_per_mwh` | float | ¥/MWh | ≥ 0 | D7 σ; 0.0 = deterministic spread |

### 2.2 Loader API

```python
from energy_go.env.tariff_model_schema import (
    load_tariff_schema, TariffRegion, SellClamp,
    validate_tariff_region, ValidationIssue, ValidationResult,
)

schema: dict = load_tariff_schema(path)
# schema["schema_version"]  → str
# schema["regions"]         → dict[str, TariffRegion]

region: TariffRegion = schema["regions"]["cn-gansu"]
# region.currency                                      → str
# region.price_table_yuan_per_mwh                      → np.ndarray shape (12, 24) float32
# region.demand_rate_yuan_per_mw_month                 → float
# region.sell_clamp.spread_yuan_per_mwh                → float
# region.sell_clamp.spread_noise_std_yuan_per_mwh      → float
# region.provenance                                    → "public" | "private"
#                                                        (runtime-injected by resolver; not in YAML)

result: ValidationResult = validate_tariff_region(region_dict)
# result.errors   → list[ValidationIssue]  — hard errors (E-* rules; block env startup)
# result.warnings → list[ValidationIssue]  — soft warnings (W-* rules; operator review)
# ValidationIssue: NamedTuple(rule_id: str, field: str, message: str, constraint: str)
# Note: ValidationIssue has NO 'severity' field — severity is implicit
#       (errors list = hard, warnings list = soft).  See config_validation.md §2.
```

`TariffRegion` and `SellClamp` are NamedTuple or dataclass; NamedTuple preferred for pytree
compatibility when passed downstream.

---

## 3. cn-gansu initial entry

All 12 rows are identical to the existing Gansu 24-vector (D8, Δt=1h, minute=0 for all steps):

```
[250, 250, 250, 250, 250, 250, 250,   # h=0–6   Valley      (23:00–07:00)
 450,                                  # h=7     Mid         (07:00–08:00)
 620, 620, 620,                        # h=8–10  Peak        (08:00–10:30, 10:00 on :00)
 780,                                  # h=11    Critical pk (10:30–11:30, 11:00 on :00)
 450, 450, 450, 450, 450, 450,         # h=12–17 Mid         (11:30–18:00)
 620,                                  # h=18    Peak        (18:00–19:00)
 780, 780,                             # h=19–20 Critical pk (19:00–21:00)
 620, 620,                             # h=21–22 Peak        (21:00–23:00)
 250]                                  # h=23    Valley
```

Arithmetic check (D8 note): at Δt=1h each step fires at minute=0. Hour 10 → 10:00 < 10:30 →
**peak (620)**. Hour 11 → 11:00 < 11:30 (still in critical-peak window) → **780**.

```
demand_rate_yuan_per_mw_month: 32000.0   # §3.7: "32 000 ¥/MW·month"
sell_clamp:
  spread_yuan_per_mwh:              30.0  # D7 baseline
  spread_noise_std_yuan_per_mwh:    10.0  # D7 σ
currency: "CNY"
```

**Bit-parity guarantee:** `region.price_table_yuan_per_mwh[m]` == GANSU_ROW for all m ∈ 0..11,
where GANSU_ROW is the 24-vector above. Tests assert this bit-exactly (float32 equality, no
tolerance).

---

## 4. Site config integration

### 4.1 Site YAML (optional field)

```yaml
# site_gansu.yaml — new optional field
tariff_region: "cn-gansu"   # if absent → resolver falls back to inline tariff block
```

Backward-compatible: existing site YAMLs without `tariff_region` continue to work unchanged
(resolver reads `tariff.price_table_yuan_per_mwh` inline exactly as today).

### 4.2 Resolver precedence

```
if site_config.get("tariff_region"):
    region = tariff_schema["regions"][site_config["tariff_region"]]
    price_table  = region.price_table_yuan_per_mwh          # (12, 24)
    demand_rate  = region.demand_rate_yuan_per_mw_month
    spread       = region.sell_clamp.spread_yuan_per_mwh
    spread_sigma = region.sell_clamp.spread_noise_std_yuan_per_mwh
else:
    # inline fallback (backward-compat)
    price_table = site_config["tariff"]["price_table_yuan_per_mwh"]  # (12,24) or (24,) → replicate
    demand_rate  = site_config["costs"]["demand_rate_yuan_per_mw_month"]
    spread       = site_config["costs"]["price_spread_yuan_per_mwh"]
    spread_sigma = site_config["costs"]["price_spread_sigma"]
```

The resolver always produces a `(12, 24)` ndarray for `EnvParams.price_table`. When the inline
fallback receives a legacy `(24,)` input it replicates × 12 (same logic as PR #87 resolver).

### 4.3 Missing region key

If `tariff_region` is set but the key is absent from `tariff_model_schema.yaml`, the resolver
raises `ConfigValidationError` (not a silent fallback) — E-TARIFF-REGION rule in config_validation.

**Test placement note:** E-TARIFF-REGION (missing region key) and backward-compatible inline-fallback
tests (absent `tariff_region` → inline site YAML) belong in `tests/env/test_env_resolver.py`
(owned by the serving/env integration layer), not in this file. This file tests the schema
validator (`validate_tariff_region`) only.

---

## 5. Validation rules

These rules are defined here and registered in `contracts/shared/config_validation.md` §4/§5
(step B amendment, post-lock, requires config_validation minor-bump to v1.1.0 for the new rules).

### E-TARIFF-SHAPE (upgrade of E-TAR-SHAPE v2)

```
HARD ERROR iff shape(price_table_yuan_per_mwh) != (12, 24)
rule_id: "E-TARIFF-SHAPE"
field:   "tariff.price_table_yuan_per_mwh" (inline) or region entry
```

Replaces E-TAR-SHAPE v2 once this contract is locked. config_validation's E-TAR-SHAPE
implementation delegates to `validate_tariff_region()` for the (12, 24) check.

### W-TARIFF-PRICE-NEG

```
WARNING iff any(price_table_yuan_per_mwh[m][h] < 0)
rule_id: "W-TARIFF-PRICE-NEG"
field:   "price_table_yuan_per_mwh"
```

Non-blocking warning: negative prices can occur in real electricity markets but are unexpected
in Chinese TOU tariffs.  
Message template: `"W-TARIFF-PRICE-NEG: price_table[{m}][{h}]={v:.1f} < 0 (unusual for CN market)"`

### W-TARIFF-SPREAD-NEG

```
WARNING iff spread_yuan_per_mwh < 0 OR spread_noise_std_yuan_per_mwh < 0
rule_id: "W-TARIFF-SPREAD-NEG"
field:   "sell_clamp.spread_yuan_per_mwh" | "sell_clamp.spread_noise_std_yuan_per_mwh"
```

Negative spread → sell price > buy price by default (risk-free arbitrage — D7 was designed to
prevent this). Negative σ is mathematically incoherent.

### W-TARIFF-CURRENCY-UNKNOWN

```
WARNING iff currency != "CNY"
rule_id: "W-TARIFF-CURRENCY-UNKNOWN"
field:   "currency"
```

The env is ¥-pure internally; all arithmetic uses ¥ regardless of the currency field. A non-CNY
currency code is unusual and likely an operator data-entry error (e.g. copy-pasted from a
foreign tariff file). Soft warning only — it does not affect env arithmetic.  
Message template: `"W-TARIFF-CURRENCY-UNKNOWN: currency='{v}'; env is ¥-pure, only 'CNY' is recognised"`

### E-TARIFF-DEMAND

```
HARD ERROR iff demand_rate_yuan_per_mw_month < 0
rule_id: "E-TARIFF-DEMAND"
field:   "demand_rate_yuan_per_mw_month"
```

A negative demand charge rate (¥/MW·month fixed fee) is **commercially impossible** — no utility
charges a negative fixed fee for peak demand. This is a hard error: unlike negative spot/spread
prices (which genuinely occur in oversupply markets and warrant only a warning), a negative
demand rate has no physically or commercially valid interpretation in the CN tariff context.

Two-tier rationale (rl-architect ruling): impossible = hard error; suspicious-but-legal = warning.
`0.0` is valid (no demand charge, common for smaller sites) — rule is strictly `< 0`.  
Message template: `"E-TARIFF-DEMAND: demand_rate={v:.1f} < 0 (commercially impossible for CN demand charge)"`

### E-TARIFF-REGION (resolver error, not schema-file error)

```
HARD ERROR iff site_config["tariff_region"] set but key absent from tariff_schema["regions"]
rule_id: "E-TARIFF-REGION"
field:   "tariff_region"
```

Raised at resolver time (ConfigValidationError). Not fired when `tariff_region` is absent (inline
fallback path).

---

## 6. Relation to config_validation (LOCKED v1.0.0)

The LOCKED `config_validation.md` §9 (Post-tariff_model_schema, Step B) specifies:

> "Tariff validation composes with the typed TariffConfig; E-TAR-SHAPE can delegate to the tariff
> schema validator."

Operationalizing this: when `tariff_model_schema` is locked, a minor-version amendment to
`config_validation` (v1.1.0) will:
1. Register E-TARIFF-SHAPE as the canonical name, replacing the E-TAR-SHAPE v2 placeholder.
2. Add W-TARIFF-PRICE-NEG and W-TARIFF-SPREAD-NEG to the validation registry.
3. Add E-TARIFF-REGION.

**That amendment is out of scope for this contract** — it is authored by config_validation's
owner when this contract is locked.

---

## 7. Consumer notes

### 7.1 Frontend — TOU-band display (server-side derivation required)

frontend-reviewer flagged (PR #91 advisory, finding #1): TOU band boundaries **must be derived
server-side** and served as structured data. The dashboard must NOT reconstruct band boundaries
client-side from price-table deltas (single-source-of-truth rule).

**`TariffBand` shape** (Python-side; serialised to JSON for the REST endpoint):

```python
class TariffBand(NamedTuple):
    name: str               # e.g. "valley", "mid", "peak", "critical_peak"
    start_hour: int         # inclusive, 0–23
    end_hour: int           # exclusive, 1–24
    price_yuan_per_mwh: float
```

**REST endpoint** (owned by serving-engineer; out of scope for this contract):

```
GET /api/config/tariff/<region_id>?month=<0-11>
→ { "region_id": str, "month": int, "bands": [TariffBand, ...] }
```

**Derivation algorithm**: run-length encoding of `price_table_yuan_per_mwh[month]` — each
contiguous run of equal prices becomes one `TariffBand`. Band name lookup from price value
(Gansu initial: 250 → "valley", 450 → "mid", 620 → "peak", 780 → "critical_peak").
Implementation lives in `serving/tariff_bands.py` (future serving-layer PR).

The dashboard's **existing hardcoded band boundaries** (10:30, 11:30, etc.) must be replaced
with data from this endpoint once it is live.

The TariffBand type and endpoint contract are out of scope for this contract (owned by
serving-engineer); this section documents the requirement so implementation is ready at
integration time.

### 7.2 Provenance and private-overlay mechanism

**Provenance field:** `TariffRegion.provenance` is a string literal `"public"` or `"private"`,
set by the resolver at load time — it is NOT stored in the YAML file:

- `"public"`: sourced from `config/tariff_model_schema.yaml` (checked-in; public data).
- `"private"`: sourced from the `ENERGY_GO_PRIVATE_CONFIG` overlay (gitignored; proprietary
  customer or seasonal tariffs).

The resolver injects `provenance` after loading; YAML entries never contain a `provenance` key.

Tariff entries are overlayable via `ENERGY_GO_PRIVATE_CONFIG` using the same mechanism as device
models (PR #68 ruling). Public `config/tariff_model_schema.yaml` carries only public data
(cn-gansu replicated-×12 baseline). Provincial seasonal data and proprietary customer tariffs
live in the gitignored private overlay. This contract does not re-specify the overlay mechanism —
reference PR #68.

---

## 8. Deliberate deviations from spec

| Item | Spec / old behaviour | New behaviour | Reason |
|---|---|---|---|
| `price_table` shape | §3.7 implicit (24,) flat table | (12, 24) month×hour | PR #87 shape change; this contract provides the data file |
| D7 clamp location | Implemented in `jax_env.py` step function | Parameters sourced from schema `sell_clamp` block | Explicit parameterisation; semantics unchanged |
| cn-gansu initial data | 24-vector from site YAML | 12 identical rows in tariff_model_schema.yaml | Same numeric content; backward-parity enforced by test |

---

## 9. Out of scope (v1.0.0)

- Real seasonal provincial price data for cn-gansu (deferred; arrives as data-only YAML edits).
- cn-guangdong, cn-xinjiang or other region entries (deferred; added when data is available).
- Feed-in tariffs (wind 290, solar 260, storage 350 ¥/MWh) — these are fixed constants in §3.7
  used only when spread mode is off; they are not part of the TOU table and are not parameterised
  in this schema.
- Sub-hourly tariff resolution — D3 fixes Δt=1h; the (12, 24) table is the correct resolution.
- TariffBand endpoint implementation — documented in §7.1 as a requirement; contract and
  implementation owned by serving-engineer at integration time.
- Multi-currency arithmetic in the env — env stays ¥-pure; currency field is display metadata.
- Tariff escalation (year-on-year price changes) — D31/F1 uses constant-real-price dispatch;
  escalation is applied post-hoc in the finance layer.

---

## 10. Checklist for reviewers

- [ ] cn-gansu 24-vector values match §3.7 + D8 minute=0 convention (especially h=10 peak vs h=11 critical-peak boundary)
- [ ] (12, 24) shape correct for month×hour semantics (row = month, col = hour)
- [ ] `demand_rate` units ¥/MW·month (not ¥/kW·month) matching `EnvParams` field; 0.0 valid (no demand charge); E-TARIFF-DEMAND hard error fires at < 0
- [ ] D7 sell_clamp parameters sourced correctly (spread=30, σ=10 from LINEAGE D7)
- [ ] E-TARIFF-SHAPE is HARD ERROR (in `result.errors`; NOT in `result.warnings`)
- [ ] W-TARIFF-PRICE-NEG is WARNING (in `result.warnings`; NOT in `result.errors`)
- [ ] W-TARIFF-SPREAD-NEG is WARNING (fires for spread < 0 OR σ < 0; 0.0 is valid for both)
- [ ] W-TARIFF-CURRENCY-UNKNOWN is WARNING (fires for currency != "CNY")
- [ ] E-TARIFF-DEMAND is HARD ERROR (fires for demand_rate < 0; in `result.errors`, NOT `result.warnings`; 0.0 valid)
- [ ] `validate_tariff_region()` returns `ValidationResult` (not bare list); `ValidationIssue` has {rule_id, field, message, constraint} — NO severity field
- [ ] `TariffRegion.provenance` field documented; resolver injects at load time; NOT in YAML
- [ ] TariffBand server-side endpoint requirement documented in §7.1 (no client-side reconstruction)
- [ ] Backward-compat fallback (absent `tariff_region` → inline site YAML)
- [ ] E-TARIFF-REGION (missing region key) raises ConfigValidationError; resolver tests in `tests/env/test_env_resolver.py`
- [ ] Private overlay referenced but not re-spec'd (PR #68 authority)
