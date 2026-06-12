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
| `demand_rate_yuan_per_mw_month` | float | ¥/MW·month | > 0 | Maps directly to `EnvParams.demand_rate_yuan_per_mw_month` |
| `spread_yuan_per_mwh` | float | ¥/MWh | ≥ 0 | D7: `eff_spread = max(0, spread + N(0, σ))` |
| `spread_noise_std_yuan_per_mwh` | float | ¥/MWh | ≥ 0 | D7 σ; 0.0 = deterministic spread |

### 2.2 Loader API

```python
from energy_go.env.tariff_model_schema import load_tariff_schema, TariffRegion

schema: dict = load_tariff_schema(path)
# schema["schema_version"]  → str
# schema["regions"]         → dict[str, TariffRegion]

region: TariffRegion = schema["regions"]["cn-gansu"]
# region.currency                        → str
# region.price_table_yuan_per_mwh        → np.ndarray shape (12, 24) float32
# region.demand_rate_yuan_per_mw_month   → float
# region.sell_clamp.spread_yuan_per_mwh                → float
# region.sell_clamp.spread_noise_std_yuan_per_mwh      → float
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

### 7.1 Frontend — TOU-band display (Step-B flag)

frontend-reviewer flagged (PR #89 advisory, §11.2): the dashboard TOU-band display must become
**month-aware** once the (12, 24) table is live. Band boundaries can vary month-to-month in
seasonal tariff data.

- The serving layer must expose the full `(12, 24)` table in the telemetry `env_config` frame
  (or a `/api/config/tariff/<region_id>` endpoint) so the dashboard can render the correct
  band for the simulated month.
- The exact telemetry-schema amendment for this field is out of scope for this contract; it is
  owned by the serving-engineer at the time of integration.

### 7.2 Private-overlay mechanism

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
- Time-of-use band metadata (band names, band boundary hours) as explicit fields — derived by
  the display layer from the price table itself.
- Multi-currency arithmetic in the env — env stays ¥-pure; currency field is display metadata.
- Tariff escalation (year-on-year price changes) — D31/F1 uses constant-real-price dispatch;
  escalation is applied post-hoc in the finance layer.

---

## 10. Checklist for reviewers

- [ ] cn-gansu 24-vector values match §3.7 + D8 minute=0 convention (especially h=10 peak vs h=11 critical-peak boundary)
- [ ] (12, 24) shape correct for month×hour semantics (row = month, col = hour)
- [ ] `demand_rate` units ¥/MW·month (not ¥/kW·month) matching `EnvParams` field
- [ ] D7 sell_clamp parameters sourced correctly (spread=30, σ=10 from LINEAGE D7)
- [ ] E-TARIFF-SHAPE is HARD ERROR (not warning)
- [ ] W-TARIFF-PRICE-NEG is WARNING (not hard error — negative prices exist in real markets)
- [ ] Backward-compat fallback (absent `tariff_region` → inline site YAML)
- [ ] E-TARIFF-REGION (missing region key) raises ConfigValidationError
- [ ] Private overlay referenced but not re-spec'd (PR #68 authority)
- [ ] Frontend TOU-band step-B flag documented in consumer notes (§7.1)
